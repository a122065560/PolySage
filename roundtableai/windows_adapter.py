"""
windows_adapter - Windows 平台适配器实现

实现 PlatformAdapter 抽象接口，提供 Windows 下的：
- 应用数据目录 / Chrome 用户数据目录 / 配置文件路径（%LOCALAPPDATA%/PolySage）
- Chrome 调试进程启动（subprocess.Popen + DETACHED_PROCESS +
  CREATE_NEW_PROCESS_GROUP，必须带 --no-sandbox）
- 进程树递归终止（CDP 优雅关闭 → psutil 递归杀进程树 → 清理锁文件）
- 端口检测、锁文件清理、健康诊断

注意：用户数据目录放在 %LOCALAPPDATA% 下而非用户主目录，
以避免 Windows Defender 实时扫描拖慢 Chrome 读写。

进程管理优先使用 psutil；若环境未安装 psutil，自动回退到
系统命令（tasklist / wmic / taskkill）方案，以保证模块始终可被 import。
本文件可跨平台 import（平台相关调用仅在运行时触发）。
"""

from __future__ import annotations

import json as _json
import os
import socket
import subprocess
import time
import urllib.request
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

# Windows 进程创建标志
# DETACHED_PROCESS：使子进程脱离父进程控制台
# CREATE_NEW_PROCESS_GROUP：创建新进程组，使子进程不受父进程 Ctrl+C 影响
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

