"""
main - 聚慧 PolySage 程序入口

使用 qasync 将 asyncio 事件循环集成到 PyQt6 的事件循环中，
使 Playwright 的异步操作（await）可以在槽函数中安全使用，UI 不会卡死。

启动：python main.py
"""

import sys
import os

# ======================================================================
# 关键：在导入 PyQt6 之前设置 Qt 环境变量
# 解决 PyInstaller 打包后 Qt 找不到插件 / framework 路径的问题
# ======================================================================

# 判断是否在 PyInstaller 打包环境中运行
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        # macOS .app 包结构: Contents/MacOS/PolySage, Contents/Resources/_internal/
        _BASE = os.path.dirname(sys.executable)  # Contents/MacOS/
        _APP_BUNDLE = os.path.dirname(_BASE)       # Contents/
        _INTERNAL = os.path.join(_APP_BUNDLE, 'Resources', '_internal')

        # Qt6 库和插件路径
        _QT6_LIB = os.path.join(_INTERNAL, 'PyQt6', 'Qt6', 'lib')
        _QT6_PLUGINS = os.path.join(_INTERNAL, 'PyQt6', 'Qt6', 'plugins')
        _QT_PLATFORMS = os.path.join(_QT6_PLUGINS, 'platforms')

        # 设置 Qt 环境变量（macOS 需要显式指定）
        os.environ['QT_PLUGIN_PATH'] = _QT6_PLUGINS
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = _QT_PLATFORMS

        # 设置动态库搜索路径（帮助找到 Qt6 framework）
        _existing_dyld = os.environ.get('DYLD_FRAMEWORK_PATH', '')
        os.environ['DYLD_FRAMEWORK_PATH'] = _QT6_LIB + (':' + _existing_dyld if _existing_dyld else '')

        _existing_lib = os.environ.get('DYLD_LIBRARY_PATH', '')
        os.environ['DYLD_LIBRARY_PATH'] = _QT6_LIB + (':' + _existing_lib if _existing_lib else '')

        # 确保内部模块路径在 sys.path 中
        if _INTERNAL not in sys.path:
            sys.path.insert(0, _INTERNAL)
    else:
        # Windows / Linux: PyInstaller onedir 结构
        # exe 同级有 _internal/ 目录，PyInstaller 会自动设置 sys._MEIPASS
        # 不需要手动设置 QT_PLUGIN_PATH，PyInstaller 的 hook 会自动处理
        _BASE = os.path.dirname(sys.executable)
        _INTERNAL = os.path.join(_BASE, '_internal')
        _APP_BUNDLE = _BASE  # Windows 没有 .app 包结构

        # 确保 _internal 在 sys.path 中
        if _INTERNAL not in sys.path:
            sys.path.insert(0, _INTERNAL)

# 确保当前目录在 Python 路径中（开发模式下）
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from qasync import QEventLoop

# 必须在导入其他模块之前初始化日志系统
from logger import setup_logger, setup_asyncio_exception_handler, log_info, log_exception
setup_logger()

from ui_main_window import MainWindow


def main():
    log_info("应用启动中...")

    # 1. 创建 QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("聚慧")
    app.setApplicationDisplayName("🪑 聚慧")
    app.setOrganizationName("PolySage")

    # 设置应用图标
    if getattr(sys, 'frozen', False):
        if sys.platform == 'darwin':
            _icon_path = os.path.join(_APP_BUNDLE, 'Resources', 'AppIcon.icns')
        else:
            _icon_path = os.path.join(_INTERNAL, 'AppIcon.icns')
    else:
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'AppIcon.icns')
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    # 2. 用 qasync 事件循环替换默认 asyncio 循环
    #    使 async def 槽函数中的 await 不阻塞 Qt 事件循环
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # 设置全局 asyncio 异常处理器
    # 确保 qasync 事件循环中的未处理异常也能被捕获并写入日志
    setup_asyncio_exception_handler(loop)
    # 同时给底层 asyncio loop 设置（qasync 内部可能使用不同的 loop 引用）
    try:
        actual_loop = asyncio.get_event_loop()
        setup_asyncio_exception_handler(actual_loop)
    except Exception:
        pass

    # 3. 初始化主窗口
    window = MainWindow()
    window.show()
    log_info("主窗口已显示")

    # 窗口关闭时退出应用（不再直接停止事件循环，改由 aboutToQuit 处理）
    app.setQuitOnLastWindowClosed(True)

    # aboutToQuit 信号：事件循环即将退出时做最终清理
    # 这比 lastWindowClosed 更可靠，避免双重退出冲突
    def _on_about_to_quit():
        log_info("应用退出中...")
        # 确保资源已清理（closeEvent 可能未触发的情况，如 Dock 退出）
        try:
            window._cleanup_resources()
        except Exception:
            pass
        # 强制退出，避免析构崩溃
        import os
        os._exit(0)

    app.aboutToQuit.connect(_on_about_to_quit)

    # 4. 运行事件循环
    with loop:
        loop.run_forever()
    log_info("事件循环已停止，程序退出")


if __name__ == "__main__":
    main()
