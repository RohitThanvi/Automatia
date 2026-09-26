# PyInstaller spec for the PC Agent (Phase 8).
#
# Build with (from the project root, inside the activated venv):
#   pyinstaller build/pyinstaller.spec --distpath dist --workpath build/work
#
# --onedir, deliberately not --onefile: this project pulls in
# faster-whisper/ctranslate2, mediapipe, torch (via faster-whisper's
# CTranslate2 backend on some platforms), and OpenCV — each with large
# native binaries and data files. A single-file exe would have to
# unpack all of that to a temp directory on every launch, which is
# slower to start and harder to debug than a plain folder of files.
#
# This spec builds TWO entry points sharing one set of dependencies:
# the agent (main.py) and the tray launcher (tray.py) — the tray icon
# is meant to be the thing users actually double-click, and it starts
# the agent as a subprocess (see tray.py), so both need to exist as
# real executables in the same dist folder.

# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).parent

# Data files that don't get auto-discovered by PyInstaller's import
# analysis: config.yaml (read from disk at runtime, not imported),
# and openwakeword/mediapipe's bundled model files.
datas = [
    (str(PROJECT_ROOT / "config.yaml"), "."),
]

try:
    from PyInstaller.utils.hooks import collect_data_files

    datas += collect_data_files("openwakeword")
    datas += collect_data_files("mediapipe")
except Exception:
    pass  # collected at build time only; missing packages fail loudly at pyinstaller invocation instead

hiddenimports = [
    "faster_whisper",
    "ctranslate2",
    "openwakeword",
    "pywinauto",
    "pywinauto.uia_defines",
    "win32com.client",  # used indirectly via pywinauto's UIA backend on Windows
    "pystray._win32",
]

agent_analysis = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

tray_analysis = Analysis(
    [str(PROJECT_ROOT / "tray.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

dashboard_analysis = Analysis(
    [str(PROJECT_ROOT / "dashboard" / "server.py")],
    pathex=[str(PROJECT_ROOT)],
    datas=datas,
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

MERGE(
    (agent_analysis, "main", "main"),
    (tray_analysis, "tray", "tray"),
    (dashboard_analysis, "dashboard_server", "dashboard_server"),
)

agent_pyz = PYZ(agent_analysis.pure, agent_analysis.zipped_data, cipher=block_cipher)
tray_pyz = PYZ(tray_analysis.pure, tray_analysis.zipped_data, cipher=block_cipher)
dashboard_pyz = PYZ(dashboard_analysis.pure, dashboard_analysis.zipped_data, cipher=block_cipher)

agent_exe = EXE(
    agent_pyz, agent_analysis.scripts, [],
    exclude_binaries=True, name="pc_agent", console=True,
)
tray_exe = EXE(
    tray_pyz, tray_analysis.scripts, [],
    exclude_binaries=True, name="pc_agent_tray", console=False,  # no console window for the tray icon
)
dashboard_exe = EXE(
    dashboard_pyz, dashboard_analysis.scripts, [],
    exclude_binaries=True, name="pc_agent_dashboard", console=True,
)

coll = COLLECT(
    agent_exe, agent_analysis.binaries, agent_analysis.zipfiles, agent_analysis.datas,
    tray_exe, tray_analysis.binaries, tray_analysis.zipfiles, tray_analysis.datas,
    dashboard_exe, dashboard_analysis.binaries, dashboard_analysis.zipfiles, dashboard_analysis.datas,
    strip=False,
    upx=False,  # UPX-compressing ML native libs (onnxruntime, ctranslate2) causes more startup issues than it saves in size
    name="PC_Agent",
)
