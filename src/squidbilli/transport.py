import numpy as np


class Transport:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.bpm = 120.0
        self.playing = False
        self.play_head_samples = 0
        self.loop_start_samples = 0
        self.loop_end_samples = 0
        self.looping = False

        # Playback speed multiplier. 1.0 is normal speed.
        # This affects how fast play_head_samples advances (and therefore playback pitch).
        self.speed = 1.0

        self.beats_per_bar = 4
        self.samples_per_beat = (60.0 / self.bpm) * self.sample_rate

    def set_bpm(self, bpm):
        self.bpm = max(20.0, min(999.0, bpm))
        self.samples_per_beat = (60.0 / self.bpm) * self.sample_rate

    def set_speed(self, speed: float):
        try:
            s = float(speed)
        except Exception:
            s = 1.0
        # Keep it bounded so the engine can't run away.
        self.speed = max(0.25, min(4.0, s))

    def start(self):
        self.playing = True

    def stop(self):
        self.playing = False

    def seek(self, sample_pos):
        self.play_head_samples = max(0, sample_pos)

    def advance(self, num_samples):
        if not self.playing:
            return

        try:
            step = int(float(num_samples) * float(self.speed))
        except Exception:
            step = int(num_samples)
        if step <= 0:
            step = int(num_samples)
        self.play_head_samples += step

        if self.looping and self.loop_end_samples > self.loop_start_samples:
            if self.play_head_samples >= self.loop_end_samples:
                overshoot = self.play_head_samples - self.loop_end_samples
                loop_len = self.loop_end_samples - self.loop_start_samples
                self.play_head_samples = self.loop_start_samples + (overshoot % loop_len)

    def get_beat_info(self):
        total_beats = self.play_head_samples / self.samples_per_beat
        bar = int(total_beats / self.beats_per_bar) + 1
        beat = int(total_beats % self.beats_per_bar) + 1
        phase = (total_beats % 1.0)
        return bar, beat, phase
