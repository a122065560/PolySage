"""
core - 托管模式核心模块

HostedMode：N 位 AI 全自动轮转讨论主循环 + 结案机制（auto / 指定AI / lm_studio）。

讨论流程：
  Phase 1 → 向 ai_list[0] 发送开场白 + 话题，提取回复
  Phase 2 → 将 ai_list[0] 的回复转发给 ai_list[1]，提取回复
  Phase 4 → 按 ai_list 顺序轮转（0→1→…→n-1→0…），每个 AI 收到上一个 AI 的回复
  结束判定 → 哨兵标记 / 最大轮数 / 超时 / 用户停止
  结案 → 结案方说 End 立即结束；全部 AI 说 End 后由结案方整合最终方案
"""

import asyncio
import os
from typing import Optional

from browser import ChromeManager
from logger import log_info, log_warning, log_exception, log_error, DiscussionLogger
from utils import (
    build_init_prompt,
    build_topic_prompt,
    build_followup_prompt,
    build_round_prompt,
    build_user_input_prompt,
    build_supplement_prompt,
    build_summary_prompt,
    build_parallel_round_prompt,
    build_first_round_prompt,
    build_arbiter_first_prompt,
    build_arbiter_round_prompt,
    build_strategist_round_prompt,
    extract_focal_points,
    contains_end_signal,
    extract_before_signal,
    format_history_entry,
    clean_text,
)


