"""
utils - 工具函数模块

提供文件读取、文本清洗、HTML转纯文本、哨兵标记检测等通用功能。
"""

import csv
import re
import io
import os
import sys
from html.parser import HTMLParser


def resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径（兼容 PyInstaller 打包和开发模式）。

    Args:
        relative_path: 相对路径（如 "logo_ui.png"）

    Returns:
        str: 绝对路径
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发模式
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


# ======================================================================
# 文件读取
# ======================================================================

def read_uploaded_file(uploaded_file) -> str:
    """
    读取 Streamlit UploadedFile，支持 .txt / .md / .csv。

    Args:
        uploaded_file: streamlit.runtime.uploaded_file_manager.UploadedFile

    Returns:
        str: 文件文本内容

    Raises:
        ValueError: 不支持的文件格式或读取失败
    """
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()
    try:
        raw = uploaded_file.read()
        # 尝试 UTF-8，回退到 GBK
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gbk", errors="replace")
    except Exception as e:
        raise ValueError(f"文件读取失败: {e}")

    if name.endswith(".csv"):
        return _read_csv_text(text)
    elif name.endswith((".txt", ".md")):
        return text.strip()
    else:
        raise ValueError(f"不支持的文件格式: {uploaded_file.name}（仅支持 .txt / .md / .csv）")


def _read_csv_text(text: str, max_rows: int = 50) -> str:
    """
    将 CSV 文本转换为可读的文本表格。

    Args:
        text: CSV 原始文本
        max_rows: 最多提取的行数

    Returns:
        str: 制表符分隔的文本表格
    """
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return ""
        # 限制行数，避免过长
        rows = rows[:max_rows]
        lines = ["\t".join(row) for row in rows]
        return "\n".join(lines)
    except Exception:
        # CSV 解析失败时回退为原始文本
        return text.strip()


# ======================================================================
# 文本清洗
# ======================================================================

class _HTMLStripper(HTMLParser):
    """轻量级 HTML 标签剥离器。"""

    def __init__(self):
        super().__init__()
        self._text_parts = []

    def handle_data(self, data):
        self._text_parts.append(data)

    def get_text(self) -> str:
        return "".join(self._text_parts)


def strip_html(html_string: str) -> str:
    """
    将 HTML 字符串转换为纯文本，去除所有标签。

    Args:
        html_string: 含 HTML 标签的字符串

    Returns:
        str: 纯文本
    """
    if not html_string:
        return ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(html_string)
    except Exception:
        # HTML 解析失败时用正则兜底
        clean = re.sub(r"<[^>]+>", "", html_string)
        return clean.strip()
    return stripper.get_text().strip()


def clean_text(text: str) -> str:
    """
    清洗 AI 回复文本：去除多余空白、HTML 残留、控制字符。

    注意：会保护哨兵标记（如 <已得出最终结果>）不被 strip_html 误删。

    Args:
        text: 原始回复文本

    Returns:
        str: 清洗后的文本
    """
    if not text:
        return ""

    # 保护哨兵标记：HTMLParser 会把 <已得出最终结果> 当作 HTML 标签删除
    # 用占位符替换，清洗后再恢复
    SENTINEL_PLACEHOLDER = "\u0001SENTINEL\u0001"
    sentinel_patterns = [
        "<已得出最终结果>",
        "<已达成共识>",
    ]
    protected_text = text
    for sp in sentinel_patterns:
        if sp in protected_text:
            protected_text = protected_text.replace(sp, SENTINEL_PLACEHOLDER)

    # 去除 HTML 标签
    result = strip_html(protected_text)

    # 过滤思考过程标记（DeepSeek/智谱清言的思考过程残留）
    thinking_patterns = [
        r"已思考（用时\s*\d+\s*秒）\s*",
        r"思考结束\s*",
        r"^ChatGLM\s*$",  # 智谱清言的思考过程标记
    ]
    for pattern in thinking_patterns:
        result = re.sub(pattern, "", result, flags=re.MULTILINE)

    # 去除控制字符（保留换行和制表符，但保留我们的占位符 \u0001）
    result = re.sub(r"[\x02-\x08\x0b\x0c\x0e-\x1f\x7f]", "", result)
    # 合并连续空行（超过2个换行压缩为2个）
    result = re.sub(r"\n{3,}", "\n\n", result)
    # 去除行首行尾多余空白
    result = "\n".join(line.rstrip() for line in result.split("\n"))

    # 恢复哨兵标记
    result = result.replace(SENTINEL_PLACEHOLDER, "<已得出最终结果>")

    return result.strip()


