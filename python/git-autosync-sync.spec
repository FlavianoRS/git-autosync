# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_sync.py'],
    pathex=[],
    binaries=[],
    # VERSION junto: sem ele o `--version` deste binario responde "desconhecida", e o
    # instalador e o diagnostico do hub nao conseguem comparar versao instalada.
    datas=[('VERSION', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='git-autosync-sync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
