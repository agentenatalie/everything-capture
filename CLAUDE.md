# Everything Capture

个人内容收藏与知识管理工具。通过浏览器扩展/快捷指令/手机网页采集链接和文本，后端提取正文、下载媒体、同步到 Notion/Obsidian，并提供 AI 助手做内容分析和知识库问答。

## 技术栈

- **后端**: Python 3 + FastAPI + SQLAlchemy (SQLite, WAL mode, FTS5 trigram 全文搜索)
- **前端**: 纯 HTML/CSS/JS（无框架、无构建工具），通过 `python -m http.server` 静态托管
- **AI**: OpenAI 兼容 Chat Completions API（可配置 base_url/model），支持 function calling 和 SSE streaming
- **内容提取**: trafilatura + BeautifulSoup + yt-dlp，平台特定解析器（小红书、抖音、Twitter、微信公众号等）
- **媒体处理**: httpx 流式下载 + yt-dlp 视频下载 + macOS Vision framework OCR + mlx-whisper 语音转文字
- **加密**: Fernet 对称加密存储 API key 等敏感信息（`security.py`）
- **知识库**: 读取本地 Obsidian vault 的 Markdown 笔记，TF-IDF + cosine similarity 检索

## 目录结构

```
backend/                       # FastAPI 后端应用
  main.py                      # 应用入口：创建 FastAPI app，挂载路由、CORS、GZip、静态文件
  database.py                  # SQLAlchemy 引擎、表创建、增量 schema 迁移、FTS5 全文索引
  models.py                    # ORM 模型定义
  schemas.py                   # Pydantic 请求/响应模型（所有 API 的 DTO）
  paths.py                     # 数据目录路径（DB_PATH, MEDIA_DIR, EXPORTS_DIR），含旧数据迁移逻辑
  security.py                  # Fernet 加密/解密，master.key 管理
  tenant.py                    # 单用户模式的默认用户/工作区 ID
  frontend_bridge.py           # 前端 URL 解析（根请求重定向、OAuth 回调跳转）
  app_settings.py              # 运行时开关（USE_FTS5_SEARCH）
  migrate.py                   # 数据库迁移工具脚本
  processing_worker.py         # 后台 worker 进程：轮询 capture_service → claim → 本地提取 → complete
  routers/                     # API 路由模块
    items.py                   # /api/items — CRUD、搜索（FTS5 trigram）、文件夹分配、笔记、内容解析触发
    ingest.py                  # /api/ingest + /api/extract — 浏览器扩展推送 + 服务端 URL 提取
    connect.py                 # /api/connect — Notion OAuth + API 同步、Obsidian REST API 同步
    ai.py                      # /api/ai — AI 对话（chat/agent 模式）、知识库问答、内容分析、流式响应
    folders.py                 # /api/folders — 文件夹 CRUD、重排序、删除
    settings.py                # /api/settings — 用户设置读写（加密存储敏感字段）
    phone_webapp.py            # /api/phone-extract — 手机端网页采集（优先 capture_service 队列）
  services/                    # 业务逻辑层
    extractor.py               # 全平台内容提取（~2500 行，核心提取引擎）
    content_extraction.py      # 内容深度解析：OCR、字幕提取、whisper 转录、繁简转换
    downloader.py              # 媒体文件下载：httpx 流式 + 断点续传 + yt-dlp 回退
    ai_client.py               # OpenAI 兼容 Chat Completions API 调用封装（普通/流式）
    ai_defaults.py             # AI 模型默认列表和 base URL
    knowledge_base.py          # Obsidian 知识库：笔记解析、TF-IDF 检索、相似度排序
    capture_queue.py           # capture_service 远程 API 客户端
    sandbox_executor.py        # AI agent 沙盒命令执行器（限制目录和命令白名单）
    media_text_extract.swift   # macOS 原生 Swift 脚本：Vision OCR + QR 码检测
  tests/                       # pytest 测试（18 个测试文件）

capture_service/               # 独立的云端采集队列服务（可选部署，独立 DB）
  api.py                       # FastAPI app：采集任务 CRUD、claim/complete 租约机制、worker 心跳
  database.py                  # 独立 SQLite（可配 PostgreSQL）
  models.py                    # CaptureItem, CaptureFolder, CaptureWorkerHeartbeat
  schemas.py                   # 请求/响应模型
  static/                      # 手机采集网页前端（HTML/CSS/JS）

frontend/                      # 主 Web 前端（纯静态 SPA）
  index.html                   # 单页应用入口，所有 JS 通过 <script> 标签内联在 HTML 底部
  css/index.css                # 全部样式（单文件）
  js/
    app-core.js                # DOM 引用、全局状态、初始化、导航逻辑
    app-items.js               # 内容列表渲染、阅读器模态框、页面笔记、内容编辑
    app-content.js             # HTML 渲染工具：Markdown 内联解析、HTML 安全转义
    app-ai.js                  # AI 对话 UI：chat/agent 模式切换、SSE 流式渲染、工具执行状态
    app-command.js             # 命令面板：⌘K 快捷搜索/URL 导入/剪贴板导入
    app-folders.js             # 文件夹侧边栏：列表渲染、拖拽排序、上下文菜单、文件夹选择器
    app-settings.js            # 设置弹窗：Notion/Obsidian/AI 配置、provider 预设、批量同步

scripts/                       # 工具脚本
  migrate_data.py              # 数据迁移
  prepare_capture_vercel_deploy.py  # capture_service Vercel 部署准备

md-docs/                       # 项目文档和开发指南
tasks/                         # 任务追踪和经验教训
```

