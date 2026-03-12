# Deployment Guide

这个项目不是“整套后端都部署到云上”的架构。

正确做法是：

- 云端只部署 `capture_service/`
- 本地继续运行 `backend/` 和 `processing_worker`

也就是：

```text
Phone / Web / Shortcut
        ->
Cloud Capture Service
        ->
pending queue
        ->
Local Processing Worker
        ->
Scraping / media download / knowledge base sync
```

## 1. What To Deploy

只部署这些：

- `capture_service/api.py`
- `capture_service/database.py`
- `capture_service/models.py`
- `capture_service/schemas.py`
- `capture_service/static/*`

不要部署这些到云上：

- `backend/services/extractor.py`
- `backend/services/downloader.py`
- `backend/processing_worker.py`
- `backend/static/media/`
- 本地知识库、Obsidian、Notion 同步逻辑

## 2. What The Cloud Service Does

云端 capture service 只负责：

- 接收手机网页、快捷指令、插件、API 的收录请求
- 把内容写入 `pending`
- 暴露文件夹和队列状态接口
- 提供手机端 capture webapp

它不负责：

- 视频下载
- 网页抓取
- 反爬
- AI 处理
- 本地文件同步

## 3. Current Runtime Model

当前仓库里：

- 云端入口页面：`GET /`
- 健康检查：`GET /healthz`
- 收录接口：`POST /api/capture`
- 文件夹接口：`GET /api/folders`、`POST /api/folders`
- 队列接口：
  - `GET /api/items`
  - `GET /api/items/{id}`
  - `POST /api/items/{id}/claim`
  - `POST /api/items/{id}/complete`
  - `POST /api/items/{id}/fail`

本地处理器会从 capture service 拉取 `pending`，本地完成抓取后回写 `processed` 或 `failed`。

## 4. Cloud Deployment Requirements

当前 `capture_service` 使用 SQLite：

```python
CAPTURE_SERVICE_DB_PATH=/path/to/capture.db
```

所以正式部署时，你需要一个支持持久磁盘的环境。

适合：

- Railway
- Render
- Fly.io
- 任何能挂载持久磁盘并运行 FastAPI 的主机

不适合长期正式使用：

- 纯临时文件系统
- 只有 `/tmp` 的无状态函数环境

说明：

- Vercel preview 适合演示 UI 和 API 形状
- 但当前仓库里的 Vercel 打包默认是临时 SQLite，不适合正式长期收录

## 5. Deploy The Cloud Capture Service

### Option A: Run Directly From Repo

在服务器上拉取仓库后：

```bash
cd everything-capture
python3 -m venv .venv
. .venv/bin/activate
pip install fastapi==0.135.1 sqlalchemy==2.0.47 pydantic==2.12.5 uvicorn==0.41.0 httpx==0.28.1
```

配置环境变量：

```bash
export CAPTURE_SERVICE_DB_PATH="/data/everything-capture/capture.db"
export CAPTURE_SERVICE_TOKEN="replace-with-a-long-random-token"
```

启动：

```bash
uvicorn capture_service.api:app --host 0.0.0.0 --port 9000
```

如果你在平台上用 `$PORT`：

```bash
uvicorn capture_service.api:app --host 0.0.0.0 --port "$PORT"
```

### Option B: Build A Deploy-Only Package

如果你不想把整个仓库都部署到云端，可以先生成单独的 capture 包：

```bash
cd everything-capture
python3 scripts/prepare_capture_vercel_deploy.py /tmp/everything-capture-vercel
```

然后只部署这个生成目录。

这个目录会包含：

- `capture_service/`
- `api/index.py`
- `requirements.txt`
- `vercel.json`

## 6. Recommended Cloud Environment Variables

至少配置：

```bash
CAPTURE_SERVICE_DB_PATH=/data/everything-capture/capture.db
CAPTURE_SERVICE_TOKEN=replace-with-a-long-random-token
```

其中：

- `CAPTURE_SERVICE_DB_PATH` 必须指向持久化路径
- `CAPTURE_SERVICE_TOKEN` 会保护 `/api/*` 接口

如果你不设置 `CAPTURE_SERVICE_TOKEN`，任何知道地址的人都可以调用队列接口。

## 7. Local Processing Setup

云端 deployment 只是“收件箱”。

真正处理内容的是你自己的电脑。

### 7.1 Create Local Capture Config

在本地创建：

`backend/.local/capture_service.env`

内容示例：

```bash
CAPTURE_SERVICE_URL="https://capture.example.com"
CAPTURE_SERVICE_TOKEN="replace-with-the-same-token"
```

