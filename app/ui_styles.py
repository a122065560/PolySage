"""
聚慧 PolySage 全局 QSS 样式表

设计参考：macOS 原生设计语言
- 分层按钮体系：Primary / Secondary / Danger / Ghost / Icon / Small
- 圆角 + 微阴影，模拟 macOS 的柔和立体感
- 清晰的交互状态：hover / pressed / disabled / focus
- 优雅的输入框和列表
- 紧凑但不过小的间距
"""

# 主色调
ACCENT = "#007AFF"            # macOS 系统蓝
ACCENT_HOVER = "#0066CC"      # 悬停色（加深）
ACCENT_PRESSED = "#0055AA"    # 按下色（更深）
ACCENT_LIGHT = "#E8F2FF"      # 浅蓝背景
ACCENT_BORDER = "#0066CC"     # 蓝色边框

# 危险色
DANGER = "#FF3B30"            # macOS 系统红
DANGER_HOVER = "#E0342A"      # 危险悬停
DANGER_PRESSED = "#CC2D25"    # 危险按下
DANGER_LIGHT = "#FFE5E3"      # 浅红背景
DANGER_BORDER = "#E0342A"     # 红色边框

# 成功色
SUCCESS = "#34C759"           # macOS 系统绿
SUCCESS_LIGHT = "#E8FAF0"     # 浅绿背景

# 警告色
WARNING = "#FF9500"           # macOS 系统橙
WARNING_LIGHT = "#FFF3E0"     # 浅橙背景

# 中性色
BG_WINDOW = "#F5F5F7"         # macOS 窗口背景（Apple 灰）
BG_PANEL = "#FFFFFF"         # 面板背景
BG_INPUT = "#FFFFFF"         # 输入框背景
BG_HOVER = "#E8E8ED"         # 悬停背景
BG_PRESSED = "#D4D4D9"       # 按下背景
BG_GHOST_HOVER = "rgba(0,0,0,0.04)"  # 幽灵按钮悬停
BORDER = "#D2D2D7"           # macOS 标准边框（浅灰）
BORDER_FOCUS = "#007AFF"      # 聚焦边框（蓝色）
BORDER_LIGHT = "#E5E5EA"     # 轻边框

# 文字色
TEXT_PRIMARY = "#1D1D1F"      # 主文字（接近纯黑）
TEXT_SECONDARY = "#86868B"    # 次文字（中灰）
TEXT_TERTIARY = "#AEAEB2"     # 三级文字（浅灰）
TEXT_ON_ACCENT = "#FFFFFF"    # 蓝底白字

