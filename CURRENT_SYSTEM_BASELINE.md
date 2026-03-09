# Current System Baseline

基于当前实际代码与当前运行数据结构梳理，核心依据包括：
[backend/main.py](/Users/hbz/everything-grabber/backend/main.py)、[backend/models.py](/Users/hbz/everything-grabber/backend/models.py)、[backend/database.py](/Users/hbz/everything-grabber/backend/database.py)、[backend/routers/ingest.py](/Users/hbz/everything-grabber/backend/routers/ingest.py)、[backend/routers/items.py](/Users/hbz/everything-grabber/backend/routers/items.py)、[backend/routers/connect.py](/Users/hbz/everything-grabber/backend/routers/connect.py)、[backend/routers/settings.py](/Users/hbz/everything-grabber/backend/routers/settings.py)、[backend/routers/folders.py](/Users/hbz/everything-grabber/backend/routers/folders.py)、[backend/services/extractor.py](/Users/hbz/everything-grabber/backend/services/extractor.py)、[backend/services/downloader.py](/Users/hbz/everything-grabber/backend/services/downloader.py)、[backend/static/index.html](/Users/hbz/everything-grabber/backend/static/index.html)、[ios/EverythingGrabber/Sources/CaptureView.swift](/Users/hbz/everything-grabber/ios/EverythingGrabber/Sources/CaptureView.swift)、[ios/EverythingGrabber/Sources/WebViewExtractor.swift](/Users/hbz/everything-grabber/ios/EverythingGrabber/Sources/WebViewExtractor.swift)、[ios/EverythingGrabber/Sources/ClipboardManager.swift](/Users/hbz/everything-grabber/ios/EverythingGrabber/Sources/ClipboardManager.swift)。

## 1. Product Overview

- 当前产品本质上是一个单用户、本地部署的“内容收藏与知识沉淀工具”，而不是已具备账号体系的 SaaS。
- 实际产品由两部分组成：
  - 本地 FastAPI 服务 + SQLite 数据库 + 单文件 Web 看板。
  - iOS App，用剪贴板检测链接并触发抓取。
- 当前主使用流程有两条：
  - Web 端：在 Command Palette 中粘贴链接 `->` 调用 `/api/extract` `->` 后端抓取/解析/下载媒体 `->` 入库 `->` 在 Library 中查看/搜索/同步。
  - iOS 端：检测剪贴板链接 `->` 先尝试后端 `/api/extract` `->` 失败时回退本地 `WKWebView + Readability` 提取 `->` 调用 `/api/ingest` 入库。
- 当前库内已有数据表现也符合“个人知识库”定位：`backend/items.db` 中现有 `16` 条 item、`97` 条 media、`0` 个 folder、`1` 条 settings 记录。

## 2. Current Features

| 功能 | 当前状态 | 入口位置 |
|---|---|---|
| 链接导入抓取 | 可用 | Web Command Palette；iOS 剪贴板检测 |
| 服务端内容解析 | 可用 | `POST /api/extract` |
| iOS 本地回退提取 | 可用 | iOS App 自动走 fallback |
| 文本入库 | 可用 | `/api/extract` 与 `/api/ingest` |
| 图片/视频下载到本地 | 可用 | `/api/extract` 后自动执行 |
| 富文本 HTML 保存 | 部分可用 | 仅 `/api/extract` 且有媒体时才保存 |
| content blocks 保存 | 部分可用 | 仅 `/api/extract` 且有媒体时才保存 |
| Library 浏览 | 可用 | Web 首页 |
| 搜索 | 可用 | 顶部搜索框；Command Palette 搜索 |
| 平台筛选 | 可用 | Web toolbar |
| 文件夹管理 | 可用 | 左侧 sidebar / folder picker |
| 批量归类 | 可用 | Selection mode |
| 删除 item | 可用 | 卡片/列表删除按钮 |
| ZIP 导出 | 可用 | Reader modal |
| Notion OAuth | 可用 | Settings modal |
| Notion 手动同步 | 可用 | Reader modal |
| Obsidian 手动同步 | 可用 | Reader modal |
| Obsidian 连通性测试 | 可用 | Settings modal |
| 自动同步 | 可用 | 全局 Settings |
| 用户/权限/多租户 | 未实现 | 无 |

