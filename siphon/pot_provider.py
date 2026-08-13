"""bgutil PO-token provider integration.

YouTube gates HD/4K streams behind the SABR experiment, which needs a per-video
PO token. yt-dlp fetches those via the bgutil provider — a plugin that talks to
a small local Node server (default http://127.0.0.1:4416). This module ensures
that server is running so downloads reach 4K instead of falling back to 360p.

One-time setup:  python -m siphon.setup_pot
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from .paths import pot_server_home

logger = logging.getLogger(__name__)

POT_PORT = 4416
POT_PING_URL = f"http://127.0.0.1:{POT_PORT}/ping"

_started: Optional[subprocess.Popen] = None


def _bundled_node() -> Optional[str]:
    """A Node runtime bundled inside the packaged app, if present."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    exe = "node.exe" if os.name == "nt" else "node"
    for cand in (Path(meipass) / "node" / exe, Path(meipass) / "node" / "bin" / exe):
        if cand.is_file():
            return str(cand)
    return None


def _bundled_server() -> Optional[Path]:
    """The prebuilt POT server bundled inside the packaged app, if present."""
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    home = Path(meipass) / "pot-server"
    return home if (home / "build" / "main.js").is_file() else None


def _resolve_runtime() -> tuple[Optional[str], Optional[Path]]:
    """Pick (node_exe, server_home): prefer bundled, else system + setup dir."""
    bnode, bserver = _bundled_node(), _bundled_server()
    node = bnode or shutil.which("node")
    server = bserver or pot_server_home()
    return node, server


def is_running(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(POT_PING_URL, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_pot_server(wait: float = 20.0) -> bool:
    """Ensure a POT server is reachable, starting one if needed. Never raises."""
    global _started
    if is_running():
        return True

    node, server_home = _resolve_runtime()
    main_js = server_home / "build" / "main.js" if server_home else None
    if not node or main_js is None or not main_js.exists():
        logger.warning(
            "PO-token server unavailable (node=%s, server=%s). 4K may fall back "
            "to 360p. Run once:  python -m siphon.setup_pot",
            bool(node), bool(main_js and main_js.exists()),
        )
        return False

    try:
        _started = subprocess.Popen(
            [node, str(main_js)], cwd=str(server_home),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning("Failed to launch PO-token server: %s", e)
        return False

    deadline = time.time() + wait
    while time.time() < deadline:
        if is_running():
            logger.info("Started bgutil PO-token server on :%d", POT_PORT)
            return True
        if _started.poll() is not None:
            logger.warning("PO-token server exited before becoming ready")
            return False
        time.sleep(0.5)
    logger.warning("PO-token server not ready within %.0fs", wait)
    return False