GLOBAL_QSS = f"""
/* ===== 全局 ===== */
QMainWindow, QWidget {{
    background-color: {BG_WINDOW};
    color: {TEXT_PRIMARY};
    font-size: 13px;
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
}}

/* ===== 对话框 ===== */
QDialog {{
    background-color: {BG_WINDOW};
    color: {TEXT_PRIMARY};
}}

/* ===== 按钮基础（所有按钮共享） ===== */
QPushButton {{
    min-height: 32px;
    padding: 6px 14px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    outline: none;
}}
QPushButton:focus {{
    border: 2px solid {BORDER_FOCUS};
    padding: 5px 13px;
}}

/* ===== Primary 主按钮（蓝色填充） ===== */
QPushButton#primary {{
    min-height: 36px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_ON_ACCENT};
    background-color: {ACCENT};
    border: none;
    border-radius: 8px;
}}
QPushButton#primary:hover {{
    background-color: {ACCENT_HOVER};
}}
QPushButton#primary:pressed {{
    background-color: {ACCENT_PRESSED};
    transform: scale(0.98);
}}
QPushButton#primary:disabled {{
    color: rgba(255,255,255,0.6);
    background-color: {BORDER};
}}

/* ===== Secondary 次按钮（白底 + 蓝色边框） ===== */
QPushButton#secondary {{
    min-height: 34px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    color: {ACCENT};
    background-color: {BG_PANEL};
    border: 1px solid {ACCENT};
    border-radius: 8px;
}}
QPushButton#secondary:hover {{
    background-color: {ACCENT_LIGHT};
}}
QPushButton#secondary:pressed {{
    background-color: #D0E3FF;
}}
QPushButton#secondary:disabled {{
    color: {TEXT_TERTIARY};
    background-color: {BG_WINDOW};
    border-color: {BORDER};
}}

/* ===== Default 默认按钮（灰底 + 灰色边框） ===== */
QPushButton#default {{
    min-height: 34px;
    padding: 7px 16px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#default:hover {{
    background-color: {BG_HOVER};
    border-color: #C0C0C5;
}}
QPushButton#default:pressed {{
    background-color: {BG_PRESSED};
    border-color: {BORDER};
}}
QPushButton#default:disabled {{
    color: {TEXT_TERTIARY};
    background-color: {BG_WINDOW};
    border-color: {BORDER_LIGHT};
}}

/* ===== Danger 危险按钮（红色填充） ===== */
QPushButton#danger {{
    min-height: 34px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    color: {TEXT_ON_ACCENT};
    background-color: {DANGER};
    border: none;
    border-radius: 8px;
}}
QPushButton#danger:hover {{
    background-color: {DANGER_HOVER};
}}
QPushButton#danger:pressed {{
    background-color: {DANGER_PRESSED};
}}
QPushButton#danger:disabled {{
    color: rgba(255,255,255,0.6);
    background-color: {BORDER};
}}

/* ===== Danger Ghost 危险幽灵按钮（无背景 + 红色文字） ===== */
QPushButton#danger_ghost {{
    min-height: 34px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    color: {DANGER};
    background-color: transparent;
    border: 1px solid {DANGER};
    border-radius: 8px;
}}
QPushButton#danger_ghost:hover {{
    background-color: {DANGER_LIGHT};
}}
QPushButton#danger_ghost:pressed {{
    background-color: #FFD0CC;
}}
QPushButton#danger_ghost:disabled {{
    color: {TEXT_TERTIARY};
    border-color: {BORDER_LIGHT};
}}

/* ===== Ghost 幽灵按钮（无背景，文字按钮） ===== */
QPushButton#ghost {{
    min-height: 32px;
    padding: 6px 10px;
    font-size: 13px;
    color: {ACCENT};
    background-color: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton#ghost:hover {{
    background-color: {BG_HOVER};
}}
QPushButton#ghost:pressed {{
    background-color: {BG_PRESSED};
}}
QPushButton#ghost:disabled {{
    color: {TEXT_TERTIARY};
}}

/* ===== Icon 图标按钮（正方形，紧凑） ===== */
QPushButton#icon {{
    min-width: 32px;
    min-height: 32px;
    max-width: 32px;
    max-height: 32px;
    padding: 0px;
    font-size: 16px;
    color: {TEXT_SECONDARY};
    background-color: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton#icon:hover {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}
QPushButton#icon:pressed {{
    background-color: {BG_PRESSED};
}}
QPushButton#icon:disabled {{
    color: {TEXT_TERTIARY};
}}

/* ===== Small 小按钮（紧凑场景：列表项内等） ===== */
QPushButton#small {{
    min-height: 28px;
    padding: 4px 12px;
    font-size: 12px;
    color: {TEXT_PRIMARY};
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QPushButton#small:hover {{
    background-color: {BG_HOVER};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton#small:pressed {{
    background-color: {BG_PRESSED};
}}
QPushButton#small:disabled {{
    color: {TEXT_TERTIARY};
    background-color: {BG_WINDOW};
    border-color: {BORDER};
}}

/* ===== 输入框 ===== */
QTextEdit, QLineEdit, QPlainTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT_LIGHT};
}}

/* ===== Radio 按钮（macOS 风格） ===== */
QRadioButton {{
    min-height: 36px;
    padding: 6px 10px;
    font-size: 13px;
    color: {TEXT_PRIMARY};
    background: transparent;
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 22px;
    height: 22px;
    border-radius: 11px;
    border: 2px solid #C4C4C8;
    background: {BG_PANEL};
}}
QRadioButton::indicator:hover {{
    border-color: {ACCENT};
}}
QRadioButton::indicator:checked {{
    border-color: {ACCENT};
    background: qradialgradient(
        cx: 0.5, cy: 0.5,
        radius: 0.5,
        fx: 0.5, fy: 0.5,
        stop: 0 {ACCENT},
        stop: 0.38 {ACCENT},
        stop: 0.4 {BG_PANEL},
        stop: 1 {BG_PANEL}
    );
}}

/* ===== 文件标签（上传后显示文件名+删除） ===== */
QFrame#file_chip {{
    background-color: {BG_HOVER};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 2px 4px;
}}
QTextEdit:focus, QLineEdit:focus, QPlainTextEdit:focus {{
    border: 1.5px solid {BORDER_FOCUS};
}}

/* ===== 下拉框 ===== */
QComboBox {{
    min-height: 28px;
    padding: 4px 12px;
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 13px;
    padding-right: 32px;
}}
QComboBox:hover {{
    border-color: #C0C0C5;
    background-color: #FBFBFC;
}}
QComboBox:focus {{
    border: 1.5px solid {BORDER_FOCUS};
}}
QComboBox:on {{
    border: 1.5px solid {BORDER_FOCUS};
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
}}
QComboBox::drop-down {{
    border: none;
    width: 32px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}
QComboBox::down-arrow {{
    image: none;
    border: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT_SECONDARY};
    margin-right: 10px;
}}
QComboBox:hover::down-arrow {{
    border-top-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 6px;
    outline: none;
    selection-background-color: {ACCENT_LIGHT};
    selection-color: {TEXT_PRIMARY};
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 4px 8px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {BG_HOVER};
}}

/* ===== 列表 ===== */
QListWidget {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    font-size: 13px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background-color: {BG_HOVER};
}}
QListWidget::item:selected {{
    background-color: {ACCENT_LIGHT};
    color: {TEXT_PRIMARY};
}}

/* ===== 滚动区域 ===== */
QScrollArea {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
}}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,0,0,0.2);
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(0,0,0,0.35);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: rgba(0,0,0,0.2);
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(0,0,0,0.35);
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ===== 标签 ===== */
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#secondary {{
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}

/* ===== 分隔线 ===== */
QFrame#separator {{
    background-color: {BORDER_LIGHT};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ===== 状态栏 ===== */
QStatusBar {{
    background-color: {BG_WINDOW};
    color: {TEXT_SECONDARY};
    font-size: 12px;
    border-top: 1px solid {BORDER_LIGHT};
}}

/* ===== 菜单栏 ===== */
QMenuBar {{
    background-color: {BG_WINDOW};
    color: {TEXT_PRIMARY};
    border-bottom: 1px solid {BORDER_LIGHT};
    padding: 2px 0;
}}
QMenuBar::item {{
    padding: 4px 10px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {BG_HOVER};
    border-radius: 4px;
}}

/* ===== 顶部标题栏 ===== */
QWidget#header_bar {{
    background-color: {BG_WINDOW};
    border-bottom: 1px solid {BORDER_LIGHT};
}}

/* ===== 分组框 ===== */
QGroupBox {{
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_PRIMARY};
}}

/* ===== 复选框 ===== */
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid {BORDER};
    background-color: {BG_PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

/* ===== SpinBox ===== */
QSpinBox {{
    min-height: 28px;
    padding: 4px 10px;
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 13px;
}}
QSpinBox:focus {{
    border: 1.5px solid {BORDER_FOCUS};
}}

/* ===== 对话框按钮盒 ===== */
QDialogButtonBox QPushButton {{
    min-height: 34px;
    padding: 7px 20px;
    font-size: 13px;
    border-radius: 8px;
}}
"""

