# Everything Capture - 知识库集成功能（Notion OAuth & Obsidian）交接文档

> **致接手的 Agent (To the next Agent)**：
> 当前用户（USER）需要你接手并完成/修复本项目（Everything Capture）的「知识库自动同步与导出功能（Notion OAuth、Obsidian Local REST API、ZIP 打包）」。
> 
> 当前该功能**无法正常运转或存在 Bug**。为了避免你盲目扫描整个代码库，本文件详细罗列了目前已实现的系统架构、核心文件的物理路径、数据库结构以及具体的业务逻辑。请仔细阅读本指南后开始排查和开发。

---

## 1. 核心需求与业务流程说明 (Business Logic)

本项目是一个网页内容抓取工具（包含 Chrome 插件、手机 WebApp / Shortcut 收录入口，以及一个本地运行的 Python/FastAPI 后端和 Vanilla JS 前端看板）。现在新增的知识库集成功能需求如下：
1. **Notion OAuth 连接**：允许用户在网页端设置面板（Settings）中填写 Notion `Client ID`、`Client Secret` 和 `Redirect URI`。点击后通过 OAuth 2.0 拿到对应工作区的 `API Token` 并存入数据库。
2. **Obsidian 局域网同步**：允许用户填写 Obsidian Local REST API 的 `URL`（如 `http://127.0.0.1:27123`）和 `API Key`，直接通过 HTTP 协议把文章和图片推送到 Obsidian 本地 Vault。
3. **手动或按需触发 (手动/自动同步)**：
   - **手动**：前端点击弹窗中的「同步至 Notion」或「同步至 Obsidian」按钮，或「下载 ZIP」按钮。
   - **自动**：当抓取任务完成时（调用 `/api/ingest` 或 `/api/extract` 结束后），根据 `Settings.auto_sync_target`（`none`, `notion`, `obsidian` 或 `both`）在后台异步触发同步任务。

---

## 2. 核心代码文件路径与分工 (File Locations & Architecture)

整个功能主要涉及以下 **6** 个核心文件。请在进行修复前优先查看这些文件。

### 📌 数据库与模型 (Database & Models)
- **`backend/models.py`**：定义了 SQLite 数据库表。
  - 关注点：`Settings` 模型，里面新加了以下字段用于配置：`notion_api_token`, `notion_database_id`, `notion_client_id`, `notion_client_secret`, `notion_redirect_uri`, `obsidian_rest_api_url`, `obsidian_api_key`, `auto_sync_target`。
- **`backend/schemas.py`**：定义了 FastAPI 的请求/响应 Pydantic 模型。
  - 关注点：`SettingsResponse` 和 `SettingsUpdateRequest`，确保所有字段对齐。

### 📌 API 路由与业务逻辑 (API Routers)
- **`backend/routers/settings.py`**：
  - **功能**：处理 `GET /api/settings` 和 `POST /api/settings`，负责拉取和保存用户的集成设置（保存 Client ID、Secret 等）。
- **`backend/routers/connect.py`** (最核心的同步层)：
  - **功能 1: Notion OAuth 路由**：
    - `GET /api/connect/notion/oauth/url`：拼装 OAuth 授权跳转链接。
    - `GET /api/connect/notion/oauth/callback`：接收 Notion 跳回来的 `code`，使用带有 Basic Auth （Base64加密的 clientId:clientSecret）请求头向 Notion 换取 `access_token`，并保存到数据库 `Settings` 中。最后重定向回 `/?notion_auth=success`。
  - **功能 2: Notion 同步路由** (`POST /api/connect/notion/sync/{item_id}`)：
    - 将数据库里提取到的文章 `canonical_text` 解析成段落，按照 Notion Block API 的要求进行 2000 字符分片，将 `original_url` 构建为 external image block，最后发送请求创建 Notion 页面。
  - **功能 3: Obsidian 同步路由** (`POST /api/connect/obsidian/sync/{item_id}`)：
    - 先把内容内包含的物理本地图片（`/static/...`）通过 POST 接口发送至设定的 Obsidian REST API 路径：`/vault/EverythingCapture_Media/图片名`。然后再将其组装成一段带 YAML 头的 Markdown，最后请求创建 Markdown 文件 `vault/文章标题.md`。
- **`backend/routers/ingest.py`**：
  - **功能**：原有的抓取链路，新增了 `BackgroundTasks` 以支持非阻塞的**自动同步功能**（函数 `background_auto_sync`）。抓取完成后如果 `Settings` 中的 `auto_sync_target` 设定了目标，则在此处触发相应的 API 调用。
- **`backend/routers/items.py`**：
  - **功能**：包含一个新接口 `GET /api/items/{item_id}/export/zip` 处理并流式回传一个包含了 `content.md` 和附带真实图片的本地 ZIP 文件。

### 📌 前端用户界面 (Frontend)
- **`backend/static/index.html`** (2200 多行的单文件原生 JS 网页)：
  - **设置弹簧 (Settings Modal)**：位于文件大约 `1128` 行附近的 `#settingsOverlay`，通过这可以直接配置所有的 OAuth 密钥。
  - **"Connect to Notion" 按钮逻辑**：大约在 `1270` 行附近，在跳转 OAuth 前会优先将当前的 inputs (`client_id`, `client_secret`) 通过 POST 发给 `/api/settings` 存起来，然后再请求 `/oauth/url` 去重定向授权。
  - **OAuth Callback 监听**：页面加载完毕 `fetchItems()` 后，紧接着在 `1698` 行左右有一段 URL Query 解析 `?notion_auth=...` 弹出 Toast 的逻辑。
  - **文章详情弹窗扩展**：在大约 `1585` 行的 `openModal(...)` 末尾动态拼接了三个处理同步和下载 ZIP 的按钮并赋予了对应的 `onclick` 事件（`syncItem()`，`downloadZip()`）。

---

## 3. 下一步你该做的事情 (What You Need to Do)

用户反馈“现在它用不了 (it doesn't work currently)”。很可能是我们在 Notion OAuth 的流程中或是 Obsidian Local API 的跨域和授权上出现了细微的问题。建议你优先排查以下常见雷区：

1. **Notion OAuth Callback 问题检查**：
   - 检查 `backend/routers/connect.py` 里的 `notion_oauth_callback` 是否正常拿到 code 并按照 Notion 的坑爹规范换到了 `access_token`（Notion OAuth 常常因为 HTTP Basic Auth 的拼装或 `redirect_uri` 的比对严格度报错 `400 Bad Request`）。在处理这些时建议给后端加上更详尽的 `logger.error(response.text)` 打印出来给用户调试。
2. **Notion API Payload 组装检查**：
   - 查看 `connect.py` 中 `sync_to_notion`：Notion 的 block 限制很多，如果标题或 chunk 包含不支持的字符，甚至如果某个 `original_url` 无效，整个页面创建都会 `400`。
3. **前端的 Redirect 时序**：
   - 前端点击 Connect 后是先 `POST /api/settings` 再去拿 `url` 的，检查看是否有竞争条件（race condition）或者前端 JavaScript 控制台抛错导致被阻止。
4. **下载 ZIP 的跨域/路径问题**：
   - 虽然写好了接口但是需要确认前端 `window.location.href = /api/items/{id}/export/zip` 时文件路径的映射是否有问题。

**任务执行要求：**
- 全局使用 **Python 3 / FastAPI** 与 **Vanilla JavaScript**（不允许引入 React/Vue 等前端框架，这是个零依赖原生项目）。
- 从后端运行日志和前端 Console 去找找线索，修改前先去阅读我罗列出的相关文件的实现逻辑。
