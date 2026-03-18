# Everything Capture Service

`capture_service/` 是 Everything Capture 里唯一建议部署到云上的部分。

它的职责很简单：

- 接收手机网页、Shortcut、分享菜单或其他客户端提交的 URL / 文本
- 把它们存进一个 `pending` 队列
- 暴露文件夹、队列状态和 worker 心跳接口
- 在根路径 `/` 提供手机网页 capture UI

它不负责：

- 网页抓取
- 视频下载
- AI 处理
- Notion / Obsidian 同步
- 本地知识库写入

## 部署 `capture_service`

### 方式 A：部署到有持久存储的主机

适合：

- Railway
- Render
- Fly.io
- 任何能挂持久磁盘或外部数据库的 Python 主机

示例：

```bash
cd /path/to/everything-capture
PYTHONPATH="$PWD:$PWD/backend" backend/venv/bin/python -m uvicorn capture_service.api:app --host 0.0.0.0 --port 9000
```

推荐环境变量：

```bash
CAPTURE_SERVICE_TOKEN=replace-with-a-long-random-token
CAPTURE_SERVICE_DATABASE_URL=postgresql://...
```

也可以不用外部数据库，改用持久化 SQLite：

```bash
CAPTURE_SERVICE_DB_PATH=/data/everything-capture/capture.db
CAPTURE_SERVICE_TOKEN=replace-with-a-long-random-token
```

说明：

- `CAPTURE_SERVICE_DATABASE_URL` / `DATABASE_URL` 适合正式部署
- `CAPTURE_SERVICE_DB_PATH` 适合有持久磁盘的单机部署
- `CAPTURE_SERVICE_TOKEN` 用来保护 `/api/*`

### 方式 B：生成 Vercel 部署包

如果你只想把手机端网页 + capture API 发到 Vercel，可以先生成一个只包含 `capture_service` 的目录：

```bash
cd /path/to/everything-capture
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py /tmp/everything-capture-vercel
```

然后把 `/tmp/everything-capture-vercel` 这个目录部署到 Vercel。

这个脚本会：

- 拷贝 `capture_service/`
- 生成 `api/index.py`
- 生成 `vercel.json`
- 生成 `requirements.txt`
- 从本地数据库（默认 `../everything-capture-data/app.db`）导出一个文件夹种子，给手机端文件夹选择器预填默认值

重要限制：

- 如果你没有配置 `CAPTURE_SERVICE_DATABASE_URL` 或 `DATABASE_URL`，Vercel 会退回到 `/tmp/capture.db`
- `/tmp` 不是持久存储，所以这种模式只适合 preview / demo，不适合长期正式收录

## 把本地 worker 接到云端 capture service

在本地创建：

`backend/.local/capture_service.env`

内容示例：

```bash
CAPTURE_SERVICE_URL="https://capture.example.com"
CAPTURE_SERVICE_TOKEN="replace-with-the-same-token"
```

然后直接运行：

```bash
./run
```

`run` 会自动：

- 启动本地 Web UI
- 启动本地 processing worker

如果你只想手动跑 worker：

```bash
cd /path/to/everything-capture/backend
venv/bin/python processing_worker.py --once
```

常用日志位置：

```text
backend/.local/processing_worker.log
```

## 手机网页怎么用

部署好 `capture_service` 之后，手机打开：

```text
https://capture.example.com/
```

手机网页支持：

- 粘贴 URL 或文本
- 选择云端文件夹
- 新建文件夹
- 查看等待列表
- 查看条目状态：`pending / processing / processed / failed`

## iPhone Shortcut / 其他客户端怎么接

请求地址：

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
  "text": null,
  "source": "ios-shortcut",
  "source_app": "share-sheet",
  "title": "Optional title",
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


## 运行方式

### 本地或自托管主机

```bash
cd /path/to/everything-capture
PYTHONPATH="$PWD:$PWD/backend" backend/venv/bin/python -m uvicorn capture_service.api:app --host 0.0.0.0 --port 9000
```

### Vercel 打包

```bash
cd /path/to/everything-capture
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py /tmp/everything-capture-vercel
```

把生成出来的目录部署到 Vercel 即可。

## 环境变量

- `CAPTURE_SERVICE_DATABASE_URL`
  推荐的正式部署方式。支持外部数据库，例如 Postgres。
- `DATABASE_URL`
  可选备用数据库变量。
- `CAPTURE_SERVICE_DB_PATH`
  SQLite 文件路径。适合本地或有持久磁盘的主机。
- `CAPTURE_SERVICE_TOKEN`
  可选 Bearer Token。设置后会保护所有 `/api/*` 队列接口。
- `CAPTURE_SERVICE_LEASE_TIMEOUT_SECONDS`
  worker claim 超时回收时间，默认 6 小时。

## 接口

- `GET /`
  手机网页 capture UI
- `GET /healthz`
  健康检查
- `GET /api/app-config`
  前端读取服务配置和存储状态
- `GET /api/worker-status`
  查看本地 worker 是否在线
- `POST /api/capture`
  创建 capture 条目
- `GET /api/folders`
  读取文件夹
- `POST /api/folders`
  新建文件夹
- `GET /api/items`
  列表 / 状态查询
- `POST /api/items/{id}/claim`
  worker claim 条目
- `POST /api/items/{id}/complete`
  worker 标记处理完成
- `POST /api/items/{id}/fail`
  worker 标记处理失败
- `POST /api/worker-heartbeat`
  worker 心跳

## 手机网页

部署完成后，手机打开服务根路径：

```text
https://capture.example.com/
```

支持：

- 粘贴链接或文本
- 选择文件夹
- 新建文件夹
- 查看等待列表
- 轮询处理状态

## 持久化说明

如果你把它部署到 Vercel 且没有配置 `CAPTURE_SERVICE_DATABASE_URL` / `DATABASE_URL`，打包入口会退回到：

```text
/tmp/capture.db
```

这只适合 preview / demo。

正式部署请使用：

- 外部数据库
- 或者有持久磁盘的 SQLite 路径

