<div align="center">

<h1 align="center"><img src="logo.png" width="28" height="28" style="vertical-align: middle; margin-right: 6px;" alt="聚慧"> 聚慧 PolySage</h1>

**多 AI 圆桌讨论桌面应用**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/平台-macOS%20%7C%20Windows-blue)](https://github.com/a122065560/聚慧/releases)
[![Release](https://img.shields.io/github/v/release/a122065560/聚慧)](https://github.com/a122065560/聚慧/releases)

</div>

---

## 简介

聚慧 PolySage 是一款桌面应用，让多个 AI（DeepSeek、智谱清言、通义千问、MiniMax、Kimi 等）围绕你提出的话题展开**多轮圆桌讨论**，互相质疑、补充、碰撞，最终产出结构化方案。

**无需任何 API Key** —— 应用通过 Playwright 控制已登录的 AI 网页完成一切操作。

## 核心特性

- **多 AI 圆桌讨论**：2-5 个 AI 同时参与，分轮次发言，军师+谋士角色分配
- **零配置开箱即用**：下载安装包即可使用，不需要 API Key
- **双模式**：托管模式（全自动讨论）+ 圆桌模式（用户主导引导）
- **结案机制**：讨论充分后自动整合结构化方案
- **文件上传**：支持上传 .txt / .md / .csv 文件作为讨论背景

## 快速开始

1. 安装后打开「聚慧」
2. 点击左侧「🚀 启动 Chrome」启动浏览器
3. 在弹出的 Chrome 中登录你要使用的 AI 平台
4. 回到应用，勾选已登录的 AI，输入话题
5. 点击「开始讨论」，AI 们自动展开圆桌讨论

## 下载安装

前往 [Releases 页面](https://github.com/a122065560/聚慧/releases) 下载最新版本：

| 文件 | 平台 | 说明 |
|------|------|------|
| `PolySage-v*-macOS.dmg` | macOS (Apple Silicon) | 双击安装 |
| `PolySage-v*-Windows.exe` | Windows x64 | 双击安装 |

## 技术栈

| 组件 | 技术 |
|------|------|
| 桌面框架 | Python + PyQt6 |
| 异步引擎 | qasync (asyncio + Qt 事件循环) |
| 浏览器控制 | Playwright (CDP 连接 Chrome) |
| 跨平台抽象 | PlatformAdapter (macOS / Windows) |
| CI/CD | GitHub Actions 双平台构建 |

## 开发

```bash
git clone https://github.com/a122065560/聚慧.git
cd PolySage/app
pip install -r requirements.txt
playwright install chromium
python main.py
```

打包构建（macOS）：

```bash
# 双击项目根目录的 build_app.command 即可生成 .app
# 或在终端执行：
cd PolySage
bash app/build_dmg.sh
```

---

<div align="center">

MIT License · Copyright © 2026 聚慧 PolySage

</div>
