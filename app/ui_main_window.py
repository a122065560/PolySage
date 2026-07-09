"""
ui_main_window - PyQt6 主窗口及组件布局

包含：
- MainWindow：主窗口，左右分栏布局
- 左侧栏：AI 平台列表 + Chrome 控制
- 右侧主区域：HostedModeTab（托管模式，单一模式）
- SettingsDialog：设置弹窗（AI 平台管理 / LM Studio / 讨论参数）
- 所有异步槽函数使用 async def，配合 qasync 不阻塞 UI
"""

import asyncio
import json
import os

from ui_styles import GLOBAL_QSS, ACCENT, TEXT_SECONDARY, TEXT_PRIMARY, SUCCESS, BG_WINDOW
from ui_flowlayout import FlowLayout

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTextEdit,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QDialog,
    QFormLayout,
    QSpinBox,
    QCheckBox,
    QGroupBox,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QFrame,
    QInputDialog,
    QGridLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QTimer
from PyQt6.QtGui import QFont, QAction, QPixmap, QIcon


from config_manager import ConfigManager
from browser import ChromeManager
from core import HostedMode
from utils import read_uploaded_file, clean_text, resource_path
from ui_widgets import ChatStream, AIPlatformItem
from ui_worker import WorkerThread
from logger import (
    delete_all_logs, get_log_dir, log_info, log_error, log_warning, log_exception,
    get_date_dirs, get_files_by_date, get_total_size, delete_file,
    log_ui, COMPONENT_UI, COMPONENT_BRAIN
)


# ======================================================================
# 设置弹窗
# ======================================================================

