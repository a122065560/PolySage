# 聚慧 PolySage 产品技术规格说明书（AI 阅读版）

> 本文档面向 AI 模型/智能体阅读，旨在让 AI 在一次性阅读后完整理解 聚慧 PolySage 是什么工具、解决什么问题、有哪些功能、技术架构如何、核心逻辑怎样运转。

---

## 一、产品定位（一句话定义）

**聚慧 PolySage 是一款 macOS 原生桌面应用，让用户在零 API Key 的前提下，通过 Playwright 自动化控制多个已登录的 AI 网页（如 DeepSeek、智谱清言等），围绕用户提出的复杂议题进行多 AI 自主协作讨论，最终产出结构化方案。**

核心价值：
- **无需任何 API Key**：直接控制浏览器中已登录的 AI 网页，复用用户的网页版会员权益
- **多 AI 自主讨论**：不是简单的多模型并答，而是 AI 之间真正的多轮对话、质疑、补充
- **结案机制**：讨论充分后由指定 AI 整合最终方案，而非简单拼接

---

## 二、产品形态

| 维度 | 说明 |
|------|------|
| 平台 | macOS（Apple Silicon arm64），以 .dmg 安装包分发 |
| 技术栈 | Python 3.9+ / PyQt6（GUI）/ Playwright（浏览器自动化）/ qasync（异步集成）|
| 运行方式 | 双击 .app 启动，原生窗口，非 Web 应用 |
| 数据存储 | 配置文件：`~/.polysage/config.json`；日志：`~/.polysage/logs/` |
| 外部依赖 | Chrome 浏览器（应用以调试模式启动并控制它）；LM Studio（可选，本地模型增强）|

---

## 三、核心功能详解

### 3.1 托管模式（Hosted Mode）—— 全自动多 AI 讨论

这是产品的核心功能。流程如下：

1. **用户输入议题**：在底部输入框输入一个复杂议题（如"设计一个电商平台的推荐系统架构"），可选上传文件（.txt/.md/.csv）
2. **选择 2 位 AI**：从已启用的 AI 平台中选择 AI-A 和 AI-B（如 DeepSeek + 智谱清言）
3. **点击"开始讨论"**：应用自动执行以下流程
4. **Phase 1 - 打开页面**：确保两个 AI 的网页已打开
5. **Phase 2 - 初始化**：向 AI-A 发送开场白 + 议题，等待 AI-A 回复；将 AI-A 的回复转发给 AI-B
6. **Phase 3-4 - 多轮交替讨论**：
   - AI-A 回复 → 提取内容 → 转发给 AI-B（附上"对方观点"上下文）
   - AI-B 回复 → 提取内容 → 转发给 AI-A（附上"对方观点"上下文）
   - 每轮检测是否出现结束标记 `<End>`
7. **结束条件**：
   - 某方回复中出现 `<End>` 标记 → 该方认为讨论已充分
   - 达到最大轮数（默认 20 轮）
   - 超时（默认 600 秒/轮）
8. **结案整合**：根据结案方设置，产出最终方案

**关键设计——结束标记机制**：
- 结束标记默认为 `<End>`
- 在发送给 AI 的 prompt 中明确告知："当你认为讨论已经充分、可以得出最终结论时，请在回复末尾添加 `<End>`"
- 当**结案方**说了 `<End>`，讨论**立即结束**，提取其标记前的内容作为最终方案
- 当非结案方说了 `<End>`，需等待另一方也说 `<End>`（双方共识）后，由结案方整合最终方案

**关键设计——结案机制**：
- 结案方默认为"智谱清言"
- 结案方说了结束语 → 直接结束，其回复即为最终方案
- 非结案方说了结束语 → 等待另一方也说结束语 → 调用结案方整合完整对话历史，输出最终方案
- 结案方可设为 `auto`（取最后一条回复）、指定 AI 名称、或 `lm_studio`（本地模型）

### 3.2 追问模式（Continue Discussion）

