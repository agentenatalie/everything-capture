# Everything Grabber - 项目架构与文件导览

本文档旨在为其他编码代理（Coding Agents）和开发者提供整个项目的全景概览。在进行修改前，请仔细阅读本指南，以便快速理解每个文件的核心功能、限制以及不可触碰的红线，避免进行不必要的全局文件分析或破坏现有逻辑。

本项目主要包含三部分：基于 FastAPI 的 Python 后端、Vanilla HTML/CSS/JS 构成的前端看板（挂载在 static 目录下），以及一个面向手机浏览器 / WebApp / Shortcut 的移动收录入口。

---

## 一、 后端核心文件 (Backend Core)

### 1. `backend/main.py`
- **功能 / 作用**: FastAPI 应用的入口文件。负责创建数据库表，注册各个领域的路由（Router），并挂载 `/static` 静态文件夹。同时提供了根路径 `/` 的重定向至看板页面。
- **需要保留的内容**: 所有路由的挂载顺序，以及 `StaticFiles` 的挂载配置。
- **不可被修改的部分**: 应用的核心初始化逻辑和依赖注入结构不应被轻易修改。
- **限制**: 对于添加新的顶级中间件（Middleware），需确保不影响正常的静态文件服务和 CORS 等。

### 2. `backend/database.py`
- **功能 / 作用**: 包含 SQLAlchemy 的基础配置，如 Engine 创建、SessionLocal 以及 `get_db` 依赖项生成器。
- **需要保留的内容**: `check_same_thread=False` 参数对于 SQLite 和 FastAPI 的工作必不可少；`get_db` generator 也必须被所有路由继续采用。
- **不可被修改的部分**: 数据库的连接 URI (`sqlite:///./items.db`) 除非有迁移至 PostgreSQL/MySQL 的明确需求。

### 3. `backend/models.py`
- **功能 / 作用**: 定义数据库实体（SQLAlchemy ORM 模型），包括 `Item` 和 `Media` 两张核心表。负责声明各字段属性及主外键关联关系（relationship）。
- **需要保留的内容**: `Item` 和 `Media` 的级联删除逻辑 (`cascade="all, delete-orphan"`)。
- **不可被修改的部分**: 已有的关键字段名（如 `canonical_text`, `content_blocks_json`, `status`），因为这些直接影响着与之前存量数据的兼容性。

### 4. `backend/schemas.py`
- **功能 / 作用**: 定义 Pydantic 模型，用于请求载荷的验证和响应序列化（例如 `ItemResponse`, `IngestRequest`）。它是与前端及手机 WebApp / Shortcut 收录链路进行 API 交互的契约。
- **相关限制**: 所有新增的属性都应提供 Optional 或者默认值，以避免向后不兼容导致客户端报错。
- **不可被修改的部分**: 不能重命名现有的响应字段（如 `item_id`, `media`, `inline_position`），因为它们已被前端或客户端重度依赖。

---

## 二、 后端路由模块 (Backend Routers)

### 1. `backend/routers/items.py`
- **功能 / 作用**: 暴露管理收录条目的 API（如 `GET /api/items` 分页获取抓取列表，`DELETE /api/items/{item_id}` 删除条目）。
- **需要保留的内容**: `GET /api/items` 时组装返回体中有关媒体排序部分的代码，需保证 `inline_position` 正确映射以供前端富文本渲染使用。
- **限制**: 修改删除逻辑时，不能破坏数据库中对 `Media` 的级联删除。

### 2. `backend/routers/ingest.py`
- **功能 / 作用**: 最核心的内容摄入路由。包含两个接口：
  - `POST /api/ingest`: 供本地文本回填 / 兼容导入使用的上传接口。
  - `POST /api/extract`: 供前端主入口使用的服务端 URL 解析接口。此接口会调用提取器并利用下载器将媒体对象存入数据库。
- **需要保留的内容**: `extract` 接口中，针对图片和视频 URL 返回映射的替换逻辑（生成安全的 `canonical_html` 和 `content_blocks_json`），非常关键且脆弱。
- **不可被修改的部分**: 必须确保提取失败时能够正确地 `db.rollback()`，以免数据库出现脏数据。

### 3. `backend/routers/connect.py`
- **功能 / 作用**: 用于关联和导出数据至第三方平台（如 Notion，Obsidian）的占位路由（Phase 2）。暂无实质逻辑。

---

## 三、 后端服务模块 (Backend Services)