# ======================================================================
# 哨兵标记检测
# ======================================================================

def contains_end_signal(text: str, end_signal: str = "<已得出最终结果>") -> bool:
    """
    检测文本中是否包含哨兵标记。

    Args:
        text: 待检测文本
        end_signal: 哨兵标记字符串

    Returns:
        bool: 是否包含哨兵标记
    """
    if not text or not end_signal:
        return False
    return end_signal in text


def extract_before_signal(text: str, end_signal: str = "<已得出最终结果>") -> str:
    """
    提取哨兵标记之前的所有内容作为最终方案。

    Args:
        text: 包含哨兵标记的文本
        end_signal: 哨兵标记字符串

    Returns:
        str: 哨兵标记之前的文本（已清洗）
    """
    if not text:
        return ""
    if end_signal and end_signal in text:
        result = text.split(end_signal)[0]
    else:
        result = text
    return clean_text(result)


# ======================================================================
# 规则模板
# ======================================================================

def build_init_prompt(my_name: str, opponent_name: str,
                      opening_remarks: str = "",
                      arbitrator: str = "auto",
                      end_signal: str = "<End>",
                      arbitration_signal: str = "<结案>",
                      all_ai_names: list = None,
                      start_signal: str = "<ok>") -> str:
    """
    Phase 1: 点击"开始讨论"后，发给所有 AI 的初始化提示。
    包含开场白（用户可配置）+ 规则（自动生成，AI名称和标识动态读取）。
    不包含话题，话题在 Phase 2 单独发送。

    Args:
        my_name: 当前 AI 名称
        opponent_name: 对方 AI 名称（逗号分隔）
        opening_remarks: 开场白（用户可配置）
        arbitrator: 军师（"auto" 或 AI 名称）
        end_signal: 结束标识
        arbitration_signal: 结案标识
        all_ai_names: 所有参与AI的名称列表
        start_signal: 开始标识

    Returns:
        str: 初始化提示字符串
    """
    opening = f"{opening_remarks}\n\n" if opening_remarks else ""

    # 构建所有谋士名称列表
    if all_ai_names:
        members_str = "".join(f"【{n}】" for n in all_ai_names)
    else:
        members_str = f"【{my_name}】"

    # 军师名称
    arb_name = arbitrator if arbitrator and arbitrator != "auto" else "（未指定）"

    # 明确当前AI的角色
    is_arb = (my_name == arb_name)
    my_role = "军师" if is_arb else "谋士"
    role_desc = (
        "你是军师，负责统筹讨论、引导共识，并在所有谋士达成共识后结案整合最终方案"
        if is_arb else
        f"你是谋士，需要与其他谋士讨论，军师是【{arb_name}】"
    )

    return f"""{opening}【规则】
- 你是【{my_name}】，{role_desc}
- 本次军帐议事一共有谋士{members_str}
- 发起话题的是主公,所有AI需遵从主公的旨意
- 所有AI在多轮讨论,得出最终结论后,并标注结束标识(如{end_signal}),未得出最终结论前,还需讨论时,不要用结束标识,切记
- 在所有AI都发出结束语后,军师可以结案总结最终方案,并标注结案标识(如{arbitration_signal})
- 开始标识,结束标识,结案标识 必须标注,用于系统识别
- 当前开始标识为{start_signal}
- 当前结束标识为{end_signal}
- 当前结案标识为{arbitration_signal}
- 由于AI能力各不相同,如果有个别AI可能忘记发标语,由军师判定是否该继续等待
- 如果主公中途发密令,则只发给军师,军师不用回复主公,只是把密令需求纳入统一考量,在后续讨论中引导谋士一并考虑;如果已结案停止,则重新激活讨论,进行新一轮讨论结案

【重要】现在只是开场白阶段，主公还未提出讨论话题。请只回复{start_signal}表示你已明白规则，不要现在就开始讨论或给出任何方案。"""


