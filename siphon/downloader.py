"""Video downloader — yt-dlp wrapper with reliable 4K.

Defeats YouTube's SABR/360p fallback with three things working together:
  * this interpreter's yt_dlp (so the bgutil PO-token plugin loads),
  * a JS runtime (--js-runtimes) + the EJS challenge solver, and
  * a strict resolution floor with retries, so a transient PO-token miss
    ERRORS and retries instead of silently delivering 360p.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .ffmpeg_tools import check_ffmpeg, ffmpeg, subprocess_kwargs
from .paths import downloads_dir
from .probe import probe

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)%")

RES_4K, RES_1440, RES_1080, RES_720 = 2160, 1440, 1080, 720
_MAX_ATTEMPTS = 4  # for HD/4K requests, to ride out PO-token misses


def _ytdlp_cmd() -> list[str]:
    """Prefer this interpreter's yt_dlp so the bundled POT plugin loads."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def _js_runtime_args() -> list[str]:
    for rt in ("deno", "node"):
        if shutil.which(rt):
            return ["--js-runtimes", rt]
    return []


def _remote_components_args() -> list[str]:
    if os.environ.get("SIPHON_NO_REMOTE_COMPONENTS"):
        return []
    return ["--remote-components", "ejs:github"]


def _relaxed_format(max_height: Optional[int], prefer_mp4: bool) -> str:
    if max_height is None:
        return ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                if prefer_mp4 else "bestvideo+bestaudio/best")
    h = int(max_height)
    if prefer_mp4:
        return (f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height<={h}][ext=mp4]/best[height<={h}]/best")
    return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"


def _strict_format(max_height: int, prefer_mp4: bool) -> str:
    """No fallback — errors (→ retry) if the tier isn't downloadable."""
    ext = "[ext=mp4]" if prefer_mp4 else ""
    aud = "[ext=m4a]" if prefer_mp4 else ""
    return f"bestvideo[height>={max_height}]{ext}+bestaudio{aud}"


def _merge_container(max_height: Optional[int], prefer_mp4: bool) -> str:
    if prefer_mp4:
        return "mp4"
    if max_height is not None and max_height <= RES_1080:
        return "mp4"
    return "mkv"


@dataclass
class ReferenceVideo:
    video_id: str
    title: str = ""
    source_url: str = ""
    local_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    duration: float = 0.0
    resolution: tuple[int, int] = (0, 0)
    fps: float = 0.0
    channel: str = ""
    view_count: int = 0
    downloaded_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id, "title": self.title, "source_url": self.source_url,
            "local_path": str(self.local_path) if self.local_path else None,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "duration": self.duration, "resolution": list(self.resolution),
            "fps": self.fps, "channel": self.channel, "view_count": self.view_count,
            "downloaded_at": self.downloaded_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReferenceVideo":
        return cls(
            video_id=d["video_id"], title=d.get("title", ""), source_url=d.get("source_url", ""),
            local_path=Path(d["local_path"]) if d.get("local_path") else None,
            audio_path=Path(d["audio_path"]) if d.get("audio_path") else None,
            duration=d.get("duration", 0.0), resolution=tuple(d.get("resolution", [0, 0])),
            fps=d.get("fps", 0.0), channel=d.get("channel", ""),
            view_count=d.get("view_count", 0), downloaded_at=d.get("downloaded_at"),
        )


def _check_ytdlp() -> bool:
    try:
        r = subprocess.run([*_ytdlp_cmd(), "--version"], capture_output=True,
                           text=True, timeout=15, **subprocess_kwargs())
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _fetch_metadata(url: str) -> Optional[dict]:
    cmd = [*_ytdlp_cmd(), *_js_runtime_args(), "--dump-json", "--no-download", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           **subprocess_kwargs())
        if r.returncode != 0:
            logger.warning("metadata fetch failed: %s", r.stderr[:200])
            return None
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning("metadata error: %s", e)
        return None


def _run_download(cmd: list[str], timeout: int, report: ProgressCallback) -> bool:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, **subprocess_kwargs())
    except FileNotFoundError:
        return False
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line.startswith("[download]"):
                m = _PCT_RE.search(line)
                if m:
                    report(10 + float(m.group(1)) * 0.78, "Downloading…")
            elif line.startswith("[Merger]") or "Merging formats" in line:
                report(90, "Merging video + audio…")
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False
    return proc.returncode == 0


