from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf
from scipy import signal

AUDIO_EXTS = {".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a"}


def default_cache_root() -> Path:
    root = Path.home() / ".cache" / "squidbilli"
    root.mkdir(parents=True, exist_ok=True)
    return root


def track_id_for_path(path: Path) -> str:
    st = path.stat()
    key = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    import hashlib

    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class TrackInfo:
    track_id: str
    path: Path
    name: str
    stems_ready: bool
    bpm: Optional[float]
    camelot: Optional[str]
    musical_key: Optional[str]


class TrackLibrary:
    def __init__(self, cache_root: Optional[Path] = None):
        self.cache_root = cache_root or default_cache_root()
        self.folders: List[Path] = []
        self._tracks: List[TrackInfo] = []
        self._index_by_id: Dict[str, TrackInfo] = {}

        self.filter_text: str = ""
        self.selected_index: int = 0

        self._analysis_lock = threading.Lock()
        self._analysis_queue: List[Tuple[str, Path]] = []
        self._analysis_inflight: set[str] = set()
        self._analysis_thread = threading.Thread(target=self._analysis_worker, daemon=True)
        self._analysis_thread.start()

    def add_folder(self, folder: Path):
        folder = folder.expanduser().resolve()
        if folder not in self.folders:
            self.folders.append(folder)

    def scan(self):
        tracks: List[TrackInfo] = []
        for folder in self.folders:
            if not folder.exists():
                continue
            for p in folder.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in AUDIO_EXTS:
                    continue
                tid = track_id_for_path(p)
                meta = self._read_meta(tid)
                stems_ready = self._stems_exist(tid)
                bpm = meta.get("bpm") if meta else None
                camelot = meta.get("camelot") if meta else None
                musical_key = meta.get("key") if meta else None

                # Opportunistic filename parse (stored separately); analysis can override later.
                filename_bpm = self._parse_bpm_from_filename(p.name)
                if filename_bpm is not None and (meta.get("filename_bpm") != filename_bpm):
                    self.update_meta(tid, {"filename_bpm": float(filename_bpm)})

                # If analysis missing (or only filename BPM exists), enqueue analysis.
                if bpm is None or camelot is None or musical_key is None:
                    self.enqueue_analysis(tid, p)
                tracks.append(
                    TrackInfo(
                        track_id=tid,
                        path=p,
                        name=p.stem,
                        stems_ready=stems_ready,
                        bpm=bpm,
                        camelot=camelot,
                        musical_key=musical_key,
                    )
                )

        tracks.sort(key=lambda t: t.name.lower())
        self._tracks = tracks
        self._index_by_id = {t.track_id: t for t in tracks}
        self.selected_index = max(0, min(self.selected_index, len(self.filtered_tracks()) - 1))

    def filtered_tracks(self) -> List[TrackInfo]:
        ft = self.filter_text.strip()
        if not ft:
            return list(self._tracks)

        bpm_min = None
        bpm_max = None
        camelot = None
        key = None
        terms: List[str] = []

        for raw in ft.split():
            token = raw.strip()
            low = token.lower()

            if low.startswith("bpm:"):
                spec = low.split(":", 1)[1]
                if "-" in spec:
                    a, b = spec.split("-", 1)
                    try:
                        bpm_min = float(a)
                        bpm_max = float(b)
                    except Exception:
                        pass
                else:
                    try:
                        v = float(spec)
                        bpm_min = v
                        bpm_max = v
                    except Exception:
                        pass
                continue

            if low.startswith("camelot:"):
                camelot = token.split(":", 1)[1].strip().upper()
                continue

            if low.startswith("key:"):
                key = token.split(":", 1)[1].strip().upper()
                continue

            terms.append(low)

        def meta_for(t: TrackInfo) -> Dict:
            return self._read_meta(t.track_id) or {}

        def passes(t: TrackInfo) -> bool:
            hay = f"{t.name.lower()} {str(t.path).lower()}"
            if any(term not in hay for term in terms):
                return False

            meta = meta_for(t)
            bpm_val = meta.get("bpm", t.bpm)
            if bpm_min is not None or bpm_max is not None:
                if bpm_val is None:
                    return False
                try:
                    b = float(bpm_val)
                except Exception:
                    return False
                if bpm_min is not None and b < bpm_min:
                    return False
                if bpm_max is not None and b > bpm_max:
                    return False

            if camelot:
                c = meta.get("camelot")
                if not c:
                    return False
                if str(c).upper() != camelot:
                    return False

            if key:
                c = meta.get("camelot")
                if c and str(c).upper() == key:
                    return True
                k = meta.get("key")
                if not k:
                    return False
                if key not in str(k).upper().replace(" ", ""):
                    return False

            return True

        return [t for t in self._tracks if passes(t)]

    def select_next(self):
        items = self.filtered_tracks()
        if not items:
            self.selected_index = 0
            return
        self.selected_index = min(self.selected_index + 1, len(items) - 1)

    def select_prev(self):
        items = self.filtered_tracks()
        if not items:
            self.selected_index = 0
            return
        self.selected_index = max(self.selected_index - 1, 0)

    def get_selected(self) -> Optional[TrackInfo]:
        items = self.filtered_tracks()
        if not items:
            return None
        return items[max(0, min(self.selected_index, len(items) - 1))]

    def cache_dir(self, track_id: str) -> Path:
        d = self.cache_root / "tracks" / track_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def stems_dir(self, track_id: str) -> Path:
        d = self.cache_dir(track_id) / "stems"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def meta_path(self, track_id: str) -> Path:
        return self.cache_dir(track_id) / "meta.json"

    def get_meta(self, track_id: str) -> Dict:
        return self._read_meta(track_id)

    def write_meta(self, track_id: str, meta: Dict):
        p = self.meta_path(track_id)
        p.write_text(json.dumps(meta, indent=2))

    def update_meta(self, track_id: str, updates: Dict):
        meta = self._read_meta(track_id) or {}
        meta.update(updates)
        self.write_meta(track_id, meta)

    def _read_meta(self, track_id: str) -> Dict:
        p = self.meta_path(track_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}

    def _stems_exist(self, track_id: str) -> bool:
        d = self.stems_dir(track_id)
        required = ["drums.wav", "bass.wav", "other.wav", "vocals.wav"]
        return all((d / r).exists() for r in required)

    def enqueue_analysis(self, track_id: str, path: Path):
        with self._analysis_lock:
            if track_id in self._analysis_inflight:
                return
            self._analysis_inflight.add(track_id)
            self._analysis_queue.append((track_id, path))

    def _analysis_worker(self):
        while True:
            item = None
            with self._analysis_lock:
                if self._analysis_queue:
                    item = self._analysis_queue.pop(0)
            if item is None:
                time.sleep(0.1)
                continue

            track_id, path = item
            try:
                updates = self._analyze_track(path)

                # Policy: analysis overrides filename bpm if disagreement.
                meta = self._read_meta(track_id) or {}
                filename_bpm = meta.get("filename_bpm")
                analyzed_bpm = updates.get("bpm")
                if analyzed_bpm is not None and filename_bpm is not None:
                    if abs(float(analyzed_bpm) - float(filename_bpm)) >= 2.0:
                        updates["bpm"] = float(analyzed_bpm)
                        updates["bpm_source"] = "analyzed"
                    else:
                        # Close enough; keep analyzed bpm but mark as consistent.
                        updates["bpm"] = float(analyzed_bpm)
                        updates["bpm_source"] = "analyzed"

                self.update_meta(track_id, updates)
            except Exception:
                pass
            finally:
                with self._analysis_lock:
                    self._analysis_inflight.discard(track_id)

    def _parse_bpm_from_filename(self, filename: str) -> Optional[float]:
        # Common forms: "128bpm", "128 bpm", "[128]", "(128)"
        s = filename.lower()
        m = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*bpm\b", s)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        m = re.search(r"\[(\d{2,3})\]", s)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        m = re.search(r"\((\d{2,3})\)", s)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        return None

    def _analyze_track(self, path: Path) -> Dict:
        # Decode up to ~60s of audio for analysis.
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            mono = data[:, 0]
        else:
            mono = data.mean(axis=1)

        max_sec = 60.0
        max_n = int(sr * max_sec)
        if mono.shape[0] > max_n:
            mono = mono[:max_n]

        # Downsample to reduce CPU.
        target_sr = 11025
        if sr != target_sr:
            g = int(np.gcd(sr, target_sr))
            up = target_sr // g
            down = sr // g
            mono = signal.resample_poly(mono, up, down).astype(np.float32)
            sr = target_sr

        bpm = self._estimate_bpm(mono, sr)
        key_name, camelot = self._estimate_key_and_camelot(mono, sr)

        out: Dict[str, object] = {}
        if bpm is not None:
            out["bpm"] = float(bpm)
            out["bpm_source"] = "analyzed"
        if key_name is not None:
            out["key"] = key_name
        if camelot is not None:
            out["camelot"] = camelot
        return out

    def _estimate_bpm(self, mono: np.ndarray, sr: int) -> Optional[float]:
        # Simple onset-strength autocorrelation tempo estimate.
        if mono.size < sr:
            return None

        # Envelope from absolute derivative.
        x = np.diff(mono)
        env = np.abs(x)
        win = int(0.02 * sr)
        win = max(8, win)
        env = signal.lfilter(np.ones(win) / win, [1.0], env)

        hop = int(0.01 * sr)
        hop = max(1, hop)
        env = env[::hop]

        env = env - np.mean(env)
        denom = np.std(env) + 1e-8
        env = env / denom

        # Autocorrelation over reasonable BPM range.
        min_bpm, max_bpm = 70.0, 180.0
        min_lag = int((60.0 / max_bpm) * (sr / hop))
        max_lag = int((60.0 / min_bpm) * (sr / hop))
        if max_lag <= min_lag + 2:
            return None

        ac = signal.correlate(env, env, mode="full")
        ac = ac[ac.size // 2 :]

        window = ac[min_lag:max_lag]
        if window.size == 0:
            return None
        lag = int(np.argmax(window)) + min_lag
        bpm = 60.0 / (lag * (hop / sr))

        # Normalize to preferred range by doubling/halving.
        while bpm < min_bpm:
            bpm *= 2.0
        while bpm > max_bpm:
            bpm /= 2.0
        return float(bpm)

    def _estimate_key_and_camelot(self, mono: np.ndarray, sr: int) -> Tuple[Optional[str], Optional[str]]:
        # Rough chroma-based key detection.
        if mono.size < sr:
            return None, None

        n_fft = 4096
        hop = 1024
        _, _, Zxx = signal.stft(mono, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, window="hann")
        mag = np.abs(Zxx)

        freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
        valid = (freqs >= 40.0) & (freqs <= 5000.0)
        freqs = freqs[valid]
        mag = mag[valid, :]

        # Map each frequency bin to a pitch class.
        midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
        pc = (np.round(midi).astype(int)) % 12

        chroma = np.zeros(12, dtype=np.float64)
        for i in range(mag.shape[0]):
            chroma[pc[i]] += float(np.mean(mag[i, :]))

        if np.allclose(chroma.sum(), 0.0):
            return None, None
        chroma = chroma / (chroma.sum() + 1e-9)

        # Krumhansl-Schmuckler profiles.
        major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        major = major / major.sum()
        minor = minor / minor.sum()

        best = (None, None, -1.0)
        for root in range(12):
            maj_prof = np.roll(major, root)
            min_prof = np.roll(minor, root)
            maj_score = float(np.dot(chroma, maj_prof))
            min_score = float(np.dot(chroma, min_prof))
            if maj_score > best[2]:
                best = (root, "major", maj_score)
            if min_score > best[2]:
                best = (root, "minor", min_score)

        root, mode, _ = best
        if root is None:
            return None, None
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        key_name = f"{names[int(root)]} {'maj' if mode == 'major' else 'min'}"
        camelot = self._camelot_for_key(int(root), mode)
        return key_name, camelot

    def _camelot_for_key(self, root_pc: int, mode: str) -> Optional[str]:
        # Camelot wheel mapping by circle-of-fifths position.
        # This uses the standard mapping where 8B=C major and 5A=C minor.
        camelot_major = {
            0: "8B",
            7: "9B",
            2: "10B",
            9: "11B",
            4: "12B",
            11: "1B",
            6: "2B",
            1: "3B",
            8: "4B",
            3: "5B",
            10: "6B",
            5: "7B",
        }
        camelot_minor = {
            0: "5A",
            7: "6A",
            2: "7A",
            9: "8A",
            4: "9A",
            11: "10A",
            6: "11A",
            1: "12A",
            8: "1A",
            3: "2A",
            10: "3A",
            5: "4A",
        }
        if mode == "major":
            return camelot_major.get(root_pc)
        return camelot_minor.get(root_pc)