## 3. Feature Implementation Details

### Link Capture

- 前端入口：
  - Web：`Cmd/Ctrl + K` 打开 Command Palette，输入链接或分享文案；[backend/static/index.html](/Users/hbz/everything-grabber/backend/static/index.html)
  - iOS：应用激活时检查系统剪贴板，弹窗确认；[ios/EverythingGrabber/Sources/EverythingGrabberApp.swift](/Users/hbz/everything-grabber/ios/EverythingGrabber/Sources/EverythingGrabberApp.swift)、[ios/EverythingGrabber/Sources/ClipboardManager.swift](/Users/hbz/everything-grabber/ios/EverythingGrabber/Sources/ClipboardManager.swift)
- 调用链路：
  - Web：`resolveCommandUrl()` `->` `extractURL()` `->` `POST /api/extract`
  - iOS：`CaptureView.startExtraction()` `->` `APIClient.extractViaServer()`；失败后 `WebViewExtractor.extract()` `->` `APIClient.ingest()`
- 后端处理逻辑：
  - `/api/extract` 调用 `extract_content(url)` 自动识别平台并走专用提取器或通用提取器；[backend/routers/ingest.py](/Users/hbz/everything-grabber/backend/routers/ingest.py)、[backend/services/extractor.py](/Users/hbz/everything-grabber/backend/services/extractor.py)
  - `/api/ingest` 直接收客户端已提取文本，不做媒体下载。
- 数据写入位置：
  - `items` 表。
- 依赖的表 / 文件 / 服务：
  - SQLite `items`。
  - iOS 本地 `UserDefaults` 只用于记录已见 URL，但实际去重已被关闭，仍然总是允许弹窗。

### 内容解析

- 前端入口：
  - 用户无显式解析按钮，抓取时隐式发生。
- 调用链路：
  - `/api/extract` `->` `extract_content()` `->` `detect_platform()` `->` 平台提取器 `->` `extract_generic()` fallback。
- 后端处理逻辑：
  - 小红书：优先 SSR `__INITIAL_STATE__`，其次 OG meta，再次 DOM 文本。
  - 抖音：优先 `_ROUTER_DATA`，其次 meta、`RENDER_DATA`、JSON-LD。
  - X/Twitter：优先 article GraphQL，再 fxtwitter/vxtwitter/oEmbed/meta fallback。
  - 通用网页：优先 DOM block 遍历保留图文顺序，再 trafilatura，再 BeautifulSoup fallback。
- 数据写入位置：
  - `items.canonical_text`
  - 条件性写入 `items.canonical_html`
  - 条件性写入 `items.content_blocks_json`
- 依赖的表 / 文件 / 服务：
  - [backend/services/extractor.py](/Users/hbz/everything-grabber/backend/services/extractor.py)
  - 依赖 `httpx`、`bs4`、可选 `trafilatura`
  - X 解析依赖外部 X / FXTwitter / VXTwitter / oEmbed 接口
- 当前实际限制：
  - `canonical_html` 和 `content_blocks_json` 只在 `result.media_urls` 存在时才会保存。
  - 纯文本网页即使提取出了结构化 HTML，当前也不会落库。
  - `/api/ingest` 虽然请求模型有 `canonical_html`，但后端当前没有写入该字段。

### 原网页 text / image 保存

- 前端入口：
  - 无单独入口，抓取成功后自动保存。
- 调用链路：
  - `/api/extract` `->` `download_media_list()` `->` 写本地文件 `->` 写 `media` 表。
- 后端处理逻辑：
  - 文本保存到 `items.canonical_text`
  - 图片/视频下载到 `backend/static/media/{item_id}/`
  - 成功下载后，将 `content_blocks_json` 与 `canonical_html` 中的媒体 URL 替换成 `/static/media/...`
  - 未下载成功的 `<img>` 在 HTML 重写阶段会被移除；部分视频站点会保留外部引用而不下载文件。
- 数据写入位置：
  - 文本：`items.canonical_text`
  - HTML：`items.canonical_html`
  - 图文块：`items.content_blocks_json`
  - 媒体索引：`media`
  - 媒体文件：`backend/static/media/{item_id}/...`
