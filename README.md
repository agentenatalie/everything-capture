<div align="center">

# Everything Capture

**从小红书、抖音到公众号，一条链接收进你的本地 AI 知识库**

看到有用的东西，复制链接丢进来就行。它会帮你抓正文、存图片视频、建好索引。之后想找什么，搜一下或者直接问 AI。数据都在你自己电脑上，不走任何云端。

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
  <img src="./docs/images/readme/hero.jpg" alt="Everything Capture 界面" width="920">
</p>

---

## 为什么做这个

每天刷到的好内容散落在收藏夹、聊天记录、截图、备忘录各种地方，真要找的时候基本靠记忆。

Everything Capture 做的事情很简单：给你一个统一的地方，把链接、文章、图片、视频收在一起，支持全文搜索和 AI 问答。Notion、Obsidian 这些工具可以接上去做同步，但你的数据本体就在自己电脑的一个 SQLite 文件里。

## 功能

### 采集

复制链接，粘到 Web UI 里，或者按 `⌘K` 用命令面板提交。手机上可以通过自己部署的云端收件箱把链接投回来。

链接丢进来之后，自动识别是哪个平台的、抓正文、下载图片视频、存进数据库。不用管分类，后面再整理。

<p align="center">
  <img src="./docs/images/readme/capture.gif" alt="采集" width="920">
</p>

### 阅读

支持小红书、抖音、Twitter(X)、微信公众号和普通网页。

打开一个条目，原文、图片视频、笔记、AI 侧栏都在一个页面里。看到一半想问"这段什么意思"或者"我之前存过类似的吗"，直接在侧栏问就行。

<p align="center">
  <img src="./docs/images/readme/reader.gif" alt="阅读器" width="920">
</p>

### 搜索与管理

所有内容存在本地 SQLite 里，图片视频存在本地磁盘。支持全文搜索（FTS5），可以按标题、正文、链接搜，也可以按文件夹、标签、平台过滤。中英文混着搜也没问题。

<p align="center">
  <img src="./docs/images/readme/dashboard.png" alt="内容库" width="920">
</p>

### 文件夹和关系图

文件夹可以嵌套，可以拖拽排序，一个条目可以放进多个文件夹。

也可以切到关系图看看，它会把文件夹、标签、相似内容之间的关系画出来，有时候会发现一些自己没注意到的关联。

<p align="center">
  <img src="./docs/images/readme/relation-map.png" alt="关系图" width="920">
</p>

### AI 助手

AI 查的是你本地的数据，不是某个云端的副本。有两种用法：

- **对话模式**：搜东西、问问题、做总结。比如"我存的 AI 相关内容里有哪些值得看？""帮我把这几篇整理成一份 Markdown"。
- **Agent 模式**：可以动手操作，比如整理文件夹、导出内容、同步到 Notion、跑本地命令。涉及系统命令的操作会让你确认之后再执行。

阅读器侧栏里默认就是 Agent 模式，不需要手动切换。AI 会慢慢记住你的习惯，比如你常用哪些文件夹、关注什么主题。

兼容 OpenAI API 格式，OpenAI、Claude、本地模型都能用。

<table>
  <tr>
    <td width="50%">
      <img src="./docs/images/readme/ai-chat-summary.png" alt="知识库总结">
      <br><strong>知识库总结</strong>
      <br>按主题检索本地条目，输出带引用的结构化结果。
    </td>
    <td width="50%">
      <img src="./docs/images/readme/ai-agent.png" alt="Agent 操作">
      <br><strong>Agent 操作</strong>
      <br>整理文件夹、导出 Markdown、同步内容，或执行需要你确认的命令。
    </td>
  </tr>
</table>

<p align="center">
  <img src="./docs/images/readme/ai-chat-find.png" alt="AI 查找" width="920">
</p>

### 还有这些

| | 功能 | 说明 |
|---|---|---|
| 🎙️ | **语音转文字** | Apple Silicon Mac 上用 mlx-whisper 在本机转录 |
| 👁️ | **OCR** | 用 macOS Vision 识别图片里的文字，也能扫二维码 |
| 📤 | **同步导出** | 可以把内容推到 Notion 或 Obsidian |
| 📱 | **手机投递** | 部署一个轻量收件箱，手机分享链接直接投进来 |
| 🖥️ | **桌面应用** | macOS .app 打包，开发中 |

## 开始使用

### 一条命令搞定

```bash
curl -O https://raw.githubusercontent.com/agentenatalie/everything-capture/main/setup.sh && bash setup.sh
```

这个脚本会帮你装好 Python、ffmpeg、克隆代码、创建虚拟环境、启动服务。跑完打开浏览器就能用。