## 数据库模型

核心 ORM 模型在 `backend/models.py`：

| 模型 | 表名 | 说明 |
|------|------|------|
| `User` | `users` | 用户（单用户模式，有默认 `local-default-user`） |
| `Workspace` | `workspaces` | 工作区（单工作区模式） |
| `Item` | `items` | 收藏条目：URL、标题、正文、HTML、平台、解析状态、OCR 文本等 |
| `Media` | `media` | 媒体文件：类型(image/video/cover)、原始 URL、本地路径、文件大小 |
| `Folder` | `folders` | 文件夹：名称、排序、用户归属 |
| `ItemFolderLink` | `item_folder_links` | 条目-文件夹多对多关联 |
| `Settings` | `settings` | 用户设置：Notion/Obsidian/AI 连接信息、agent 权限开关 |
| `AiConversation` | `ai_conversations` | AI 对话记录：消息 JSON、模式(chat/agent)、关联条目 |
| `ItemPageNote` | `item_page_notes` | 条目笔记：可关联 AI 对话消息 |
| `AiMemory` | `ai_memories` | AI 长期记忆：类型(learned/preference/correction) |

**Schema 迁移方式**：`database.py` 的 `ensure_runtime_schema()` 在每次启动时运行，通过 `PRAGMA table_info` 检查列是否存在，不存在则 `ALTER TABLE ADD COLUMN`。新增字段必须同时修改 `models.py` 和 `ensure_runtime_schema()`。

## 数据存储

- **数据目录**: 默认 `../everything-capture-data/`（项目同级目录），通过 `DATA_DIR` 环境变量覆盖
- **数据库**: `{DATA_DIR}/app.db` (SQLite WAL mode)，通过 `SQLITE_PATH` 覆盖
- **媒体文件**: `{DATA_DIR}/media/users/{user_id}/{item_id}/`，通过 `MEDIA_DIR` 覆盖
- **导出文件**: `{DATA_DIR}/exports/`（AI 沙盒工作目录）
- **加密密钥**: `{DATA_DIR}/.local/master.key`（Fernet key，权限 0600）
- **全文搜索**: SQLite FTS5 虚拟表 `items_fts`，trigram tokenizer，通过触发器自动同步

## 启动和运行

```bash
# 创建虚拟环境并安装依赖
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 启动全部服务（后端 :8000 + 前端 :8010 + capture worker）
./run

# 只启动后端（不 reload）
RUN_RELOAD=0 ./run
```

`./run` 脚本做的事情：
1. 检查 `backend/venv/bin/python` 是否存在
2. 加载 `backend/.local/capture_service.env` 中的环境变量
3. 清理占用端口的旧进程
4. 启动 uvicorn（`backend.main:app`，默认 `--reload`）
5. 启动 `processing_worker.py`（如果配置了 `CAPTURE_SERVICE_URL`）
6. 启动前端静态文件服务器

服务地址：
- 后端 API: `http://localhost:8000`
- 前端 UI: `http://localhost:8010`（`FRONTEND_PORT` 可改）

## 测试

```bash
# 从项目根目录运行所有后端测试
cd backend
source venv/bin/activate
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/ -v

# 运行单个测试文件
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/test_ai_routes.py -v

# capture_service 测试
PYTHONPATH="$(pwd)/.." python -m pytest ../capture_service/tests/ -v
```

