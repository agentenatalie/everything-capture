# Current System Baseline

本文档基于当前仓库真实结构整理，核心依据包括：
`backend/main.py`、`backend/database.py`、`backend/models.py`、`backend/auth.py`、`backend/tenant.py`、`backend/routers/auth.py`、`backend/routers/ingest.py`、`backend/routers/items.py`、`backend/routers/folders.py`、`backend/routers/settings.py`、`backend/routers/connect.py`、`backend/routers/phone_webapp.py`、`backend/services/extractor.py`、`backend/services/downloader.py`、`backend/security.py`、`backend/static/index.html`、`backend/static/js/*.js`。

## 1. Product Overview

- 当前产品已经不是“匿名可用的单用户本地工具”。
- 当前实际形态是：
  - 一个带真实登录会话的 FastAPI + SQLite Web 应用。
  - 一个按 `user_id` 做主要数据隔离、按 `workspace_id` 做预留字段的后端。
  - 一个内置在同一前端里的手机 WebApp / Shortcut 收录入口，可直接走 `/api/phone-extract` 或转发到 capture queue。
- 当前 Web 端主流程：
  - 用户先登录。
  - 在 Command Palette 输入链接或关键词。
  - 链接走 `/api/extract`，搜索走 `/api/items?q=...`。
  - 成功后进入 Library、Reader、同步、导出、文件夹归类。
- 当前手机端主流程：
  - 在同一首页打开移动收录壳层。
  - 提交内容走 `/api/phone-extract`。
  - 若配置了 `capture_service`，则先入队；否则直接复用本地提取链路。
- 当前运行数据快照基于 `backend/items.db`：
  - `users = 2`
  - `workspaces = 1`
  - `items = 17`
  - `media = 104`
  - `folders = 2`
  - `item_folder_links = 7`
  - `settings = 1`
  - `auth_sessions = 8`
  - `auth_verification_codes = 13`

## 2. Current Features

| 功能 | 当前状态 | 入口位置 |
|---|---|---|
| 会话登录 | 可用 | Web Auth Overlay |
| Google OAuth 登录 | 条件可用 | `/api/auth/google/start` |
| 邮箱验证码登录 | 可用 | `/api/auth/email/*` |
| 手机验证码登录 | 条件可用 | `/api/auth/phone/*` |
| 服务端链接抓取 | 可用 | Web Command Palette；手机 WebApp / Shortcut |
| 手机 Web 收录 | 可用 | `#mobileCaptureShell` + `/api/phone-extract` |
| 文本入库 | 可用 | `/api/extract`、`/api/ingest` |
| 媒体下载到本地 | 可用 | `/api/extract` 后自动执行 |
| Library 浏览 | 可用 | Web 首页 |
| 搜索 | 可用 | 顶部搜索框；Command Palette |
| 平台筛选 | 可用 | Toolbar Select |
| 文件夹管理 | 可用 | Sidebar + Folder Picker |
| 多文件夹归类 | 可用 | `item_folder_links` + picker |
| 删除 item | 可用 | 卡片/列表删除 |
| ZIP 导出 | 可用 | Reader Modal |
| Notion OAuth / 同步 | 可用 | Settings + Reader Modal |
| Obsidian 测试 / 同步 | 可用 | Settings + Reader Modal |
| 自动同步 | 可用 | 用户级 Settings |
| 多用户隔离 | 部分可用 | 主要基于 `user_id` |
| 多 workspace 隔离 | 预留未落地 | `workspace_id` 仍基本固定默认值 |

## 3. Feature Implementation Details

### 3.1 Authentication

- 鉴权入口：
  - `GET /api/auth/providers`
  - `GET /api/auth/session`
  - `POST /api/auth/email/request-code`
  - `POST /api/auth/email/verify-code`
  - `POST /api/auth/phone/request-code`
  - `POST /api/auth/phone/verify-code`
  - `GET /api/auth/google/start`
  - `GET /api/auth/google/callback`
  - `POST /api/auth/logout`
