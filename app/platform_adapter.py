"""
platform_adapter - 跨平台抽象层

定义平台无关的抽象接口 PlatformAdapter，以及 Chrome 启动所需的数据结构。
具体平台实现见 macos_adapter.py 与 windows_adapter.py。

聚慧（PolySage）通过 current_adapter() 工厂函数获取当前平台的适配器实例，
实现 macOS / Windows 上的 Chrome 调试进程管理、端口检测、进程树清理等能力。

设计目标：
1. 上层业务代码只依赖 PlatformAdapter 抽象接口，不感知具体平台差异；
2. 新增平台只需继承 PlatformAdapter 并实现全部抽象方法即可接入；
3. Chrome 启停、锁文件清理、进程树终止等平台相关细节全部下沉到适配器层。
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


# ======================================================================
# 数据结构
# ======================================================================

@dataclass
class ChromeLaunchSpec:
    """
    Chrome 启动参数规格。

    Attributes:
        debug_port: 调试端口（对应 --remote-debugging-port）
        user_data_dir: 用户数据目录（对应 --user-data-dir）
        headless: 是否以无头模式启动
        extra_args: 额外的 Chrome 命令行参数
        instance_id: 实例标识，用于多实例隔离与日志区分
    """
    debug_port: int
    user_data_dir: Path
    headless: bool = False
    extra_args: List[str] = field(default_factory=list)
    instance_id: str = "default"


@dataclass
class ChromeHandle:
    """
    已启动 Chrome 进程的句柄，封装进程控制所需的关键信息。

    Attributes:
        pid: Chrome 主进程 PID
        debug_port: 调试端口
        user_data_dir: 用户数据目录
        cdp_url: CDP 调试地址（http://127.0.0.1:<port>）
        launch_time: 启动时间戳（time.time()）
    """
    pid: int
    debug_port: int
    user_data_dir: Path
    cdp_url: str = ""
    launch_time: float = 0.0


# ======================================================================
# 抽象基类
# ======================================================================

class PlatformAdapter(ABC):
    """
    平台适配器抽象基类。

    所有平台实现（macOS / Windows 等）必须继承本类并实现全部抽象方法。
    上层代码面向本抽象编程，通过 current_adapter() 获取具体实例。
    """

    # ------------------------------------------------------------------
    # 平台与路径
    # ------------------------------------------------------------------

    @abstractmethod
    def name(self) -> str:
        """返回平台名称（如 "macOS" / "Windows"）。"""
        raise NotImplementedError

    @abstractmethod
    def app_data_dir(self) -> Path:
        """返回应用数据目录。"""
        raise NotImplementedError

    @abstractmethod
    def default_user_data_dir(self) -> Path:
        """返回 Chrome 默认用户数据目录。"""
        raise NotImplementedError

    @abstractmethod
    def config_path(self) -> Path:
        """返回配置文件路径。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Chrome 启停
    # ------------------------------------------------------------------

    @abstractmethod
    def launch_chrome(self, spec: ChromeLaunchSpec) -> ChromeHandle:
        """按规格启动 Chrome 调试进程，返回进程句柄。"""
        raise NotImplementedError

    @abstractmethod
    def kill_chrome_tree(self, handle: ChromeHandle, grace_seconds: float = 5.0) -> None:
        """递归终止 Chrome 进程树。grace_seconds 为优雅关闭的宽限时间。"""
        raise NotImplementedError

    @abstractmethod
    def is_chrome_alive(self, handle: ChromeHandle) -> bool:
        """检查 Chrome 进程是否存活。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 端口检测
    # ------------------------------------------------------------------

    @abstractmethod
    def is_port_listening(self, port: int) -> bool:
        """检查指定端口是否被监听（占用）。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    @abstractmethod
    def pre_launch_cleanup(self, user_data_dir: Path) -> None:
        """启动前清理用户数据目录下的锁文件。"""
        raise NotImplementedError

    @abstractmethod
    def post_close_cleanup(self, user_data_dir: Path) -> None:
        """关闭后清理用户数据目录下的锁文件。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 进程查找 / 按名清理
    # ------------------------------------------------------------------

    @abstractmethod
    def find_processes_by_name(self, name_substr: str) -> List[int]:
        """按进程名称（子串匹配）查找 PID 列表。"""
        raise NotImplementedError

    @abstractmethod
    def kill_process_tree_by_name(self, name_substr: str) -> int:
        """按进程名称递归终止进程树，返回成功终止的进程数。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 健康诊断
    # ------------------------------------------------------------------

    @abstractmethod
    def diagnose(self) -> dict:
        """健康检查，返回平台环境关键信息字典。"""
        raise NotImplementedError


# ======================================================================
# 工厂函数
# ======================================================================

# 模块级缓存：适配器无状态，避免重复构造
_cached_adapter: "PlatformAdapter | None" = None


def current_adapter() -> PlatformAdapter:
    """
    根据 sys.platform 自动选择当前平台的适配器实例。

    Returns:
        PlatformAdapter: 当前平台适配器实例

    Raises:
        RuntimeError: 当前平台不受支持
    """
    global _cached_adapter
    if _cached_adapter is not None:
        return _cached_adapter

    if sys.platform == "darwin":
        from macos_adapter import MacOSAdapter
        _cached_adapter = MacOSAdapter()
    elif sys.platform == "win32":
        from windows_adapter import WindowsAdapter
        _cached_adapter = WindowsAdapter()
    else:
        raise RuntimeError(
            f"不支持的平台: {sys.platform}（聚慧目前仅支持 macOS / Windows）"
        )

    return _cached_adapter


def reset_adapter_cache() -> None:
    """重置适配器缓存（主要用于测试场景）。"""
    global _cached_adapter
    _cached_adapter = None
