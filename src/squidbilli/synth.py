from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def _note_to_midi(note: str) -> int | None:
    s = str(note or "").strip().upper()
    if not s:
        return None
    if s in ("~", "REST", "R"):
        return None

    names = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}

    if len(s) < 2:
        return None

    letter = s[0]
    accidental = ""
    rest = s[1:]
    if rest and rest[0] in ("#", "B"):
        accidental = rest[0]
        rest = rest[1:]

    key = letter + accidental
    if key not in names:
        return None

    try:
        octave = int(rest)
    except Exception:
        return None

    # MIDI: C4 = 60
    return int((octave + 1) * 12 + names[key])


def midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((float(midi) - 69.0) / 12.0))


def parse_pattern(pattern: str) -> list[int | None]:
    s = str(pattern or "").strip()
    if not s:
        return []
    out: list[int | None] = []
    for tok in s.split():
        m = _note_to_midi(tok)
        out.append(m)
    return out


@dataclass
class SynthPatch:
    osc: str = "saw"  # sine|saw|square|noise
    amp: float = 0.6
    attack: float = 0.005
    decay: float = 0.08
    sustain: float = 0.0
    release: float = 0.08
    cutoff: float = 16000.0


class _OnePoleLP:
    def __init__(self):
        self.z = 0.0

    def process(self, x: np.ndarray, cutoff_hz: float, sr: float) -> np.ndarray:
        if cutoff_hz >= 0.49 * sr:
            return x
        if cutoff_hz <= 5.0:
            return np.zeros_like(x)
        # Simple one-pole coefficient.
        a = math.exp(-2.0 * math.pi * float(cutoff_hz) / float(sr))
        y = np.empty_like(x)
        z = float(self.z)
        for i in range(x.shape[0]):
            z = (a * z) + ((1.0 - a) * float(x[i]))
            y[i] = z
        self.z = z
        return y


class SynthLane:
    def __init__(self, sr: int = 44100):
        self.sr = int(sr)
        self.patch = SynthPatch()
        self.pattern: list[int | None] = []
        self.step_idx = 0
        self.phase = 0.0

        self.env = 0.0
        self._gate = False
        self._filter_l = _OnePoleLP()
        self._filter_r = _OnePoleLP()

        self._last_step_abs = None

    def set_pattern(self, pattern: str):
        self.pattern = parse_pattern(pattern)
        self.step_idx = 0
        self._last_step_abs = None

    def set_patch(self, **kwargs):
        for k, v in kwargs.items():
            if not hasattr(self.patch, k):
                continue
            try:
                setattr(self.patch, k, v)
            except Exception:
                pass

    def _osc_sample(self, osc: str, phase: float) -> float:
        o = str(osc or "saw").lower()
        if o == "sine":
            return math.sin(2.0 * math.pi * phase)
        if o == "square":
            return 1.0 if phase < 0.5 else -1.0
        if o == "noise":
            # Noise handled separately (vectorized)
            return 0.0
        # saw
        return (2.0 * phase) - 1.0

    def render(self, abs_sample: int, frames: int, bpm: float) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        if not self.pattern:
            return out

        bpm = float(bpm) if bpm and bpm > 1e-3 else 120.0
        sr = float(self.sr)

        # 16th-note step grid: 4 steps per beat.
        samples_per_step = max(1, int((60.0 / bpm) * sr / 4.0))
        step_abs = int(abs_sample) // samples_per_step

        if self._last_step_abs is None:
            self._last_step_abs = step_abs

        if step_abs != self._last_step_abs:
            # Advance steps (handle missed steps if callback is large)
            delta = max(1, int(step_abs - int(self._last_step_abs)))
            self.step_idx = (self.step_idx + delta) % max(1, len(self.pattern))
            self._last_step_abs = step_abs

            note = self.pattern[self.step_idx]
            if note is None:
                self._gate = False
            else:
                self._gate = True
                self._midi = int(note)

        # Envelope + oscillator
        osc = str(self.patch.osc or "saw").lower()
        amp = float(self.patch.amp)
        atk = max(1e-4, float(self.patch.attack))
        dec = max(1e-4, float(self.patch.decay))
        sus = max(0.0, min(1.0, float(self.patch.sustain)))
        rel = max(1e-4, float(self.patch.release))

        if getattr(self, "_midi", None) is None:
            freq = 0.0
        else:
            freq = midi_to_hz(int(self._midi))

        phase = float(self.phase)
        env = float(self.env)

        atk_step = 1.0 / max(1.0, atk * sr)
        dec_step = (1.0 - sus) / max(1.0, dec * sr)
        rel_step = 1.0 / max(1.0, rel * sr)

        if osc == "noise":
            noise = (np.random.rand(frames).astype(np.float32) * 2.0) - 1.0
            sig = noise
        else:
            sig = np.zeros((frames,), dtype=np.float32)

        if freq > 0.0 and osc != "noise":
            ph_inc = float(freq) / sr
            for i in range(frames):
                if self._gate:
                    if env < 1.0:
                        env = min(1.0, env + atk_step)
                    else:
                        if env > sus:
                            env = max(sus, env - dec_step)
                else:
                    env = max(0.0, env - rel_step)

                sig[i] = float(self._osc_sample(osc, phase))
                phase += ph_inc
                if phase >= 1.0:
                    phase -= 1.0
        else:
            for i in range(frames):
                if self._gate:
                    if env < 1.0:
                        env = min(1.0, env + atk_step)
                    else:
                        if env > sus:
                            env = max(sus, env - dec_step)
                else:
                    env = max(0.0, env - rel_step)

        sig *= float(env) * amp

        cutoff = float(self.patch.cutoff)
        left = self._filter_l.process(sig.astype(np.float32, copy=False), cutoff, sr)
        right = self._filter_r.process(sig.astype(np.float32, copy=False), cutoff, sr)

        out[:, 0] = left
        out[:, 1] = right

        self.phase = phase
        self.env = env
        return out