- 会话机制：
  - `backend/main.py` 注册全局 middleware。
  - 优先从 `everything_capture_session` cookie 取 token，也支持 `Authorization: Bearer ...`。
  - middleware 解析成功后，将 `request.state.auth_user` 写入请求上下文，并把 `user_id` 放进 `ContextVar`。
  - 业务路由通过 `tenant.get_current_user_id()` 读取当前用户。
- 当前结论：
  - Web 端已经是“必须先登录后访问个人资料库”的模型。
  - 所有 items / folders / settings 查询都带 `user_id` 过滤。
  - 这已经不是匿名 API。

### 3.2 Link Capture / Ingest

- Web 入口：
  - `Cmd/Ctrl + K` 打开 Command Palette。
  - 输入链接走 `/api/extract`。
  - 输入普通文本走 `/api/items?q=...` 搜索。
- 手机入口：
  - iPhone 打开同一前端首页时进入移动收录壳层。
  - 提交后调用 `/api/phone-extract`。
  - 可选地转发到 `capture_service` 队列。
- 后端行为：
  - `/api/extract` 调用 `extract_content(url)`。
  - `/api/ingest` 直接落文本，不下载媒体，也不真正写入 `canonical_html`。
- 当前限制：
  - 手机 Web 入口与桌面共用同一前端页面，改 DOM / 样式时必须兼顾两端。
  - 若启用 `capture_service`，本地 worker 与移动收录入口都依赖配置一致性。

### 3.3 Content Extraction

- 平台识别和提取仍集中在 `backend/services/extractor.py`。
- 当前支持逻辑仍包括：
  - 小红书专用解析
  - 抖音专用解析
  - X/Twitter 专用解析
  - 通用网页 fallback
- `/api/extract` 当前落库行为：
  - 总是写 `canonical_text`
  - 有媒体时才会继续下载媒体并重写 `content_blocks_json`
  - 有媒体时才会把重写后的 `canonical_html` 保存到 `items`
- 当前限制：
  - 纯文本页面即使提取出了 HTML，当前也可能不会保存到 `canonical_html`
  - `/api/ingest` 请求模型包含 `canonical_html`，但实际后端没有写入该字段

### 3.4 Library / Search

- 统一列表接口是 `GET /api/items`。
- 支持参数：
  - `skip`
  - `limit`
  - `q`
  - `platform`
  - `folder_scope`
  - `folder_id`
- 搜索实现：
  - 当前没有单独 `/search` 路由。
  - 搜索逻辑在 `routers/items.py` 内完成。
  - 基于 query normalization、tokenization、intent boost、字段权重和时间因素做 Python 排序。
- 当前限制：
  - `items_fts` FTS5 表已经存在，但当前主搜索并不直接查询它。
  - 仍然是“先取候选，再在 Python 内打分”。

### 3.5 Folder Management

- 文件夹接口：
  - `GET /api/folders`
  - `POST /api/folders`
  - `PATCH /api/folders/{folder_id}`
  - `DELETE /api/folders/{folder_id}`
  - `PATCH /api/items/{item_id}/folder`
  - `POST /api/items/bulk-folder`
- 当前真实模型：
  - `items.folder_id` 仍保留，作为兼容字段/主文件夹映射。
  - `item_folder_links` 是当前多文件夹归类的真实关系表。
- 当前状态：
  - 不是旧文档里的“单 folder 归类”模型了。

### 3.6 Notion / Obsidian Sync

- Notion 接口：
  - `GET /api/connect/notion/oauth/url`
  - `GET /api/connect/notion/oauth/callback`
  - `GET /api/connect/notion/databases`
  - `POST /api/connect/notion/sync/{item_id}`
- Obsidian 接口：
  - `POST /api/connect/obsidian/test`
  - `POST /api/connect/obsidian/sync/{item_id}`
