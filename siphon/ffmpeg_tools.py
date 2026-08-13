"""Locate ffmpeg/ffprobe, and auto-download a static build when missing.

Lookup order: PATH → PyInstaller bundle → app-managed bin dir → (Windows)
known install locations → bare name. If nothing is found, ``install_ffmpeg``
fetches a verified static build into the managed bin dir.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from .paths import bin_dir

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]

_URLS = {
    "Windows": {"ffmpeg": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"},
    "Darwin": {
        "ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/zip",
        "ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    },
    "Linux": {"ffmpeg": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"},
}


def subprocess_kwargs() -> dict:
    """Suppress console windows on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _search_bundled(name: str) -> Optional[str]:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    for ext in ("", ".exe"):
        cand = Path(meipass) / "ffmpeg" / f"{name}{ext}"
        if cand.is_file():
            return str(cand)
    return None


def _search_managed(name: str) -> Optional[str]:
    cand = bin_dir() / _exe(name)
    return str(cand) if cand.is_file() else None


def _search_windows(name: str) -> Optional[str]:
    exe = f"{name}.exe"
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.environ.get("USERPROFILE", "")
    dirs = []
    if local:
        dirs += [os.path.join(local, r"Microsoft\WinGet\Links"),
                 os.path.join(local, r"Microsoft\WinGet\Packages")]
    dirs += [r"C:\Program Files\WinGet\Links", r"C:\ProgramData\chocolatey\bin",
             r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"]
    if profile:
        dirs.append(os.path.join(profile, r"scoop\apps\ffmpeg\current\bin"))
    for base in dirs:
        bp = Path(base)
        if not bp.exists():
            continue
        direct = bp / exe
        if direct.is_file():
            return str(direct)
        for match in bp.rglob(exe):
            if match.is_file():
                return str(match)
    return None


@lru_cache(maxsize=4)
def find_ff(name: str = "ffmpeg") -> str:
    """Full path to an ffmpeg-family executable (bare name as last resort)."""
    found = shutil.which(name)
    if found:
        return found
    found = _search_bundled(name)
    if found:
        return found
    found = _search_managed(name)
    if found:
        return found
    if os.name == "nt":
        found = _search_windows(name)
        if found:
            return found
    return name


def ffmpeg() -> str:
    return find_ff("ffmpeg")


def ffprobe() -> str:
    return find_ff("ffprobe")


def check_ffmpeg() -> bool:
    try:
        subprocess.run([ffmpeg(), "-version"], capture_output=True, timeout=5,
                       **subprocess_kwargs())
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# --- auto-install ----------------------------------------------------------

def can_auto_install() -> bool:
    return platform.system() in _URLS


def _fetch(url: str, report: ProgressCallback, base: float, span: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Siphon"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        buf, read = io.BytesIO(), 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            read += len(chunk)
            report(base + span * (read / total) if total else -1, "Downloading ffmpeg…")
    return buf.getvalue()


def _extract(data: bytes, wanted: set[str], dest: Path) -> list[str]:
    written = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                b = Path(info.filename).name
                if b in wanted:
                    (dest / b).write_bytes(zf.read(info))
                    written.append(b)
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for m in tf.getmembers():
                b = Path(m.name).name
                if m.isfile() and b in wanted:
                    src = tf.extractfile(m)
                    if src is not None:
                        (dest / b).write_bytes(src.read())
                        written.append(b)
    return written


def install_ffmpeg(progress: Optional[ProgressCallback] = None) -> Optional[str]:
    """Download a verified static ffmpeg+ffprobe into the managed bin dir."""
    def report(pct: float, msg: str) -> None:
        if progress:
            try:
                progress(pct, msg)
            except Exception:
                pass

    urls = _URLS.get(platform.system())
    if not urls:
        report(0, f"Unsupported platform: {platform.system()}")
        return None

    dest = bin_dir()
    dest.mkdir(parents=True, exist_ok=True)
    want = {_exe("ffmpeg"), _exe("ffprobe")}
    report(0, "Fetching ffmpeg…")

    try:
        archives = list(urls.items())
        n = len(archives)
        got: set[str] = set()
        for i, (_k, url) in enumerate(archives):
            data = _fetch(url, report, base=i / n * 85, span=85 / n)
            report(88, "Unpacking…")
            got.update(_extract(data, want, dest))

        if _exe("ffmpeg") not in got:
            report(0, "Archive missing ffmpeg")
            return None

        if os.name != "nt":
            for nm in want:
                f = dest / nm
                if f.exists():
                    f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        report(95, "Verifying…")
        ff = dest / _exe("ffmpeg")
        r = subprocess.run([str(ff), "-version"], capture_output=True, timeout=15,
                           **subprocess_kwargs())
        if r.returncode != 0:
            report(0, "Downloaded ffmpeg failed to run")
            return None

        find_ff.cache_clear()
        report(100, "ffmpeg ready")
        logger.info("Installed managed ffmpeg at %s", ff)
        return str(ff)
    except Exception as e:
        logger.exception("ffmpeg auto-install failed")
        report(0, f"Install failed: {e}")
        return None
