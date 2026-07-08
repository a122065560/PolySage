"""
logger - 全局日志模块（多组件分文件架构）

目录结构：
  ~/.polysage/logs/
  ├── 20260709/
  │   ├── ui.log              ← 主UI: 用户操作
  │   ├── brain.log           ← 大脑线程: 调度事件
  │   ├── ai_DeepSeek.log     ← AIWorker: 检测/发送/接收
  │   ├── ai_智谱清言.log
  │   └ discussions/
  │       ├── 0709_0905_xxx.json
  │       └ 0709_1030_xxx.json

日志写入时自动创建当天目录，删除后下次写入自动重建。
"""

import logging
import os
import sys
import json
import traceback
from datetime import datetime
from pathlib import Path


# ==================== 路径管理 ====================

LOG_BASE_DIR = Path.home() / ".polysage" / "logs"

# 日志组件类型
COMPONENT_UI = "ui"
COMPONENT_BRAIN = "brain"
COMPONENT_AI_PREFIX = "ai_"


def _get_actual_log_base():
    """获取实际可用的日志根目录，不可写则回退到临时目录。"""
    try:
        LOG_BASE_DIR.mkdir(parents=True, exist_ok=True)
        test_file = LOG_BASE_DIR / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        return LOG_BASE_DIR
    except Exception:
        pass

    import tempfile
    fallback = Path(tempfile.gettempdir()) / "polysage_logs"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


# 全局可写的日志根目录（延迟初始化）
_log_base: Path | None = None


def _ensure_log_base() -> Path:
    """确保日志根目录可用，返回路径。"""
    global _log_base
    if _log_base is not None:
        return _log_base
    _log_base = _get_actual_log_base()
    return _log_base


def get_today_dir() -> Path:
    """获取今天的日志目录（按日期分文件夹）。不存在则创建。"""
    base = _ensure_log_base()
    today = datetime.now().strftime("%Y%m%d")
    day_dir = base / today
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def get_discussions_dir() -> Path:
    """获取今天的讨论记录目录。"""
    d = get_today_dir() / "discussions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_dir() -> Path:
    """获取日志根目录（兼容旧接口）。"""
    return _ensure_log_base()


def get_component_log_path(component: str) -> Path:
    """获取指定组件的日志文件路径。"""
    return get_today_dir() / f"{component}.log"


# ==================== Logger 管理 ====================

# 组件级 logger 缓存: {component_name: (logger, file_path)}
_component_loggers: dict = {}


def _get_component_logger(component: str) -> logging.Logger:
    """获取或创建指定组件的 logger。"""
    global _component_loggers

    today = datetime.now().strftime("%Y%m%d")
    cache_key = f"{component}_{today}"
    log_path = get_component_log_path(component)

    cached = _component_loggers.get(cache_key)
    if cached is not None:
        # 检查文件是否还存在（可能被删除）
        if cached[1] == log_path and log_path.exists():
            return cached[0]
        # 文件被删除或路径变了，重建
        old_logger = cached[0]
        for h in list(old_logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            old_logger.removeHandler(h)

    # 创建新 logger
    logger = logging.getLogger(f"PolySage_{cache_key}")
    logger.setLevel(logging.DEBUG)

    # 如果已有 handlers，先清理
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)

    # FileHandler
    try:
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8", mode="a")
        file_handler.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except Exception:
        pass

    _component_loggers[cache_key] = (logger, log_path)
    return logger


def _log(component: str, level: str, msg: str):
    """写入指定组件的日志。"""
    logger = _get_component_logger(component)
    getattr(logger, level)(msg)


# ==================== 公共接口 ====================

def log_info(msg, component=COMPONENT_BRAIN):
    """记录一般信息。默认写入 brain.log，可指定组件。"""
    _log(component, "info", msg)


def log_warning(msg, component=COMPONENT_BRAIN):
    """记录警告信息。"""
    _log(component, "warning", msg)


def log_error(msg, component=COMPONENT_BRAIN):
    """记录错误信息。"""
    _log(component, "error", msg)


def log_debug(msg, component=COMPONENT_BRAIN):
    """记录调试信息。"""
    _log(component, "debug", msg)


def log_exception(msg, exc_type=None, exc_value=None, exc_tb=None, component=COMPONENT_BRAIN):
    """记录异常信息（含完整堆栈）。"""
    logger = _get_component_logger(component)
    logger.error(f"❌ {msg}")
    if exc_tb is not None:
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error(tb_text)
    elif exc_value is not None:
        logger.error(f"异常类型: {exc_type.__name__ if exc_type else 'Unknown'}")
        logger.error(f"异常信息: {exc_value}")


# ==================== AI 日志快捷函数 ====================

def log_ai(ai_name: str, msg: str, level: str = "info"):
    """写入指定 AI 的日志文件。"""
    component = f"{COMPONENT_AI_PREFIX}{ai_name}"
    _log(component, level, msg)


# ==================== UI 日志快捷函数 ====================

def log_ui(msg: str, level: str = "info"):
    """写入 UI 日志文件。"""
    _log(COMPONENT_UI, level, msg)


# ==================== 讨论记录 JSON ====================