### 1. `backend/services/extractor.py`
- **功能 / 作用**: **（高度敏感文件）** 负责解析来自不同平台（小红书、抖音、Twitter/X 乃至通用网页）的内容提取服务。包含了高度定制的正则表达式、SSR (Server-Side Rendering) JSON 树深度遍历逻辑以及多种 Fallback 机制。
- **相关限制**: 这个文件极其复杂，各个提取策略之间有级联降级机制（如 小红书先查 \_\_INITIAL_STATE\_\_，后查 OG meta；推文先查公共 API 后抓 meta）。
- **需要保留的内容**: 对不同平台的 User-Agent (`_MOBILE_UA`, `_DESKTOP_UA`) 区分必须保留以免被封禁。用于提取 HTML 中正文内图片相对位置的算法 `_inline_position` 也需无条件保留，这是支持正文混排渲染的核心机制。
- **不可被修改的部分**: 不要试图用一个通用大一统的方法取代特定网站的提取逻辑，也不要更改现有的 `_is_meaningful_image` 的排除模式列表。

### 2. `backend/services/downloader.py`
- **功能 / 作用**: 后台下载远程图片、视频，将它们存储在本地 `static/media/` 中。包含文件名后缀的容错推理能力（如微信的 `wx_fmt`）。
- **相关限制**: 依赖并发下载，不能轻易修改 `httpx` 的流式下载。
- **不可被修改的部分**: 本地路径生成结构 `relative_path = f"media/{item_id}/{filename}"` 不能变动，否则将破坏所有正在数据库中生效的图片路径。

---

## 四、 前端看板代码 (Frontend / Web)

### 1. `backend/static/index.html` (及相关页面)
- **功能 / 作用**: Single-Page Application 前端文件负责渲染瀑布流 / 列表展示所有抓取的摘要内容及原平台的图文。内含极其复杂且定制化的 Vanilla JS (逻辑处理) 并且 CSS 写在了文件内。
- **针对 UI 修改的红线与限制**:
  - **核心视觉风格绝不可破坏**: 现有的 CSS 变量系统（`:root` 中的定义）和基于**玻璃拟态（Glassmorphism）**的视觉设计、背景模糊、光影渐变以及卡片悬浮动画必须被严格保留，不得随意改为普通的扁平化或重写主色调。
  - **DOM 结构与绑定的脆弱性**: UI 中的核心 DOM ID 和大类名（如 `.extract-bar`, `.grid`, `.filter-input`, `.delete-btn`, 各种视图切换按钮以及 Modal 弹窗的相关容器）被底部的 Vanilla JS (原生 JavaScript) 强绑定。任何修改 HTML 结构或类名的行为都必须同步更新 JS 中的事件监听和属性获取，否则会导致致命的交互失效。
  - **复杂的图文混排与功能逻辑**: 针对 API `/api/items` 请求返回的分页渲染逻辑，必须要能兼容带有 `inline_position` 数据的图片排列（保证动态插入正文的图片顺序不乱）。此外，最近恢复的“删除操作”及其相关的 `toast` 提示反馈流程绝不可被移除。

---

## 五、 手机 Web 入口 (iOS WebApp / Mobile Web)

### 1. `backend/static/index.html`
- **功能 / 作用**: 同一首页同时承载桌面 Library 与手机端收录壳层。手机端主要依赖 `#mobileCaptureShell`、输入 pill、文件夹选择和提交反馈。
- **针对 UI 修改的红线与限制**:
  - **移动壳层必须保留最短路径**: 手机入口的目标是快速投递，不要把桌面看板的复杂控件搬进去。
  - **移动与桌面共用同一 DOM 基线**: 改动 ID、类名或弹层结构时，必须同步核对桌面 Library 与手机壳层两条链路。

### 2. `backend/routers/phone_webapp.py`
- **功能 / 作用**: 处理 `POST /api/phone-extract`，把手机 WebApp / Shortcut 的请求转成本地处理或 capture queue 入队。
- **需要保留的内容**: 文件夹分配逻辑要继续复用 `normalize_requested_folder_ids`、`resolve_folders` 和 `sync_item_folder_assignments`，保证手机入口与桌面 Library 的归类行为一致。

---

## 六、 给 AI 代理的最佳实践总结

当你接到用户的请求时，请参考上述导览做出规划：
1. **如果是新增爬虫支持**：主要修改 `backend/services/extractor.py` 中的解析路由。
2. **如果涉及数据库字段变更**：务必同时更新 `models.py`、`schemas.py` 与 `routers/items.py` 或 `routers/ingest.py`。最后在前端 `index.html` 中增加呈现逻辑。
3. **如果是提升性能/搜索**：请避免在页面初始加载进行耗时的全局拉取。
4. **如果遇到 bug**：先确定是桌面 Web、手机 WebApp / Shortcut，还是服务端提取失败，再沿着 `phone_webapp.py` / `ingest.py` -> `extractor.py` 的链路查询。
