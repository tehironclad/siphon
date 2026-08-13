#!/usr/bin/env python3
"""Frozen-app entry point.

PyInstaller runs its entry script as the top-level ``__main__`` module with no
package context, so ``siphon/__main__.py`` (which uses relative imports) can't
be the entry. This top-level shim imports the package absolutely instead.

It also repairs ``sys.stdout``/``sys.stderr``, which are ``None`` in a windowed
(console-less) build — otherwise anything that touches them (uvicorn's logger
calling ``sys.stdout.isatty()``, ``print``, ``logging``) crashes at startup.
"""

import os
import sys
from pathlib import Path


def _ensure_streams() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        d = Path(os.environ.get("SIPHON_HOME") or (Path.home() / ".siphon"))
        d.mkdir(parents=True, exist_ok=True)
        sink = open(d / "siphon.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        sink = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


_ensure_streams()

from siphon.__main__ import main

if __name__ == "__main__":
    main()