class SynthRack:
    def __init__(self, sr: int = 44100, lanes: int = 2):
        self.sr = int(sr)
        self.enabled = False
        self.gain = 0.7
        n = int(lanes)
        self.lanes = [SynthLane(sr=self.sr) for _ in range(n)]
        self.lane_gain = [1.0 for _ in range(n)]
        self.lane_pan = [0.0 for _ in range(n)]
        self.lane_mute = [False for _ in range(n)]

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def set_gain(self, gain: float):
        try:
            g = float(gain)
        except Exception:
            g = 0.0
        self.gain = max(0.0, min(2.0, g))

    def set_pattern(self, lane: int, pattern: str):
        if 0 <= int(lane) < len(self.lanes):
            self.lanes[int(lane)].set_pattern(pattern)

    def set_patch(self, lane: int, **kwargs):
        if 0 <= int(lane) < len(self.lanes):
            self.lanes[int(lane)].set_patch(**kwargs)

    def set_lane_gain(self, lane: int, gain: float):
        if not (0 <= int(lane) < len(self.lanes)):
            return
        try:
            g = float(gain)
        except Exception:
            g = 0.0
        self.lane_gain[int(lane)] = max(0.0, min(2.0, g))

    def set_lane_pan(self, lane: int, pan: float):
        if not (0 <= int(lane) < len(self.lanes)):
            return
        try:
            p = float(pan)
        except Exception:
            p = 0.0
        self.lane_pan[int(lane)] = max(-1.0, min(1.0, p))

    def set_lane_mute(self, lane: int, mute: bool):
        if not (0 <= int(lane) < len(self.lanes)):
            return
        self.lane_mute[int(lane)] = bool(mute)

    def render(self, abs_sample: int, frames: int, bpm: float) -> np.ndarray:
        if not self.enabled:
            return np.zeros((frames, 2), dtype=np.float32)
        out = np.zeros((frames, 2), dtype=np.float32)

        for i, l in enumerate(self.lanes):
            if i < len(self.lane_mute) and self.lane_mute[i]:
                continue
            lane_out = l.render(abs_sample, frames, bpm)
            g = self.lane_gain[i] if i < len(self.lane_gain) else 1.0
            p = self.lane_pan[i] if i < len(self.lane_pan) else 0.0
            lane_out *= float(g)

            if p != 0.0:
                left_gain = min(1.0, 1.0 - float(p))
                right_gain = min(1.0, 1.0 + float(p))
                lane_out[:, 0] *= left_gain
                lane_out[:, 1] *= right_gain

            out += lane_out
        out *= float(self.gain)
        return out
