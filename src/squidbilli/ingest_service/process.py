import multiprocessing as mp
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from squidbilli.library import TrackLibrary, default_cache_root, track_id_for_path


@dataclass
class IngestStatus:
    job_id: str
    state: str
    message: str
    progress: float
    url: str
    local_path: str | None
    track_id: str | None


def _safe_filename(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-zA-Z0-9 _\-\.\(\)\[\]]+", "", s)
    s = s.strip().strip(".")
    if not s:
        return "track"
    return s


def _emit_status(status_q: mp.Queue, status: IngestStatus):
    try:
        status_q.put_nowait(status)
    except Exception:
        pass


def _ingest_worker_main(cmd_q: mp.Queue, status_q: mp.Queue):
    library = TrackLibrary(cache_root=default_cache_root())

    try:
        from yt_dlp import YoutubeDL
    except Exception:
        YoutubeDL = None

    running = True
    while running:
        cmd = None
        try:
            cmd = cmd_q.get(timeout=0.05)
        except Exception:
            cmd = None

        if not cmd:
            continue

        c = cmd.get("cmd")
        if c == "shutdown":
            running = False
            continue

        if c != "import_url":
            continue

        url = str(cmd.get("url") or "").strip()
        if not url:
            continue

        job_id = str(cmd.get("job_id") or uuid.uuid4().hex)
        target_dir = Path(cmd.get("target_dir") or (Path.home() / "Music" / "SquidBilli Imports"))
        target_dir.mkdir(parents=True, exist_ok=True)

        _emit_status(
            status_q,
            IngestStatus(
                job_id=job_id,
                state="starting",
                message="Starting import...",
                progress=0.0,
                url=url,
                local_path=None,
                track_id=None,
            ),
        )

        if YoutubeDL is None:
            _emit_status(
                status_q,
                IngestStatus(
                    job_id=job_id,
                    state="error",
                    message="yt-dlp is not installed",
                    progress=0.0,
                    url=url,
                    local_path=None,
                    track_id=None,
                ),
            )
            continue

        final_path: Path | None = None

        def hook(d):
            nonlocal final_path
            try:
                st = str(d.get("status") or "")
                if st == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes")
                    p = 0.0
                    if total and downloaded is not None:
                        try:
                            p = float(downloaded) / float(total)
                        except Exception:
                            p = 0.0
                    _emit_status(
                        status_q,
                        IngestStatus(
                            job_id=job_id,
                            state="downloading",
                            message="Downloading...",
                            progress=max(0.0, min(1.0, float(p))),
                            url=url,
                            local_path=str(final_path) if final_path else None,
                            track_id=None,
                        ),
                    )
                elif st == "finished":
                    fp = d.get("filename")
                    if fp:
                        final_path = Path(fp)
                    _emit_status(
                        status_q,
                        IngestStatus(
                            job_id=job_id,
                            state="downloaded",
                            message="Download finished",
                            progress=1.0,
                            url=url,
                            local_path=str(final_path) if final_path else None,
                            track_id=None,
                        ),
                    )
            except Exception:
                pass

        outtmpl = str(target_dir / "%(title)s - %(uploader)s [%(id)s].%(ext)s")

        ydl_opts = {
            "outtmpl": outtmpl,
            "quiet": True,
            "noprogress": True,
            "progress_hooks": [hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }
            ],
            "postprocessor_args": ["-ar", "44100"],
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if isinstance(info, dict):
                    fn = ydl.prepare_filename(info)
                    p = Path(fn)
                    mp3 = p.with_suffix(".mp3")
                    if mp3.exists():
                        final_path = mp3
                    elif p.exists():
                        final_path = p
        except Exception as e:
            _emit_status(
                status_q,
                IngestStatus(
                    job_id=job_id,
                    state="error",
                    message=f"Download failed: {e}",
                    progress=0.0,
                    url=url,
                    local_path=None,
                    track_id=None,
                ),
            )
            continue

        if final_path is None or (not final_path.exists()):
            _emit_status(
                status_q,
                IngestStatus(
                    job_id=job_id,
                    state="error",
                    message="Download produced no file",
                    progress=0.0,
                    url=url,
                    local_path=None,
                    track_id=None,
                ),
            )
            continue

        try:
            sz = final_path.stat().st_size
            if sz <= 0:
                raise RuntimeError("Downloaded file is empty")
        except Exception as e:
            _emit_status(
                status_q,
                IngestStatus(
                    job_id=job_id,
                    state="error",
                    message=f"Invalid file: {e}",
                    progress=0.0,
                    url=url,
                    local_path=str(final_path),
                    track_id=None,
                ),
            )
            continue

        try:
            tid = track_id_for_path(final_path)
        except Exception:
            tid = None

        _emit_status(
            status_q,
            IngestStatus(
                job_id=job_id,
                state="analyzing",
                message="Analyzing BPM/key...",
                progress=0.0,
                url=url,
                local_path=str(final_path),
                track_id=tid,
            ),
        )

        if tid is not None:
            try:
                library.update_meta(
                    tid,
                    {
                        "source_url": url,
                        "source": "ingest",
                        "imported_at": float(time.time()),
                    },
                )
            except Exception:
                pass

            try:
                updates = library._analyze_track(final_path)
                if updates:
                    library.update_meta(tid, dict(updates))
            except Exception:
                pass

        _emit_status(
            status_q,
            IngestStatus(
                job_id=job_id,
                state="done",
                message="Imported",
                progress=1.0,
                url=url,
                local_path=str(final_path),
                track_id=tid,
            ),
        )


class IngestController:
    def __init__(self):
        ctx = mp.get_context("spawn")
        self._cmd_q: mp.Queue = ctx.Queue()
        self._status_q: mp.Queue = ctx.Queue()
        self._proc = ctx.Process(target=_ingest_worker_main, args=(self._cmd_q, self._status_q), daemon=True)
        self._last_status: IngestStatus | None = None

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

    def poll_status(self) -> IngestStatus | None:
        s = None
        for _ in range(64):
            try:
                s = self._status_q.get_nowait()
            except Exception:
                break
        if s is not None:
            self._last_status = s
        return self._last_status

    def import_url(self, url: str, *, target_dir: str | None = None, job_id: str | None = None):
        payload = {"cmd": "import_url", "url": str(url), "job_id": job_id or uuid.uuid4().hex}
        if target_dir is not None:
            payload["target_dir"] = str(target_dir)
        self._cmd_q.put(payload)
        return payload["job_id"]