讨论结束后，用户可以在输入框继续输入问题：
- 系统检测到讨论已结束但有历史 → 进入追问模式
- 复用已有的 HostedMode 实例和对话历史
- 向两位 AI 发送追问消息，继续讨论
- 追问中同样适用结案机制

### 3.3 用户插话（中途介入）

讨论进行中，用户可以随时在输入框输入消息：
- 消息会即时插入到当前讨论流中
- 系统将用户消息发送给当前正在等待的 AI
- AI 回复后继续原有的交替讨论流程

### 3.4 圆桌模式（Round Table Mode）—— 用户主导

与托管模式不同，圆桌模式由用户完全控制：
- 用户勾选 2-3 位 AI 参与
- 用户选择发送目标（某位 AI 或所有 AI）
- 用户手动输入消息，逐轮控制发言节奏
- 可随时插话、追问、引导方向
- 用户手动点击"结案"生成最终方案
- 可选接入 LM Studio 提供实时摘要和追问建议

### 3.5 AI 平台管理

- **预置平台**：DeepSeek、智谱清言（开箱即用）
- **自定义平台**：用户可添加任意 AI 网页平台，需配置：
  - 平台名称、URL
  - CSS 选择器（输入框、发送按钮、停止按钮、回复容器、登录指示器等）
- **启用/禁用**：每个平台可独立启用/禁用
- **登录检测**：通过 CSS 选择器检测页面是否已登录
- **活跃 AI**：从已启用平台中选择参与讨论的 AI（芯片式 UI，点击切换）
- **卸载/移除**：活跃 AI 可以随时移除（包括最后一个），讨论开始时会检查至少需要 2 个

### 3.6 文件上传

- 支持格式：`.txt`、`.md`、`.csv`
- 文件内容自动读取并拼接到议题前面一起发送给 AI
- 大文件自动截断（防止超出输入框限制）

### 3.7 LM Studio 本地模型增强（可选）

- 通过 OpenAI 兼容 API 接入本地 LM Studio
- 用途：提供第三方中立视角的摘要、追问建议
- 配置：服务地址（默认 `http://127.0.0.1:1234/v1`）、显示名称、API Key

---

## 四、技术架构

### 4.1 模块结构

```
polysage/
├── main.py              # 程序入口，初始化 QApplication + qasync 事件循环
├── ui_main_window.py    # PyQt6 主窗口（~1900行）：布局、设置弹窗、Tab页、事件处理
├── ui_widgets.py        # 自定义组件：聊天气泡 ChatBubble、对话流 ChatStream、输入框
├── ui_styles.py         # 全局 QSS 样式表（颜色变量、组件样式）
├── browser.py           # ChromeManager：启动/连接 Chrome 调试模式 + Playwright 页面控制
├── core.py              # HostedMode：托管模式核心逻辑（多轮讨论、结案、追问）
├── config_manager.py    # ConfigManager：config.json 加载/保存/验证/迁移
├── utils.py             # 工具函数：文件读取、文本清洗、结束标记检测、HTML解析
├── logger.py            # 日志模块：按日期滚动，info/warning/error
├── chrome_launcher      # Chrome 启动脚本
├── build_dmg.sh         # 打包脚本（PyInstaller + create-dmg）
├── Info.plist           # macOS 应用信息
├── AppIcon.icns         # 应用图标
├── logo_ui.png          # UI 内 logo
└── requirements.txt     # 依赖列表
```

### 4.2 异步架构（防止 UI 卡死的核心）

```
用户点击按钮 → async def 槽函数（通过 qasync 调度）
                    ↓
            await playwright 操作（Playwright 的 async API）
                    ↓
            await 期间控制权回到 Qt 事件循环 → UI 不卡死
                    ↓
            操作完成后继续执行 → 直接更新 UI 控件
```

关键技术点：
- `qasync.QEventLoop` 替换 Python 默认 asyncio 事件循环，将 asyncio 集成到 Qt 事件循环
- 所有 Playwright 操作使用 `async/await`，不阻塞 UI 线程
- UI 更新直接在 async 函数中执行，无需跨线程信号（qasync 保证线程安全）

