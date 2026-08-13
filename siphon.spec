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

# yt-dlp + the bgutil POT plugin must be fully collected (plugins are a
# namespace package PyInstaller won't find on its own).
hiddenimports = ["siphon", "siphon.server", "siphon.launcher"]
hiddenimports += collect_submodules("uvicorn")
for pkg in ("yt_dlp", "yt_dlp_plugins", "bgutil_ytdlp_pot_provider"):
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
    [str(ROOT / "siphon" / "__main__.py")],
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