这个文件当前不会提交到 git。

### 7.2 Start The Local App And Worker

现在仓库根目录的 `./run` 已经会自动做两件事：

- 启动本地 FastAPI app
- 如果检测到 `CAPTURE_SERVICE_URL`，自动启动 `processing_worker`

直接运行：

```bash
cd everything-capture
./run
```

如果你只想手动跑 worker：

```bash
cd everything-capture/backend
../backend/venv/bin/python processing_worker.py
```

只处理一轮然后退出：

```bash
cd everything-capture/backend
../backend/venv/bin/python processing_worker.py --once
```

### 7.3 Worker Log

本地 worker 日志在：

`backend/.local/processing_worker.log`

常用排查命令：

```bash
tail -f backend/.local/processing_worker.log
```

## 8. Phone Webapp

部署完成后，手机直接打开云端根路径：

```text
https://capture.example.com/
```

它支持：

- 粘贴链接或文本
- 自动尝试读取剪贴板并填入输入框
- 选择云端文件夹
- 新建云端文件夹
- 点击“等待列表”查看当前等待中/处理中条目和累计上传数量
- 收录后轮询状态：
  - `已收录到待处理队列`
  - `处理中`
  - `已处理`
  - `处理失败`

## 9. Shortcut Configuration

如果你用 iPhone Shortcut，直接发到：

```text
POST https://capture.example.com/api/capture
```

请求头：

```text
Authorization: Bearer <CAPTURE_SERVICE_TOKEN>
Content-Type: application/json
```

请求体示例：

```json
{
  "url": "https://example.com/article",
  "source": "ios-shortcut",
  "source_app": "share-sheet",
  "timestamp": "2026-03-10T09:30:00-05:00",
  "folder_names": ["Inbox"]
}
```

返回示例：

```json
{
  "success": true,
  "captured": true,
  "item_id": "uuid",
  "status": "pending"
}
```

## 10. End-To-End Verification

部署后建议按这个顺序验证。

### Step 1: Cloud Service

确认：

```bash
curl https://capture.example.com/healthz
```

应该返回：

```json
{"status":"ok"}
```

### Step 2: Folder API

确认：

```bash
curl -H "Authorization: Bearer <CAPTURE_SERVICE_TOKEN>" \
  https://capture.example.com/api/folders
```

### Step 3: Phone Webapp

手机打开：

```text
https://capture.example.com/
```

提交一条链接，应该先看到：

- `已收录到待处理队列`

如果本地 worker 已连接，后面应该更新为：

- `处理中`
- `已处理`

### Step 4: Local Worker

本地看日志：

```bash
tail -f backend/.local/processing_worker.log
```

### Step 5: Local Knowledge Base

确认新内容已经进入本地 `backend/items.db`，并完成媒体下载或同步。

## 11. Common Problems

### Problem: 页面显示“已收录到待处理队列，等待本地处理器连接”

原因通常是：

- 本地没有运行 `./run`
- `backend/.local/capture_service.env` 没配置
- `CAPTURE_SERVICE_URL` 写错
- `CAPTURE_SERVICE_TOKEN` 不一致

先检查：

```bash
cat backend/.local/capture_service.env
tail -f backend/.local/processing_worker.log
```

### Problem: 队列一直是 pending

先确认本地 worker 是否真的能访问云端：

```bash
cd everything-capture/backend
../backend/venv/bin/python processing_worker.py --once
```

如果失败，看日志里的：

- 连接错误
- 401 token 错误
- 平台抓取错误

### Problem: 手机网页空白

确保你部署的是当前 `capture_service/static/*`，不要只部署 API。

### Problem: Vercel preview 能打开，但数据会丢

这是预期行为。

当前 Vercel preview 只适合：

- 演示页面
- 联调接口
- 测试 UI

如果你要让隔夜未处理的队列继续存在，必须给 capture service 配置持久数据库：

- `CAPTURE_SERVICE_DATABASE_URL`
- 或 `DATABASE_URL`

不要把生产队列只放在 `/tmp/capture.db`。

不适合正式长期运行，因为默认 SQLite 不是持久化存储。

## 12. Open Source Notes

如果你准备开源，建议默认告诉使用者：

1. 这是“两层架构”，不是“全云架构”
2. 云端只负责 capture
3. 本地机器负责抓取、下载、知识库同步
4. 必须先部署 capture service，再启动本地 worker
5. 正式部署需要持久化 SQLite 路径

这是当前项目最稳定、最现实的部署方式。
