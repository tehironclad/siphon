"""Minimal ffprobe wrapper — duration, resolution, fps for a local file."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .ffmpeg_tools import ffprobe, subprocess_kwargs

logger = logging.getLogger(__name__)


def _run_ffprobe(path: Path) -> Optional[dict]:
    cmd = [ffprobe(), "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                           **subprocess_kwargs())
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def _video_stream(data: dict) -> Optional[dict]:
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def _duration(data: dict) -> float:
    for src in (data.get("format", {}), _video_stream(data) or {}):
        d = src.get("duration")
        if d:
            try:
                return float(d)
            except (ValueError, TypeError):
                pass
    return 0.0


def _fps(stream: dict) -> float:
    for key in ("r_frame_rate", "avg_frame_rate"):
        val = stream.get(key, "")
        if "/" in val:
            try:
                num, den = val.split("/")
                fps = float(num) / float(den)
                if fps > 0:
                    return round(fps, 3)
            except (ValueError, ZeroDivisionError):
                pass
    return 30.0


def _resolution(stream: dict) -> tuple[int, int]:
    try:
        return int(stream.get("width", 0)), int(stream.get("height", 0))
    except (ValueError, TypeError):
        return (0, 0)


def probe(path: Path) -> tuple[float, tuple[int, int], float]:
    """Return (duration_seconds, (width, height), fps)."""
    data = _run_ffprobe(path)
    if not data:
        return 0.0, (0, 0), 0.0
    vs = _video_stream(data)
    if not vs:
        return _duration(data), (0, 0), 0.0
    return _duration(data), _resolution(vs), _fps(vs)
