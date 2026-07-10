"""
ConfigManager - 配置文件管理模块

负责 config.json 的加载、保存、验证和默认配置生成。
配置文件路径：~/.polysage/config.json
"""

import json
import os
from pathlib import Path

try:
    from logger import log_info
except ImportError:
    def log_info(msg): print(msg)


# 配置目录与文件路径
CONFIG_DIR = Path.home() / ".polysage"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 默认配置版本号（每次修改 DEFAULT_CONFIG 中的选择器/思考模式时递增）
# 用于判断用户配置是否需要同步更新默认平台的配置
DEFAULT_CONFIG_VERSION = 3

# 默认配置
DEFAULT_CONFIG = {
    "config_version": DEFAULT_CONFIG_VERSION,
    "chrome": {
        "debug_port": 9222,
        "user_data_dir": str(CONFIG_DIR / "chrome-data"),
        "browser_mode": "built-in",  # "built-in"=内置浏览器, "system"=谷歌浏览器
    },
    "discussion": {
        "end_signal": "<End>",
        "start_signal": "<ok>",
        "arbitration_signal": "<结案>",
        "max_rounds": 20,
        "timeout_seconds": 300,
        "default_active_ais": ["DeepSeek", "智谱清言"],
        "opening_remarks": "你正在参与一场多AI群聊协作。\n发起话题的是主公，你需遵从主公的旨意。\n请等待主公提出复杂议题（如项目架构、创作大纲等），\n需要你与其他AI展开深度推演：质疑细节、补充边界、提供替代方案。\n请分轮次讨论，不急于给出最终结论。当多方确认讨论充分后，再整合为结构化方案。",
    },
    "lm_studio": {
        "enabled": False,
        "url": "http://127.0.0.1:1234/v1",
        "display_name": "MyAi",
        "api_key": "",
    },
    "ai_platforms": [
        {
            "name": "DeepSeek",
            "url": "https://chat.deepseek.com/",
            "enabled": True,
            "is_arbitrator": True,
            "selectors": {
                "input_textarea": "textarea",
                "send_button": "div[class*='input'] div[role='button']:last-child",
                "send_button_selectors": [
                    "div.enter.is-main-chat",
                    "div.enter-icon-container:not(.empty)",
                    "div[class*='enter-icon-container']:not(.empty)",
                    "img.enter_icon",
                    "div[class*='input'] div[role='button']:last-child",
                    "div[class*='send']",
                    "button[class*='send']",
                    "button[aria-label*='发送']",
                ],
                "stop_button": "div[class*='answer'] div[class*='stop']",
                "response_container": "div.message-content",
                "last_response": "div.message-content:not([class*='think']):last-of-type",
                "logged_in_selector": "div[class*='avatar'], img[class*='avatar']",
                "logged_out_selector": "button:has-text('登录'), a:has-text('登录')",
                "auth_storage_keys": ["userToken", "token", "userInfo"],
            },
            "thinking_mode": {
                # DeepSeek flash 模式已足够强大，不需要思考模式
                "enabled": False,
            },
        },
        {
            "name": "智谱清言",
            "url": "https://chatglm.cn/",
            "enabled": True,
            "is_arbitrator": False,
            "selectors": {
                "input_textarea": "textarea",
                "send_button": "div[class*='send'], div[class*='chat-input-send'], button[aria-label*='发送'], div.enter-icon-container",
                "send_button_selectors": [
                    "div.enter-icon-container:not(.empty)",
                    "div.enter.is-main-chat",
                    "button[aria-label*='发送']",
                    "div[aria-label*='发送']",
                    "div.chat-input-footer div[class*='icon']:not([class*='stop'])",
                ],
                "stop_button": "div[class*='stop'], button:has-text('停止')",
                "response_container": "div[class*='message']",
                "last_response": "div[class*='markdown']:not([class*='think']):last-of-type",
                "logged_in_selector": "div[class*='avatar'], img[class*='avatar']",
                "logged_out_selector": "button:has-text('登录'), a:has-text('登录')",
                "auth_storage_keys": ["chatglm_token", "token", "user"],
            },
            "thinking_mode": {
                "enabled": True,
                # 检测配置（只读检测，不操作）
                "detect": {
                    "type": "dropdown",
                    "label_selector": "span.think-label",
                    "label_text": "深度",
                },
                # 启用步骤（按顺序执行，支持多步操作）
                "enable_steps": [
                    {"action": "click", "selector": "div.think-mode-trigger"},
                    {"action": "wait", "ms": 1000},
                    {"action": "click_text", "text": "深度", "selector": "span.item-name"},
                    {"action": "wait", "ms": 800},
                ],
            },
        },
        {
            "name": "通义千问",
            "url": "https://www.qianwen.com/",
            "enabled": True,
            "is_arbitrator": False,
            "selectors": {
                "input_textarea": "div[contenteditable='true'][role='textbox'], textarea",
                "send_button": "button[aria-label='发送'], button:has-text('发送')",
                "send_button_selectors": ["button[aria-label=\"发送\"]", "button:has-text(\"发送\")", "div[class*=\"send\"]", "button[class*=\"send\"]"],
                "stop_button": "button[class*='stop'], button[aria-label='停止']",
                "response_container": "div[class*='message'], div[class*='conversation']",
                "last_response": "div[class*='markdown']:not([class*='think']):not([class*='reasoning']):last-of-type, div[class*='bubble']:not([class*='think']):last-of-type",
                "logged_in_selector": "div[class*='avatar'], img[class*='avatar'], div[class*='user-info']",
                "logged_out_selector": "button[class*='black-button']:has-text('登录'), button:has-text('登录')",
                "auth_storage_keys": ["token", "userToken", "userInfo", "login_aliyunid_token"],
            },
            "thinking_mode": {
                "enabled": True,
                "detect": {
                    "type": "toggle",
                    "selector": "button[aria-label='思考']",
                    "label_text": "思考",
                    "active_attr": "aria-pressed",
                    "active_value": "true",
                },
                "enable_steps": [
                    {"action": "click", "selector": "button[aria-label='思考']"},
                    {"action": "wait", "ms": 800},
                ],
            },
        },
        {
            "name": "MiniMax",
            "url": "https://agent.minimaxi.com/",
            "enabled": True,
            "is_arbitrator": False,
            "selectors": {
                "input_textarea": "div[data-testid='message-textarea'], div[contenteditable='true'].tiptap, textarea, div[contenteditable='true']",
                "send_button": "div[data-testid='send-button'], button[data-testid='send-button'], div[class*='send'], button[class*='send']",
                "send_button_selectors": ["div[data-testid=\"send-button\"]", "button[data-testid=\"send-button\"]", "div[class*=\"send\"]", "button[class*=\"send\"]"],
                "stop_button": "button:has-text('停止'), div[class*='stop'], button[class*='stop']",
                "response_container": "div[class*='message'], div[class*='conversation'], div[class*='chat'], div[class*='bubble'], div[class*='reply'], div[class*='answer'], div[class*='response'], div[class*='content']:not([class*='input'])",
                "last_response": "div[class*='markdown']:not([class*='think']):not([class*='reasoning']):last-of-type, div[class*='message-content']:not([class*='think']):last-of-type, div[class*='bubble']:not([class*='think']):last-of-type, div[class*='reply']:not([class*='think']):last-of-type, div[class*='answer']:not([class*='think']):last-of-type, div.semi-modal-content, div[class*='prose']:not([class*='think']):last-of-type",
                "logged_in_selector": "div[class*='avatar'], img[class*='avatar']",
                "logged_out_selector": "button:has-text('登录'), a:has-text('登录')",
                "auth_storage_keys": ["token", "userToken", "userInfo", "sessionToken"],
            },
            "thinking_mode": {
                "enabled": True,
                "detect": {
                    "type": "toggle",
                    "selector": "button[data-testid='model-thinking-trigger-toggle']",
                    "label_text": "思考",
                    "active_attr": "aria-checked",
                    "active_value": "true",
                },
                "enable_steps": [
                    {"action": "click", "selector": "button[data-testid='model-thinking-trigger-toggle']"},
                    {"action": "wait", "ms": 800},
                ],
            },
        },
        {
            "name": "Kimi",
            "url": "https://www.kimi.com/",
            "enabled": True,
            "is_arbitrator": False,
            "selectors": {
                "input_textarea": "div.chat-input-editor[contenteditable='true'], div[contenteditable='true'][role='textbox'], textarea",
                "send_button": "div.send-button-container, div[class*='send-button']",
                "send_button_selectors": ["div.send-button-container", "div[class*=\"send-button\"]", "div[class*=\"send\"]", "button[class*=\"send\"]"],
                "stop_button": "button:has-text('停止'), div[class*='stop']",
                "response_container": "div[class*='message'], div[class*='conversation'], section[class*='chat']",
                "last_response": "div[class*='markdown']:not([class*='think']):not([class*='reasoning']):last-of-type, div[class*='message-content']:not([class*='think']):last-of-type, div[class*='bubble']:not([class*='think']):last-of-type",
                "logged_in_selector": "div[class*='avatar'], img[class*='avatar']",
                "logged_out_selector": "button:has-text('登录'), a:has-text('登录')",
                "auth_storage_keys": ["token", "userToken", "userInfo", "access_token"],
            },
            "thinking_mode": {
                "enabled": True,
                "detect": {
                    "type": "dropdown",
                    "label_selector": "div.model-name span.name",
                    "label_text": "思考",
                },
                "enable_steps": [
                    {"action": "click", "selector": "div.current-model, div.model-name"},
                    {"action": "wait", "ms": 1200},
                    {"action": "click_text", "text": "思考",
                     "selector": "div[class*='dropdown'] div[class*='item'], div[class*='menu-item'], li[class*='item'], div[class*='model-item'], [role='option'], [role='menuitem'], div[class*='select'] div[class*='option']"},
                    {"action": "wait", "ms": 800},
                ],
            },
        },
    ],
    "selected_ais": [],
}