# 聊天气泡样式
CHAT_BUBBLE_STYLES = {
    "user": f"""
        ChatBubble {{
            background-color: {ACCENT};
            border-radius: 16px 16px 4px 16px;
            padding: 10px 14px;
            margin-left: 60px;
        }}
        QLabel {{ color: {TEXT_ON_ACCENT}; }}
        QLabel#name_label {{ color: #93C5FD; font-size: 11px; font-weight: bold; }}
        QLabel#content_label {{ color: {TEXT_ON_ACCENT}; }}
    """,
    "ai": f"""
        ChatBubble {{
            background-color: {BG_HOVER};
            border-radius: 16px 16px 16px 4px;
            padding: 10px 14px;
            margin-right: 60px;
        }}
        QLabel#name_label {{ color: {ACCENT}; font-size: 11px; font-weight: bold; }}
        QLabel#content_label {{ color: {TEXT_PRIMARY}; }}
    """,
    "system": f"""
        ChatBubble {{
            background-color: #FFF8E1;
            border: 1px solid #FFE082;
            border-radius: 12px;
            padding: 6px 12px;
        }}
        QLabel {{ color: #795548; font-size: 12px; }}
    """,
    "result": f"""
        ChatBubble {{
            background-color: {SUCCESS_LIGHT};
            border: 1.5px solid {SUCCESS};
            border-radius: 16px;
            padding: 12px 16px;
        }}
        QLabel#name_label {{ color: #1B7A3A; font-size: 12px; font-weight: bold; }}
        QLabel#content_label {{ color: #1A3A2A; }}
    """,
}
