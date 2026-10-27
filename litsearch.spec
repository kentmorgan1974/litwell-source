# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Litwell.

Two layouts, chosen with the LITSEARCH_ONEFILE environment variable:

  * default (onedir):
      macOS   -> dist/Litwell.app
      Windows -> dist/Litwell/  (folder with Litwell.exe)

  * LITSEARCH_ONEFILE=1 (onefile):
      Windows -> dist/Litwell.exe   (a single file to hand to someone)
      macOS   -> dist/Litwell       (single Unix binary; the .app
                 bundle is still the better choice for distribution on Mac)

Build with:
    pyinstaller --noconfirm litsearch.spec

PyInstaller can only build FOR the platform it runs ON: run it on macOS for the
Mac build, on Windows for the Windows build. The build scripts set the env var
for you (build_windows.bat = folder, build_windows_onefile.bat = single .exe).
"""

import os
import sys

ONEFILE = os.environ.get("LITSEARCH_ONEFILE") == "1"
APP_NAME = "Litwell"
# Read the version from the package without importing it.
import re
VERSION = re.search(
    r'__version__\s*=\s*"([^"]+)"',
    open(os.path.join(SPECPATH, "litsearch", "__init__.py"), encoding="utf-8").read(),
).group(1)
# Window/Dock/taskbar icon: .ico on Windows, .icns on macOS.
ICON = (
    "litwell_icons/litwell.ico" if sys.platform.startswith("win")
    else "litwell_icons/litwell.icns" if sys.platform == "darwin"
    else None
)
block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("litwell_icons", "litwell_icons"),                        # runtime window-icon files
        ("docs/Litwell_How_To_Guide.pdf", "litwell_docs"),         # the Help / How-to Guide button
        ("LICENSE", "litwell_docs"), ("NOTICE", "litwell_docs"),
        ("THIRD_PARTY_NOTICES.md", "litwell_docs"),
    ],
    hiddenimports=["openpyxl.cell._writer"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "PIL", "pytest", "lxml",
        "matplotlib", "PyQt5", "PySide2", "tkinter.test",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_common = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no terminal window
    disable_windowed_traceback=False,
    argv_emulation=(sys.platform == "darwin"),  # macOS-only option
    target_arch=os.environ.get("LITWELL_TARGET_ARCH") or None,  # CI sets universal2 on macOS
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        runtime_tmpdir=None,
        **_common,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name=f"{APP_NAME}.app",
            icon=ICON,
            bundle_identifier="com.litwell.app",
            info_plist={
                "CFBundleName": APP_NAME,
                "NSHumanReadableCopyright": "Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Apache License 2.0.",
                "CFBundleDisplayName": APP_NAME,
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "10.13.0",
            },
        )
