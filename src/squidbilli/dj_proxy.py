from __future__ import annotations


class DJProxy:
    """A safe live-code object for deck navigation and beatmatch.

    The UI transports are not the ones driving audio (audio runs in a worker), so
    these actions must be forwarded to the audio controller.
    """

    def __init__(self, audio_controller):
        self._audio = audio_controller

    def beatmatch(self, src: str = "A", dst: str = "B"):
        if self._audio is None:
            return
        try:
            self._audio.beatmatch(src=src, dst=dst)
        except Exception:
            pass

    def jump_beats(self, deck: str, beats: float):
        if self._audio is None:
            return
        try:
            self._audio.jump_beats(deck=deck, beats=float(beats))
        except Exception:
            pass

    def jump_bars(self, deck: str, bars: float):
        if self._audio is None:
            return
        try:
            self._audio.jump_bars(deck=deck, bars=float(bars))
        except Exception:
            pass

    def nudge_samples(self, deck: str, samples: int):
        if self._audio is None:
            return
        try:
            self._audio.nudge(deck=str(deck).upper(), samples=int(samples))
        except Exception:
            pass

    def nudge_ms(self, deck: str, ms: float, sample_rate: int = 44100):
        if self._audio is None:
            return
        try:
            s = int((float(ms) / 1000.0) * float(sample_rate))
        except Exception:
            s = 0
        self.nudge_samples(deck, s)

    def bend(self, deck: str, speed: float):
        """Tempo bend by changing playback speed multiplier.

        Examples:
        - bend('B', 1.01)  # slightly faster
        - bend('B', 0.99)  # slightly slower
        - bend('B', 1.0)   # reset
        """
        if self._audio is None:
            return
        try:
            self._audio.bend_speed(deck=str(deck).upper(), speed=float(speed))
        except Exception:
            pass