### 4.3 浏览器控制架构

```
ChromeManager
├── launch_chrome()        # 以调试模式启动 Chrome（--remote-debugging-port=9222）
├── connect()              # 通过 CDP（Chrome DevTools Protocol）连接
├── get_or_create_page()   # 获取或创建 Playwright Page 对象
├── is_chrome_running()    # 检测 Chrome 调试模式是否运行
└── send_and_wait()        # 核心：发送消息 + 等待 AI 回复完成
    ├── 填充输入框
    ├── 点击发送按钮
    ├── 轮询检测回复完成（停止按钮消失 / 回复内容稳定 / 思考模式处理）
    ├── 提取最后一条回复文本
    └── 返回回复内容
```

**回复完成检测策略**（多信号融合）：
1. 停止按钮消失（如果配置了 stop_button 选择器）
2. 回复内容连续 N 次轮询不变（内容稳定）
3. 思考模式特殊处理（DeepSeek/智谱清言的深度思考模式有独立的思考块，需等思考完成后再等正文完成）

### 4.4 配置文件结构（config.json）

```json
{
  "chrome": {
    "debug_port": 9222,
    "user_data_dir": "~/.polysage/chrome-data"
  },
  "discussion": {
    "end_signal": "<End>",
    "max_rounds": 20,
    "timeout_seconds": 600,
    "arbitrator": "智谱清言",
    "opening_remarks": "你正在参与一场多AI群聊协作..."
  },
  "lm_studio": {
    "enabled": false,
    "url": "http://127.0.0.1:1234/v1",
    "display_name": "MyAi",
    "api_key": ""
  },
  "ai_platforms": [
    {
      "name": "DeepSeek",
      "url": "https://chat.deepseek.com/",
      "enabled": true,
      "selectors": {
        "input_textarea": "textarea",
        "send_button": "...",
        "stop_button": "...",
        "response_container": "...",
        "last_response": "...",
        "login_indicator": "...",
        "login_button": "..."
      }
    }
  ],
  "selected_ais": []
}
```

### 4.5 打包流程

- **PyInstaller**：将 Python 项目打包为 .app（`--windowed --target-arch arm64`）
- **资源打包**：logo_ui.png、logo_ui@2x.png 通过 `--add-data` 打包进 app
- **资源路径**：`utils.resource_path()` 函数兼容开发模式和 PyInstaller 打包模式（`sys._MEIPASS`）
- **图标**：AppIcon.icns 通过 `--icon` 设置，包含 16~1024px 全尺寸
- **签名**：codesign 自签名
- **DMG**：hdiutil 生成 .dmg 安装包

---

## 五、UI 界面结构

### 5.1 主窗口布局

```
┌─────────────────────────────────────────────────────┐
│ 菜单栏（文件 / Chrome / 帮助）                        │
├──────────┬──────────────────────────────────────────┤
│ 左侧栏    │ 右侧主区域（Tab 页）                       │
│          │                                          │
│ AI就绪   │ ┌──────────────────────────────────────┐ │
│ 指示器   │ │ Tab: 托管模式 | 圆桌模式              │ │
│          │ ├──────────────────────────────────────┤ │
│ AI芯片   │ │                                      │ │
│ (活跃AI) │ │         对话流区域                    │ │
│          │ │    （AI消息气泡拉满宽度）              │ │
│ 议题输入 │ │                                      │ │
│ 文件上传 │ │                                      │ │
│ 开始讨论 │ │                                      │ │
│ 停止按钮 │ ├──────────────────────────────────────┤ │
│          │ │ 即时状态栏（等待XX回复...）           │ │
│          │ ├──────────────────────────────────────┤ │
│          │ │ 输入框 + 发送按钮                     │ │
│          │ └──────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────┘
```

### 5.2 设置弹窗