# 用户数据目录下需要清理的 Chrome 锁文件
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def _chrome_candidates() -> List[str]:
    """返回 Windows 下 Chrome 可执行文件候选路径。"""
    programfiles = os.environ.get("PROGRAMFILES", "")
    programfiles_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    return [
        os.path.join(programfiles, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(programfiles_x86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(localappdata, "Google", "Chrome", "Application", "chrome.exe"),
    ]


# ======================================================================
# WindowsAdapter
# ======================================================================

class WindowsAdapter(PlatformAdapter):
    """Windows 平台适配器。"""

    # ------------------------------------------------------------------
    # 平台与路径
    # ------------------------------------------------------------------

    def name(self) -> str:
        return "Windows"

    def app_data_dir(self) -> Path:
        """应用数据目录：%LOCALAPPDATA%/PolySage"""
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "PolySage"

    def default_user_data_dir(self) -> Path:
        """
        Chrome 默认用户数据目录。

        放在 %LOCALAPPDATA% 下而非用户主目录，避免 Windows Defender
        实时扫描拖慢 Chrome。
        """
        return self.app_data_dir() / "chrome-data"

    def config_path(self) -> Path:
        """配置文件路径。"""
        return self.app_data_dir() / "config.json"

    # ------------------------------------------------------------------
    # Chrome 路径检测
    # ------------------------------------------------------------------

    def _find_chrome_path(self) -> Optional[str]:
        """检测系统 Chrome 可执行文件路径，未找到返回 None。"""
        for path in _chrome_candidates():
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
        """检查 Chrome 主进程是否存活。优先 psutil，回退 tasklist。"""
        return self._pid_alive(handle.pid)

    def _pid_alive(self, pid: int) -> bool:
        if _PSUTIL_AVAILABLE:
            return psutil.pid_exists(pid)
        # Windows 下 os.kill(pid, 0) 不可靠，使用 tasklist 检测
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=2,
            )
            return str(pid) in out.stdout
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Chrome 启动
    # ------------------------------------------------------------------

    def launch_chrome(self, spec: ChromeLaunchSpec) -> ChromeHandle:
        """
        启动 Chrome 调试进程。

        Windows 下使用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP 使
        Chrome 独立于父进程运行；必须带 --no-sandbox，否则在某些环境
        下会因沙箱权限问题启动失败。
        """
        chrome_path = self._find_chrome_path()
        if not chrome_path:
            raise FileNotFoundError("未找到 Google Chrome，请确认已安装。")

        # 启动前清理锁文件
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
            "--no-sandbox",  # Windows 下必须
        ]
        if spec.headless:
            args.append("--headless=new")
        args.extend(spec.extra_args)

        log_info(
            f"[Windows] 启动 Chrome: 端口 {spec.debug_port}, "
            f"数据目录 {spec.user_data_dir}, 实例 {spec.instance_id}"
        )

        # DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP：使 Chrome 独立于父进程
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
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
            log_warning(f"[Windows] Chrome 启动后端口 {spec.debug_port} 未就绪")

        return handle

    # ------------------------------------------------------------------
    # Chrome 进程树终止
    # ------------------------------------------------------------------

    def kill_chrome_tree(self, handle: ChromeHandle, grace_seconds: float = 5.0) -> None:
        """
        递归终止 Chrome 进程树。

        流程（三阶段）：
        1. CDP 优雅关闭：通过 CDP HTTP 接口关闭所有页面，促使浏览器自行退出；
        2. psutil 递归杀进程树：terminate → 超时 → kill，清理残留进程；
        3. 清理锁文件：删除用户数据目录下的 Singleton* 锁文件。
        """
        pid = handle.pid
        log_info(f"[Windows] 终止 Chrome 进程树 (pid={pid})")

        # 第一阶段：CDP 优雅关闭
        self._cdp_graceful_close(handle.debug_port)

        # 等待端口释放（优雅关闭宽限）
        deadline = time.time() + grace_seconds
        while time.time() < deadline:
            if not self.is_port_listening(handle.debug_port):
                break
            time.sleep(0.3)

        # 第二阶段：psutil 递归终止进程树
        tree = self._collect_process_tree(pid)
        if _PSUTIL_AVAILABLE:
            # 先 terminate 子进程（逆序，从叶子到根）
            for child_pid in reversed(tree):
                self._psutil_terminate(child_pid)
            # 等待并强制 kill 仍存活的进程
            time.sleep(1.0)
            for child_pid in tree:
                self._psutil_kill(child_pid)
        else:
            # 回退方案：taskkill /T /F 递归强制终止
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=10,
                )
            except Exception as e:
                log_warning(f"[Windows] taskkill 失败 (pid={pid}): {e}")

        # 第三阶段：清理锁文件
        self.post_close_cleanup(handle.user_data_dir)
        log_info(f"[Windows] Chrome 进程树已终止 (pid={pid})")

    def _cdp_graceful_close(self, port: int) -> None:
        """
        通过 CDP HTTP 接口优雅关闭浏览器。

        依次关闭所有可见页面，促使 Chrome 自行退出，避免直接强杀
        导致用户数据目录锁文件残留或 profile 损坏。
        """
        # 1. 尝试逐个关闭打开的页面
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2
            )
            tabs = _json.loads(resp.read())
            for tab in tabs:
                tid = tab.get("id")
                if not tid:
                    continue
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/close/{tid}", timeout=2
                    )
                except Exception:
                    pass
        except Exception:
            # CDP 不可用（端口已释放或浏览器已退出），忽略
            pass

    # ------------------------------------------------------------------
    # 进程树辅助
    # ------------------------------------------------------------------

    def _collect_process_tree(self, pid: int) -> List[int]:
        """收集以 pid 为根的完整进程树（含自身）。"""
        if _PSUTIL_AVAILABLE:
            try:
                parent = psutil.Process(pid)
                tree = [p.pid for p in parent.children(recursive=True)]
                tree.append(pid)
                return tree
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return [pid]
        return [pid]

    def _psutil_terminate(self, pid: int) -> None:
        """psutil 优雅终止进程。"""
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
            pass

    def _psutil_kill(self, pid: int) -> None:
        """psutil 强制终止进程。"""
        try:
            psutil.Process(pid).kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception:
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
                    log_warning(f"[Windows] 清理锁文件失败 {lock}: {e}")

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

        # 回退：wmic 按名称模糊匹配
        try:
            out = subprocess.run(
                ["wmic", "process", "where",
                 f"name like '%{name_substr}%'",
                 "get", "processid"],
                capture_output=True, text=True, timeout=5,
            )
            for line in out.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception as e:
            log_warning(f"[Windows] wmic 查找进程失败: {e}")
        return pids

    def kill_process_tree_by_name(self, name_substr: str) -> int:
        """
        按名称递归终止进程树。

        Returns:
            int: 命中并尝试终止的进程数
        """
        pids = self.find_processes_by_name(name_substr)
        killed = 0

        if _PSUTIL_AVAILABLE:
            for pid in pids:
                tree = self._collect_process_tree(pid)
                # 逆序：先 terminate 子进程
                for child_pid in reversed(tree):
                    self._psutil_terminate(child_pid)
                killed += 1
            # 等待并强制 kill 仍存活的进程
            time.sleep(1.0)
            for pid in pids:
                tree = self._collect_process_tree(pid)
                for child_pid in tree:
                    if self._pid_alive(child_pid):
                        self._psutil_kill(child_pid)
        else:
            # 回退：taskkill /T /F 递归强制终止
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True, timeout=10,
                    )
                    killed += 1
                except Exception as e:
                    log_warning(f"[Windows] taskkill 失败 (pid={pid}): {e}")

        log_info(f"[Windows] 按名称 '{name_substr}' 终止进程数: {killed}")
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
