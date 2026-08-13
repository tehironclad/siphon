"""Launch Siphon as a desktop window (pywebview), or fall back to the browser."""

from __future__ import annotations

import logging
import threading
import time
import urllib.request

from .server import create_app

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8677


def _serve() -> None:
    import uvicorn
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


def _wait_ready(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def main(browser: bool = False) -> None:
    url = f"http://{HOST}:{PORT}/"
    threading.Thread(target=_serve, daemon=True).start()
    _wait_ready(f"http://{HOST}:{PORT}/api/health")

    if not browser:
        try:
            import webview  # pywebview
            webview.create_window("Siphon", url, width=880, height=920, min_size=(560, 640))
            webview.start()
            return
        except Exception as e:
            logger.warning("Desktop window unavailable (%s) — opening browser.", e)

    import webbrowser
    webbrowser.open(url)
    print(f"Siphon running at {url}  (Ctrl+C to quit)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
