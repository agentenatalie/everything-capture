<div align="center">

# Everything Capture

**本地优先的内容采集与个人知识库**

从任何设备抓取网址、文章、社交媒体帖子、视频和文本 — 提取、存储、整理，全部在你自己的机器上完成。

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_+_FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: Elastic 2.0](https://img.shields.io/badge/License-Elastic%202.0-orange?style=flat-square)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS_|_Linux-lightgrey?style=flat-square&logo=apple&logoColor=white)](https://github.com/agentenatalie/everything-capture)
[![GitHub stars](https://img.shields.io/github/stars/agentenatalie/everything-capture?style=flat-square&logo=github)](https://github.com/agentenatalie/everything-capture/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/agentenatalie/everything-capture?style=flat-square)](https://github.com/agentenatalie/everything-capture/commits/main)

[English](./README_EN.md) · [项目主页](https://agentenatalie.github.io/everything-capture/)

</div>

<p align="center">
  <img src="./docs/images/readme/hero.jpg" alt="Everything Capture 搜索与快捷采集界面" width="920">
</p>

---

## 为什么做这个

大多数「稍后阅读」服务把你的数据存在他们的服务器上。Everything Capture 把**所有内容、媒体和元数据存在你本机的 SQLite 数据库**里。AI 助手默认直接读取这份本地 `app.db` 条目库本身；Obsidian 只是一个可选同步 / 导出目标，不是默认检索源。可选的云端采集服务允许手机提交链接，但真正的内容提取始终在本地运行。

## 产品截图

Everything Capture 把采集、搜索、阅读、图谱和 AI 问答放在同一个本地应用里。

<p align="center">
  <img src="./docs/images/readme/dashboard.png" alt="Everything Capture 本地内容库看板" width="920">
</p>

<table>
  <tr>
    <td width="50%">
      <img src="./docs/images/readme/capture.gif" alt="快捷采集面板">
      <br><strong>快捷采集</strong>
      <br>从剪贴板、分享文本或页面内容中识别链接，直接进入本地解析队列。
    </td>
    <td width="50%">
      <img src="./docs/images/readme/reader.gif" alt="阅读器与内容分析侧栏">
      <br><strong>阅读器与内容分析</strong>
      <br>原文、媒体、解析正文、笔记和 AI 侧栏并排呈现，阅读时就能追问和整理。
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="./docs/images/readme/relation-map.png" alt="内容关系图">
      <br><strong>内容关系图</strong>
      <br>用文件夹、主题和相似内容构建可探索的知识网络。
    </td>
    <td width="50%">
      <img src="./docs/images/readme/ai-chat-summary.png" alt="AI 按主题总结知识库内容">
      <br><strong>知识库总结</strong>
      <br>让 AI 从本地条目里检索、引用和汇总，输出可继续追问的结构化结果。
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="./docs/images/readme/ai-chat-find.png" alt="AI 在知识库中查找具体答案">
      <br><strong>精确查找</strong>
      <br>用自然语言定位保存过的答案、命令、链接和上下文。
    </td>
    <td width="50%">
      <img src="./docs/images/readme/ai-agent.png" alt="AI Agent 导出和整理内容">
      <br><strong>Agent 操作</strong>
      <br>在授权后执行整理、导出、同步和本地命令，把知识库变成可操作的工作台。
    </td>
  </tr>
</table>

## 功能

| | 功能 | 说明 |
|---|---|---|
| 📥 | **多端采集** | Web UI（粘贴链接或 ⌘K 命令面板）、服务端 URL 提取 API |
| 📄 | **智能提取** | 文章正文、社交媒体（小红书、抖音、Twitter/X、微信公众号）、图片、视频 |
| 💾 | **本地媒体存储** | 所有媒体（图片、视频、封面）下载到本地磁盘 |
| 🔍 | **全文搜索** | SQLite FTS5 trigram 索引，中英文混合高速搜索 |
| 🗂️ | **文件夹整理** | 多层嵌套、拖拽移入/排序、多文件夹归类、父文件夹聚合计数 |
| 🤖 | **AI 助手** | 对话与 Agent 模式，知识库问答、内容分析、自动整理 |
| 🎙️ | **本地语音转录** | 设备端 mlx-whisper 语音转文字（Apple Silicon） |
| 👁️ | **OCR 识别** | macOS Vision 框架提取图片文字 + 识别二维码 |
| 📤 | **可选同步 / 导出** | 推送到 Notion 或 Obsidian；它们是可选输出，不是 AI 的主检索来源 |
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

其中本地 `app.db` 是 AI 检索与引用的主知识源。

## 文件夹层级

- 文件夹支持多层嵌套。
- 把一个文件夹拖到另一个文件夹上，会直接变成它的子文件夹。
- 拖到文件夹行的上边缘或下边缘时，会在同级里重新排序。
- 父文件夹显示的是整个子树的唯一内容总数，不只是自己直接包含的内容。
- 点击顶层文件夹时，会立刻在展开和收起之间切换，并同时切到这个 main folder 本身，而且不会额外显示小三角。

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
| **Obsidian** | 通过 Obsidian REST API 插件做可选 Markdown 导出 |
| **AI**（OpenAI 兼容） | 知识库问答、内容分析、自动整理 |

所有 API 密钥使用 Fernet 加密存储。

## AI 功能

内置 AI 助手支持两种模式：

- **对话模式** — 知识库上下文问答、内容分析
- **Agent 模式** — 工具调用：搜索、文件夹管理、同步、导出、沙盒执行、系统命令

知识源说明：助手默认读取 Everything Capture 自己的本地 `app.db` 条目与解析文本。Obsidian 同步只是可选输出，不属于默认检索链路。

**阅读器侧栏 AI** 自动使用 Agent 模式 — 根据你的请求自动判断是否需要调用工具，无需手动切换模式。

**系统命令执行** — Agent 可以在你的电脑上执行命令（git clone、brew install 等），每条命令需要通过弹窗逐一审批。你会看到完整命令内容，点击「允许」后才会执行。Agent 会解读每条命令的输出后再决定下一步操作。

**AI 持久记忆** — Agent 会跨对话记住你的偏好。它会观察你的文件夹组织方式、关注的主题领域和喜欢的回答风格，然后自动应用这些知识。整理内容时，它会先学习你现有的分类习惯再动手操作。你的纠正会被立即记住，不会犯同样的错误。

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

本仓库采用 [Elastic License 2.0](./LICENSE)（`Elastic-2.0`）作为公开的 source-available 社区许可。

在公开许可下，你不能把本软件作为托管服务、代运营服务或 SaaS 直接提供给第三方使用。

如果你需要托管/SaaS、白标、OEM 或其他超出 Elastic-2.0 的商业权利，需要单独取得商业授权。见 [COMMERCIAL-LICENSING.md](./COMMERCIAL-LICENSING.md)。

这属于 source-available 授权，不是 OSI 意义上的开源许可证。
