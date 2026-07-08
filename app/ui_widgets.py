"""
ui_widgets - 自定义聊天气泡组件

基于 QFrame 实现的聊天气泡，支持用户消息、AI回复、系统状态、最终方案
四种样式，自动根据角色调整对齐方式、背景色和圆角。
"""

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QWidget,
    QSizePolicy,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPalette


# ======================================================================
# 单条聊天气泡
# ======================================================================

class ChatBubble(QFrame):
    """
    单条聊天气泡。

    role 取值：
        "user"   → 右对齐，蓝色背景
        "ai"     → 左对齐，灰色背景，显示 AI 名称
        "system" → 居中，浅黄背景
        "result" → 居中，绿色背景
    """

    # 各角色样式表（使用 ui_styles 中的统一定义）
    _STYLES = {
        "user": """
            ChatBubble {
                background-color: #007AFF;
                border-radius: 16px 16px 4px 16px;
                padding: 10px 14px;
                margin-left: 60px;
            }
            QLabel { color: #FFFFFF; }
            QLabel#name_label { color: #93C5FD; font-size: 11px; font-weight: bold; }
            QLabel#content_label { color: #FFFFFF; }
        """,
        "ai": """
            ChatBubble {
                background-color: #E8E8ED;
                border-radius: 16px 16px 16px 4px;
                padding: 10px 14px;
            }
            QLabel#name_label { color: #007AFF; font-size: 11px; font-weight: bold; }
            QLabel#content_label { color: #1D1D1F; }
        """,
        "system": """
            ChatBubble {
                background-color: #FFF8E1;
                border: 1px solid #FFE082;
                border-radius: 12px;
                padding: 6px 12px;
            }
            QLabel { color: #795548; font-size: 12px; }
        """,
        "result": """
            ChatBubble {
                background-color: #D4F5DC;
                border: 2px solid #34C759;
                border-radius: 16px;
                padding: 12px 16px;
            }
            QLabel#name_label { color: #1B7A3A; font-size: 13px; font-weight: bold; }
            QLabel#content_label { color: #1A3A2A; }
        """,
    }

    def __init__(self, role: str, name: str, content: str, parent=None):
        """
        Args:
            role: 消息角色 ("user" / "ai" / "system" / "result")
            name: 发送者名称（AI 名称 / "用户" / "系统" / "最终方案"）
            content: 消息文本
        """
        super().__init__(parent)
        self.role = role
        self._build_ui(name, content)

    def _build_ui(self, name: str, content: str):
        self._content_text = content  # 保存原始内容供复制使用

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # AI 消息和结果消息显示名称标签 + 复制按钮（右上角）
        if self.role in ("ai", "result"):
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(4)

            name_label = QLabel(f"【{name}】")
            name_label.setObjectName("name_label")
            name_label.setFont(QFont("", -1, QFont.Weight.Bold))
            header_layout.addWidget(name_label)
            header_layout.addStretch(1)

            # 复制按钮
            copy_btn = QPushButton("复制")
            copy_btn.setFixedSize(40, 20)
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(0, 0, 0, 0.06);
                    color: #6B7280;
                    border: none;
                    border-radius: 10px;
                    font-size: 10px;
                    padding: 0px 6px;
                }
                QPushButton:hover {
                    background-color: rgba(0, 122, 255, 0.15);
                    color: #007AFF;
                }
            """)
            copy_btn.clicked.connect(self._copy_content)
            header_layout.addWidget(copy_btn)

            layout.addLayout(header_layout)

        # 内容标签（支持多行、自动换行、选中文本）
        content_label = QLabel(content)
        content_label.setObjectName("content_label")
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(content_label)

        # AI 回复添加元信息（时间）
        if self.role == "ai":
            from datetime import datetime
            now_str = datetime.now().strftime("%H:%M:%S")
            meta_label = QLabel(now_str)
            meta_label.setObjectName("meta_label")
            meta_label.setStyleSheet("color: #9CA3AF; font-size: 10px; background: transparent; border: none;")
            layout.addWidget(meta_label)

        # 应用样式
        self.setStyleSheet(self._STYLES.get(self.role, self._STYLES["system"]))

        # 对齐方式
        if self.role == "user":
            self.setLayoutAlignment(Qt.AlignmentFlag.AlignRight)
        elif self.role in ("system", "result"):
            self.setLayoutAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.setLayoutAlignment(Qt.AlignmentFlag.AlignLeft)

        # 大小策略
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _copy_content(self):
        """复制当前气泡的内容到剪贴板。"""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self._content_text)
        # 临时改变按钮文字提示
        btn = self.sender()
        if btn:
            btn.setText("已复制")
            QTimer.singleShot(1500, lambda: btn.setText("复制"))

    def setLayoutAlignment(self, alignment):
        """在父布局中的对齐方式（通过 sizePolicy 间接实现）。"""
        sp = self.sizePolicy()
        if alignment == Qt.AlignmentFlag.AlignRight:
            sp.setHorizontalPolicy(QSizePolicy.Policy.Maximum)
            sp.setHorizontalStretch(1)
        elif alignment == Qt.AlignmentFlag.AlignCenter:
            sp.setHorizontalPolicy(QSizePolicy.Policy.Maximum)
        else:
            # AI 消息：拉满宽度
            sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            sp.setHorizontalStretch(1)
        self.setSizePolicy(sp)


# ======================================================================
# 聊天消息流容器（可滚动）
# ======================================================================

class ChatStream(QScrollArea):
    """
    可滚动的聊天消息流容器。

    自动在底部追加消息，并滚动到最新内容。
    提供 append_message / append_status / append_result / clear 方法。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._msg_counter = 0  # 消息编号计数器
        self._counting_enabled = False  # 是否开始编号（正式讨论开始后启用）
        self._auto_scroll = True  # 是否自动滚动到底部（用户手动上滚后暂停）
        self._build_ui()

    def _build_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 内部容器
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)
        # 弹簧，使消息从顶部开始排列
        self._layout.addStretch(1)
        self.setWidget(self._container)

        # 悬浮"回到底部"按钮
        self._scroll_btn = QPushButton("↓ 回到最新", self)
        self._scroll_btn.setFixedSize(110, 32)
        self._scroll_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scroll_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(59, 130, 246, 0.9);
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: rgba(59, 130, 246, 1.0);
            }
        """)
        self._scroll_btn.clicked.connect(self._on_scroll_btn_clicked)
        self._scroll_btn.hide()

        # 监听滚动条变化，检测用户手动滚动
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        # 监听滚动范围变化：新内容添加时，如果auto_scroll=True则自动滚到底部
        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)

    def _on_range_changed(self, _min, _max):
        """滚动范围变化（新内容添加）时，如果auto_scroll=True则滚到底部。"""
        if self._auto_scroll:
            self.verticalScrollBar().setValue(_max)

    def append_message(self, role: str, name: str, content: str):
        """
        追加一条消息。

        Args:
            role: "user" / "ai" / "system" / "result"
            name: 发送者名称
            content: 消息文本
        """
        # 不再使用全局计数器，改为直接显示AI名称
        # 编号信息已在content中包含（如"[第4轮]"）
        display_name = name

        bubble = ChatBubble(role, display_name, content)
        # 在弹簧之前插入
        self._layout.insertWidget(self._layout.count() - 1, bubble)

        # 只有在自动滚动模式时才滚动到底部
        if self._auto_scroll:
            # 延迟滚动：等布局更新完成后再滚动，否则 scrollbar.maximum() 是旧值
            QTimer.singleShot(0, self._scroll_to_bottom)

    def start_counting(self):
        """开始消息编号（所有AI回复ok后，正式讨论开始时调用）。"""
        self._counting_enabled = True
        self._msg_counter = 0

    def stop_counting(self):
        """停止消息编号。"""
        self._counting_enabled = False

    def append_user(self, content: str):
        """快捷方法：追加主公消息。"""
        self.append_message("user", "主公", content)

    def append_ai(self, name: str, content: str):
        """快捷方法：追加 AI 回复。"""
        self.append_message("ai", name, content)

    def append_status(self, text: str):
        """快捷方法：追加系统状态。"""
        self.append_message("system", "系统", text)

    def append_result(self, title: str, content: str):
        """快捷方法：追加最终方案。"""
        self.append_message("result", title, content)

    def clear_messages(self):
        """清空所有消息。"""
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 保留底部弹簧
        # 重置编号计数器
        self._msg_counter = 0
        self._counting_enabled = False

    def get_all_text(self) -> str:
        """获取所有消息的纯文本（用于复制）。"""
        lines = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            # ChatBubble 有 role 属性
            if hasattr(widget, "role"):
                # 找到 name_label 和 content_label
                name_text = ""
                content_text = ""
                for child in widget.findChildren(QLabel):
                    if child.objectName() == "name_label":
                        name_text = child.text()
                    elif child.objectName() == "content_label":
                        content_text = child.text()
                if name_text:
                    lines.append(f"{name_text}\n{content_text}\n")
                else:
                    lines.append(f"{content_text}\n")
        return "\n".join(lines)

    def get_result_text(self) -> str:
        """获取最终结果消息的纯文本（用于复制）。"""
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            if hasattr(widget, "role") and widget.role == "result":
                content_text = ""
                for child in widget.findChildren(QLabel):
                    if child.objectName() == "content_label":
                        content_text = child.text()
                return content_text
        return ""

    def get_all_text(self) -> str:
        """获取全部对话内容的纯文本（用于复制全文）。"""
        lines = []
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if not item or not item.widget():
                continue
            widget = item.widget()
            if not hasattr(widget, "role"):
                continue
            role = widget.role
            # 获取名称标签和内容标签
            sender = ""
            content = ""
            for child in widget.findChildren(QLabel):
                if child.objectName() == "name_label":
                    sender = child.text()
                elif child.objectName() == "content_label":
                    content = child.text()
            if role == "user":
                lines.append(f"--- 发送提示 ---\n{content}\n")
            elif role == "user_message":
                lines.append(f"--- 主公插话 ---\n{content}\n")
            elif role in ("ai", "result"):
                lines.append(f"{sender}\n{content}\n")
            elif role == "system":
                pass  # 跳过状态消息
        return "\n".join(lines)

    def _scroll_to_bottom(self):
        """滚动到最底部。"""
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_scroll_changed(self, value):
        """滚动条变化时检测用户是否手动上滚。"""
        scrollbar = self.verticalScrollBar()
        max_val = scrollbar.maximum()
        # 如果离底部超过50像素，说明用户在看历史
        at_bottom = (max_val - value) <= 50

        if not at_bottom:
            # 用户在看历史 → 停止自动滚动，显示悬浮按钮
            self._auto_scroll = False
            self._scroll_btn.show()
        else:
            # 用户在底部 → 恢复自动滚动，隐藏悬浮按钮
            self._auto_scroll = True
            self._scroll_btn.hide()

    def _on_scroll_btn_clicked(self):
        """点击悬浮按钮回到底部并恢复自动滚动。"""
        self._auto_scroll = True
        # 延迟滚动确保布局已更新
        QTimer.singleShot(0, self._scroll_to_bottom)
        self._scroll_btn.hide()

    def resizeEvent(self, event):
        """窗口大小变化时重新定位悬浮按钮。"""
        super().resizeEvent(event)
        # 悬浮按钮放在右下角，距底部20px，距右侧20px
        btn_x = self.width() - self._scroll_btn.width() - 20
        btn_y = self.height() - self._scroll_btn.height() - 20
        self._scroll_btn.move(btn_x, btn_y)
        self._scroll_btn.raise_()


# ======================================================================
# AI 平台列表项
# ======================================================================

class AIPlatformItem(QWidget):
    """
    AI 平台列表项组件，显示在左侧 QListWidget 中。

    包含：状态图标、平台名称、启用/禁用按钮、登录检测按钮。
    """

    login_requested = pyqtSignal(str)  # 平台名称
    toggle_requested = pyqtSignal(str)  # 平台名称

    def __init__(self, name: str, enabled: bool, logged_in: bool = False, parent=None):
        super().__init__(parent)
        self.platform_name = name
        self._build_ui(name, enabled, logged_in)

    def _build_ui(self, name: str, enabled: bool, logged_in: bool):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # 状态图标
        self.status_label = QLabel()
        self._update_status_icon(enabled, logged_in)
        layout.addWidget(self.status_label)

        # 平台名称
        self.name_label = QLabel(name)
        self.name_label.setFont(QFont("", 13))
        layout.addWidget(self.name_label, stretch=1)

        # 启用/禁用按钮
        self.toggle_btn = QPushButton("禁用" if enabled else "启用")
        self.toggle_btn.setObjectName("small")
        self.toggle_btn.setFixedWidth(50)
        self.toggle_btn.clicked.connect(
            lambda: self.toggle_requested.emit(self.platform_name)
        )
        layout.addWidget(self.toggle_btn)

        # 登录检测按钮
        self.login_btn = QPushButton("...")
        self.login_btn.setObjectName("icon")
        self.login_btn.setFixedSize(28, 28)
        self.login_btn.setFont(QFont("", 14))
        self.login_btn.setToolTip("检测登录状态")
        self.login_btn.clicked.connect(
            lambda: self.login_requested.emit(self.platform_name)
        )
        layout.addWidget(self.login_btn)

    def _update_status_icon(self, enabled: bool, logged_in: bool):
        if enabled and logged_in:
            self.status_label.setText("🟢")
            self.status_label.setToolTip("已启用 · 已登录")
        elif enabled:
            self.status_label.setText("🟡")
            self.status_label.setToolTip("已启用 · 未登录")
        else:
            self.status_label.setText("⚪")
            self.status_label.setToolTip("未启用")

    def update_status(self, enabled: bool, logged_in: bool = False):
        """更新平台状态显示。"""
        self._update_status_icon(enabled, logged_in)
        self.toggle_btn.setText("禁用" if enabled else "启用")


# 延迟导入 QPushButton（避免顶部循环引用）
from PyQt6.QtWidgets import QPushButton
