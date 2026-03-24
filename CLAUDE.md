# Everything Capture

个人内容收藏与知识管理工具。通过浏览器扩展/快捷指令/手机网页采集链接和文本，后端提取正文、下载媒体、同步到 Notion/Obsidian，并提供 AI 助手做内容分析和知识库问答。

## 技术栈

- **后端**: Python 3 + FastAPI + SQLAlchemy (SQLite, WAL mode, FTS5 全文搜索)
- **前端**: 纯 HTML/CSS/JS（无构建工具），通过 `python -m http.server` 静态托管
- **AI**: OpenAI 兼容 API（可配置 base_url/model），支持 function calling
- **内容提取**: trafilatura + BeautifulSoup + yt-dlp，平台特定解析器（小红书、抖音、Twitter 等）
- **加密**: Fernet 对称加密存储 API key 等敏感信息

## 目录结构

```
backend/                   # FastAPI 后端应用
  main.py                  # 应用入口，挂载路由和中间件
  database.py              # SQLAlchemy 引擎、表创建、schema 迁移、FTS5 索引
  models.py                # ORM 模型（Item, Media, Folder, Settings, AiConversation 等）
  schemas.py               # Pydantic 请求/响应模型
  paths.py                 # 数据目录路径配置（DB、媒体、导出）
  security.py              # Fernet 加密/解密敏感字段
  tenant.py                # 单用户默认租户 ID
  frontend_bridge.py       # 前端 URL 解析（用于重定向和 OAuth 回调）
  app_settings.py          # 运行时开关（FTS5 搜索等）
  migrate.py               # 数据库迁移工具
  processing_worker.py     # 后台 worker：从 capture_service 拉取待处理任务并提取内容
  routers/                 # API 路由
    items.py               # /api/items — CRUD、搜索、文件夹、笔记、内容解析
    ingest.py              # /api/ingest, /api/extract — 内容导入（浏览器扩展 + URL 提取）
    connect.py             # /api/connect — Notion/Obsidian 同步、OAuth
    ai.py                  # /api/ai — AI 对话、知识库问答、内容分析
    folders.py             # /api/folders — 文件夹 CRUD 和排序
    settings.py            # /api/settings — 用户设置读写
    phone_webapp.py        # /api/phone — 手机端网页采集
  services/                # 业务逻辑层
    extractor.py           # 多平台内容提取（小红书、抖音、Twitter、通用网站）
    content_extraction.py  # 内容深度解析（媒体文字提取、OCR）
    downloader.py          # 媒体文件下载
    ai_client.py           # OpenAI 兼容 API 调用封装
    ai_defaults.py         # AI 模型默认配置和 URL 建议
    knowledge_base.py      # 知识库服务（Obsidian vault 笔记检索）
    capture_queue.py       # capture_service API 客户端
    sandbox_executor.py    # AI agent 沙盒命令执行
    media_text_extract.swift  # macOS 原生 OCR（Vision framework）
  tests/                   # pytest 测试

capture_service/           # 独立的云端采集队列服务（可选部署）
  api.py                   # FastAPI 应用，管理采集任务队列
  database.py              # 独立 SQLite 数据库
  models.py                # CaptureItem, CaptureFolder 等
  schemas.py               # 请求/响应模型
  static/                  # 手机采集网页前端

frontend/                  # 主 Web 前端
  index.html               # 单页应用入口
  css/index.css            # 样式
  js/
    app-core.js            # 核心逻辑、路由、状态管理
    app-items.js           # 内容列表和详情
    app-content.js         # 内容阅读和编辑
    app-ai.js              # AI 对话界面
    app-command.js         # 命令面板（快捷搜索/导入）
    app-folders.js         # 文件夹管理
    app-settings.js        # 设置页面

scripts/                   # 工具脚本
md-docs/                   # 项目文档
tasks/                     # 任务和经验记录
```

## 数据存储

- **数据目录**: 默认 `../everything-capture-data/`（项目同级），可通过 `DATA_DIR` 环境变量覆盖
- **数据库**: `{DATA_DIR}/app.db` (SQLite)，可通过 `SQLITE_PATH` 覆盖
- **媒体文件**: `{DATA_DIR}/media/`，可通过 `MEDIA_DIR` 覆盖
- **加密密钥**: `{DATA_DIR}/.local/master.key`

