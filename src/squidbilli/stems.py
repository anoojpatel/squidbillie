import os
import subprocess
import threading
import tempfile
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf
from pydub import AudioSegment
from scipy import signal
from scipy.io import wavfile

from squidbilli.library import default_cache_root, track_id_for_path


class StemManager:
    def __init__(self, clip_manager=None):
        self.full_mix = None
        self.stems = {}
        self.lanes = [None] * 8
        self.sample_rate = 44100
        self.is_loading = False
        self.is_separating = False
        self.stems_ready = False
        self.clip_manager = clip_manager

        self.current_track_path: Path | None = None
        self.current_track_id: str | None = None
        self.cache_root = default_cache_root()

        self.waveform_ready = False
        self.waveform_x = None
        self.waveform_y = None
        self.waveform_y_low = None
        self.waveform_y_mid = None
        self.waveform_y_high = None
        self._waveform_thread = None

        self.temp_dir = tempfile.mkdtemp()

    def load_track(
        self,
        file_path,
        track_id: str | None = None,
        cache_dir: str | Path | None = None,
        start_separation: bool = True,
    ):
        self.is_loading = True
        try:
            p = Path(file_path).expanduser().resolve()
            self.current_track_path = p
            self.current_track_id = track_id or track_id_for_path(p)

            # Reset state
            self.stems_ready = False
            self.is_separating = False
            self.stems = {}
            self.lanes = [None] * 8

            audio = AudioSegment.from_file(file_path)
            audio = audio.set_frame_rate(self.sample_rate).set_channels(2)

            samples = np.array(audio.get_array_of_samples())
            if audio.sample_width == 2:
                samples = samples.astype(np.float32) / 32768.0
            elif audio.sample_width == 4:
                samples = samples.astype(np.float32) / 2147483648.0
            samples = samples.reshape((-1, 2))

            self.full_mix = samples
            self.track_len_samples = samples.shape[0]

            if self.clip_manager:
                try:
                    self.clip_manager.grid = [[None for _ in range(self.clip_manager.num_slots)] for _ in range(self.clip_manager.num_lanes)]
                    self.clip_manager.active_clip_indices = [-1] * self.clip_manager.num_lanes
                    self.clip_manager.pending_clip_indices = [-2] * self.clip_manager.num_lanes
                    self.clip_manager.clip_playheads = [0.0] * self.clip_manager.num_lanes
                except Exception:
                    pass
                try:
                    target_len = int(self.full_mix.shape[0])
                    self.clip_manager.set_page(
                        0,
                        total_samples=target_len,
                        sample_rate=int(self.sample_rate),
                        bpm=120.0,
                        bars_per_slot=8,
                        slots_per_page=8,
                    )
                except Exception:
                    pass

            self.waveform_ready = False
            self.waveform_x = None
            self.waveform_y = None
            self.waveform_y_low = None
            self.waveform_y_mid = None
            self.waveform_y_high = None
            self.start_waveform_compute(points=None)

            if start_separation:
                # Try to load cached stems first
                cache_stems_dir = Path(cache_dir) if cache_dir is not None else (
                    self.cache_root / "tracks" / self.current_track_id / "stems"
                )
                if self._load_cached_stems(cache_stems_dir):
                    self._derive_lanes()
                    self.stems_ready = True
                    return

                t = threading.Thread(target=self._run_separation, args=(file_path, cache_stems_dir))
                t.start()

        except Exception as e:
            print(f"Error loading track: {e}")
        finally:
            self.is_loading = False

    def start_waveform_compute(self, points: int | None = 2000):
        if self.full_mix is None:
            return
        if self._waveform_thread and self._waveform_thread.is_alive():
            return

        # Adaptive envelope density: keep cached rendering fast but ensure zoom windows
        # have enough bins on long tracks.
        if points is None:
            try:
                n = int(self.full_mix.shape[0])
                sr = float(self.sample_rate)
                dur_s = float(n) / max(1.0, sr)
            except Exception:
                dur_s = 0.0

            # Target bins-per-second with caps to avoid expensive compute.
            # Higher density helps the 8s zoom window look continuous while keeping
            # runtime rendering fast (still uses cached envelope).
            bins_per_sec = 120.0
            min_points = 4000
            max_points = 20000
            try:
                points = int(dur_s * bins_per_sec)
            except Exception:
                points = min_points
            if points < min_points:
                points = min_points
            if points > max_points:
                points = max_points

        self._waveform_thread = threading.Thread(target=self._compute_waveform, args=(points,))
        self._waveform_thread.daemon = True
        self._waveform_thread.start()

    def _compute_waveform(self, points: int):
        try:
            x = self.full_mix
            if x is None:
                return

            mono = x.mean(axis=1)
            mono = mono.astype(np.float32, copy=False)
            n = mono.shape[0]
            if n == 0:
                return

            points = max(200, int(points))
            hop = max(1, n // points)

            sr = self.sample_rate

            peaks = []
            times = []
            for i in range(0, n, hop):
                seg = mono[i : i + hop]
                if seg.size == 0:
                    continue
                peaks.append(float(np.max(np.abs(seg))))
                times.append(float(i) / float(sr))

            if len(peaks) < 2:
                self.waveform_x = times
                self.waveform_y = peaks
                self.waveform_y_low = peaks
                self.waveform_y_mid = peaks
                self.waveform_y_high = peaks
                self.waveform_ready = True
                return

            # Cheap pseudo-3-band decomposition from the peak envelope.
            # No per-track filtering; just multi-scale smoothing.
            try:
                pk = np.asarray(peaks, dtype=np.float32)

                def _ma(xv: np.ndarray, win: int) -> np.ndarray:
                    w = int(win)
                    if w <= 1:
                        return xv
                    k = np.ones(w, dtype=np.float32) / float(w)
                    y = np.convolve(xv, k, mode="same")
                    return y.astype(np.float32, copy=False)

                # Window sizes scale with point count to keep behavior stable.
                slow = _ma(pk, max(3, int(pk.shape[0] // 120)))
                mid = _ma(pk, max(3, int(pk.shape[0] // 300)))

                e_low = np.maximum(slow, 0.0)
                e_mid = np.maximum(mid - slow, 0.0)
                e_high = np.maximum(pk - mid, 0.0)
                w_low = np.float32(1.0)
                w_mid = np.float32(1.0)
                w_high = np.float32(0.55)
                tot = (e_low * w_low) + (e_mid * w_mid) + (e_high * w_high) + np.float32(1e-6)

                low = pk * ((e_low * w_low) / tot)
                midc = pk * ((e_mid * w_mid) / tot)
                high = pk * ((e_high * w_high) / tot)

                self.waveform_x = times
                self.waveform_y = [float(v) for v in pk]
                self.waveform_y_low = [float(v) for v in low]
                self.waveform_y_mid = [float(v) for v in midc]
                self.waveform_y_high = [float(v) for v in high]
            except Exception:
                self.waveform_x = times
                self.waveform_y = peaks
                self.waveform_y_low = peaks
                self.waveform_y_mid = peaks
                self.waveform_y_high = peaks
            self.waveform_ready = True
        except Exception:
            self.waveform_ready = False

    def _run_separation(self, file_path, cache_stems_dir: Path):
        self.is_separating = True
        try:
            cmd = [
                "demucs",
                "-n",
                "htdemucs",
                "-d",
                "cpu",
                "--out",
                self.temp_dir,
                "--float32",
                file_path,
            ]

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            _, stderr = process.communicate()

            if process.returncode != 0:
                tail = stderr[-4000:] if stderr else ""
                print(f"Demucs failed (code={process.returncode}). Command: {' '.join(cmd)}")
                print(tail)
                return

            filename_no_ext = os.path.splitext(os.path.basename(file_path))[0]
            model_name = "htdemucs"
            base_path = os.path.join(self.temp_dir, model_name, filename_no_ext)

            stem_names = ["drums", "bass", "other", "vocals"]
            loaded_stems = {}

            for name in stem_names:
                stem_path = os.path.join(base_path, f"{name}.wav")
                if not os.path.exists(stem_path):
                    continue

                data, sr = sf.read(stem_path, dtype="float32", always_2d=True)
                if sr != self.sample_rate:
                    pass

                if data.shape[1] == 1:
                    data = np.repeat(data, 2, axis=1)

                loaded_stems[name] = data

                # Save to cache
                cache_stems_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(stem_path, cache_stems_dir / f"{name}.wav")
                except Exception:
                    pass

            self.stems = loaded_stems
            self._derive_lanes()
            self.stems_ready = True

        except Exception as e:
            print(f"Separation error: {e}")
        finally:
            self.is_separating = False

    def _load_cached_stems(self, cache_stems_dir: Path) -> bool:
        stem_names = ["drums", "bass", "other", "vocals"]
        if not cache_stems_dir.exists():
            return False
        loaded_stems = {}
        for name in stem_names:
            p = cache_stems_dir / f"{name}.wav"
            if not p.exists():
                return False
            try:
                data, sr = sf.read(str(p), dtype="float32", always_2d=True)
                if data.shape[1] == 1:
                    data = np.repeat(data, 2, axis=1)
                loaded_stems[name] = data
            except Exception:
                return False

        self.stems = loaded_stems
        return True

    def _derive_lanes(self):
        if not self.stems:
            return

        def apply_filter(data, cutoff, btype):
            b, a = signal.butter(2, cutoff / (self.sample_rate / 2), btype=btype)
            return signal.filtfilt(b, a, data, axis=0)

        self.lanes[4] = self.stems.get("bass", np.zeros_like(self.full_mix))
        self.lanes[7] = self.stems.get("vocals", np.zeros_like(self.full_mix))

        drums = self.stems.get("drums", np.zeros_like(self.full_mix))
        kick = apply_filter(drums, 150, "low")
        hats = apply_filter(drums, 5000, "high")
        snare = apply_filter(drums, 200, "high")
        snare = apply_filter(snare, 4000, "low")
        perc = drums - kick - hats - snare

        self.lanes[0] = kick
        self.lanes[1] = snare
        self.lanes[2] = hats
        self.lanes[3] = perc

        other = self.stems.get("other", np.zeros_like(self.full_mix))
        chords = apply_filter(other, 1000, "low")
        lead = apply_filter(other, 1000, "high")
        self.lanes[5] = chords
        self.lanes[6] = lead

        target_len = self.full_mix.shape[0]
        for i in range(8):
            if self.lanes[i] is None:
                self.lanes[i] = np.zeros((target_len, 2), dtype=np.float32)
            else:
                l = self.lanes[i].shape[0]
                if l < target_len:
                    self.lanes[i] = np.pad(self.lanes[i], ((0, target_len - l), (0, 0)))
                elif l > target_len:
                    self.lanes[i] = self.lanes[i][:target_len]

        if self.clip_manager:
            try:
                # Keep existing page-based clip grid; don't override it here.
                pass
            except Exception:
                pass

    def get_frame(self, frame_idx, count, use_stems=False, *, clip_only: bool = False):
        if self.full_mix is None:
            return np.zeros((count, 2), dtype=np.float32), np.zeros((8, count, 2), dtype=np.float32)

        def read_buffer(buf, start, num):
            slen = buf.shape[0]
            if start >= slen:
                return np.zeros((num, 2), dtype=np.float32)
            end = start + num
            if end <= slen:
                return buf[start:end]
            part = buf[start:]
            pad = num - part.shape[0]
            return np.pad(part, ((0, pad), (0, 0)))

        mix_chunk = read_buffer(self.full_mix, frame_idx, count)

        lanes_chunk = np.zeros((8, count, 2), dtype=np.float32)
        if self.stems_ready:
            for i in range(8):
                active_clip = None
                if self.clip_manager:
                    active_clip = self.clip_manager.get_active_clip(i)

                if active_clip:
                    clip_start = active_clip.start_sample
                    clip_end = active_clip.end_sample
                    clip_len = clip_end - clip_start
                    if clip_len <= 0:
                        continue

                    current_offset = self.clip_manager.clip_playheads[i]
                    out_ptr = 0
                    needed = count
                    while needed > 0:
                        remaining_in_loop = clip_len - current_offset
                        to_read = min(needed, int(remaining_in_loop))
                        read_start = int(clip_start + current_offset)

                        if self.lanes[i] is not None:
                            chunk = read_buffer(self.lanes[i], read_start, to_read)
                            lanes_chunk[i, out_ptr : out_ptr + to_read] = chunk

                        out_ptr += to_read
                        needed -= to_read
                        current_offset += to_read

                        if current_offset >= clip_len:
                            current_offset = 0.0

                    self.clip_manager.clip_playheads[i] = current_offset
                else:
                    if (not bool(clip_only)) and self.lanes[i] is not None:
                        lanes_chunk[i] = read_buffer(self.lanes[i], frame_idx, count)

        return mix_chunk, lanes_chunk