- 同步状态接口：
  - `POST /api/connect/sync-status/refresh`
- 自动同步：
  - `routers/ingest.py` 在入库后通过 `BackgroundTasks` 触发。
  - 目标从当前用户的 `settings.auto_sync_target` 决定。
- 当前真实状态：
  - 同步配置已是按 `user_id` 读取，不再是全局单例语义。

## 4. Frontend Architecture

- 前端不再是“所有逻辑都写在一个 HTML 文件里”。
- 当前结构：
  - HTML 壳：`backend/static/index.html`
  - 样式：`backend/static/css/index.css`
  - JS 模块：
    - `app-core.js`
    - `app-auth.js`
    - `app-settings.js`
    - `app-command.js`
    - `app-folders.js`
    - `app-content.js`
    - `app-items.js`
- 页面核心区域：
  - Auth Overlay
  - Folder Sidebar
  - Toolbar
  - Library Grid/List
  - Reader Modal
  - Settings Modal
  - Folder Picker
  - Command Palette
- 当前状态管理方式：
  - 仍然是原生 JS + 全局变量。
  - 但已经按模块拆分，不再是单文件脚本。
- 关键交互约束：
  - 未登录时直接显示 auth overlay。
  - `window.fetch` 已被 auth-aware 封装，非 auth API 若返回 `401` 会自动进入重新登录流程。
  - 资料库、文件夹、设置数据只有在 `authState.authenticated` 为真时才加载。

## 5. Backend Architecture

- 应用入口：
  - `backend/main.py`
- 基础设施：
  - `backend/database.py`
  - `backend/models.py`
  - `backend/security.py`
  - `backend/app_settings.py`
  - `backend/auth.py`
  - `backend/tenant.py`
- 路由模块：
  - `backend/routers/auth.py`
  - `backend/routers/ingest.py`
  - `backend/routers/items.py`
  - `backend/routers/folders.py`
  - `backend/routers/settings.py`
  - `backend/routers/connect.py`
- 服务模块：
  - `backend/services/extractor.py`
  - `backend/services/downloader.py`
- 初始化流程：
  - `Base.metadata.create_all(bind=engine)`
  - `ensure_runtime_schema()`
  - `init_search_index()`
- 关键特点：
  - ORM 表结构和运行期增量迁移同时存在。
  - 搜索索引通过 FTS5 + triggers 维护。
  - 认证态在 middleware 中解析，不是各路由手工重复解析。

## 6. Database Schema

### 6.1 Core Tables

- `users`
  - 当前已存在。
  - 支持 `email`、`phone_e164`、`google_sub`、`avatar_url`、`last_login_at`。
- `workspaces`
  - 当前已存在。
  - 但运行时基本仍停留在默认 workspace。
- `items`
  - 当前核心字段：`id`、`user_id`、`workspace_id`、`source_url`、`final_url`、`title`、`canonical_text`、`canonical_html`、`content_blocks_json`、`platform`、`status`、`notion_page_id`、`obsidian_path`、`folder_id`。
  - 当前查询和写入主要按 `user_id` 隔离。
- `media`
  - 当前已带 `user_id`、`workspace_id`。
  - `local_path` 仍是 `/static/media/{item_id}/...` 相对路径，不带用户目录层级。
- `folders`
  - 当前已带 `user_id`、`workspace_id`。
  - 用户内唯一约束是 `(user_id, name)`。
- `item_folder_links`
  - 当前多文件夹归类的真实关联表。
- `settings`
  - 当前已带 `user_id`、`workspace_id`。
  - 每个用户一条，`idx_settings_user_id` 唯一。
- `app_config`
  - 用于保存 Google OAuth client 配置。
- `auth_sessions`
  - 保存登录会话。
- `auth_verification_codes`
  - 保存邮箱/手机验证码。

### 6.2 Search Tables

