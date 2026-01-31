import numpy as np
from scipy import signal


class SimpleFilter:
    def __init__(self, filter_type="lp", cutoff=1000, fs=44100):
        self.fs = fs
        self.type = filter_type
        self.cutoff = cutoff
        self.zi = np.zeros((2, 2))
        self.b, self.a = self._calc_coeffs()

    def _calc_coeffs(self):
        nyq = 0.5 * self.fs
        normal_cutoff = self.cutoff / nyq
        normal_cutoff = np.clip(normal_cutoff, 0.001, 0.999)
        if self.type == "lp":
            b, a = signal.butter(1, normal_cutoff, btype="low")
        else:
            b, a = signal.butter(1, normal_cutoff, btype="high")
        return b, a

    def process(self, data):
        out, self.zi = signal.lfilter(self.b, self.a, data, axis=0, zi=self.zi)
        return out

    def update_cutoff(self, cutoff):
        if abs(cutoff - self.cutoff) > 1.0:
            self.cutoff = cutoff
            self.b, self.a = self._calc_coeffs()


class LaneDSP:
    def __init__(self, fs=44100):
        self.fs = fs
        self.lp_filter = None
        self.hp_filter = None

    def process(self, audio, hp_cutoff, lp_cutoff):
        if hp_cutoff > 20.0:
            if self.hp_filter is None:
                self.hp_filter = SimpleFilter("hp", hp_cutoff, self.fs)
            else:
                self.hp_filter.update_cutoff(hp_cutoff)
            audio = self.hp_filter.process(audio)

        if lp_cutoff < 19000.0:
            if self.lp_filter is None:
                self.lp_filter = SimpleFilter("lp", lp_cutoff, self.fs)
            else:
                self.lp_filter.update_cutoff(lp_cutoff)
            audio = self.lp_filter.process(audio)

        return audio