设置弹窗包含以下区域：
- **AI 平台管理**：平台列表、添加/编辑/删除平台、启用/禁用
- **讨论参数**：结束标记、最大轮数、超时时间、结案方（下拉框+ⓘ提示）、开场白
- **LM Studio 配置**：启用开关、服务地址、显示名称、API Key
- **日志管理**：日志文件下拉、展开日志（弹窗查看）、删除日志、打开日志目录

### 5.3 设计语言

- **配色**：浅色主题，主色蓝（#1E40AF），背景白/浅灰
- **AI 消息气泡**：灰色背景（#E8E8ED），拉满对话流宽度，左下小圆角
- **用户消息气泡**：蓝色背景（#3B82F6），右对齐
- **状态消息**：居中灰色文字
- **即时状态栏**：输入框上方，浅蓝背景，实时显示"等待 XX 回复..."

---

## 六、核心流程伪代码

### 6.1 托管模式讨论流程

```python
async def run(topic, ai_a, ai_b, progress_callback):
    # Phase 1: 打开页面
    page_a = await chrome.get_or_create_page(ai_a.url)
    page_b = await chrome.get_or_create_page(ai_b.url)

    # Phase 2: 初始化 - 向 AI-A 发送开场白+议题
    opening = opening_remarks + "\n\n议题：" + topic
    reply_a = await chrome.send_and_wait(page_a, ai_a, opening)
    history.append({"name": ai_a.name, "content": reply_a})

    # 将 AI-A 的回复转发给 AI-B
    prompt_b = f"以下是 {ai_a.name} 的观点：\n{reply_a}\n\n请回应..."
    reply_b = await chrome.send_and_wait(page_b, ai_b, prompt_b)
    history.append({"name": ai_b.name, "content": reply_b})

    # Phase 3-4: 多轮交替讨论
    a_done = False
    b_done = True  # AI-B 已回复，等待 AI-A
    for round in range(max_rounds):
        # 当前接收方 = 轮换
        current_receiver = ai_a if b_done else ai_b
        other_reply = history[-1]["content"]

        prompt = f"以下是 {other_ai.name} 的观点：\n{other_reply}\n\n请回应..."
        reply = await chrome.send_and_wait(page, current_receiver, prompt)
        history.append(...)

        # 检测结束标记
        if "<End>" in reply:
            # 如果是结案方说的 → 立即结束
            if current_receiver.name == arbitrator:
                return final_result = extract_before(reply, "<End>")
            # 否则标记该方完成
            if current_receiver == ai_a: a_done = True
            else: b_done = True
            # 双方都说 End → 调用结案方整合
            if a_done and b_done:
                final = await resolve_arbitrator(arbitrator, history)
                return final

    # 超过最大轮数
    return timeout_result
```

### 6.2 追问流程

```python
async def continue_discussion(user_message, progress_callback):
    # 复用已有的对话历史
    # 向当前轮次的接收方发送用户追问
    prompt = f"用户追问：{user_message}"
    reply = await chrome.send_and_wait(page, current_receiver, prompt)
    # 继续原有的交替讨论 + 结束标记检测 + 结案逻辑
```

### 6.3 结案整合

```python
async def resolve_arbitrator(arbitrator_name, history, last_reply, ai_a, ai_b, page_a, page_b):
    if arbitrator_name == "auto":
        return extract_before_signal(last_reply, end_signal)

    # 指定 AI 结案
    full_history_text = format_history_for_arbitrator(history)
    prompt = f"以下是多AI讨论的完整记录：\n{full_history_text}\n\n请整合为最终结构化方案。"

    if arbitrator_name == "lm_studio":
        return await lm_studio.complete(prompt)
    else:
        # 找到结案方的页面
        page = page_a if arbitrator_name == ai_a.name else page_b
        return await chrome.send_and_wait(page, ai_config, prompt)
```

---

## 七、Prompt 工程

### 7.1 开场白（发送给第一个 AI）