- 依赖的表 / 文件 / 服务：
  - [backend/services/downloader.py](/Users/hbz/everything-grabber/backend/services/downloader.py)
  - `yt-dlp` 仅用于 YouTube/Vimeo 类视频下载
- 当前实际限制：
  - 删除 item 只删数据库记录，不删本地媒体文件。
  - `final_url` 被存库，但前端与导出主要仍使用 `source_url`。
  - `inline_position` 被存库，但当前 Web UI 基本不消费它。

### library 存储

- 前端入口：
  - 首页画廊 / 列表视图。
- 调用链路：
  - `fetchItems()` `->` `GET /api/items`
- 后端处理逻辑：
  - 直接从 `items` 查询，joined load `media` 与 `folder`，按 `created_at desc` 返回。
- 数据写入位置：
  - 核心是 `items`、`media`、`folders`
- 依赖的表 / 文件 / 服务：
  - [backend/models.py](/Users/hbz/everything-grabber/backend/models.py)
  - [backend/routers/items.py](/Users/hbz/everything-grabber/backend/routers/items.py)
- 当前实际限制：
  - 没有分页 UI，前端默认一次请求 `limit=200`
  - 没有重复 URL 去重
  - 没有归档、收藏、标签、用户维度

### search

- 前端入口：
  - 顶部搜索框
  - Command Palette 文本搜索
- 调用链路：
  - 两者都调用 `GET /api/items?q=...`
- 后端处理逻辑：
  - 当前没有单独 `/search` API。
  - 搜索完全实现在 `routers/items.py` 中：
    - 先取候选 rows
    - 再做 query normalization、tokenization、intent detection、weighted scoring、时间衰减排序
  - 支持平台筛选、文件夹筛选。
- 数据写入位置：
  - 无额外写入。
- 依赖的表 / 文件 / 服务：
  - [backend/routers/items.py](/Users/hbz/everything-grabber/backend/routers/items.py)
  - `items_fts` FTS5 表虽然已创建，但当前搜索逻辑并未实际查询它；它现在更像是预留结构。
- 当前实际限制：
  - 搜索是“读全候选再 Python 排序”，不是标准全文索引查询。
  - 没有按用户隔离搜索空间。

### notion sync

- 前端入口：
  - Settings 中 OAuth 连接与 target 选择
  - Reader modal 中“同步至 Notion”
- 调用链路：
  - `GET /api/connect/notion/oauth/url`
  - `GET /api/connect/notion/oauth/callback`
  - `GET /api/connect/notion/databases`
  - `POST /api/connect/notion/sync/{item_id}`
- 后端处理逻辑：
  - OAuth 成功后把 access token 存进全局 `settings`
  - 同步时解析 `settings.notion_database_id`，它实际上可能存的是 page/database/data_source 任一种 ID
  - 若 target 是 data source，会尝试补齐 `Date` / `Source` / `Platform` 属性
  - 创建新 page，并把正文按 block 结构写入
  - 如果 item 之前已有 `notion_page_id`，当前实现不是“原地更新”，而是“新建一页 + 尝试归档旧页”
- 数据写入位置：
  - 配置：`settings`
  - 回写同步结果：`items.notion_page_id`
- 依赖的表 / 文件 / 服务：
  - [backend/routers/connect.py](/Users/hbz/everything-grabber/backend/routers/connect.py)
  - Notion API
- 当前实际限制：
  - `notion_database_id` 字段命名不准确，当前承担“任意 Notion sync target”的角色。
  - settings 接口会把 token 明文返回给前端。
  - 没有按 workspace/user 隔离配置。
  - 前端对 `data_source` 与 `page`/`database` 的显示标签有混用。

### obsidian sync

- 前端入口：
  - Settings 中 REST API 配置、目标文件夹、测试按钮
  - Reader modal 中“同步至 Obsidian”
- 调用链路：
  - `POST /api/connect/obsidian/test`
  - `POST /api/connect/obsidian/sync/{item_id}`
