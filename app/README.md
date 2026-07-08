<div align="center">

# 🪑 聚慧 PolySage

**多 AI 圆桌讨论桌面应用 · Multi-AI Roundtable Discussion App**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-blue)](https://github.com/a122065560/PolySage/releases)
[![Release](https://img.shields.io/github/v/release/a122065560/PolySage)](https://github.com/a122065560/PolySage/releases)

</div>

---

## 中文说明

### 这是什么？

聚慧 PolySage 是一款桌面应用，让多个 AI（DeepSeek、智谱清言、通义千问、MiniMax、Kimi 等）围绕你提出的话题展开**多轮圆桌讨论**，互相质疑、补充、碰撞，最终产出结构化方案。

**无需任何 API Key** —— 应用通过 Playwright 控制已登录的 AI 网页完成一切操作。

### 核心特性

- **多 AI 圆桌讨论**：2-5 个 AI 同时参与，分轮次发言，军师+谋士角色分配
- **零配置开箱即用**：下载安装包即可使用，不需要 API Key
- **双模式**：托管模式（全自动讨论）+ 圆桌模式（用户主导引导）
- **结案机制**：讨论充分后自动整合结构化方案
- **文件上传**：支持上传 .txt / .md / .csv 文件作为讨论背景

### 快速开始

1. 安装后打开「聚慧 PolySage」
2. 点击左侧「🚀 启动 Chrome」启动浏览器
3. 在弹出的 Chrome 中登录你要使用的 AI 平台
4. 回到应用，勾选已登录的 AI，输入话题
5. 点击「开始讨论」，AI 们自动展开圆桌讨论

### 技术栈

| 组件 | 技术 |
|------|------|
| 桌面框架 | Python + PyQt6 |
| 异步引擎 | qasync (asyncio + Qt 事件循环) |
| 浏览器控制 | Playwright (CDP 连接 Chrome) |
| 跨平台抽象 | PlatformAdapter (macOS / Windows) |
| CI/CD | GitHub Actions 双平台构建 |

### 开发

```bash
git clone https://github.com/a122065560/PolySage.git
cd PolySage/app
pip install -r requirements.txt
playwright install chromium
python main.py
```

---

## English

### What is this?

PolySage is a desktop app that lets multiple AI assistants (DeepSeek, Zhipu, Tongyi, MiniMax, Kimi, etc.) engage in **multi-round roundtable discussions** around your topic — questioning, supplementing, and building on each other's ideas to produce a structured final proposal.

**No API Key required** — the app controls your logged-in AI web pages via Playwright.

### Key Features

- **Multi-AI Roundtable**: 2-5 AIs participate simultaneously, taking turns with strategist + advisor roles
- **Zero Config**: Download and run, no API Key needed
- **Dual Mode**: Autonomous mode (fully automated) + Roundtable mode (user-guided)
- **Case Closure**: Auto-generates structured proposal when discussion converges
- **File Upload**: Support .txt / .md / .csv files as discussion context

### Quick Start

1. Open PolySage after installation
2. Click "🚀 Launch Chrome" to start the browser
3. Log in to your AI platforms in the Chrome window
4. Back in the app, select AIs, enter your topic
5. Click "Start Discussion" — watch the roundtable unfold

### Tech Stack

Python + PyQt6 + Playwright + qasync, with cross-platform PlatformAdapter abstraction and GitHub Actions CI/CD.

### Development

```bash
git clone https://github.com/a122065560/PolySage.git
cd PolySage/app
pip install -r requirements.txt
playwright install chromium
python main.py
```

---

<div align="center">

MIT License · Copyright © 2026 PolySage

</div>
