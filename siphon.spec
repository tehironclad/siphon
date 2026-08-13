# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Siphon — bundles ffmpeg, Node, and the POT server."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
STAGE = ROOT / "build_assets"

# Bundle the app UI + the three runtimes staged by build.py.
datas = [(str(ROOT / "siphon" / "static"), "siphon/static")]
for name in ("ffmpeg", "node", "pot-server"):
    d = STAGE / name
    if d.exists():
        datas.append((str(d), name))

# Collect the app's own submodules (route handlers import them lazily, which
# PyInstaller's static graph can miss) plus the server stack's runtime deps.
hiddenimports = collect_submodules("siphon")
hiddenimports += [
    "h11", "httptools", "websockets", "websockets.legacy",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on", "uvicorn.loops.asyncio", "uvicorn.loops.auto",
]

# Fully collect the server stack, yt-dlp, and the bgutil POT plugin (a namespace
# package PyInstaller won't find on its own).
for pkg in ("uvicorn", "starlette", "fastapi", "anyio",
            "yt_dlp", "yt_dlp_plugins", "bgutil_ytdlp_pot_provider"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        hiddenimports += h
    except Exception:
        pass

# pywebview is optional (browser fallback), collect if present.
try:
    d, b, h = collect_all("webview")
    datas += d
    hiddenimports += h
except Exception:
    pass

block_cipher = None

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "torch"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="Siphon", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(ROOT / "siphon" / "static" / "icon.ico") if (ROOT / "siphon" / "static" / "icon.ico").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="Siphon")

# macOS .app bundle
import sys
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Siphon.app", icon=None, bundle_identifier="dev.siphon.app")