- 后端处理逻辑：
  - 使用 Local REST API 向当前打开的 vault 写文件
  - note 路径为 `{folder_path}/{safe_title}-{short_id}.md`
  - 媒体先上传到 `EverythingCapture_Media/{item.id}/`
  - Markdown frontmatter 包含 `item_id/source/platform/date`
  - 若已有 `obsidian_path`，会先检查文件是否还存在且内容是否匹配当前 item，匹配则原地覆盖
- 数据写入位置：
  - 配置：`settings`
  - 回写同步结果：`items.obsidian_path`
  - 外部文件：Obsidian 当前打开 vault
- 依赖的表 / 文件 / 服务：
  - [backend/routers/connect.py](/Users/hbz/everything-grabber/backend/routers/connect.py)
  - Obsidian Local REST API 插件
- 当前实际限制：
  - 配置是全局唯一的。
  - 只支持当前打开的单个 vault。
  - 测试接口使用的是“已保存设置”，不是 modal 中尚未保存的输入值。

### settings / integrations

- 前端入口：
  - 右上角 Settings modal
- 调用链路：
  - `GET /api/settings`
  - `POST /api/settings`
- 后端处理逻辑：
  - 永远读写 `settings` 表第一条记录；没有 profile/user scope
  - 同时承载 Notion、Obsidian、自动同步三类全局配置
- 数据写入位置：
  - `settings`
- 依赖的表 / 文件 / 服务：
  - [backend/routers/settings.py](/Users/hbz/everything-grabber/backend/routers/settings.py)
- 当前实际限制：
  - 秘钥明文存 SQLite
  - 秘钥明文经 API 返回前端
  - 没有审计、版本、加密、权限控制

## 4. Frontend Architecture

- 页面结构：
  - 单文件应用，静态 HTML/CSS/原生 JS 全在 [backend/static/index.html](/Users/hbz/everything-grabber/backend/static/index.html)
  - 主要区域是左侧 folder sidebar、顶部 toolbar、中间 library grid/list、Reader modal、Settings modal、Folder picker、Command Palette。
- 主要组件：
  - Command Palette：导入链接 / 搜索内容
  - Library cards/list rows：展示标题、平台、缩略图、同步状态
  - Reader modal：正文阅读、同步、下载 ZIP、移动文件夹
  - Settings modal：Notion / Obsidian / 自动同步
  - Folder sidebar：全部、未分类、自定义文件夹
- 状态管理方式：
  - 纯前端全局变量，没有框架状态库
  - 核心状态包括 `itemsData`、`filteredEntries`、`foldersData`、`currentView`、`currentFolderScope`、`selectedItemIds`、`currentOpenItemId`
- 关键交互流程：
  - 导入：Command Palette `->` `/api/extract` `->` 刷新 library
  - 浏览：`fetchItems()` `->` grid/list 渲染
  - 阅读：点击 item `->` modal `->` 根据平台决定 carousel 还是 article flow
  - 同步：modal 按钮 `->` sync API `->` 更新状态点
  - 文件夹：sidebar/folder picker `->` patch/bulk-folder API
- 当前必须保留的 UI/UX：
  - `Cmd/Ctrl + K` 作为统一入口
  - 画廊 / 列表双视图
  - 左侧文件夹导航 + 移动端 folder chips
  - Reader modal 内直接执行同步与 ZIP 导出
  - Notion / Obsidian 两个状态点
  - 搜索、平台筛选、文件夹筛选三者可叠加

## 5. Backend Architecture

- 服务结构：
  - 应用入口：`main.py`
  - ORM/连接：`database.py`、`models.py`
  - API 路由：`routers/ingest.py`、`items.py`、`folders.py`、`settings.py`、`connect.py`
  - 抓取与媒体服务：`services/extractor.py`、`downloader.py`