def build_topic_prompt(topic: str) -> str:
    """
    Phase 2: 给第一个 AI 发送话题（用户视角）。
    用"用户："前缀，因为用户可以在讨论中多次插话加入新话题。

    Args:
        topic: 讨论话题

    Returns:
        str: 话题提示字符串
    """
    return f"主公：{topic}"


def build_followup_prompt(topic: str, first_ai_name: str, first_reply: str,
                          my_name: str, end_signal: str = "<End>") -> str:
    """
    Phase 3: 把话题 + 第一个 AI 的回复发给第二个 AI。

    Args:
        topic: 讨论话题
        first_ai_name: 第一个回复的 AI 名称
        first_reply: 第一个 AI 的回复内容
        my_name: 当前接收方的 AI 名称
        end_signal: 结束标记

    Returns:
        str: 跟进提示字符串
    """
    return f"""用户：{topic}
{first_ai_name}回复：{first_reply}

请{my_name}进行回应或补充。如果讨论已达成共识，请写出一份完整的、结构化的最终方案，并在最后一行单独加上 {end_signal}。"""


def build_round_prompt(my_name: str, opponent_name: str, last_reply: str,
                       end_signal: str = "<End>") -> str:
    """
    Phase 4: 后续轮次的提示（轮流对话）。

    Args:
        my_name: 当前 AI 名称
        opponent_name: 对方 AI 名称
        last_reply: 对方上一轮的回复内容
        end_signal: 结束标记

    Returns:
        str: 提示字符串
    """
    return f"""{opponent_name}回复：
{last_reply}

请{my_name}进行回应或补充。如果讨论已达成共识，请写出一份完整的、结构化的最终方案，并在最后一行单独加上 {end_signal}。"""


def build_user_input_prompt(user_msg: str, my_name: str,
                             opponent_name: str = "",
                             opponent_reply: str = "",
                             end_signal: str = "<End>") -> str:
    """
    用户插话时发给 AI 的提示。

    如果 opponent_reply 为空，说明是直接发给第一个 AI 的用户消息；
    否则说明是发给第二个 AI 的（包含第一个 AI 对用户消息的回复）。

    Args:
        user_msg: 用户输入的消息
        my_name: 当前 AI 名称
        opponent_name: 对方 AI 名称（可为空）
        opponent_reply: 对方 AI 对用户消息的回复（可为空）
        end_signal: 结束标记

    Returns:
        str: 用户插话提示字符串
    """
    if opponent_reply:
        return f"""主公补充：{user_msg}
{opponent_name}回复：{opponent_reply}

请{my_name}进行回应或补充。如果讨论已达成共识，请写出一份完整的、结构化的最终方案，并在最后一行单独加上 {end_signal}。"""
    else:
        return f"""主公补充：{user_msg}

请{my_name}进行回应或补充。如果讨论已达成共识，请写出一份完整的、结构化的最终方案，并在最后一行单独加上 {end_signal}。"""


def build_supplement_prompt(user_msg: str, arbitrator: str,
                            end_signal: str = "<End>",
                            system_notice: str = "") -> str:
    """
    讨论期间用户补充条件（主公密令），只发给军师。

    统一格式：
    【系统通知】（包含密令 + AI变动等）
    军师行动指令

    Args:
        user_msg: 用户补充的内容（密令）
        arbitrator: 军师名称
        end_signal: 结束标识
        system_notice: 其他系统通知（如AI变动通知）

    Returns:
        str: 补充条件提示字符串
    """
    parts = []
    sn_parts = []
    sn_parts.append(f"  - 主公密令：{user_msg}")
    if system_notice:
        sn_parts.append(system_notice)
    parts.append("【系统通知】\n" + "\n".join(sn_parts) + "\n")
    parts.append(
        f"\n请{arbitrator}作为军师，将以上密令纳入当前讨论，并在后续讨论中引导其他谋士一并考虑。"
        f"如果讨论已达成共识，请写出完整的结构化最终方案，并在最后一行单独加上 {end_signal}。"
    )
    return "\n".join(parts)


def build_summary_prompt(history: list) -> str:
    """
    构建要求 AI/LM Studio 汇总讨论历史的提示。

    Args:
        history: 讨论历史列表，每条为 "【AI名称】\\n内容"

    Returns:
        str: 汇总提示字符串
    """
    history_text = "\n\n".join(history)
    return f"""请根据以下讨论历史，汇总并输出一份完整的、结构化的最终方案：

{history_text}

请直接输出最终方案，无需重复讨论过程。"""


