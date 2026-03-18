# Everything Capture

Everything Capture 是一个本地优先的内容采集和知识库整理系统。

它把「采集入口」和「真正的抓取/下载/同步」拆开：

- 本地 `backend/` 负责正文提取、媒体下载、知识库浏览、Notion / Obsidian 同步、AI 能力
- 可选云端 `capture_service/` 只负责接收手机网页 / Shortcut / Share Sheet 的收录请求，并把任务放进队列
- 本地 `processing_worker` 从云端队列拉任务，完成真正的 extraction

这套结构适合你把手机端入口部署出去，同时把敏感或重型的 extraction 保留在自己的电脑上。

## 功能概览

- 从桌面、本地网页、手机网页、iPhone Shortcut 提交 URL 或文本
- 抓取网页 / 社交平台内容
- 下载图片、封面、视频等媒体到本地
- 把内容存入本地 SQLite 知识库并在 Web UI 中浏览、搜索、整理、归档到文件夹
- 可选同步到 Notion / Obsidian
- 可选接入 AI，对本地知识库做问答、分析和关联

## 架构

```text
Desktop browser / local UI
        -> frontend/ (served on a separate local port)
        -> local backend API
        -> everything-capture-data/app.db + everything-capture-data/media/

Phone / Share Sheet / Shortcut
        -> optional cloud capture_service
        -> pending queue
        -> local processing_worker
        -> local backend extraction pipeline
        -> everything-capture-data/app.db + everything-capture-data/media/
```

一句话版本：

- 只想本地用：跑 `backend/` 就够了
- 想让手机也能随时投递：再部署 `capture_service/`

## 仓库结构

```text
everything-capture/
├── backend/            本地 FastAPI API、同步与 AI 能力（代码only，不含数据）
├── capture_service/    可单独部署的手机收件箱 / 队列服务
├── frontend/           独立静态前端，由本地 HTTP 服务单独启动
├── scripts/            部署辅助脚本
├── run                 本地启动入口
└── .gitignore          已忽略本地数据库、媒体、日志、私有笔记等
```

关键文件：

- `backend/main.py`
  本地 FastAPI 应用入口，`/` 会重定向到独立前端地址，后端负责 API 与媒体服务。
- `backend/paths.py`
  所有数据路径的集中配置，定义外部数据目录位置。
- `frontend/index.html`
  本地知识库 UI 入口页面，由 `./run` 启动的静态文件服务提供。
- `backend/processing_worker.py`
  本地队列消费者。只有配置了 `CAPTURE_SERVICE_URL` 时才需要。
- `capture_service/api.py`
  云端 capture API + 手机网页入口。
- `scripts/prepare_capture_vercel_deploy.py`
  生成一个只包含 `capture_service` 的 Vercel 部署包。

## 本地运行

### 前提

- Python 3.11
- 一个可用的虚拟环境，路径为 `backend/venv`
- 如果要处理视频，建议本机安装 `ffmpeg`

说明：

- 这个仓库当前默认使用 `backend/venv` 这一路径
- 项目里暂时没有公开发布用的锁定依赖清单；README 以下命令默认你已经准备好了这个虚拟环境

### 启动主应用

```bash
cd /path/to/everything-capture
./run
```

默认行为：

- 启动本地后端：`http://127.0.0.1:8000`
- 启动本地前端：`http://127.0.0.1:8010`
- 如果 `backend/.local/capture_service.env` 存在且配置了 `CAPTURE_SERVICE_URL`，自动同时启动本地 processing worker

本地数据默认写到项目同级的外部数据目录（代码与数据分离）：

- 数据目录：`../everything-capture-data/`
- 数据库：`../everything-capture-data/app.db`
- 媒体：`../everything-capture-data/media/`
- 加密密钥：`../everything-capture-data/.local/master.key`
- 导出/备份：`../everything-capture-data/exports/`、`../everything-capture-data/backups/`

可通过环境变量覆盖：`DATA_DIR`、`SQLITE_PATH`、`MEDIA_DIR`、`EXPORTS_DIR`、`BACKUPS_DIR`

### 不启用云端队列时

如果你只在本机浏览器里使用这个项目，不需要部署任何云端服务：

1. 运行 `./run`
2. 打开 `http://127.0.0.1:8010`
3. 直接在本地 UI 里导入 / 抓取内容

## 手机端 / 云端收件箱

如果你想从手机、Shortcut、分享菜单把内容先丢到云上，再由自己电脑慢慢处理，就部署 `capture_service/`。

- 云端 capture 组件说明：[capture_service/README.md](./capture_service/README.md)

## 可选集成

这些都不是项目运行的硬前提，但可以在本地模式里打开：

- Notion 同步
- Obsidian 同步
- AI Base URL / Model / API Key
- Google / Email / Phone 认证相关能力

如果你只是把这个仓库作为单人、本地优先工具来使用，可以完全不配置这些。
