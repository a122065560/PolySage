# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

IS_MACOS = sys.platform == 'darwin'
IS_WINDOWS = sys.platform == 'win32'

datas = [('logo_ui.png', '.'), ('logo_ui@2x.png', '.')]
binaries = []
hiddenimports = ['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.sip', 'qasync', 'playwright', 'playwright.async_api', 'playwright._impl', 'openai', 'platform_adapter', 'macos_adapter', 'windows_adapter']
datas += collect_data_files('qasync')
datas += copy_metadata('openai')
datas += copy_metadata('qasync')
binaries += collect_dynamic_libs('PyQt6')
hiddenimports += collect_submodules('PyQt6')
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

exclude_list = ['PyQt6.Qt6', 'tkinter', 'matplotlib', 'numpy', 'pandas', 'PyQt5', 'PySide6', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DRender', 'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DExtras', 'PyQt6.Qt3DInput', 'PyQt6.Qt3DLogic', 'PyQt6.QtBluetooth', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization', 'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'PyQt6.QtNetwork', 'PyQt6.QtNfc', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtPositioning', 'PyQt6.QtPrintSupport', 'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtQuickControls2', 'PyQt6.QtQuickWidgets', 'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort', 'PyQt6.QtSpatialAudio', 'PyQt6.QtSql', 'PyQt6.QtTest', 'PyQt6.QtTextToSpeech', 'PyQt6.QtWebChannel', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineQuick', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebSockets', 'PyQt6.QtXml']
if IS_MACOS:
    exclude_list.append('PIL')

a = Analysis(
    ['main.py', 'ui_main_window.py', 'ui_widgets.py', 'ui_worker.py', 'ui_flowlayout.py', 'browser.py', 'core.py', 'config_manager.py', 'utils.py', 'logger.py', 'platform_adapter.py', 'macos_adapter.py', 'windows_adapter.py'],
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
if IS_MACOS:
    exe_kwargs['target_arch'] = 'arm64'
    if os.path.exists('AppIcon.icns'):
        exe_kwargs['icon'] = ['AppIcon.icns']
elif IS_WINDOWS:
    if os.path.exists('AppIcon.ico'):
        exe_kwargs['icon'] = ['AppIcon.ico']
exe = EXE(pyz, a.scripts, [], **exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PolySage',
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name='PolySage.app',
        icon='AppIcon.icns' if os.path.exists('AppIcon.icns') else None,
        bundle_identifier='com.polysage.app',
    )
