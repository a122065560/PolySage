# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

IS_MACOS = sys.platform == 'darwin'
IS_WINDOWS = sys.platform == 'win32'

datas = [('logo_ui.png', '.'), ('logo_ui@2x.png', '.')]
binaries = []
hiddenimports = ['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.sip', 'qasync', 'playwright', 'playwright.async_api', 'playwright._impl', 'openai']
datas += collect_data_files('qasync')
datas += copy_metadata('openai')
datas += copy_metadata('qasync')
binaries += collect_dynamic_libs('PyQt6')
hiddenimports += collect_submodules('PyQt6')
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Windows 上不要排除 PIL（PyInstaller 需要 Pillow 转换图标格式）
exclude_list = ['PyQt6.Qt6', 'tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PySide6']
if IS_MACOS:
    exclude_list.append('PIL')

# 图标：macOS 用 .icns，Windows 用 .ico（如果有的话），否则不用图标
icon_path = 'AppIcon.icns' if IS_MACOS else None

a = Analysis(
    ['main.py', 'ui_main_window.py', 'ui_widgets.py', 'ui_worker.py', 'ui_flowlayout.py', 'browser.py', 'core.py', 'config_manager.py', 'utils.py', 'logger.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=exclude_list,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_kwargs = dict(
    pyz=pyz,
    scripts=a.scripts,
    exclude_binaries=True,
    name='PolySage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS: 指定 arm64 架构 + .icns 图标
# Windows: 不指定架构（默认 x64）+ .ico 图标（如有）
if IS_MACOS:
    exe_kwargs['target_arch'] = 'arm64'
    exe_kwargs['icon'] = ['AppIcon.icns']
elif IS_WINDOWS:
    # Windows 上如果有 .ico 就用，没有就跳过
    import os
    if os.path.exists('AppIcon.ico'):
        exe_kwargs['icon'] = ['AppIcon.ico']

exe = EXE(**exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PolySage',
)

# BUNDLE 仅 macOS 生成 .app
if IS_MACOS:
    app = BUNDLE(
        coll,
        name='PolySage.app',
        icon='AppIcon.icns',
        bundle_identifier='com.polysage.app',
    )
