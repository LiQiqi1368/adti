# -*- mode: python ; coding: utf-8 -*-
# 授权工具打包配置（独立 exe，可单独发给用户）

from pathlib import Path
# 基于 spec 文件自身位置定位
import sys
import os
project_dir = Path(os.path.dirname(os.path.abspath(sys.argv[0]))).resolve() if '__file__' not in dir() else Path('.').resolve()
block_cipher = None

a = Analysis(
    [str(project_dir / "授权工具" / "generate_license.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="授权码生成工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    icon=str(project_dir / "icon.ico"),
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="授权码生成工具",
)