- 核心 API 列表：
  - `POST /api/extract`：服务端抓取并入库
  - `POST /api/ingest`：客户端已提取文本直入库
  - `GET /api/items`：列表 + 搜索 + 平台/文件夹过滤
  - `DELETE /api/items/{id}`：删 item
  - `GET /api/items/{id}/export/zip`：导出 zip
  - `PATCH /api/items/{id}/folder`：单条归类
  - `POST /api/items/bulk-folder`：批量归类
  - `GET/POST /api/settings`：全局集成配置
  - `GET/POST/PATCH/DELETE /api/folders...`：文件夹管理
  - `GET /api/connect/notion/oauth/url`：获取 OAuth URL
  - `GET /api/connect/notion/oauth/callback`：OAuth 回调
  - `GET /api/connect/notion/databases`：列出可见 target
  - `POST /api/connect/notion/sync/{id}`：同步到 Notion
  - `POST /api/connect/obsidian/sync/{id}`：同步到 Obsidian
  - `POST /api/connect/obsidian/test`：测试 Obsidian
  - `POST /api/connect/sync-status/refresh`：校验远端同步状态
- 主要业务流程：
  - 抓取链路：`extract -> parse -> save item -> download media -> rewrite local URLs -> optional auto sync`
  - 阅读链路：`get items -> open modal -> render canonical_html / content_blocks / fallback text`
  - 同步链路：`manual or auto sync -> remote write -> backfill notion_page_id/obsidian_path`

## 6. Database Schema

- `items`
  - 作用：收藏主表。
  - 核心字段：`id`、`created_at`、`source_url`、`final_url`、`title`、`canonical_text`、`canonical_text_length`、`platform`、`notion_page_id`、`obsidian_path`、`canonical_html`、`content_blocks_json`、`folder_id`
  - 现状说明：`status/error_reason/debug_json` 存在，但失败记录并未形成完整工作流。
  - 单用户写法：没有 `user_id`；`notion_page_id/obsidian_path` 直接挂在 item 上，默认全局唯一用户。
- `media`
  - 作用：媒体索引表。
  - 核心字段：`id`、`item_id`、`type`、`original_url`、`local_path`、`display_order`、`inline_position`
  - 表关系：`media.item_id -> items.id`
  - 单用户写法：没有用户隔离；文件路径无租户前缀。
- `folders`
  - 作用：全局文件夹分类。
  - 核心字段：`id`、`name`、`created_at`、`updated_at`
  - 表关系：`items.folder_id -> folders.id`
  - 单用户写法：`name` 全局唯一；没有 owner。
- `settings`
  - 作用：全局集成配置。
  - 核心字段：`id`、`notion_api_token`、`notion_database_id`、`notion_client_id`、`notion_client_secret`、`notion_redirect_uri`、`obsidian_rest_api_url`、`obsidian_api_key`、`obsidian_folder_path`、`auto_sync_target`
  - 单用户写法：只有一条记录，当前实际也是 1 条。
- `items_fts`
  - 作用：FTS5 虚拟表。
  - 核心字段：`item_id/title/content/source_url`
  - 现状说明：已建表并有 trigger，但当前搜索逻辑没有真正使用它。

## 7. Storage / Media Handling

- 图片、截图、附件当前全部存在本地文件系统，不是对象存储。
- 文件路径结构：
  - 静态根目录：`backend/static/`
  - 媒体目录：`backend/static/media/{item_id}/`
  - 文件名：`image_000.jpg`、`video_000.mp4`、`cover_000.webp`
- 媒体与内容的关联方式：
  - DB 层：`media.item_id`
  - 内容层：`content_blocks_json` 与 `canonical_html` 被替换成 `/static/media/...`
  - 导出层：ZIP 导出重新从本地文件拼 markdown 包
- 当前实际问题：
  - 删除 item 不删除磁盘媒体，磁盘会积累孤儿文件。
  - 没有存储抽象层，没有 CDN，没有签名 URL，没有生命周期管理。
  - 路径中只有 `item_id`，没有用户隔离。

## 8. Integration Architecture

- Notion 集成当前如何实现：
  - OAuth 获取 access token
  - token 存 `settings`
  - target 从 settings 读取并解析
  - 同步时新建 page 写 block
- Obsidian 集成当前如何实现：
  - 使用 Obsidian Local REST API
  - 先传媒体，再 PUT markdown note
  - note 内 frontmatter 记录 item_id/source/platform/date
- 配置是全局的还是局部的：
  - 全局唯一。
  - 不是“按用户”、“按 workspace”、“按 library”。
- token / config 当前如何保存：
  - SQLite `settings` 表明文保存
  - `GET /api/settings` 会把这些值返回给前端页面
