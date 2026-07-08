"""
browser - 浏览器控制模块

ChromeManager：启动调试模式 Chrome、Playwright CDP 连接、
消息发送/等待/回复提取、登录检测。

所有浏览器操作均使用 asyncio 异步执行，避免阻塞 Streamlit 主线程。
"""

import asyncio
import os
import platform
import socket
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from utils import clean_text
from logger import log_info, log_error, log_exception, log_warning


# ======================================================================
# Chrome 路径自动检测
# ======================================================================

def detect_chrome_path() -> Optional[str]:
    """
    自动检测系统 Chrome 可执行文件路径。

    Returns:
        str: Chrome 路径，未找到则 None
    """
    system = platform.system()

    if system == "Darwin":
        # macOS 常见路径
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif system == "Windows":
        candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
    else:
        # Linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]

    for path in candidates:
        if path and os.path.isfile(path):
            return path

    return None


def is_port_in_use(port: int) -> bool:
    """检测端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, timeout: int = 15) -> bool:
    """
    等待调试端口就绪。

    Returns:
        bool: 端口是否就绪
    """
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


# ======================================================================
# ChromeManager
# ======================================================================

class ChromeManager:
    """
    Chrome 调试模式管理器 + Playwright 控制器。

    职责：
    1. 启动 / 检测 Chrome 调试模式进程
    2. 通过 CDP 连接 Playwright
    3. 发送消息、等待回复、提取回复
    4. 登录状态检测
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 完整配置字典（来自 ConfigManager）
        """
        self.config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.chrome_path: Optional[str] = detect_chrome_path()
        # 页面创建锁：防止并发调用 get_or_create_page 导致重复打开页面
        import asyncio
        self._page_lock = asyncio.Lock()
        # 思考模式缓存：{ai_name: True} 表示已确认无需再检测
        self._thinking_mode_cache = {}
        # 思考模式操作锁：防止同一个 AI 被并发操作（避免无限循环）
        self._thinking_in_progress = set()  # {ai_name}
        # 思考模式失败计数：{ai_name: count}，超过3次后停止重试
        self._thinking_fail_count = {}
        # URL 重定向缓存：{config_url: final_url}，处理跨域重定向
        self._url_redirect_cache = {}
        # 对话状态记录：记录工具最后一次对谁说了什么，用于验证提取的回复
        # {ai_name: {"message": str, "timestamp": float, "type": "init"/"topic"/"reply"}}
        self._last_sent_to = {}
        self._last_reply = {}  # 记录每个AI上一次的回复文本，用于检测重复

    # ------------------------------------------------------------------
    # Chrome 进程管理
    # ------------------------------------------------------------------

    # LaunchAgent 标识（用于通过 launchd 启动/停止 Chrome）
    _LAUNCH_AGENT_LABEL = "com.polysage.chrome"
    _LAUNCH_AGENT_PLIST = os.path.expanduser(
        "~/Library/LaunchAgents/com.polysage.chrome.plist"
    )

    async def start_chrome_debug_async(self) -> tuple:
        """
        启动 Chrome 调试模式（跨平台）。

        macOS: 通过 LaunchAgent 让 launchd 启动 Chrome（避免 TCC 权限提示）
        Windows/Linux: 直接 subprocess.Popen 启动

        Returns:
            tuple: (success: bool, message: str)
        """
        import subprocess

        chrome_cfg = self.config.get("chrome", {})
        port = chrome_cfg.get("debug_port", 9222)
        user_data_dir = chrome_cfg.get("user_data_dir", "")

        # 展开路径
        if user_data_dir:
            user_data_dir = os.path.expanduser(user_data_dir)
        else:
            user_data_dir = os.path.expanduser("~/.polysage/chrome-data")

        # 端口已占用时，可能 Chrome 已在运行
        if is_port_in_use(port):
            log_info(f"Chrome 调试端口 {port} 已占用（可能已在运行）")
            return True, f"Chrome 调试端口 {port} 已就绪（可能已在运行）。"

        # 确保用户数据目录存在
        os.makedirs(user_data_dir, exist_ok=True)

        # 检测 Chrome 路径（跨平台）
        chrome_path = self.chrome_path or detect_chrome_path()
        if not chrome_path or not os.path.isfile(chrome_path):
            return False, "未找到 Google Chrome，请确认已安装。"

        # Chrome 启动参数（通用）
        chrome_args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--silent-launch",
        ]

        if sys.platform == 'darwin':
            # macOS: 通过 LaunchAgent 启动（避免 TCC 权限问题）
            import plistlib

            plist_content = {
                "Label": self._LAUNCH_AGENT_LABEL,
                "ProgramArguments": chrome_args,
                "RunAtLoad": True,
                "StandardOutPath": "/tmp/rt-chrome-stdout.log",
                "StandardErrorPath": "/tmp/rt-chrome-stderr.log",
            }

            os.makedirs(os.path.dirname(self._LAUNCH_AGENT_PLIST), exist_ok=True)

            # 如果有旧的 plist，先 unload
            if os.path.exists(self._LAUNCH_AGENT_PLIST):
                try:
                    subprocess.run(
                        ["launchctl", "unload", self._LAUNCH_AGENT_PLIST],
                        timeout=5, capture_output=True
                    )
                except Exception:
                    pass

            with open(self._LAUNCH_AGENT_PLIST, "wb") as f:
                plistlib.dump(plist_content, f)

            log_info(f"启动 Chrome (LaunchAgent): 端口 {port}, 数据目录 {user_data_dir}")

            try:
                subprocess.run(
                    ["launchctl", "load", self._LAUNCH_AGENT_PLIST],
                    check=True, timeout=10, capture_output=True
                )
            except Exception as e:
                log_exception("Chrome 启动异常", type(e), e, e.__traceback__)
                return False, f"Chrome 启动失败: {e}"
        else:
            # Windows / Linux: 直接启动
            log_info(f"启动 Chrome: 端口 {port}, 数据目录 {user_data_dir}")

            try:
                if sys.platform == 'win32':
                    # Windows: DETACHED_PROCESS 防止父进程退出时连带杀死 Chrome
                    CREATE_NEW_PROCESS_GROUP = 0x00000200
                    DETACHED_PROCESS = 0x00000008
                    subprocess.Popen(
                        chrome_args,
                        creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    # Linux
                    subprocess.Popen(
                        chrome_args,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
            except Exception as e:
                log_exception("Chrome 启动异常", type(e), e, e.__traceback__)
                return False, f"Chrome 启动失败: {e}"

        # 等待端口就绪
        if not wait_for_port(port, timeout=20):
            log_error(f"Chrome 启动后端口 {port} 未就绪")
            return False, f"Chrome 启动后端口 {port} 未就绪，请检查。"

        log_info(f"Chrome 调试模式已启动（端口 {port}）")
        return True, f"Chrome 调试模式已启动（端口 {port}）。"

    def is_chrome_running(self) -> bool:
        """检测 Chrome 调试端口是否可用。"""
        port = self.config.get("chrome", {}).get("debug_port", 9222)
        return is_port_in_use(port)

    def is_page_open(self, url: str) -> bool:
        """
        检测指定 URL 的页面是否仍然打开着。

        通过 CDP HTTP 接口查询已打开的标签页列表。
        使用域名级匹配 + 重定向缓存，避免重定向导致 URL 变化后误判。
        """
        if not self.is_chrome_running():
            return False

        port = self.config.get("chrome", {}).get("debug_port", 9222)
        try:
            import urllib.request
            import json as _json
            from urllib.parse import urlparse
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2
            )
            tabs = _json.loads(resp.read())
            # 收集所有要匹配的域名
            config_domain = urlparse(url).netloc if url else ""
            # 也检查重定向缓存中的域名
            domains_to_check = {config_domain}
            final_url = self._url_redirect_cache.get(url)
            if final_url:
                domains_to_check.add(urlparse(final_url).netloc)
            domains_to_check.discard("")

            for tab in tabs:
                if tab.get("type") != "page":
                    continue
                tab_url = tab.get("url", "")
                tab_domain = urlparse(tab_url).netloc
                if tab_domain in domains_to_check:
                    return True
                # 回退到包含匹配
                if url in tab_url:
                    return True
            return False
        except Exception:
            return False

    def stop_chrome(self):
        """
        停止 Chrome 调试进程（跨平台）。

        macOS: launchctl unload + pkill 后备
        Windows: taskkill 终止进程树
        Linux: pkill
        """
        import subprocess
        import time

        port = self.config.get("chrome", {}).get("debug_port", 9222)

        if sys.platform == 'darwin':
            # macOS: 通过 launchctl unload 让 launchd 终止 Chrome
            if os.path.exists(self._LAUNCH_AGENT_PLIST):
                try:
                    subprocess.run(
                        ["launchctl", "unload", self._LAUNCH_AGENT_PLIST],
                        timeout=5, capture_output=True
                    )
                    log_info("Chrome 已通过 launchctl unload 停止")
                except Exception as e:
                    log_warning(f"launchctl unload 失败: {e}")

            # 等待端口释放
            deadline = time.time() + 3
            while time.time() < deadline:
                if not is_port_in_use(port):
                    break
                time.sleep(0.5)

            # 后备：pkill
            if is_port_in_use(port):
                try:
                    subprocess.run(
                        ["pkill", "-f", f"remote-debugging-port={port}"],
                        timeout=5, capture_output=True
                    )
                    log_info(f"Chrome 已通过 pkill 强制关闭 (port={port})")
                    time.sleep(1)
                except Exception as e:
                    log_warning(f"pkill 关闭 Chrome 失败: {e}")
        elif sys.platform == 'win32':
            # Windows: 用 taskkill 终止带特定端口的 Chrome 进程
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                    timeout=10, capture_output=True
                )
                log_info("Chrome 已通过 taskkill 停止")
                time.sleep(1)
            except Exception as e:
                log_warning(f"taskkill 关闭 Chrome 失败: {e}")
        else:
            # Linux
            try:
                subprocess.run(
                    ["pkill", "-f", f"remote-debugging-port={port}"],
                    timeout=5, capture_output=True
                )
                log_info(f"Chrome 已通过 pkill 关闭 (port={port})")
                time.sleep(1)
            except Exception as e:
                log_warning(f"pkill 关闭 Chrome 失败: {e}")

        # 清理 Playwright 资源
        # 注意：退出时事件循环可能已停止，不要尝试 run_until_complete
        self._context = None
        self._browser = None
        if self._playwright:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 事件循环仍在运行，安全地调度异步清理
                    task = asyncio.ensure_future(self._playwright.stop())
                    # 添加异常回调，避免 "Task exception was never retrieved"
                    def _suppress_exc(t):
                        try:
                            t.result()
                        except Exception:
                            pass
                    task.add_done_callback(_suppress_exc)
                else:
                    # 事件循环已停止，直接置空，让进程退出时自动清理
                    pass
            except Exception:
                pass
            self._playwright = None

    # ------------------------------------------------------------------
    # Playwright 连接
    # ------------------------------------------------------------------

    async def connect_playwright(self, max_retries: int = 3) -> Browser:
        """
        获取 Playwright Browser 实例。

        优先使用 launch_persistent_context 启动的浏览器；
        如果 Chrome 是外部启动的，则通过 CDP 连接。

        Returns:
            Browser: Playwright Browser 实例

        Raises:
            ConnectionError: 连接失败
        """
        # 如果有 persistent context，直接返回其 Browser
        if self._context is not None:
            try:
                browser = self._context.browser
                if browser is not None:
                    return browser
            except Exception:
                pass

        if self._browser is not None:
            try:
                _ = self._browser.contexts
                return self._browser
            except Exception:
                self._browser = None

        # 清除代理环境变量
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(var, None)

        port = self.config.get("chrome", {}).get("debug_port", 9222)
        cdp_url = f"http://127.0.0.1:{port}"

        log_info(f"Playwright CDP 连接: {cdp_url}")

        last_error = None
        for attempt in range(max_retries):
            try:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                log_info("Playwright CDP 连接成功")
                return self._browser
            except Exception as e:
                last_error = e
                log_warning(f"Playwright 连接尝试 {attempt + 1}/{max_retries} 失败: {e}")
                await asyncio.sleep(1)

        raise ConnectionError(
            f"Playwright 连接 Chrome 失败（重试 {max_retries} 次）: {last_error}。"
            f"请确认 Chrome 调试模式已启动。"
        )

    async def get_or_create_page(self, url: str) -> Page:
        """
        获取已打开该 URL 的页面，或新建并导航。

        使用锁保护，防止并发调用导致重复打开页面。
        导航完成后，通过 osascript 将本应用拉回前台，
        防止 Chrome 抢占台前显示。

        Args:
            url: 目标 AI 平台 URL

        Returns:
            Page: Playwright Page 对象
        """
        async with self._page_lock:
            # 优先使用 persistent context
            if self._context is not None:
                for page in self._context.pages:
                    try:
                        if self._url_matches_with_redirect(url, page.url):
                            log_info(f"找到已打开的页面: {page.url}")
                            await self._bring_app_to_front()
                            return page
                    except Exception:
                        continue
                # 新建页面
                log_info(f"新建页面并导航到: {url}")
                page = await self._context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                log_info(f"页面已加载: {url}")
                self._bring_app_to_front()
                return page

            # CDP 回退
            browser = await self.connect_playwright()

            for context in browser.contexts:
                for page in context.pages:
                    try:
                        if self._url_matches_with_redirect(url, page.url):
                            log_info(f"找到已打开的页面: {page.url}")
                            self._bring_app_to_front()
                            return page
                    except Exception:
                        continue

            log_info(f"新建页面并导航到: {url}")
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            # 记录重定向后的最终 URL（处理跨域重定向）
            try:
                final_url = page.url
                if final_url and final_url != url:
                    from urllib.parse import urlparse
                    config_domain = urlparse(url).netloc
                    final_domain = urlparse(final_url).netloc
                    if config_domain != final_domain:
                        log_info(f"检测到跨域重定向: {url} → {final_url}")
                        self._url_redirect_cache[url] = final_url
            except Exception:
                pass
            log_info(f"页面已加载: {url}")
            await self._bring_app_to_front()
            return page

    async def _bring_app_to_front(self):
        """将本应用拉回前台（跨平台，异步，不阻塞事件循环）。"""
        try:
            if sys.platform == 'darwin':
                # macOS: osascript
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", 'tell application "聚慧" to activate',
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=3)
            # Windows/Linux: 不需要特殊处理，Qt 窗口会自动获得焦点
        except Exception as e:
            log_warning(f"拉回前台失败: {e}")

    @staticmethod
    def _url_matches(config_url: str, page_url: str) -> bool:
        """
        判断页面 URL 是否匹配配置 URL。

        采用域名级匹配，避免路径差异导致重复打开。
        例如配置 https://chat.deepseek.com/ 能匹配 https://chat.deepseek.com/sign_in

        Args:
            config_url: 配置中的平台 URL
            page_url: 浏览器中实际的页面 URL

        Returns:
            bool: 是否匹配
        """
        if not config_url or not page_url:
            return False
        # 提取域名进行比较
        try:
            from urllib.parse import urlparse
            config_domain = urlparse(config_url).netloc
            page_domain = urlparse(page_url).netloc
            if config_domain and page_domain:
                return config_domain == page_domain
        except Exception:
            pass
        # 回退到包含匹配
        return config_url in page_url

    def _url_matches_with_redirect(self, config_url: str, page_url: str) -> bool:
        """
        判断页面 URL 是否匹配配置 URL（含重定向缓存检查）。

        在 _url_matches 基础上，额外检查重定向缓存中记录的最终域名。
        """
        if self._url_matches(config_url, page_url):
            return True
        # 检查重定向缓存
        final_url = self._url_redirect_cache.get(config_url)
        if final_url and self._url_matches(final_url, page_url):
            return True
        return False

    async def close_page(self, url: str) -> bool:
        """
        关闭已打开的指定 URL 的页面。

        Args:
            url: 目标 AI 平台 URL

        Returns:
            bool: 是否成功关闭
        """
        try:
            closed = False

            # 优先使用 persistent context
            if self._context is not None:
                for page in self._context.pages:
                    try:
                        if url in page.url:
                            await page.close()
                            log_info(f"已关闭页面: {url}")
                            closed = True
                    except Exception:
                        continue
                return closed

            # CDP 回退
            browser = await self.connect_playwright()
            for context in browser.contexts:
                for page in context.pages:
                    try:
                        if url in page.url:
                            await page.close()
                            log_info(f"已关闭页面: {url}")
                            closed = True
                    except Exception:
                        continue
            return closed
        except Exception as e:
            log_warning(f"关闭页面失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 新对话 / 消息发送 / 等待 / 提取
    # ------------------------------------------------------------------

    async def start_new_chat(self, page: Page, ai_config: dict) -> bool:
        """
        在 AI 平台上开启新对话。

        策略：
        1. 尝试点击"新对话"/"新建对话"按钮
        2. 如果找不到按钮，重新导航到平台 URL

        Args:
            page: Playwright Page
            ai_config: AI 平台配置

        Returns:
            bool: 是否成功开启新对话
        """
        ai_name = ai_config.get("name", "")
        url = ai_config.get("url", "")

        # 新对话按钮选择器（多种平台兼容）
        new_chat_selectors = [
            # DeepSeek
            "div[role='button']:has-text('新建对话')",
            "button:has-text('新建对话')",
            "a:has-text('新建对话')",
            "div[class*='new']:has-text('新')",
            # 智谱清言
            "div:has-text('新对话')",
            "button:has-text('新对话')",
            # 通用
            "button:has-text('New Chat')",
            "button:has-text('新建')",
            "a[href*='new']",
            "[class*='new-chat']",
            "[class*='newChat']",
        ]

        try:
            for selector in new_chat_selectors:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        await el.click()
                        await page.wait_for_timeout(2000)
                        log_info(f"[{ai_name}] 通过按钮开启新对话: {selector}")
                        return True
                except Exception:
                    continue

            # 没找到按钮，重新导航
            log_info(f"[{ai_name}] 未找到新对话按钮，重新导航到 {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            log_info(f"[{ai_name}] 已重新导航，开启新对话")
            return True

        except Exception as e:
            log_warning(f"[{ai_name}] 开启新对话失败: {e}")
            return False

    async def send_and_wait(self, page: Page, message: str,
                            ai_config: dict, timeout: int = 120,
                            fast_wait: bool = False) -> str:
        """
        发送消息并等待 AI 回复完成，提取最新回复纯文本。

        流程：
        1. （可选）上传文件
        2. 定位输入框并填充消息
        3. 点击发送按钮（多种策略）
        4. 主策略：等待"停止生成"按钮消失（AI 输出完成）
        5. 备选策略：内容稳定检测（连续3次内容不变）
        6. 提取最新一条回复的纯文本

        Args:
            page: Playwright Page
            message: 要发送的消息文本
            ai_config: AI 平台配置（含 selectors）
            timeout: 单轮最大等待秒数
            fast_wait: 是否使用快速等待模式

        Returns:
            str: AI 回复的纯文本

        Raises:
            TimeoutError: 等待回复超时
            Exception: 发送或提取失败
        """
        selectors = ai_config.get("selectors", {})
        input_selector = selectors.get("input_textarea", "textarea")
        send_selector = selectors.get("send_button", "button[type='submit']")
        send_button_selectors = selectors.get("send_button_selectors", [])
        stop_selector = selectors.get("stop_button", "")
        last_response_selector = selectors.get("last_response", "")

        timeout_ms = timeout * 1000
        ai_name = ai_config.get("name", "未知")

        # 检查页面是否已关闭，如果关闭则尝试重新获取
        try:
            if page.is_closed():
                log_warning(f"[{ai_name}] 页面已关闭，尝试重新获取页面...")
                page = await self.get_or_create_page(ai_config["url"])
                if page.is_closed():
                    raise Exception(f"页面重新获取失败: {ai_name} 页面仍然关闭")
                log_info(f"[{ai_name}] 页面重新获取成功")
        except Exception as e:
            if "Target page" in str(e) or "has been closed" in str(e) or page.is_closed():
                log_warning(f"[{ai_name}] 页面不可用({e})，尝试重新获取...")
                try:
                    page = await self.get_or_create_page(ai_config["url"])
                    log_info(f"[{ai_name}] 页面重新获取成功")
                except Exception as e2:
                    raise Exception(f"页面不可用且重新获取失败: {e2}")

        try:
            # 0.5 记录发送前的状态（页面内容长度 + 回复区块数）
            state_before = await page.evaluate("""() => {
                const selectors = '.ds-markdown--content, div[class*="message-content"], div[class*="markdown-body"], div[class*="message__content"], div[class*="answer-content"], div[class*="reply-content"], div[class*="bubble"], div[data-role="assistant"]';
                const els = document.querySelectorAll(selectors);
                return {
                    count: els.length,
                    content_len: document.body.innerText.length
                };
            }""")
            reply_count_before = state_before.get("count", 0)
            content_len_before = state_before.get("content_len", 0)
            log_info(f"[{ai_name}] 发送前状态: 回复区块={reply_count_before}, 内容长度={content_len_before}")

            # 1. 定位输入框并填充（带重试，粘贴文件后页面可能重渲染）
            # 检查消息长度，超过50000字时自动转为文件上传
            MAX_INLINE_LENGTH = 50000
            if len(message) > MAX_INLINE_LENGTH:
                import time as _time_for_file
                log_info(f"[{ai_name}] 消息过长（{len(message)}字 > {MAX_INLINE_LENGTH}字），转为文件上传...")
                import os
                # 创建临时txt文件
                tmp_dir = os.path.expanduser("~/.polysage/temp")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_file = os.path.join(tmp_dir, f"prompt_{ai_name}_{int(_time_for_file.time())}.txt")
                with open(tmp_file, "w", encoding="utf-8") as f:
                    f.write(message)
                log_info(f"[{ai_name}] 已创建临时文件: {tmp_file}")

                # 上传文件到AI页面
                try:
                    await self._upload_file(page, tmp_file, ai_name)
                    log_info(f"[{ai_name}] 文件上传成功，等待页面处理...")
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    log_warning(f"[{ai_name}] 文件上传失败: {e}，回退到截断发送")
                    # 上传失败则截断消息
                    message = message[:MAX_INLINE_LENGTH] + "\n\n[注意：消息过长已被截断，完整内容请见上传的文件]"
                    tmp_file = None

                # 发送简短说明消息
                if tmp_file:
                    short_msg = "请先阅读上传的文件内容，然后根据文件中的内容进行回复。"
                    message = short_msg

            log_info(f"[{ai_name}] 定位输入框: {input_selector}")
            input_el = await self._try_locate(page, input_selector, state="visible", timeout=10000)
            if input_el is None:
                raise Exception("输入框未找到，网页可能已更新或未登录。")

            fill_ok = False
            for attempt in range(3):
                try:
                    await input_el.click()
                    await page.wait_for_timeout(300)
                    # 方法1：用 execCommand 模拟真实文本插入（Vue/React都能识别）
                    fill_success = await page.evaluate("""(msg) => {
                        const el = document.querySelector('textarea, [contenteditable="true"], [role="textbox"]');
                        if (!el) return false;
                        el.focus();
                        // 先清空
                        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                            el.value = '';
                            el.select();
                        } else {
                            el.textContent = '';
                            const range = document.createRange();
                            range.selectNodeContents(el);
                            const sel = window.getSelection();
                            sel.removeAllRanges();
                            sel.addRange(range);
                        }
                        // 用 execCommand 插入文本（触发完整的input事件链）
                        const inserted = document.execCommand('insertText', false, msg);
                        if (inserted) {
                            return true;
                        }
                        // execCommand 失败，回退到 nativeInputValueSetter
                        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLTextAreaElement.prototype, 'value'
                            ).set;
                            nativeInputValueSetter.call(el, msg);
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                        el.textContent = msg;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        return true;
                    }""", message)
                    await page.wait_for_timeout(300)
                    if not fill_success:
                        # 回退到 fill
                        await input_el.fill(message)
                        await page.wait_for_timeout(200)
                    # 验证Vue/React是否同步了状态：检查发送按钮是否不再是"empty"状态
                    state_ok = await page.evaluate("""() => {
                        const btn = document.querySelector('.enter-icon-container, div[class*="send"]');
                        if (btn && btn.className.includes('empty')) {
                            return false;  // 按钮仍为empty状态，框架未同步
                        }
                        const ta = document.querySelector('textarea');
                        if (ta && ta.value && ta.value.length > 5) return true;
                        return true;  // 无法判断，假设成功
                    }""")
                    if not state_ok:
                        log_warning(f"[{ai_name}] 填充后发送按钮仍为empty状态，尝试用keyboard.type补充")
                        # 用execCommand再试一次
                        await page.evaluate("""(msg) => {
                            const el = document.querySelector('textarea');
                            if (el) {
                                el.focus();
                                el.select();
                                document.execCommand('insertText', false, msg);
                            }
                        }""", message)
                        await page.wait_for_timeout(300)
                    log_info(f"[{ai_name}] 消息已填充（长度 {len(message)}），开始发送...")
                    fill_ok = True
                    break
                except Exception as e:
                    log_warning(f"[{ai_name}] 填充消息失败(尝试{attempt+1}/3): {e}")
                    # 元素可能已失效，重新定位
                    await page.wait_for_timeout(1000)
                    input_el = await self._try_locate(page, input_selector, state="visible", timeout=5000)
                    if input_el is None:
                        # 尝试其他选择器
                        for sel in ["textarea", '[contenteditable="true"]', '.ProseMirror', '[role="textbox"]']:
                            input_el = await self._try_locate(page, sel, state="visible", timeout=2000)
                            if input_el is not None:
                                break
                    if input_el is None:
                        raise Exception("输入框重定位失败，网页可能已更新或未登录。")

            if not fill_ok:
                raise Exception("消息填充失败，输入框可能已失效。")

            # 2. 激活输入框（触发 input 事件，让发送按钮变为可用）
            await self._activate_input(page, input_el, ai_name)

            # 3. 点击发送按钮（多种策略）
            sent = await self._click_send_button(page, send_selector, input_el, ai_name, message, send_button_selectors)
            if not sent:
                log_error(f"[{ai_name}] 所有发送策略均失败")
                raise Exception("无法找到发送按钮，请检查网页是否已更新。")

            log_info(f"[{ai_name}] 消息已发送，等待回复...")

            # 记录对话状态（用于验证提取的回复）
            import time as _time
            self._last_sent_to[ai_name] = {
                "message": message,
                "timestamp": _time.time(),
                "content_len_before": content_len_before,
                "reply_count_before": reply_count_before,
            }
            msg_preview = message[:50].replace('\n', ' ') + ('...' if len(message) > 50 else '')
            log_info(f"[{ai_name}] 对话状态已记录: 发送了({len(message)}字) '{msg_preview}'")

            # 4. 等待回复完成（传入发送前的状态和发送的消息）
            import time as _time_mod
            overall_deadline = _time_mod.time() + (timeout_ms / 1000)  # 总超时截止时间
            # 重新测量基线：文件上传和消息发送可能已经改变了页面内容
            try:
                content_len_after_send = await page.evaluate("""() => document.body.innerText.length""")
                if content_len_after_send != content_len_before:
                    log_info(f"[{ai_name}] 发送后内容长度变化: {content_len_before} → {content_len_after_send}，使用新基线")
                    content_len_before = content_len_after_send
            except Exception:
                pass
            await self._wait_for_reply_complete(page, stop_selector, timeout_ms, reply_count_before, content_len_before, message, fast_wait)

            # 5. 提取最新回复，带验证重试
            # 重试次数和间隔根据剩余超时时间动态计算，不超过配置的 timeout_seconds
            reply_text = ""
            sent_state = self._last_sent_to.get(ai_name, {})
            sent_msg_preview = (sent_state.get("message", "")[:80] or "").replace('\n', ' ')

            max_retries = 10
            # 初始化提示特征词，用于在JS提取阶段排除开场白容器
            init_markers = [
                "你正在参与一场多AI群聊协作",
                "多AI群聊协作",
                "请等待发起话题",
                "明白了就回复",
                "【规则】",
                "本次军帐议事一共有谋士",
                "需要你与其他AI展开深度推演",
            ]
            # Kimi 等平台的占位符文本，提取到这些说明不是AI回复
            placeholder_markers = [
                "问点难的，让我多想一步",
                "K2.6 思考",
                "K2.6 快速",
                "K1.5 思考",
                "K1.5 快速",
                '输入 "/" 唤起插件和技能',
                "高峰时段算力不足",
                "升级会员畅用思考模型",
                "算力不足",
                # 通义千问侧边栏元素
                "我的空间", "智能体", "对话分组", "新分组",
                "最近对话", "Qwen9953", "新建聊天",
                # MiniMax分段回复UI标签
                "继续生成", "查看更多", "加载更多",
            ]
            # 智谱清言广告/推广内容特征
            ad_markers = [
                "GLM-", "旗舰模型上线",
                "扫描二维码", "保存名片", "分享智能体",
                "点击体验", "立即下载",
            ]
            _last_page_len = -1  # 上次重试时的页面内容长度（用于检测页面是否变化）
            for retry in range(max_retries):
                # 检查是否已超过总超时
                remaining = overall_deadline - _time_mod.time()
                if remaining <= 5:
                    log_warning(f"[{ai_name}] 总超时已到（剩余 {remaining:.0f}s），停止重试")
                    break
                # 智能重试间隔：如果页面内容未变化（提取问题而非AI还在思考），缩短等待
                try:
                    current_page_len = await page.evaluate("() => document.body.innerText.length")
                except Exception:
                    current_page_len = 0
                page_changed = (current_page_len != _last_page_len)
                _last_page_len = current_page_len
                if retry == 0:
                    retry_interval = max(5, min(15, int(remaining / 5)))
                elif page_changed:
                    # 页面有变化，AI可能还在输出，正常等待
                    retry_interval = max(5, min(15, int(remaining / 5)))
                else:
                    # 页面未变化，是提取逻辑问题，缩短等待避免浪费时间
                    retry_interval = 3
                    log_info(f"[{ai_name}] 页面内容未变化（{current_page_len}字），缩短重试间隔至{retry_interval}s")

                reply_text = await self._extract_last_response(page, last_response_selector, timeout_ms, ai_name, reply_count_before, message, init_markers)
                if not reply_text:
                    log_warning(f"[{ai_name}] 提取为空，重试 {retry+1}/{max_retries}...（等待AI回复中，{retry_interval}s后重试，剩余{remaining:.0f}s）")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是初始化提示（开场白/系统提示词）
                init_indicators = [
                    ("【规则】" in reply_text and "请等待发起话题" in reply_text),
                    ("你正在参与一场多AI群聊协作" in reply_text and "【规则】" in reply_text),
                    ("请等待发起话题" in reply_text and "明白了就回复" in reply_text),
                    ("多AI群聊协作" in reply_text and "深度推演" in reply_text and reply_text.strip().startswith("你正在")),
                ]
                if any(init_indicators):
                    log_warning(f"[{ai_name}] 提取到初始化提示而非AI回复，重试 {retry+1}/{max_retries}...（AI可能还在思考，{retry_interval}s后重试）")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是占位符/UI提示文字（Kimi等平台的输入框提示、模型选择器文字）
                if any(p in reply_text for p in placeholder_markers) and len(reply_text.strip()) < 50:
                    log_warning(f"[{ai_name}] 提取到占位符/UI文字而非AI回复({reply_text[:30]})，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是广告/推广内容（智谱清言页面底部广告）
                if any(ad in reply_text for ad in ad_markers) and len(reply_text.strip()) < 100:
                    log_warning(f"[{ai_name}] 提取到广告/推广内容而非AI回复({reply_text[:30]})，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是侧边栏导航内容（通义千问侧边栏）
                sidebar_lines = [l.strip() for l in reply_text.split('\n') if l.strip()]
                sidebar_label_count = sum(1 for l in sidebar_lines if l in ["新建对话", "我的空间", "智能体", "对话分组", "新分组", "最近对话", "Qwen9953", "新建聊天", "历史记录", "设置", "帮助"])
                if len(sidebar_lines) >= 3 and sidebar_label_count >= len(sidebar_lines) * 0.5:
                    log_warning(f"[{ai_name}] 提取到侧边栏导航内容而非AI回复({reply_text[:30]})，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是"回复N/M"等MiniMax分段UI标签
                import re as _re
                if _re.match(r'^回复\d+/\d+$', reply_text.strip()) or _re.match(r'^\d+/\d+$', reply_text.strip()):
                    log_warning(f"[{ai_name}] 提取到分段UI标签({reply_text[:30]})，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是文件附件标签（如"PolySage_技术文档.txt 36KB"）
                if _re.match(r'^[\w\u4e00-\u9fff\-_.]+\.(txt|md|csv|pdf|docx?|xlsx?|pptx?|zip|rar)\s*\n?\s*\d*(KB|MB|GB|B)?\s*$', reply_text.strip(), _re.IGNORECASE):
                    log_warning(f"[{ai_name}] 提取到文件附件标签({reply_text[:30]})，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复太短（<20字）时很可能是提取到了页面片段而非完整AI回复
                if len(reply_text.strip()) < 20:
                    log_warning(f"[{ai_name}] 提取内容过短({len(reply_text)}字: {reply_text[:30]})，可能不是完整回复，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能是发送的消息本身
                if reply_text.strip() == message.strip():
                    log_warning(f"[{ai_name}] 提取到发送消息本身，重试 {retry+1}/{max_retries}...（AI可能还没开始回复）")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能与上一次回复完全相同（防止提取到旧回复）
                last_reply = self._last_reply.get(ai_name, "")
                if last_reply and reply_text.strip() == last_reply.strip():
                    log_warning(f"[{ai_name}] 提取到与上一次完全相同的回复（{len(reply_text)}字），可能提取了旧回复，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能包含发送消息的大部分内容（工具发送的消息被提取了）
                if len(message) > 50 and message.strip()[:80] in reply_text and reply_text.strip()[:80] in message:
                    log_warning(f"[{ai_name}] 提取内容与发送消息高度重叠，重试 {retry+1}/{max_retries}...（AI可能还没开始回复）")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复不能太短（AI回复至少应该有几个字，"ok"除外）
                if len(reply_text.strip()) < 2 and "ok" not in reply_text.lower():
                    log_warning(f"[{ai_name}] 提取内容过短（{len(reply_text)}字），重试 {retry+1}/{max_retries}...（AI可能还在思考）")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：内容长度交叉检查
                # 如果页面内容增长很多但提取的回复很短，可能提取了UI元素（如"录音纪要"）
                try:
                    current_content_len = await page.evaluate("() => document.body.innerText.length")
                except Exception:
                    current_content_len = 0
                content_growth = current_content_len - content_len_before
                if content_growth > 200 and len(reply_text.strip()) < 50 and "ok" not in reply_text.lower():
                    log_warning(f"[{ai_name}] 提取内容过短（{len(reply_text)}字）但页面内容增长{content_growth}字，可能提取了UI元素，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：提取内容远小于内容增长（可能只提取了一个片段）
                if content_growth > 500 and len(reply_text.strip()) < content_growth * 0.15 and "ok" not in reply_text.lower():
                    log_warning(f"[{ai_name}] 提取内容({len(reply_text)}字)远小于内容增长({content_growth}字)，可能只提取了片段，重试 {retry+1}/{max_retries}...")
                    await asyncio.sleep(retry_interval)
                    continue
                # 验证：回复可能被截断（以常见标点结尾则视为完整，否则可能还在输出）
                # 只在前2次重试且页面仍在变化时检查，避免无限等待
                if retry < 2 and len(reply_text) > 50 and page_changed:
                    stripped_end = reply_text.rstrip()
                    # 检查是否以常见结束标点结尾
                    ends_properly = stripped_end.endswith(('.', '。', '!', '！', '?', '？', '"', '"', "'", "'", ')', '）', '```', '<End>', '<End>', '---', '***'))
                    if not ends_properly:
                        log_warning(f"[{ai_name}] 提取内容可能被截断（不以标点结尾），重试 {retry+1}/{max_retries}...（AI可能还在输出）")
                        await asyncio.sleep(min(retry_interval, 10))
                        continue
                # 验证通过
                log_info(f"[{ai_name}] ✅ 回复验证通过（{len(reply_text)}字）")
                self._last_reply[ai_name] = reply_text  # 记录本次回复，用于下次去重
                break
            else:
                log_warning(f"[{ai_name}] 重试{max_retries}次后仍无法提取有效回复，尝试通用提取")
                # 最后尝试：通用DOM提取
                try:
                    generic = await self._extract_generic_response(page, ai_name)
                    if generic and len(generic) > len(reply_text):
                        reply_text = generic
                        log_info(f"[{ai_name}] 通用提取成功（{len(reply_text)}字）")
                except Exception:
                    pass
                log_warning(f"[{ai_name}] 使用当前内容: {reply_text[:50]}...")

            # 6. 后处理：过滤残留的思考过程内容
            reply_text = self._strip_thinking_content(reply_text, ai_name)

            log_info(f"[{ai_name}] 回复提取完成（长度 {len(reply_text)}）: {reply_text[:100]}...")
            return reply_text

        except TimeoutError:
            raise
        except Exception as e:
            log_exception(f"[{ai_name}] 发送消息失败", type(e), e, e.__traceback__)
            raise Exception(f"发送消息失败: {e}")

    async def _upload_file(self, page: Page, file_path: str, ai_name: str):
        """上传文件到 AI 平台。

        统一使用模拟粘贴/拖放事件，不依赖各平台的上传按钮。
        跟粘贴开场白一样的方式，绕过每个AI上传按钮不同的问题。
        """
        import os as _os
        file_name = _os.path.basename(file_path)

        try:
            # 关闭已知弹窗
            try:
                await page.evaluate("""() => {
                    const knownPopups = ['#maasGuidePopover', '[class*="guide-popover"]', '[class*="activity-modal"]'];
                    knownPopups.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });
                }""")
                await page.wait_for_timeout(300)
            except Exception:
                pass

            # 模拟粘贴/拖放文件
            log_info(f"[{ai_name}] 上传文件(粘贴/拖放): {file_path}")
            await self._upload_via_paste_drop(page, file_path, file_name, ai_name)
            await page.wait_for_timeout(2000)

            # 验证
            if await self._verify_file_uploaded(page, file_name, ai_name):
                return

            # 粘贴失败，回退到 input[type=file]（DeepSeek 等平台可用）
            log_warning(f"[{ai_name}] 粘贴/拖放失败，回退到 input[type=file]")
            file_inputs = await page.query_selector_all("input[type='file']")
            if file_inputs:
                import os as _os2
                file_ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
                for idx, fi in enumerate(file_inputs):
                    try:
                        accept_attr = await fi.get_attribute("accept") or ""
                        # 检查 accept 是否匹配文件扩展名
                        if accept_attr and file_ext:
                            accept_exts = [e.strip().lower() for e in accept_attr.split(",")]
                            if file_ext not in accept_exts and "/*" not in " ".join(accept_exts):
                                continue
                        await fi.set_input_files(file_path)
                        await page.wait_for_timeout(2000)
                        if await self._verify_file_uploaded(page, file_name, ai_name):
                            return
                        else:
                            try:
                                await fi.set_input_files([])
                            except Exception:
                                pass
                    except Exception:
                        continue

            log_warning(f"[{ai_name}] 文件上传失败")

        except Exception as e:
            log_warning(f"[{ai_name}] 文件上传失败: {e}")

    async def _upload_via_paste_drop(self, page: Page, file_path: str,
                                       file_name: str, ai_name: str) -> bool:
        """模拟粘贴和拖放事件上传文件（绕过上传按钮）。

        读取文件内容 → 创建 File 对象 → 触发 paste 和 drop 事件。
        """
        try:
            with open(file_path, "rb") as f:
                file_content = f.read()

            import mimetypes
            mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

            # 先聚焦输入框
            input_selectors = ["textarea", '[contenteditable="true"]', ".ProseMirror", '[role="textbox"]']
            for sel in input_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click(timeout=2000)
                        break
                except Exception:
                    continue

            # 注入 JS：创建 File 对象，触发 paste 事件（成功则不再 drop）
            result = await page.evaluate(
                """([fileName, fileBytes, mimeType]) => {
                // 创建 File 对象
                const uint8 = new Uint8Array(fileBytes);
                const file = new File([uint8], fileName, { type: mimeType });

                // 找到输入框
                const input = document.querySelector('textarea, [contenteditable="true"], .ProseMirror, [role="textbox"]')
                    || document.activeElement;
                if (!input) return 'no-input';

                let pasteOk = false;
                let dropOk = false;

                // --- 尝试 paste 事件 ---
                try {
                    const dt = new DataTransfer();
                    dt.items.add(file);

                    const pasteEvent = new ClipboardEvent('paste', {
                        bubbles: true,
                        cancelable: true,
                    });

                    // 设置 clipboardData
                    const cd = {
                        files: [file],
                        items: [{ kind: 'file', type: file.type, getAsFile: () => file }],
                        getData: () => '',
                        setData: () => {},
                        types: ['Files'],
                    };
                    Object.defineProperty(pasteEvent, 'clipboardData', {
                        value: cd, writable: false, configurable: true,
                    });

                    input.dispatchEvent(pasteEvent);
                    pasteOk = true;
                } catch (e) {
                    // paste 失败，继续尝试 drop
                }

                // --- 只有 paste 失败时才尝试 drop（避免文件被粘贴两次） ---
                if (!pasteOk) {
                    try {
                        const dt2 = new DataTransfer();
                        dt2.items.add(file);
                        dt2.setData('Files', '');

                        const dragEnterEvent = new DragEvent('dragenter', {
                            bubbles: true, cancelable: true, dataTransfer: dt2,
                        });
                        const dragOverEvent = new DragEvent('dragover', {
                            bubbles: true, cancelable: true, dataTransfer: dt2,
                        });
                        const dropEvent = new DragEvent('drop', {
                            bubbles: true, cancelable: true, dataTransfer: dt2,
                        });

                        input.dispatchEvent(dragEnterEvent);
                        input.dispatchEvent(dragOverEvent);
                        input.dispatchEvent(dropEvent);
                        dropOk = true;
                    } catch (e) {
                        // drop 失败
                    }
                }

                return 'paste=' + pasteOk + ',drop=' + dropOk;
            }""",
                [file_name, list(file_content), mime_type],
            )

            log_info(f"[{ai_name}] 粘贴/拖放事件结果: {result}")
            return "true" in result
        except Exception as e:
            log_warning(f"[{ai_name}] 粘贴/拖放异常: {e}")
            return False

    async def _verify_file_uploaded(self, page: Page, file_name: str, ai_name: str) -> bool:
        """验证文件是否真正上传成功：检查页面上是否出现文件名。"""
        try:
            await page.wait_for_timeout(1500)
            page_text = await page.evaluate("() => document.body.innerText")
            # 文件名去掉扩展名后检查（有些平台只显示文件名不含扩展名）
            name_no_ext = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
            if file_name in page_text or name_no_ext in page_text:
                log_info(f"[{ai_name}] ✅ 文件上传验证成功: '{file_name}' 出现在页面上")
                return True
            else:
                log_warning(f"[{ai_name}] ❌ 文件上传验证失败: '{file_name}' 未出现在页面上")
                return False
        except Exception as e:
            log_warning(f"[{ai_name}] 文件验证异常: {e}")
            return False

    async def upload_file_to_pages(self, pages: dict, file_path: str):
        """
        将文件上传到所有 AI 页面（讨论开始前一次性调用）。

        每个 AI 页面只上传一次，重复调用不会重复上传。

        Args:
            pages: {ai_name: Page} 字典
            file_path: 本地文件绝对路径
        """
        if not file_path or not os.path.isfile(file_path):
            return
        if not hasattr(self, '_uploaded_pages'):
            self._uploaded_pages = set()
        for ai_name, page in pages.items():
            if page in self._uploaded_pages:
                continue
            try:
                log_info(f"[{ai_name}] 上传文件: {file_path}")
                await self._upload_file(page, file_path, ai_name)
                self._uploaded_pages.add(page)
            except Exception as e:
                log_warning(f"[{ai_name}] 文件上传失败: {e}")

    async def _activate_input(self, page: Page, input_el, ai_name: str):
        """
        激活输入框，触发浏览器 input 事件，使发送按钮变为可用。

        很多 AI 网页（如 DeepSeek）在输入框有用户输入前禁用发送按钮。
        Playwright 的 fill() 不会触发所有浏览器原生事件，需要手动触发。
        """
        try:
            log_info(f"[{ai_name}] 激活输入框（触发 input 事件）")

            # 再次点击确保焦点
            await input_el.click()
            await page.wait_for_timeout(100)

            # 通过 JS 触发原生 input 事件
            # 使用 page.evaluate 直接操作 DOM
            await page.evaluate("""(sel) => {
                const el = document.querySelector(sel);
                if (!el) return;
                el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('compositionend', { bubbles: true }));
            }""", 'textarea, [contenteditable="true"], [role="textbox"]')
        except Exception as e:
            log_warning(f"[{ai_name}] 激活输入框失败: {e}")

    async def _click_send_button(self, page: Page, config_selector: str,
                                  input_el, ai_name: str, message: str = "",
                                  platform_selectors: list = None) -> bool:
        """
        发送消息 — 严格单次发送，绝不重复点击。

        核心原则：
        1. 只尝试一种发送方式，发送后立即验证
        2. 如果发送成功（输入框清空/内容增长），直接返回 True
        3. 如果发送失败，返回 False，由调用方决定是否重试
        4. 绝不连续点击多个按钮 — 第一次发送后按钮可能变成"停止"按钮
        """
        before_text = ""
        try:
            before_text = await input_el.input_value()
        except Exception:
            try:
                before_text = await input_el.inner_text()
            except Exception:
                before_text = message

        # 确保输入框有焦点
        try:
            await input_el.focus()
        except Exception:
            fresh = await page.query_selector("textarea") or \
                    await page.query_selector('[contenteditable="true"]') or \
                    await page.query_selector('[role="textbox"]')
            if fresh:
                input_el = fresh
                await input_el.focus()
        await page.wait_for_timeout(200)

        # --- 方式1: Playwright Enter ---
        log_info(f"[{ai_name}] 尝试方式1: Playwright Enter 发送")
        try:
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)
            if await self._verify_sent(page, input_el, before_text, ai_name, "Playwright Enter"):
                return True
            try:
                remaining = await input_el.input_value()
            except Exception:
                remaining = ""
            if not remaining or len(remaining) < 3:
                log_info(f"[{ai_name}] 输入框已清空，消息已发送")
                return True
            log_info(f"[{ai_name}] 方式1未成功，输入框仍有 {len(remaining)} 字")
        except Exception as e:
            log_warning(f"[{ai_name}] 方式1失败: {e}")

        # --- 方式2: 点击发送按钮（只点击一次） ---
        log_info(f"[{ai_name}] 尝试方式2: 点击发送按钮")
        # 构建发送按钮选择器列表：配置优先级 > config_selector > 通用兜底
        send_selectors = []
        if platform_selectors:
            send_selectors.extend(platform_selectors)
        if config_selector and config_selector not in send_selectors:
            send_selectors.append(config_selector)
        # 通用兜底选择器（不用平台独占的，避免误触）
        generic_fallbacks = [
            'div[class*="send"]',
            'button[class*="send"]',
            'div[class*="submit"]',
        ]
        for sel in generic_fallbacks:
            if sel not in send_selectors:
                send_selectors.append(sel)
        clicked_btn = False
        for sel in send_selectors:
            if not sel:
                continue
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    clicked_btn = True
                    log_info(f"[{ai_name}] 点击发送按钮: {sel}")
                    await page.wait_for_timeout(1500)
                    if await self._verify_sent(page, input_el, before_text, ai_name, f"点击({sel})"):
                        return True
                    try:
                        remaining = await input_el.input_value()
                    except Exception:
                        remaining = ""
                    if not remaining or len(remaining) < 3:
                        log_info(f"[{ai_name}] 输入框已清空，消息已发送")
                        return True
                    break  # 只点击一个按钮
            except Exception:
                continue

        # --- 方式3: JS 点击发送按钮（只点击一次） ---
        if not clicked_btn:
            log_info(f"[{ai_name}] 尝试方式3: JS 点击发送按钮")
            try:
                clicked = await page.evaluate("""() => {
                    const zhipuBtn = document.querySelector(
                        'div.enter.is-main-chat, div.enter-icon-container:not(.empty), div[class*="enter-icon-container"]:not(.empty)'
                    );
                    if (zhipuBtn) { zhipuBtn.click(); return true; }
                    const sendBtn = document.querySelector(
                        'div[class*="send"], button[class*="send"], div[class*="submit"]'
                    );
                    if (sendBtn) { sendBtn.click(); return true; }
                    return false;
                }""")
                if clicked:
                    await page.wait_for_timeout(1500)
                    if await self._verify_sent(page, input_el, before_text, ai_name, "JS点击"):
                        return True
            except Exception as e:
                log_warning(f"[{ai_name}] 方式3失败: {e}")

        return False

    async def _verify_sent(self, page: Page, input_el, before_text: str,
                            ai_name: str, method: str) -> bool:
        """
        验证消息是否成功发送。

        判断依据（按可靠性排序）：
        1. input_el 已脱离 DOM → 发送后重新渲染输入框，说明已发送
        2. 输入框已清空或内容变化 → 已发送
        3. 页面内容增长（有新回复出现）→ 已发送
        4. 搜索弹窗出现 → 误触搜索按钮，返回 False

        使用轮询检测（每500ms检查一次，最多检查6次=3秒），
        解决React异步渲染导致延迟更新DOM的问题。
        """
        # 检查是否弹出了搜索对话框
        try:
            search_dialog = await page.query_selector(
                "[class*='search'] [class*='dialog'], [class*='search-popup'], "
                "[class*='search-modal']"
            )
            if search_dialog and await search_dialog.is_visible():
                log_warning(f"[{ai_name}] 检测到搜索弹窗，尝试关闭")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(500)
                return False
        except Exception:
            pass

        # 记录发送前的页面内容长度
        try:
            before_body_len = await page.evaluate("() => document.body.innerText.length")
        except Exception:
            before_body_len = 0

        # 轮询检测：每500ms检查一次，最多6次（3秒）
        # 解决React异步渲染导致DOM延迟更新的问题
        for check_idx in range(6):
            await page.wait_for_timeout(500)

            # 判断1：input_el 是否已脱离 DOM（发送后重新渲染输入框）
            input_detached = False
            try:
                await input_el.input_value()
            except Exception:
                input_detached = True

            if input_detached:
                log_info(f"[{ai_name}] 发送成功（{method}），输入框已重新渲染（DOM detach）[轮询第{check_idx+1}次]")
                return True

            # 判断2：输入框是否清空或内容变化
            try:
                after_text = await input_el.input_value()
            except Exception:
                after_text = ""

            if not after_text or after_text != before_text:
                log_info(f"[{ai_name}] 发送成功（{method}），输入框已清空/变化 [轮询第{check_idx+1}次]")
                return True

            # 判断3：页面内容是否增长（有新回复出现）
            try:
                after_body_len = await page.evaluate("() => document.body.innerText.length")
            except Exception:
                after_body_len = before_body_len

            if after_body_len > before_body_len + 50:
                log_info(f"[{ai_name}] 发送成功（{method}），页面内容增长 {before_body_len}→{after_body_len} [轮询第{check_idx+1}次]")
                return True

        log_warning(f"[{ai_name}] {method} 后无变化(输入框={len(after_text)}字, 页面={after_body_len})")
        return False

    async def _wait_for_reply_complete(self, page: Page, stop_selector: str,
                                       timeout_ms: int, reply_count_before: int = -1,
                                       content_len_before: int = 0,
                                       sent_message: str = "",
                                       fast_wait: bool = False):
        """
        等待 AI 回复完成（纯内容增长检测，不依赖停止按钮）。

        流程：
        1. 强制最小等待（确保AI有时间开始回复）
        2. 等待内容开始增长（AI开始输出，包括思考过程）
        3. 持续监测内容增长，直到连续N秒无变化（AI输出完成）

        fast_wait=True 时使用更短的等待时间（用于简短确认回复如"ok"）。
        """
        import time

        deadline = time.time() + (timeout_ms / 1000)
        sent_len = len(sent_message)

        # 步骤1: 强制等待（fast_wait 模式 0.3 秒，正常 1 秒）
        min_wait = 0.3 if fast_wait else 1
        log_info(f"强制等待 {min_wait} 秒...")
        await asyncio.sleep(min_wait)

        # 步骤2: 等待内容开始增长（AI开始输出，包括思考过程）
        log_info(f"等待AI回复内容开始增长（基线: {content_len_before}, 发送消息: {sent_len}）...")
        # 降低阈值：某些AI页面使用虚拟滚动，发送的消息可能不会全部出现在innerText中
        # 只要内容增长超过发送消息长度的30%+50即可
        expected_min_len = content_len_before + max(sent_len * 0.3, 50) + 50
        # 但如果发送消息很长（>5000字），不要要求太多增长
        if sent_len > 5000:
            expected_min_len = content_len_before + 200  # 长消息只需要少量增长即可
        wait_start = time.time()
        growth_started = False
        last_logged_len = 0
        log_counter = 0
        while time.time() < deadline:
            try:
                current_len = await asyncio.wait_for(
                    page.evaluate("""() => document.body.innerText.length"""),
                    timeout=10
                )
            except asyncio.TimeoutError:
                log_warning(f"页面内容检测超时(10s)，跳过增长等待")
                growth_started = True  # 跳过增长等待，直接进入稳定检测
                break
            except Exception as e:
                log_warning(f"页面内容检测异常: {e}，跳过增长等待")
                growth_started = True
                break
            if current_len > expected_min_len:
                log_info(f"内容开始增长（{current_len} > {expected_min_len}，耗时 {time.time()-wait_start:.1f}s）")
                growth_started = True
                break
            # 每5次检测记录一次，方便排查
            log_counter += 1
            if log_counter % 10 == 0 and current_len != last_logged_len:
                log_info(f"等待增长中... 当前={current_len}, 目标={expected_min_len}（已等待{time.time()-wait_start:.0f}s）")
                last_logged_len = current_len
            await asyncio.sleep(0.3 if fast_wait else 0.5)

        if not growth_started:
            log_warning(f"等待内容增长超时，继续执行")
            return

        # 步骤3: 持续监测内容增长，直到连续N秒无变化
        check_interval = 0.3 if fast_wait else 0.5
        stable_threshold = 2 if fast_wait else 4  # fast: 2s, normal: 4s
        log_info(f"监测内容增长，等待稳定（连续{stable_threshold}秒无变化）...")
        last_len = 0
        stable_seconds = 0
        monitor_start = time.time()
        shrink_detected = False
        shrink_extra = 0  # 收缩带来的额外等待秒数（按收缩比例动态计算）

        while time.time() < deadline:
            try:
                current_len = await asyncio.wait_for(
                    page.evaluate("""() => document.body.innerText.length"""),
                    timeout=10
                )
            except asyncio.TimeoutError:
                log_warning(f"页面内容监测超时(10s)，跳过稳定检测")
                break
            except Exception as e:
                log_warning(f"页面内容监测异常: {e}，跳过稳定检测")
                break

            if current_len == last_len:
                stable_seconds += check_interval
                effective_threshold = stable_threshold + shrink_extra
                if stable_seconds >= effective_threshold:
                    log_info(f"内容已稳定（长度 {current_len}，稳定 {stable_seconds}s，总监测 {time.time()-monitor_start:.1f}s，缩折叠={shrink_detected}）")
                    break
            elif current_len < last_len:
                shrink_amount = last_len - current_len
                # 按收缩比例动态计算额外等待：大幅收缩(>500字)给6秒，小幅收缩(<200字)给2秒
                if shrink_amount > 500:
                    shrink_extra = max(shrink_extra, 6)
                elif shrink_amount > 200:
                    shrink_extra = max(shrink_extra, 4)
                else:
                    shrink_extra = max(shrink_extra, 2)
                log_info(f"内容缩小: {last_len} → {current_len}（-{shrink_amount}），可能是思考过程折叠，额外等待{shrink_extra}s")
                shrink_detected = True
                stable_seconds = 0
                last_len = current_len
            else:
                if last_len > 0:
                    log_info(f"内容仍在增长: {last_len} → {current_len}（+{current_len-last_len}）")
                stable_seconds = 0
                last_len = current_len

            await asyncio.sleep(check_interval)

        # 最终等待确保渲染完成
        final_wait = 0.5 if fast_wait else 1
        await asyncio.sleep(final_wait)

    async def _wait_content_stable(self, page: Page, deadline: float,
                                   check_interval: int = 2, stable_count: int = 3):
        """
        通过内容稳定检测判断 AI 是否输出完成。
        连续 stable_count 次内容不变则认为完成。
        """
        import time

        last_content = ""
        stable = 0

        while time.time() < deadline:
            await asyncio.sleep(check_interval)
            try:
                current = await page.evaluate("""() => document.body.innerText.length""")
            except Exception:
                current = 0

            if current == last_content and current > 0:
                stable += 1
                if stable >= stable_count:
                    return
            else:
                stable = 0
            last_content = current

        # 超时也不报错，交给上层处理

    async def _extract_last_response(self, page: Page, selector: str,
                                     timeout_ms: int, ai_name: str = "",
                                     reply_count_before: int = -1,
                                     sent_message: str = "",
                                     init_markers: list = None) -> str:
        """
        提取最新一条 AI 回复的完整纯文本（排除思考过程和工具发送的消息）。

        核心策略：
        1. 在页面上找到所有"回复区块"
        2. 如果传入了 reply_count_before，只取索引 >= reply_count_before 的区块（新回复）
        3. 排除思考过程区块
        4. 排除与发送消息内容匹配的区块（工具发送的消息）
        5. 取最后一个有效区块的完整 innerText

        关键：提取容器的完整文本，而非逐个子元素，避免只拿到末尾段落。

        Args:
            page: Playwright Page
            selector: 最新回复选择器
            timeout_ms: 超时（毫秒）
            ai_name: AI 名称（用于日志）
            init_markers: 初始化提示特征词列表，用于排除开场白容器

        Returns:
            str: 完整回复纯文本（不含思考过程）
        """
        prefix = f"[{ai_name}] " if ai_name else ""
        # 初始化提示特征词（用于排除开场白容器，避免误提取）
        init_markers = init_markers or []

        # 主策略：JS 智能提取（过滤思考过程 + 排除工具发送的消息）
        log_info(f"{prefix}使用 JS 智能提取（取完整回复容器，reply_count_before={reply_count_before}）")
        try:
            text = await page.evaluate("""({replyCountBefore, sentMessage, initMarkers}) => {
                // ---- 思考过程检测 ----
                const THINKING_KEYWORDS = [
                    '分析输入', '构思回复', '起草回复', '对照约束',
                    '思考过程', '深度思考', '最终润色',
                    'Thought', 'Analysis', 'Reasoning',
                ];

                function isThinkingElement(el) {
                    const cls = (el.className || '').toString().toLowerCase();
                    // 统一过滤所有含 think 的类名（包括通义千问的 thinkingContent）
                    if (cls.includes('think')) return true;
                    if (cls.includes('reasoning') || cls.includes('chain-of-thought') || cls.includes('cot-')) return true;
                    if (cls.includes('ds-markdown--block') || cls.includes('ds-thinking')) return true;
                    // 通义千问: data-card_name="deep_think" 属性标识思考卡片
                    const cardName = el.getAttribute('data-card_name') || el.getAttribute('data-card-name') || '';
                    if (cardName && cardName.toLowerCase().includes('think')) return true;
                    // 通义千问: "深度思考已完成" 标题
                    if (el.querySelector) {
                        const titleEl = el.querySelector('.text-caption, span');
                        if (titleEl && titleEl.textContent && titleEl.textContent.includes('深度思考')) return true;
                    }
                    // 检查祖先链（思考块可能多层嵌套）
                    let p = el.parentElement;
                    let depth = 0;
                    while (p && depth < 5) {
                        const pcls = (p.className || '').toString().toLowerCase();
                        if (pcls.includes('think') || pcls.includes('reasoning') || 
                            pcls.includes('ds-markdown--block') || pcls.includes('ds-thinking')) return true;
                        // 祖先有 data-card_name="deep_think"
                        const pCardName = p.getAttribute && (p.getAttribute('data-card_name') || p.getAttribute('data-card-name') || '');
                        if (pCardName && pCardName.toLowerCase().includes('think')) return true;
                        p = p.parentElement;
                        depth++;
                    }
                    return false;
                }

                // ---- UI 元素检测 ----
                function isUIElement(el) {
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'button' || tag === 'a' || tag === 'input') return true;
                    const role = el.getAttribute('role');
                    if (role === 'button' || role === 'menuitem' || role === 'link') return true;
                    const cls = (el.className || '').toString().toLowerCase();
                    if (cls.includes('toolbar') || cls.includes('action') || cls.includes('footer-action')) return true;
                    return false;
                }

                // ---- UI 标签黑名单（通义千问等平台的UI元素，非AI回复） ----
                const UI_LABEL_BLOCKLIST = new Set([
                    '录音纪要', '语音输入', '新建对话', '清空对话', '上传文件',
                    '发送消息', '停止生成', '重新生成', '分享对话', '导出对话',
                    '复制', '点赞', '踩', '收藏', '更多', '展开', '收起',
                    '我的空间', '智能体', '对话分组', '新分组', '最近对话',
                    'Qwen9953', '新建聊天', '历史记录', '设置', '帮助',
                    '模型', '温度', '最大长度', '顶部', '停止',
                    '回复', '继续生成', '查看更多', '加载更多',
                    '搜索', '首页', '发现', '消息', '我的', '个人中心',
                    '全部', '未读', '已读', '置顶',
                    '深度思考已完成', '深度思考', '思考已完成',
                    'AI生视频',
                ]);

                // ---- 正则黑名单：匹配"回复1/4"等分段UI标签 ----
                function isUIReplyLabel(el) {
                    const text = (el.innerText || '').trim();
                    // 匹配 "回复N/M" 格式（MiniMax分段回复标签）
                    if (/^回复\d+\/\d+$/.test(text)) return true;
                    // 匹配 "N/M" 纯数字分页
                    if (/^\d+\/\d+$/.test(text)) return true;
                    return false;
                }

                // ---- 检测侧边栏/导航栏内容 ----
                // 如果文本中包含多个UI标签（换行分隔），说明是侧边栏
                function isSidebarContent(el) {
                    const text = (el.innerText || '').trim();
                    if (text.length === 0) return false;
                    const lines = text.split(String.fromCharCode(10)).map(s => s.trim()).filter(s => s.length > 0);
                    if (lines.length < 2) return false;

                    // 检查1：超过一半的行是已知UI标签
                    let labelCount = 0;
                    for (const line of lines) {
                        if (UI_LABEL_BLOCKLIST.has(line)) labelCount++;
                    }
                    if (lines.length >= 3 && labelCount >= lines.length * 0.5) return true;

                    // 检查2：短行模式（侧边栏历史记录特征）
                    // 所有行都很短（<30字），且总内容<200字，很可能是侧边栏
                    if (lines.length >= 3 && text.length < 200) {
                        let shortLineCount = 0;
                        for (const line of lines) {
                            if (line.length <= 30) shortLineCount++;
                        }
                        if (shortLineCount >= lines.length * 0.8) return true;
                    }

                    // 检查3：Kimi侧边栏历史记录特征
                    // 每行都是一个独立的话题标题（无标点、无句子结构）
                    if (lines.length >= 2 && text.length < 300) {
                        let titleLikeCount = 0;
                        for (const line of lines) {
                            // 标题特征：短、无句号/问号/感叹号、无逗号分隔的长句
                            if (line.length <= 50 && !/[。！？.!?,，；;]/.test(line)) {
                                titleLikeCount++;
                            }
                        }
                        if (titleLikeCount >= lines.length * 0.8) return true;
                    }

                    return false;
                }

                // ---- 检测广告/推广内容 ----
                function isAdContent(el) {
                    const text = (el.innerText || '').trim();
                    if (text.length === 0) return false;
                    // 智谱清言广告
                    if (text.includes('GLM-') && text.includes('旗舰模型')) return true;
                    if (text.includes('扫描二维码') && text.includes('体验')) return true;
                    if (text.includes('保存名片') || text.includes('分享智能体')) return true;
                    // 通用广告模式
                    if (text.includes('点击体验') || text.includes('立即下载')) return true;
                    if (text.includes('升级会员') || text.includes('开通会员')) return true;
                    return false;
                }

                // ---- 检测文件附件标签 ----
                // AI回复中可能包含上传文件的附件标签（如"PolySage_技术文档.txt 36KB"）
                // 这些不是AI的实际回复内容
                function isFileAttachment(el) {
                    const text = (el.innerText || '').trim();
                    if (text.length === 0) return false;
                    // 纯文件名+大小标签（如"文件名.txt 36KB"或"文件名.txt" + 换行 + "36KB"）
                    if (/^[\w\u4e00-\u9fff\-_.]+\.(txt|md|csv|pdf|docx?|xlsx?|pptx?|zip|rar)[\s\S]*\d+(KB|MB|GB|B)$/i.test(text)) return true;
                    // 纯文件名（无大小）
                    if (/^[\w\u4e00-\u9fff\-_.]+\.(txt|md|csv|pdf|docx?|xlsx?|pptx?|zip|rar)$/i.test(text) && text.length < 100) return true;
                    // 包含文件大小标签且很短
                    if (/\d+(KB|MB|GB)\s*$/i.test(text) && text.length < 50) return true;
                    return false;
                }

                // ---- Kimi 等平台的占位符/提示词黑名单 ----
                // 这些是输入框占位符、模型选择器文字等，不是AI回复
                const PLACEHOLDER_TEXTS = [
                    '问点难的，让我多想一步',
                    '输入 "/" 唤起插件和技能',
                    'K2.6 思考',
                    'K2.6 快速',
                    'K1.5 思考',
                    'K1.5 快速',
                    '高峰时段算力不足',
                    '升级会员畅用思考模型',
                    '已切换至',
                    '算力不足',
                    '深度思考已完成',
                    '深度思考',
                    '思考已完成',
                ];
                function isPlaceholderText(el) {
                    const text = (el.innerText || '').trim();
                    for (const p of PLACEHOLDER_TEXTS) {
                        // 完全匹配或文本就是占位符本身
                        if (text === p) return true;
                        // 文本以占位符开头且很短（模型选择器可能带箭头图标文字）
                        if (text.length < 30 && text.startsWith(p)) return true;
                    }
                    return false;
                }
                function isUILabel(el) {
                    const text = (el.innerText || '').trim();
                    // 短文本（<=10字）且完全匹配黑名单 → 是UI标签
                    if (text.length <= 10 && UI_LABEL_BLOCKLIST.has(text)) return true;
                    return false;
                }

                // ---- 初始化提示检测（排除开场白/系统提示词容器） ----
                function isInitPrompt(el, markers) {
                    if (!markers || markers.length === 0) return false;
                    const text = (el.innerText || '').trim();
                    if (text.length < 20) return false;
                    // 匹配任意一个特征词即可判定为初始化提示
                    for (const m of markers) {
                        if (m && text.includes(m)) return true;
                    }
                    return false;
                }

                // ---- 工具发送的消息检测 ----
                // sentMessage 是工具发送的原始消息，排除与其内容匹配的区块
                function isSentMessage(el, sentMsg) {
                    if (!sentMsg) return false;
                    const text = (el.innerText || '').trim();
                    // 完全匹配
                    if (text === sentMsg.trim()) return true;
                    // 发送消息是区块内容的一部分（工具消息可能被拆分成多段）
                    if (text.length > 0 && sentMsg.trim().includes(text) && text.length > sentMsg.length * 0.5) return true;
                    // 区块内容是发送消息的一部分
                    if (text.length > 0 && text.includes(sentMsg.trim()) && text.length < sentMsg.length * 1.5) return true;
                    return false;
                }

                // ---- 检测发送的prompt区块（含轮次标题的模式）----
                // 工具发送的prompt以"【第N轮 - 军师发言】"或"【第N轮 - 谋士发言】"开头
                // AI回复不会以这种格式开头（AI回复前缀是"[第N轮]"由工具添加）
                function isSentPromptBlock(el) {
                    const text = (el.innerText || '').trim();
                    if (text.length === 0) return false;
                    // 匹配"【第N轮 - 军师/谋士发言】"开头
                    if (/^【第\d+轮\s*-\s*(军师|谋士)发言】/.test(text.substring(0, 30))) return true;
                    // 匹配"【讨论话题】"开头（第一轮prompt）
                    if (text.startsWith('【讨论话题】')) return true;
                    // 匹配"【主公追问】"开头
                    if (text.startsWith('【主公追问】')) return true;
                    // 匹配"【上一轮"开头
                    if (text.startsWith('【上一轮')) return true;
                    // 匹配"【军师"开头（谋士prompt中的军师发言段）
                    if (text.startsWith('【军师') && text.length < 200) return true;
                    // 匹配"【第N轮 - 军师发言】"在内容前30字
                    if (/【第\d+轮\s*-\s*(军师|谋士)发言】/.test(text.substring(0, 50))) return true;
                    return false;
                }

                // ---- 用户消息检测（通过DOM属性区分用户消息和AI回复） ----
                function isUserMessage(el) {
                    // 检查元素自身及祖先是否有用户角色标识
                    const userPatterns = ['user', 'me', 'human', 'question', 'prompt'];
                    // 检查 data-role 属性
                    const dataRole = el.getAttribute('data-role') || '';
                    if (dataRole === 'user') return true;
                    // 检查 class 属性
                    const className = el.className || '';
                    if (typeof className === 'string') {
                        for (const p of userPatterns) {
                            if (className.toLowerCase().includes(p) && !className.toLowerCase().includes('assistant')) return true;
                        }
                    }
                    // 检查父元素（最多向上3层）
                    let parent = el.parentElement;
                    for (let i = 0; i < 3 && parent; i++) {
                        const pClass = parent.className || '';
                        const pRole = parent.getAttribute('data-role') || '';
                        if (pRole === 'user') return true;
                        if (typeof pClass === 'string') {
                            for (const p of userPatterns) {
                                if (pClass.toLowerCase().includes(p) && !pClass.toLowerCase().includes('assistant')) return true;
                            }
                        }
                        parent = parent.parentElement;
                    }
                    return false;
                }

                // ---- 查找回复区块 ----
                const containerSelectors = [
                    '.ds-markdown--content',
                    'div[class*="message-content"]:not([class*="think"])',
                    'div[class*="markdown-body"]:not([class*="think"])',
                    'div[class*="message__content"]',
                    'div[class*="answer-content"]',
                    'div[class*="reply-content"]',
                    'div[class*="bubble"]:not([class*="input"]):not([class*="toolbar"])',
                    'div[data-role="assistant"]',
                    'article',
                ];

                let containers = [];
                for (const sel of containerSelectors) {
                    const found = document.querySelectorAll(sel);
                    for (const el of found) {
                        if (el.closest('textarea, input, button, [class*="search"], [class*="input-area"], [class*="chat-editor"], [class*="chat-input"], [class*="model-name"], [class*="current-model"], [class*="send-button"], [class*="chat-editor-action"], [class*="left-area"], [class*="right-area"], [class*="sidebar"], [class*="nav"], [class*="menu"], [class*="history"], [class*="conversation-list"], nav, aside')) continue;
                        if (isThinkingElement(el)) continue;
                        if (isUIElement(el)) continue;
                        if (isUILabel(el)) continue;
                        if (isUIReplyLabel(el)) continue;
                        if (isPlaceholderText(el)) continue;
                        if (isSidebarContent(el)) continue;
                        if (isAdContent(el)) continue;
                        if (isFileAttachment(el)) continue;
                        if (isUserMessage(el)) continue;
                        if (isSentPromptBlock(el)) continue;
                        if (isInitPrompt(el, initMarkers)) continue;
                        // 排除工具发送的消息
                        if (isSentMessage(el, sentMessage)) continue;
                        const text = (el.innerText || '').trim();
                        if (text.length < 2) continue;
                        containers.push(el);
                    }
                }

                // 去重：移除被其他容器包含的子元素
                let uniqueContainers = [];
                for (const el of containers) {
                    let isChild = false;
                    for (const other of containers) {
                        if (other !== el && other.contains(el)) {
                            isChild = true;
                            break;
                        }
                    }
                    if (!isChild) {
                        uniqueContainers.push(el);
                    }
                }

                // 按页面位置排序
                uniqueContainers.sort((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    return ra.top - rb.top;
                });

                // 如果传入了 replyCountBefore，只取新回复
                if (replyCountBefore >= 0 && uniqueContainers.length > replyCountBefore) {
                    const newContainers = uniqueContainers.slice(replyCountBefore);
                    // 只有一个新容器，直接用
                    if (newContainers.length === 1) {
                        return (newContainers[0].innerText || '').trim();
                    }
                    // 多个新容器：优先选最后一个（通常是正文，而非思考块）
                    // 因为思考块在DOM中通常出现在正文之前
                    // 只有当最后一个太短(<50字)时才回退到选最长
                    let bestEl = newContainers[newContainers.length - 1];
                    let bestLen = (bestEl.innerText || '').trim().length;
                    if (bestLen < 50) {
                        // 最后一个太短，可能选到UI元素，回退到选最长
                        for (const el of newContainers) {
                            const t = (el.innerText || '').trim().length;
                            if (t > bestLen) {
                                bestEl = el;
                                bestLen = t;
                            }
                        }
                    }
                    return (bestEl.innerText || '').trim();
                }

                // 回退：优先取最后一个（正文在思考之后）
                if (uniqueContainers.length > 0) {
                    if (uniqueContainers.length === 1) {
                        return (uniqueContainers[0].innerText || '').trim();
                    }
                    // 优先取最后一个，太短才回退到最长
                    let bestEl = uniqueContainers[uniqueContainers.length - 1];
                    let bestLen = (bestEl.innerText || '').trim().length;
                    if (bestLen < 50) {
                        for (const el of uniqueContainers) {
                            const t = (el.innerText || '').trim().length;
                            if (t > bestLen) {
                                bestEl = el;
                                bestLen = t;
                            }
                        }
                    }
                    return (bestEl.innerText || '').trim();
                }

                // 更宽泛的回退（也排除发送消息和UI标签）
                const fallbackSelectors = [
                    '[class*="content"]:not([class*="input"]):not([class*="search"]):not([class*="think"])',
                    '[class*="message"]:not([class*="input"])',
                ];
                let fallbackCandidates = [];
                for (const sel of fallbackSelectors) {
                    const found = document.querySelectorAll(sel);
                    for (let i = found.length - 1; i >= 0; i--) {
                        const el = found[i];
                        if (el.closest('textarea, input, button, [class*="search"], [class*="input-area"]')) continue;
                        if (isThinkingElement(el)) continue;
                        if (isUIElement(el)) continue;
                        if (isUILabel(el)) continue;
                        if (isSidebarContent(el)) continue;
                        if (isAdContent(el)) continue;
                        if (isFileAttachment(el)) continue;
                        if (isInitPrompt(el, initMarkers)) continue;
                        if (isSentMessage(el, sentMessage)) continue;
                        if (isSentPromptBlock(el)) continue;
                        if (isUserMessage(el)) continue;
                        const text = (el.innerText || '').trim();
                        if (text.length > 0) fallbackCandidates.push(el);
                    }
                }
                // 回退也优先选最长的
                if (fallbackCandidates.length > 0) {
                    let bestEl = fallbackCandidates[0];
                    let bestLen = (bestEl.innerText || '').trim().length;
                    for (const el of fallbackCandidates) {
                        const t = (el.innerText || '').trim().length;
                        if (t > bestLen) {
                            bestEl = el;
                            bestLen = t;
                        }
                    }
                    return (bestEl.innerText || '').trim();
                }

                return '';
            }""", {"replyCountBefore": reply_count_before, "sentMessage": sent_message, "initMarkers": init_markers})

            text = clean_text(text)
            if text and len(text) >= 20:
                log_info(f"{prefix}JS 智能提取成功（长度 {len(text)}）: {text[:100]}...")
                return text
            elif text and len(text) >= 1:
                log_warning(f"{prefix}JS 智能提取结果过短（{len(text)}字: {text[:50]}），尝试其他策略")
                # 不返回，继续尝试配置选择器
            else:
                log_warning(f"{prefix}JS 智能提取结果为空")
        except Exception as e:
            log_warning(f"{prefix}JS 智能提取失败: {e}")

        # 备选策略1：配置的选择器
        if selector:
            log_info(f"{prefix}尝试配置的回复选择器: {selector}")
            try:
                elements = await page.query_selector_all(selector)
                # 第一轮：从后往前找第一个可见且有内容的元素
                best_text = ""
                best_len = 0
                all_visible_texts = []
                for el in reversed(elements):
                    try:
                        if await el.is_visible():
                            text = await el.inner_text()
                            text = clean_text(text)
                            if text and len(text) >= 1 and not self._is_thinking_content(text):
                                if len(text) > best_len:
                                    best_text = text
                                    best_len = len(text)
                                all_visible_texts.append(text)
                    except Exception:
                        continue

                if best_text:
                    # 如果最佳结果较短，尝试拼接所有匹配元素
                    if best_len < 200 and len(all_visible_texts) > 1:
                        combined = "\n\n".join(reversed(all_visible_texts))
                        combined = clean_text(combined)
                        if len(combined) > best_len:
                            log_info(f"{prefix}配置选择器拼接{len(all_visible_texts)}个元素成功: {len(combined)}字")
                            return combined
                    log_info(f"{prefix}配置选择器提取成功: {best_text[:80]}...")
                    return best_text
            except Exception as e:
                log_warning(f"{prefix}配置选择器提取失败: {e}")

            # 备选策略1b：去掉 :last-of-type 后缀，获取所有匹配元素拼接
            if ":last-of-type" in selector:
                broad_selector = selector.replace(":last-of-type", "")
                try:
                    elements = await page.query_selector_all(broad_selector)
                    if elements:
                        all_texts = []
                        for el in elements:
                            try:
                                if await el.is_visible():
                                    text = await el.inner_text()
                                    text = clean_text(text)
                                    if text and len(text) >= 5 and not self._is_thinking_content(text):
                                        all_texts.append(text)
                            except Exception:
                                continue
                        if all_texts:
                            combined = "\n\n".join(all_texts)
                            combined = clean_text(combined)
                            if len(combined) > 50:
                                log_info(f"{prefix}宽选择器拼接{len(all_texts)}个元素成功: {len(combined)}字")
                                return combined
                except Exception as e:
                    log_warning(f"{prefix}宽选择器提取失败: {e}")

        # 备选策略2：通用 DOM 提取
        log_info(f"{prefix}尝试通用 DOM 提取")
        text = await self._extract_generic_response(page, ai_name)
        if text and len(text) >= 1 and not self._is_thinking_content(text):
            log_info(f"{prefix}通用提取成功: {text[:80]}...")
            return text

        log_error(f"{prefix}所有提取策略均失败，返回空字符串")
        return ""

    @staticmethod
    def _is_thinking_content(text: str) -> bool:
        """判断文本是否为 AI 的思考过程（而非最终回复）。"""
        if not text:
            return False
        thinking_keywords = [
            '分析输入', '构思回复', '起草回复', '对照约束',
            '思考过程', '深度思考', '最终润色',
            'Thought', 'Analysis', 'Reasoning',
            # 智谱清言/通义千问等AI的思考格式
            'Role:', 'Goal:', 'Strategy:', 'Current State:',
            'Drafting the Response', 'Key Points to Make',
            'Response Structure', 'Summary of Conflict',
            'Analysis of Disagreements', 'Phase 1:', 'Phase 2:',
            'Action:', 'Direct the next round',
            # 扩充：通义千问/其他AI的思考格式
            'The user', 'The project', 'The lord', 'I need to',
            'This is', 'Let me', 'I should', 'I will',
            '【思考】', '【分析】', '【推理】',
            '已深度思考', 'Thought for', '思考完成',
            'Step 1:', 'Step 2:', 'Step 3:',
            'First,', 'Second,', 'Third,',
            'Now I', 'Based on', 'Looking at',
        ]
        # 强信号关键词：单独出现即可判定
        strong_signals = [
            'Role:', 'Goal:', 'Strategy:', 'Current State:',
            'Drafting the Response', 'Key Points to Make',
            '分析输入', '构思回复', '起草回复',
            '已深度思考', 'Thought for', '思考完成',
            '【思考】', '【分析】', '【推理】',
        ]
        # 检查文本前几行是否包含思考关键词
        first_lines = text.strip().split('\n')[:12]
        keyword_count = 0
        for line in first_lines:
            for kw in thinking_keywords:
                if kw in line:
                    keyword_count += 1
                    break
        # 强信号：前12行中任意1行命中即判定
        for line in first_lines:
            for kw in strong_signals:
                if kw in line:
                    return True
        # 普通信号：前12行中有2行以上包含思考关键词（从3降低到2）
        return keyword_count >= 2

    @staticmethod
    def _strip_thinking_content(text: str, ai_name: str = "") -> str:
        """
        后处理：从提取的文本中移除残留的思考过程内容。

        策略：
        1. 如果整段文本都是思考过程，尝试找到实际回复部分
        2. 移除以思考关键词开头的段落
        3. 移除 *分析输入：* / *构思回复：* 等标记段落
        """
        if not text:
            return text

        prefix = f"[{ai_name}] " if ai_name else ""

        # 先用快速检测：如果文本不是思考内容，直接返回
        if not ChromeManager._is_thinking_content(text):
            # 仍然过滤 UI 元素文字
            return ChromeManager._strip_ui_elements(text, ai_name)

        # 文本被判定为思考内容，尝试找到实际回复部分
        lines = text.split('\n')

        # 策略1: 查找中文方括号【开头的行（通常是正式回复的标题）
        reply_start_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('【') and len(stripped) > 5:
                reply_start_idx = i
                break

        # 策略2: 如果没找到【, 查找最后一个"一、二、三、"等中文序号开头
        if reply_start_idx == -1:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('一、') or stripped.startswith('二、') or stripped.startswith('三、'):
                    reply_start_idx = i
                    break

        # 策略3: 如果没找到，查找以AI名称开头的正式回复行
        if reply_start_idx == -1 and ai_name:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f'{ai_name}：') or stripped.startswith(f'{ai_name}:') or stripped.startswith(f'【{ai_name}'):
                    reply_start_idx = i
                    break

        # 策略4: 查找 "各位" 开头的行（军师常用开场白）
        if reply_start_idx == -1:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('各位谋士') or stripped.startswith('各位同僚') or stripped.startswith('主公'):
                    reply_start_idx = i
                    break

        if reply_start_idx >= 0:
            result = '\n'.join(lines[reply_start_idx:]).strip()
            log_info(f"{prefix}后处理：检测到思考内容，从第{reply_start_idx+1}行截取实际回复，从 {len(text)} 字符中提取 {len(result)} 字符")
            return ChromeManager._strip_ui_elements(result, ai_name)

        # 策略5: 无法找到明确的回复起始点，使用原有的行级过滤
        thinking_markers = [
            '分析输入', '构思回复', '起草回复', '对照约束',
            '思考过程', '深度思考', '最终润色',
            '*分析输入', '*构思回复', '*起草回复', '*对照约束',
            'Thought', 'Analysis', 'Reasoning',
            'Role:', 'Goal:', 'Strategy:', 'Current State:',
            'Drafting the Response', 'Key Points to Make',
            'Response Structure', 'Summary of Conflict',
            'Analysis of Disagreements', 'Phase 1:', 'Phase 2:',
            'Phase 3:', 'Phase 4:', 'Action:',
            'Direct the next round', 'Focus for next round',
        ]

        cleaned_lines = []
        in_thinking_block = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            is_thinking_line = False
            for marker in thinking_markers:
                if stripped.startswith(marker) or stripped.startswith(f'*{marker}'):
                    is_thinking_line = True
                    break

            if is_thinking_line:
                in_thinking_block = True
                continue

            if in_thinking_block:
                if not stripped:
                    in_thinking_block = False
                elif stripped.startswith('*') or stripped.startswith('-') or stripped.startswith('•'):
                    continue
                else:
                    in_thinking_block = False
                    cleaned_lines.append(line)
            else:
                cleaned_lines.append(line)

        result = '\n'.join(cleaned_lines).strip()

        if len(result) < 20 and len(text) > 100:
            for i in range(len(lines) - 1, -1, -1):
                stripped = lines[i].strip()
                if stripped and not any(stripped.startswith(m) for m in thinking_markers):
                    reply_start = i
                    for j in range(i - 1, -1, -1):
                        jstripped = lines[j].strip()
                        if any(jstripped.startswith(m) for m in thinking_markers):
                            break
                        reply_start = j
                    result = '\n'.join(lines[reply_start:]).strip()
                    break

        if result != text:
            log_info(f"{prefix}后处理：从 {len(text)} 字符中过滤思考内容，剩余 {len(result)} 字符")

        return ChromeManager._strip_ui_elements(result, ai_name)

    @staticmethod
    def _strip_ui_elements(text: str, ai_name: str = "") -> str:
        """过滤网页 UI 元素文字。"""
        if not text:
            return text

        # 过滤网页 UI 元素文字
        ui_keywords = [
            'AI编辑', '收藏至知识库', '收藏', '编辑', '复制', '分享',
            '点赞', '重新生成', '停止生成', '继续生成',
            'Copy', 'Edit', 'Share', 'Regenerate',
        ]
        lines = text.split('\n')
        cleaned = [line for line in lines if not any(kw in line.strip() for kw in ui_keywords) or len(line.strip()) > 30]
        result = '\n'.join(cleaned).strip()

        return result if result else text

    async def _extract_generic_response(self, page: Page, ai_name: str = "") -> str:
        """通用回复提取：使用多种选择器获取最后一条 AI 回复（过滤思考过程）。"""
        prefix = f"[{ai_name}] " if ai_name else ""

        # 多种选择器尝试
        extract_selectors = [
            # DeepSeek 风格（排除 thinking block）
            "div[class*='message-content']:not([class*='think'])",
            "div.ds-markdown:not(.ds-markdown--block)",
            "div[class*='markdown-body']:not([class*='think'])",
            # 智谱清言 风格
            "div[class*='answer']:not([class*='think'])",
            "div[class*='reply-content']:not([class*='think'])",
            # 通用
            "div[data-role='assistant']:not([class*='think'])",
            "article:not([class*='think'])",
        ]

        for sel in extract_selectors:
            try:
                elements = await page.query_selector_all(sel)
                # 从后往前找第一个非思考内容
                for el in reversed(elements):
                    try:
                        text = await el.inner_text()
                        text = clean_text(text)
                        if text and len(text) >= 1 and not self._is_thinking_content(text):
                            log_info(f"{prefix}选择器 '{sel}' 提取成功: {text[:80]}...")
                            return text
                    except Exception:
                        continue
            except Exception:
                continue

        # 最终回退：JS 获取所有文本容器的最后一条（过滤思考）
        try:
            text = await page.evaluate("""() => {
                const THINKING_KEYWORDS = [
                    '分析输入', '构思回复', '起草回复', '对照约束',
                    '思考过程', '深度思考', '最终润色',
                ];
                const elements = document.querySelectorAll(
                    '[class*="message"], [class*="markdown"], [data-role="assistant"], article, ' +
                    '[class*="answer"], [class*="response"], [class*="reply"]'
                );
                // 从后往前找第一个非思考内容
                for (let i = elements.length - 1; i >= 0; i--) {
                    const el = elements[i];
                    const cls = (el.className || '').toString().toLowerCase();
                    if (cls.includes('think') || cls.includes('reasoning')) continue;
                    const text = el.innerText.trim();
                    if (text.length < 1) continue;
                    let kwCount = 0;
                    for (const kw of THINKING_KEYWORDS) {
                        if (text.includes(kw)) kwCount++;
                    }
                    if (kwCount >= 2) continue;
                    return text;
                }
                return '';
            }""")
            return clean_text(text)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # 登录检测
    # ------------------------------------------------------------------

    async def check_login_status(self, page: Page, ai_config: dict) -> tuple:
        """
        多方法组合登录检测（严格模式：必须同时满足输入框可用 + 登录指示器存在）。

        检测策略（按优先级）：
        1. URL 包含 login/auth → 未登录
        2. 存在"登录"按钮 → 未登录
        3. 输入框可用 + 登录指示器存在 → 已登录（严格确认）
        4. 输入框可用但无登录指示器 → 未登录（可能处于游客模式）
        5. 输入框不存在 → 未登录
        6. 以上均无法判定 → 未知

        Args:
            page: Playwright Page
            ai_config: AI 平台配置

        Returns:
            tuple: (status: str, message: str)
            status ∈ {"logged_in", "not_logged_in", "unknown"}
        """
        selectors = ai_config.get("selectors", {})

        try:
            current_url = page.url
        except Exception:
            current_url = ""

        # 1. URL 检测（瞬时）
        if any(kw in current_url.lower() for kw in [
            "login", "auth", "signin", "sign-in", "sign_in", "signup", "sign-up", "sign_up"
        ]):
            return "not_logged_in", f"当前页面为登录页({current_url})，请先登录。"

        # 2. 优先检测输入框（已登录的最快路径，3s）
        input_selector = selectors.get("input_textarea", "textarea")
        input_el = await self._try_locate(page, input_selector, state="visible", timeout=3000)
        input_ok = False
        if input_el is not None:
            try:
                is_enabled = await input_el.is_enabled()
                if is_enabled:
                    input_ok = True
                else:
                    return "not_logged_in", "输入框存在但不可用，可能需要登录。"
            except Exception:
                pass
        else:
            # 输入框不存在 → 检测是否有登录按钮
            login_btn_selector = selectors.get("login_button", "button:has-text('登录')")
            login_btn = await self._try_locate(page, login_btn_selector, state="visible", timeout=500)
            if login_btn is not None:
                return "not_logged_in", "检测到登录按钮，请先登录。"
            return "not_logged_in", "未找到对话输入框，可能未登录或页面未加载完成。"

        # 3. 严格登录确认：检查登录指示器（用户头像等）
        # 只有登录指示器存在才确认已登录，避免游客模式误判
        login_indicator = selectors.get("login_indicator", "")
        if login_indicator:
            indicator_el = await self._try_locate(page, login_indicator, state="attached", timeout=1500)
            if indicator_el is not None:
                return "logged_in", "已登录（输入框可用+登录指示器存在）"
            # 登录指示器未找到，但二次确认：确保没有登录按钮
            login_btn_selector = selectors.get("login_button", "button:has-text('登录')")
            login_btn = await self._try_locate(page, login_btn_selector, state="visible", timeout=500)
            if login_btn is not None:
                return "not_logged_in", "检测到登录按钮，请先登录。"
            # 输入框可用且无登录按钮 → 推测已登录（选择器可能过时）
            if input_ok:
                return "logged_in", "输入框可用且无登录按钮，推测已登录。"
        else:
            # 未配置登录指示器 → 仅凭输入框可用判断（兼容旧配置）
            if input_ok:
                return "logged_in", "输入框可用，推测已登录。"

        return "unknown", "无法确定登录状态，请手动确认。"

    async def ensure_thinking_mode(self, page: Page, ai_config: dict) -> tuple:
        """
        检测并开启 AI 平台的思考/深度思考模式（基于配置）。

        支持两种开关类型（由配置 thinking_mode.type 决定）：
        - toggle: 按钮式开关，通过 active_attr/active_value 判断是否已激活
        - dropdown: 下拉菜单式，通过 label_selector 读取标签判断，点击 option_selector 选择

        配置字段（thinking_mode）：
        - enabled: 是否启用
        - type: "toggle" 或 "dropdown"
        - selector: 开关/触发器的 CSS 选择器
        - label_selector: (dropdown) 标签元素的选择器
        - label_text: 激活状态的标签文本关键词
        - option_selector: (dropdown) 选项元素的选择器
        - option_text: (dropdown) 要点击的选项文本
        - active_attr: (toggle) 激活状态属性名（如 aria-pressed）
        - active_value: (toggle) 激活状态的属性值（如 true）

        Args:
            page: Playwright Page
            ai_config: AI 平台配置

        Returns:
            tuple: (success: bool, message: str)
        """
        ai_name = ai_config.get("name", "未知")
        tm = ai_config.get("thinking_mode", {})

        # 未配置思考模式或未启用 → 跳过
        if not tm or not tm.get("enabled", False):
            return True, "无需思考模式"

        # 缓存命中：已确认无需再检测
        if self._thinking_mode_cache.get(ai_name):
            return True, "已就绪"

        # 操作锁
        if ai_name in self._thinking_in_progress:
            return False, "正在操作中"
        self._thinking_in_progress.add(ai_name)

        try:
            # 等待页面 DOM 稳定
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=1500)
            except Exception:
                pass
            await page.wait_for_timeout(500)

            tm_type = tm.get("type", "toggle")
            selector = tm.get("selector", "")
            label_text = tm.get("label_text", "")

            if tm_type == "dropdown":
                # 下拉菜单式
                label_selector = tm.get("label_selector", "")
                option_selector = tm.get("option_selector", "")
                option_text = tm.get("option_text", "")

                result = await page.evaluate("""
                    async (config) => {
                        let trigger = null;
                        try { trigger = document.querySelector(config.selector); } catch(e) {}
                        if (!trigger) return {found: false};

                        let labelEl = null;
                        if (config.label_selector) {
                            try { labelEl = document.querySelector(config.label_selector); } catch(e) {}
                        }
                        const label = labelEl ? labelEl.textContent.trim() : '';

                        if (label.includes(config.label_text))
                            return {found: true, active: true, label: label};
                        if (!label)
                            return {found: false, msg: '标签为空，页面未加载完'};

                        // 点击触发器打开下拉
                        trigger.click();
                        await new Promise(r => setTimeout(r, 1000));

                        // 查找选项
                        let clicked = false;
                        if (config.option_selector && config.option_text) {
                            const opts = document.querySelectorAll(config.option_selector);
                            for (const opt of opts) {
                                if (opt.textContent.trim().includes(config.option_text)) {
                                    let target = opt.parentElement;
                                    for (let i = 0; i < 4; i++) {
                                        if (!target) break;
                                        const cls = (target.className || '');
                                        if (cls.includes('item') || cls.includes('mode')) {
                                            target.click();
                                            clicked = true;
                                            break;
                                        }
                                        target = target.parentElement;
                                    }
                                    if (!clicked && opt.parentElement) {
                                        opt.parentElement.click();
                                        clicked = true;
                                    }
                                    break;
                                }
                            }
                        }

                        if (!clicked) {
                            trigger.click();
                            return {found: true, active: false, label: label, msg: '未找到选项'};
                        }

                        await new Promise(r => setTimeout(r, 800));
                        const newLabelEl = config.label_selector ?
                            document.querySelector(config.label_selector) : null;
                        const newLabel = newLabelEl ? newLabelEl.textContent.trim() : '';
                        return {found: true, active: newLabel.includes(config.label_text),
                                label: newLabel, msg: '切换后: ' + newLabel};
                    }
                """, {"selector": selector, "label_selector": label_selector,
                      "label_text": label_text, "option_selector": option_selector,
                      "option_text": option_text})

            else:
                # toggle 按钮式
                active_attr = tm.get("active_attr", "aria-pressed")
                active_value = tm.get("active_value", "true")

                result = await page.evaluate("""
                    async (config) => {
                        let toggle = null;
                        // 主选择器：try-catch 防止 :has-text() 等非标准CSS导致报错
                        try {
                            toggle = document.querySelector(config.selector);
                        } catch(e) {
                            // 选择器含 Playwright 伪选择器，跳过，走备选逻辑
                        }

                        // 备选1：通过 aria-label 查找
                        if (!toggle && config.label_text) {
                            const buttons = document.querySelectorAll('button, div[role="button"]');
                            for (const btn of buttons) {
                                const ariaLabel = btn.getAttribute('aria-label') || '';
                                if (ariaLabel === config.label_text) {
                                    toggle = btn;
                                    break;
                                }
                            }
                        }

                        // 备选2：搜索含 label_text 文本的元素
                        if (!toggle && config.label_text) {
                            const allDivs = document.querySelectorAll('div, button, span');
                            for (const el of allDivs) {
                                const text = (el.textContent || '').trim();
                                if (text === config.label_text || text === config.label_text + '(R1)') {
                                    let node = el;
                                    for (let i = 0; i < 5; i++) {
                                        if (!node) break;
                                        const cls = (node.className || '').toString();
                                        if (cls.includes('toggle') || cls.includes('button') ||
                                            node.tagName === 'BUTTON' ||
                                            node.getAttribute('role') === 'button' ||
                                            node.hasAttribute(config.active_attr)) {
                                            toggle = node;
                                            break;
                                        }
                                        node = node.parentElement;
                                    }
                                    if (toggle) break;
                                }
                            }
                        }

                        if (!toggle) return {found: false};

                        const attrVal = toggle.getAttribute(config.active_attr);
                        const isActive = attrVal === config.active_value;

                        if (isActive) return {found: true, active: true, text: config.label_text};

                        toggle.click();
                        await new Promise(r => setTimeout(r, 800));

                        const newVal = toggle.getAttribute(config.active_attr);
                        return {found: true, active: newVal === config.active_value,
                                text: config.label_text, clicked: true};
                    }
                """, {"selector": selector, "label_text": label_text,
                      "active_attr": active_attr, "active_value": active_value})

            if result and result.get("found"):
                if result.get("active"):
                    log_info(f"[{ai_name}] 思考模式已开启（{result.get('label', result.get('text', ''))}）")
                    self._thinking_mode_cache[ai_name] = True
                    self._thinking_fail_count.pop(ai_name, None)
                    return True, "已就绪"
                else:
                    msg = result.get("msg", result.get("label", result.get("text", "")))
                    log_warning(f"[{ai_name}] 思考模式切换失败: {msg}")
                    self._thinking_fail_count[ai_name] = self._thinking_fail_count.get(ai_name, 0) + 1
                    if self._thinking_fail_count[ai_name] >= 3:
                        log_warning(f"[{ai_name}] 思考模式切换失败3次，停止重试")
                        self._thinking_mode_cache[ai_name] = True
                        return True, "已就绪（跳过思考模式）"
                    return False, f"切换失败: {msg}"

            # 未找到开关
            self._thinking_fail_count[ai_name] = self._thinking_fail_count.get(ai_name, 0) + 1
            if self._thinking_fail_count[ai_name] >= 1:
                log_info(f"[{ai_name}] 未找到思考模式按钮，跳过（页面上可能无此按钮）")
                self._thinking_mode_cache[ai_name] = True
                return True, "已就绪"
            log_info(f"[{ai_name}] 未找到思考模式按钮(第{self._thinking_fail_count[ai_name]}次)，稍后重试")
            return False, "页面加载中"

        except Exception as e:
            log_warning(f"[{ai_name}] 思考模式检测失败: {e}")
            return False, f"思考模式检测失败: {e}"
        finally:
            self._thinking_in_progress.discard(ai_name)

    # ------------------------------------------------------------------
    # 元素定位辅助
    # ------------------------------------------------------------------

    @staticmethod
    async def _try_locate(page: Page, selector: str, state: str = "visible",
                          timeout: int = 5000):
        """
        尝试定位元素，支持多种选择器语法。

        优先尝试 Playwright 的 wait_for_selector（支持 CSS、:has-text 等）。
        失败后尝试 XPath（以 // 或 xpath= 开头时）。
        失败返回 None（不抛异常）。
        """
        if not selector:
            return None

        # XPath 支持
        if selector.startswith("//") or selector.startswith("xpath="):
            xpath = selector.replace("xpath=", "", 1)
            try:
                el = await page.wait_for_selector(f"xpath={xpath}", state=state, timeout=timeout)
                return el
            except Exception:
                return None

        # CSS / Playwright 伪选择器
        try:
            el = await page.wait_for_selector(selector, state=state, timeout=timeout)
            return el
        except Exception:
            pass

        # 备选：get_by_role 尝试（从 :has-text 提取文本）
        try:
            if ":has-text(" in selector:
                import re
                match = re.search(r":has-text\(['\"](.+?)['\"]\)", selector)
                if match:
                    text = match.group(1)
                    tag = re.match(r"(\w+)", selector)
                    role_map = {"button": "button", "a": "link", "input": "textbox"}
                    if tag:
                        role = role_map.get(tag.group(1).lower())
                        if role:
                            el = await page.get_by_role(role, name=text).first
                            try:
                                await el.wait_for(state=state, timeout=timeout)
                                return el
                            except Exception:
                                pass
        except Exception:
            pass

        return None
