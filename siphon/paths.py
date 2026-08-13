"""Central location for Siphon's on-disk paths (overridable via env)."""

from __future__ import annotations

import os
from pathlib import Path


def base_dir() -> Path:
    """Root for all Siphon data (~/.siphon by default)."""
    override = os.environ.get("SIPHON_HOME")
    return Path(override) if override else (Path.home() / ".siphon")


def downloads_dir() -> Path:
    return base_dir() / "downloads"


def bin_dir() -> Path:
    """Where an auto-downloaded ffmpeg lives."""
    override = os.environ.get("SIPHON_BIN_DIR")
    return Path(override) if override else (base_dir() / "bin")


def pot_server_home() -> Path:
    """The built bgutil POT server (…/server)."""
    override = os.environ.get("SIPHON_POT_SERVER_HOME")
    if override:
        return Path(override)
    return Path.home() / "bgutil-ytdlp-pot-provider" / "server"