class VideoDownloader:
    """Download and track videos in ~/.siphon/downloads."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else downloads_dir()
        self.video_dir = self.output_dir / "videos"
        self.audio_dir = self.output_dir / "audio"
        self.meta_path = self.output_dir / "downloads.json"

    # storage
    def _load(self) -> list[ReferenceVideo]:
        if not self.meta_path.exists():
            return []
        try:
            return [ReferenceVideo.from_dict(d) for d in json.loads(self.meta_path.read_text())]
        except (json.JSONDecodeError, KeyError):
            return []

    def _save(self, refs: list[ReferenceVideo]) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps([r.to_dict() for r in refs], indent=2))

    def _add(self, ref: ReferenceVideo) -> None:
        refs = [r for r in self._load() if r.video_id != ref.video_id]
        refs.append(ref)
        self._save(refs)

    def list_references(self) -> list[ReferenceVideo]:
        return self._load()

    def _extract_audio(self, source: Path, vid: str) -> Optional[Path]:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        out = self.audio_dir / f"{vid}.wav"
        if out.exists():
            return out
        cmd = [ffmpeg(), "-y", "-i", str(source), "-vn", "-acodec", "pcm_s16le",
               "-ar", "44100", "-ac", "2", str(out)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               **subprocess_kwargs())
            return out if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def download(self, url: str, *, resolution: Optional[int] = RES_4K,
                 prefer_mp4: bool = False, extract_audio: bool = True,
                 timeout: int = 3600,
                 progress: Optional[ProgressCallback] = None) -> Optional[ReferenceVideo]:
        def report(pct: float, msg: str) -> None:
            if progress:
                try:
                    progress(pct, msg)
                except Exception:
                    pass

        report(0, "Preparing…")
        if not _check_ytdlp():
            logger.error("yt-dlp not available")
            report(0, "yt-dlp not available")
            return None
        if not check_ffmpeg():
            logger.error("ffmpeg not found")
            report(0, "ffmpeg is required — install it first")
            return None

        # Ensure the PO-token server is up (unlocks 4K). Best-effort.
        from .pot_provider import ensure_pot_server
        report(-1, "Preparing downloader…")
        ensure_pot_server()

        report(-1, "Fetching video info…")
        meta = _fetch_metadata(url)
        if meta is None:
            report(0, "Could not read video info")
            return None

        vid = meta.get("id", "unknown")
        title = meta.get("title", "Unknown")
        channel = meta.get("channel", meta.get("uploader", ""))
        container = _merge_container(resolution, prefer_mp4)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        video_path = self.video_dir / f"{vid}.{container}"

        existing = next(self.video_dir.glob(f"{vid}.*"), None)
        if existing is not None:
            video_path = existing
            report(90, "Already downloaded")
        else:
            if not self._download_with_retry(url, resolution, prefer_mp4, container,
                                             video_path, vid, timeout, report):
                return None
            video_path = next(self.video_dir.glob(f"{vid}.*"), video_path)

        if extract_audio:
            report(94, "Extracting audio…")
        audio_path = self._extract_audio(video_path, vid) if extract_audio else None

        report(98, "Finalizing…")
        dur, res, fps = probe(video_path)
        ref = ReferenceVideo(
            video_id=vid, title=title, source_url=url, local_path=video_path,
            audio_path=audio_path, duration=dur or meta.get("duration", 0) or 0,
            resolution=res if res != (0, 0) else (meta.get("width", 0), meta.get("height", 0)),
            fps=fps or meta.get("fps", 0) or 0.0, channel=channel,
            view_count=meta.get("view_count", 0) or 0,
            downloaded_at=datetime.now().isoformat(),
        )
        self._add(ref)
        report(100, "Done")
        return ref

    def _download_with_retry(self, url, resolution, prefer_mp4, container,
                             video_path, vid, timeout, report) -> bool:
        """Download, insisting on the requested tier for HD/4K before relaxing.

        For a >=1080p request, early attempts use a strict floor so a PO-token
        miss (which drops the HD formats) ERRORS and we retry, instead of
        yt-dlp silently grabbing the 360p muxed stream. The final attempt
        relaxes so genuinely low-res videos still download.
        """
        strict = resolution is not None and resolution >= RES_1080
        attempts = _MAX_ATTEMPTS if strict else 1
        base_cmd = [*_ytdlp_cmd(), *_js_runtime_args(), *_remote_components_args()]

        for attempt in range(1, attempts + 1):
            for f in self.video_dir.glob(f"{vid}.*"):
                f.unlink()
            last = attempt == attempts
            fmt = (_relaxed_format(resolution, prefer_mp4) if last
                   else _strict_format(resolution, prefer_mp4))
            cmd = [*base_cmd, "-f", fmt, "--merge-output-format", container,
                   "--newline", "-o", str(video_path)]
            ff = ffmpeg()
            ff_dir = str(Path(ff).parent) if (os.sep in ff or "/" in ff) else None
            if ff_dir:
                cmd += ["--ffmpeg-location", ff_dir]
            cmd.append(url)

            if attempt > 1:
                report(-1, f"Retrying for full quality ({attempt}/{attempts})…")
            ok = _run_download(cmd, timeout, report)
            got = next(self.video_dir.glob(f"{vid}.*"), None)
            if ok and got:
                # On strict attempts, verify we actually hit the tier.
                if strict and not last:
                    _, (_, h), _ = probe(got)
                    if h and h >= resolution * 0.9:
                        return True
                    logger.warning("attempt %d got %sp (below %sp) — retrying",
                                   attempt, h, resolution)
                    time.sleep(3)
                    continue
                return True
            if not last:
                time.sleep(3)
        logger.error("download failed for %s after %d attempt(s)", url, attempts)
        report(0, "Download failed")
        return False
