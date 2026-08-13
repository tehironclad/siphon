"""bgutil PO-token provider integration.

YouTube gates HD/4K streams behind the SABR experiment, which needs a per-video
PO token. yt-dlp fetches those via the bgutil provider — a plugin that talks to
a small local Node server (default http://127.0.0.1:4416). This module ensures
that server is running so downloads reach 4K instead of falling back to 360p.

One-time setup:  python -m siphon.setup_pot
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import urllib.request
from typing import Optional

from .paths import pot_server_home

logger = logging.getLogger(__name__)

POT_PORT = 4416
POT_PING_URL = f"http://127.0.0.1:{POT_PORT}/ping"

_started: Optional[subprocess.Popen] = None


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

    node = shutil.which("node")
    main_js = pot_server_home() / "build" / "main.js"
    if not node or not main_js.exists():
        logger.warning(
            "PO-token server unavailable (node=%s, server=%s). 4K may fall back "
            "to 360p. Run once:  python -m siphon.setup_pot",
            bool(node), main_js.exists(),
        )
        return False

    try:
        _started = subprocess.Popen(
            [node, str(main_js)], cwd=str(pot_server_home()),
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