# ======================================================================
# 其他工具
# ======================================================================

def format_history_entry(ai_name: str, content: str) -> str:
    """格式化讨论历史条目。"""
    return f"【{ai_name}】\n{content}"


def truncate_text(text: str, max_length: int = 5000) -> str:
    """截断过长文本，附加省略提示。"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n\n...(内容过长，已截断)"


# ======================================================================
# 并行讨论模式提示构建
# ======================================================================

def build_parallel_round_prompt(
    my_name: str,
    topic: str,
    prev_round_replies: list,  # [{"name": "DeepSeek", "content": "..."}, ...]
    focal_points: str = "",
    end_signal: str = "<End>",
    arbitration_signal: str = "<结案>",
    is_arbitrator: bool = False,
) -> str:
    """
    并行模式：每轮所有AI同时收到上一轮所有人的回复，同时回复。

    Args:
        my_name: 当前AI名称
        topic: 原始讨论话题
        prev_round_replies: 上一轮所有AI的回复列表
        focal_points: 军师提炼的分歧焦点（可为空）
        end_signal: 结束标记
        arbitration_signal: 结案标记
        is_arbitrator: 当前AI是否为军师
    """
    # 构建上一轮回复摘要
    replies_text = ""
    for r in prev_round_replies:
        replies_text += f"【{r['name']}】说：\n{r['content']}\n\n"

    parts = []
    parts.append(f"【讨论话题】\n{topic}\n")

    if focal_points:
        parts.append(f"【分歧焦点】\n{focal_points}\n")

    parts.append(f"【上一轮讨论】\n{replies_text}")

    if is_arbitrator:
        parts.append(
            f"请{my_name}（军师）进行回应。作为军师，你可以：\n"
            f"1. 针对分歧点进行仲裁和整合\n"
            f"2. 提出新的方向引导讨论\n"
            f"3. 如果讨论已充分，写出完整结构化最终方案，并在最后一行加上 {arbitration_signal}\n"
            f"4. 如果认为还需讨论，正常发表观点即可"
        )
    else:
        parts.append(
            f"请{my_name}进行回应。你可以：\n"
            f"1. 针对其他人的观点进行质疑、补充或支持\n"
            f"2. 提出新的论点或视角\n"
            f"3. 如果认为讨论已达成共识，请说出你的结论，并在最后一行加上 {end_signal}"
        )

    return "\n".join(parts)


def build_first_round_prompt(
    my_name: str,
    topic: str,
    end_signal: str = "<End>",
) -> str:
    """
    并行模式第一轮：所有AI同时收到话题，同时回复。
    """
    return f"""【讨论话题】
{topic}

