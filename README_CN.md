<div align="center">

# Everything Capture

**本地优先的内容采集与个人知识库**

从任何设备抓取网址、文章、社交媒体帖子、视频和文本 — 提取、存储、整理，全部在你自己的机器上完成。

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_+_FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS_|_Linux-lightgrey?style=flat-square&logo=apple&logoColor=white)](https://github.com/agentenatalie/everything-capture)
[![GitHub stars](https://img.shields.io/github/stars/agentenatalie/everything-capture?style=flat-square&logo=github)](https://github.com/agentenatalie/everything-capture/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/agentenatalie/everything-capture?style=flat-square)](https://github.com/agentenatalie/everything-capture/commits/main)

[English](./README.md) · [项目主页](https://agentenatalie.github.io/everything-capture/)

</div>

---

## 为什么做这个

大多数「稍后阅读」服务把你的数据存在他们的服务器上。Everything Capture 把**所有内容、媒体和元数据存在你本机的 SQLite 数据库**里。可选的云端采集服务允许手机提交链接，但真正的内容提取始终在本地运行。

## 功能

| | 功能 | 说明 |
|---|---|---|
| 📥 | **多端采集** | Web UI（粘贴链接或 ⌘K 命令面板）、服务端 URL 提取 API |
| 📄 | **智能提取** | 文章正文、社交媒体（小红书、抖音、Twitter/X、微信公众号）、图片、视频 |
| 💾 | **本地媒体存储** | 所有媒体（图片、视频、封面）下载到本地磁盘 |
| 🔍 | **全文搜索** | SQLite FTS5 trigram 索引，中英文混合高速搜索 |
| 🗂️ | **文件夹整理** | 拖拽排序、多文件夹归类、批量操作 |
| 🤖 | **AI 助手** | 对话与 Agent 模式，知识库问答、内容分析、自动整理 |
| 🎙️ | **本地语音转录** | 设备端 mlx-whisper 语音转文字（Apple Silicon） |
| 👁️ | **OCR 识别** | macOS Vision 框架提取图片文字 + 识别二维码 |
| 📤 | **同步到 Notion/Obsidian** | 推送到你已有的知识管理工具 |
| 📱 | **云端收件箱** | 可选 — 自行部署轻量采集服务，手机/快捷指令投递链接 |
| 🖥️ | **桌面应用** | *开发中* — macOS .app 打包，支持代码签名和公证 |

## 快速开始

### 一键安装（推荐）

```bash
curl -O https://raw.githubusercontent.com/agentenatalie/everything-capture/main/setup.sh && bash setup.sh
```

自动完成 Python 3 安装、ffmpeg 安装、代码下载、依赖安装和服务启动。

### 手动安装

```bash
git clone https://github.com/agentenatalie/everything-capture.git
cd everything-capture
python3 -m venv backend/venv
backend/venv/bin/pip install -r requirements.txt
./run
```

浏览器访问 **http://localhost:8000** 即可使用。

### 系统依赖

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| Python 3.11+ | 后端运行时 | `brew install python3` / `apt install python3` |
| ffmpeg | 视频转录、字幕提取 | `brew install ffmpeg` / `apt install ffmpeg` |
| Swift（macOS 自带） | 图片 OCR + 二维码识别 | `xcode-select --install` |

> **注意：** `mlx` 和 `mlx-whisper`（本地语音转文字）仅在 macOS Apple Silicon 上安装，其他平台自动跳过，不影响其他功能。

## 架构

```
桌面浏览器 / Web UI
    → backend/ (FastAPI :8000，同时提供 UI 和 API)
    → ../everything-capture-data/app.db + media/

手机 / 分享菜单 / 快捷指令
    → 可选云端 capture_service/
    → 待处理队列
    → 本地 processing_worker 轮询提取
    → ../everything-capture-data/app.db + media/
```

## 项目结构

```
everything-capture/
├── backend/                FastAPI API、提取引擎、同步、AI
│   ├── routers/            API 路由模块（items, ingest, ai, folders, settings, connect）
│   ├── services/           业务逻辑（extractor, downloader, ai_client, knowledge_base）
│   ├── models.py           SQLAlchemy ORM 模型
│   ├── database.py         数据库初始化、迁移、FTS5 索引
│   └── main.py             应用入口
├── frontend/               纯 HTML/CSS/JS 单页应用（无构建工具）
│   ├── index.html          SPA 入口
│   ├── css/index.css       全部样式
│   └── js/                 app-core, app-items, app-ai, app-folders 等
├── capture_service/        可独立部署的云端采集收件箱（可选）
├── desktop/                macOS .app 打包（PyInstaller + DMG）
│   ├── launcher/           桌面启动器，管理后端子进程生命周期
│   ├── spec/               构建规格、manifest、签名配置
│   └── scripts/            构建、签名、公证、发布脚本
├── docs/                   项目落地页（纯静态站点）
├── logo/                   SVG Logo 资源
├── setup.sh                一键安装脚本
├── run                     开发启动脚本（后端 + 前端 + worker）
└── requirements.txt        Python 依赖
```

## 数据存储

所有数据存储在仓库**外部**的同级目录中：

```
../everything-capture-data/
├── app.db              SQLite 数据库（WAL 模式）
├── media/              下载的图片、视频、封面
├── .local/master.key   Fernet 加密主密钥
├── exports/            AI 沙盒导出文件
└── components/         已安装的可选组件
```

可通过环境变量覆盖：`DATA_DIR`、`SQLITE_PATH`、`MEDIA_DIR`、`EXPORTS_DIR`。

## 手机端 / 云端采集（可选，需自行部署）

如需从手机或 iOS 快捷指令采集，需自行部署轻量的 `capture_service/`：

```bash
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py ./deploy_output
cd deploy_output && vercel
```

然后在本地配置：

```bash
mkdir -p backend/.local
echo 'CAPTURE_SERVICE_URL="https://your-deployment.vercel.app"' > backend/.local/capture_service.env
```

运行 `./run` 时，本地 `processing_worker` 会自动从云端队列拉取任务。

详见 [capture_service/README.md](./capture_service/README.md)。

## 可选集成

在 Web UI 设置页面中配置，无需手动编辑配置文件：

| 集成 | 用途 |
|---|---|
| **Notion** | 同步条目到 Notion 数据库（OAuth 授权） |
| **Obsidian** | 通过 Obsidian REST API 插件导出 Markdown |
| **AI**（OpenAI 兼容） | 知识库问答、内容分析、自动整理 |

所有 API 密钥使用 Fernet 加密存储。

## AI 功能

内置 AI 助手支持两种模式：

- **对话模式** — 知识库上下文问答、内容分析
- **Agent 模式** — 工具调用：搜索、文件夹管理、同步、导出、沙盒执行、系统命令

**阅读器侧栏 AI** 自动使用 Agent 模式 — 根据你的请求自动判断是否需要调用工具，无需手动切换模式。

**系统命令执行** — Agent 可以在你的电脑上执行命令（git clone、brew install 等），每条命令需要通过弹窗逐一审批。你会看到完整命令内容，点击「允许」后才会执行。Agent 会解读每条命令的输出后再决定下一步操作。

支持 reasoning/思维链模型的 `<think>` 标签流式输出。兼容任意 OpenAI 兼容 API（OpenAI、Claude、本地模型等）。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `../everything-capture-data/` | 数据根目录 |
| `SQLITE_PATH` | `$DATA_DIR/app.db` | 数据库路径 |
| `MEDIA_DIR` | `$DATA_DIR/media/` | 媒体存储路径 |
| `CAPTURE_SERVICE_URL` | *（无）* | 云端采集服务地址 |
| `CAPTURE_SERVICE_TOKEN` | *（无）* | 采集服务认证 token |
| `RUN_RELOAD` | `1` | 启用 uvicorn 热重载 |
| `USE_FTS5_SEARCH` | `true` | 启用 FTS5 全文搜索 |
| `EVERYTHING_CAPTURE_FRONTEND_ORIGIN` | *（无）* | 反向代理或 OAuth 回调场景下的前端地址覆盖 |

## 开发

```bash
# 运行后端测试
cd backend && source venv/bin/activate
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/ -v

# 运行 capture service 测试
PYTHONPATH="$(pwd)/.." python -m pytest ../capture_service/tests/ -v
```

## 许可证

[MIT](./LICENSE)