class DiscussionLogger:
    """讨论内容 JSON 记录器。每条回复只记录一次。"""

    def __init__(self, topic: str, participants: list):
        self.topic = topic
        self.participants = participants
        self.start_time = datetime.now()
        self.messages = []
        self._msg_counter = 0

        # 文件名: 日期_时分_主题摘要
        time_str = self.start_time.strftime("%m%d_%H%M")
        topic_short = topic[:10].replace(" ", "_").replace("/", "_")
        # 清理文件名非法字符
        for ch in '\\:*?"<>|':
            topic_short = topic_short.replace(ch, "_")
        self.filename = f"{time_str}_{topic_short}.json"

    def add_message(self, speaker: str, content: str, round_num: int,
                    reply_to: list = None) -> int:
        """添加一条消息，返回消息 ID。内容只存一次。每次添加后自动保存。"""
        self._msg_counter += 1
        msg = {
            "id": self._msg_counter,
            "round": round_num,
            "speaker": speaker,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "char_count": len(content),
        }
        if reply_to:
            msg["context_received"] = reply_to
        self.messages.append(msg)
        # 每次添加后自动保存（确保异常退出时也有记录）
        self.save()
        return self._msg_counter

    def save(self):
        """保存到 JSON 文件。"""
        data = {
            "topic": self.topic,
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "participants": self.participants,
            "messages": self.messages,
        }
        filepath = get_discussions_dir() / self.filename
        try:
            filepath.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
        return filepath


# ==================== 初始化 ====================

def setup_logger() -> logging.Logger:
    """初始化日志系统（兼容旧接口）。"""
    _ensure_log_base()

    # 写入启动信息到 brain.log
    log_info("=" * 60)
    log_info("聚慧 PolySage 日志系统已启动")
    log_info(f"Python: {sys.version}")
    log_info(f"平台: {sys.platform}")
    log_info(f"日志目录: {_ensure_log_base()}")
    log_info("=" * 60)

    _install_exception_hooks()

    # 返回一个兼容的 logger（旧代码可能直接用返回值）
    return _get_component_logger(COMPONENT_BRAIN)


def _install_exception_hooks():
    """安装全局异常捕获钩子。"""

    def sys_excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log_exception("未捕获的异常 (sys.excepthook)", exc_type, exc_value, exc_tb)

    sys.excepthook = sys_excepthook

    def threading_excepthook(args):
        log_exception(
            f"子线程未捕获异常 (thread={args.thread.name})",
            args.exc_type, args.exc_value, args.exc_traceback,
        )

    try:
        import threading
        threading.excepthook = threading_excepthook
    except Exception:
        pass

    def asyncio_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "无消息")
        if exc is not None:
            log_exception(f"asyncio 未处理异常: {msg}", type(exc), exc, exc.__traceback__)
        else:
            log_error(f"asyncio 错误上下文: {context}")

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


# ==================== 日志查询接口 ====================

def get_date_dirs() -> list[str]:
    """获取所有有日志的日期目录（降序）。"""
    base = _ensure_log_base()
    if not base.exists():
        return []
    dirs = []
    for d in base.iterdir():
        if d.is_dir() and len(d.name) == 8 and d.name.isdigit():
            dirs.append(d.name)
    return sorted(dirs, reverse=True)


def get_files_by_date(date_str: str) -> list[dict]:
    """获取指定日期下的所有日志文件。

    Returns:
        [{"type": "操作日志", "name": "ui.log", "path": Path, "size": 1024}, ...]
    """
    base = _ensure_log_base()
    day_dir = base / date_str
    if not day_dir.exists():
        return []

    files = []
    for f in sorted(day_dir.glob("*.log")):
        files.append({
            "type": "操作日志",
            "name": f.name,
            "path": f,
            "size": f.stat().st_size,
        })

    # 讨论记录
    disc_dir = day_dir / "discussions"
    if disc_dir.exists():
        for f in sorted(disc_dir.glob("*.json")):
            files.append({
                "type": "讨论记录",
                "name": f.name,
                "path": f,
                "size": f.stat().st_size,
            })

    return files


def get_total_size() -> int:
    """获取所有日志的总大小（字节）。"""
    base = _ensure_log_base()
    if not base.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(base):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except Exception:
                pass
    return total


def delete_file(filepath) -> bool:
    """删除单个文件，不弹确认。"""
    try:
        Path(filepath).unlink()
        return True
    except Exception:
        return False


def delete_all_logs() -> tuple[int, str]:
    """清空所有日志（所有日期目录）。"""
    base = _ensure_log_base()
    if not base.exists():
        return (0, "日志目录不存在，无需删除。")

    count = 0
    for item in base.iterdir():
        if item.is_dir() and item != base:
            # 日期目录
            for root, dirs, files in os.walk(item):
                for f in files:
                    try:
                        (Path(root) / f).unlink()
                        count += 1
                    except Exception:
                        pass
            try:
                import shutil
                shutil.rmtree(item)
            except Exception:
                pass
        elif item.is_file() and item.name != ".write_test":
            try:
                item.unlink()
                count += 1
            except Exception:
                pass

    # 清理 logger 缓存，下次写入时自动重建
    global _component_loggers
    for key, (logger, path) in _component_loggers.items():
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
    _component_loggers = {}

    return (count, f"已清空全部 {count} 个日志文件，下次运行时自动重建。")


# ==================== 兼容旧接口 ====================

def get_log_files():
    """兼容旧接口：返回操作日志文件列表。"""
    base = _ensure_log_base()
    if not base.exists():
        return []
    files = []
    for d in base.iterdir():
        if d.is_dir() and len(d.name) == 8 and d.name.isdigit():
            files.extend(d.glob("*.log"))
    return sorted(files, key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)


def get_error_log_files():
    """兼容旧接口：返回空列表（异常已合并到操作日志）。"""
    return []


def delete_logs():
    """兼容旧接口：删除操作日志。"""
    return delete_all_logs()


def delete_error_logs():
    """兼容旧接口：无操作。"""
    return (0, "异常日志已合并到操作日志")
