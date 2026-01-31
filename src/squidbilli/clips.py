from dataclasses import dataclass


def _parse_pattern_tokens(pattern: str):
    # Very small Tidal-ish subset:
    # - tokens separated by whitespace
    # - "~" means rest
    # - "1".."8" selects clip slot (1-indexed in the UI, stored 0-indexed)
    tokens = []
    for raw in (pattern or "").strip().split():
        t = raw.strip()
        if not t:
            continue
        if t in ("~", "_"):
            tokens.append(None)
            continue
        if t.isdigit():
            n = int(t)
            if 1 <= n <= 8:
                tokens.append(n - 1)
                continue
        # Unknown token -> treat as rest for now
        tokens.append(None)
    return tokens


@dataclass
class Clip:
    name: str
    lane_idx: int
    start_sample: int
    end_sample: int
    color: tuple = (255, 255, 255)


class ClipManager:
    def __init__(self, num_lanes=8, num_slots=8):
        self.num_lanes = num_lanes
        self.num_slots = num_slots
        self.grid = [[None for _ in range(num_slots)] for _ in range(num_lanes)]

        self.current_page = 0
        self.bars_per_slot = 8
        self.slots_per_page = num_slots

        self.active_clip_indices = [-1] * num_lanes

        self.pending_clip_indices = [-2] * num_lanes

        self.clip_playheads = [0.0] * num_lanes

        # Pattern state: per-lane sequence of slot indices (or None for rest)
        self.patterns = [[] for _ in range(num_lanes)]
        self.pattern_steps = [0] * num_lanes

        # Scene banks (A/B) are just labels for selecting a scene index 0..7.
        self.scene_a = 0
        self.scene_b = 0

    def create_clip(self, lane_idx, slot_idx, name, start, end):
        if 0 <= lane_idx < self.num_lanes and 0 <= slot_idx < self.num_slots:
            self.grid[lane_idx][slot_idx] = Clip(name, lane_idx, start, end)

    def set_page(
        self,
        page: int,
        *,
        total_samples: int,
        sample_rate: int,
        bpm: float,
        bars_per_slot: int = 8,
        slots_per_page: int | None = None,
    ):
        try:
            p = int(page)
        except Exception:
            p = 0
        if p < 0:
            p = 0

        try:
            total = int(total_samples)
        except Exception:
            total = 0
        if total < 0:
            total = 0

        try:
            sr = int(sample_rate)
        except Exception:
            sr = 44100
        if sr <= 0:
            sr = 44100

        try:
            bpm_f = float(bpm)
        except Exception:
            bpm_f = 120.0
        if bpm_f <= 1e-3:
            bpm_f = 120.0

        spp = int(slots_per_page) if slots_per_page is not None else int(self.num_slots)
        if spp <= 0:
            spp = int(self.num_slots)

        bps = int(bars_per_slot) if bars_per_slot is not None else 8
        if bps <= 0:
            bps = 8

        # 1 bar = 4 beats.
        bar_samples = int((60.0 / bpm_f) * 4.0 * float(sr))
        slot_len = max(1, int(bar_samples) * int(bps))

        self.current_page = p
        self.bars_per_slot = bps
        self.slots_per_page = spp

        # Rebuild grid in-place.
        self.grid = [[None for _ in range(self.num_slots)] for _ in range(self.num_lanes)]
        base_slot = int(p) * int(spp)
        for l in range(self.num_lanes):
            for s in range(self.num_slots):
                abs_slot = base_slot + int(s)
                start = int(abs_slot) * slot_len
                end = start + slot_len
                if start >= total:
                    continue
                if end > total:
                    end = total
                if end <= start:
                    continue
                self.create_clip(l, s, f"Clip {l}-{s}", start, end)

    def queue_clip(self, lane_idx, slot_idx):
        if 0 <= lane_idx < self.num_lanes:
            self.pending_clip_indices[lane_idx] = slot_idx

    def trigger_scene(self, slot_idx):
        for l in range(self.num_lanes):
            self.queue_clip(l, slot_idx)

    def set_pattern(self, lane_idx: int, pattern: str):
        if not (0 <= lane_idx < self.num_lanes):
            return
        self.patterns[lane_idx] = _parse_pattern_tokens(pattern)
        self.pattern_steps[lane_idx] = 0

    def clear_patterns(self):
        for l in range(self.num_lanes):
            self.patterns[l] = []
            self.pattern_steps[l] = 0

    def tick_patterns_on_bar(self):
        # Advance patterns once per bar. If a step selects a slot, queue it for that lane.
        for l in range(self.num_lanes):
            pat = self.patterns[l]
            if not pat:
                continue
            step = self.pattern_steps[l] % len(pat)
            slot = pat[step]
            if slot is None:
                pass
            else:
                self.queue_clip(l, slot)
            self.pattern_steps[l] = (self.pattern_steps[l] + 1) % len(pat)

    def select_scene_a(self, scene_idx: int, launch: bool = True):
        if 0 <= scene_idx < self.num_slots:
            self.scene_a = scene_idx
            if launch:
                self.trigger_scene(scene_idx)

    def select_scene_b(self, scene_idx: int, launch: bool = True):
        if 0 <= scene_idx < self.num_slots:
            self.scene_b = scene_idx
            if launch:
                self.trigger_scene(scene_idx)

    def on_bar_quantization(self):
        self.tick_patterns_on_bar()
        for l in range(self.num_lanes):
            pending = self.pending_clip_indices[l]
            if pending != -2:
                self.active_clip_indices[l] = pending
                self.clip_playheads[l] = 0.0
                self.pending_clip_indices[l] = -2

    def get_active_clip(self, lane_idx):
        slot = self.active_clip_indices[lane_idx]
        if slot != -1:
            return self.grid[lane_idx][slot]
        return None