- `items_fts`
  - FTS5 虚拟表。
  - 字段：`item_id`、`title`、`content`、`source_url`。
  - 有 insert/update/delete trigger 自动同步。
  - 目前主要是“已建好但未成为主查询入口”的状态。

## 7. Storage / Secret Handling

### 7.1 Media Storage

- 媒体仍然保存在本地文件系统。
- 路径根目录：
  - `backend/static/media/{item_id}/`
- 当前改动点：
  - 删除 item 时，后端会在 commit 后调用 `_cleanup_item_media_files(local_paths)` 清理本地媒体文件。
  - 旧文档里“删除 item 不删磁盘媒体”已经不准确。
- 仍然存在的限制：
  - 路径没有用户目录层级。
  - 仍然不是对象存储，也没有 CDN / 生命周期策略。

### 7.2 Secret Storage

- Notion token、Notion client secret、Obsidian API key、Google OAuth client secret 都不再明文保存。
- 当前使用方式：
  - `backend/security.py`
  - Fernet 加密
  - master key 读取优先级：
    - 环境变量 `EVERYTHING_GRABBER_MASTER_KEY`
    - 本地文件 `backend/.local/master.key`
- `GET /api/settings` 返回的是：
  - `*_saved` 布尔值
  - readiness / missing fields
  - 不直接回传 secret 明文

## 8. Integration Architecture

### 8.1 Notion

- 当前配置来源：
  - 当前用户的 `settings`
  - Google OAuth 则来自 `app_config` 或环境变量
- 当前 Notion 同步行为：
  - 使用保存的 token 请求 Notion API
  - target 来源于 `settings.notion_database_id`
  - 支持 page/database/data source 的兼容解析
  - 同步结果回写 `items.notion_page_id`
- 当前限制：
  - `notion_database_id` 这个命名已经偏离真实含义，本质上是 Notion sync target id

### 8.2 Obsidian

- 当前使用 Obsidian Local REST API。
- 当前用户可配置：
  - `obsidian_rest_api_url`
  - `obsidian_api_key`
  - `obsidian_folder_path`
- 同步结果回写：
  - `items.obsidian_path`

## 9. Tenancy Baseline

- 当前系统已经进入“有真实用户隔离”的阶段，但还不是完整多租户 SaaS。
- 准确描述应为：
  - `user_id` 是当前实际生效的隔离边界。
  - `workspace_id` 已经进 schema，但仍主要使用默认 workspace，属于过渡层。
  - settings / items / folders / media 都已是 user-scoped。
  - 静态媒体 URL 仍不是 tenant-aware public URL 方案。
- 当前必须明确的事实：
  - 旧文档中的“所有 API 匿名可调”“没有用户表”“settings 全局唯一”“前端头像只是占位”都已不成立。
  - 但“完整 workspace 多租户”“移动收录链路与登录态完全收敛”“媒体路径按租户隔离”也仍未成立。

## 10. Remaining Gaps / Risk Notes

- 当前所有移动收录说明都应统一以手机 WebApp / Shortcut 收录链路为准。
- `workspace_id` 目前更多是结构预留，不是已完成的产品隔离边界。
- 搜索仍然主要依赖 Python 打分，不是 FTS-first。
- `/api/ingest` 和 `/api/extract` 在 `canonical_html` / `content_blocks_json` 的落库行为仍不对称。
- 自动同步仍通过 FastAPI `BackgroundTasks` 直接执行，不是独立 job queue。
- 前端是模块化原生 JS，但仍依赖大量共享全局状态，重构风险不小。

## 11. Recommended Baseline Statement

如果后续文档需要一句话描述当前系统，建议统一表述为：

> 当前 Everything Capture 是一个带 Web 登录会话、按用户隔离数据与集成配置的本地优先内容抓取系统；workspace、多租户媒体隔离、移动收录认证收敛与异步任务化仍处于过渡阶段。
