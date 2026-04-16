# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\dms\\interfaces\\gui\\app.py'],
    pathex=[],
    binaries=[('bin/exiftool.exe', 'bin')],
    datas=[('src/dms/data', 'dms/data'), ('bin/exiftool_files', 'bin/exiftool_files')],
    hiddenimports=[],
    hookspath=['hooks/'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas', 'IPython', 'jupyter', 'notebook', 'PyQt5', 'wx', 'gi'],
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
    name='DMS_Portable',
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
    icon=['src\\dms\\data\\icon.ico'],
)
