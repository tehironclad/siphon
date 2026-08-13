#!/usr/bin/env python3
"""Build a self-contained Siphon desktop app with PyInstaller.

Stages three bundled runtimes so the shipped app needs nothing preinstalled:
  * ffmpeg   — static build (merges 4K streams)
  * node     — portable Node runtime (runs the PO-token server)
  * pot-server — the built bgutil token server (unlocks 4K)

Usage:
    python build.py                # build for the current OS
    python build.py --skip-stage   # reuse already-staged assets

CI (.github/workflows/build.yml) calls this on Windows + macOS runners.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGE = ROOT / "build_assets"
POT_VERSION_FALLBACK = "1.3.1"
POT_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"


def run(cmd, **kw):
    print("+ " + " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kw)


def tool(name: str) -> str:
    return shutil.which(name) or name


# --- staging ---------------------------------------------------------------

def stage_ffmpeg() -> None:
    dest = STAGE / "ffmpeg"
    dest.mkdir(parents=True, exist_ok=True)
    print("== Staging ffmpeg ==", flush=True)
    os.environ["SIPHON_BIN_DIR"] = str(dest)
    from siphon.ffmpeg_tools import install_ffmpeg
    if install_ffmpeg(progress=lambda p, m: None) is None:
        raise SystemExit("ffmpeg staging failed")


def stage_node() -> None:
    dest = STAGE / "node"
    dest.mkdir(parents=True, exist_ok=True)
    print("== Staging Node runtime ==", flush=True)
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js not found on PATH — required to build.")
    # Copy the node binary (and, on Windows, nothing else is needed to run JS).
    exe = "node.exe" if os.name == "nt" else "node"
    shutil.copy2(node, dest / exe)
    if os.name != "nt":
        os.chmod(dest / exe, 0o755)


def stage_pot_server() -> None:
    dest = STAGE / "pot-server"
    print("== Staging PO-token server ==", flush=True)
    try:
        from importlib.metadata import version
        ver = version("bgutil-ytdlp-pot-provider")
    except Exception:
        ver = POT_VERSION_FALLBACK

    work = ROOT / ".pot-build"
    if not (work / "server").exists():
        if work.exists():
            shutil.rmtree(work)
        run([tool("git"), "clone", "--depth", "1", "--branch", ver, POT_REPO, str(work)])
    server = work / "server"
    run([tool("npm"), "install"], cwd=str(server))
    run([tool("npx"), "tsc"], cwd=str(server))
    if not (server / "build" / "main.js").exists():
        raise SystemExit("POT server build failed")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    # Runtime needs build/ + node_modules/ + package.json.
    shutil.copytree(server / "build", dest / "build")
    shutil.copytree(server / "node_modules", dest / "node_modules")
    shutil.copy2(server / "package.json", dest / "package.json")


def stage_all() -> None:
    STAGE.mkdir(exist_ok=True)
    stage_ffmpeg()
    stage_node()
    stage_pot_server()


def pyinstaller() -> None:
    print("== PyInstaller ==", flush=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "siphon.spec")])
    out = ROOT / "dist" / "Siphon"
    print(f"\n✓ Built: {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-stage", action="store_true", help="Reuse staged assets")
    args = ap.parse_args()
    print(f"Building Siphon for {platform.system()} {platform.machine()}", flush=True)
    if not args.skip_stage:
        stage_all()
    pyinstaller()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