请{my_name}发表你的初始观点和分析。"""


def extract_focal_points(replies: list) -> str:
    """
    Python端规则引擎：从回复列表中提取分歧关键句（不调用AI）。

    规则：
    - 包含对比连词（"但是"、"然而"、"相比之下"、"不过"）的句子
    - 包含条件假设（"如果...那么..."）的句子
    - 包含明确否定（"不对"、"不行"、"不同意"、"反对"）的句子

    Returns:
        str: 分歧焦点列表，无分歧则返回空串
    """
    if not replies:
        return ""

    # 分歧关键词
    conflict_patterns = [
        "但是", "然而", "相比之下", "不过", "与此相反",
        "不对", "不行", "不同意", "反对", "质疑",
        "如果", "假设", "万一",
        "认为不行", "不可取", "存疑",
    ]

    focal_lines = []
    for r in replies:
        name = r.get("name", "")
        content = r.get("content", "")
        # 按句号/问号/感叹号分割
        import re
        sentences = re.split(r'[。！？\n.!?]', content)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 5:
                continue
            for pattern in conflict_patterns:
                if pattern in sent:
                    # 避免重复
                    line = f"- [{name}] {sent}"
                    if line not in focal_lines:
                        focal_lines.append(line)
                    break

    if not focal_lines:
        return ""

    # 限制最多10条，避免过长
    return "\n".join(focal_lines[:10])


# ======================================================================
# 军师主导模式 prompt 构建
# ======================================================================

def build_arbiter_first_prompt(
    my_name: str,
    topic: str,
    all_ai_names: list,
    end_signal: str = "<End>",
    arbitration_signal: str = "<结案>",
    system_notice: str = "",
) -> str:
    """军师第一轮：看到话题，发表初始分析，为讨论定下方向。

    统一格式：
    【系统通知】（如有，包含AI变动等）
    军师行动指令（含讨论话题）
    """
    members_str = "".join(f"【{n}】" for n in all_ai_names if n != my_name)
    parts = []
    if system_notice:
        parts.append(system_notice)
    parts.append(f"【第1轮 - 军师发言】\n")
    parts.append(f"【讨论话题】\n{topic}\n")
    parts.append(f"【参与谋士】{members_str}\n")
    parts.append(
        f"请{my_name}（军师）发表初始观点和分析，为讨论定下方向。\n"
        f"你的发言将被发送给所有谋士，他们会基于你的分析展开讨论。\n"
        f"请给出你的核心观点和需要重点讨论的方向，不需要给出最终方案。"
    )
    return "\n".join(parts)


def build_arbiter_round_prompt(
    my_name: str,
    topic: str,
    prev_round_replies: list,
    focal_points: str = "",
    round_num: int = 1,
    end_signal: str = "<End>",
    arbitration_signal: str = "<结案>",
    system_notice: str = "",
) -> str:
    """军师后续轮：收到上一轮所有谋士的回复，给出方向或结案。

    统一格式：
    【系统通知】（如有，包含AI变动等）
    【讨论回复】（其他AI的回复）
    军师行动指令
    """
    replies_text = ""
    for r in prev_round_replies:
        ts = r.get("timestamp", "")
        r_num = r.get("round", round_num - 1)
        replies_text += f"  {r['name']}（第{r_num}轮 {ts}）：\n{r['content']}\n\n"

    parts = []
    if system_notice:
        parts.append(system_notice)
    parts.append(f"【第{round_num}轮 - 军师发言】\n")
    parts.append(f"【讨论回复】\n{replies_text}")
    if focal_points:
        parts.append(f"【分歧焦点】\n{focal_points}\n")
    parts.append(
        f"请{my_name}（军师）进行回应。你可以：\n"
        f"1. 针对分歧点进行仲裁和整合\n"
        f"2. 提出新的方向引导讨论\n"
        f"3. 如果讨论已充分（至少10轮以上），写出完整结构化最终方案，并在最后一行加上 {arbitration_signal}\n"
        f"4. 如果认为还需讨论，正常发表观点即可"
    )
    return "\n".join(parts)


def build_strategist_round_prompt(
    my_name: str,
    topic: str,
    arbiter_name: str,
    arbiter_reply: str,
    prev_round_replies: list = None,
    focal_points: str = "",
    round_num: int = 1,
    end_signal: str = "<End>",
) -> str:
    """谋士轮：看到军师的发言（+上一轮讨论），发表看法。"""
    parts = [f"【第{round_num}轮 - 谋士发言】\n"]
    # 第一轮包含话题，后续轮不重复（AI通过浏览器页面能看到第一轮话题）
    if round_num <= 1:
        parts.append(f"【讨论话题】\n{topic}\n")
    parts.append(f"【军师{arbiter_name}第{round_num}轮发言】\n{arbiter_reply}\n")

    if prev_round_replies:
        other_replies = ""
        for r in prev_round_replies:
            if r["name"] != my_name:  # 不重复显示自己的回复
                ts = r.get("timestamp", "")
                r_num = r.get("round", round_num - 1)
                other_replies += f"【{r['name']}】(第{r_num}轮 {ts}) 说：\n{r['content']}\n\n"
        if other_replies:
            parts.append(f"【上一轮（第{round_num - 1}轮）其他人的讨论】\n{other_replies}")

    if focal_points:
        parts.append(f"【分歧焦点】\n{focal_points}\n")

    parts.append(
        f"请{my_name}（谋士）进行回应。你可以：\n"
        f"1. 针对军师和其他人的观点进行质疑、补充或支持\n"
        f"2. 提出新的论点或视角\n"
        f"3. 如果认为讨论已达成共识，请说出你的结论，并在最后一行加上 {end_signal}"
    )
    return "\n".join(parts)