- 其它实现细节：
  - Notion 日期显示固定按 `America/New_York`
  - Obsidian URL 会在 `http://localhost` 与 `https://127.0.0.1` 间尝试兼容

## 9. Single-User Assumptions

- 没有用户表，没有登录，没有 session，没有权限模型。
- 所有 API 都是匿名可调用的，只要能访问服务地址即可。
- `settings` 是全局唯一记录，不区分用户。
- `folders` 没有 `user_id`，名字全局唯一。
- `items` / `media` / `folders` 全部没有 `user_id`。
- 搜索默认就在全库范围内进行，没有 tenant filter。
- 文件系统路径没有用户隔离，都是 `media/{item_id}`。
- Notion token / Obsidian key 是全局共享凭证。
- 自动同步配置 `auto_sync_target` 是全局开关，不是 per user。
- 前端“用户头像区域”只是占位 UI，不对应真实用户系统。
- iOS App `APIClient` base URL 写死为 `http://127.0.0.1:8000/api`，明显是本地单机假设。
- `DISPLAY_TIMEZONE = America/New_York` 是硬编码时区，不是用户时区。
- 同步状态字段 `notion_page_id`、`obsidian_path` 直接写在 item 上，默认只有一套外部知识库映射。

## 10. SaaS Migration Risk Notes

- 最容易出问题的部分：
  - `settings` 全局单例。SaaS 化后首先会把所有人的 Notion/Obsidian 配置混在一起。
  - 所有表都没有 `user_id/workspace_id`，查询与写入默认全局可见。
  - 本地媒体目录没有租户隔离，URL 也是公开静态路径。
  - `/api/settings` 明文下发密钥，这在多用户环境下会直接变成严重安全问题。
  - Notion sync 不是 update，而是“新建并替换旧页”，多次同步行为需要谨慎兼容。
  - 删除 item 不删媒体文件，SaaS 后会快速形成存储垃圾与计费问题。
- 必须保持兼容的逻辑：
  - `/api/extract` 的平台识别与内容质量回退链路
  - 当前 reader modal 的图文恢复策略
  - ZIP 导出格式
  - Obsidian note 的 frontmatter 约定
  - Notion block 生成逻辑，尤其是图片/代码块/列表顺序
- 适合分阶段改造的部分：
  - 第 1 阶段：先引入 `users/workspaces` 与鉴权，不动提取核心
  - 第 2 阶段：给 `items/media/folders/settings` 全部补 owner scope
  - 第 3 阶段：抽离 media storage 到对象存储
  - 第 4 阶段：把 Notion/Obsidian 配置与同步状态改成 per user/per workspace
  - 第 5 阶段：补异步任务系统，替代当前请求内或 background task 直跑同步

## 扩展为 SaaS 前必须确认的关键点 Checklist

- [ ] 是否引入 `user_id` 还是 `workspace_id` 作为一层租户边界
- [ ] `settings` 是按用户、按 workspace，还是按 library 绑定
- [ ] Notion/Obsidian 凭证如何安全存储，是否需要加密与密钥管理
- [ ] `/api/settings` 是否彻底停止向前端返回敏感 token/key 明文
- [ ] 媒体文件是否迁移到对象存储，路径是否改成按租户隔离
- [ ] 现有 `/static/media/...` URL 是否还需要兼容旧数据
- [ ] `notion_database_id` 是否重命名为更准确的 `notion_target_id/type`
- [ ] Notion 同步是否继续采用“重建页面”还是改为“原地更新”
- [ ] Obsidian 是否继续支持单 vault，还是允许每用户独立 vault
- [ ] 搜索是否保留当前 Python ranking，还是切换到真正全文索引服务
- [ ] 删除 item 时是否补做本地/远端媒体清理
- [ ] iOS App 的 `127.0.0.1` 本地 API 地址如何迁移到真实 SaaS API
- [ ] 自动同步是否改成异步 job 队列，避免请求链路阻塞
- [ ] 当前 reader / folder / command palette UX 中哪些必须 1:1 保留
- [ ] 旧单用户 SQLite 数据如何迁移到多用户 schema