**重要**: PYTHONPATH 必须包含项目根目录和 backend 目录，因为 import 混用了两种路径（`from database import ...` 和 `from capture_service.database import ...`）。

## API 路由详细说明

### Items (`routers/items.py`, prefix `/api`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/items` | 列表查询，支持 `q`(搜索)、`platform`、`folder_id`、`scope`(all/unfiled)、分页 |
| GET | `/items/search-suggestions` | 搜索建议 |
| GET | `/items/{id}` | 获取单个条目详情 |
| PATCH | `/items/{id}/folder` | 更新条目文件夹分配（支持多文件夹） |
| PATCH | `/items/{id}/content` | 更新条目标题/正文/HTML |
| PATCH | `/items/{id}/note` | 更新条目笔记（extracted_text） |
| POST | `/items/{id}/parse-content` | 触发内容深度解析（OCR、字幕提取等） |
| POST | `/items/bulk-folder` | 批量文件夹分配 |
| DELETE | `/items/{id}` | 删除条目（级联删除媒体和笔记） |
| GET | `/items/{id}/page-notes` | 条目页面笔记列表 |
| POST | `/items/{id}/page-notes` | 创建页面笔记 |
| PATCH | `/items/{id}/page-notes/{note_id}` | 更新页面笔记 |
| DELETE | `/items/{id}/page-notes/{note_id}` | 删除页面笔记 |

搜索实现：当 `USE_FTS5_SEARCH=true` 时使用 FTS5 trigram 索引搜索 title+content+source_url，否则回退到 LIKE 查询。搜索支持中文和英文混合查询，有语义意图扩展（如搜 "ui" 自动扩展相关设计关键词）。

### Ingest (`routers/ingest.py`, prefix `/api`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ingest` | 浏览器扩展推送已提取内容（含 HTML/text/media） |
| POST | `/extract` | 服务端 URL 提取：传入 URL 或文本，后端完成提取 |

Ingest 流程：收到内容 → 创建 Item → 下载媒体 → HTML 清洗 → 自动同步（如开启）→ 后台触发内容解析。

### Connect (`routers/connect.py`, prefix `/api/connect`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/notion/oauth/url` | 获取 Notion OAuth 授权 URL |
| GET | `/notion/oauth/callback` | Notion OAuth 回调处理 |
| GET | `/notion/databases` | 列出用户 Notion 数据库 |
| POST | `/notion/sync/{item_id}` | 同步单个条目到 Notion |
| POST | `/notion/sync-all` | 批量同步所有未同步条目到 Notion |
| POST | `/obsidian/sync/{item_id}` | 同步单个条目到 Obsidian（通过 REST API 插件） |
| POST | `/obsidian/sync-all` | 批量同步到 Obsidian |
| POST | `/obsidian/test` | 测试 Obsidian 连接 |
| POST | `/sync-status/refresh` | 刷新同步状态 |

Notion 同步：创建 page，写入 title + text blocks + media embeds + 来源 URL。
Obsidian 同步：通过 Obsidian REST API 插件写入 Markdown 文件，支持增量同步（hash 对比）。

### AI (`routers/ai.py`, prefix `/api/ai`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ask` | 知识库问答（单次 Q&A，使用知识库检索 + AI 回答） |
| POST | `/assistant` | AI 助手对话（chat/agent 模式，支持 tool calling） |
| POST | `/assistant/stream` | 流式 AI 助手对话（SSE） |
| GET | `/items/{id}/related` | 获取相关笔记（基于知识库相似度） |
| POST | `/items/{id}/analysis` | AI 分析条目（生成摘要、核心观点、思考问题） |
| POST | `/items/{id}/organize-analysis` | AI 自动整理条目（分配文件夹 + 分析） |
| GET | `/conversations` | 对话历史列表（支持搜索） |
| GET | `/conversations/{id}` | 获取单个对话详情 |
| POST | `/conversations` | 保存/更新对话 |
| DELETE | `/conversations/{id}` | 删除对话 |
| GET | `/exports/{path}` | 下载 AI 沙盒导出的文件 |

**AI Agent 工具列表**（在 `ai.py` 中定义，通过 function calling 给 LLM 使用）：