### 自己一步步来也行

```bash
git clone https://github.com/agentenatalie/everything-capture.git
cd everything-capture
python3 -m venv backend/venv
backend/venv/bin/pip install -r requirements.txt
./run
```

然后打开 http://localhost:8000 。

### 需要装什么

| 依赖 | 干嘛用的 | 怎么装 |
|---|---|---|
| Python 3.11+ | 跑后端 | `brew install python3` / `apt install python3` |
| ffmpeg | 处理视频和音频 | `brew install ffmpeg` / `apt install ffmpeg` |
| Swift（macOS 自带） | OCR 和二维码识别 | `xcode-select --install` |

> `mlx` 和 `mlx-whisper` 只有在 Apple Silicon Mac 上才会装，其他机器自动跳过，不影响正常使用。

## 整体结构

```
浏览器 / Web UI
    → backend/ (FastAPI :8000，前端和 API 一起跑)
    → ../everything-capture-data/app.db + media/

手机 / 快捷指令
    → 云端 capture_service/（可选部署）
    → 待处理队列
    → 本地 worker 轮询拉取
    → ../everything-capture-data/app.db + media/
```

平时就是本地后端在干活。手机端只是一个投递入口，真正的内容提取都在你自己机器上完成。

## 项目结构

```
everything-capture/
├── backend/                FastAPI 后端：采集、解析、搜索、AI
│   ├── routers/            API 路由
│   ├── services/           业务逻辑
│   ├── models.py           数据模型
│   ├── database.py         数据库、迁移、FTS5
│   └── main.py             入口
├── frontend/               纯 HTML/CSS/JS 单页应用，不需要构建工具
│   ├── index.html
│   ├── css/index.css
│   └── js/
├── capture_service/        可选的云端收件箱
├── desktop/                macOS 桌面版打包相关
├── docs/                   项目主页
├── logo/                   Logo 资源
├── setup.sh                一键安装
├── run                     启动脚本
└── requirements.txt
```

## 数据放在哪

数据不在代码仓库里，放在仓库旁边的 `everything-capture-data/` 目录。更新代码不会影响你的数据。

```
../everything-capture-data/
├── app.db              SQLite 数据库（WAL 模式）
├── media/              图片、视频、封面
├── .local/master.key   加密密钥
├── exports/            导出文件
└── components/         可选组件
```

想换位置可以通过环境变量设置：`DATA_DIR`、`SQLITE_PATH`、`MEDIA_DIR`、`EXPORTS_DIR`。

## 手机怎么用

部署一个轻量的 `capture_service/` 到云上（比如 Vercel），手机分享链接时就能直接投递到你的本地机器。

```bash
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py ./deploy_output
cd deploy_output && vercel
```

然后在本地告诉它你的部署地址：

```bash
mkdir -p backend/.local
echo 'CAPTURE_SERVICE_URL="https://your-deployment.vercel.app"' > backend/.local/capture_service.env
```

跑 `./run` 之后，本地 worker 会自动去云端拉新链接回来处理。具体看 [capture_service/README.md](./capture_service/README.md)。

## 和其他工具的配合

在 Web UI 的设置页里就能配，不用改配置文件。

| 集成 | 说明 |
|---|---|
| **Notion** | 同步条目到 Notion 数据库，OAuth 授权 |
| **Obsidian** | 通过 REST API 插件导出 Markdown |
| **AI** | 接 OpenAI 兼容的 API，用来问答、分析、整理 |

API 密钥会加密之后再存储。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `../everything-capture-data/` | 数据根目录 |
| `SQLITE_PATH` | `$DATA_DIR/app.db` | 数据库路径 |
| `MEDIA_DIR` | `$DATA_DIR/media/` | 媒体存储 |
| `CAPTURE_SERVICE_URL` | — | 云端采集服务地址 |
| `CAPTURE_SERVICE_TOKEN` | — | 采集服务 token |
| `RUN_RELOAD` | `1` | uvicorn 热重载 |
| `USE_FTS5_SEARCH` | `true` | FTS5 全文搜索 |
| `EVERYTHING_CAPTURE_FRONTEND_ORIGIN` | — | 前端地址覆盖（反代 / OAuth 场景） |

## 开发

```bash
# 后端测试
cd backend && source venv/bin/activate
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/ -v

# capture service 测试
PYTHONPATH="$(pwd)/.." python -m pytest ../capture_service/tests/ -v
```

## License

[Elastic License 2.0](./LICENSE)（source-available）。不可以用来做 SaaS 或托管服务。商业授权见 [COMMERCIAL-LICENSING.md](./COMMERCIAL-LICENSING.md)。
