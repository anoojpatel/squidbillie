import numpy as np
import sounddevice as sd

from squidbilli.dsp import LaneDSP
from squidbilli.synth import SynthRack

try:
    from pedalboard import Compressor, Delay, Pedalboard, Reverb

    HAS_PEDALBOARD = True
except ImportError:
    print("Warning: Pedalboard not found. FX will be disabled.")
    HAS_PEDALBOARD = False


class AudioEngine:
    def __init__(self, transport_a, transport_b, mixer_state, stem_manager_a, stem_manager_b):
        self.transport_a = transport_a
        self.transport_b = transport_b
        self.mixer_state = mixer_state
        self.stem_manager_a = stem_manager_a
        self.stem_manager_b = stem_manager_b

        self.block_size = 2048
        self.sample_rate = 44100
        self.latency = "high"

        self.stream = None

        self._xrun_count = 0
        self._last_status_print = 0.0

        self.lane_dsp_a = [LaneDSP(self.sample_rate) for _ in range(8)]
        self.lane_dsp_b = [LaneDSP(self.sample_rate) for _ in range(8)]

        # Scratch buffers to reduce per-callback allocations.
        self._scratch_deck_a = np.zeros((self.block_size, 2), dtype=np.float32)
        self._scratch_deck_b = np.zeros((self.block_size, 2), dtype=np.float32)
        self._scratch_rev = np.zeros((self.block_size, 2), dtype=np.float32)
        self._scratch_dly = np.zeros((self.block_size, 2), dtype=np.float32)
        self._scratch_stems = np.zeros((self.block_size, 2), dtype=np.float32)

        self.synth = SynthRack(sr=self.sample_rate, lanes=2)

        if HAS_PEDALBOARD:
            self.reverb = Pedalboard([Reverb(room_size=0.8, wet_level=1.0, dry_level=0.0)])
            self.delay = Pedalboard([Delay(delay_seconds=0.375, feedback=0.4, mix=1.0)])
            self.master_limiter = Pedalboard(
                [Compressor(threshold_db=-1.0, ratio=4.0, attack_ms=1.0, release_ms=100.0)]
            )
        else:
            self.reverb = None
            self.delay = None
            self.master_limiter = None

    def start(self):
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=2,
                dtype="float32",
                latency=self.latency,
                callback=self.audio_callback,
            )
            self.stream.start()
            print("Audio engine started.")
        except Exception as e:
            print(f"Failed to start audio engine: {e}")

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

    def audio_callback(self, outdata, frames, time_info, status):
        if status:
            self._xrun_count += 1
            # Avoid printing every callback (can itself cause xruns).
            try:
                t = float(time_info.get("current_time", 0.0))
            except Exception:
                t = 0.0
            if t - self._last_status_print > 1.0:
                self._last_status_print = t
                try:
                    print(f"Audio status: {status} (xruns={self._xrun_count})")
                except Exception:
                    pass

        if not self.transport_a.playing and not self.transport_b.playing:
            outdata[:] = 0.0
            return

        state = self.mixer_state.get_mix_snapshot()
        deck_x = float(state.get("deck_crossfade", 0.0))
        stem_blend = float(state.get("stem_blend", 1.0))
        master_gain = state["master_gain"]

        clip_only_a = bool(state.get("clip_only_a", False))
        clip_only_b = bool(state.get("clip_only_b", False))

        deck_x = max(0.0, min(1.0, deck_x))
        stem_blend = max(0.0, min(1.0, stem_blend))

        # Equal-power crossfade between decks.
        # x=0 => all A, x=1 => all B
        ga = float(np.cos(deck_x * np.pi * 0.5))
        gb = float(np.sin(deck_x * np.pi * 0.5))

        if frames == self.block_size:
            deck_a = self._scratch_deck_a
            deck_b = self._scratch_deck_b
            deck_a[:] = 0.0
            deck_b[:] = 0.0
        else:
            deck_a = np.zeros((frames, 2), dtype=np.float32)
            deck_b = np.zeros((frames, 2), dtype=np.float32)

        stop_a_at_end = False
        if self.transport_a.playing:
            current_pos_a = int(self.transport_a.play_head_samples)
            try:
                track_len_a = int(self.stem_manager_a.full_mix.shape[0]) if self.stem_manager_a.full_mix is not None else 0
            except Exception:
                track_len_a = 0
            if (not self.transport_a.looping) and track_len_a > 0 and current_pos_a >= track_len_a:
                self.transport_a.seek(track_len_a)
                self.transport_a.stop()
                current_pos_a = track_len_a
            if (not self.transport_a.looping) and track_len_a > 0 and (current_pos_a + frames) >= track_len_a:
                stop_a_at_end = True
            mix_chunk_a, lanes_chunk_a = self.stem_manager_a.get_frame(current_pos_a, frames, clip_only=clip_only_a)

            if frames == self.block_size:
                stems_sum = self._scratch_stems
                send_reverb_sum = self._scratch_rev
                send_delay_sum = self._scratch_dly
                stems_sum[:] = 0.0
                send_reverb_sum[:] = 0.0
                send_delay_sum[:] = 0.0
            else:
                stems_sum = np.zeros_like(mix_chunk_a)
                send_reverb_sum = np.zeros((frames, 2), dtype=np.float32)
                send_delay_sum = np.zeros((frames, 2), dtype=np.float32)

            if self.stem_manager_a.stems_ready:
                for i in range(8):
                    l_cfg = state.get("lanes_a", state.get("lanes", []))[i]
                    lane_audio = lanes_chunk_a[i]

                    lane_audio = self.lane_dsp_a[i].process(lane_audio, l_cfg["hp"], l_cfg["lp"])

                    gain = l_cfg["gain"]
                    pan = l_cfg["pan"]
                    lane_audio *= gain

                    if pan != 0.0:
                        left_gain = min(1.0, 1.0 - pan)
                        right_gain = min(1.0, 1.0 + pan)
                        lane_audio[:, 0] *= left_gain
                        lane_audio[:, 1] *= right_gain

                    if HAS_PEDALBOARD:
                        if l_cfg["reverb"] > 0.0:
                            send_reverb_sum += lane_audio * l_cfg["reverb"]
                        if l_cfg["delay"] > 0.0:
                            send_delay_sum += lane_audio * l_cfg["delay"]

                    stems_sum += lane_audio

            if HAS_PEDALBOARD:
                if self.reverb:
                    rev_out = self.reverb(send_reverb_sum, self.sample_rate)
                    stems_sum += rev_out
                if self.delay:
                    del_out = self.delay(send_delay_sum, self.sample_rate)
                    stems_sum += del_out

            deck_a = mix_chunk_a * (1.0 - stem_blend) + stems_sum * stem_blend

        stop_b_at_end = False
        if self.transport_b.playing:
            current_pos_b = int(self.transport_b.play_head_samples)
            try:
                track_len_b = int(self.stem_manager_b.full_mix.shape[0]) if self.stem_manager_b.full_mix is not None else 0
            except Exception:
                track_len_b = 0
            if (not self.transport_b.looping) and track_len_b > 0 and current_pos_b >= track_len_b:
                self.transport_b.seek(track_len_b)
                self.transport_b.stop()
                current_pos_b = track_len_b
            if (not self.transport_b.looping) and track_len_b > 0 and (current_pos_b + frames) >= track_len_b:
                stop_b_at_end = True
            mix_chunk_b, lanes_chunk_b = self.stem_manager_b.get_frame(current_pos_b, frames, clip_only=clip_only_b)

            if frames == self.block_size:
                stems_sum_b = self._scratch_deck_b
                send_reverb_sum_b = self._scratch_rev
                send_delay_sum_b = self._scratch_dly
                stems_sum_b[:] = 0.0
                send_reverb_sum_b[:] = 0.0
                send_delay_sum_b[:] = 0.0
            else:
                stems_sum_b = np.zeros_like(mix_chunk_b)
                send_reverb_sum_b = np.zeros((frames, 2), dtype=np.float32)
                send_delay_sum_b = np.zeros((frames, 2), dtype=np.float32)

            if self.stem_manager_b.stems_ready:
                for i in range(8):
                    l_cfg = state.get("lanes_b", state.get("lanes", []))[i]
                    lane_audio = lanes_chunk_b[i]

                    lane_audio = self.lane_dsp_b[i].process(lane_audio, l_cfg["hp"], l_cfg["lp"])

                    gain = l_cfg["gain"]
                    pan = l_cfg["pan"]
                    lane_audio *= gain

                    if pan != 0.0:
                        left_gain = min(1.0, 1.0 - pan)
                        right_gain = min(1.0, 1.0 + pan)
                        lane_audio[:, 0] *= left_gain
                        lane_audio[:, 1] *= right_gain

                    if HAS_PEDALBOARD:
                        if l_cfg["reverb"] > 0.0:
                            send_reverb_sum_b += lane_audio * l_cfg["reverb"]
                        if l_cfg["delay"] > 0.0:
                            send_delay_sum_b += lane_audio * l_cfg["delay"]

                    stems_sum_b += lane_audio

            if HAS_PEDALBOARD:
                if self.reverb:
                    rev_out_b = self.reverb(send_reverb_sum_b, self.sample_rate)
                    stems_sum_b += rev_out_b
                if self.delay:
                    del_out_b = self.delay(send_delay_sum_b, self.sample_rate)
                    stems_sum_b += del_out_b

            deck_b = mix_chunk_b * (1.0 - stem_blend) + stems_sum_b * stem_blend

        final_mix = (deck_a * ga) + (deck_b * gb)
        final_mix *= master_gain

        try:
            if self.transport_a.playing:
                synth_abs = int(self.transport_a.play_head_samples)
                synth_bpm = float(getattr(self.transport_a, "bpm", 120.0))
            else:
                synth_abs = int(self.transport_b.play_head_samples)
                synth_bpm = float(getattr(self.transport_b, "bpm", 120.0))
            synth_chunk = self.synth.render(synth_abs, frames, synth_bpm)
            final_mix += synth_chunk
        except Exception:
            pass

        try:
            if HAS_PEDALBOARD and self.master_limiter:
                final_mix = self.master_limiter(final_mix, self.sample_rate)

            # Sanitize: avoid NaN/inf bursts that can sound like static.
            final_mix = np.nan_to_num(final_mix, nan=0.0, posinf=0.0, neginf=0.0)

            # Conservative clip instead of tanh soft clip (tanh can add a lot of harmonics).
            final_mix = np.clip(final_mix, -1.0, 1.0)

            outdata[:] = final_mix.astype(np.float32, copy=False)
        except Exception:
            outdata[:] = 0.0

        if self.transport_a.playing:
            old_beat_info = self.transport_a.get_beat_info()
            self.transport_a.advance(frames)
            new_beat_info = self.transport_a.get_beat_info()

            if int(new_beat_info[0]) > int(old_beat_info[0]):
                if self.stem_manager_a.clip_manager:
                    self.stem_manager_a.clip_manager.on_bar_quantization()

            if stop_a_at_end:
                try:
                    track_len_a = int(self.stem_manager_a.full_mix.shape[0]) if self.stem_manager_a.full_mix is not None else 0
                except Exception:
                    track_len_a = 0

                if track_len_a > 0:
                    self.transport_a.seek(track_len_a)
                self.transport_a.stop()

        if self.transport_b.playing:
            old_beat_info_b = self.transport_b.get_beat_info()
            self.transport_b.advance(frames)
            new_beat_info_b = self.transport_b.get_beat_info()

            if int(new_beat_info_b[0]) > int(old_beat_info_b[0]):
                if self.stem_manager_b.clip_manager:
                    self.stem_manager_b.clip_manager.on_bar_quantization()

            if stop_b_at_end:
                try:
                    track_len_b = int(self.stem_manager_b.full_mix.shape[0]) if self.stem_manager_b.full_mix is not None else 0
                except Exception:
                    track_len_b = 0
                if track_len_b > 0:
                    self.transport_b.seek(track_len_b)
                self.transport_b.stop()
