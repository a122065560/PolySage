"""
logger - 全局日志模块（讨论日志 + 操作日志）

功能：
- 自动创建日志目录 ~/.polysage/logs/
- 按日期分文件记录日志
  - 讨论日志：discussion_YYYY-MM-DD.log（讨论过程：第几轮、谁说了什么）
  - 操作日志：operation_YYYY-MM-DD.log（系统操作记录、报错信息）

日志路径：
  ~/.polysage/logs/discussion_YYYY-MM-DD.log  （讨论日志）
  ~/.polysage/logs/operation_YYYY-MM-DD.log   （操作日志）
"""

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


# 日志目录
LOG_DIR = Path.home() / ".polysage" / "logs"

# 日志文件名格式
LOG_FILE_FORMAT = "discussion_{}.log"     # 讨论日志
ERR_FILE_FORMAT = "operation_{}.log"      # 操作日志

# 单例
_logger: logging.Logger | None = None
_log_file_path: Path | None = None
_err_file_path: Path | None = None


def get_log_file_path() -> Path:
    """获取当前普通日志文件路径。"""
    global _log_file_path
    if _log_file_path is None:
        today = datetime.now().strftime("%Y-%m-%d")
        _log_file_path = LOG_DIR / LOG_FILE_FORMAT.format(today)
    return _log_file_path


def get_err_file_path() -> Path:
    """获取当前异常日志文件路径。"""
    global _err_file_path
    if _err_file_path is None:
        today = datetime.now().strftime("%Y-%m-%d")
        _err_file_path = LOG_DIR / ERR_FILE_FORMAT.format(today)
    return _err_file_path


