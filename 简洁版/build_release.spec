# -*- mode: python ; coding: utf-8 -*-
# 主程序打包配置

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
import os

# 自动获取当前目录（打包时 cwd 即为简洁版目录）
project_dir = Path(".").resolve()
block_cipher = None

# Playwright 需要这些隐藏导入
hiddenimports = collect_submodules("playwright")

# 查找 Playwright 浏览器目录
playwright_browser_dir = None
possible_paths = [
    Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1208",
    Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1205",
    Path.home() / "AppData" / "Local" / "ms-playwright" / "chromium-1203",
]
for p in possible_paths:
    if p.exists():
        playwright_browser_dir = p
        break

if playwright_browser_dir:
    print(f"找到 Playwright 浏览器: {playwright_browser_dir}")
else:
    print("警告: 未找到 Playwright 浏览器目录，请运行 'playwright install chromium'")

datas = [
    (str(project_dir / "data" / "question_bank.db"), "data"),
    (str(project_dir / "config.py"), "."),  # 将 config.py 复制到 exe 同级目录
]

# 如果有浏览器目录，添加到打包
if playwright_browser_dir:
    datas.append((str(playwright_browser_dir), "playwright_browsers/chromium-1208"))

a = Analysis(
    [str(project_dir / "main.pyw")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_dir)],
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
    name="答题助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # 不显示终端
    disable_windowed_traceback=True,  # 不弹出 Python 报错窗口
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
    name="答题助手",
)