| 工具名 | 说明 | 权限控制 |
|--------|------|----------|
| `search_library_items` | 搜索收藏库中的条目 | 始终可用 |
| `get_item_details` | 读取条目详情 | 始终可用 |
| `list_recent_notes` | 列出最近的条目 | 始终可用 |
| `get_related_notes` | 查找相关条目 | 始终可用 |
| `list_folders` | 列出文件夹 | 始终可用 |
| `save_memory` | 保存 AI 长期记忆 | 始终可用 |
| `delete_memory` | 删除 AI 记忆 | 始终可用 |
| `assign_item_folders` | 分配条目到文件夹 | `ai_agent_can_manage_folders` |
| `create_folder` | 创建新文件夹 | `ai_agent_can_manage_folders` |
| `batch_assign_item_folders` | 批量分配文件夹 | `ai_agent_can_manage_folders` |
| `parse_item_content` | 触发内容解析 | `ai_agent_can_parse_content` |
| `sync_item_to_obsidian` | 同步到 Obsidian | `ai_agent_can_sync_obsidian` |
| `sync_item_to_notion` | 同步到 Notion | `ai_agent_can_sync_notion` |
| `export_items_to_zip` | 导出内容为 ZIP | `ai_agent_can_execute_commands` |
| `execute_sandbox_command` | 沙盒命令执行 | `ai_agent_can_execute_commands` |

AI 对话模式：
- **chat**: 普通对话，可引用当前阅读的条目和知识库
- **agent**: 有工具调用能力，可以搜索、整理、同步、导出

### Folders (`routers/folders.py`, prefix `/api/folders`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 文件夹列表（含每个文件夹的条目数 + 未分类数） |
| POST | `/` | 创建文件夹（名称唯一，大小写不敏感） |
| PATCH | `/{id}` | 重命名文件夹 |
| POST | `/reorder` | 重排序（传入完整 folder_ids 数组） |
| DELETE | `/{id}` | 删除文件夹（条目自动回退到其他文件夹或变为未分类） |

### Settings (`routers/settings.py`, prefix `/api/settings`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 读取设置（敏感字段返回 `*_saved: bool`，不返回明文） |
| POST | `/` | 更新设置（敏感字段自动加密存储） |

### Phone Webapp (`routers/phone_webapp.py`, prefix `/api`)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/phone-extract` | 手机端采集（优先走 capture_service 队列，失败回退本地处理） |

## 内容提取引擎 (`services/extractor.py`)

核心函数 `extract_content(url)` 的流程：
1. `detect_platform(url)` 根据域名识别平台
2. 调用平台专用提取器（优先）
3. 回退到通用提取器（trafilatura + BeautifulSoup）

支持的平台和提取策略：

| 平台 | 域名 | 提取策略 |
|------|------|----------|
| 小红书 | xiaohongshu.com, xhslink.com | SSR HTML 解析 → JSON-LD → 正文+图片 |
| 抖音 | douyin.com, iesdouyin.com | Router 数据解析 → 图文轮播 → yt-dlp 视频 |
| Twitter/X | twitter.com, x.com | Syndication API → 多源回退（数据嵌入、nitter） |
| 微信公众号 | mp.weixin.qq.com | 通用提取（自动检测验证码拦截页） |
| 通用网站 | 其他所有 | trafilatura article 提取 → OG/meta 解析 → 可见文本回退 |

返回 `ExtractResult`：title, text, platform, final_url, media_urls（含 inline_position）

## 内容深度解析 (`services/content_extraction.py`)

`parse_item_content(item)` 对已入库条目做二次解析：

- **图片 OCR**: 调用 macOS Vision framework（通过 `media_text_extract.swift`），提取文字和 QR 码链接
- **视频字幕**: 优先查找伴生字幕文件 → 提取嵌入字幕轨（ffmpeg） → mlx-whisper 语音转录
- **繁简转换**: 视频转录结果自动繁体→简体转换（硬编码字符映射表）
- **文本格式化**: 视频转录文本自动分段（基于段落标记词和句子长度）
- **URL 提取**: 从 OCR 文本和正文中提取 HTTP URL

## 知识库服务 (`services/knowledge_base.py`)

读取本地 Obsidian vault 中的 Markdown 笔记用于 AI 检索：

- **发现路径**: 读取 `~/Library/Application Support/obsidian/obsidian.json` 找到 vault → 查找 `Sources.base` 子目录
- **笔记解析**: YAML frontmatter（title, summary, tags, date, source, item_id）+ Markdown body
- **缓存机制**: 基于文件数量 + 最新 mtime 的快照缓存，文件无变化不重新解析
- **检索算法**: TF-IDF 加权（title 3.2x, summary 5.4x, tags 2.8x, folder 1.7x, excerpt 1.4x）+ cosine similarity
- **查询扩展**: 伪相关反馈（PRF）——用初始结果的高权重词扩展查询
- **相似推荐**: 基于笔记间的 cosine similarity + folder/tag 重合度 bonus

