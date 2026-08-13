"""One-time setup for reliable 4K: install the bgutil PO-token provider.

Installs the yt-dlp plugin and clones + builds its Node token server. Run once
per machine, inside Siphon's environment:

    python -m siphon.setup_pot

Prerequisites (install yourself): Node.js 18+ and ffmpeg (ffmpeg can also be
auto-installed from the app).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_DEFAULT_VERSION = "1.3.1"
_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
_HOME = Path.home() / "bgutil-ytdlp-pot-provider"


def _run(cmd: list[str], **kw) -> None:
    print("+ " + " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def _tool(name: str) -> str:
    return shutil.which(name) or name


def _plugin_version() -> str:
    try:
        from importlib.metadata import version
        return version("bgutil-ytdlp-pot-provider")
    except Exception:
        return _DEFAULT_VERSION


def main() -> int:
    print("== Installing bgutil PO-token provider plugin ==", flush=True)
    _run([sys.executable, "-m", "pip", "install",
          f"bgutil-ytdlp-pot-provider=={_plugin_version()}"])

    if not shutil.which("node"):
        print("\nERROR: Node.js not found on PATH. Install Node 18+ and re-run:\n"
              "  Windows:  winget install OpenJS.NodeJS.LTS\n"
              "  macOS:    brew install node\n"
              "  Debian:   sudo apt install nodejs npm", file=sys.stderr)
        return 1

    version = _plugin_version()
    print(f"\n== Building bgutil POT server v{version} at {_HOME} ==", flush=True)
    server = _HOME / "server"
    if not server.exists():
        _run([_tool("git"), "clone", "--depth", "1", "--branch", version, _REPO, str(_HOME)])
    _run([_tool("npm"), "install"], cwd=str(server))
    _run([_tool("npx"), "tsc"], cwd=str(server))

    if not (server / "build" / "main.js").exists():
        print("\nERROR: build did not produce build/main.js", file=sys.stderr)
        return 1

    if not shutil.which("ffmpeg"):
        print("\nNOTE: ffmpeg not found — Siphon can auto-install it from the app, "
              "or install it yourself (winget/brew/apt).", file=sys.stderr)

    print("\n✓ Setup complete. Siphon will auto-start the token server and "
          "download in up to 4K.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
