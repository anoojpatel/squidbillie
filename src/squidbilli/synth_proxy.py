from __future__ import annotations


class SynthProxy:
    """A safe live-code object that forwards synth commands to the audio worker.

    This avoids doing any DSP or time-critical operations on the UI thread.
    """

    def __init__(self, audio_controller):
        self._audio = audio_controller

    def enable(self, enabled: bool = True):
        if self._audio is None:
            return
        try:
            self._audio.synth_enable(bool(enabled))
        except Exception:
            pass

    def gain(self, gain: float):
        if self._audio is None:
            return
        try:
            self._audio.synth_gain(float(gain))
        except Exception:
            pass

    def lane_gain(self, lane: int, gain: float):
        if self._audio is None:
            return
        try:
            self._audio.synth_lane_gain(int(lane), float(gain))
        except Exception:
            pass

    def lane_pan(self, lane: int, pan: float):
        if self._audio is None:
            return
        try:
            self._audio.synth_lane_pan(int(lane), float(pan))
        except Exception:
            pass

    def lane_mute(self, lane: int, mute: bool = True):
        if self._audio is None:
            return
        try:
            self._audio.synth_lane_mute(int(lane), bool(mute))
        except Exception:
            pass

    def set_pattern(self, lane: int, pattern: str):
        if self._audio is None:
            return
        try:
            self._audio.synth_pattern(int(lane), str(pattern))
        except Exception:
            pass

    def set_patch(self, lane: int, **params):
        if self._audio is None:
            return
        try:
            self._audio.synth_patch(int(lane), **params)
        except Exception:
            pass