class HostedMode:
    """讨论模式：基于托管模式，支持 N 个 AI 轮转讨论与用户多次插话。"""

    def __init__(self, config: dict, chrome_manager: ChromeManager):
        """
        Args:
            config: 完整配置字典
            chrome_manager: ChromeManager 实例
        """
        self.config = config
        self.chrome = chrome_manager
        self.discussion = config.get("discussion", {})
        self.end_signal = self.discussion.get("end_signal", "<已得出最终结果>")
        self.start_signal = self.discussion.get("start_signal", "<ok>")
        self.arbitration_signal = self.discussion.get("arbitration_signal", "<结案>")
        self.max_rounds = self.discussion.get("max_rounds", 20)
        self.timeout = self.discussion.get("timeout_seconds", 300)
        self.arbitrator = self.discussion.get("arbitrator", "")
        if not self.arbitrator:
            # 从AI平台列表中读取 is_arbitrator 标记
            platforms = config.get("ai_platforms", [])
            for p in platforms:
                if p.get("is_arbitrator", False):
                    self.arbitrator = p["name"]
                    break
            if not self.arbitrator and platforms:
                self.arbitrator = platforms[0]["name"]
        self.opening_remarks = self.discussion.get("opening_remarks", "")
        # 最少讨论轮数：在此之前不允许军师结案（防止开场白阶段误触发）
        self.min_rounds_before_arbitration = self.discussion.get("min_rounds_before_arbitration", 3)
        # 用户输入队列：用户可在讨论中随时插话
        self._user_input_queue: asyncio.Queue = asyncio.Queue()
        # 讨论是否正在进行（用于控制用户输入）
        self._is_running = False
        # 用户请求停止讨论
        self._stop_requested = False
        # 被用户剔除的AI（讨论中途移出议事厅），不再发送/重建页面
        self._removed_ais: set = set()
        # 本轮被剔除的AI及原因 {name: reason}，用于通知军师
        self._removed_this_round: dict = {}
        # 追问模式引用（run 结束后保存，供 continue_discussion 使用）
        self._last_ai_list: Optional[list] = None
        self._last_pages: Optional[dict] = None
        self._last_history: Optional[list] = None

    # ------------------------------------------------------------------
    # 状态控制（保持不变）
    # ------------------------------------------------------------------

    def submit_user_input(self, message: str):
        """用户提交主公密令（线程安全，可在任意协程中调用）。

        即使讨论正在初始化（_is_running 还未设为 True），
        也允许将消息加入队列，后续 run() 循环会处理。
        """
        self._user_input_queue.put_nowait(message)
        log_info(f"主公密令已加入队列: {message[:50]}...")

    def request_stop(self):
        """用户请求停止讨论（优雅终止）。"""
        self._stop_requested = True
        log_info("用户请求停止讨论")

    def mark_ai_removed(self, name: str, reason: str = "用户手动剔除"):
        """标记AI被用户剔除（讨论中途移出议事厅），不再发送/重建页面。"""
        self._removed_ais.add(name)
        self._removed_this_round[name] = reason
        log_info(f"AI [{name}] 被剔除（{reason}），不再发送/重建页面")

    def _check_short_reply(self, ai_name: str, reply: str,
                           ai_short_replies: dict, ai_disabled: set,
                           progress_callback=None) -> bool:
        """
        检测短回复重复：如果AI回复<=20字且与上次回复内容相同，累计计数。
        连续2次相同短回复则自动剔除该AI。

        Args:
            ai_name: AI名称
            reply: 本次回复内容
            ai_short_replies: {name: {"text": str, "count": int}} 记录上次短回复
            ai_disabled: 已禁用的AI集合
            progress_callback: 进度回调

        Returns:
            bool: True表示该AI被剔除，False表示正常
        """
        SHORT_REPLY_THRESHOLD = 20  # 20字以内算短回复
        SHORT_REPLY_MAX_COUNT = 2   # 重复2次即剔除

        reply_stripped = reply.strip()
        if len(reply_stripped) > SHORT_REPLY_THRESHOLD:
            # 回复正常长度，重置计数
            if ai_name in ai_short_replies:
                del ai_short_replies[ai_name]
            return False

        # 短回复，检查是否与上次相同
        prev = ai_short_replies.get(ai_name)
        if prev is None:
            # 首次短回复，记录
            ai_short_replies[ai_name] = {"text": reply_stripped, "count": 1}
            log_info(f"[{ai_name}] 短回复检测（第1次，{len(reply_stripped)}字）：{reply_stripped[:30]}")
            return False

        if reply_stripped == prev["text"]:
            # 与上次相同的短回复
            prev["count"] += 1
            count = prev["count"]
            log_warning(f"[{ai_name}] 短回复检测（第{count}次，{len(reply_stripped)}字）：{reply_stripped[:30]}")

            if count >= SHORT_REPLY_MAX_COUNT:
                # 达到阈值，自动剔除
                reason = f"连续{count}次相同短回复（{len(reply_stripped)}字），已失去讨论能力，自动剔除"
                ai_disabled.add(ai_name)
                self._removed_ais.add(ai_name)
                self._removed_this_round[ai_name] = reason
                if progress_callback:
                    progress_callback("status", "系统",
                        f"🚫 {ai_name} 连续{count}次相同短回复（'{reply_stripped[:20]}'），已自动剔除议事厅")
                log_warning(f"[{ai_name}] 连续{count}次相同短回复，已自动剔除")
                # 清除记录
                del ai_short_replies[ai_name]
                return True
        else:
            # 不同的短回复，重置计数
            ai_short_replies[ai_name] = {"text": reply_stripped, "count": 1}
            log_info(f"[{ai_name}] 短回复检测（重置，{len(reply_stripped)}字）：{reply_stripped[:30]}")

        return False

    def is_running(self) -> bool:
        """讨论是否正在进行。"""
        return self._is_running

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _other_names(self, my_name: str, ai_list: list) -> str:
        """返回 ai_list 中除 my_name 外的所有 AI 名称（逗号分隔）。"""
        return ", ".join(ai["name"] for ai in ai_list if ai["name"] != my_name)

    def _init_prefix(self, ai: dict, initialized: set, ai_list: list) -> str:
        """
        首次参与的 AI 返回初始化提示前缀（并标记已初始化），否则返回空串。

        保证 N>2 时，ai_list[2:] 在首次收到消息时也能获得身份规则与结束标记说明。
        """
        if ai["name"] in initialized:
            return ""
        initialized.add(ai["name"])
        init_prompt = build_init_prompt(
            my_name=ai["name"],
            opponent_name=self._other_names(ai["name"], ai_list),
            opening_remarks=self.opening_remarks,
            arbitrator=self.arbitrator,
            end_signal=self.end_signal,
            arbitration_signal=self.arbitration_signal,
            all_ai_names=[a["name"] for a in ai_list],
            start_signal=self.start_signal,
        )
        return init_prompt + "\n\n"

    async def _check_end(self, reply: str, ai: dict, history: list,
                         done_set: set, done_state: dict, ai_list: list,
                         pages: dict, progress_callback, round_count: int):
        """
        检查回复是否包含结束标记或结案标记，返回 (ended, result)。

        会就地更新 done_set 与 done_state。

        结束规则（严格）：
          - 军师说结案标识(如<结案>) → 立即结束，军师的回复即为最终方案
          - 所有 AI 都说了 End → 结案方整合最终方案
          - 结案方单独说 End 不会立即结束（必须等所有AI都同意）
          - 达到最大轮数时，强制结案方整合
        """
        # 优先检测：军师发出结案标识 → 立即结束
        # 但在前 min_rounds_before_arbitration 轮内不允许结案（防止过早结束）
        is_arbitrator = (
            self.arbitrator and self.arbitrator != "auto"
            and ai["name"] == self.arbitrator
        )
        # 最少讨论轮数：前几轮不允许结案（防止开场白阶段误触发）
        min_rounds = getattr(self, 'min_rounds_before_arbitration', 3)
        if is_arbitrator and self.arbitration_signal and self.arbitration_signal in reply:
            if round_count < min_rounds:
                # 轮数不足，忽略结案信号，军师继续参与讨论
                if progress_callback:
                    progress_callback("status", "系统",
                        f"⏸️ 军师想要结案，但讨论才第 {round_count + 1} 轮（至少需 {min_rounds + 1} 轮），继续讨论...")
                log_info(f"军师结案被推迟: 当前{round_count + 1}轮 < 最少{min_rounds + 1}轮")
                # 回复已经从外部清理（_check_end之后才加入history）
                return False, None
            if progress_callback:
                progress_callback("status", "系统", f"⚖️ 军师 {self.arbitrator} 已结案，讨论终止")
                progress_callback("waiting", "系统", "已结案")
            # 提取结案标识之前的内容作为最终方案
            final = extract_before_signal(reply, self.arbitration_signal)
            if not final.strip():
                final = reply.replace(self.arbitration_signal, "").strip()
            self._is_running = False
            self._save_discussion_state(ai_list, pages, history)
            return True, {
                "history": history,
                "final_result": final,
                "ended_by": f"军师 {self.arbitrator} 结案",
                "rounds": round_count + 1,
            }

        if not contains_end_signal(reply, self.end_signal):
            return False, None

        done_set.add(ai["name"])
        done_state["last_reply"] = reply
        done_state["last_name"] = ai["name"]

        if progress_callback:
            progress_callback("status", "系统",
                              f"✅ {ai['name']} 已确认讨论充分（{len(done_set)}/{len(ai_list)}）")

        # 只有当所有 AI 都说了 End → 结案方整合最终方案
        if len(done_set) >= len(ai_list):
            if self.arbitrator and self.arbitrator != "auto":
                if progress_callback:
                    progress_callback("status", "系统",
                                      f"所有AI已达成共识，由军师 {self.arbitrator} 结案整合最终方案...")
                final = await self.resolve_arbitrator(
                    self.arbitrator, history, done_state["last_reply"],
                    ai_list, pages
                )
                # 在最终方案末尾添加结案标识
                final = f"{final}\n{self.arbitration_signal}"
                if progress_callback:
                    progress_callback("status", "系统", f"军师 {self.arbitrator} 已结案")
                    progress_callback("waiting", "系统", "已结案")
            else:
                # auto 模式：提取最后一条说 End 的回复中标记前内容
                final = extract_before_signal(done_state["last_reply"], self.end_signal)
            self._is_running = False
            return True, {
                "history": history,
                "final_result": final,
                "ended_by": f"所有AI达成共识（{done_state['last_name']} 最后确认）",
                "rounds": round_count + 1,
            }

        # 还有其他 AI 未说 End → 继续讨论
        remaining = [ai["name"] for ai in ai_list if ai["name"] not in done_set]
        if progress_callback:
            progress_callback("status", "系统",
                              f"等待 {', '.join(remaining)} 确认...")
        return False, None

    def _save_discussion_state(self, ai_list, pages, history):
        """保存讨论状态，供追问模式复用。"""
        self._last_ai_list = ai_list
        self._last_pages = pages
        self._last_history = list(history) if history else []
        log_info(f"讨论状态已保存: {len(ai_list)}个AI, {len(self._last_history)}条历史")

    async def _send_to(self, ai: dict, pages: dict, prompt: str,
                       progress_callback, timeout: int = None,
                       fast_wait: bool = False,
                       force_file_upload: bool = False):
        timeout = timeout or self.timeout
        max_retries = 3  # 页面失效时最多重建3次

        # 如果AI已被用户剔除，直接跳过，不发送也不重建页面
        if ai["name"] in self._removed_ais:
            log_info(f"[{ai['name']}] 已被用户剔除，跳过发送")
            return None, Exception(f"{ai['name']} 已被用户剔除")

        for attempt in range(max_retries):
            try:
                page = pages.get(ai["name"])
                if page is None:
                    raise Exception("页面引用为空")

                # 轻量检测页面是否有效
                try:
                    _ = page.url
                except Exception:
                    raise Exception("页面已关闭（Target page, context or browser has been closed）")

                # 通知UI：AI开始发言
                if progress_callback and not fast_wait:
                    progress_callback("ai_speaking", ai["name"], "True")

                reply = await self.chrome.send_and_wait(
                    page, prompt, ai,
                    timeout=timeout, fast_wait=fast_wait,
                    force_file_upload=force_file_upload
                )

                # === 大脑后处理：思考过滤（不再做二次提取） ===
                # 注意：之前这里有"大脑二次提取"逻辑，使用 reply_count_before=-1 提取所有容器
                # 这会导致提取到旧讨论内容和思考内容（因为-1表示不限制索引）
                # 现在完全移除二次提取，只依赖 send_and_wait 的首次提取（使用正确的 reply_count_before）
                if not fast_wait and reply and len(reply) > 20:
                    # 检查是否提取到思考内容
                    if self.chrome._is_thinking_content(reply):
                        log_warning(f"[{ai['name']}] 大脑检测到思考内容，尝试过滤...")
                        filtered = self.chrome._strip_thinking_content(reply, ai["name"])
                        if filtered and len(filtered) > 20 and not self.chrome._is_thinking_content(filtered):
                            log_info(f"[{ai['name']}] ✅ 从思考内容中提取到实际回复: {len(filtered)}字")
                            reply = filtered
                        else:
                            log_warning(f"[{ai['name']}] 思考内容过滤失败，保留原始提取结果")

                # 如果回复很短（<20字），尝试通用提取作为最后手段
                if not fast_wait and reply and len(reply) < 20:
                    try:
                        generic_reply = await self.chrome._extract_generic_response(page, ai["name"])
                        if generic_reply and len(generic_reply) > len(reply):
                            log_info(f"[{ai['name']}] 通用提取更完整: {len(reply)}字 → {len(generic_reply)}字")
                            reply = generic_reply
                    except Exception:
                        pass

                # 通知UI：AI发言完毕
                if progress_callback and not fast_wait:
                    progress_callback("ai_speaking", ai["name"], "False")

                return reply, None

            except Exception as e:
                error_msg = str(e)
                is_page_error = ("closed" in error_msg.lower() or "target" in error_msg.lower()
                                 or "页面" in error_msg or "page" in error_msg.lower())

                if is_page_error and attempt < max_retries - 1:
                    # 如果AI已被用户剔除，不再重建页面
                    if ai["name"] in self._removed_ais:
                        log_info(f"[{ai['name']}] 已被用户剔除，不重建页面")
                        return None, Exception(f"{ai['name']} 已被用户剔除")
                    # 页面失效，尝试重建
                    if progress_callback:
                        progress_callback("status", "系统",
                            f"🔄 {ai['name']} 页面断开，正在重连...（第{attempt + 1}次）")
                    log_warning(f"[{ai['name']}] 页面失效: {error_msg}，尝试重建（第{attempt + 1}次）")

                    try:
                        new_page = await asyncio.wait_for(
                            self.chrome.get_or_create_page(ai["url"]),
                            timeout=30
                        )
                        if new_page:
                            pages[ai["name"]] = new_page
                            log_info(f"[{ai['name']}] 页面重建成功，等待加载...")
                            if progress_callback:
                                progress_callback("status", "系统",
                                    f"✅ {ai['name']} 页面已重连，等待页面加载...")
                            await asyncio.sleep(5)  # 等待页面加载和登录恢复
                            continue  # 重试发送
                        else:
                            log_error(f"[{ai['name']}] 页面重建返回空")
                    except asyncio.TimeoutError:
                        log_error(f"[{ai['name']}] 页面重建超时（30秒）")
                        if progress_callback:
                            progress_callback("status", "系统",
                                f"⚠️ {ai['name']} 页面重连超时，等待网络恢复...")
                        await asyncio.sleep(10)  # 等待更长时间
                        continue
                    except Exception as re_err:
                        log_error(f"[{ai['name']}] 页面重建失败: {re_err}")
                        if progress_callback:
                            progress_callback("status", "系统",
                                f"⚠️ {ai['name']} 页面重连失败，等待网络恢复...")
                        await asyncio.sleep(10)
                        continue
                else:
                    # 非页面错误，或已达到最大重试次数
                    return None, e

        return None, Exception(f"页面重建{max_retries}次后仍失败")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self, topic: str, ai_list: list,
                  progress_callback=None, file_paths: list = None) -> dict:
        """
        托管模式主循环（N 个 AI 轮转讨论）。

        流程：
          Phase 0: 上传文件到所有 AI 页面（如有）
          Phase 1: 向所有 AI 发送开场白（含身份规则），等待每个 AI 回复"ok"
          Phase 2: 向 ai_list[0] 发送用户话题，等待回复
          Phase 3: 将 ai_list[0] 的回复转发给 ai_list[1]，等待回复
          Phase 4: 按 ai_list 顺序轮转，每个 AI 收到上一个 AI 的回复
                   直到结案方说 End、所有 AI 说 End、达到最大轮数或用户停止

        Args:
            topic: 讨论话题
            ai_list: AI 平台配置字典列表（2 个或更多）
            progress_callback: 进度回调函数
            file_paths: 可选文件路径列表（在 Phase 0 上传到所有 AI 页面）

        Returns:
            dict: {"history", "final_result", "ended_by", "rounds"}
        """
        # 校验：至少 2 个 AI
        if not ai_list or len(ai_list) < 2:
            msg = "错误: 至少需要 2 个 AI 参与讨论"
            if progress_callback:
                progress_callback("error", "系统", msg)
            log_info(msg)
            self._is_running = False
            return {
                "history": [], "final_result": None,
                "ended_by": msg, "rounds": 0,
            }

        self._is_running = True
        self._stop_requested = False
        self._removed_ais.clear()  # 新讨论开始时，清除上次的剔除记录
        self._removed_this_round.clear()  # 清除剔除通知记录
        # 新讨论开始时，清除上一次讨论的回复缓存
        if hasattr(self.chrome, '_last_reply'):
            self.chrome._last_reply.clear()
            log_info("已清除AI回复缓存（新讨论开始，AI网页上下文不受影响）")

        # 创建讨论记录器
        participants = [a["name"] for a in ai_list]
        disc_logger = DiscussionLogger(topic, participants)
        log_info(f"[大脑] 讨论开始: {topic} (参与: {', '.join(participants)})")

        history = []
        round_count = 0
        n = len(ai_list)
        done_set = set()
        done_state = {"last_reply": "", "last_name": ""}
        initialized = set()
        pages = {}

        # 打开所有 AI 页面（结案后重新讨论时，复用已有页面，延续上下文）
        for ai in ai_list:
            if progress_callback:
                log_info(f"正在打开 {ai['name']} 页面...")
            pages[ai["name"]] = await self.chrome.get_or_create_page(ai["url"])

        # ==============================================================
        # Phase 0+1: 向所有 AI 并行上传文件 + 发送开场白，等待确认
        # ==============================================================
        # 并行优化：所有 AI 同时收到文件和开场白，同时等待回复
        # 比串行快 N 倍（N = AI 数量）

        async def _init_one_ai(ai: dict) -> tuple:
            """初始化单个 AI：上传文件 + 发送开场白 + 等待确认。返回 (ai, reply, error)。"""
            name = ai["name"]
            page = pages[name]

            # 0a. 上传文件到这个 AI 的页面（支持多文件）
            if file_paths:
                for fp in file_paths:
                    if fp and os.path.isfile(fp):
                        log_info(f"[{name}] 上传文件: {fp}")
                        if progress_callback:
                            progress_callback("status", "系统", f"正在上传文件 {os.path.basename(fp)} 到 {name}...")
                        await self.chrome._upload_file(page, fp, name)
                        await asyncio.sleep(3)

            # 0b. 发送开场白
            init_prompt = self._init_prefix(ai, initialized, ai_list)
            if progress_callback:
                log_info(f"正在向 {name} 发送开场白...")
                progress_callback("user_prompt", name, init_prompt)
                progress_callback("waiting", "系统", f"等待 {name} 确认...")

            # 0c. 等待回复（缩短超时，确认回复通常很快，使用快速检测）
            reply_ok, err = await self._send_to(ai, pages, init_prompt, progress_callback, timeout=30, fast_wait=True)
            return (ai, reply_ok, err)

        # 并行执行所有 AI 的初始化
        init_tasks = []
        for ai in ai_list:
            if self._stop_requested:
                self._is_running = False
                return {
                    "history": history, "final_result": None,
                    "ended_by": "用户手动结束讨论", "rounds": 0,
                }
            init_tasks.append(_init_one_ai(ai))

        if progress_callback:
            progress_callback("status", "系统", f"正在同时向 {len(init_tasks)} 个 AI 发送开场白...")

        # asyncio.gather 并行等待所有 AI 确认
        init_results = await asyncio.gather(*init_tasks, return_exceptions=True)

        # 检查结果
        failed_ais = set()
        for result in init_results:
            if isinstance(result, Exception):
                log_error(f"初始化异常: {result}")
                # 记录异常但不中断讨论，跳过该AI
                continue
            ai, reply_ok, err = result
            if err is not None:
                if progress_callback:
                    progress_callback("error", ai["name"], str(err))
                log_warning(f"[{ai['name']}] 确认失败: {err}，跳过该AI，继续讨论")
                failed_ais.add(ai["name"])
                continue

            reply_ok_clean = clean_text(reply_ok).lower().strip()
            is_confirmed = any(kw in reply_ok_clean for kw in [
                "ok", "收到", "明白", "明白", "ready", "就绪", "准备", "好的", "可以", "确认",
                "okay", "yes", "sure", "got it", "understood", "acknowledged",
            ])
            if is_confirmed:
                log_info(f"Phase 1: {ai['name']} 已确认")
            else:
                log_info(f"Phase 1: {ai['name']} 回复({reply_ok_clean[:80]}), 继续")
            if progress_callback:
                progress_callback("ai_reply", ai["name"], reply_ok)

        # 过滤掉初始化失败的AI
        if failed_ais:
            ai_list = [ai for ai in ai_list if ai["name"] not in failed_ais]
            if progress_callback:
                progress_callback("status", "系统", f"⚠️ {', '.join(failed_ais)} 初始化失败，已跳过，继续讨论")
            log_warning(f"初始化失败的AI: {failed_ais}，剩余AI: {[a['name'] for a in ai_list]}")
            if len(ai_list) < 2:
                self._is_running = False
                return {
                    "history": history, "final_result": None,
                    "ended_by": f"错误: 参与讨论的AI不足2个（{', '.join(failed_ais)}初始化失败）",
                    "rounds": 0,
                }

        log_info("Phase 0+1 完成: 所有 AI 已并行收到文件和开场白")
        if progress_callback:
            progress_callback("status", "系统", "所有 AI 已就绪，开始正式讨论...")
            progress_callback("discussion_start", "系统", "")  # 通知UI开始编号

        # ==============================================================
        # Phase 2-4: 军师主导 + 大脑统筹的并行讨论
        # ==============================================================
        # 架构（用户指定方案）：
        #   1. 军师先发言 → 大脑收到
        #   2. 大脑把军师的话发给所有谋士 → 谋士并行回复
        #   3. 大脑收集所有回复（标注：谁、什么时间、说了什么）
        #   4. 大脑统筹汇总 → 下发给所有AI → 下一轮
        #   - asyncio.as_completed：先回复的先展示，不互相等待
        #   - 软超时180秒：给AI足够时间生成长回复
        #   - 全失败时重试（最多3次），不立即结束
        #   - 军师可随时结案结束（但需达到最少轮数）

        soft_timeout = max(self.timeout, 120)  # 软超时 = 单AI超时（用户可设置），至少120s
        prev_round_replies = []  # 上一轮所有AI的回复
        consecutive_failures = 0  # 连续失败轮数
        ai_fail_count = {}  # 各AI连续失败计数 {name: count}
        ai_disabled = set()  # 已禁用的AI（连续失败超过阈值）
        ai_short_replies = {}  # 短回复检测 {name: {"text": str, "count": int}}

        while round_count < self.max_rounds:
            if self._stop_requested:
                self._is_running = False
                self._save_discussion_state(ai_list, pages, history)
                if progress_callback:
                    progress_callback("status", "系统", "主公结束了讨论")
                return {
                    "history": history, "final_result": None,
                    "ended_by": "用户手动结束讨论",
                    "rounds": round_count,
                }

            # ----------------------------------------------------------
            # 主公密令处理（累积队列策略）
            # 军师在上一轮已回复完毕（空闲），此时处理所有累积的密令
            # 多条密令合并为一条发给军师，避免打扰军师吐token
            # ----------------------------------------------------------
            all_user_msgs = []
            while not self._user_input_queue.empty():
                try:
                    user_msg = self._user_input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                all_user_msgs.append(user_msg)

            if all_user_msgs:
                # 合并多条密令为一条
                if len(all_user_msgs) == 1:
                    combined_msg = all_user_msgs[0]
                    log_info(f"处理主公密令: {combined_msg[:50]}...")
                else:
                    combined_msg = "\n\n".join(
                        f"密令{i+1}: {msg}" for i, msg in enumerate(all_user_msgs)
                    )
                    log_info(f"处理{len(all_user_msgs)}条主公密令，已合并发送")

                if progress_callback:
                    progress_callback("user_message", "主公", combined_msg)

                # 构建AI剔除通知（如果有AI被剔除，密令中也附带通知）
                removal_notice_for_supplement = ""
                if self._removed_this_round:
                    removal_lines = [f"  - {name}：{reason}" for name, reason in self._removed_this_round.items()]
                    removal_notice_for_supplement = "\n".join(removal_lines)

                # 密令发给军师，军师将密令纳入下一轮上下文
                arb_ai = None
                if self.arbitrator and self.arbitrator != "auto":
                    for a in ai_list:
                        if a["name"] == self.arbitrator:
                            arb_ai = a
                            break
                if arb_ai:
                    prompt_user = (
                        self._init_prefix(arb_ai, initialized, ai_list)
                        + build_supplement_prompt(combined_msg, arb_ai["name"],
                                                  end_signal=self.end_signal,
                                                  system_notice=removal_notice_for_supplement)
                    )
                    if progress_callback:
                        progress_callback("user_prompt", arb_ai["name"], prompt_user)
                    reply_u, err = await self._send_to(arb_ai, pages, prompt_user, progress_callback)
                    if err is None:
                        reply_u = clean_text(reply_u)
                        history.append(format_history_entry(arb_ai["name"], reply_u))
                        if progress_callback:
                            progress_callback("ai_reply", arb_ai["name"], reply_u)
                        # 检查军师是否结案
                        ended, result = await self._check_end(
                            reply_u, arb_ai, history, done_set, done_state,
                            ai_list, pages, progress_callback, round_count
                        )
                        if ended:
                            self._is_running = False
                            self._save_discussion_state(ai_list, pages, history)
                            return result

            # ----------------------------------------------------------
            # 军师主导架构：军师先发言 → 大脑转发给谋士 → 谋士并行回复
            # ----------------------------------------------------------
            import datetime

            # 找到军师AI
            arb_ai = None
            if self.arbitrator and self.arbitrator != "auto":
                for a in ai_list:
                    if a["name"] == self.arbitrator:
                        arb_ai = a
                        break
            # 如果没有指定军师，退化为纯并行模式
            if not arb_ai:
                arb_ai = ai_list[0]

            strategist_ais = [a for a in ai_list if a["name"] != arb_ai["name"] and a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
            # 通知被禁用的AI
            for a in ai_list:
                if a["name"] != arb_ai["name"] and (a["name"] in ai_disabled or a["name"] in self._removed_ais):
                    if progress_callback:
                        progress_callback("status", "系统", f"⚠️ {a['name']} 连续超时/失败或被用户剔除，本轮跳过")

            # Step 1: 军师先发言
            focal_points = extract_focal_points(prev_round_replies) if prev_round_replies else ""

            # 构建统一系统通知（AI变动等），格式为【系统通知】块
            system_notice = ""
            if self._removed_this_round:
                removal_lines = [f"  - {name}：{reason}" for name, reason in self._removed_this_round.items()]
                system_notice = "【系统通知】\n以下AI已被移出议事厅，不再参与讨论，无需等待他们的回复：\n" + "\n".join(removal_lines) + "\n"
                # 通知后清除，避免重复通知
                self._removed_this_round.clear()

            if not prev_round_replies:
                # 第一轮：军师收到话题，发表初始分析
                arb_prompt = (
                    self._init_prefix(arb_ai, initialized, ai_list)
                    + build_arbiter_first_prompt(
                        my_name=arb_ai["name"],
                        topic=topic,
                        all_ai_names=[a["name"] for a in ai_list if a["name"] not in self._removed_ais],
                        end_signal=self.end_signal,
                        arbitration_signal=self.arbitration_signal,
                        system_notice=system_notice,
                    )
                )
            else:
                # 后续轮：军师收到上一轮所有谋士的回复
                arb_prompt = (
                    self._init_prefix(arb_ai, initialized, ai_list)
                    + build_arbiter_round_prompt(
                        my_name=arb_ai["name"],
                        topic=topic,
                        prev_round_replies=prev_round_replies,
                        focal_points=focal_points,
                        round_num=round_count + 1,
                        end_signal=self.end_signal,
                        arbitration_signal=self.arbitration_signal,
                        system_notice=system_notice,
                    )
                )

            if progress_callback:
                progress_callback("user_prompt", arb_ai["name"], arb_prompt)
                # 构建轮次状态：已发言/未发言
                all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                spoken = []
                unspoken = [n for n in all_names if n != arb_ai["name"]]
                round_status = f"第{round_count + 1}轮 | 💬 {arb_ai['name']} 正在发言 | 已发言{len(spoken)}({','.join(spoken) if spoken else '无'}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                progress_callback("round_status", "系统", round_status)
                progress_callback("status", "系统", f"第 {round_count + 1} 轮：军师 {arb_ai['name']} 正在发言...")
                progress_callback("waiting", "系统", f"等待军师 {arb_ai['name']} 回复...")

            # 军师发言：第一轮用文字发送话题，后续轮用txt文件发送（避免文字过长导致AI平台罢工）
            arb_force_file = (round_count > 0)
            arb_reply, err = await self._send_to(arb_ai, pages, arb_prompt, progress_callback,
                                                  force_file_upload=arb_force_file)
            if err is not None:
                if progress_callback:
                    progress_callback("error", arb_ai["name"], str(err))
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    if progress_callback:
                        progress_callback("status", "系统", f"⚠️ 连续 {consecutive_failures} 次军师回复失败，讨论结束")
                    break
                if progress_callback:
                    progress_callback("status", "系统",
                        f"⚠️ 军师回复失败（第{consecutive_failures}次），等待网络恢复后重试...")
                log_warning(f"军师回复失败，连续{consecutive_failures}次，等待15秒后重试...")
                await asyncio.sleep(15)  # 等待更长时间让网络恢复
                continue

            arb_reply = clean_text(arb_reply)
            arb_timestamp = datetime.datetime.now().strftime("%H:%M:%S")

            # 短回复重复检测（军师也适用）
            if self._check_short_reply(arb_ai["name"], arb_reply, ai_short_replies, ai_disabled, progress_callback):
                # 军师被剔除，直接停止讨论（不好中途换帅）
                if progress_callback:
                    progress_callback("status", "系统",
                        f"🛑 军师 {arb_ai['name']} 短回复重复被剔除，讨论直接停止（不好中途换帅）")
                self._is_running = False
                return {"history": history, "final_result": None,
                        "ended_by": f"军师 {arb_ai['name']} 短回复重复被剔除，讨论停止",
                        "rounds": round_count}

            # 检查军师是否结案
            ended, result = await self._check_end(
                arb_reply, arb_ai, history, done_set, done_state,
                ai_list, pages, progress_callback, round_count
            )
            if ended:
                return result

            # 军师未结案，清理结案信号后加入历史
            arb_reply_clean = arb_reply
            if self.arbitration_signal and self.arbitration_signal in arb_reply_clean:
                arb_reply_clean = arb_reply_clean.replace(self.arbitration_signal, "").strip()

            current_round = round_count + 1
            round_replies = [{"name": arb_ai["name"], "content": arb_reply_clean, "timestamp": arb_timestamp, "round": current_round}]
            history.append(format_history_entry(arb_ai["name"], f"[第{current_round}轮] {arb_reply_clean}"))
            # 记录军师发言到讨论日志
            disc_logger.add_message(arb_ai["name"], arb_reply_clean, current_round)
            log_info(f"[大脑] {arb_ai['name']} 第{current_round}轮发言 ({len(arb_reply_clean)}字) → msg#{disc_logger._msg_counter}")
            if progress_callback:
                progress_callback("ai_reply", arb_ai["name"], f"[第{current_round}轮] {arb_reply_clean}")
                # 更新轮次状态：军师已发言
                all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                spoken = [arb_ai["name"]]
                unspoken = [n for n in all_names if n != arb_ai["name"]]
                round_status = f"第{current_round}轮 | ✅ {arb_ai['name']} 已发言 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                progress_callback("round_status", "系统", round_status)
                progress_callback("status", "系统", f"✅ 第{current_round}轮：军师 {arb_ai['name']} 已发言")

            # Step 2: 大脑把军师的话发给所有谋士，谋士并行回复
            # 重新过滤 strategist_ais，排除在军师发言期间被用户剔除的AI
            strategist_ais = [a for a in strategist_ais if a["name"] not in self._removed_ais and a["name"] not in ai_disabled]
            if strategist_ais:
                ai_prompts = {}
                for ai in strategist_ais:
                    prompt = (
                        self._init_prefix(ai, initialized, ai_list)
                        + build_strategist_round_prompt(
                            my_name=ai["name"],
                            topic=topic,
                            arbiter_name=arb_ai["name"],
                            arbiter_reply=arb_reply_clean,
                            prev_round_replies=prev_round_replies if prev_round_replies else None,
                            focal_points=focal_points,
                            round_num=round_count + 1,
                            end_signal=self.end_signal,
                        )
                    )
                    ai_prompts[ai["name"]] = prompt
                    if progress_callback:
                        progress_callback("user_prompt", ai["name"], prompt)

                if progress_callback:
                    ai_names = ", ".join(a["name"] for a in strategist_ais)
                    # 更新轮次状态：谋士正在并行回复
                    all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                    spoken = [arb_ai["name"]]
                    unspoken = [a["name"] for a in strategist_ais]
                    round_status = f"第{current_round}轮 | 💬 {ai_names} 正在回复 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                    progress_callback("round_status", "系统", round_status)
                    progress_callback("status", "系统", f"第 {round_count + 1} 轮：{ai_names} 正在并行回复...")
                    progress_callback("waiting", "系统", f"等待 {ai_names} 回复...")

                # 并行发送+等待（谋士始终用txt文件接收内容，避免文字过长导致AI平台罢工）
                async def _send_and_receive(ai: dict) -> tuple:
                    try:
                        reply, err = await self._send_to(ai, pages, ai_prompts[ai["name"]], progress_callback,
                                                          force_file_upload=True)
                        return (ai, reply, err)
                    except Exception as e:
                        return (ai, None, e)

                tasks = [asyncio.ensure_future(_send_and_receive(ai)) for ai in strategist_ais]
                done_count = 0
                total = len(tasks)

                for future in asyncio.as_completed(tasks, timeout=soft_timeout):
                    done_count += 1
                    try:
                        ai, reply, err = await future
                        # 跳过在等待期间被用户剔除的AI
                        if ai["name"] in self._removed_ais:
                            log_info(f"[{ai['name']}] 已被用户剔除，跳过本次回复处理")
                            total -= 1
                            continue
                        if err is not None:
                            # 记录该AI连续失败次数
                            ai_name = ai["name"]
                            ai_fail_count[ai_name] = ai_fail_count.get(ai_name, 0) + 1
                            fail_count = ai_fail_count[ai_name]
                            # Bug6: 超时2次即自动剔除
                            if fail_count >= 2 and ai_name not in ai_disabled:
                                ai_disabled.add(ai_name)
                                self._removed_ais.add(ai_name)
                                self._removed_this_round[ai_name] = f"连续{fail_count}次超时/无响应，已自动剔除"
                                if progress_callback:
                                    progress_callback("status", "系统",
                                        f"🚫 {ai_name} 连续 {fail_count} 次超时/失败，已自动剔除议事厅")
                                log_warning(f"[{ai_name}] 连续失败 {fail_count} 次，已自动剔除")
                                # Bug6: 如果被剔除的是军师，直接停止讨论（不好中途换帅）
                                if ai_name == self.arbitrator:
                                    if progress_callback:
                                        progress_callback("status", "系统",
                                            f"🛑 军师 {ai_name} 超时被剔除，讨论直接停止（不好中途换帅）")
                                    self._is_running = False
                                    return {
                                        "history": history, "final_result": None,
                                        "ended_by": f"军师 {ai_name} 超时被剔除，讨论停止",
                                        "rounds": round_count,
                                    }
                            elif progress_callback:
                                progress_callback("error", ai["name"], str(err))
                            continue

                        # 回复成功，重置该AI的失败计数
                        ai_fail_count[ai["name"]] = 0

                        reply = clean_text(reply)
                        reply_ts = datetime.datetime.now().strftime("%H:%M:%S")

                        # 短回复重复检测：<=20字且与上次相同，重复2次自动剔除
                        if self._check_short_reply(ai["name"], reply, ai_short_replies, ai_disabled, progress_callback):
                            # 该AI被剔除，跳过本次处理
                            continue

                        # 检查是否结束
                        ended, result = await self._check_end(
                            reply, ai, history, done_set, done_state,
                            ai_list, pages, progress_callback, round_count
                        )
                        if not ended:
                            reply_clean = reply
                            if self.arbitration_signal and self.arbitration_signal in reply_clean:
                                reply_clean = reply_clean.replace(self.arbitration_signal, "").strip()
                            round_replies.append({"name": ai["name"], "content": reply_clean, "timestamp": reply_ts, "round": current_round})
                            history.append(format_history_entry(ai["name"], f"[第{current_round}轮] {reply_clean}"))
                            # 记录谋士发言到讨论日志
                            # context_received: 引用本轮军师+之前轮次的回复
                            ctx_ids = [disc_logger._msg_counter - len(round_replies) + 1]  # 军师msg ID
                            msg_id = disc_logger.add_message(ai["name"], reply_clean, current_round, reply_to=ctx_ids if prev_round_replies else None)
                            log_info(f"[大脑] {ai['name']} 第{current_round}轮发言 ({len(reply_clean)}字) → msg#{msg_id}")
                            if progress_callback:
                                progress_callback("ai_reply", ai["name"], f"[第{current_round}轮] {reply_clean}")
                                # 更新轮次状态：谋士已回复
                                spoken.append(ai["name"])
                                remaining_unspoken = [n for n in all_names if n not in spoken and n not in self._removed_ais]
                                round_status = f"第{current_round}轮 | ✅ {ai['name']} 已回复 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(remaining_unspoken)}({','.join(remaining_unspoken) if remaining_unspoken else '无'})"
                                progress_callback("round_status", "系统", round_status)
                                progress_callback("status", "系统", f"✅ 第{current_round}轮：{ai['name']} 已回复 ({done_count}/{total})")
                        else:
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            return result

                    except asyncio.TimeoutError:
                        if progress_callback:
                            # 找出未完成的AI名称
                            pending_ais = []
                            for t, ai in zip(tasks, strategist_ais):
                                if not t.done():
                                    pending_ais.append(ai["name"])
                            pending_names = ", ".join(pending_ais) if pending_ais else "未知AI"
                            remaining = total - done_count + 1
                            progress_callback("status", "系统", f"⏰ 软超时 {soft_timeout}s，{remaining} 个谋士本轮跳过（{pending_names}）")
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log_exception(f"处理谋士回复时异常", type(e), e, e.__traceback__)
                        if progress_callback:
                            progress_callback("error", "系统", f"处理回复异常: {e}")
                        continue

                # 取消未完成任务
                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.sleep(0.5)

            # Step 3: 大脑统筹汇总，更新上一轮回复
            prev_round_replies = round_replies

            if len(round_replies) < 2:
                # 只有军师回复，没有谋士回复
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    if progress_callback:
                        progress_callback("status", "系统", f"⚠️ 连续 {consecutive_failures} 轮无谋士回复，讨论结束")
                    break
                if progress_callback:
                    progress_callback("status", "系统", f"⚠️ 本轮无谋士回复，重试中({consecutive_failures}/3)...")
                await asyncio.sleep(5)
                continue

            consecutive_failures = 0
            round_count += 1

        # 达到最大轮数，强制军师结案
        if self.arbitrator and self.arbitrator != "auto":
            if progress_callback:
                progress_callback("status", "系统",
                                  f"已达最大轮数 {self.max_rounds}，强制军师 {self.arbitrator} 结案结案...")
            try:
                final = await self.resolve_arbitrator(
                    self.arbitrator, history, prev_round_replies[-1]["content"] if prev_round_replies else "",
                    ai_list, pages
                )
                final = f"{final}\n{self.arbitration_signal}"
                if progress_callback:
                    progress_callback("status", "系统", f"军师 {self.arbitrator} 已结案")
            except Exception:
                final = None
            self._is_running = False
            self._save_discussion_state(ai_list, pages, history)
            return {
                "history": history,
                "final_result": final,
                "ended_by": f"达到最大轮数 {self.max_rounds}，军师强制结案结案",
                "rounds": round_count,
            }
        self._is_running = False
        self._save_discussion_state(ai_list, pages, history)
        return {
            "history": history,
            "final_result": None,
            "ended_by": f"达到最大轮数 {self.max_rounds}，未达成共识",
            "rounds": round_count,
        }

    # ------------------------------------------------------------------
    # 追问模式
    # ------------------------------------------------------------------

    async def continue_discussion(self, user_message: str,
                                   progress_callback=None) -> dict:
        """
        追问模式：讨论结束后，用户基于已有上下文继续提问。

        不重新初始化，直接复用上次讨论保存的 ai_list / pages / history，
        把用户消息按轮转发给各 AI，随后进入 Phase 4 轮转。

        Args:
            user_message: 用户的追问消息
            progress_callback: 进度回调

        Returns:
            dict: {"history", "final_result", "ended_by", "rounds"}
        """
        log_info(f"追问模式启动: {user_message[:50]}...")

        self._is_running = True
        self._stop_requested = False
        # 追问模式不清除 _removed_ais（上次剔除的AI仍然保持剔除状态）

        # 使用上次讨论保存的 AI、页面与历史
        if not self._last_ai_list or not self._last_pages:
            self._is_running = False
            return {
                "history": [], "final_result": None,
                "ended_by": "无可用的讨论上下文",
                "rounds": 0,
            }

        ai_list = self._last_ai_list
        pages = self._last_pages
        # 追问基于上次讨论历史，新增回合追加其后（供结案方整合时拥有完整上下文）
        history = list(self._last_history or [])
        n = len(ai_list)
        round_count = 0
        done_set = set()
        done_state = {"last_reply": "", "last_name": ""}
        # 追问模式下所有 AI 均已初始化过，不再重复发送身份规则
        initialized = {ai["name"] for ai in ai_list}

        # ==========================================================
        # 追问模式也使用军师主导架构
        # ==========================================================
        import datetime
        soft_timeout = max(self.timeout, 120)
        prev_round_replies = []
        consecutive_failures = 0
        ai_fail_count = {}  # 各AI连续失败计数
        ai_disabled = set()  # 已禁用的AI
        ai_short_replies = {}  # 短回复检测 {name: {"text": str, "count": int}}

        # 找到军师AI
        arb_ai = None
        if self.arbitrator and self.arbitrator != "auto":
            for a in ai_list:
                if a["name"] == self.arbitrator:
                    arb_ai = a
                    break
        if not arb_ai:
            arb_ai = ai_list[0]
        strategist_ais = [a for a in ai_list if a["name"] != arb_ai["name"] and a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
        for a in ai_list:
            if a["name"] != arb_ai["name"] and (a["name"] in ai_disabled or a["name"] in self._removed_ais):
                if progress_callback:
                    progress_callback("status", "系统", f"⚠️ {a['name']} 连续超时/失败或被用户剔除，本轮跳过")

        while round_count < self.max_rounds:
            if self._stop_requested:
                self._is_running = False
                return {
                    "history": history, "final_result": None,
                    "ended_by": "用户手动结束讨论",
                    "rounds": round_count,
                }

            # Step 1: 军师先发言
            focal_points = extract_focal_points(prev_round_replies) if prev_round_replies else ""

            # 构建统一系统通知（AI变动等），格式为【系统通知】块
            system_notice = ""
            if self._removed_this_round:
                removal_lines = [f"  - {name}：{reason}" for name, reason in self._removed_this_round.items()]
                system_notice = "【系统通知】\n以下AI已被移出议事厅，不再参与讨论，无需等待他们的回复：\n" + "\n".join(removal_lines) + "\n"
                self._removed_this_round.clear()

            if round_count == 0:
                # 第一轮追问：军师收到用户消息
                sn_parts = []
                sn_parts.append(f"  - 主公追问：{user_message}")
                if system_notice:
                    # system_notice 已有【系统通知】头，取出内容部分追加
                    sn_content = system_notice.replace("【系统通知】\n", "").rstrip("\n")
                    sn_parts.append(sn_content)
                full_system_notice = "【系统通知】\n" + "\n".join(sn_parts) + "\n"
                arb_prompt = (
                    self._init_prefix(arb_ai, initialized, ai_list)
                    + full_system_notice
                    + f"\n请{arb_ai['name']}（军师）针对以上主公追问发表你的看法。"
                )
            else:
                arb_prompt = (
                    self._init_prefix(arb_ai, initialized, ai_list)
                    + build_arbiter_round_prompt(
                        my_name=arb_ai["name"],
                        topic=user_message,
                        prev_round_replies=prev_round_replies,
                        focal_points=focal_points,
                        round_num=round_count + 1,
                        end_signal=self.end_signal,
                        arbitration_signal=self.arbitration_signal,
                        system_notice=system_notice,
                    )
                )

            if progress_callback and round_count == 0:
                progress_callback("user_message", "主公", user_message)
                progress_callback("user_prompt", arb_ai["name"], arb_prompt)
                progress_callback("status", "系统", f"追问：军师 {arb_ai['name']} 正在发言...")
                progress_callback("waiting", "系统", f"等待军师 {arb_ai['name']} 回复...")

            # 更新轮次状态
            if progress_callback:
                all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                spoken = []
                unspoken = [n for n in all_names if n != arb_ai["name"]]
                round_status = f"第{round_count + 1}轮 | 💬 {arb_ai['name']} 正在发言 | 已发言{len(spoken)}({','.join(spoken) if spoken else '无'}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                progress_callback("round_status", "系统", round_status)

            # 军师发言：第一轮用文字发送，后续轮用txt文件（避免文字过长导致AI平台罢工）
            arb_force_file = (round_count > 0)
            arb_reply, err = await self._send_to(arb_ai, pages, arb_prompt, progress_callback,
                                                  force_file_upload=arb_force_file)
            if err is not None:
                if progress_callback:
                    progress_callback("error", arb_ai["name"], str(err))
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    break
                if progress_callback:
                    progress_callback("status", "系统",
                        f"⚠️ 军师回复失败（第{consecutive_failures}次），等待网络恢复后重试...")
                await asyncio.sleep(15)
                continue

            arb_reply = clean_text(arb_reply)
            arb_timestamp = datetime.datetime.now().strftime("%H:%M:%S")

            # 短回复重复检测（军师也适用）
            if self._check_short_reply(arb_ai["name"], arb_reply, ai_short_replies, ai_disabled, progress_callback):
                # 军师被剔除，直接停止讨论（不好中途换帅）
                if progress_callback:
                    progress_callback("status", "系统",
                        f"🛑 军师 {arb_ai['name']} 短回复重复被剔除，讨论直接停止（不好中途换帅）")
                self._is_running = False
                return {"history": history, "final_result": None,
                        "ended_by": f"军师 {arb_ai['name']} 短回复重复被剔除，讨论停止",
                        "rounds": round_count}

            ended, result = await self._check_end(
                arb_reply, arb_ai, history, done_set, done_state,
                ai_list, pages, progress_callback, round_count
            )
            if ended:
                return result

            arb_reply_clean = arb_reply
            if self.arbitration_signal and self.arbitration_signal in arb_reply_clean:
                arb_reply_clean = arb_reply_clean.replace(self.arbitration_signal, "").strip()

            current_round = round_count + 1
            round_replies = [{"name": arb_ai["name"], "content": arb_reply_clean, "timestamp": arb_timestamp, "round": current_round}]
            history.append(format_history_entry(arb_ai["name"], f"[第{current_round}轮] {arb_reply_clean}"))
            if progress_callback:
                progress_callback("ai_reply", arb_ai["name"], f"[第{current_round}轮] {arb_reply_clean}")
                # 更新轮次状态：军师已发言
                all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                spoken = [arb_ai["name"]]
                unspoken = [n for n in all_names if n != arb_ai["name"]]
                round_status = f"第{current_round}轮 | ✅ {arb_ai['name']} 已发言 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                progress_callback("round_status", "系统", round_status)
                progress_callback("status", "系统", f"✅ 第{current_round}轮：军师 {arb_ai['name']} 已发言")

            # Step 2: 谋士并行回复
            # 重新过滤 strategist_ais，排除在军师发言期间被用户剔除的AI
            strategist_ais = [a for a in strategist_ais if a["name"] not in self._removed_ais and a["name"] not in ai_disabled]
            if strategist_ais:
                ai_prompts = {}
                for ai in strategist_ais:
                    prompt = (
                        self._init_prefix(ai, initialized, ai_list)
                        + build_strategist_round_prompt(
                            my_name=ai["name"],
                            topic=user_message,
                            arbiter_name=arb_ai["name"],
                            arbiter_reply=arb_reply_clean,
                            prev_round_replies=prev_round_replies if prev_round_replies else None,
                            focal_points=focal_points,
                            round_num=round_count + 1,
                            end_signal=self.end_signal,
                        )
                    )
                    ai_prompts[ai["name"]] = prompt
                    if progress_callback:
                        progress_callback("user_prompt", ai["name"], prompt)

                if progress_callback:
                    ai_names = ", ".join(a["name"] for a in strategist_ais)
                    # 更新轮次状态：谋士正在并行回复
                    all_names = [a["name"] for a in ai_list if a["name"] not in ai_disabled and a["name"] not in self._removed_ais]
                    spoken = [arb_ai["name"]]
                    unspoken = [a["name"] for a in strategist_ais]
                    round_status = f"第{current_round}轮 | 💬 {ai_names} 正在回复 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(unspoken)}({','.join(unspoken) if unspoken else '无'})"
                    progress_callback("round_status", "系统", round_status)
                    progress_callback("status", "系统", f"第 {round_count + 1} 轮：{ai_names} 正在并行回复...")

                async def _send_and_receive_cont(ai: dict) -> tuple:
                    try:
                        reply, err = await self._send_to(ai, pages, ai_prompts[ai["name"]], progress_callback,
                                                          force_file_upload=True)
                        return (ai, reply, err)
                    except Exception as e:
                        return (ai, None, e)

                tasks = [asyncio.ensure_future(_send_and_receive_cont(ai)) for ai in strategist_ais]
                done_count = 0
                total = len(tasks)

                for future in asyncio.as_completed(tasks, timeout=soft_timeout):
                    done_count += 1
                    try:
                        ai, reply, err = await future
                        # 跳过在等待期间被用户剔除的AI
                        if ai["name"] in self._removed_ais:
                            log_info(f"[{ai['name']}] 已被用户剔除，跳过本次回复处理")
                            total -= 1
                            continue
                        if err is not None:
                            ai_name = ai["name"]
                            ai_fail_count[ai_name] = ai_fail_count.get(ai_name, 0) + 1
                            fail_count = ai_fail_count[ai_name]
                            # Bug6: 超时2次即自动剔除
                            if fail_count >= 2 and ai_name not in ai_disabled:
                                ai_disabled.add(ai_name)
                                self._removed_ais.add(ai_name)
                                self._removed_this_round[ai_name] = f"连续{fail_count}次超时/无响应，已自动剔除"
                                if progress_callback:
                                    progress_callback("status", "系统",
                                        f"🚫 {ai_name} 连续 {fail_count} 次超时/失败，已自动剔除议事厅")
                                log_warning(f"[{ai_name}] 连续失败 {fail_count} 次，已自动剔除")
                                # Bug6: 如果被剔除的是军师，直接停止讨论（不好中途换帅）
                                if ai_name == self.arbitrator:
                                    if progress_callback:
                                        progress_callback("status", "系统",
                                            f"🛑 军师 {ai_name} 超时被剔除，讨论直接停止（不好中途换帅）")
                                    self._is_running = False
                                    return {
                                        "history": history, "final_result": None,
                                        "ended_by": f"军师 {ai_name} 超时被剔除，讨论停止",
                                        "rounds": round_count,
                                    }
                            elif progress_callback:
                                progress_callback("error", ai["name"], str(err))
                            continue
                        # 回复成功，重置失败计数
                        ai_fail_count[ai["name"]] = 0
                        reply = clean_text(reply)
                        reply_ts = datetime.datetime.now().strftime("%H:%M:%S")

                        # 短回复重复检测：<=20字且与上次相同，重复2次自动剔除
                        if self._check_short_reply(ai["name"], reply, ai_short_replies, ai_disabled, progress_callback):
                            # 该AI被剔除，跳过本次处理
                            continue

                        ended, result = await self._check_end(
                            reply, ai, history, done_set, done_state,
                            ai_list, pages, progress_callback, round_count
                        )
                        if not ended:
                            reply_clean = reply
                            if self.arbitration_signal and self.arbitration_signal in reply_clean:
                                reply_clean = reply_clean.replace(self.arbitration_signal, "").strip()
                            round_replies.append({"name": ai["name"], "content": reply_clean, "timestamp": reply_ts, "round": current_round})
                            history.append(format_history_entry(ai["name"], f"[第{current_round}轮] {reply_clean}"))
                            if progress_callback:
                                progress_callback("ai_reply", ai["name"], f"[第{current_round}轮] {reply_clean}")
                                # 更新轮次状态：谋士已回复
                                spoken.append(ai["name"])
                                remaining_unspoken = [n for n in all_names if n not in spoken and n not in self._removed_ais]
                                round_status = f"第{current_round}轮 | ✅ {ai['name']} 已回复 | 已发言{len(spoken)}({','.join(spoken)}) 未发言{len(remaining_unspoken)}({','.join(remaining_unspoken) if remaining_unspoken else '无'})"
                                progress_callback("round_status", "系统", round_status)
                                progress_callback("status", "系统", f"✅ 第{current_round}轮：{ai['name']} 已回复 ({done_count}/{total})")
                        else:
                            for t in tasks:
                                if not t.done():
                                    t.cancel()
                            return result
                    except asyncio.TimeoutError:
                        if progress_callback:
                            # 找出未完成的AI名称
                            pending_ais = []
                            for t, ai in zip(tasks, strategist_ais):
                                if not t.done():
                                    pending_ais.append(ai["name"])
                            pending_names = ", ".join(pending_ais) if pending_ais else "未知AI"
                            remaining = total - done_count + 1
                            progress_callback("status", "系统", f"⏰ 软超时 {soft_timeout}s，{remaining} 个谋士跳过（{pending_names}）")
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        log_exception(f"追问模式处理谋士回复时异常", type(e), e, e.__traceback__)
                        if progress_callback:
                            progress_callback("error", "系统", f"处理回复异常: {e}")
                        continue

                for t in tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.sleep(0.5)

            # ----------------------------------------------------------
            # 主公密令处理（追问模式，累积队列策略）
            # ----------------------------------------------------------
            all_user_msgs = []
            while not self._user_input_queue.empty():
                try:
                    user_msg = self._user_input_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                all_user_msgs.append(user_msg)

            if all_user_msgs:
                if len(all_user_msgs) == 1:
                    combined_msg = all_user_msgs[0]
                else:
                    combined_msg = "\n\n".join(
                        f"密令{i+1}: {msg}" for i, msg in enumerate(all_user_msgs)
                    )
                log_info(f"追问模式处理{len(all_user_msgs)}条主公密令")

                if progress_callback:
                    progress_callback("user_message", "主公", combined_msg)

                # 构建AI剔除通知（如果有AI被剔除，密令中也附带通知）
                removal_notice_for_supplement = ""
                if self._removed_this_round:
                    removal_lines = [f"  - {name}：{reason}" for name, reason in self._removed_this_round.items()]
                    removal_notice_for_supplement = "\n".join(removal_lines)

                if arb_ai:
                    prompt_user = (
                        self._init_prefix(arb_ai, initialized, ai_list)
                        + build_supplement_prompt(combined_msg, arb_ai["name"],
                                                  end_signal=self.end_signal,
                                                  system_notice=removal_notice_for_supplement)
                    )
                    if progress_callback:
                        progress_callback("user_prompt", arb_ai["name"], prompt_user)
                    reply_u, err = await self._send_to(arb_ai, pages, prompt_user, progress_callback)
                    if err is None:
                        reply_u = clean_text(reply_u)
                        history.append(format_history_entry(arb_ai["name"], reply_u))
                        if progress_callback:
                            progress_callback("ai_reply", arb_ai["name"], reply_u)
                        ended, result = await self._check_end(
                            reply_u, arb_ai, history, done_set, done_state,
                            ai_list, pages, progress_callback, round_count
                        )
                        if ended:
                            return result

            prev_round_replies = round_replies
            if len(round_replies) < 2:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    break
                await asyncio.sleep(5)
                continue

            consecutive_failures = 0
            round_count += 1

        if self.arbitrator and self.arbitrator != "auto":
            if progress_callback:
                progress_callback("status", "系统",
                                  f"已达最大轮数 {self.max_rounds}，强制军师 {self.arbitrator} 结案结案...")
            try:
                final = await self.resolve_arbitrator(
                    self.arbitrator, history,
                    prev_round_replies[-1]["content"] if prev_round_replies else "",
                    ai_list, pages
                )
                final = f"{final}\n{self.arbitration_signal}"
            except Exception:
                final = None
            self._is_running = False
            self._save_discussion_state(ai_list, pages, history)
            return {
                "history": history,
                "final_result": final,
                "ended_by": f"达到最大轮数 {self.max_rounds}，军师强制结案结案",
                "rounds": round_count,
            }
        self._is_running = False
        self._save_discussion_state(ai_list, pages, history)
        return {
            "history": history,
            "final_result": None,
            "ended_by": f"达到最大轮数 {self.max_rounds}，未达成共识",
            "rounds": round_count,
        }

    # ------------------------------------------------------------------
    # 结案机制
    # ------------------------------------------------------------------

    async def resolve_arbitrator(self, arbitrator_name: str, history: list,
                                 last_done_reply: str, ai_list: list,
                                 pages: dict) -> str:
        """
        结案机制：根据仲裁模式产出最终方案。

        Args:
            arbitrator_name: 仲裁模式
                "auto" → 提取哨兵标记前的内容
                "lm_studio" → 发给本地模型汇总
                指定 AI 名称 → 将历史发给该 AI 汇总
            history: 完整讨论历史
            last_done_reply: 包含哨兵标记的最后一条回复
            ai_list: 参与讨论的 AI 配置列表
            pages: AI 名称 → 页面 的字典

        Returns:
            str: 最终方案文本
        """
        # auto 模式：提取哨兵标记前的内容作为最终方案
        if arbitrator_name == "auto":
            return extract_before_signal(last_done_reply, self.end_signal)

        # lm_studio 模式：发给本地模型汇总
        if arbitrator_name == "lm_studio":
            return await self._lm_studio_summarize(history)

        # 指定 AI 模式：先在 ai_list 中查找，再回退到全局 ai_platforms
        target_ai = None
        for ai in ai_list:
            if ai["name"] == arbitrator_name:
                target_ai = ai
                break
        if target_ai is None:
            for p in self.config.get("ai_platforms", []):
                if p["name"] == arbitrator_name:
                    target_ai = p
                    break

        if target_ai is None:
            # 找不到指定 AI，回退到 auto
            return extract_before_signal(last_done_reply, self.end_signal)

        # 获取目标 AI 的页面（优先复用 pages 字典，否则新建）
        target_page = pages.get(target_ai["name"])
        if target_page is None:
            try:
                target_page = await self.chrome.get_or_create_page(target_ai["url"])
                pages[target_ai["name"]] = target_page
            except Exception:
                return extract_before_signal(last_done_reply, self.end_signal)

        # 将完整对话历史发给指定 AI 汇总
        summary_prompt = build_summary_prompt(history)
        try:
            result = await self.chrome.send_and_wait(
                target_page, summary_prompt, target_ai, timeout=self.timeout
            )
            return clean_text(result)
        except Exception:
            return (f"指定AI汇总失败，回退为原始方案：\n\n"
                    f"{extract_before_signal(last_done_reply, self.end_signal)}")

    # ------------------------------------------------------------------
    # LM Studio 结案
    # ------------------------------------------------------------------

    async def _lm_studio_summarize(self, history: list) -> str:
        """
        使用 LM Studio 本地模型汇总讨论历史。

        支持流式输出。

        Returns:
            str: 汇总结果
        """
        lm = self.config.get("lm_studio", {})
        if not lm.get("enabled"):
            return "错误：LM Studio 未启用，无法进行结案汇总。"

        url = lm.get("url", "http://127.0.0.1:1234/v1")
        api_key = lm.get("api_key", "") or "not-needed"
        summary_prompt = build_summary_prompt(history)

        try:
            from openai import OpenAI
            import httpx

            # 创建不使用系统代理的 httpx 客户端，避免 Clash 等代理工具干扰本地连接
            http_client = httpx.Client(trust_env=False, timeout=120.0)
            client = OpenAI(base_url=url, api_key=api_key, http_client=http_client)

            # 尝试获取已加载的模型
            try:
                models = client.models.list()
                model_id = models.data[0].id if models.data else "default"
            except Exception:
                model_id = lm.get("summary_model", "default")

            # 流式输出
            stream = client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "你是讨论汇总助手，请根据讨论历史输出一份完整的、结构化的最终方案。",
                    },
                    {"role": "user", "content": summary_prompt},
                ],
                stream=True,
            )

            result_parts = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    result_parts.append(chunk.choices[0].delta.content)

            return "".join(result_parts).strip()

        except Exception as e:
            return f"LM Studio 结案失败: {e}\n\n请检查 LM Studio 是否已启动并加载模型。"