```
你正在参与一场多AI群聊协作。
请等待用户提出复杂议题（如项目架构、创作大纲等），
需要你与其他AI展开深度推演：质疑细节、补充边界、提供替代方案。
请分轮次讨论，不急于给出最终结论。当多方确认讨论充分后，再整合为结构化方案。

议题：{用户输入的议题}
{上传文件内容（如果有）}

结束标记说明：当你认为讨论已经充分、可以得出最终结论时，请在回复末尾添加 <End>
```

### 7.2 交替讨论 Prompt

```
以下是 {对方AI名称} 的观点：
{对方AI的最新回复}

请回应、质疑或补充。当你认为讨论已经充分时，在回复末尾添加 <End>。
```

### 7.3 结案方 Prompt

```
以下是多AI讨论的完整记录：
{格式化的对话历史}

请基于以上讨论，整合为最终的结构化方案。
```

---

## 八、容错与恢复机制

| 场景 | 处理方式 |
|------|----------|
| Chrome 未启动 | 提示用户点击"启动 Chrome"按钮 |
| 页面被关闭 | `send_and_wait` 中检测 `page.is_closed()`，自动重新获取页面 |
| 元素未找到 | 自动尝试备选 CSS 选择器，失败后提示"网页可能已更新" |
| AI 回复超时 | 弹窗让用户选择"继续等待"或"放弃本轮" |
| Playwright 连接失败 | 自动重试 3 次 |
| 配置文件损坏 | 回退到默认配置 |
| 旧版配置迁移 | 自动将旧结束标记 `<已得出最终结果>` 迁移为 `<End>`，旧超时 120s 迁移为 600s |
| 结案方页面不可用 | 错误提示，讨论终止 |

---

## 九、日志系统

- **日志目录**：`~/.polysage/logs/`
- **日志格式**：`polysage_YYYYMMDD.log`（按日期滚动）
- **日志级别**：INFO / WARNING / ERROR
- **日志内容**：
  - 用户操作（启动 Chrome、开始讨论、发送消息）
  - AI 回复摘要（前 100 字符）
  - 状态变更（轮次切换、结束标记检测、结案）
  - 错误详情（异常堆栈、Playwright 错误）
- **日志查看**：设置弹窗中可选择日志文件，点击"展开日志"弹窗查看完整内容

---

## 十、与同类产品的区别

| 特性 | 聚慧 PolySage | 普通 AI 聊天工具 | 多模型并答工具 |
|------|---------------|-----------------|---------------|
| API Key | 不需要 | 需要 | 需要 |
| 多 AI 交互 | AI 之间真实对话 | 单一 AI | 并行独立回答 |
| 讨论深度 | 多轮深度推演 | 单轮 | 单轮 |
| 结案整合 | 有（指定 AI 整合） | 无 | 无 |
| 用户介入 | 支持中途插话/追问 | 不适用 | 不适用 |
| 运行成本 | 零（复用网页会员） | API 费用 | API 费用 |

---

## 十一、当前版本已知特性

- 默认预置 DeepSeek 和智谱清言两个平台
- 默认结案方为智谱清言
- 默认结束标记为 `<End>`
- 默认超时 600 秒/轮，最大 20 轮
- 默认窗口尺寸 1400×900，最小 1200×850
- 应用图标为白底渐变圆（蓝→粉），带 macOS 标准安全边距
- 支持追问模式（讨论结束后继续输入即可追问）
- 支持用户插话（讨论进行中输入即可插话）

---

## 十二、总结

聚慧 PolySage 的本质是一个**多 AI 自主协作编排器**：

1. **输入**：用户的复杂议题 + 选择的多个 AI 平台
2. **处理**：通过浏览器自动化，让 AI 之间进行多轮真实对话，互相质疑、补充、推演
3. **输出**：经过结案方整合的结构化最终方案

它不依赖任何 API Key，通过 Playwright 控制用户已登录的 AI 网页实现自动化，让多个 AI 像圆桌会议一样真正"讨论"问题，而非简单的并行问答。