class SettingsDialog(QDialog):
    """设置弹窗：AI 平台管理 / LM Studio / 讨论参数 / 开场白 / 日志管理"""

    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.setWindowTitle("设置")
        self.setMinimumWidth(1100)
        self.setMinimumHeight(640)
        self.resize(1200, 700)
        # 应用全局样式表到弹窗
        from ui_styles import GLOBAL_QSS
        self.setStyleSheet(GLOBAL_QSS)
        self._build_ui()
        # 打开时自动刷新日志列表
        self._refresh_log_dates()
        self._refresh_log_files()
        self._refresh_log_info()

    def _show_toast(self, message: str, duration: int = 2500):
        """在设置弹窗中显示简短提示（使用状态栏式标签）。"""
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QLabel
        if not hasattr(self, '_toast_label') or self._toast_label is None:
            self._toast_label = QLabel(self)
            self._toast_label.setStyleSheet(
                "background-color: rgba(30, 30, 30, 0.95); color: #FFFFFF; "
                "padding: 8px 16px; border-radius: 8px; font-size: 13px;"
            )
            self._toast_label.setAlignment(Qt.AlignCenter)
            self._toast_label.hide()
        self._toast_label.setText(message)
        self._toast_label.adjustSize()
        # 居中显示在弹窗底部
        x = (self.width() - self._toast_label.width()) // 2
        y = self.height() - self._toast_label.height() - 20
        self._toast_label.move(x, y)
        self._toast_label.raise_()
        self._toast_label.show()
        QTimer.singleShot(duration, self._toast_label.hide)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 恢复默认小按钮样式 - 紧凑，与标题同高
        RESET_BTN_STYLE = """
            QPushButton {
                min-height: 18px;
                max-height: 18px;
                padding: 0px 8px;
                font-size: 11px;
                color: #86868B;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
            }
            QPushButton:hover {
                color: #007AFF;
                border-color: #007AFF;
                background-color: #E8F2FF;
            }
        """

        def make_group(title: str, reset_callback=None):
            """创建带自定义标题行的 GroupBox，恢复默认按钮放在标题行右侧。"""
            group = QGroupBox("")
            group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #E5E5EA;
                    border-radius: 8px;
                    margin-top: 0px;
                    padding: 4px 8px 8px 8px;
                    font-weight: 600;
                    font-size: 14px;
                }
            """)
            # 自定义标题行：标题文字 + 恢复默认按钮
            title_bar = QWidget()
            title_bar.setStyleSheet("background: transparent;")
            title_bar_layout = QHBoxLayout(title_bar)
            title_bar_layout.setContentsMargins(4, 6, 4, 2)
            title_bar_layout.setSpacing(6)

            title_label = QLabel(title)
            title_label.setStyleSheet("font-weight: 600; font-size: 13px; color: #1D1D1F; background: transparent;")
            title_bar_layout.addWidget(title_label)

            if reset_callback:
                title_bar_layout.addStretch()
                reset_btn = QPushButton("恢复默认")
                reset_btn.setStyleSheet(RESET_BTN_STYLE)
                reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                reset_btn.clicked.connect(reset_callback)
                title_bar_layout.addWidget(reset_btn)

            group._title_bar = title_bar
            return group

        # 3列网格布局，2行
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # ==================== 第一行：AI管理 | 日志 ====================

        # --- 左上：AI 平台管理 ---
        platform_group = make_group("🤖 AI 平台管理", self._on_reset_platform)
        platform_layout = QVBoxLayout(platform_group)
        platform_layout.setContentsMargins(4, 0, 4, 4)
        platform_layout.setSpacing(2)
        platform_layout.addWidget(platform_group._title_bar)

        # 用 QWidget 容器 + QVBoxLayout 替代 QListWidget，行高紧凑（参考主界面AI芯片28px）
        self._platform_container = QWidget()
        self._platform_container.setStyleSheet("background: transparent; border: none;")
        self._platform_container_layout = QVBoxLayout(self._platform_container)
        self._platform_container_layout.setContentsMargins(2, 0, 2, 0)
        self._platform_container_layout.setSpacing(1)

        # 包裹在 QScrollArea 中
        platform_scroll = QScrollArea()
        platform_scroll.setWidget(self._platform_container)
        platform_scroll.setWidgetResizable(True)
        platform_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        platform_scroll.setMinimumHeight(120)
        platform_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                background-color: #FFFFFF;
            }
        """)
        platform_layout.addWidget(platform_scroll)
        self._refresh_platform_list()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.add_btn = QPushButton("添加")
        self.edit_btn = QPushButton("编辑")
        self.toggle_btn = QPushButton("启用/禁用")
        self.delete_btn = QPushButton("删除")
        for btn in [self.add_btn, self.edit_btn, self.toggle_btn, self.delete_btn]:
            btn.setObjectName("secondary")
            btn.setFixedHeight(24)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.toggle_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        platform_layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._on_add_platform)
        self.edit_btn.clicked.connect(self._on_edit_platform)
        self.toggle_btn.clicked.connect(self._on_toggle_platform)
        self.delete_btn.clicked.connect(self._on_delete_platform)

        grid.addWidget(platform_group, 0, 0)

        # --- 中上+右上：日志管理（合并2列，内部左右分栏） ---
        log_group = make_group("📋 日志管理")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 0, 4, 4)
        log_layout.setSpacing(4)
        log_layout.addWidget(log_group._title_bar)

        log_inner = QHBoxLayout()
        log_inner.setSpacing(8)

        # ---- 左半侧：文件列表 ----
        log_left = QVBoxLayout()
        log_left.setSpacing(2)

        # 文件列表（自定义Widget行，与AI平台列表统一风格）
        self._log_file_container = QWidget()
        self._log_file_container.setStyleSheet("background: transparent; border: none;")
        self._log_file_layout = QVBoxLayout(self._log_file_container)
        self._log_file_layout.setContentsMargins(2, 0, 2, 0)
        self._log_file_layout.setSpacing(1)

        log_scroll = QScrollArea()
        log_scroll.setWidget(self._log_file_container)
        log_scroll.setWidgetResizable(True)
        log_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                background-color: #FFFFFF;
            }
        """)
        log_left.addWidget(log_scroll)

        log_inner.addLayout(log_left, stretch=2)

        # ---- 右半侧：日期选择 + 日志信息 + 按钮 ----
        log_right = QVBoxLayout()
        log_right.setSpacing(6)

        # 日期选择（移到右侧顶部）
        date_row = QHBoxLayout()
        date_row.setSpacing(6)
        date_label = QLabel("📅 日期:")
        date_label.setStyleSheet("font-size: 12px; color: #6B7280;")
        self._log_date_combo = QComboBox()
        self._log_date_combo.setMinimumWidth(100)
        self._log_date_combo.setFixedHeight(24)
        self._refresh_log_dates()
        self._log_date_combo.currentTextChanged.connect(self._refresh_log_files)
        date_row.addWidget(date_label)
        date_row.addWidget(self._log_date_combo, stretch=1)
        log_right.addLayout(date_row)

        # 统计信息卡片
        self._log_info_label = QLabel()
        self._refresh_log_info()
        self._log_info_label.setWordWrap(True)
        self._log_info_label.setStyleSheet("""
            QLabel {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
                color: #374151;
            }
        """)
        log_right.addWidget(self._log_info_label)

        # 操作按钮区（竖向排列）
        log_btn_col = QVBoxLayout()
        log_btn_col.setSpacing(6)

        self.open_log_btn = QPushButton("📂 打开日志目录")
        self.open_log_btn.setObjectName("secondary")
        self.open_log_btn.setFixedHeight(24)
        log_btn_col.addWidget(self.open_log_btn)

        self.delete_all_log_btn = QPushButton("🗑 清空全部日志")
        self.delete_all_log_btn.setObjectName("secondary")
        self.delete_all_log_btn.setFixedHeight(24)
        log_btn_col.addWidget(self.delete_all_log_btn)

        log_right.addLayout(log_btn_col)

        log_right.addStretch()

        log_inner.addLayout(log_right, stretch=1)

        self.open_log_btn.clicked.connect(self._on_open_log_dir)
        self.delete_all_log_btn.clicked.connect(self._on_delete_all_logs)

        log_layout.addLayout(log_inner)

        grid.addWidget(log_group, 0, 1, 1, 2)  # 跨2列

        # ==================== 第二行：讨论参数 | 开场白 | LMStudio ====================

        # --- 左下：讨论参数 ---
        disc_group = make_group("💬 讨论参数", self._on_reset_discussion)
        disc_layout = QVBoxLayout(disc_group)
        disc_layout.setContentsMargins(4, 0, 4, 4)
        disc_layout.setSpacing(2)
        disc_layout.addWidget(disc_group._title_bar)

        disc_form = QFormLayout()
        disc_form.setSpacing(6)
        disc_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        disc_form.setContentsMargins(8, 0, 8, 0)
        disc = self.config_mgr.config.get("discussion", {})

        self.max_rounds_spin = QSpinBox()
        self.max_rounds_spin.setRange(1, 200)
        self.max_rounds_spin.setValue(disc.get("max_rounds", 100))
        self.max_rounds_spin.setFixedHeight(24)
        self.max_rounds_spin.setMinimumWidth(120)
        disc_form.addRow("最大轮数:", self.max_rounds_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 3600)
        self.timeout_spin.setValue(disc.get("timeout_seconds", 600))
        self.timeout_spin.setFixedHeight(24)
        self.timeout_spin.setMinimumWidth(120)
        disc_form.addRow("超时(秒):", self.timeout_spin)

        self.start_signal_edit = QLineEdit(disc.get("start_signal", "<ok>"))
        self.start_signal_edit.setFixedHeight(24)
        self.start_signal_edit.setMinimumWidth(120)
        self.start_signal_edit.setPlaceholderText("如 <ok>")
        disc_form.addRow("开场标识:", self.start_signal_edit)

        self.end_signal_edit = QLineEdit(disc.get("end_signal", "<End>"))
        self.end_signal_edit.setFixedHeight(24)
        self.end_signal_edit.setMinimumWidth(120)
        self.end_signal_edit.setPlaceholderText("如 <End>")
        disc_form.addRow("结束标识:", self.end_signal_edit)

        self.arbitration_signal_edit = QLineEdit(disc.get("arbitration_signal", "<结案>"))
        self.arbitration_signal_edit.setFixedHeight(24)
        self.arbitration_signal_edit.setMinimumWidth(120)
        self.arbitration_signal_edit.setPlaceholderText("如 <结案>")
        disc_form.addRow("结案标识:", self.arbitration_signal_edit)

        # 默认军师选择
        self.default_arb_combo = QComboBox()
        self.default_arb_combo.setFixedHeight(24)
        self.default_arb_combo.setMinimumWidth(120)
        for p in self.config_mgr.get_ai_platforms():
            self.default_arb_combo.addItem(p["name"])
        current_arb = disc.get("arbitrator", "智谱清言")
        idx = self.default_arb_combo.findText(current_arb)
        if idx >= 0:
            self.default_arb_combo.setCurrentIndex(idx)
        disc_form.addRow("默认军师:", self.default_arb_combo)

        disc_layout.addLayout(disc_form)
        disc_layout.addStretch()

        grid.addWidget(disc_group, 1, 0)

        # --- 中下：开场白 ---
        opening_group = make_group("📝 开场白", self._on_reset_opening)
        opening_layout = QVBoxLayout(opening_group)
        opening_layout.setContentsMargins(4, 0, 4, 4)
        opening_layout.setSpacing(4)
        opening_layout.addWidget(opening_group._title_bar)

        opening_hint = QLabel("此开场白会原样发送给每个AI。\n系统会自动在后面追加【规则】部分，无需在此填写规则。")
        opening_hint.setStyleSheet("color: #86868B; font-size: 11px; padding: 0 4px;")
        opening_hint.setWordWrap(True)
        opening_layout.addWidget(opening_hint)

        self.opening_edit = QTextEdit()
        self.opening_edit.setAcceptRichText(False)
        self.opening_edit.setPlaceholderText("输入开场白...")
        self.opening_edit.setPlainText(disc.get("opening_remarks", ""))
        self.opening_edit.setMinimumHeight(80)
        opening_layout.addWidget(self.opening_edit)

        grid.addWidget(opening_group, 1, 1)

        # --- 右下：LM Studio 配置 ---
        lm_group = make_group("🧠 LM Studio 配置", self._on_reset_lmstudio)
        lm_layout = QVBoxLayout(lm_group)
        lm_layout.setContentsMargins(4, 0, 4, 4)
        lm_layout.setSpacing(2)
        lm_layout.addWidget(lm_group._title_bar)

        lm_form = QFormLayout()
        lm_form.setSpacing(6)
        lm_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lm_form.setContentsMargins(8, 0, 8, 0)
        lm = self.config_mgr.config.get("lm_studio", {})

        self.lm_enabled_cb = QCheckBox("启用 LM Studio")
        self.lm_enabled_cb.setChecked(lm.get("enabled", False))
        lm_form.addRow(self.lm_enabled_cb)

        self.lm_url_edit = QLineEdit(lm.get("url", "http://127.0.0.1:1234/v1"))
        self.lm_url_edit.setFixedHeight(24)
        self.lm_url_edit.setMinimumWidth(160)
        self.lm_url_edit.setPlaceholderText("http://127.0.0.1:1234/v1")
        lm_form.addRow("服务地址:", self.lm_url_edit)

        self.lm_name_edit = QLineEdit(lm.get("display_name", "MyAi"))
        self.lm_name_edit.setFixedHeight(24)
        self.lm_name_edit.setMinimumWidth(160)
        self.lm_name_edit.setPlaceholderText("本地模型的显示名称")
        lm_form.addRow("显示名称:", self.lm_name_edit)

        self.lm_key_edit = QLineEdit(lm.get("api_key", ""))
        self.lm_key_edit.setFixedHeight(24)
        self.lm_key_edit.setMinimumWidth(160)
        self.lm_key_edit.setPlaceholderText("留空则使用 not-needed")
        lm_form.addRow("API Key:", self.lm_key_edit)

        lm_hint = QLabel("💡 用于本地大模型辅助\n（实时摘要 / 追问建议 / 结案汇总）")
        lm_hint.setStyleSheet("color: #86868B; font-size: 11px; padding: 0 4px;")
        lm_hint.setWordWrap(True)
        lm_form.addRow("", lm_hint)

        lm_layout.addLayout(lm_form)
        lm_layout.addStretch()

        grid.addWidget(lm_group, 1, 2)

        layout.addLayout(grid)

        # --- 底部按钮行 ---
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.restore_all_btn = QPushButton("恢复所有默认")
        self.restore_all_btn.setObjectName("secondary")
        self.restore_all_btn.setFixedHeight(28)
        self.restore_all_btn.clicked.connect(self._on_restore_all_defaults)
        btn_bar.addWidget(self.restore_all_btn)

        self.save_btn = QPushButton("保存设置")
        self.save_btn.setObjectName("primary")
        self.save_btn.setFixedHeight(28)
        self.save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self.save_btn)

        layout.addLayout(btn_bar)

        # 选中平台索引（替代 QListWidget.currentRow）
        self._platform_selected_row = -1

    # ---- 统一列表行构建 ----

    def _build_list_row(self, text, size_text=None, icon=None, indent=0,
                         selected=False, on_dblclick=None, on_delete=None):
        """创建统一风格的列表行。"""
        row = QWidget()
        row.setFixedHeight(26)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 4px;
            }
            QWidget:hover {
                background-color: #F3F4F6;
            }
        """)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8 + indent, 0, 4, 0)
        layout.setSpacing(6)

        if icon:
            icon_label = QLabel(icon)
            icon_label.setFixedWidth(16)
            icon_label.setStyleSheet("background: transparent; border: none; font-size: 12px;")
            layout.addWidget(icon_label)

        text_label = QLabel(text)
        text_label.setStyleSheet("font-size: 12px; color: #1D1D1F; background: transparent; border: none;")
        text_label.setWordWrap(False)
        layout.addWidget(text_label, stretch=1)

        if size_text:
            size_label = QLabel(size_text)
            size_label.setFixedWidth(45)
            size_label.setStyleSheet("font-size: 11px; color: #9CA3AF; background: transparent; border: none;")
            size_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(size_label)

        if on_delete:
            del_btn = QPushButton("×")
            del_btn.setFixedSize(18, 18)
            del_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; border: none; color: #C0C0C5;
                    font-size: 14px; font-weight: bold; padding: 0;
                }
                QPushButton:hover { color: #FF3B30; }
            """)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.clicked.connect(on_delete)
            layout.addWidget(del_btn)

        if on_dblclick:
            row.mouseDoubleClickEvent = lambda e, cb=on_dblclick: cb()

        return row

    def _refresh_platform_list(self):
        """刷新 AI 平台列表（自定义 Widget 行）。"""
        # 清空容器
        layout = self._platform_container_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._platform_selected_row = -1

        platforms = self.config_mgr.get_ai_platforms()
        for i, p in enumerate(platforms):
            url = p.get('url', '')
            domain = url.replace('https://', '').replace('http://', '').split('/')[0]
            icon = "🟢" if p.get("enabled") else "⚪"
            text = f"{p['name']}  ({domain})"

            row = self._build_list_row(
                text=text, icon=icon,
                on_dblclick=lambda idx=i: self._on_edit_platform(idx),
                on_delete=lambda idx=i: self._delete_platform_at(idx)
            )
            layout.addWidget(row)

    def _get_selected_platform_row(self):
        """获取当前选中的平台行索引。"""
        return self._platform_selected_row

    def _on_add_platform(self):
        """添加平台 - 使用 PlatformEditDialog 统一编辑界面。"""
        new_platform = {
            "name": "",
            "url": "",
            "enabled": False,
            "selectors": {
                "input_textarea": "textarea",
                "send_button": "button[type='submit']",
                "stop_button": "",
                "response_container": "",
                "last_response": "",
                "login_indicator": "",
                "login_button": "button:has-text('登录')",
            },
            "thinking_mode": {"enabled": False, "detect": {}, "enable_steps": []},
        }
        dialog = PlatformEditDialog(new_platform, self)
        dialog.setWindowTitle("添加平台")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            platform = dialog.get_platform()
            if not platform["name"].strip():
                self._show_toast("平台名称不能为空。")
                return
            if not platform["url"].strip():
                self._show_toast("平台URL不能为空。")
                return
            if self.config_mgr.add_platform(platform):
                self._refresh_platform_list()
                self._show_toast(f"平台 '{platform['name']}' 已添加。")
            else:
                self._show_toast(f"添加失败：名称 '{platform['name']}' 可能已存在。")

    def _on_edit_platform(self, idx=None):
        """编辑平台 - 弹出选择器编辑对话框。"""
        platforms = self.config_mgr.get_ai_platforms()
        if idx is None:
            idx = self._get_selected_platform_row()
        if idx < 0 or idx >= len(platforms):
            self._show_toast("请先选择一个平台。")
            return

        platform = platforms[idx]
        dialog = PlatformEditDialog(platform, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_platform()
            self.config_mgr.update_platform(platform["name"], updated)
            self._refresh_platform_list()

    def _on_delete_platform(self):
        """删除平台（内置5个AI不允许删除）。"""
        BUILTIN_AIS = {"DeepSeek", "智谱清言", "通义千问", "MiniMax", "Kimi"}
        row = self._get_selected_platform_row()
        platforms = self.config_mgr.get_ai_platforms()
        if row < 0 or row >= len(platforms):
            return
        name = platforms[row]["name"]
        if name in BUILTIN_AIS:
            QMessageBox.warning(self, "无法删除", f"'{name}' 是内置 AI，不允许删除。\n您可以禁用它（取消启用）。")
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除 '{name}' 吗？"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.delete_platform(name)
            self._refresh_platform_list()

    def _delete_platform_at(self, idx):
        """删除指定索引的平台（行尾×按钮调用）。"""
        BUILTIN_AIS = {"DeepSeek", "智谱清言", "通义千问", "MiniMax", "Kimi"}
        platforms = self.config_mgr.get_ai_platforms()
        if idx < 0 or idx >= len(platforms):
            return
        name = platforms[idx]["name"]
        if name in BUILTIN_AIS:
            QMessageBox.warning(self, "无法删除", f"'{name}' 是内置 AI，不允许删除。\n您可以禁用它（取消启用）。")
            return
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除 '{name}' 吗？"
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.delete_platform(name)
            self._refresh_platform_list()

    def _on_toggle_platform(self):
        """启用/禁用选中的平台。"""
        row = self._get_selected_platform_row()
        platforms = self.config_mgr.get_ai_platforms()
        if row < 0 or row >= len(platforms):
            self._show_toast("请先选择一个平台。")
            return
        platform = platforms[row]
        platform["enabled"] = not platform.get("enabled", False)
        self.config_mgr.update_platform(platform["name"], platform)
        self._refresh_platform_list()
        status = "启用" if platform["enabled"] else "禁用"
        log_info(f"平台 {platform['name']} 已{status}")

    def _on_save(self):
        """保存所有设置。"""
        self.config_mgr.set("lm_studio.enabled", self.lm_enabled_cb.isChecked())
        self.config_mgr.set("lm_studio.url", self.lm_url_edit.text())
        self.config_mgr.set("lm_studio.display_name", self.lm_name_edit.text())
        self.config_mgr.set("lm_studio.api_key", self.lm_key_edit.text())
        self.config_mgr.set("discussion.max_rounds", self.max_rounds_spin.value())
        self.config_mgr.set("discussion.timeout_seconds", self.timeout_spin.value())
        self.config_mgr.set("discussion.start_signal", self.start_signal_edit.text())
        self.config_mgr.set("discussion.end_signal", self.end_signal_edit.text())
        self.config_mgr.set("discussion.arbitration_signal", self.arbitration_signal_edit.text())
        # 保存默认军师
        self.config_mgr.set("discussion.arbitrator", self.default_arb_combo.currentText())
        self.config_mgr.set("discussion.opening_remarks", self.opening_edit.toPlainText())
        self.config_mgr.save()
        log_info("设置已保存")
        self._show_toast("设置已保存。")
        self.accept()

    def _on_reset_defaults(self):
        """恢复讨论参数和开场白为默认值（旧版兼容，现在由各模块独立按钮替代）。"""
        self._on_reset_discussion()
        self._on_reset_opening()

    def _on_reset_platform(self):
        """恢复 AI 平台为默认配置。"""
        reply = QMessageBox.question(
            self, "恢复默认",
            "确定要将 AI 平台恢复为默认配置吗？\n\n"
            "• 内置平台（DeepSeek、智谱清言、通义千问、MiniMax、Kimi）将恢复默认选择器\n"
            "• 你手动添加的自定义平台不受影响"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import copy
        from config_manager import DEFAULT_CONFIG, DEFAULT_CONFIG_VERSION
        default_names = {"DeepSeek", "智谱清言", "通义千问", "MiniMax", "Kimi"}
        user_custom_platforms = [
            dict(p) for p in self.config_mgr.config.get("ai_platforms", [])
            if p.get("name") not in default_names
        ]
        new_config = copy.deepcopy(DEFAULT_CONFIG)
        if user_custom_platforms:
            new_config["ai_platforms"].extend(user_custom_platforms)
        new_config["config_version"] = DEFAULT_CONFIG_VERSION
        self.config_mgr.config = new_config
        self.config_mgr.save()
        self._refresh_platform_list()
        self._show_toast("AI 平台已恢复默认，请重启应用生效")
        log_info("已恢复 AI 平台为默认配置")

    def _on_reset_discussion(self):
        """恢复讨论参数为默认值。"""
        from config_manager import DEFAULT_CONFIG
        reply = QMessageBox.question(
            self, "恢复默认",
            "确定要将讨论参数恢复为默认值吗？"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        default_disc = DEFAULT_CONFIG.get("discussion", {})
        self.max_rounds_spin.setValue(default_disc.get("max_rounds", 100))
        self.timeout_spin.setValue(default_disc.get("timeout_seconds", 600))
        self.start_signal_edit.setText(default_disc.get("start_signal", "<ok>"))
        self.end_signal_edit.setText(default_disc.get("end_signal", "<End>"))
        self.arbitration_signal_edit.setText(default_disc.get("arbitration_signal", "<结案>"))
        # 恢复默认军师
        arb_name = default_disc.get("arbitrator", "DeepSeek")
        idx = self.default_arb_combo.findText(arb_name)
        if idx >= 0:
            self.default_arb_combo.setCurrentIndex(idx)
        self._show_toast("讨论参数已恢复默认")
        log_info("已恢复讨论参数为默认值")

    def _on_reset_opening(self):
        """恢复开场白为默认值。"""
        from config_manager import DEFAULT_CONFIG
        reply = QMessageBox.question(
            self, "恢复默认",
            "确定要将开场白恢复为默认值吗？"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        default_disc = DEFAULT_CONFIG.get("discussion", {})
        self.opening_edit.setPlainText(default_disc.get("opening_remarks", ""))
        self._show_toast("开场白已恢复默认")
        log_info("已恢复开场白为默认值")

    def _on_reset_lmstudio(self):
        """恢复 LM Studio 配置为默认值。"""
        from config_manager import DEFAULT_CONFIG
        reply = QMessageBox.question(
            self, "恢复默认",
            "确定要将 LM Studio 配置恢复为默认值吗？"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        lm = DEFAULT_CONFIG.get("lm_studio", {})
        self.lm_enabled_cb.setChecked(lm.get("enabled", False))
        self.lm_url_edit.setText(lm.get("url", "http://127.0.0.1:1234/v1"))
        self.lm_name_edit.setText(lm.get("display_name", "MyAi"))
        self.lm_key_edit.setText(lm.get("api_key", ""))
        self._show_toast("LM Studio 配置已恢复默认")
        log_info("已恢复 LM Studio 配置为默认值")

    def _on_restore_all_defaults(self):
        """恢复所有默认配置（包括 AI 平台、讨论参数、LM Studio 等）。

        策略：
        - 默认平台（DeepSeek/智谱清言/通义千问/MiniMax/Kimi）：恢复为代码中的最新配置
        - 用户手动添加的自定义平台：保留不动
        - 讨论参数、开场白、LM Studio：恢复默认
        - config_version：重置为 DEFAULT_CONFIG_VERSION
        """
        # 先识别用户自定义平台（不在默认平台名列表中的）
        default_names = {"DeepSeek", "智谱清言", "通义千问", "MiniMax", "Kimi"}
        user_custom_platforms = [
            dict(p) for p in self.config_mgr.config.get("ai_platforms", [])
            if p.get("name") not in default_names
        ]

        custom_count = len(user_custom_platforms)
        custom_msg = ""
        if custom_count > 0:
            custom_names = "、".join(p["name"] for p in user_custom_platforms)
            custom_msg = f"\n\n你的自定义平台（{custom_names}）将被保留。"

        reply = QMessageBox.question(
            self, "恢复所有默认",
            "确定要恢复所有默认配置吗？\n\n"
            "这将重置：\n"
            "• AI 平台（恢复 DeepSeek、智谱清言、通义千问、MiniMax、Kimi 的默认选择器）\n"
            "• 讨论参数（轮数、超时、结束标记、结案方）\n"
            "• 开场白\n"
            "• LM Studio 配置\n\n"
            "你对默认平台的修改将丢失！"
            + custom_msg
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import copy
        from config_manager import DEFAULT_CONFIG, DEFAULT_CONFIG_VERSION
        # 用 DEFAULT_CONFIG 完全替换配置
        new_config = copy.deepcopy(DEFAULT_CONFIG)
        # 保留用户自定义平台
        if user_custom_platforms:
            new_config["ai_platforms"].extend(user_custom_platforms)
        # 确保版本号是最新的
        new_config["config_version"] = DEFAULT_CONFIG_VERSION
        self.config_mgr.config = new_config
        self.config_mgr.save()
        log_info(f"已恢复所有默认配置（版本 v{DEFAULT_CONFIG_VERSION}），保留了 {custom_count} 个自定义平台")
        self._refresh_platform_list()
        self._show_toast(f"已恢复所有默认配置（v{DEFAULT_CONFIG_VERSION}），请重启应用生效")

    def _refresh_log_info(self):
        """刷新日志统计信息。"""
        total = get_total_size()
        dates = get_date_dirs()
        if total == 0 and not dates:
            self._log_info_label.setText("📝 当前无日志文件")
            return
        size_str = f"{total / 1024:.1f} KB" if total < 1024 * 1024 else f"{total / 1024 / 1024:.1f} MB"
        self._log_info_label.setText(
            f"📝 日志: {len(dates)} 天  |  📊 总大小: {size_str}\n"
            f"📂 路径: {get_log_dir()}"
        )

    def _refresh_log_dates(self):
        """刷新日期下拉列表。"""
        if not hasattr(self, '_log_date_combo'):
            return
        self._log_date_combo.clear()
        dates = get_date_dirs()
        for d in dates:
            # 格式化为可读: 20260709 → 2026-07-09
            readable = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            self._log_date_combo.addItem(readable, d)
        if dates:
            self._log_date_combo.setCurrentIndex(0)

    def _refresh_log_files(self):
        """根据选中的日期刷新文件列表（自定义 Widget 行）。"""
        if not hasattr(self, '_log_file_layout'):
            return
        # 清空容器
        layout = self._log_file_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        date_str = self._log_date_combo.currentData()
        if not date_str:
            return

        files = get_files_by_date(date_str)
        if not files:
            return

        # 分组
        op_files = [f for f in files if f["type"] == "操作日志"]
        disc_files = [f for f in files if f["type"] == "讨论记录"]

        def _add_group(icon, title, file_list):
            # 组标题行
            header = QWidget()
            header.setFixedHeight(26)
            h_layout = QHBoxLayout(header)
            h_layout.setContentsMargins(8, 0, 8, 0)
            h_layout.setSpacing(4)
            h_icon = QLabel(icon)
            h_icon.setStyleSheet("background: transparent; border: none; font-size: 12px;")
            h_layout.addWidget(h_icon)
            h_title = QLabel(title)
            h_title.setStyleSheet("font-size: 11px; font-weight: 600; color: #6B7280; background: transparent; border: none;")
            h_layout.addWidget(h_title)
            h_layout.addStretch()
            layout.addWidget(header)
            # 文件行（统一用 _build_list_row）
            for f in file_list:
                filepath = str(f["path"])
                size_text = self._format_size(f["size"])
                row = self._build_list_row(
                    text=f["name"], size_text=size_text, indent=24,
                    on_dblclick=lambda fp=filepath: self._on_log_file_double_clicked(fp),
                    on_delete=lambda fp=filepath: self._delete_log_file(fp)
                )
                layout.addWidget(row)

        if op_files:
            _add_group("📁", "操作日志", op_files)
        if disc_files:
            _add_group("💬", "讨论记录", disc_files)

    def _delete_log_file(self, filepath):
        """删除单个日志文件。"""
        import os
        try:
            os.remove(filepath)
            log_info(f"已删除日志文件: {filepath}")
            self._refresh_log_files()
            self._refresh_log_info()
        except Exception as e:
            self._show_toast(f"删除失败: {e}")

    def _on_log_file_double_clicked(self, filepath: str):
        """双击文件查看内容。"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception as e:
            self._show_toast(f"读取失败: {e}")
            return

        # 如果是 JSON 讨论记录，格式化展示
        is_json = filepath.endswith('.json')
        if is_json:
            try:
                import json as _json
                data = _json.loads(content)
                formatted = self._format_discussion_json(data)
                title = f"讨论记录 - {data.get('topic', '未知')[:30]}"
            except Exception:
                is_json = False
                formatted = content
                title = os.path.basename(filepath)
        else:
            formatted = content
            title = f"日志 - {os.path.basename(filepath)}"

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        # 使用屏幕 85% 大小，确保内容完整可见
        screen = QApplication.primaryScreen().availableGeometry()
        dialog.resize(int(screen.width() * 0.85), int(screen.height() * 0.85))
        from ui_styles import GLOBAL_QSS
        dialog.setStyleSheet(GLOBAL_QSS)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(10, 10, 10, 10)

        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setAcceptRichText(False)
        viewer.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        viewer.setPlainText(formatted)
        # 跨平台等宽字体 + 舒适字号行距
        viewer.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                font-family: 'Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New', monospace;
                font-size: 14px;
                padding: 12px;
                border: none;
            }
        """)
        # 跳转到顶部
        viewer.verticalScrollBar().setValue(0)
        dialog_layout.addWidget(viewer)

        button_row = QHBoxLayout()
        # 字数统计
        info_label = QLabel(f"共 {len(formatted)} 字  |  文件: {os.path.basename(filepath)}")
        info_label.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        button_row.addWidget(info_label)
        button_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondary")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(dialog.accept)
        button_row.addWidget(close_btn)
        dialog_layout.addLayout(button_row)

        dialog.exec()

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小。"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / 1024 / 1024:.1f} MB"

    @staticmethod
    def _format_discussion_json(data: dict) -> str:
        """格式化讨论记录 JSON 为可读文本。"""
        lines = []
        lines.append(f"主题: {data.get('topic', '未知')}")
        lines.append(f"时间: {data.get('start_time', '')} ~ {data.get('end_time', '')}")
        lines.append(f"参与: {', '.join(data.get('participants', []))}")
        lines.append("")

        current_round = 0
        for msg in data.get("messages", []):
            rnd = msg.get("round", 1)
            if rnd != current_round:
                current_round = rnd
                lines.append(f"{'='*20} 第{current_round}轮 {'='*20}")
            speaker = msg.get("speaker", "?")
            ts = msg.get("timestamp", "")
            content = msg.get("content", "")
            ctx = msg.get("context_received")
            ctx_str = f" (引用: {ctx})" if ctx else ""
            lines.append(f"\n[{speaker}] {ts}{ctx_str}")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)

    def _on_delete_all_logs(self):
        """清空全部日志（需确认）。"""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "确认清空",
            "确定要清空所有日志文件吗？\n\n此操作不可撤销，所有操作日志和讨论记录将被删除。\n下次运行时自动重建。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        count, msg = delete_all_logs()
        log_ui(f"用户清空了全部日志 ({count} 个文件)")
        self._refresh_log_info()
        self._refresh_log_dates()
        self._refresh_log_files()
        self._show_toast(msg)

    def _on_open_log_dir(self):
        """在 Finder 中打开日志目录。"""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
            log_ui("用户打开日志目录")
        except Exception as e:
            log_error(f"打开日志目录失败: {e}")
            self._show_toast(f"无法打开日志目录: {e}")


class PlatformEditDialog(QDialog):
    """平台选择器编辑对话框。"""

    def __init__(self, platform: dict, parent=None):
        super().__init__(parent)
        self.platform = dict(platform)
        self.setWindowTitle(f"编辑平台: {platform['name']}")
        self.setMinimumWidth(700)
        self.resize(750, 600)
        from ui_styles import GLOBAL_QSS
        self.setStyleSheet(GLOBAL_QSS)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 启用复选框
        self.enabled_cb = QCheckBox("启用此平台（启用后才会在主界面显示）")
        self.enabled_cb.setChecked(self.platform.get("enabled", False))
        layout.addWidget(self.enabled_cb)

        # 名称和URL
        form_top = QFormLayout()
        form_top.setSpacing(8)
        self.name_edit = QLineEdit(self.platform.get("name", ""))
        self.name_edit.setFixedHeight(24)
        self.name_edit.setMinimumWidth(500)
        form_top.addRow("名称:", self.name_edit)

        self.url_edit = QLineEdit(self.platform.get("url", ""))
        self.url_edit.setFixedHeight(24)
        self.url_edit.setMinimumWidth(500)
        form_top.addRow("URL:", self.url_edit)
        layout.addLayout(form_top)

        # GroupBox 标题样式（覆盖全局QSS，确保标题完整显示）
        GROUP_STYLE = """
            QGroupBox {
                border: 1px solid #E5E5EA;
                border-radius: 8px;
                margin-top: 14px;
                padding: 18px 10px 10px 10px;
                font-size: 13px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                top: 0px;
                padding: 0 6px;
                background-color: #FFFFFF;
            }
        """

        # 选择器
        sels_group = QGroupBox("CSS 选择器配置")
        sels_group.setStyleSheet(GROUP_STYLE)
        sels_layout = QFormLayout(sels_group)
        sels_layout.setSpacing(6)
        sels = self.platform.get("selectors", {})

        self.sel_inputs = {}
        sel_fields = [
            ("input_textarea", "输入框选择器:"),
            ("send_button", "发送按钮选择器:"),
            ("stop_button", "停止按钮选择器:"),
            ("response_container", "回复容器选择器:"),
            ("last_response", "最新回复选择器:"),
            ("login_indicator", "登录指示器选择器:"),
            ("login_button", "登录按钮选择器:"),
        ]
        for key, label in sel_fields:
            edit = QLineEdit(sels.get(key, ""))
            edit.setFixedHeight(24)
            edit.setMinimumWidth(500)
            sels_layout.addRow(label, edit)
            self.sel_inputs[key] = edit

        layout.addWidget(sels_group)

        # 思考模式配置
        think_group = QGroupBox("思考模式配置（可选，用于自动开启深度思考）")
        think_group.setStyleSheet(GROUP_STYLE)
        think_layout = QFormLayout(think_group)
        think_layout.setSpacing(6)
        tm = self.platform.get("thinking_mode", {})
        detect_cfg = tm.get("detect", {})

        self.tm_enabled = QCheckBox("启用自动开启思考模式")
        self.tm_enabled.setChecked(tm.get("enabled", False))
        think_layout.addRow(self.tm_enabled)

        self.tm_detect_type = QComboBox()
        self.tm_detect_type.addItems(["toggle", "dropdown"])
        self.tm_detect_type.setFixedHeight(24)
        self.tm_detect_type.setCurrentText(detect_cfg.get("type", tm.get("type", "toggle")))
        think_layout.addRow("检测类型:", self.tm_detect_type)
        self.tm_inputs = {}
        tm_fields = [
            ("label_selector", "标签选择器 (dropdown检测用):"),
            ("label_text", "激活标签文本:"),
            ("selector", "开关选择器 (toggle检测用):"),
            ("active_attr", "激活属性名 (toggle用):"),
            ("active_value", "激活属性值 (toggle用):"),
        ]
        for key, label in tm_fields:
            edit = QLineEdit(detect_cfg.get(key, tm.get(key, "")))
            edit.setFixedHeight(24)
            edit.setMinimumWidth(500)
            think_layout.addRow(label, edit)
            self.tm_inputs[key] = edit

        # 启用步骤
        steps_label = QLabel("启用步骤（JSON格式，每步: click/wait/click_text）:")
        steps_label.setStyleSheet("font-size: 12px; color: #6B7280;")
        think_layout.addRow(steps_label)
        import json as _json
        steps = tm.get("enable_steps", [])
        self.tm_steps_edit = QLineEdit(_json.dumps(steps, ensure_ascii=False) if steps else "")
        self.tm_steps_edit.setFixedHeight(24)
        self.tm_steps_edit.setMinimumWidth(500)
        self.tm_steps_edit.setPlaceholderText('[{"action":"click","selector":"..."},{"action":"wait","ms":800}]')
        think_layout.addRow("enable_steps:", self.tm_steps_edit)

        layout.addWidget(think_group)

        # 保存按钮
        btn = QPushButton("保存")
        btn.setObjectName("primary")
        btn.setFixedHeight(28)
        btn.setMaximumWidth(120)
        btn.clicked.connect(self._on_save)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _on_save(self):
        self.platform["name"] = self.name_edit.text()
        self.platform["url"] = self.url_edit.text()
        self.platform["enabled"] = self.enabled_cb.isChecked()
        for key, edit in self.sel_inputs.items():
            self.platform.setdefault("selectors", {})[key] = edit.text()
        # 保存思考模式配置（新格式：detect + enable_steps）
        tm = {"enabled": self.tm_enabled.isChecked()}
        if self.tm_enabled.isChecked():
            # 检测配置
            detect_cfg = {"type": self.tm_detect_type.currentText()}
            for key, edit in self.tm_inputs.items():
                val = edit.text().strip()
                if val:
                    detect_cfg[key] = val
            tm["detect"] = detect_cfg
            # 启用步骤
            import json as _json
            steps_text = self.tm_steps_edit.text().strip()
            if steps_text:
                try:
                    tm["enable_steps"] = _json.loads(steps_text)
                except Exception:
                    pass  # JSON 解析失败时忽略
        self.platform["thinking_mode"] = tm
        self.accept()

    def get_platform(self) -> dict:
        return self.platform


# ======================================================================
# 状态监控线程
# ======================================================================

class StatusMonitor(QThread):
    """
    后台线程：定时监控 Chrome 和各 AI 平台页面的状态。

    信号：
        status_changed(list): [(platform_name, url, chrome_running, page_open), ...]
    """
    status_changed = pyqtSignal(list)

    def __init__(self, chrome_mgr: ChromeManager, config_mgr: ConfigManager):
        super().__init__()
        self.chrome_mgr = chrome_mgr
        self.config_mgr = config_mgr
        self._running = True
        self._interval = 3  # 每 3 秒检查一次

    def run(self):
        while self._running:
            try:
                chrome_running = self.chrome_mgr.is_chrome_running()
                results = []
                for p in self.config_mgr.get_ai_platforms():
                    if not p.get("enabled"):
                        results.append((p["name"], p.get("url", ""), False, False))
                        continue
                    url = p.get("url", "")
                    page_open = False
                    if chrome_running and url:
                        page_open = self.chrome_mgr.is_page_open(url)
                    results.append((p["name"], url, chrome_running, page_open))
                self.status_changed.emit(results)
            except Exception:
                pass
            self.msleep(self._interval * 1000)

    def stop(self):
        self._running = False
        # 给线程足够时间退出，但设置超时避免卡死
        self.wait(3000)

    def start(self):
        """重写 start：重置 _running 标志，确保停止后可重新启动。"""
        self._running = True
        super().start()


# ======================================================================
# AI 状态旋转图标
# ======================================================================

class AISpinnerIcon(QWidget):
    """
    AI 状态图标：三态颜色。
    - orange: 橙色旋转（默认/检测中，活跃但思考模式未确认）
    - green:  绿色旋转（登录+思考模式都OK，可以开始讨论）
    - red:    红色静止（未启用/被剔除，不可用）
    参考 Trae IDE 的实时跟踪风格。
    """

    # 颜色常量
    COLOR_ORANGE = "#F59E0B"
    COLOR_GREEN = "#10B981"
    COLOR_RED = "#EF4444"

    def __init__(self, state: str = "orange", parent=None):
        super().__init__(parent)
        self._state = state  # "orange", "green", "red"
        self._angle = 0
        self.setFixedSize(14, 14)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)

        # orange 和 green 旋转，red 静止
        if self._state != "red":
            self._timer.start(80)

    def set_state(self, state: str):
        """切换状态: orange/green/red。"""
        if self._state == state:
            return
        self._state = state
        if state == "red":
            self._timer.stop()
        else:
            self._timer.start(80)
        self.update()

    def get_state(self) -> str:
        return self._state

    def _on_timeout(self):
        self._angle = (self._angle + 15) % 360
        self.update()

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPen, QBrush
        from PyQt6.QtCore import QRectF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2

        # 根据状态选择颜色
        if self._state == "green":
            color = QColor(self.COLOR_GREEN)
        elif self._state == "orange":
            color = QColor(self.COLOR_ORANGE)
        else:  # red
            color = QColor(self.COLOR_RED)

        if self._state != "red":
            # 旋转状态：中心圆点 + 旋转弧线
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

            painter.translate(cx, cy)
            painter.rotate(self._angle)

            pen = QPen(color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            r = 7
            for i in range(4):
                start_angle = i * 90
                rect = QRectF(-r, -r, 2 * r, 2 * r)
                painter.drawArc(rect, int(start_angle * 16), int(25 * 16))
        else:
            # 红色静止：中心红点 + 红色圆环
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

            pen = QPen(QColor("#FCA5A5"), 1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))

        painter.end()


# ======================================================================
# 文件拖拽上传区
# ======================================================================

class FileDropArea(QFrame):
    """文件拖拽上传区域：支持点击选择和拖拽文件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self.setFixedHeight(32)
        self._build_ui()

    def set_main_window(self, mw):
        self._main_window = mw

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)

        self._label = QLabel("📎  拖拽文件到此处，或点击选择")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("font-size: 12px; color: #6B7280; background: transparent; border: none;")
        layout.addWidget(self._label)

        self._update_style()

    def _update_style(self):
        border_color = "#007AFF" if self._hovered else "#D2D2D7"
        bg_color = "#E8F2FF" if self._hovered else "#F5F5F7"
        self.setStyleSheet(f"""
            FileDropArea {{
                border: 1.5px dashed {border_color};
                border-radius: 8px;
                background-color: {bg_color};
            }}
        """)
        if self._hovered:
            self._label.setStyleSheet("font-size: 12px; color: #007AFF; background: transparent; border: none;")
        else:
            self._label.setStyleSheet("font-size: 12px; color: #86868B; background: transparent; border: none;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._main_window:
            self._main_window._on_upload()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._hovered = True
            self._update_style()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._hovered = False
        self._update_style()

    def dropEvent(self, event):
        self._hovered = False
        self._update_style()
        urls = event.mimeData().urls()
        if urls and self._main_window:
            paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
            if paths:
                # 追加到已有文件列表（去重）
                existing = list(self._main_window.hosted_tab._file_paths)
                for p in paths:
                    if p not in existing:
                        existing.append(p)
                self._main_window._set_file_paths(existing)
                event.acceptProposedAction()


# ======================================================================
# 托管模式 Tab
# ======================================================================

class ChatInputEdit(QTextEdit):
    """聊天输入框：Enter发送，Shift+Enter换行。右键菜单中文化。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt
        if event.key() == Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._callback()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """重写右键菜单，全部改为中文。"""
        from PyQt6.QtGui import QAction
        menu = self.createStandardContextMenu()
        # 遍历所有 action，将英文改为中文
        cn_map = {
            "Undo": "撤销",
            "Redo": "重做",
            "Cut": "剪切",
            "Copy": "复制",
            "Paste": "粘贴",
            "Delete": "删除",
            "Select All": "全选",
            "Select all": "全选",
        }
        for action in menu.actions():
            en_text = action.text()
            if en_text in cn_map:
                action.setText(cn_map[en_text])
        menu.exec(event.globalPos())


class HostedModeTab(QWidget):
    """讨论内容区：对话流 + 底部输入框。控件由 MainWindow 左侧栏管理。"""

    def __init__(self, config_mgr: ConfigManager, chrome_mgr: ChromeManager,
                 main_window: QMainWindow):
        super().__init__()
        self.config_mgr = config_mgr
        self.chrome = chrome_mgr
        self.main_window = main_window
        self._file_paths = []
        self.hosted = None  # 当前 HostedMode 实例（讨论运行时设置）
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 对话流（最大化，占主要空间）
        self.chat_stream = ChatStream()
        layout.addWidget(self.chat_stream, stretch=1)

        # 即时状态提示栏（输入框上方）
        self.status_bar = QLabel("")
        self.status_bar.setObjectName("instant_status")
        self.status_bar.setStyleSheet("""
            QLabel#instant_status {
                background-color: #F0F4FF;
                border: 1px solid #C7D2FE;
                border-radius: 6px;
                padding: 4px 10px;
                color: #4338CA;
                font-size: 12px;
                min-height: 20px;
            }
        """)
        layout.addWidget(self.status_bar)

        # 底部输入区（聊天室风格：输入框 + 发送按钮）
        input_layout = QHBoxLayout()
        input_layout.setSpacing(4)

        self.message_edit = ChatInputEdit(self._on_send)
        self.message_edit.setPlaceholderText("输入消息开始讨论... (Enter发送, Shift+Enter换行)")
        self.message_edit.setMinimumHeight(40)
        self.message_edit.setMaximumHeight(80)
        self.message_edit.setAcceptRichText(False)
        input_layout.addWidget(self.message_edit, stretch=1)

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setMinimumWidth(72)
        self.send_btn.setFixedHeight(34)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

    def _set_status(self, text: str):
        """更新即时状态栏。"""
        self.status_bar.setText(text)

    def _clear_status(self):
        """清空即时状态栏。"""
        self.status_bar.setText("")

    def _on_send(self):
        """统一发送：讨论未开始时启动讨论，进行中时主公密令，结束后追问。"""
        text = self.message_edit.toPlainText().strip()
        if not text:
            return

        # 优先从 worker 获取 hosted 实例（self.hosted 可能为 None）
        hosted = self.hosted
        if not hosted and hasattr(self.main_window, 'worker') and self.main_window.worker:
            hosted = getattr(self.main_window.worker, '_hosted', None)
            if hosted:
                self.hosted = hosted  # 缓存引用

        is_running = hosted.is_running() if hosted else False
        log_info(f"_on_send: hosted={hosted is not None}, is_running={is_running}, "
                 f"has_history={hasattr(hosted, '_last_ai_list') and bool(hosted._last_ai_list) if hosted else False}")

        if hosted and is_running:
            # 讨论进行中 → 主公密令（累积多条，等军师空闲时批量发送）
            self.chat_stream.append_user(text)
            hosted.submit_user_input(text)
            self.message_edit.clear()
            # 查看队列中有多少条密令
            queue_size = hosted._user_input_queue.qsize() if hasattr(hosted, '_user_input_queue') else 0
            self.main_window._show_toast(f"📜 主公密令已暂存（队列中{queue_size}条），军师空闲时自动发送")
        elif hosted and hasattr(hosted, '_last_ai_list') and hosted._last_ai_list:
            # 讨论已结束但有历史 → 追问模式
            if self.main_window._start_in_progress:
                log_warning("追问正在进行中，忽略发送")
                self.main_window._show_toast("⏳ 追问正在进行中，请等待当前追问完成")
                return
            log_info("→ 进入追问模式")
            self.chat_stream.append_user(text)
            self.message_edit.clear()
            self.main_window._start_in_progress = True
            self.main_window._discussion_running = True
            self.main_window.worker.do_continue_discussion(text)
        else:
            # 无历史 → 新讨论
            # 检查Chrome是否启动
            if not self.main_window.chrome_mgr.is_chrome_running():
                self.main_window._show_toast("⚠️ Chrome 尚未启动，无法执行讨论。\n请先点击「启动Chrome」按钮")
                return
            # 检查AI是否就绪
            active_ais = list(self.main_window.active_ais)
            if len(active_ais) < 2:
                self.main_window._show_toast(
                    f"⚠️ 至少需要选择 2 个 AI 参与讨论。\n当前: {len(active_ais)} 个\n\n"
                    f"请在中军帐中选中AI并等待其状态变为绿色")
                return
            if self.main_window._start_in_progress:
                log_warning("讨论正在启动中，忽略发送")
                self.main_window._show_toast("⏳ 讨论正在启动中，请稍候...")
                return
            log_info("→ 进入新讨论模式")
            self._start_discussion(text)

    def _start_discussion(self, first_message: str):
        """启动讨论（以用户的首条消息作为话题）。"""
        if self.main_window._start_in_progress:
            return

        # 先检查 AI 就绪状态，未就绪则阻拦（不显示消息到对话框）
        active_ais = list(self.main_window.active_ais)
        if len(active_ais) < 2:
            self.main_window._show_toast(
                f"至少需要选择 2 个 AI 参与讨论。\n当前: {len(active_ais)} 个")
            return

        not_ready = []
        for name in active_ais:
            color = self.main_window._get_ai_color(name)
            if color != "green":
                msg = self.main_window._get_ai_status_msg(name)
                not_ready.append((name, color, msg))

        if not_ready:
            lines = []
            for name, color, msg in not_ready:
                lines.append(f"  • {name}: {msg}")
            detail = "\n".join(lines)
            self.main_window._show_toast(
                f"以下 AI 尚未就绪，请等待图标变绿后再开始：\n\n{detail}")
            return

        # AI 全部就绪，显示用户消息（不清空之前的对话记录，新问题围绕之前讨论继续）
        # 只有第一次讨论（完全没有历史记录且聊天区为空）才清空占位提示
        # 大脑线程没有权限清空对话框，只有用户点击按钮才能清空
        _hosted = self.hosted
        if not _hosted and hasattr(self.main_window, 'worker') and self.main_window.worker:
            _hosted = getattr(self.main_window.worker, '_hosted', None)
            if _hosted:
                self.hosted = _hosted
        has_prior_history = (_hosted and hasattr(_hosted, '_last_ai_list') and _hosted._last_ai_list)
        if not has_prior_history and self.chat_stream._layout.count() <= 1:
            # 聊天区只有弹簧（空），清空占位提示
            self.chat_stream.clear_messages()
        self.chat_stream.append_user(first_message)
        self.message_edit.clear()
        self.main_window._start_in_progress = True
        self.main_window._discussion_running = True

        # 构建 AI 列表，军师排首位
        ai_list = []
        for name in active_ais:
            ai_cfg = self.main_window.config_mgr.get_platform_by_name(name)
            if ai_cfg:
                ai_list.append(ai_cfg)
        arb_name = self.main_window.config_mgr.config.get("discussion", {}).get("arbitrator", "auto")
        if arb_name and arb_name != "auto":
            arb_ai = None
            others = []
            for ai in ai_list:
                if ai["name"] == arb_name:
                    arb_ai = ai
                else:
                    others.append(ai)
            if arb_ai:
                ai_list = [arb_ai] + others

        # 委托给工作线程执行讨论（不阻塞 UI）
        self.main_window.worker.do_start_discussion(
            first_message, ai_list, self._file_paths
        )

    def refresh_platforms(self):
        """刷新 AI 下拉列表（由 MainWindow 的 AI 芯片选择器管理）。"""
        self.main_window._refresh_ai_chips()

    def _on_start(self):
        """开始讨论（兼容左侧栏按钮调用）。"""
        log_ui("用户点击「开始讨论」按钮")
        text = self.message_edit.toPlainText().strip()
        if not text:
            self.main_window._show_toast("请输入消息开始讨论。")
            return
        self._start_discussion(text)

    def _on_clear(self):
        self.chat_stream.clear_messages()
        self.message_edit.clear()
        self._file_paths = []
        self.main_window._set_file_paths([])


# ======================================================================
# 主窗口
# ======================================================================

class MainWindow(QMainWindow):
    """聚慧 PolySage 主窗口。"""

    # 信号：用于线程安全的 UI 更新
    status_message = pyqtSignal(str, int)  # (message, timeout_ms)

    def __init__(self):
        super().__init__()
        self._exiting = False
        self._start_in_progress = False  # 防止重复点击"开始讨论"
        # AI 状态缓存：{ai_name: {"color": "orange"/"green"/"red", "msg": str, "ts": float}}
        self._ai_state_cache = {}
        self._ai_icons = {}  # {ai_name: AISpinnerIcon} 活跃区图标引用
        self._ai_chips = {}  # {ai_name: QWidget} 活跃区芯片引用
        # 记录上一次各 AI 页面打开状态，用于检测"重新打开"
        self._last_page_open = {}  # {ai_name: bool}
        self.config_mgr = ConfigManager()
        self._arbitrator = self.config_mgr.config.get("discussion", {}).get("arbitrator", "智谱清言")
        # 先创建 chrome_mgr 占位（_build_ui 中 HostedModeTab 需要引用）
        self.chrome_mgr = ChromeManager(self.config_mgr.config)
        self.setWindowTitle("聚慧")
        # 设置窗口图标
        _icon_path = resource_path("logo_ui.png")
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))
        self.setMinimumSize(900, 650)
        self.resize(1100, 750)
        self.setStyleSheet(GLOBAL_QSS)
        self._build_ui()
        self._build_menu()
        self._refresh_all()

        # ===== 工作线程（独立的 asyncio 事件循环，处理所有业务逻辑） =====
        self.worker = WorkerThread(self.config_mgr)
        self.worker.chrome_result.connect(self._on_chrome_result)
        self.worker.chrome_started_signal.connect(self._on_worker_chrome_started)
        self.worker.chrome_stopped_signal.connect(self._on_worker_chrome_stopped)
        self.worker.page_opened.connect(self._on_page_opened)
        self.worker.ai_status.connect(self._on_ai_status)
        self.worker.progress.connect(self._on_progress)
        self.worker.discussion_done.connect(self._on_discussion_done)
        self.worker.toast.connect(self._show_toast)
        self.worker.status_msg.connect(lambda msg, t: self.statusBar().showMessage(msg, t))
        self.worker.button_state.connect(self._on_button_state)
        self.worker.chat_counting.connect(lambda: self.hosted_tab.chat_stream.start_counting())
        self.worker.chips_refresh.connect(self._refresh_ai_chips)
        self.worker.start()
        log_info("WorkerThread 已启动")

        # 注意：chrome_mgr 保持为 _build_ui 前创建的占位实例
        # 工作线程内部有自己的 ChromeManager，用于实际 Playwright 操作
        # 主线程的 chrome_mgr 仅用于 is_chrome_running() 等同步方法

        # 状态监控线程（只检测 Chrome 进程和页面是否存在，不碰网页内容）
        self._status_monitor = StatusMonitor(self.chrome_mgr, self.config_mgr)
        self._status_monitor.status_changed.connect(self._on_status_changed)

    # ===== WorkerThread 信号处理器（在主线程上运行，安全更新 UI） =====

    def _on_chrome_result(self, success: bool, msg: str):
        """Chrome 启动/关闭结果。"""
        if not success:
            self._show_toast(msg)
        self._refresh_chrome_status()

    def _on_worker_chrome_started(self):
        """Chrome 已启动 — 大脑线程通知，主线程更新UI。"""
        import time
        self._chrome_start_time = time.time()
        self.chrome_start_btn.setEnabled(True)
        self.chrome_stop_btn.setEnabled(True)
        if hasattr(self, '_status_monitor') and self._status_monitor is not None:
            if not self._status_monitor.isRunning():
                self._status_monitor.start()
                log_info("StatusMonitor 线程已启动")

    def _on_worker_chrome_stopped(self):
        """Chrome 已关闭 — 大脑线程通知，主线程更新UI。"""
        import time as _time
        # 停止后台监控线程
        if hasattr(self, '_status_monitor') and self._status_monitor is not None:
            if self._status_monitor.isRunning():
                self._status_monitor.stop()
                log_info("StatusMonitor 线程已停止")
        # 清除所有 AI 状态缓存并设为橙色
        for name in list(self._ai_state_cache.keys()):
            self._ai_state_cache[name] = {
                "color": "orange", "msg": "Chrome 未运行", "ts": _time.time()
            }
            self._update_ai_icon(name)
        for name in self.active_ais:
            if name not in self._ai_state_cache:
                self._ai_state_cache[name] = {
                    "color": "orange", "msg": "Chrome 未运行", "ts": _time.time()
                }
            self._update_ai_icon(name)
        self._refresh_ai_status_indicator()
        # 恢复按钮状态
        self.chrome_start_btn.setEnabled(True)
        self.chrome_stop_btn.setEnabled(True)
        self._chrome_stopping = False
        self.statusBar().showMessage("Chrome 已关闭", 3000)

    def _on_page_opened(self, name: str, success: bool):
        """页面打开结果。"""
        if success:
            log_info(f"[WorkerThread] {name} 页面已打开")
        else:
            log_warning(f"[WorkerThread] {name} 页面打开失败")

    def _on_ai_status(self, name: str, color: str, msg: str):
        """AI 状态更新（从工作线程发来，在主线程更新 UI）。"""
        import time
        # Chrome 未运行时，忽略 AIWorker 发来的"绿色"状态（防止竞态）
        if color == "green" and not self.chrome_mgr.is_chrome_running():
            log_info(f"[后台检测] 忽略 {name} 的绿色状态（Chrome 已关闭）")
            return
        old = self._ai_state_cache.get(name, {}).get("color")
        self._ai_state_cache[name] = {"color": color, "msg": msg, "ts": time.time()}
        if old != color:
            log_info(f"[后台检测] {name}: {old}→{color} ({msg})")
        self._update_ai_icon(name)

    def _on_progress(self, role: str, name: str, text: str):
        """讨论进度更新（从工作线程发来，在主线程更新 UI）。"""
        cs = self.hosted_tab.chat_stream
        if role == "ai_reply":
            cs.append_ai(name, text)
            log_info(f"AI 回复 [{name}]: {text[:100]}...")
        elif role == "waiting":
            self.hosted_tab._set_status(text)
            log_info(f"状态: {text}")
        elif role == "status":
            cs.append_status(text)
            log_info(f"状态: {text}")
        elif role == "discussion_start":
            cs.start_counting()
        elif role == "error":
            cs.append_status(f"❌ {name}: {text}")
            self.hosted_tab._set_status(f"❌ {name}: {text}")
            log_error(f"错误 [{name}]: {text}")
        elif role == "user_prompt":
            log_info(f"发送提示 [{name}]: {text[:80]}...")
        elif role == "user_message":
            log_info(f"用户插话: {text[:80]}...")
        elif role == "ai_speaking":
            # AI发言状态：text=True=正在发言, False=发言完毕
            if text == True or text == "True":
                self.hosted_tab._set_status(f"💬 {name} 正在发言...")
            # 发言完毕时清除状态
            elif text == False or text == "False":
                self.hosted_tab._set_status("")

    def _on_discussion_done(self, result: dict):
        """讨论完成（大脑线程发来，主线程更新 UI）。"""
        import time as _time
        self._discussion_running = False
        self._start_in_progress = False
        self._discussion_end_time = _time.time()
        self.hosted_tab._clear_status()

        cs = self.hosted_tab.chat_stream
        ended_by = result.get("ended_by", "")
        log_info(f"讨论完成: ended_by={ended_by}, rounds={result.get('rounds')}")

        # 错误情况：弹toast提示
        if "错误" in ended_by:
            self._show_toast(f"❌ {ended_by}", 3000)
            cs.append_status(f"⚠️ {ended_by}（共 {result.get('rounds', 0)} 轮）")
            return

        if result.get("final_result"):
            if "结案" in ended_by:
                title = f"⚖️ 军师已结案（共 {result['rounds']} 轮）"
            else:
                title = f"📋 最终方案（{ended_by}，共 {result['rounds']} 轮）"
            cs.append_result(title, result["final_result"])
            self.statusBar().showMessage(f"讨论完成：{ended_by}", 5000)
        else:
            cs.append_status(f"⚠️ {ended_by}（共 {result.get('rounds', 0)} 轮）")

    def _on_button_state(self, start_enabled: bool, stop_enabled: bool):
        """按钮状态更新。

        发送按钮始终保持可用，用户可随时发送消息。
        即使讨论进行中或Chrome启动中，发送按钮也不禁用。
        如果没有AI运行，_on_send会给出提示。
        """
        # 发送按钮始终保持启用，不做任何禁用操作
        pass

    # ===== StatusMonitor 回调 =====

    def _on_status_changed(self, results: list):
        """监控线程回调：更新 UI 上的状态指示，并同步活跃 AI 列表。"""
        if not results:
            return

        chrome_running = results[0][2]

        # 更新 AI 运行状态指示器
        if not chrome_running:
            self.ai_status_label.setText("🔴 AI 未就绪")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #EF4444; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #FEF2F2;
                    border-radius: 6px; border: 1px solid #FECACA;
                }
            """)
        else:
            # 检查所有活跃 AI 的颜色状态
            if self.active_ais:
                all_green = all(self._get_ai_color(n) == "green" for n in self.active_ais)
                any_orange = any(self._get_ai_color(n) == "orange" for n in self.active_ais)

                if all_green:
                    self.ai_status_label.setText("🟢 AI 已就绪")
                    self.ai_status_label.setStyleSheet("""
                        QLabel {
                            color: #10B981; font-size: 13px; font-weight: 600;
                            padding: 4px 8px; background-color: #ECFDF5;
                            border-radius: 6px; border: 1px solid #A7F3D0;
                        }
                    """)
                elif any_orange:
                    self.ai_status_label.setText("🟠 AI 检测中")
                    self.ai_status_label.setStyleSheet("""
                        QLabel {
                            color: #F59E0B; font-size: 13px; font-weight: 600;
                            padding: 4px 8px; background-color: #FFFBEB;
                            border-radius: 6px; border: 1px solid #FDE68A;
                        }
                    """)
                else:
                    self.ai_status_label.setText("🔴 AI 未就绪")
                    self.ai_status_label.setStyleSheet("""
                        QLabel {
                            color: #EF4444; font-size: 13px; font-weight: 600;
                            padding: 4px 8px; background-color: #FEF2F2;
                            border-radius: 6px; border: 1px solid #FECACA;
                        }
                    """)
            else:
                self.ai_status_label.setText("🔴 AI 未就绪")
                self.ai_status_label.setStyleSheet("""
                    QLabel {
                        color: #EF4444; font-size: 13px; font-weight: 600;
                        padding: 4px 8px; background-color: #FEF2F2;
                        border-radius: 6px; border: 1px solid #FECACA;
                    }
                """)

        # Chrome 未运行时，强制将所有中军帐 AI 变回橙色
        if not chrome_running:
            import time as _time
            for name in self.active_ais:
                cached = self._ai_state_cache.get(name)
                if cached and cached.get("color") == "green":
                    self._ai_state_cache[name] = {
                        "color": "orange", "msg": "Chrome 未运行", "ts": _time.time()
                    }
                    self._update_ai_icon(name)

        # 同步活跃 AI 列表：如果活跃 AI 的网页被关闭，自动从讨论中剔除
        # 注意：Chrome 刚启动时页面可能还没打开，此时不应剔除
        import time
        chrome_start_time = getattr(self, "_chrome_start_time", 0)
        now = time.time()

        # 检测页面"从关闭变为打开"的变化，清除缓存触发重新检测
        current_page_open = {}
        for name, url, cr, page_open in results:
            current_page_open[name] = page_open

        for name, is_open in current_page_open.items():
            last_open = self._last_page_open.get(name, False)
            if not last_open and is_open:
                # 页面从关闭变为打开 → 清除缓存，重新检测
                log_info(f"检测到 {name} 页面重新打开，清除缓存重新检测")
                self._ai_state_cache.pop(name, None)
                self.chrome_mgr.clear_thinking_cache(name)
        self._last_page_open = current_page_open

        # 中军帐为唯一权威源：
        # - 关闭网页 → 不同步至中军帐（不剔除），只标记AI为橙色
        # - 关闭中军帐 → 才同步关闭网页
        # 不再因网页关闭而自动剔除中军帐AI

    # _login_check_loop 已移至 WorkerThread，主线程不再运行检测循环

    def _update_ai_icon(self, ai_name: str):
        """更新单个 AI 的图标颜色（根据缓存状态），并刷新顶部状态指示器。"""
        cached = self._ai_state_cache.get(ai_name)
        if not cached:
            return
        icon = self._ai_icons.get(ai_name)
        if icon:
            icon.set_state(cached["color"])

        # 同步更新中军帐内 AI 芯片的框体颜色（含军师）
        chip = self._ai_chips.get(ai_name)
        if chip is not None:
            # 更新 tooltip：橙色只显示原因，绿色才显示操作提示
            msg = cached.get("msg", "未知")
            color = cached.get("color", "orange")
            is_arb = (ai_name == self._arbitrator)
            if color == "green":
                arb_hint = " | 右键设为军师" if not is_arb else " | 当前军师"
                chip.setToolTip(f"✅ 已就绪{arb_hint}（左键移出讨论）")
            else:
                chip.setToolTip(f"⚠️ {msg}")
            is_green = (cached["color"] == "green")
            if is_arb:
                if is_green:
                    # 军师就绪：绿色框体 + 粗边框（2px区分军师）
                    chip.setStyleSheet("""
                        QWidget#ai_chip_active {
                            background-color: #DCFCE7;
                            border: 2px solid #34C759;
                            border-radius: 5px;
                            min-height: 22px; max-height: 28px;
                        }
                        QWidget#ai_chip_active:hover {
                            background-color: #BBF7D0;
                            border-color: #EF4444;
                        }
                    """)
                    # 军师徽章变绿
                    for child in chip.findChildren(QLabel):
                        if child.text() == "军师":
                            child.setStyleSheet("""
                                font-size: 10px; font-weight: 700; color: #FFFFFF;
                                background-color: #10B981; border-radius: 3px;
                                padding: 0px 4px; min-height: 14px; max-height: 16px;
                            """)
                else:
                    # 军师未就绪：橙色框体
                    chip.setStyleSheet("""
                        QWidget#ai_chip_active {
                            background-color: #FEF3C7;
                            border: 1px solid #F59E0B;
                            border-radius: 5px;
                            min-height: 22px; max-height: 28px;
                        }
                        QWidget#ai_chip_active:hover {
                            background-color: #FDE68A;
                            border-color: #EF4444;
                        }
                    """)
                    for child in chip.findChildren(QLabel):
                        if child.text() == "军师":
                            child.setStyleSheet("""
                                font-size: 10px; font-weight: 700; color: #FFFFFF;
                                background-color: #F59E0B; border-radius: 3px;
                                padding: 0px 4px; min-height: 14px; max-height: 16px;
                            """)
            else:
                # 普通AI：绿色/橙色框体（未就绪统一橙色）
                if is_green:
                    chip.setStyleSheet("""
                        QWidget#ai_chip_active {
                            background-color: #DCFCE7;
                            border: 1px solid #34C759;
                            border-radius: 5px;
                            min-height: 22px; max-height: 28px;
                        }
                        QWidget#ai_chip_active:hover {
                            background-color: #BBF7D0;
                            border-color: #EF4444;
                        }
                    """)
                else:
                    chip.setStyleSheet("""
                        QWidget#ai_chip_active {
                            background-color: #FEF3C7;
                            border: 1px solid #F59E0B;
                            border-radius: 5px;
                            min-height: 22px; max-height: 28px;
                        }
                        QWidget#ai_chip_active:hover {
                            background-color: #FDE68A;
                            border-color: #EF4444;
                        }
                    """)
            # 强制刷新 Qt 样式（unpolish + polish 确保样式立即生效）
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            chip.update()

        # 刷新顶部 AI 状态指示器
        self._refresh_ai_status_indicator()

    def _refresh_ai_status_indicator(self):
        """根据所有活跃 AI 的颜色状态，更新顶部状态指示器。"""
        if not hasattr(self, "ai_status_label"):
            return
        if not self.chrome_mgr.is_chrome_running():
            self.ai_status_label.setText("🔴 AI 未就绪")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #EF4444; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #FEF2F2;
                    border-radius: 6px; border: 1px solid #FECACA;
                }
            """)
            return

        if not self.active_ais:
            self.ai_status_label.setText("🔴 AI 未就绪")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #EF4444; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #FEF2F2;
                    border-radius: 6px; border: 1px solid #FECACA;
                }
            """)
            return

        all_green = all(self._get_ai_color(n) == "green" for n in self.active_ais)
        any_orange = any(self._get_ai_color(n) == "orange" for n in self.active_ais)

        if all_green:
            self.ai_status_label.setText("🟢 AI 已就绪")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #10B981; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #ECFDF5;
                    border-radius: 6px; border: 1px solid #A7F3D0;
                }
            """)
        elif any_orange:
            self.ai_status_label.setText("🟠 AI 检测中")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #F59E0B; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #FFFBEB;
                    border-radius: 6px; border: 1px solid #FDE68A;
                }
            """)
        else:
            self.ai_status_label.setText("🔴 AI 未就绪")
            self.ai_status_label.setStyleSheet("""
                QLabel {
                    color: #EF4444; font-size: 13px; font-weight: 600;
                    padding: 4px 8px; background-color: #FEF2F2;
                    border-radius: 6px; border: 1px solid #FECACA;
                }
            """)

    def _update_all_ai_icons(self):
        """更新所有活跃 AI 的图标颜色。"""
        for name in self._ai_icons:
            self._update_ai_icon(name)

    def _get_ai_color(self, ai_name: str) -> str:
        """获取 AI 的当前颜色状态，无缓存返回 orange。"""
        cached = self._ai_state_cache.get(ai_name)
        if cached:
            return cached["color"]
        return "orange"

    def _get_ai_status_msg(self, ai_name: str) -> str:
        """获取 AI 的状态消息。"""
        cached = self._ai_state_cache.get(ai_name)
        if cached:
            return cached["msg"]
        return "尚未检测"

    def _show_toast(self, message: str, duration: int = 3000):
        """显示自动消失的警告提示（替代 QMessageBox）。

        Args:
            message: 提示文本
            duration: 显示时长（毫秒），默认3秒
        """
        from PyQt6.QtWidgets import QLabel
        toast = QLabel(message, self)
        toast.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toast.setStyleSheet("""
            QLabel {
                background-color: #1F2937;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 500;
                padding: 16px 24px;
                border-radius: 10px;
                border: 1px solid #374151;
                max-width: 400px;
            }
        """)
        toast.setWordWrap(True)
        toast.adjustSize()
        # 居中显示在主窗口上方
        geo = self.geometry()
        x = geo.x() + (geo.width() - toast.width()) // 2
        y = geo.y() + 80
        toast.move(x, y)
        toast.show()
        # duration 毫秒后自动关闭
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(duration, toast.close)

    def _build_ui(self):
        # 中央 widget
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- 主内容区（左右分栏） ---
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        root_layout.addLayout(main_layout)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 左侧控制栏 ---
        left_panel = QWidget()
        left_panel.setObjectName("left_panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 0, 8)
        left_layout.setSpacing(6)

        # 1. AI 运行状态指示器（与按钮同高）
        self.ai_status_label = QLabel("AI 未就绪")
        self.ai_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ai_status_label.setFixedHeight(48)
        self.ai_status_label.setStyleSheet("""
            QLabel {
                color: #EF4444;
                font-size: 13px;
                font-weight: 600;
                background-color: #FEF2F2;
                border-radius: 6px;
                border: 1px solid #FECACA;
            }
        """)
        left_layout.addWidget(self.ai_status_label)

        # Chrome 启动/关闭按钮（横向填满）
        chrome_row = QHBoxLayout()
        chrome_row.setSpacing(4)
        self.chrome_start_btn = QPushButton("启动 Chrome")
        self.chrome_start_btn.setObjectName("default")
        self.chrome_start_btn.clicked.connect(self._on_start_chrome)
        chrome_row.addWidget(self.chrome_start_btn, stretch=1)

        self.chrome_stop_btn = QPushButton("关闭 Chrome")
        self.chrome_stop_btn.setObjectName("danger_ghost")
        self.chrome_stop_btn.clicked.connect(self._on_stop_chrome)
        chrome_row.addWidget(self.chrome_stop_btn, stretch=1)
        left_layout.addLayout(chrome_row)

        # 2. 文件上传区（固定位置）
        self.file_drop_area = FileDropArea()
        self.file_drop_area.set_main_window(self)
        left_layout.addWidget(self.file_drop_area)

        # 文件列表容器
        self.file_list_container = QWidget()
        self.file_list_container.setVisible(False)
        self.file_list_layout = FlowLayout(spacing=4)
        self.file_list_layout.setContentsMargins(0, 0, 0, 0)
        self.file_list_container.setLayout(self.file_list_layout)
        left_layout.addWidget(self.file_list_container)

        # 3. AI 选择器（辕门外 + 中军帐）
        # 辕门外：按钮高度 2 倍
        self.ai_inactive_frame = QFrame()
        self.ai_inactive_frame.setObjectName("ai_inactive_frame")
        self.ai_inactive_frame.setFixedHeight(110)
        self.ai_inactive_outer_layout = QVBoxLayout(self.ai_inactive_frame)
        self.ai_inactive_outer_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_inactive_outer_layout.setSpacing(0)
        self.ai_inactive_title = QLabel("辕门外:")
        self.ai_inactive_title.setFixedHeight(18)
        self.ai_inactive_title.setStyleSheet("font-size: 11px; color: #86868B; background: transparent; border: none; padding-left: 6px;")
        self.ai_inactive_outer_layout.addWidget(self.ai_inactive_title)
        self.ai_inactive_inner = QWidget()
        inactive_layout = FlowLayout(spacing=4)
        inactive_layout.setContentsMargins(6, 2, 6, 4)
        self.ai_inactive_inner.setLayout(inactive_layout)
        self.ai_inactive_outer_layout.addWidget(self.ai_inactive_inner)
        self.ai_inactive_frame.setStyleSheet("""
            QFrame#ai_inactive_frame {
                background-color: #F5F5F7;
                border: 1.5px dashed #D2D2D7;
                border-radius: 6px;
            }
        """)
        self.ai_inactive_container = self.ai_inactive_inner
        left_layout.addWidget(self.ai_inactive_frame)

        # 中军帐：按钮高度 2 倍
        self.ai_active_frame = QFrame()
        self.ai_active_frame.setObjectName("ai_active_frame")
        self.ai_active_frame.setFixedHeight(110)
        self.ai_active_outer_layout = QVBoxLayout(self.ai_active_frame)
        self.ai_active_outer_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_active_outer_layout.setSpacing(0)
        self.ai_active_title = QLabel("中军帐:")
        self.ai_active_title.setFixedHeight(18)
        self.ai_active_title.setStyleSheet("font-size: 11px; color: #007AFF; font-weight: 600; background: transparent; border: none; padding-left: 6px;")
        self.ai_active_outer_layout.addWidget(self.ai_active_title)
        self.ai_active_inner = QWidget()
        active_layout = FlowLayout(spacing=4)
        active_layout.setContentsMargins(6, 2, 6, 4)
        self.ai_active_inner.setLayout(active_layout)
        self.ai_active_outer_layout.addWidget(self.ai_active_inner)
        self.ai_active_frame.setStyleSheet("""
            QFrame#ai_active_frame {
                background-color: #E8F2FF;
                border: 1.5px solid #007AFF;
                border-radius: 6px;
            }
        """)
        self.ai_active_container = self.ai_active_inner
        left_layout.addWidget(self.ai_active_frame)

        # 跟踪活跃 AI 列表
        self.active_ais = []

        # 弹簧：把所有内容推到顶部，底部不留空
        left_layout.addStretch(1)

        # 底部按钮（复制全文）
        copy_row = QHBoxLayout()
        copy_row.setSpacing(4)
        self.copy_all_btn = QPushButton("复制全文")
        self.copy_all_btn.setObjectName("small")
        self.copy_all_btn.clicked.connect(self._on_copy_all)
        copy_row.addWidget(self.copy_all_btn, stretch=1)
        left_layout.addLayout(copy_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(4)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("small")
        self.settings_btn.clicked.connect(self._on_open_settings)
        action_row.addWidget(self.settings_btn, stretch=1)
        self.clear_btn = QPushButton("清空记录")
        self.clear_btn.setObjectName("small")
        self.clear_btn.clicked.connect(self._on_clear)
        action_row.addWidget(self.clear_btn, stretch=1)
        left_layout.addLayout(action_row)

        splitter.addWidget(left_panel)

        # --- 右侧内容区 ---
        right_panel = QWidget()
        right_panel.setObjectName("right_panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(2)

        # 内容区：直接使用 HostedModeTab（单一模式）
        self.hosted_tab = HostedModeTab(self.config_mgr, self.chrome_mgr, self)
        right_layout.addWidget(self.hosted_tab, stretch=1)

        splitter.addWidget(right_panel)

        # 设置分栏比例（左侧适中，右侧宽）
        splitter.setSizes([240, 760])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # 限制左侧面板宽度范围
        left_panel.setMinimumWidth(200)
        left_panel.setMaximumWidth(300)

        main_layout.addWidget(splitter)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    def _build_menu(self):
        """构建菜单栏。"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件")
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self._on_open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Chrome 菜单
        chrome_menu = menubar.addMenu("Chrome")
        start_action = QAction("启动调试模式", self)
        start_action.triggered.connect(self._on_start_chrome)
        chrome_menu.addAction(start_action)
        stop_action = QAction("关闭", self)
        stop_action.triggered.connect(self._on_stop_chrome)
        chrome_menu.addAction(stop_action)

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------

    def _refresh_all(self):
        """刷新所有 UI 状态。"""
        self._refresh_chrome_status()
        self._refresh_platform_list()
        self.hosted_tab.refresh_platforms()

    def _refresh_chrome_status(self):
        """刷新 Chrome 和 AI 状态指示器。"""
        self._refresh_ai_status_indicator()

    def _refresh_ai_chips(self):
        """刷新 AI 芯片选择器：活跃区 + 非活跃区。"""
        all_platforms = self.config_mgr.get_ai_platforms()
        enabled_names = [p["name"] for p in all_platforms if p.get("enabled")]

        # 确保 active_ais 只包含已启用的平台
        self.active_ais = [n for n in self.active_ais if n in enabled_names]

        # 仅在首次初始化时加载默认 AI（从配置读取）
        # 用户手动移除所有 AI 后，不再自动重新加载
        if not self.active_ais and not getattr(self, '_ai_chips_initialized', False):
            defaults = self.config_mgr.config.get("discussion", {}).get("default_active_ais", ["DeepSeek", "智谱清言"])
            self.active_ais = [n for n in defaults if n in enabled_names]
            # 如果默认平台不够2个，补充其他已启用平台
            if len(self.active_ais) < 2:
                for n in enabled_names:
                    if n not in self.active_ais:
                        self.active_ais.append(n)
                        if len(self.active_ais) >= 2:
                            break
        self._ai_chips_initialized = True
        # 确保军师有效
        self._ensure_arbitrator()

        inactive_names = [n for n in enabled_names if n not in self.active_ais]

        # 清空图标引用
        self._ai_icons = {}
        # 清空芯片引用
        self._ai_chips = {}

        # 清空非活跃区
        layout = self.ai_inactive_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 填充非活跃区（带红色静止图标）
        if not inactive_names:
            empty_lbl = QLabel("（全部已加入）")
            empty_lbl.setObjectName("secondary")
            empty_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF;")
            layout.addWidget(empty_lbl)
        else:
            for name in inactive_names:
                chip = QWidget()
                chip.setObjectName("ai_chip_inactive")
                chip_layout = QHBoxLayout(chip)
                chip_layout.setContentsMargins(6, 1, 6, 1)
                chip_layout.setSpacing(4)

                # 红色静止图标
                red_icon = AISpinnerIcon(state="red")
                chip_layout.addWidget(red_icon)

                # AI 名称
                name_label = QLabel(name)
                name_label.setStyleSheet("font-size: 12px; color: #6B7280; font-weight: 500; background: transparent; border: none;")
                chip_layout.addWidget(name_label)

                chip.setStyleSheet("""
                    QWidget#ai_chip_inactive {
                        background-color: #FEF2F2;
                        border: 1px solid #FECACA;
                        border-radius: 5px;
                        min-height: 22px;
                        max-height: 28px;
                    }
                    QWidget#ai_chip_inactive:hover {
                        background-color: #FEE2E2;
                        border-color: #2563EB;
                    }
                """)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setToolTip("点击加入讨论")

                def _chip_mouse_press(event, n=name):
                    if event.button() == Qt.MouseButton.LeftButton:
                        self._on_ai_chip_click(n, activate=True)
                chip.mousePressEvent = _chip_mouse_press

                layout.addWidget(chip)

        # 清空活跃区
        active_layout = self.ai_active_container.layout()
        while active_layout.count():
            item = active_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 填充活跃区（带动态颜色图标）
        arbitrator = self.config_mgr.config.get("discussion", {}).get("arbitrator", "智谱清言")
        # 军师排在第一位
        sorted_active = sorted(self.active_ais, key=lambda n: (n != arbitrator, n))
        for name in sorted_active:
            chip = QWidget()
            chip.setObjectName("ai_chip_active")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(6, 1, 6, 1)
            chip_layout.setSpacing(4)

            # 动态颜色图标（根据缓存状态）
            color = self._get_ai_color(name)
            icon = AISpinnerIcon(state=color)
            self._ai_icons[name] = icon  # 保存引用以便后续更新
            chip_layout.addWidget(icon)
            # 保存芯片引用以便后续更新框体颜色
            self._ai_chips[name] = chip

            # AI 名称
            name_label = QLabel(name)
            name_label.setStyleSheet("font-size: 12px; color: #1E40AF; font-weight: 600; background: transparent; border: none;")
            chip_layout.addWidget(name_label)

            # 军师标记
            if name == arbitrator:
                arb_badge = QLabel("军师")
                arb_badge.setStyleSheet("""
                    font-size: 10px; font-weight: 700; color: #FFFFFF;
                    background-color: #F59E0B; border-radius: 3px;
                    padding: 0px 4px; min-height: 14px; max-height: 16px;
                """)
                chip_layout.addWidget(arb_badge)

            is_arb = (name == arbitrator)
            # 初始样式：未就绪统一橙色框（_update_ai_icon 会根据状态更新颜色）
            chip.setStyleSheet("""
                QWidget#ai_chip_active {
                    background-color: #FEF3C7;
                    border: 1px solid #F59E0B;
                    border-radius: 5px;
                    min-height: 22px;
                    max-height: 28px;
                }
            """)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            # tooltip 初始显示（后续由 _update_ai_icon 动态更新）
            msg = self._get_ai_status_msg(name)
            chip.setToolTip(f"⚠️ {msg}")

            # 鼠标点击事件：左键移出，右键设为军师
            def _chip_mouse_press(event, n=name):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._on_ai_chip_click(n, activate=False)
                elif event.button() == Qt.MouseButton.RightButton:
                    self._set_arbitrator(n)
            chip.mousePressEvent = _chip_mouse_press

            active_layout.addWidget(chip)

        # 创建完所有 chip 后，立即根据缓存状态同步颜色（防止刷新覆盖 green 状态）
        self._update_all_ai_icons()

    def _on_ai_chip_click(self, name: str, activate: bool):
        """AI 芯片点击：激活或移出，同时同步创建/销毁 AIWorker。"""
        all_platforms = self.config_mgr.get_ai_platforms()
        platform = next((p for p in all_platforms if p["name"] == name), None)
        if not platform:
            return
        url = platform.get("url", "")

        if activate:
            if name not in self.active_ais:
                self.active_ais.append(name)
            # 清除缓存，触发重新检测（包括思考模式）
            self._ai_state_cache.pop(name, None)
            self.chrome_mgr.clear_thinking_cache(name)
            # Chrome 运行时创建 AIWorker（会自动打开页面+监控）
            if self.chrome_mgr.is_chrome_running():
                self.worker.on_ai_added(name)
        else:
            if name in self.active_ais:
                self.active_ais.remove(name)
                # 销毁 AIWorker（会自动关闭页面）
                self.worker.on_ai_removed(name)
                # Chrome 运行时自动关闭对应网页
                if url and self.chrome_mgr.is_chrome_running():
                    self.worker.submit(self._sync_close_page(name, url))
        # 确保军师有效（移除军师后自动补位）
        self._ensure_arbitrator()
        self._refresh_ai_chips()

    def _set_arbitrator(self, name: str):
        """设置军师（右键点击中军帐 AI 触发）。"""
        if name not in self.active_ais:
            self._show_toast(f"{name} 不在中军帐内，无法设为军师")
            return
        self.config_mgr.set("discussion.arbitrator", name)
        self.config_mgr.save()
        self._arbitrator = name
        log_info(f"军师已设置为: {name}")
        self._show_toast(f"军师已设置为: {name}")
        self._refresh_ai_chips()

    def _ensure_arbitrator(self):
        """确保中军帐内有军师。
        - 0个AI：无军师
        - 1个AI：默认该AI为军师
        - 多个AI：如果当前军师不在中军帐内，自动设第一个为军师
        """
        if not self.active_ais:
            return
        current_arb = self.config_mgr.config.get("discussion", {}).get("arbitrator", "智谱清言")
        if current_arb in self.active_ais:
            self._arbitrator = current_arb
            return
        # 军师不在中军帐内，自动设第一个为军师
        new_arb = self.active_ais[0]
        self.config_mgr.set("discussion.arbitrator", new_arb)
        self.config_mgr.save()
        self._arbitrator = new_arb
        log_info(f"军师自动设置为: {new_arb}")
        self._show_toast(f"军师自动设置为: {new_arb}")

    async def _sync_close_page(self, name: str, url: str):
        """异步关闭 AI 平台网页。"""
        try:
            self.statusBar().showMessage(f"正在关闭 {name}...")
            await self.chrome_mgr.close_page(url)
            self.statusBar().showMessage(f"✅ {name} 已关闭", 3000)
            log_info(f"AI 芯片同步: 已关闭 {name} ({url})")
        except Exception as e:
            self.statusBar().showMessage(f"关闭 {name} 失败: {e}", 3000)
            log_warning(f"AI 芯片同步关闭 {name} 失败: {e}")

    def _refresh_platform_list(self):
        """刷新 AI 平台列表（兼容旧代码）。"""
        self._refresh_ai_chips()

    # ------------------------------------------------------------------
    # 按钮事件
    # ------------------------------------------------------------------

    def _on_start_chrome(self):
        """启动 Chrome（只发命令给工作线程，不阻塞 UI）。"""
        log_ui("用户点击「启动 Chrome」")
        self._ai_state_cache.clear()
        self.worker.do_start_chrome(list(self.active_ais))

    # _trigger_immediate_check 和 _auto_open_platforms 已移至 WorkerThread

    def _on_stop_chrome(self):
        """关闭 Chrome — 主线程只发命令，大脑线程执行。"""
        log_ui("用户点击「关闭 Chrome」")
        self._chrome_stopping = True
        self._start_in_progress = False
        self._discussion_running = False
        if hasattr(self, 'hosted_tab') and self.hosted_tab:
            self.hosted_tab.hosted = None
        # 只发命令给大脑线程，不执行任何耗时操作
        self.worker.do_stop_chrome()
        # 立即更新UI状态
        self.chrome_start_btn.setEnabled(False)
        self.chrome_stop_btn.setEnabled(False)
        self.statusBar().showMessage("正在关闭 Chrome...", 3000)

    def _on_open_settings(self):
        """打开设置弹窗。"""
        dialog = SettingsDialog(self.config_mgr, self)
        dialog.exec()
        # 无论保存还是取消，都刷新（启用/禁用等操作可能已即时保存）
        self.chrome_mgr.config = self.config_mgr.config
        self._refresh_all()

    # ------------------------------------------------------------------
    # 控件委托
    # ------------------------------------------------------------------

    def _on_upload(self):
        """上传文件（支持追加，不替换已有文件）。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择参考文件（可多选）", "",
            "文档 (*.txt *.md *.pdf *.docx *.csv *.json);;所有文件 (*)"
        )
        if paths:
            existing = list(self.hosted_tab._file_paths)
            for p in paths:
                if p not in existing:
                    existing.append(p)
            self._set_file_paths(existing)

    def _set_file_paths(self, paths: list):
        """设置文件路径列表：每个文件显示为一个可单独删除的 chip。"""
        self.hosted_tab._file_paths = list(paths)

        # 清空旧 chip
        while self.file_list_layout.count():
            item = self.file_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not paths:
            self.file_list_container.setVisible(False)
            self.file_drop_area.setVisible(True)
            return

        self.file_list_container.setVisible(True)

        for i, path in enumerate(paths):
            name = path.split('/')[-1]
            # 限制显示长度
            display_name = name if len(name) <= 16 else name[:14] + ".."

            chip = QFrame()
            chip.setObjectName("file_item_chip")
            chip.setStyleSheet("""
                QFrame#file_item_chip {
                    background-color: #E8F0FE;
                    border: 1px solid #007AFF;
                    border-radius: 5px;
                }
            """)
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(6, 2, 2, 2)
            chip_layout.setSpacing(3)

            label = QLabel(display_name)
            label.setStyleSheet("font-size: 11px; color: #1D1D1F; background: transparent; border: none;")
            label.setToolTip(path)
            label.setMaximumWidth(120)
            chip_layout.addWidget(label)

            # 删除按钮（只删这一个文件）
            remove_btn = QPushButton("x")
            remove_btn.setObjectName("icon")
            remove_btn.setFixedSize(18, 18)
            remove_btn.setFont(QFont("", 9))
            remove_btn.setStyleSheet("""
                QPushButton#icon {
                    min-width: 18px; min-height: 18px;
                    max-width: 18px; max-height: 18px;
                    font-size: 9px; color: #007AFF;
                    background: transparent; border: none;
                    border-radius: 4px; padding: 0px;
                }
                QPushButton#icon:hover {
                    background-color: #FF3B30;
                    color: #FFFFFF;
                }
            """)
            # 捕获当前索引
            remove_btn.clicked.connect(lambda checked, idx=i: self._on_remove_single_file(idx))
            chip_layout.addWidget(remove_btn)

            self.file_list_layout.addWidget(chip)

    def _on_remove_single_file(self, index: int):
        """删除单个指定文件。"""
        paths = list(self.hosted_tab._file_paths)
        if 0 <= index < len(paths):
            removed = paths.pop(index)
            log_info(f"删除文件: {removed}")
            self._set_file_paths(paths)

    def _on_remove_file(self):
        """删除已上传的所有文件。"""
        self.hosted_tab._file_paths = []
        self._set_file_paths([])

    def _on_stop(self):
        """结束讨论（委托给工作线程）。"""
        self.worker.do_stop_discussion()

    def _on_clear(self):
        """清空讨论记录，同时开启新对话 — 主线程只发命令。"""
        # 清空托管模式 Tab（UI操作，主线程做）
        self.hosted_tab._on_clear()
        # 清除文件
        self.hosted_tab._file_paths = []
        self._set_file_paths([])
        # 清除讨论历史 — 发命令给大脑线程
        self.worker.do_clear_history()
        # 在各活跃 AI 平台上开启新对话 — 发命令给大脑线程
        if not self.chrome_mgr.is_chrome_running():
            self.statusBar().showMessage("Chrome 未启动，无法开启新对话", 3000)
            return
        self.worker.submit(self._start_new_chats_async())

    async def _start_new_chats_async(self):
        """异步在所有活跃 AI 平台上开启新对话。"""
        self.statusBar().showMessage("正在开启新对话...")
        self.clear_btn.setEnabled(False)

        try:
            all_platforms = self.config_mgr.get_ai_platforms()
            for name in self.active_ais:
                platform = next((p for p in all_platforms if p["name"] == name), None)
                if not platform:
                    continue
                try:
                    page = await self.chrome_mgr.get_or_create_page(platform["url"])
                    await self.chrome_mgr.start_new_chat(page, platform)
                    log_info(f"已在 {name} 开启新对话")
                except Exception as e:
                    log_warning(f"在 {name} 开启新对话失败: {e}")

            self.statusBar().showMessage("✅ 已在所有 AI 平台开启新对话", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"开启新对话失败: {e}", 3000)
        finally:
            self.clear_btn.setEnabled(True)

    def _on_copy_all(self):
        """复制全部对话内容到剪贴板。"""
        from PyQt6.QtWidgets import QApplication
        text = self.hosted_tab.chat_stream.get_all_text()

        if not text.strip():
            self.statusBar().showMessage("没有对话内容可复制", 3000)
            return

        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.statusBar().showMessage("✅ 全部对话已复制到剪贴板", 3000)

    # ------------------------------------------------------------------
    # 关闭事件
    # ------------------------------------------------------------------

    def _cleanup_resources(self):
        """统一清理资源 — 程序退出时调用，不阻塞UI。"""
        if getattr(self, "_exiting", False):
            return
        self._exiting = True

        # 1. 停止状态监控线程（设置标志，不阻塞等待）
        try:
            if hasattr(self, "_status_monitor") and self._status_monitor is not None:
                self._status_monitor._running = False
        except Exception:
            pass

        # 2. 通知大脑线程停止（设置标志，不阻塞等待）
        try:
            if hasattr(self, "worker") and self.worker is not None:
                self.worker._running = False
                # 异步关闭Chrome（不阻塞）
                if self.worker._loop and self.worker._loop.is_running():
                    self.worker.submit(self.worker._async_stop_chrome_full())
        except Exception:
            pass

        # 3. 不在主线程同步关闭Chrome，交给大脑线程异步处理

    def closeEvent(self, event):
        """窗口关闭时完整清理资源，避免崩溃。"""
        self._cleanup_resources()

        # 接受关闭事件
        event.accept()

        # 清理后强制退出，避免 Python 析构过程中的崩溃
        # （QTimer、Playwright 子进程、asyncio 协程等在正常退出时会访问已销毁对象）
        import os
        os._exit(0)