## AI 沙盒执行器 (`services/sandbox_executor.py`)

AI agent 的 `execute_sandbox_command` 工具使用的安全沙盒：

- **允许目录**: 仅 `{DATA_DIR}` 和 `/tmp`
- **工作目录**: `{DATA_DIR}/exports/`
- **命令白名单**: ls, cat, head, tail, wc, find, tree, cp, mv, mkdir, zip, unzip, tar, git, curl, wget, python3, node, jq, sort, grep, awk, sed, du, file, touch, echo
- **禁止模式**: rm -rf /, sudo, chmod 777, eval 等
- **操作类型**: git_clone, download_file, zip_files, list_files, read_file, write_file, move_file, delete_file, run_command, batch
- **超时**: 单命令 60s，下载 120s
- **输出限制**: 最大 64KB

## 媒体下载 (`services/downloader.py`)

- **图片下载**: httpx 流式下载 + 文件扩展名智能推断（支持微信 wx_fmt 参数）
- **视频下载**: 优先 yt-dlp（douyin/youtube/vimeo）→ 回退 httpx 直接下载 → 回退分享页 yt-dlp
- **断点续传**: 支持 Range header，最多 8 次重试
- **字幕获取**: yt-dlp 自动下载 VTT 字幕 → 转为纯文本伴生文件
- **存储路径**: `media/users/{user_id}/{item_id}/{type}_{order}.{ext}`
- **YouTube 等外部视频**: 保留外部引用而不下载

## Capture Service 和 Processing Worker

**Capture Service** (`capture_service/api.py`) 是可选的独立云端服务：
- 接收来自快捷指令/手机的采集请求，入队为 `pending` 状态
- 提供 claim/complete/fail 租约机制防止重复处理
- Worker 心跳监控（45s 超时判定离线）
- 过期租约自动释放（默认 6 小时）

**Processing Worker** (`backend/processing_worker.py`) 是本地后台进程：
- 以固定间隔（默认 15s）轮询 capture_service 获取 pending 任务
- claim 任务 → 调用 `execute_extract_request` 本地提取 → complete/fail
- 自动创建/映射文件夹（capture_service 文件夹名 → 本地文件夹）
- 上报心跳状态

## 前端架构

纯 JS 单页应用，所有 JS 文件通过 `<script>` 标签在 `index.html` 底部引入，共享全局作用域。

| 文件 | 职责 |
|------|------|
| `app-core.js` | DOM 元素引用缓存（60+ 个 getElementById）、全局状态变量、SVG 图标定义、视图切换 |
| `app-items.js` | 内容卡片列表渲染（gallery/list 视图）、阅读器模态框、页面笔记、内容编辑（contenteditable）、拖拽操作 |
| `app-content.js` | HTML 工具函数：escapeHtml、Markdown 内联语法解析（链接/加粗/代码/删除线）、URL 安全提取 |
| `app-ai.js` | AI 对话界面：chat/agent 双模式、SSE 流式渲染、工具执行动画、Markdown 代码块高亮、对话历史侧边栏 |
| `app-command.js` | ⌘K 命令面板：URL 检测→导入、文字→搜索、剪贴板读取 |
| `app-folders.js` | 文件夹侧边栏：列表/统计/上下文菜单/拖拽排序/文件夹选择器弹窗/inline 创建 |
| `app-settings.js` | 设置弹窗：Notion OAuth/Obsidian/AI 三区配置、provider 模型预设列表、批量同步操作、agent 权限开关 |

前端状态管理：使用全局变量（`let items = []`、`let foldersData = []`），无响应式框架。API 调用使用原生 `fetch`，API base URL 从当前 hostname 动态拼接（`window.API_BASE_URL = 'http://' + host + ':8000'`）。

## 代码规范

### Python 后端
- **命名**: snake_case 函数和变量，PascalCase 类名
- **路由**: 直接在路由文件内写业务逻辑，复杂/可复用逻辑抽到 `services/`
- **数据库**: 通过 `get_db()` FastAPI 依赖注入获取 Session，路由内直接 SQLAlchemy 查询
- **后台任务**: `threading.Thread`（长时间任务如内容解析）或 `BackgroundTasks`（轻量级如自动同步）
- **敏感字段**: 存储时 `encrypt_secret()`，读取时 `decrypt_secret()`，返回前端只返回 `*_saved: bool`
- **错误处理**: 路由层 `HTTPException`，service 层自定义异常（`AiClientError`, `ContentExtractionError`, `SandboxError`）
- **Schema 迁移**: 只用 `ALTER TABLE ADD COLUMN`（SQLite 不支持 DROP/MODIFY），在 `ensure_runtime_schema()` 中
- **日志**: `logging` 标准库，中文日志消息

