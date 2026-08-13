"""Siphon's local web server — the download + ffmpeg API and the UI."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .paths import downloads_dir

logger = logging.getLogger(__name__)

_RES_MAP = {"4k": 2160, "1440": 1440, "1080": 1080, "720": 720, "best": None}

# --------------------------------------------------------------------------
# Download API
# --------------------------------------------------------------------------
download_router = APIRouter(prefix="/api/download", tags=["download"])
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


class DownloadRequest(BaseModel):
    url: str
    resolution: str = "4k"
    prefer_mp4: bool = False
    extract_audio: bool = True


def _set(job_id: str, **fields) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _ref_summary(ref) -> dict:
    w, h = ref.resolution
    return {
        "video_id": ref.video_id, "title": ref.title, "channel": ref.channel,
        "source_url": ref.source_url, "duration": ref.duration, "width": w, "height": h,
        "fps": ref.fps, "local_path": str(ref.local_path) if ref.local_path else None,
        "audio_path": str(ref.audio_path) if ref.audio_path else None,
        "view_count": ref.view_count,
    }


def _run_job(job_id: str, req: DownloadRequest) -> None:
    from .downloader import VideoDownloader

    def on_progress(pct: float, msg: str) -> None:
        _set(job_id, percent=max(0.0, min(100.0, pct)) if pct >= 0 else -1, message=msg)

    try:
        ref = VideoDownloader().download(
            req.url, resolution=_RES_MAP.get(req.resolution, 2160),
            prefer_mp4=req.prefer_mp4, extract_audio=req.extract_audio, progress=on_progress,
        )
    except Exception as e:
        logger.exception("download crashed")
        _set(job_id, status="error", error=str(e))
        return

    if ref is None:
        _set(job_id, status="error", percent=0,
             error="Download failed. Ensure ffmpeg is installed and the URL is reachable.")
        return
    _set(job_id, status="done", percent=100, message="Done", result=_ref_summary(ref))


@download_router.post("")
async def start_download(req: DownloadRequest) -> dict:
    if req.resolution not in _RES_MAP:
        raise HTTPException(400, f"Invalid resolution: {req.resolution}")
    if not req.url.strip():
        raise HTTPException(400, "URL is required")
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "url": req.url, "status": "running",
                         "percent": 0.0, "message": "Queued…", "error": None, "result": None}
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@download_router.get("/library")
async def library() -> dict:
    from .downloader import VideoDownloader
    return {"items": [_ref_summary(r) for r in VideoDownloader().list_references()]}


@download_router.get("/file/{video_id}")
async def open_file(video_id: str):
    """Return the downloaded video file for a given id (for the UI to save)."""
    vdir = downloads_dir() / "videos"
    match = next(vdir.glob(f"{video_id}.*"), None)
    if match is None or not match.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(match, filename=match.name)


@download_router.get("/{job_id}")
async def job_status(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return dict(job)


# --------------------------------------------------------------------------
# ffmpeg API (status + one-click auto-install)
# --------------------------------------------------------------------------
ffmpeg_router = APIRouter(prefix="/api/ffmpeg", tags=["ffmpeg"])
_ff_job: dict = {"status": "idle", "percent": 0.0, "message": "", "error": None}
_ff_lock = threading.Lock()


def _ff_set(**fields) -> None:
    with _ff_lock:
        _ff_job.update(fields)


@ffmpeg_router.get("/status")
async def ffmpeg_status() -> dict:
    from .ffmpeg_tools import can_auto_install, check_ffmpeg, ffmpeg, subprocess_kwargs
    import subprocess as sp
    available = check_ffmpeg()
    path = version = None
    if available:
        path = ffmpeg()
        try:
            out = sp.run([path, "-version"], capture_output=True, text=True,
                         timeout=5, **subprocess_kwargs())
            version = out.stdout.splitlines()[0] if out.stdout else None
        except Exception:
            pass
    with _ff_lock:
        installing = _ff_job.get("status") == "running"
    return {"available": available, "path": path, "version": version,
            "can_auto_install": can_auto_install(), "installing": installing}


def _run_ff_install() -> None:
    from .ffmpeg_tools import install_ffmpeg
    def on_progress(pct: float, msg: str) -> None:
        _ff_set(percent=max(0.0, min(100.0, pct)) if pct >= 0 else -1, message=msg)
    if install_ffmpeg(progress=on_progress):
        _ff_set(status="done", percent=100, message="ffmpeg ready", error=None)
    else:
        with _ff_lock:
            msg = _ff_job.get("message") or "Install failed"
        _ff_set(status="error", error=msg)


@ffmpeg_router.post("/install")
async def ffmpeg_install() -> dict:
    from .ffmpeg_tools import check_ffmpeg
    if check_ffmpeg():
        _ff_set(status="done", percent=100, message="Already installed", error=None)
        return {"status": "done"}
    with _ff_lock:
        if _ff_job.get("status") == "running":
            return {"status": "running"}
        _ff_job.update(status="running", percent=0.0, message="Starting…", error=None)
    threading.Thread(target=_run_ff_install, daemon=True).start()
    return {"status": "running"}


@ffmpeg_router.get("/install")
async def ffmpeg_install_status() -> dict:
    with _ff_lock:
        return dict(_ff_job)


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="Siphon", version=__version__)
    app.include_router(download_router)
    app.include_router(ffmpeg_router)

    @app.get("/api/health")
    async def health() -> dict:
        from .ffmpeg_tools import check_ffmpeg
        return {"ok": True, "version": __version__, "ffmpeg_available": check_ffmpeg()}

    static_dir = Path(__file__).parent / "static"
    index = static_dir / "index.html"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)))

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home():
        if index.is_file():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Siphon</h1><p>UI missing.</p>", status_code=500)

    return app


def run_server(host: str = "127.0.0.1", port: int = 8677) -> None:
    import uvicorn
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