class ConfigManager:
    """配置管理器：加载、保存、验证 config.json"""

    def __init__(self, config_path: str = None):
        """
        初始化配置管理器。

        Args:
            config_path: 自定义配置文件路径，默认为 ~/.polysage/config.json
        """
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self.config = None
        self.load()

    # ------------------------------------------------------------------
    # 加载与保存
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """
        加载配置文件。若文件不存在则生成默认配置。
        若文件存在但格式不完整，自动补全缺失字段。

        Returns:
            dict: 配置字典
        """
        if not self.config_path.exists():
            self.config = self._deep_copy(DEFAULT_CONFIG)
            self.save()
            return self.config

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            # 合并默认配置，补全缺失字段
            self.config = self._merge_config(self._deep_copy(DEFAULT_CONFIG), loaded)
            # 迁移旧配置：将旧的结束标记和开场白更新为新的默认值
            self._migrate_legacy_config()
            # 自动启用默认平台（DeepSeek 和 智谱清言）
            self._ensure_default_platforms_enabled()
            return self.config
        except (json.JSONDecodeError, IOError) as e:
            print(f"[ConfigManager] 配置文件读取失败: {e}，将使用默认配置。")
            self.config = self._deep_copy(DEFAULT_CONFIG)
            self.save()
            return self.config

    def save(self) -> bool:
        """
        将当前配置写入 config.json。

        Returns:
            bool: 保存是否成功
        """
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"[ConfigManager] 配置文件保存失败: {e}")
            return False

    def reload(self) -> dict:
        """重新加载配置文件。"""
        return self.load()

    # ------------------------------------------------------------------
    # 配置访问
    # ------------------------------------------------------------------

    def get(self, key: str, default=None):
        """
        获取配置项。

        Args:
            key: 支持点号分隔的多级键，如 "chrome.debug_port"
            default: 键不存在时的默认值
        """
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value):
        """
        设置配置项。

        Args:
            key: 支持点号分隔的多级键
            value: 要设置的值
        """
        keys = key.split(".")
        d = self.config
        for k in keys[:-1]:
            if k not in d or not isinstance(d[k], dict):
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    # ------------------------------------------------------------------
    # AI 平台管理
    # ------------------------------------------------------------------

    def get_ai_platforms(self) -> list:
        """获取所有 AI 平台列表。"""
        return self.config.get("ai_platforms", [])

    def get_enabled_platforms(self) -> list:
        """获取所有已启用的 AI 平台。"""
        return [p for p in self.get_ai_platforms() if p.get("enabled", False)]

    def get_platform_by_name(self, name: str) -> dict:
        """根据名称获取 AI 平台配置。"""
        for p in self.get_ai_platforms():
            if p["name"] == name:
                return p
        return None

    def add_platform(self, platform: dict) -> bool:
        """
        添加 AI 平台。

        Args:
            platform: 平台配置字典，需包含 name、url、selectors
        """
        if not platform.get("name"):
            return False
        # 检查重名
        existing = self.get_platform_by_name(platform["name"])
        if existing is not None:
            return False
        platform.setdefault("enabled", False)
        platform.setdefault("selectors", {})
        self.config["ai_platforms"].append(platform)
        return self.save()

    def update_platform(self, name: str, platform: dict) -> bool:
        """
        更新 AI 平台配置。

        Args:
            name: 原平台名称
            platform: 新的平台配置字典
        """
        for i, p in enumerate(self.config["ai_platforms"]):
            if p["name"] == name:
                self.config["ai_platforms"][i] = platform
                return self.save()
        return False

    def delete_platform(self, name: str) -> bool:
        """删除 AI 平台。"""
        original_len = len(self.config["ai_platforms"])
        self.config["ai_platforms"] = [
            p for p in self.config["ai_platforms"] if p["name"] != name
        ]
        if len(self.config["ai_platforms"]) < original_len:
            return self.save()
        return False

    def set_platform_enabled(self, name: str, enabled: bool) -> bool:
        """启用/禁用 AI 平台。"""
        for p in self.config["ai_platforms"]:
            if p["name"] == name:
                p["enabled"] = enabled
                return self.save()
        return False

    # ------------------------------------------------------------------
    # 验证
    # ------------------------------------------------------------------

    def validate(self) -> list:
        """
        验证当前配置的完整性。

        Returns:
            list: 错误信息列表，空列表表示配置有效
        """
        errors = []

        # Chrome 配置
        chrome = self.config.get("chrome", {})
        if not chrome.get("debug_port"):
            errors.append("chrome.debug_port 未配置")
        if not chrome.get("user_data_dir"):
            errors.append("chrome.user_data_dir 未配置")

        # 讨论配置
        discussion = self.config.get("discussion", {})
        if not discussion.get("end_signal"):
            errors.append("discussion.end_signal 未配置")
        if not isinstance(discussion.get("max_rounds"), int) or discussion.get("max_rounds", 0) <= 0:
            errors.append("discussion.max_rounds 必须为正整数")
        if not isinstance(discussion.get("timeout_seconds"), int) or discussion.get("timeout_seconds", 0) <= 0:
            errors.append("discussion.timeout_seconds 必须为正整数")

        # AI 平台
        for i, p in enumerate(self.config.get("ai_platforms", [])):
            if not p.get("name"):
                errors.append(f"ai_platforms[{i}].name 未配置")
            if not p.get("url"):
                errors.append(f"ai_platforms[{i}].url 未配置")
            selectors = p.get("selectors", {})
            if not selectors.get("input_textarea"):
                errors.append(f"ai_platforms[{i}].selectors.input_textarea 未配置")
            if not selectors.get("send_button"):
                errors.append(f"ai_platforms[{i}].selectors.send_button 未配置")

        # LM Studio（启用时才校验 URL）
        lm = self.config.get("lm_studio", {})
        if lm.get("enabled") and not lm.get("url"):
            errors.append("lm_studio.url 未配置（LM Studio 已启用）")

        return errors

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_copy(obj):
        """深拷贝（不依赖 copy 模块，处理 dict/list）。"""
        if isinstance(obj, dict):
            return {k: ConfigManager._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [ConfigManager._deep_copy(v) for v in obj]
        return obj

    def _ensure_default_platforms_enabled(self):
        """确保默认平台配置完整且为最新版本。

        策略：
        - 首次加载（无 config_version）或 config_version 低于 DEFAULT_CONFIG_VERSION：
          → 同步默认平台的选择器和思考模式为最新版本（用户自定义的会被覆盖）
        - config_version 等于 DEFAULT_CONFIG_VERSION：
          → 不覆盖用户已修改的选择器和思考模式，仅自动启用默认平台
        - 用户手动添加的自定义平台：永远不覆盖
        """
        # 所有默认平台都自动启用
        default_names = {"DeepSeek", "智谱清言", "通义千问", "MiniMax", "Kimi"}
        # 从 DEFAULT_CONFIG 获取最新配置（含选择器和思考模式）
        default_platforms = {p["name"]: p for p in DEFAULT_CONFIG.get("ai_platforms", [])}
        platforms = self.config.get("ai_platforms", [])
        changed = False

        # 判断是否需要同步默认平台配置
        user_version = self.config.get("config_version", 0)
        need_sync = user_version < DEFAULT_CONFIG_VERSION

        if need_sync:
            log_info(f"配置版本 {user_version} < {DEFAULT_CONFIG_VERSION}，同步默认平台配置")

        # 更新已有平台的选择器和思考模式配置
        existing_names = set()
        for p in platforms:
            name = p.get("name")
            existing_names.add(name)
            # 启用默认平台
            if name in default_names and not p.get("enabled", False):
                p["enabled"] = True
                changed = True
            # 仅在需要同步时更新选择器和思考模式为最新版本
            if name in default_platforms and need_sync:
                latest = default_platforms[name]
                # 同步 URL（确保地址为最新）
                if p.get("url") != latest.get("url"):
                    p["url"] = latest.get("url", "")
                    changed = True
                if p.get("selectors") != latest.get("selectors"):
                    p["selectors"] = dict(latest.get("selectors", {}))
                    changed = True
                # 同步思考模式配置
                if p.get("thinking_mode") != latest.get("thinking_mode"):
                    p["thinking_mode"] = dict(latest.get("thinking_mode", {}))
                    changed = True

        # 自动补全配置中缺失的默认平台（如新增的千问）
        for name, default_p in default_platforms.items():
            if name not in existing_names:
                platforms.append(dict(default_p))
                changed = True

        # 更新配置版本号
        if need_sync:
            self.config["config_version"] = DEFAULT_CONFIG_VERSION
            changed = True

        if changed:
            self.save()

    def _migrate_legacy_config(self):
        """迁移旧配置：将旧的结束标记和开场白更新为新的默认值。"""
        disc = self.config.get("discussion", {})
        changed = False
        # 旧的结束标记 → 新的 <End>
        if disc.get("end_signal") == "<已得出最终结果>":
            disc["end_signal"] = "<End>"
            changed = True
        # 旧的开场白 → 新的开场白
        old_opening = "你好，你正在参与一场协作讨论。"
        if disc.get("opening_remarks", "").startswith(old_opening):
            disc["opening_remarks"] = DEFAULT_CONFIG["discussion"]["opening_remarks"]
            changed = True
        # 超时时间：如果还是旧的120秒或600秒，更新为300秒
        if disc.get("timeout_seconds") in (120, 600):
            disc["timeout_seconds"] = 300
            changed = True
        # 讨论轮数：如果还是旧的50轮，恢复为默认20轮
        if disc.get("max_rounds") == 50:
            disc["max_rounds"] = 20
            changed = True
        # 结案标识：如果未配置或还是旧的<拍板>，设为默认 <结案>
        if not disc.get("arbitration_signal") or disc.get("arbitration_signal") == "<拍板>":
            disc["arbitration_signal"] = "<结案>"
            changed = True
        # 最少讨论轮数：从旧的10降为3
        if disc.get("min_rounds_before_arbitration", 3) == 10:
            disc["min_rounds_before_arbitration"] = 3
            changed = True
        if changed:
            self.config["discussion"] = disc
            self.save()

    @staticmethod
    def _merge_config(base: dict, override: dict) -> dict:
        """
        递归合并配置：以 base 为默认值，用 override 覆盖。
        仅对 dict 递归合并；list 和标量直接覆盖。
        """
        result = ConfigManager._deep_copy(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = ConfigManager._merge_config(result[k], v)
            else:
                result[k] = ConfigManager._deep_copy(v)
        return result
