"""
macos_adapter - macOS 平台适配器实现

实现 PlatformAdapter 抽象接口，提供 macOS 下的：
- 应用数据目录 / Chrome 用户数据目录 / 配置文件路径
- Chrome 调试进程启动（subprocess.Popen）
- 进程树递归终止（kill -TERM → grace 秒超时 → kill -9）
- 端口检测、锁文件清理、健康诊断

聚慧（PolySage）在 macOS 上将数据存放于：
    ~/Library/Application Support/PolySage

进程管理优先使用 psutil；若环境未安装 psutil，自动回退到
系统命令（pgrep / kill）方案，以保证模块始终可被 import。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional

# psutil 为软依赖：未安装时回退到系统命令方案
try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - 取决于运行环境
    psutil = None
    _PSUTIL_AVAILABLE = False

from platform_adapter import (
    PlatformAdapter,
    ChromeLaunchSpec,
    ChromeHandle,
)

# 复用项目已有日志模块；若在脱离项目环境时 import 失败则使用空操作兜底
try:
    from logger import log_info, log_error, log_warning, log_exception
except Exception:  # pragma: no cover - 兜底，保证可独立 import
    def _noop(msg, *args, **kwargs):
        pass

    log_info = log_error = log_warning = log_exception = _noop


# ======================================================================
# 常量
# ======================================================================

# Chrome 可执行文件候选路径（macOS）
_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    os.path.expanduser(
        "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ),
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

# 用户数据目录下需要清理的 Chrome 锁文件
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


# ======================================================================
# MacOSAdapter
# ======================================================================

class MacOSAdapter(PlatformAdapter):
    """macOS 平台适配器。"""

    # ------------------------------------------------------------------
    # 平台与路径
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "macOS"

    def app_data_dir(self) -> Path:
        """应用数据目录：~/Library/Application Support/PolySage"""
        return Path.home() / "Library" / "Application Support" / "PolySage"

    def default_user_data_dir(self) -> Path:
        """Chrome 默认用户数据目录。"""
        return self.app_data_dir() / "chrome-data"

    def config_path(self) -> Path:
        """配置文件路径。"""
        return self.app_data_dir() / "config.json"

    # ------------------------------------------------------------------
    # Chrome 路径检测
    # ------------------------------------------------------------------

    def _find_chrome_path(self) -> Optional[str]:
        """检测系统 Chrome 可执行文件路径，未找到返回 None。"""
        for path in _CHROME_CANDIDATES:
            if path and os.path.isfile(path):
                return path
        return None

    # ------------------------------------------------------------------
    # 端口检测
    # ------------------------------------------------------------------

    def is_port_listening(self, port: int) -> bool:
        """检查端口是否被监听（占用）。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _wait_for_port(self, port: int, timeout: float = 20.0) -> bool:
        """轮询等待调试端口就绪。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_port_listening(port):
                return True
            time.sleep(0.5)
        return False

    # ------------------------------------------------------------------
    # 进程存活检测
    # ------------------------------------------------------------------

    def is_chrome_alive(self, handle: ChromeHandle) -> bool:
        """检查 Chrome 主进程是否存活。优先 psutil，回退 os.kill(pid, 0)。"""
        return self._pid_alive(handle.pid)

    def _pid_alive(self, pid: int) -> bool:
        if _PSUTIL_AVAILABLE:
            return psutil.pid_exists(pid)
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Chrome 启动
    # ------------------------------------------------------------------

    def launch_chrome(self, spec: ChromeLaunchSpec) -> ChromeHandle:
        """
        启动 Chrome 调试进程。

        使用 subprocess.Popen 直接拉起 Chrome，并附带
        --remote-debugging-port 参数开启 CDP 调试端口。
        """
        chrome_path = self._find_chrome_path()
        if not chrome_path:
            raise FileNotFoundError("未找到 Google Chrome，请确认已安装。")

        # 启动前清理锁文件，避免上次异常退出导致拒绝启动
        self.pre_launch_cleanup(spec.user_data_dir)

        # 确保用户数据目录存在
        spec.user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [
            chrome_path,
            f"--remote-debugging-port={spec.debug_port}",
            f"--user-data-dir={spec.user_data_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if spec.headless:
            args.append("--headless=new")
        args.extend(spec.extra_args)

        log_info(
            f"[macOS] 启动 Chrome: 端口 {spec.debug_port}, "
            f"数据目录 {spec.user_data_dir}, 实例 {spec.instance_id}"
        )

        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

        handle = ChromeHandle(
            pid=proc.pid,
            debug_port=spec.debug_port,
            user_data_dir=spec.user_data_dir,
            cdp_url=f"http://127.0.0.1:{spec.debug_port}",
            launch_time=time.time(),
        )

        # 等待调试端口就绪
        if not self._wait_for_port(spec.debug_port, timeout=20.0):
            log_warning(f"[macOS] Chrome 启动后端口 {spec.debug_port} 未就绪")

        return handle

    # ------------------------------------------------------------------
    # Chrome 进程树终止
    # ------------------------------------------------------------------

    def kill_chrome_tree(self, handle: ChromeHandle, grace_seconds: float = 5.0) -> None:
        """
        递归终止 Chrome 进程树。

        流程：kill -TERM 优雅终止 → 等待 grace_seconds 秒 →
        对仍存活的进程 kill -9 强制终止 → 清理锁文件。
        """
        pid = handle.pid
        log_info(f"[macOS] 终止 Chrome 进程树 (pid={pid})")

        # 收集完整进程树（含自身）
        pids = self._collect_process_tree(pid)

        # 第一轮：SIGTERM 优雅终止
        for child_pid in pids:
            self._send_signal(child_pid, signal.SIGTERM)

        # 等待 grace 秒，给进程优雅退出的时间
        deadline = time.time() + grace_seconds
        while time.time() < deadline:
            if all(not self._pid_alive(p) for p in pids):
                break
            time.sleep(0.3)

        # 第二轮：SIGKILL 强制终止仍在存活的进程
        for child_pid in pids:
            if self._pid_alive(child_pid):
                self._send_signal(child_pid, signal.SIGKILL)

        # 关闭后清理锁文件
        self.post_close_cleanup(handle.user_data_dir)
        log_info(f"[macOS] Chrome 进程树已终止 (pid={pid})")

    # ------------------------------------------------------------------
    # 进程树辅助
    # ------------------------------------------------------------------

    def _collect_process_tree(self, pid: int) -> List[int]:
        """收集以 pid 为根的完整进程树（含自身），顺序无关。"""
        if _PSUTIL_AVAILABLE:
            try:
                parent = psutil.Process(pid)
                tree = [p.pid for p in parent.children(recursive=True)]
                tree.append(pid)
                return tree
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return [pid]

        # 回退方案：通过 pgrep -P 递归收集子进程
        tree: List[int] = [pid]
        stack = [pid]
        while stack:
            current = stack.pop()
            try:
                out = subprocess.run(
                    ["pgrep", "-P", str(current)],
                    capture_output=True, text=True, timeout=2,
                )
                for line in out.stdout.split():
                    if line.strip().isdigit():
                        child = int(line.strip())
                        tree.append(child)
                        stack.append(child)
            except Exception as e:
                log_warning(f"[macOS] pgrep 收集子进程失败 (pid={current}): {e}")
        return tree

    def _send_signal(self, pid: int, sig) -> None:
        """向进程发送信号，忽略已退出/无权限错误。"""
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 锁文件清理
    # ------------------------------------------------------------------

    def pre_launch_cleanup(self, user_data_dir: Path) -> None:
        """启动前清理锁文件，避免上次异常退出导致 Chrome 拒绝启动。"""
        self._cleanup_lock_files(user_data_dir)

    def post_close_cleanup(self, user_data_dir: Path) -> None:
        """关闭后清理锁文件。"""
        self._cleanup_lock_files(user_data_dir)

    def _cleanup_lock_files(self, user_data_dir: Path) -> None:
        if not user_data_dir.exists():
            return
        for name in _LOCK_FILES:
            lock = user_data_dir / name
            if lock.exists():
                try:
                    lock.unlink()
                except Exception as e:
                    log_warning(f"[macOS] 清理锁文件失败 {lock}: {e}")

    # ------------------------------------------------------------------
    # 进程查找 / 按名清理
    # ------------------------------------------------------------------

    def find_processes_by_name(self, name_substr: str) -> List[int]:
        """按进程名称（子串匹配）查找 PID 列表。"""
        pids: List[int] = []

        if _PSUTIL_AVAILABLE:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    pname = p.info.get("name") or ""
                    if name_substr.lower() in pname.lower():
                        pids.append(p.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return pids

        # 回退：pgrep -f 按完整命令行匹配
        try:
            out = subprocess.run(
                ["pgrep", "-f", name_substr],
                capture_output=True, text=True, timeout=3,
            )
            for line in out.stdout.split():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
        except Exception as e:
            log_warning(f"[macOS] pgrep 查找进程失败: {e}")
        return pids

    def kill_process_tree_by_name(self, name_substr: str) -> int:
        """
        按名称递归终止进程树。

        Returns:
            int: 命中并尝试终止的进程数
        """
        pids = self.find_processes_by_name(name_substr)
        killed = 0

        for pid in pids:
            tree = self._collect_process_tree(pid)
            for child_pid in tree:
                self._send_signal(child_pid, signal.SIGTERM)
            killed += 1

        # 等待并强制清理仍存活的进程
        time.sleep(1.0)
        for pid in pids:
            tree = self._collect_process_tree(pid)
            for child_pid in tree:
                if self._pid_alive(child_pid):
                    self._send_signal(child_pid, signal.SIGKILL)

        log_info(f"[macOS] 按名称 '{name_substr}' 终止进程数: {killed}")
        return killed

    # ------------------------------------------------------------------
    # 健康诊断
    # ------------------------------------------------------------------

    def diagnose(self) -> dict:
        """健康检查：返回平台、Chrome 路径、关键目录等环境信息。"""
        chrome = self._find_chrome_path()
        return {
            "platform": self.name(),
            "chrome_path": chrome,
            "chrome_found": chrome is not None,
            "app_data_dir": str(self.app_data_dir()),
            "config_path": str(self.config_path()),
            "user_data_dir": str(self.default_user_data_dir()),
            "psutil_available": _PSUTIL_AVAILABLE,
        }
