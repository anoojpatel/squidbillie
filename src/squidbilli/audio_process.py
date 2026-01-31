import multiprocessing as mp
import time
from dataclasses import dataclass

from squidbilli.audio_engine import AudioEngine
from squidbilli.clips import ClipManager
from squidbilli.mixer_state import MixerState
from squidbilli.stems import StemManager
from squidbilli.transport import Transport


@dataclass
class AudioStatus:
    playing_a: bool
    playing_b: bool
    playhead_a: int
    playhead_b: int
    bpm: float
    xruns: int
    active_clips_a: list[int]
    pending_clips_a: list[int]
    clip_playheads_a: list[float]
    clip_page_a: int
    active_clips_b: list[int]
    pending_clips_b: list[int]
    clip_playheads_b: list[float]
    clip_page_b: int


def _audio_worker_main(cmd_q: mp.Queue, status_q: mp.Queue):
    transport_a = Transport()
    transport_b = Transport()
    mixer_state = MixerState()

    clip_manager_a = ClipManager()
    clip_manager_b = ClipManager()
    stem_manager_a = StemManager(clip_manager=clip_manager_a)
    stem_manager_b = StemManager(clip_manager=clip_manager_b)

    engine = AudioEngine(transport_a, transport_b, mixer_state, stem_manager_a, stem_manager_b)
    engine.start()

    running = True
    last_status = 0.0

    while running:
        # Drain commands quickly.
        for _ in range(64):
            try:
                cmd = cmd_q.get_nowait()
            except Exception:
                cmd = None

            if not cmd:
                break

            c = cmd.get("cmd")

            if c == "shutdown":
                running = False
                break

            if c == "play":
                deck = cmd.get("deck")
                do_play = bool(cmd.get("playing", True))
                if deck == "A":
                    transport_a.start() if do_play else transport_a.stop()
                elif deck == "B":
                    transport_b.start() if do_play else transport_b.stop()

            elif c == "seek":
                deck = cmd.get("deck")
                pos = int(cmd.get("pos", 0))
                if deck == "A":
                    transport_a.seek(pos)
                elif deck == "B":
                    transport_b.seek(pos)

            elif c == "set_bpm":
                bpm = float(cmd.get("bpm", 120.0))
                transport_a.set_bpm(bpm)
                transport_b.set_bpm(bpm)

            elif c == "mixer":
                with mixer_state.lock:
                    for k, v in cmd.get("values", {}).items():
                        if hasattr(mixer_state, k):
                            setattr(mixer_state, k, v)

            elif c == "lane":
                idx = int(cmd.get("lane", -1))
                deck = str(cmd.get("deck", "A")).upper()
                lanes = mixer_state.lanes_b if deck == "B" else mixer_state.lanes
                if 0 <= idx < len(lanes):
                    with mixer_state.lock:
                        l = lanes[idx]
                        for k, v in cmd.get("values", {}).items():
                            if hasattr(l, k):
                                setattr(l, k, v)

            elif c == "store_scene":
                mixer_state.store_scene(int(cmd.get("scene", 0)))

            elif c == "load":
                deck = cmd.get("deck")
                path = cmd.get("path")
                track_id = cmd.get("track_id")
                cache_dir = cmd.get("cache_dir")
                start_separation = bool(cmd.get("start_separation", True))

                if deck == "A" and path:
                    stem_manager_a.load_track(path, track_id=track_id, cache_dir=cache_dir, start_separation=start_separation)
                    transport_a.seek(0)
                    try:
                        if stem_manager_a.full_mix is not None:
                            clip_manager_a.set_page(
                                0,
                                total_samples=int(stem_manager_a.full_mix.shape[0]),
                                sample_rate=int(transport_a.sample_rate),
                                bpm=float(transport_a.bpm),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass
                elif deck == "B" and path:
                    stem_manager_b.load_track(path, track_id=track_id, cache_dir=cache_dir, start_separation=start_separation)
                    transport_b.seek(0)
                    try:
                        if stem_manager_b.full_mix is not None:
                            clip_manager_b.set_page(
                                0,
                                total_samples=int(stem_manager_b.full_mix.shape[0]),
                                sample_rate=int(transport_b.sample_rate),
                                bpm=float(transport_b.bpm),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass

            elif c == "set_clip_page":
                deck = str(cmd.get("deck", "A")).upper()
                page = int(cmd.get("page", 0))
                if deck == "B":
                    try:
                        if stem_manager_b.full_mix is not None:
                            clip_manager_b.set_page(
                                page,
                                total_samples=int(stem_manager_b.full_mix.shape[0]),
                                sample_rate=int(transport_b.sample_rate),
                                bpm=float(transport_b.bpm),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass
                else:
                    try:
                        if stem_manager_a.full_mix is not None:
                            clip_manager_a.set_page(
                                page,
                                total_samples=int(stem_manager_a.full_mix.shape[0]),
                                sample_rate=int(transport_a.sample_rate),
                                bpm=float(transport_a.bpm),
                                bars_per_slot=8,
                                slots_per_page=8,
                            )
                    except Exception:
                        pass

            elif c == "queue_clip":
                deck = str(cmd.get("deck", "A")).upper()
                lane = int(cmd.get("lane", 0))
                slot = int(cmd.get("slot", -1))
                if deck == "B":
                    clip_manager_b.queue_clip(lane, slot)
                else:
                    clip_manager_a.queue_clip(lane, slot)

            elif c == "trigger_scene":
                deck = str(cmd.get("deck", "A")).upper()
                scene = int(cmd.get("scene", 0))
                if deck == "B":
                    clip_manager_b.trigger_scene(scene)
                else:
                    clip_manager_a.trigger_scene(scene)

            elif c == "pattern":
                deck = str(cmd.get("deck", "A")).upper()
                lane = int(cmd.get("lane", 0))
                pattern = cmd.get("pattern", "")
                if deck == "B":
                    clip_manager_b.set_pattern(lane, pattern)
                else:
                    clip_manager_a.set_pattern(lane, pattern)

            elif c == "clear_patterns":
                deck = str(cmd.get("deck", "A")).upper()
                if deck == "B":
                    clip_manager_b.clear_patterns()
                else:
                    clip_manager_a.clear_patterns()

            elif c == "synth":
                action = str(cmd.get("action", "")).lower()
                if action == "enable":
                    try:
                        engine.synth.set_enabled(bool(cmd.get("enabled", False)))
                    except Exception:
                        pass
                elif action == "gain":
                    try:
                        engine.synth.set_gain(float(cmd.get("gain", 0.0)))
                    except Exception:
                        pass
                elif action == "lane_gain":
                    try:
                        lane = int(cmd.get("lane", 0))
                        gain = float(cmd.get("gain", 1.0))
                        engine.synth.set_lane_gain(lane, gain)
                    except Exception:
                        pass
                elif action == "lane_pan":
                    try:
                        lane = int(cmd.get("lane", 0))
                        pan = float(cmd.get("pan", 0.0))
                        engine.synth.set_lane_pan(lane, pan)
                    except Exception:
                        pass
                elif action == "lane_mute":
                    try:
                        lane = int(cmd.get("lane", 0))
                        mute = bool(cmd.get("mute", False))
                        engine.synth.set_lane_mute(lane, mute)
                    except Exception:
                        pass
                elif action == "pattern":
                    try:
                        lane = int(cmd.get("lane", 0))
                        pattern = str(cmd.get("pattern", ""))
                        engine.synth.set_pattern(lane, pattern)
                    except Exception:
                        pass
                elif action == "patch":
                    try:
                        lane = int(cmd.get("lane", 0))
                        params = cmd.get("params", {})
                        if isinstance(params, dict):
                            engine.synth.set_patch(lane, **params)
                    except Exception:
                        pass

            elif c == "beatmatch":
                src = str(cmd.get("src", "A")).upper()
                dst = str(cmd.get("dst", "B")).upper()
                a = transport_a if src == "A" else transport_b
                b = transport_a if dst == "A" else transport_b
                try:
                    b.set_bpm(float(a.bpm))
                except Exception:
                    pass
                try:
                    # Align downbeats (bar grid) and the position within the bar.
                    spb = float(getattr(b, "samples_per_beat", 0.0) or 0.0)
                    if spb > 1e-6:
                        bpb = int(getattr(b, "beats_per_bar", 4) or 4)
                        if bpb <= 0:
                            bpb = 4
                        total_beats_src = float(a.play_head_samples) / float(getattr(a, "samples_per_beat", spb) or spb)
                        total_beats_dst = float(b.play_head_samples) / spb

                        src_bar_start = float(int(total_beats_src // bpb) * bpb)
                        # Always choose the NEXT downbeat on the destination deck.
                        dst_bar_start = float((int(total_beats_dst // float(bpb)) + 1) * bpb)

                        within_bar = total_beats_src - src_bar_start
                        b.seek(int((dst_bar_start + within_bar) * spb))
                except Exception:
                    pass

            elif c == "nudge":
                deck = str(cmd.get("deck", "A")).upper()
                samples = int(cmd.get("samples", 0))
                tr = transport_a if deck == "A" else transport_b
                try:
                    tr.seek(int(tr.play_head_samples) + int(samples))
                except Exception:
                    pass

            elif c == "bend":
                deck = str(cmd.get("deck", "A")).upper()
                speed = float(cmd.get("speed", 1.0))
                tr = transport_a if deck == "A" else transport_b
                try:
                    tr.set_speed(speed)
                except Exception:
                    try:
                        tr.speed = float(speed)
                    except Exception:
                        pass

            elif c == "jump":
                deck = str(cmd.get("deck", "A")).upper()
                unit = str(cmd.get("unit", "beats")).lower()
                amount = float(cmd.get("amount", 0.0))
                tr = transport_a if deck == "A" else transport_b
                try:
                    spb = float(getattr(tr, "samples_per_beat", 0.0) or 0.0)
                    bpb = int(getattr(tr, "beats_per_bar", 4) or 4)
                    beats = amount
                    if unit == "bars":
                        beats = amount * float(bpb)
                    delta = int(beats * spb)
                    tr.seek(int(tr.play_head_samples) + delta)
                except Exception:
                    pass

        now = time.time()
        if now - last_status > 0.05:
            last_status = now
            try:
                status_q.put_nowait(
                    AudioStatus(
                        playing_a=bool(transport_a.playing),
                        playing_b=bool(transport_b.playing),
                        playhead_a=int(transport_a.play_head_samples),
                        playhead_b=int(transport_b.play_head_samples),
                        bpm=float(transport_a.bpm),
                        xruns=int(getattr(engine, "_xrun_count", 0)),
                        active_clips_a=list(getattr(clip_manager_a, "active_clip_indices", [-1] * 8)),
                        pending_clips_a=list(getattr(clip_manager_a, "pending_clip_indices", [-2] * 8)),
                        clip_playheads_a=[float(v) for v in getattr(clip_manager_a, "clip_playheads", [0.0] * 8)],
                        clip_page_a=int(getattr(clip_manager_a, "current_page", 0)),
                        active_clips_b=list(getattr(clip_manager_b, "active_clip_indices", [-1] * 8)),
                        pending_clips_b=list(getattr(clip_manager_b, "pending_clip_indices", [-2] * 8)),
                        clip_playheads_b=[float(v) for v in getattr(clip_manager_b, "clip_playheads", [0.0] * 8)],
                        clip_page_b=int(getattr(clip_manager_b, "current_page", 0)),
                    )
                )
            except Exception:
                pass

        time.sleep(0.002)

    try:
        engine.stop()
    except Exception:
        pass


class AudioController:
    def __init__(self):
        ctx = mp.get_context("spawn")
        self._cmd_q: mp.Queue = ctx.Queue()
        self._status_q: mp.Queue = ctx.Queue()
        self._proc = ctx.Process(target=_audio_worker_main, args=(self._cmd_q, self._status_q), daemon=True)
        self._last_status: AudioStatus | None = None

    def start(self):
        self._proc.start()

    def stop(self):
        try:
            self._cmd_q.put({"cmd": "shutdown"})
        except Exception:
            pass
        try:
            if self._proc.is_alive():
                self._proc.join(timeout=2.0)
        except Exception:
            pass

    def poll_status(self) -> AudioStatus | None:
        # Drain queue; keep last.
        s = None
        for _ in range(64):
            try:
                s = self._status_q.get_nowait()
            except Exception:
                break
        if s is not None:
            self._last_status = s
        return self._last_status

    def play(self, deck: str, playing: bool):
        self._cmd_q.put({"cmd": "play", "deck": deck, "playing": bool(playing)})

    def seek(self, deck: str, pos: int):
        self._cmd_q.put({"cmd": "seek", "deck": deck, "pos": int(pos)})

    def set_bpm(self, bpm: float):
        self._cmd_q.put({"cmd": "set_bpm", "bpm": float(bpm)})

    def set_mixer_values(self, **values):
        self._cmd_q.put({"cmd": "mixer", "values": values})

    def set_lane_values(self, lane_idx: int, *, deck: str = "A", **values):
        self._cmd_q.put({"cmd": "lane", "deck": str(deck).upper(), "lane": int(lane_idx), "values": values})

    def store_scene(self, scene_idx: int):
        self._cmd_q.put({"cmd": "store_scene", "scene": int(scene_idx)})

    def load_deck(self, deck: str, path: str, track_id: str | None = None, cache_dir: str | None = None, start_separation: bool = True):
        self._cmd_q.put(
            {
                "cmd": "load",
                "deck": deck,
                "path": path,
                "track_id": track_id,
                "cache_dir": cache_dir,
                "start_separation": bool(start_separation),
            }
        )

    def queue_clip(self, deck: str, lane: int, slot: int):
        self._cmd_q.put({"cmd": "queue_clip", "deck": str(deck).upper(), "lane": int(lane), "slot": int(slot)})

    def trigger_scene(self, deck: str, scene: int):
        self._cmd_q.put({"cmd": "trigger_scene", "deck": str(deck).upper(), "scene": int(scene)})

    def set_pattern(self, deck: str, lane: int, pattern: str):
        self._cmd_q.put({"cmd": "pattern", "deck": str(deck).upper(), "lane": int(lane), "pattern": pattern})

    def clear_patterns(self, deck: str):
        self._cmd_q.put({"cmd": "clear_patterns", "deck": str(deck).upper()})

    def set_clip_page(self, deck: str, page: int):
        self._cmd_q.put({"cmd": "set_clip_page", "deck": str(deck).upper(), "page": int(page)})

    def synth_enable(self, enabled: bool):
        self._cmd_q.put({"cmd": "synth", "action": "enable", "enabled": bool(enabled)})

    def synth_gain(self, gain: float):
        self._cmd_q.put({"cmd": "synth", "action": "gain", "gain": float(gain)})

    def synth_lane_gain(self, lane: int, gain: float):
        self._cmd_q.put({"cmd": "synth", "action": "lane_gain", "lane": int(lane), "gain": float(gain)})

    def synth_lane_pan(self, lane: int, pan: float):
        self._cmd_q.put({"cmd": "synth", "action": "lane_pan", "lane": int(lane), "pan": float(pan)})

    def synth_lane_mute(self, lane: int, mute: bool):
        self._cmd_q.put({"cmd": "synth", "action": "lane_mute", "lane": int(lane), "mute": bool(mute)})

    def synth_pattern(self, lane: int, pattern: str):
        self._cmd_q.put({"cmd": "synth", "action": "pattern", "lane": int(lane), "pattern": str(pattern)})

    def synth_patch(self, lane: int, **params):
        self._cmd_q.put({"cmd": "synth", "action": "patch", "lane": int(lane), "params": dict(params)})

    def beatmatch(self, src: str = "A", dst: str = "B"):
        self._cmd_q.put({"cmd": "beatmatch", "src": str(src).upper(), "dst": str(dst).upper()})

    def jump_beats(self, deck: str, beats: float):
        self._cmd_q.put({"cmd": "jump", "deck": str(deck).upper(), "unit": "beats", "amount": float(beats)})

    def jump_bars(self, deck: str, bars: float):
        self._cmd_q.put({"cmd": "jump", "deck": str(deck).upper(), "unit": "bars", "amount": float(bars)})

    def nudge(self, deck: str, samples: int):
        self._cmd_q.put({"cmd": "nudge", "deck": str(deck).upper(), "samples": int(samples)})

    def bend_speed(self, deck: str, speed: float):
        self._cmd_q.put({"cmd": "bend", "deck": str(deck).upper(), "speed": float(speed)})