def _try_create_log_dir() -> Path:
    """
    尝试创建日志目录，如果主目录不可用则回退到临时目录。

    Returns:
        Path: 可用的日志目录
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        test_file = LOG_DIR / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        return LOG_DIR
    except Exception:
        pass

    import tempfile
    fallback_dir = Path(tempfile.gettempdir()) / "polysage_logs"
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback_dir


def setup_logger() -> logging.Logger:
    """
    初始化并返回全局 Logger。

    - 创建日志目录
    - 配置双 FileHandler（普通日志 + 异常日志）
    - 配置 StreamHandler（控制台，开发模式）
    - 安装全局异常钩子
    """
    global _logger, LOG_DIR

    if _logger is not None:
        return _logger

    actual_log_dir = _try_create_log_dir()
    LOG_DIR = actual_log_dir

    log_path = get_log_file_path()
    err_path = get_err_file_path()

    _logger = logging.getLogger("PolySage")
    _logger.setLevel(logging.DEBUG)

    if not _logger.handlers:
        # 普通日志 handler（INFO 及以上，排除 ERROR）
        try:
            file_handler = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")
            file_handler.setLevel(logging.INFO)
            file_handler.addFilter(lambda record: record.levelno < logging.ERROR)
            file_fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(file_fmt)
            _logger.addHandler(file_handler)
        except Exception:
            pass

        # 异常日志 handler（仅 ERROR 及以上）
        try:
            err_handler = logging.FileHandler(str(err_path), encoding="utf-8", mode="a")
            err_handler.setLevel(logging.ERROR)
            err_fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            err_handler.setFormatter(err_fmt)
            _logger.addHandler(err_handler)
        except Exception:
            pass

        # 控制台 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
        console_handler.setFormatter(console_fmt)
        _logger.addHandler(console_handler)

    _install_exception_hooks()

    _logger.info("=" * 60)
    _logger.info("聚慧 PolySage 日志系统已启动")
    _logger.info(f"讨论日志: {log_path}")
    _logger.info(f"操作日志: {err_path}")
    _logger.info(f"Python: {sys.version}")
    _logger.info(f"平台: {sys.platform}")
    _logger.info("=" * 60)

    return _logger


def _install_exception_hooks():
    """安装全局异常捕获钩子，覆盖所有异常路径。"""

    # 1. 捕获主线程同步异常（sys.excepthook）
    def sys_excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log_exception("未捕获的异常 (sys.excepthook)", exc_type, exc_value, exc_tb)

    sys.excepthook = sys_excepthook

    # 2. 捕获子线程异常（threading.excepthook，Python 3.8+）
    def threading_excepthook(args):
        log_exception(
            f"子线程未捕获异常 (thread={args.thread.name})",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    try:
        import threading
        threading.excepthook = threading_excepthook
    except Exception:
        pass

    # 3. 捕获 asyncio 未处理异常（防止崩溃）
    def asyncio_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "无消息")
        if exc is not None:
            log_exception(
                f"asyncio 未处理异常: {msg}",
                type(exc),
                exc,
                exc.__traceback__,
            )
        else:
            log_error(f"asyncio 错误上下文: {context}")
        # 不重新抛出异常，防止进程崩溃

    try:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        if loop is not None:
            loop.set_exception_handler(asyncio_exception_handler)
    except Exception:
        pass

    global _stored_asyncio_handler
    _stored_asyncio_handler = asyncio_exception_handler


_stored_asyncio_handler = None


def setup_asyncio_exception_handler(loop):
    """在事件循环创建后调用，设置 asyncio 异常处理器。"""
    if _stored_asyncio_handler is not None:
        loop.set_exception_handler(_stored_asyncio_handler)


def log_exception(msg, exc_type=None, exc_value=None, exc_tb=None):
    """记录异常信息（含完整堆栈），同时写入普通日志和异常日志。"""
    logger = _logger or setup_logger()
    logger.error(f"❌ {msg}")
    if exc_tb is not None:
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error(tb_text)
    elif exc_value is not None:
        logger.error(f"异常类型: {exc_type.__name__ if exc_type else 'Unknown'}")
        logger.error(f"异常信息: {exc_value}")


def log_error(msg):
    """记录错误信息（同时写入普通日志和异常日志）。"""
    logger = _logger or setup_logger()
    logger.error(msg)


def log_warning(msg):
    """记录警告信息（仅普通日志）。"""
    logger = _logger or setup_logger()
    logger.warning(msg)


def log_info(msg):
    """记录一般信息（仅普通日志）。"""
    logger = _logger or setup_logger()
    logger.info(msg)


def log_debug(msg):
    """记录调试信息（仅普通日志）。"""
    logger = _logger or setup_logger()
    logger.debug(msg)


# ===== 日志删除接口 =====

def delete_logs() -> tuple[int, str]:
    """删除所有讨论日志文件。"""
    global _logger, _log_file_path

    if not LOG_DIR.exists():
        return (0, "日志目录不存在，无需删除。")

    count = 0
    errors = []

    for f in LOG_DIR.glob("discussion_*.log"):
        try:
            f.unlink()
            count += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    _reinit_logger()
    if errors:
        return (count, f"删除了 {count} 个普通日志文件，但有错误:\n" + "\n".join(errors))
    return (count, f"已删除 {count} 个普通日志文件，新的日志将自动创建。")


def delete_error_logs() -> tuple[int, str]:
    """删除所有操作日志文件。"""
    global _logger, _err_file_path

    if not LOG_DIR.exists():
        return (0, "日志目录不存在，无需删除。")

    count = 0
    errors = []

    for f in LOG_DIR.glob("operation_*.log"):
        try:
            f.unlink()
            count += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    _reinit_logger()
    if errors:
        return (count, f"删除了 {count} 个异常日志文件，但有错误:\n" + "\n".join(errors))
    return (count, f"已删除 {count} 个异常日志文件，新的日志将自动创建。")


def delete_all_logs() -> tuple[int, str]:
    """一键删除所有日志文件（讨论日志 + 操作日志）。"""
    global _logger, _log_file_path, _err_file_path

    if not LOG_DIR.exists():
        return (0, "日志目录不存在，无需删除。")

    count = 0
    errors = []

    for f in LOG_DIR.glob("*.log"):
        try:
            f.unlink()
            count += 1
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    _reinit_logger()
    if errors:
        return (count, f"删除了 {count} 个日志文件，但有错误:\n" + "\n".join(errors))
    return (count, f"已删除全部 {count} 个日志文件，新的日志将自动创建。")


def _reinit_logger():
    """重新初始化 logger（删除日志后调用）。"""
    global _logger, _log_file_path, _err_file_path

    if _logger is not None:
        for h in list(_logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            _logger.removeHandler(h)
        _logger = None
        _log_file_path = None
        _err_file_path = None

    setup_logger()


def get_log_dir() -> Path:
    """获取日志目录路径。"""
    return LOG_DIR


def get_log_files() -> list[Path]:
    """获取所有讨论日志文件列表（按修改时间降序）。"""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("discussion_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)


def get_error_log_files() -> list[Path]:
    """获取所有操作日志文件列表（按修改时间降序）。"""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("operation_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)


def get_all_log_files() -> list[Path]:
    """获取所有日志文件列表（讨论+操作，按修改时间降序）。"""
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
