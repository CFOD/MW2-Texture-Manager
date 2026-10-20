# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

# customtkinter ships its theme JSON files as package data; tkinterdnd2 ships
# a native Tcl/tkdnd extension. Both need to be picked up explicitly since
# PyInstaller's default analysis only follows Python imports.
import os

datas = [('texconv.exe', '.'), ('libsquish.dll', '.'), ('icon.ico', '.')]

# iwi2dds.exe / imgXiwi.exe are third-party tools we don't redistribute, so
# public builds leave them out and users place them beside the EXE. Set
# MW2_BUNDLE_EXTERNAL=1 to embed them in a private, all-in-one build.
if os.environ.get('MW2_BUNDLE_EXTERNAL') == '1':
    datas += [('iwi2dds.exe', '.'), ('imgXiwi.exe', '.')]
datas += collect_data_files('customtkinter')
datas += collect_data_files('tkinterdnd2')

# Upscaler (Real-ESRGAN ncnn-vulkan) ships as its own subfolder — exe, its
# vcomp140 runtime DLL, and the model weights — rather than flat files, so it
# needs its own datas entry preserving that folder structure under upscaler/.
datas += [('upscaler/realesrgan-ncnn-vulkan.exe', 'upscaler'),
          ('upscaler/vcomp140.dll', 'upscaler'),
          ('upscaler/models/realesrgan-x4plus.bin', 'upscaler/models'),
          ('upscaler/models/realesrgan-x4plus.param', 'upscaler/models')]

a = Analysis(
    ['mw2_upscale_assistant.py'],
    pathex=[],
    binaries=[],
    datas=datas,
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
    name='MW2_Tool',
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
    icon=['icon.ico'],
)
