from dataclasses import dataclass
import threading


NUM_LANES = 8
NUM_SCENES = 8


@dataclass
class LaneState:
    gain: float = 1.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    hp_cutoff: float = 0.0
    lp_cutoff: float = 20000.0
    send_reverb: float = 0.0
    send_delay: float = 0.0


class MixerState:
    def __init__(self):
        self.lanes = [LaneState() for _ in range(NUM_LANES)]
        self.lanes_b = [LaneState() for _ in range(NUM_LANES)]
        self.master_gain = 1.0
        self.deck_crossfade = 0.0
        self.stem_blend = 1.0

        self.clip_only_a = False
        self.clip_only_b = False

        # Octatrack-style morph scenes.
        # A and B select two scene indices; scene_xfade interpolates between them.
        self.scene_a_idx = 0
        self.scene_b_idx = 1
        self.scene_xfade = 0.0

        # Stored scene snapshots. Each entry is either None or a dict with per-lane params.
        self.scenes = [None for _ in range(NUM_SCENES)]
        self.lock = threading.Lock()

        self.lane_names = [
            "Kick",
            "Snare/Clap",
            "Hats",
            "Perc/Top",
            "Bass",
            "Chords",
            "Lead",
            "Vox",
        ]

    def set_lane_gain(self, lane_idx, db):
        with self.lock:
            self.lanes[lane_idx].gain = 10.0 ** (db / 20.0)

    def set_lane_mute(self, lane_idx, muted):
        with self.lock:
            self.lanes[lane_idx].mute = muted

    def set_lane_solo(self, lane_idx, soloed):
        with self.lock:
            self.lanes[lane_idx].solo = soloed

    def get_lane_snapshot(self, lane_idx):
        l = self.lanes[lane_idx]
        return (
            l.gain,
            l.pan,
            l.mute,
            l.solo,
            l.hp_cutoff,
            l.lp_cutoff,
            l.send_reverb,
            l.send_delay,
        )

    def get_mix_snapshot(self):
        with self.lock:
            any_solo_a = any(l.solo for l in self.lanes)
            any_solo_b = any(l.solo for l in self.lanes_b)

            def _scene_lane(scene, lane_idx: int):
                if scene is None:
                    return None
                lanes = scene.get("lanes")
                if not lanes:
                    return None
                if not (0 <= lane_idx < len(lanes)):
                    return None
                return lanes[lane_idx]

            # Prepare scene morph config if both scenes exist.
            x = float(self.scene_xfade)
            if x < 0.0:
                x = 0.0
            if x > 1.0:
                x = 1.0

            a_scene = None
            b_scene = None
            if 0 <= int(self.scene_a_idx) < len(self.scenes):
                a_scene = self.scenes[int(self.scene_a_idx)]
            if 0 <= int(self.scene_b_idx) < len(self.scenes):
                b_scene = self.scenes[int(self.scene_b_idx)]

            use_scene_morph = (a_scene is not None) and (b_scene is not None)

            def _build_lane_configs(lanes, any_solo_flag: bool):
                lane_configs = []
                for l in lanes:
                    is_audible = True
                    if l.mute:
                        is_audible = False
                    elif any_solo_flag and not l.solo:
                        is_audible = False

                    # Default to current lane params.
                    gain = l.gain
                    pan = l.pan
                    hp = l.hp_cutoff
                    lp = l.lp_cutoff
                    reverb = l.send_reverb
                    delay = l.send_delay

                    # Optional scene morph overrides continuous params only.
                    if use_scene_morph:
                        idx = len(lane_configs)
                        a_l = _scene_lane(a_scene, idx)
                        b_l = _scene_lane(b_scene, idx)
                        if a_l is not None and b_l is not None:
                            def _lerp(a, b):
                                return (float(a) * (1.0 - x)) + (float(b) * x)

                            gain = _lerp(a_l.get("gain", gain), b_l.get("gain", gain))
                            pan = _lerp(a_l.get("pan", pan), b_l.get("pan", pan))
                            hp = _lerp(a_l.get("hp", hp), b_l.get("hp", hp))
                            lp = _lerp(a_l.get("lp", lp), b_l.get("lp", lp))
                            reverb = _lerp(a_l.get("reverb", reverb), b_l.get("reverb", reverb))
                            delay = _lerp(a_l.get("delay", delay), b_l.get("delay", delay))

                    lane_configs.append(
                        {
                            "gain": gain if is_audible else 0.0,
                            "pan": pan,
                            "hp": hp,
                            "lp": lp,
                            "reverb": reverb,
                            "delay": delay,
                        }
                    )
                return lane_configs

            lane_configs_a = _build_lane_configs(self.lanes, any_solo_a)
            lane_configs_b = _build_lane_configs(self.lanes_b, any_solo_b)

            return {
                "lanes_a": lane_configs_a,
                "lanes_b": lane_configs_b,
                "master_gain": self.master_gain,
                "deck_crossfade": self.deck_crossfade,
                "stem_blend": self.stem_blend,
                "clip_only_a": bool(self.clip_only_a),
                "clip_only_b": bool(self.clip_only_b),
            }

    def store_scene(self, scene_idx: int):
        if not (0 <= int(scene_idx) < NUM_SCENES):
            return
        with self.lock:
            lanes = []
            for l in self.lanes:
                lanes.append(
                    {
                        "gain": float(l.gain),
                        "pan": float(l.pan),
                        "hp": float(l.hp_cutoff),
                        "lp": float(l.lp_cutoff),
                        "reverb": float(l.send_reverb),
                        "delay": float(l.send_delay),
                    }
                )
            self.scenes[int(scene_idx)] = {"lanes": lanes}
