# 🪑 聚慧 PolySage

**Multi-Agent Collaborator · 多AI协作器**

聚慧 PolySage 是一款开源的 macOS **原生桌面应用**，用户无需任何 API Key，即可通过 Playwright 控制已登录的 AI 网页（如 DeepSeek、智谱清言等），围绕用户话题进行多 AI 讨论，最终产出结构化方案。

## ✨ 功能特性

- **原生桌面应用**：基于 PyQt6，双击即运行，流畅不卡顿
- **零 API Key**：纯本地运行，所有操作通过浏览器控制完成
- **托管模式**：2 位 AI 全自动讨论，哨兵标记结束，支持灵活的结案机制
- **圆桌模式**：用户主导，2-3 位 AI 参与，手动控制发言节奏，实时引导讨论
- **结案机制**：三种模式（auto / 指定AI / LM Studio），适配不同场景
- **本地模型增强**：可选接入 LM Studio，提供实时摘要和追问建议
- **文件上传**：支持 .txt / .md / .csv 格式，自动拼接到话题前发送
- **异步不卡顿**：qasync 集成 asyncio 与 PyQt6 事件循环，Playwright 操作不阻塞 UI

## 📦 环境准备

- **Python** 3.9+
- **Chrome 浏览器**（应用会自动检测路径）
- **LM Studio**（可选，用于本地模型增强）

## 🚀 安装步骤

```bash
# 克隆仓库
git clone https://github.com/yourname/polysage.git
cd polysage

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

## 🎮 启动应用

```bash
python main.py
```

应用窗口将直接弹出，无需浏览器。

## ⚙️ 一次性配置

### 1. 启动 Chrome 调试模式

点击左侧栏 **"🚀 启动 Chrome"** 按钮，或菜单栏 **Chrome → 🚀 启动调试模式**。Chrome 将以调试模式启动（端口 9222），支持 Playwright 远程控制。

### 2. 添加 / 配置 AI 平台

点击 **"⚙️ 设置"** → **"➕ 添加"**，填写平台名称、URL 和 CSS 选择器。

### 3. 启用并登录检测

在左侧 AI 平台列表中点击 **"启用"**，然后点击 **"🔍"** 检测登录：
- 🟢 已登录 → 可直接使用
- 🟡 未登录 → 在弹出的 Chrome 窗口中手动登录，然后重新检测

### 4. （可选）配置 LM Studio

在设置弹窗中启用 LM Studio，配置服务地址和显示名称。

## 📖 使用说明

### 托管模式（全自动）

1. 选择 2 位已启用的 AI（AI-A 和 AI-B）
2. 输入讨论话题（可选上传 .txt / .md / .csv 文件）
3. 点击 **"🚀 开始讨论"**
4. AI 自动交替讨论，直至某 AI 发出哨兵标记 `<已得出最终结果>` 或达到最大轮数
5. 根据结案机制产出最终方案并高亮展示

### 圆桌模式（用户主导）

1. 勾选 2-3 位参与的 AI
2. 选择发送目标（某位 AI 或所有 AI）
3. 在底部输入框输入消息，按 Enter 或点击 **"📤 发送"**
4. 应用自动发送消息并等待回复，展示在对话流中
5. 用户可随时插话、追问、引导方向
6. 点击 **"📌 结案"** 生成最终方案

### 结案机制说明

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `auto`（默认） | 谁先发出哨兵标记，提取其标记前的内容作为最终方案 | 最自动化，适合大多数用户 |
| 指定AI名称 | 将完整对话历史发给指定 AI，由其汇总输出 | 用户有明确偏好 |
| `lm_studio` | 将对话历史发给本地 LM Studio 模型综合输出 | 追求第三方中立视角 |

## 🔧 macOS 权限设置

系统设置 → 隐私与安全性 → 辅助功能 → 添加终端 / iTerm

## 🤖 如何添加新 AI 平台

1. 在 Chrome 中打开目标 AI 网页并登录
2. 在网页上右键点击 → **"检查"**，打开开发者工具
3. 找到输入框和发送按钮，右键点击 → **Copy** → **Copy selector**
4. 在应用设置中添加新 AI 平台，填入 URL 和选择器

### 选择器配置示例

**DeepSeek:**
- URL: `https://chat.deepseek.com/`
- 输入框: `textarea`
- 发送按钮: `div[role='button']:has(svg)`

**智谱清言:**
- URL: `https://chatglm.cn/`
- 输入框: `textarea`
- 发送按钮: `button:has-text('发送')`

## 🏗️ 技术架构

| 组件 | 技术 | 说明 |
|------|------|------|
| UI 框架 | PyQt6 | 原生桌面界面，左右分栏 + Tab 布局 |
| 异步集成 | qasync | 将 asyncio 循环集成到 Qt 事件循环，防止 UI 卡死 |
| 浏览器控制 | Playwright | 通过 CDP 连接 Chrome 调试模式 |
| 本地模型 | OpenAI SDK | 兼容 LM Studio 接口 |
| 配置管理 | json | config.json 读写 |

### 防止界面卡死的核心设计

```
用户点击按钮 → async def 槽函数
                    ↓
            await playwright 操作（不阻塞 Qt 事件循环）
                    ↓
            UI 更新（直接操作控件，qasync 保证线程安全）
```

- 所有 Playwright 操作在 `async def` 槽函数中通过 `await` 执行
- `qasync.QEventLoop` 替换默认事件循环，`await` 时控制权回到 Qt
- UI 更新直接在槽函数中执行，无需跨线程信号

## 📁 项目结构

```
polysage/
├── main.py             # 程序入口，初始化 qasync 事件循环
├── ui_main_window.py   # PyQt6 主窗口及组件布局（含设置弹窗）
├── ui_widgets.py       # 自定义聊天气泡组件（QFrame / ChatStream）
├── browser.py          # ChromeManager：启动/连接Chrome + Playwright控制器
├── core.py             # 托管模式主循环 + 结案机制
├── roundtable.py       # 圆桌模式核心逻辑（用户主导 + LM Studio辅助）
├── config_manager.py   # ConfigManager：加载/保存/验证config.json
├── utils.py            # 工具函数：文件读取、文本清洗、哨兵标记检测
├── requirements.txt    # 项目依赖
└── README.md           # 项目文档
```

## 🐛 故障排查

| 问题 | 解决方案 |
|------|----------|
| Chrome 未启动 | 点击 "启动 Chrome" 按钮 |
| 9222 端口被占用 | 检查端口是否被占用，或更改配置中的端口号 |
| Playwright 连接失败 | 自动重试 3 次，失败后提示检查 Chrome 调试模式 |
| 元素未找到 | 自动尝试备选定位器，失败后弹窗提示 "网页可能已更新" |
| LM Studio 未启动 | 提示先启动 LM Studio 并加载模型 |
| 超时（120秒） | 弹窗提示选择 "继续等待" 或 "放弃本轮" |
| 文件读取失败 | 检查文件格式（仅支持 .txt, .md, .csv） |
| UI 卡死 | 确认使用的是 qasync 事件循环（main.py 已配置） |

## 📄 开源协议

MIT License
