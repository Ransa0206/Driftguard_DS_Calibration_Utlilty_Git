# -*- mode: python ; coding: utf-8 -*-

EXCLUDE_MODULES = [
    'pip',
]

datas = [
    ("data/icon_drift_guard_main.ico", "data"),
]

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DriftguardCB",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    min_size=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["data/icon_drift_guard_main.ico"],
    version="version.txt",
)