## 启动和运行

```bash
# 创建虚拟环境
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 启动（后端 :8000 + 前端 :8010 + capture worker）
./run

# 只启动后端（不 reload）
RUN_RELOAD=0 ./run
```

- 后端: `http://localhost:8000`（FastAPI + uvicorn）
- 前端: `http://localhost:8010`（python http.server 静态托管）
- `FRONTEND_PORT` 环境变量可改前端端口

## 测试

```bash
cd backend
source venv/bin/activate
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/ -v

# 运行单个测试文件
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/test_ai_routes.py -v

# capture_service 测试
PYTHONPATH="$(pwd)/.." python -m pytest ../capture_service/tests/ -v
```

注意：PYTHONPATH 必须包含项目根目录和 backend 目录，因为 import 混用了两种路径。

## API 路由总览

| 前缀 | 路由文件 | 功能 |
|------|---------|------|
| `/api/items` | `routers/items.py` | 内容条目 CRUD、搜索、文件夹分配、笔记、内容解析 |
| `/api/ingest` `/api/extract` | `routers/ingest.py` | 浏览器扩展推送内容、URL 提取 |
| `/api/connect` | `routers/connect.py` | Notion/Obsidian 连接和同步 |
| `/api/ai` | `routers/ai.py` | AI 对话、知识库问答、内容分析、agent 工具调用 |
| `/api/folders` | `routers/folders.py` | 文件夹管理 |
| `/api/settings` | `routers/settings.py` | 设置读写 |
| `/api/phone` | `routers/phone_webapp.py` | 手机采集页 |

## 代码规范

- **Python 风格**: snake_case 函数和变量，PascalCase 类名，无 type stub
- **路由函数**: 直接在路由文件内写业务逻辑，复杂逻辑抽到 `services/`
- **数据库操作**: 通过 `get_db()` 依赖注入获取 Session，路由内直接查询
- **后台任务**: 使用 `threading.Thread` 或 FastAPI `BackgroundTasks` 运行异步操作
- **前端**: 纯 JS，无框架，函数命名 camelCase，全局函数挂在 window 上
- **Schema 迁移**: `database.py` 的 `ensure_runtime_schema()` 在启动时自动增量迁移（ALTER TABLE ADD COLUMN）
- **敏感字段**: API key 等存储时加密（`security.py`），读取时解密，返回前端时只返回 `*_saved: bool`
- **错误处理**: 路由层抛 `HTTPException`，service 层抛自定义异常（如 `AiClientError`）

## 改动指引

| 要改什么 | 去哪里改 |
|---------|---------|
| 新增/修改 API 路由 | `backend/routers/` 对应文件，schema 加到 `schemas.py` |
| 新增数据库字段 | `models.py` 加 Column，`database.py` 的 `ensure_runtime_schema()` 加 ALTER TABLE 迁移 |
| 修改内容提取逻辑 | `backend/services/extractor.py`（平台特定解析）或 `content_extraction.py`（深度解析） |
| 修改 AI 对话/工具 | `backend/routers/ai.py`（路由+tool定义），`services/ai_client.py`（API调用） |
| 修改前端 UI | `frontend/js/` 对应模块，样式在 `frontend/css/index.css` |
| 修改 Notion/Obsidian 同步 | `backend/routers/connect.py` |
| 修改设置项 | `models.py` Settings 模型 + `schemas.py` SettingsResponse/UpdateRequest + `routers/settings.py` + `frontend/js/app-settings.js` |
| 修改 capture service | `capture_service/` 目录（独立应用） |
| 修改启动流程 | `run` 脚本 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `DATA_DIR` | 数据根目录（默认 `../everything-capture-data`） |
| `SQLITE_PATH` | 数据库路径覆盖 |
| `MEDIA_DIR` | 媒体目录覆盖 |
| `FRONTEND_PORT` | 前端端口（默认 8010） |
| `FRONTEND_ORIGIN` | 前端 origin（CORS 和重定向） |
| `CAPTURE_SERVICE_URL` | 云端采集服务 URL |
| `CAPTURE_SERVICE_TOKEN` | 采集服务认证 token |
| `EVERYTHING_GRABBER_MASTER_KEY` | 加密主密钥（覆盖文件存储的密钥） |
