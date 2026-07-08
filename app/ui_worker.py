"""WorkerThread + AIWorker: 三级线程架构。

架构：
  1级 主线程 (Qt UI): 只收信号、发命令、更新UI
  2级 WorkerThread (大脑): 独立 asyncio 事件循环，接收主线程命令，调度各 AIWorker
  3级 AIWorker (每个AI一个 asyncio Task): 只关注自己的AI页面，执行大脑分派的任务

关键设计：
  - Chrome 启动前：不创建任何 AIWorker，大脑空闲
  - Chrome 启动后：为每个中军帐AI创建 AIWorker，开始持续监控
  - AI 进出中军帐：动态创建/销毁 AIWorker
  - 讨论时：大脑通过 queue 向 AIWorker 发命令，AIWorker 执行完报告大脑
"""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from browser import ChromeManager
from core import HostedMode
from logger import log_info, log_error, log_warning, log_exception


# ======================================================================
# 3级：AIWorker — 每个AI一个，只关注自己的页面
# ======================================================================

class AIWorker:
    """单个 AI 的工作协程：监控状态 + 执行大脑分派的任务。

    生命周期：
      创建 → 打开页面 → 持续监控(登录+思考模式) → 讨论时接收命令执行 → 销毁
    """

    def __init__(self, ai_config: dict, chrome_mgr: ChromeManager,
                 brain_queue: asyncio.Queue):
        self.name = ai_config.get("name", "")
        self.config = ai_config
        self.chrome_mgr = chrome_mgr
        self.brain_queue = brain_queue  # 报告大脑的队列
        self.task_queue = asyncio.Queue()  # 接收大脑命令的队列
        self.page = None
        self._running = True
        self._monitoring = True  # 是否在监控状态
        self._task = None
        self._last_status = None  # 上次状态：green/orange/None
        self._discussion_active = False  # 是否正在讨论中

    async def run(self):
        """AIWorker 主循环：打开页面 → 监控状态 → 等待命令。"""
        url = self.config.get("url", "")
        try:
            # 打开页面
            self.page = await asyncio.wait_for(
                self.chrome_mgr.get_or_create_page(url),
                timeout=30
            )
            if not self.page:
                await self.brain_queue.put(("page_failed", self.name, "页面打开失败"))
                return

            await self.brain_queue.put(("page_opened", self.name, ""))
            log_info(f"[AIWorker:{self.name}] 页面已打开")

            # 主循环：监控 + 命令处理
            while self._running:
                # 检查是否有命令（非阻塞）
                try:
                    cmd = self.task_queue.get_nowait()
                    if cmd[0] == "send_message":
                        self._monitoring = False
                        self._discussion_active = True
                        await self._handle_send(cmd)
                        self._monitoring = True
                        # 发送完成后不立即恢复检测，延迟5秒避免页面重渲染导致波动
                        await asyncio.sleep(5)
                        self._discussion_active = False
                    elif cmd[0] == "stop":
                        break
                except asyncio.QueueEmpty:
                    pass

                # 监控状态
                if self._monitoring:
                    await self._check_status()

                await asyncio.sleep(2)

        except Exception as e:
            log_error(f"[AIWorker:{self.name}] 异常: {e}")
            await self.brain_queue.put(("error", self.name, str(e)))
        finally:
            log_info(f"[AIWorker:{self.name}] 已停止")

    async def _check_status(self):
        """统一检测 AI 就绪状态：对话框 + 登录 + 思考模式。

        流程：
        1. check_ai_ready（只读检测三个条件）
        2. 如果橙色且原因是思考模式未开启 → try_enable_thinking_mode（操作）
        3. 操作后重新 detect_thinking_mode 确认
        4. 用户手动开启后，下次检测自动变绿（检测与操作独立）
        """
        # 讨论进行中时，已绿色的AI不再反复检测（防止波动）
        if self._discussion_active and self._last_status == "green":
            return

        # 检查页面是否已失效，尝试重建
        page_invalid = False
        if self.page is None:
            page_invalid = True
        else:
            try:
                _ = self.page.url
            except Exception:
                page_invalid = True

        if page_invalid:
            log_warning(f"[AIWorker:{self.name}] 页面已失效，尝试重建...")
            try:
                self.page = await asyncio.wait_for(
                    self.chrome_mgr.get_or_create_page(self.config.get("url", "")),
                    timeout=30
                )
                if self.page:
                    log_info(f"[AIWorker:{self.name}] 页面重建成功")
                    self.chrome_mgr.clear_thinking_cache(self.name)
                    await asyncio.sleep(3)
                else:
                    self._last_status = "orange"
                    await self.brain_queue.put(("status", self.name, "orange", "页面重建失败"))
                    return
            except Exception as e:
                log_error(f"[AIWorker:{self.name}] 页面重建失败: {e}")
                self._last_status = "orange"
                await self.brain_queue.put(("status", self.name, "orange", f"页面重建失败: {e}"))
                return

        try:
            # 1. 统一检测（只读，不操作）
            status, reason = await asyncio.wait_for(
                self.chrome_mgr.check_ai_ready(self.page, self.config),
                timeout=15
            )

            # 2. 如果橙色且原因是思考模式 → 尝试自动启用
            if status == "orange" and "思考模式" in reason:
                tm = self.config.get("thinking_mode", {})
                if tm.get("enabled", False):
                    # 尝试启用（操作）
                    enable_ok, enable_msg = await asyncio.wait_for(
                        self.chrome_mgr.try_enable_thinking_mode(self.page, self.config),
                        timeout=10
                    )
                    if enable_ok:
                        # 操作后重新检测（确认是否成功）
                        await asyncio.sleep(1)
                        is_active, detect_reason = await asyncio.wait_for(
                            self.chrome_mgr.detect_thinking_mode(self.page, self.config),
                            timeout=8
                        )
                        if is_active:
                            status = "green"
                            reason = "已就绪"
                        else:
                            reason = f"未打开思考模式（自动切换失败，请手动开启）"

            # 3. 报告状态
            self._last_status = status
            await self.brain_queue.put(("status", self.name, status, reason))

        except asyncio.TimeoutError:
            self._last_status = "orange"
            await self.brain_queue.put(("status", self.name, "orange", "检测超时"))
        except Exception as e:
            error_msg = str(e)
            self._last_status = "orange"
            await self.brain_queue.put(("status", self.name, "orange", f"检测异常: {e}"))
            if "closed" in error_msg.lower() or "target" in error_msg.lower():
                self.page = None

    async def _handle_send(self, cmd):
        """处理大脑发来的 send_message 命令。

        职责（3级线程）：
        1. 将消息发送给自己监控的AI
        2. 监控AI是否在发言（吐token）
        3. AI发言完毕后，提取回复内容，传输回大脑
        4. 如果一次没截全，做二次提取，保证无遗漏
        5. 不做任何判断（判断交给大脑）
        """
        _, message, timeout, fast_wait = cmd
        try:
            # 发送前检查页面是否有效，无效则重建
            page_ok = False
            if self.page is not None:
                try:
                    _ = self.page.url
                    page_ok = True
                except Exception:
                    page_ok = False
            if not page_ok:
                log_warning(f"[AIWorker:{self.name}] 发送前页面失效，尝试重建...")
                self.page = await asyncio.wait_for(
                    self.chrome_mgr.get_or_create_page(self.config.get("url", "")),
                    timeout=30
                )
                if self.page:
                    await asyncio.sleep(3)
                    log_info(f"[AIWorker:{self.name}] 页面重建成功，继续发送")
                else:
                    await self.brain_queue.put(("reply_error", self.name, "页面重建失败，无法发送消息"))
                    return

            # 报告大脑：AI即将开始发言
            await self.brain_queue.put(("ai_speaking", self.name, True))

            # 发送消息并等待回复（ChromeManager负责发送+等待+初步提取）
            reply = await self.chrome_mgr.send_and_wait(
                self.page, message, self.config,
                timeout=timeout or 120, fast_wait=fast_wait
            )

            # 二次提取：等待2秒后再次提取，确保AI已完全输出
            # 解决"一次没截全"的问题
            if not fast_wait and reply and len(reply) > 20:
                await asyncio.sleep(2)
                try:
                    reply2 = await self.chrome_mgr._extract_last_response(
                        self.page,
                        self.config.get("selectors", {}).get("last_response", ""),
                        5000,
                        ai_name=self.name
                    )
                    if reply2:
                        from logger import log_info as _log
                        _log(f"[AIWorker:{self.name}] 二次提取: 首次{len(reply)}字, 二次{len(reply2)}字")
                        # 如果二次提取更长，说明首次没截全，用二次的
                        if len(reply2) > len(reply):
                            reply = reply2
                            _log(f"[AIWorker:{self.name}] ✅ 二次提取更完整，使用二次结果")
                        # 如果两者内容差异大，都发给大脑，让大脑判断
                        elif len(reply2) > 20 and reply2 != reply and abs(len(reply2) - len(reply)) > 50:
                            # 发送两次结果，大脑负责统筹
                            await self.brain_queue.put(("reply_fragment", self.name, reply))
                            await self.brain_queue.put(("reply_fragment", self.name, reply2))
                            await self.brain_queue.put(("reply", self.name, reply))
                            await self.brain_queue.put(("ai_speaking", self.name, False))
                            return
                except Exception as e2:
                    log_warning(f"[AIWorker:{self.name}] 二次提取失败: {e2}")

            # 报告大脑：AI发言完毕 + 回复内容
            await self.brain_queue.put(("reply", self.name, reply))
            await self.brain_queue.put(("ai_speaking", self.name, False))

        except Exception as e:
            error_msg = str(e)
            # 如果是页面关闭错误，标记下次需要重建
            if "closed" in error_msg.lower() or "target" in error_msg.lower():
                self.page = None
            await self.brain_queue.put(("reply_error", self.name, error_msg))
            await self.brain_queue.put(("ai_speaking", self.name, False))

    def send_command(self, cmd):
        """大脑调用：向此 AIWorker 投递命令。"""
        self.task_queue.put_nowait(cmd)

    def stop(self):
        """大脑调用：停止此 AIWorker。"""
        self._running = False
        self.send_command(("stop",))