### JavaScript 前端
- **命名**: camelCase 函数和变量
- **无框架**: 原生 DOM 操作，全局函数直接定义在文件顶层
- **API 调用**: 原生 `fetch()`，手动处理 JSON 解析和错误
- **HTML 渲染**: 字符串拼接 + `innerHTML`，需手动 `escapeHtml()` 防 XSS
- **CSS**: 单文件 `index.css`，使用 CSS 变量做主题、`@media` 响应式

## 改动指引

| 要改什么 | 去哪里改 |
|---------|---------|
| 新增 API 路由 | `backend/routers/` 对应文件 + `schemas.py` 加 DTO + `main.py` 确认 include_router |
| 新增数据库字段 | `models.py` 加 Column + `database.py` `ensure_runtime_schema()` 加 ALTER TABLE + 迁移默认值 |
| 新增平台提取器 | `services/extractor.py`: 在 `_PLATFORM_RULES` 加域名映射 + 写 `extract_xxx()` + 注册到 `_EXTRACTORS` |
| 修改内容提取逻辑 | `services/extractor.py`（网页解析）或 `content_extraction.py`（OCR/字幕/转录） |
| 修改 AI 对话行为 | `routers/ai.py`（system prompt / tool 定义 / tool 执行逻辑） |
| 新增 AI agent 工具 | `routers/ai.py`: 在 `tools` 列表加工具定义 + 在 tool dispatch 加执行逻辑 + 前端 `AI_TOOL_LABELS` 加中文标签 |
| 修改知识库检索 | `services/knowledge_base.py`（TF-IDF 权重/检索算法/笔记解析） |
| 修改 AI 沙盒 | `services/sandbox_executor.py`（命令白名单/目录限制/操作类型） |
| 修改媒体下载 | `services/downloader.py`（下载策略/yt-dlp 配置/续传逻辑） |
| 修改 Notion 同步 | `routers/connect.py`（搜索 `sync_to_notion`） |
| 修改 Obsidian 同步 | `routers/connect.py`（搜索 `sync_to_obsidian`） |
| 修改前端 UI | `frontend/js/app-*.js` 对应模块 + `frontend/css/index.css` |
| 修改设置项 | `models.py` Settings + `schemas.py` SettingsResponse/UpdateRequest + `routers/settings.py` + `frontend/js/app-settings.js` |
| 修改 capture service | `capture_service/` 目录（独立应用，独立数据库） |
| 修改启动流程 | `run` 脚本 |
| 修改 AI 默认模型列表 | `services/ai_defaults.py` + `frontend/js/app-settings.js` 的 `AI_PROVIDER_MODEL_PRESETS` |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATA_DIR` | 数据根目录 | `../everything-capture-data` |
| `SQLITE_PATH` | 数据库路径覆盖 | `{DATA_DIR}/app.db` |
| `MEDIA_DIR` | 媒体目录覆盖 | `{DATA_DIR}/media` |
| `EXPORTS_DIR` | 导出目录覆盖 | `{DATA_DIR}/exports` |
| `FRONTEND_PORT` | 前端端口 | `8010` |
| `FRONTEND_ORIGIN` | 前端 origin（CORS 和重定向） | 自动检测 |
| `EVERYTHING_CAPTURE_FRONTEND_ORIGIN` | 前端 origin（优先级更高） | - |
| `EVERYTHING_CAPTURE_ALLOWED_ORIGINS` | 额外允许的 CORS origin（逗号分隔） | - |
| `CAPTURE_SERVICE_URL` | 云端采集服务 URL | - |
| `CAPTURE_SERVICE_TOKEN` | 采集服务认证 token | - |
| `CAPTURE_WORKER_INTERVAL` | Worker 轮询间隔（秒） | `15` |
| `START_CAPTURE_WORKER` | 是否启动 capture worker | `1` |
| `EVERYTHING_GRABBER_MASTER_KEY` | 加密主密钥（覆盖文件密钥） | - |
| `USE_FTS5_SEARCH` | 是否启用 FTS5 全文搜索 | `true` |
| `RUN_RELOAD` | uvicorn 是否开启 hot reload | `1` |
