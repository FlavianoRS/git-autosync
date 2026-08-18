# -*- mode: python ; coding: utf-8 -*-
import platform

# Windows: sem console (janela/tray). Linux: com console, pra CLI funcionar
# quando alguem roda o binario direto do terminal (sem GUI/janela propria pra
# mostrar a saida de texto).
IS_WINDOWS = platform.system() == "Windows"

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('VERSION', '.'), ('assets/icon.ico', 'assets'), ('assets/icon.png', 'assets')],
    hiddenimports=['customtkinter', 'assets.generate_icon'],
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
    name='git-autosync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=not IS_WINDOWS,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if IS_WINDOWS else None,
)