# ======================================================================
# 2级：WorkerThread — 大脑线程
# ======================================================================

class WorkerThread(QThread):
    """大脑线程：独立 asyncio 事件循环，统筹所有 AIWorker。"""

    # ===== 信号（发给主线程） =====
    chrome_result = pyqtSignal(bool, str)
    chrome_started_signal = pyqtSignal()
    chrome_stopped_signal = pyqtSignal()
    page_opened = pyqtSignal(str, bool)
    ai_status = pyqtSignal(str, str, str)
    progress = pyqtSignal(str, str, str)
    discussion_done = pyqtSignal(dict)
    toast = pyqtSignal(str)
    status_msg = pyqtSignal(str, int)
    button_state = pyqtSignal(bool, bool)
    chat_counting = pyqtSignal()
    chips_refresh = pyqtSignal()

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self._loop = None
        self._chrome_mgr = None
        self._running = True
        self._hosted = None
        self._discussion_running = False

        # AIWorker 管理
        self._ai_workers = {}  # {name: AIWorker}
        self._brain_queue = None  # asyncio.Queue，接收 AIWorker 报告
        self._brain_task = None  # 大脑调度协程

    def run(self):
        """工作线程主入口。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._chrome_mgr = ChromeManager(self.config_mgr.config)
        self._brain_queue = asyncio.Queue()

        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            self._loop.close()

    def submit(self, coro):
        """提交协程到工作线程（主线程调用）。"""
        if self._loop and self._loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        return None

    def stop(self):
        """停止工作线程。"""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait(5000)

    @property
    def chrome_mgr(self):
        return self._chrome_mgr

    # ===== Chrome 启动/关闭 =====

    def do_start_chrome(self, active_ais: list):
        """启动 Chrome（主线程调用）。"""
        self.submit(self._start_chrome_async(active_ais))

    async def _start_chrome_async(self, active_ais: list):
        """启动 Chrome，然后为中军帐每个AI创建 AIWorker。"""
        self.button_state.emit(False, False)
        self.status_msg.emit("正在启动 Chrome...", 0)
        self._chrome_mgr.clear_thinking_cache()

        try:
            success, msg = await self._chrome_mgr.start_chrome_debug_async()
            if success:
                self.status_msg.emit(msg, 3000)
                self.chrome_started_signal.emit()

                # 启动大脑调度循环
                if self._brain_task is None:
                    self._brain_task = asyncio.ensure_future(self._brain_loop())

                # 为每个中军帐AI创建 AIWorker
                platforms = self.config_mgr.get_ai_platforms()
                active_set = set(active_ais)
                for p in platforms:
                    if p.get("name") in active_set and p.get("name") not in self._ai_workers:
                        await self._create_ai_worker(p)
            else:
                self.toast.emit(msg)
        except Exception as e:
            log_exception("Chrome 启动异常", type(e), e, e.__traceback__)
            self.toast.emit(str(e))
        finally:
            self.button_state.emit(True, True)

    async def _create_ai_worker(self, ai_config: dict):
        """创建一个 AIWorker 并启动。"""
        name = ai_config.get("name", "")
        if name in self._ai_workers:
            return
        worker = AIWorker(ai_config, self._chrome_mgr, self._brain_queue)
        self._ai_workers[name] = worker
        worker._task = asyncio.ensure_future(worker.run())
        log_info(f"[大脑] 创建 AIWorker: {name}")

    def _destroy_ai_worker(self, name: str):
        """销毁一个 AIWorker（主线程调用）。"""
        if name in self._ai_workers:
            self._ai_workers[name].stop()
            del self._ai_workers[name]
            log_info(f"[大脑] 销毁 AIWorker: {name}")

    def on_ai_added(self, name: str):
        """AI 进入中军帐时创建 AIWorker（主线程调用）。"""
        if not self._chrome_mgr or not self._chrome_mgr.is_chrome_running():
            return  # Chrome 未启动，不创建
        platform = self.config_mgr.get_platform_by_name(name)
        if platform:
            self.submit(self._create_ai_worker(platform))

    def on_ai_removed(self, name: str):
        """AI 离开中军帐 — 主线程只发命令，大脑线程销毁AIWorker。"""
        self.submit(self._async_destroy_ai_worker(name))

    async def _async_destroy_ai_worker(self, name: str):
        """在工作线程中销毁 AIWorker。"""
        if name in self._ai_workers:
            self._ai_workers[name].stop()
            del self._ai_workers[name]
            log_info(f"[大脑] 销毁 AIWorker: {name}")

    # ===== 大脑调度循环 =====

    async def _brain_loop(self):
        """大脑主循环：接收 AIWorker 报告，更新UI，调度讨论。"""
        while self._running:
            try:
                report = await asyncio.wait_for(self._brain_queue.get(), timeout=1.0)
                await self._handle_report(report)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log_warning(f"大脑调度异常: {e}")

    async def _handle_report(self, report: tuple):
        """处理 AIWorker 发来的报告。

        大脑职责（2级线程）：
        - 接收3级线程的所有报告（状态、回复、发言状态等）
        - 统筹多条消息：如果同一AI发了多条，判断是否需要合并
        - 将有效回复转发给 HostedMode 处理
        - 发言状态转发给主线程更新UI
        """
        report_type = report[0]
        name = report[1]

        if report_type == "status":
            color = report[2]
            msg = report[3]
            self.ai_status.emit(name, color, msg)

        elif report_type == "page_opened":
            self.page_opened.emit(name, True)

        elif report_type == "page_failed":
            self.page_opened.emit(name, False)
            self.ai_status.emit(name, "orange", "页面打开失败")

        elif report_type == "ai_speaking":
            # AI发言状态：True=正在发言, False=发言完毕
            speaking = report[2]
            if speaking:
                self.ai_status.emit(name, "green", "正在发言...")
            # 发言完毕时不改变状态颜色，保持green

        elif report_type == "reply":
            # AIWorker报告的回复，转发给 HostedMode 处理
            if self._discussion_reply_queue:
                await self._discussion_reply_queue.put(("reply", name, report[2]))

        elif report_type == "reply_fragment":
            # AIWorker报告的回复片段（可能不是完整回复）
            # 大脑记录这些片段，在收到完整reply时一起处理
            if self._discussion_reply_queue:
                await self._discussion_reply_queue.put(("reply_fragment", name, report[2]))

        elif report_type == "reply_error":
            if self._discussion_reply_queue:
                await self._discussion_reply_queue.put(("reply_error", name, report[2]))

        elif report_type == "error":
            log_error(f"[大脑] AIWorker {name} 错误: {report[2]}")
            self.ai_status.emit(name, "orange", report[2])

    # ===== 讨论操作 =====

    def do_start_discussion(self, topic: str, ai_list: list, file_paths: list):
        """开始讨论（主线程调用）。"""
        self.submit(self._run_discussion(topic, ai_list, file_paths))

    async def _run_discussion(self, topic: str, ai_list: list, file_paths: list):
        """运行讨论流程。"""
        self._discussion_running = True
        # 讨论中保持发送按钮可用（用户可随时插话），只禁用启动阶段
        self.button_state.emit(True, True)

        def progress_callback(role, name, text):
            self.progress.emit(role, name, text)

        try:
            self._chrome_mgr.config = self.config_mgr.config
            hosted = HostedMode(self.config_mgr.config, self._chrome_mgr)
            self._hosted = hosted

            result = await hosted.run(topic, ai_list, progress_callback,
                                      file_paths=file_paths or None)
            self.discussion_done.emit(result)
        except Exception as e:
            log_exception("讨论过程中发生异常", type(e), e, e.__traceback__)
            self.toast.emit(f"讨论过程中出错:\n{e}")
        finally:
            self._discussion_running = False
            self.button_state.emit(True, True)
            if self._hosted:
                self._hosted._is_running = False

    def do_continue_discussion(self, user_message: str):
        """继续讨论（用户插话）。"""
        self.submit(self._run_continue(user_message))

    async def _run_continue(self, user_message: str):
        """运行继续讨论流程。"""
        self._discussion_running = True
        self.button_state.emit(True, True)

        def progress_callback(role, name, text):
            self.progress.emit(role, name, text)

        try:
            if self._hosted:
                result = await self._hosted.continue_discussion(
                    user_message, progress_callback
                )
                self.discussion_done.emit(result)
        except Exception as e:
            log_exception("继续讨论异常", type(e), e, e.__traceback__)
            self.toast.emit(f"继续讨论出错:\n{e}")
        finally:
            self._discussion_running = False
            self.button_state.emit(True, True)

    def do_stop_discussion(self):
        """停止讨论 — 主线程只发命令，大脑线程执行。"""
        self.submit(self._async_stop_discussion())

    async def _async_stop_discussion(self):
        """在工作线程中停止讨论。"""
        if self._hosted:
            self._hosted._stop_requested = True

    def do_clear_history(self):
        """清除讨论历史 — 主线程只发命令，大脑线程执行。"""
        self.submit(self._async_clear_history())

    async def _async_clear_history(self):
        """在工作线程中清除讨论历史。"""
        if self._hosted:
            self._hosted._last_ai_list = None
            self._hosted._last_pages = None
            self._hosted._last_history = None
            log_info("讨论历史已清除")

    def do_stop_chrome(self):
        """关闭 Chrome — 主线程只发命令，大脑线程异步执行全部操作。"""
        self.submit(self._async_stop_chrome_full())

    async def _async_stop_chrome_full(self):
        """在工作线程中完成所有关闭操作：停止讨论 → 销毁AIWorker → 关闭Chrome → 通知UI。"""
        try:
            # 1. 停止讨论
            if self._hosted:
                self._hosted._stop_requested = True
                self._hosted._is_running = False

            # 2. 销毁所有 AIWorker
            for name in list(self._ai_workers.keys()):
                try:
                    self._ai_workers[name].stop()
                    del self._ai_workers[name]
                    log_info(f"[大脑] 销毁 AIWorker: {name}")
                except Exception as e:
                    log_warning(f"销毁 AIWorker {name} 失败: {e}")

            # 3. 关闭 Chrome
            if self._chrome_mgr:
                self._chrome_mgr.stop_chrome()

            # 4. 通知UI
            self.chrome_stopped_signal.emit()
        except Exception as e:
            log_error(f"关闭Chrome失败: {e}")
            self.chrome_stopped_signal.emit()

    @property
    def discussion_running(self):
        return self._discussion_running

    @property
    def hosted(self):
        return self._hosted

    @property
    def _discussion_reply_queue(self):
        """讨论回复队列（HostedMode 用于接收 AIWorker 的回复）。"""
        if self._hosted and hasattr(self._hosted, '_reply_queue'):
            return self._hosted._reply_queue
        return None
