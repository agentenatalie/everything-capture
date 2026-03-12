# 文件夹 / 分类管理增量方案

## 背景

当前项目是 FastAPI + SQLite + 单文件静态前端：

- 前端主界面集中在 `backend/static/index.html`
- 顶部工具栏已包含视图切换、统计、搜索、平台筛选
- 内容列表由 `/api/items` 提供，前端通过 `fetchItems()` 拉取并渲染
- 数据模型目前只有 `items`、`media`、`settings`

目标不是重做页面，而是在现有卡片式看板体验上，新增一层轻量整理能力。

## 实施约束

根据 `md-docs/UI_NON_NEGOTIABLES.md` 和 `md-docs/project_overview.md`，本次实现必须额外遵守：

- 不修改网页详情的三层渲染优先级：
  1. `content_blocks_json`
  2. `canonical_html`
  3. inline fallback
- 不合并社媒和网页文章的详情渲染路径
- 不删除或重命名以下 DOM / JS 合约：
  - `modalTitle`
  - `modalContent`
  - `modalFooter`
  - `readerStatusDots`
  - `toggleFullscreenBtn`
  - `closeModal`
  - `openModalById(...)`
  - `openModalByItem(...)`
- 不破坏 `getItemThumbnail(...)`、画廊卡片缩略图、列表缩略图
- UI 调整只改外围布局和新增交互，不重写受保护阅读逻辑

## 结论

最适合当前页面的方案是：

- 桌面端：增加一个轻量左侧文件夹侧边栏
- 移动端：侧边栏折叠为顶部横向文件夹 chips
- 内容卡片：增加一个轻量“加入文件夹”入口，不改卡片主体结构
- 批量操作：以“选择模式”方式进入，不在默认态长期占据视觉权重

这是对当前布局侵入最小、认知最自然的做法。  
原因：你现在已经有顶部搜索/筛选，文件夹如果继续堆在顶部，会让工具栏过密；左侧导航更适合作为“浏览维度”，而卡片区继续作为主内容区。

---

## 1. 最佳页面改法

### 页面结构

将当前：

- `board-toolbar`
- `grid`

改成：

- `board-shell`
  - `folder-sidebar`
  - `board-content`
    - `board-toolbar`
    - `folder-mobile-strip`（仅移动端显示）
    - `grid`

### 视觉原则

- 不改变现有玻璃感、圆角、轻 dashboard 语言
- 文件夹侧栏做成低存在感的浅玻璃 panel
- 不加厚重表格、树状结构、权限管理、复杂层级
- 文件夹只是“筛选与整理层”，不是新的主画面

### 建议宽度

- 侧栏宽度：`220px ~ 240px`
- 内容区：继续沿用当前 `board-toolbar + grid/list-view`
- 小屏下取消左右分栏，文件夹改为横向滚动 chips

---

## 2. UI 结构调整建议

## 2.1 顶层结构

当前工具栏位于 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L1600) 附近，建议只包一层外壳，不动内部信息层级：

```html
<main>
  <div class="board-shell">
    <aside class="folder-sidebar"></aside>
    <section class="board-content">
      <div class="board-toolbar"></div>
      <div class="folder-mobile-strip"></div>
      <div id="grid"></div>
    </section>
  </div>
</main>
```

## 2.2 左侧文件夹侧边栏

结构建议：

- 侧栏标题：`文件夹`
- 右上角：`+ 新建`
- 默认项：
  - `全部内容`
  - `未分类`
- 用户文件夹列表：
  - `产品灵感`
  - `AI 工具`
  - `竞品素材`
- 每项右侧显示数量
- 激活项使用当前系统已有的轻高亮态，不做重背景块

### 侧栏每项建议

- 左侧文件夹图标
- 中间名称
- 右侧数量 badge
- hover 显示轻度背景
- active 保持白底或更强玻璃底

## 2.3 移动端

小屏不保留左栏，改为：

- 工具栏下方增加 `folder-mobile-strip`
- 横向滚动展示：
  - `全部`
  - `未分类`
  - 各文件夹
  - `+ 新建`

---

## 3. 新增按钮 / 入口放在哪里

## 3.1 新建文件夹

主入口：

- 放在左侧侧栏标题右侧 `+ 新建`

移动端入口：

- 放在顶部 folder chips 的最后一个 `+ 新建`

次入口：

- 在“加入文件夹”弹层里，如果当前没有合适文件夹，可直接 `新建并加入`

不建议放在顶部主工具栏。  
原因：顶部已经承载搜索、平台筛选、视图切换、设置，继续加“新建文件夹”会打断主检索流。

## 3.2 批量整理

建议放在顶部工具栏左侧，紧跟 `stats` 之后，作为一个轻按钮：

- `选择`

进入选择模式后：

- `stats` 切换为 `已选择 3 条`
- 顶部右侧出现：
  - `加入文件夹`
  - `取消选择`

默认态不显示批量操作区，避免界面变重。

## 3.3 文件夹管理入口

对单个文件夹：

- 侧栏 hover 时显示 `···`
- 菜单项：
  - `重命名`
  - `删除文件夹`

删除文件夹默认行为：

- 不删内容
- 将该文件夹内内容置为“未分类”

---

## 4. 每条内容卡片如何加入文件夹

## 单条操作

当前卡片 footer 在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L2976) 附近，列表 actions 在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L2937) 附近。

建议在现有删除按钮前新增一个轻量文件夹按钮：

- 图标：文件夹
- title：`加入文件夹`

点击后打开一个小型 popover / action sheet：

- 顶部：`加入文件夹`
- 第一项：`未分类`
- 第二项起：用户已有文件夹
- 底部：`+ 新建文件夹`

如果该内容已在某个文件夹中：

- 当前项显示勾选
- 可切换到其他文件夹

## 卡片上的文件夹展示

建议在卡片 meta 区域增加一个轻 tag：

- 有文件夹：显示 `📁 AI 工具`
- 未分类：不显示 tag，避免信息噪音

列表视图里可放在 `list-meta` 最后一个字段。

## 阅读弹窗中的入口

当前详情弹窗 footer 在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L3067) 附近。

建议再补一个按钮：

- `移动到文件夹`

这样用户在阅读后也能顺手归类。

---

## 5. 文件夹列表如何展示

## V1 展示规则

顺序：

1. `全部内容`
2. `未分类`
3. 用户创建的文件夹（按 `updated_at desc` 或 `name asc`）

每项展示：

- 图标
- 名称
- 数量

### 数量定义

- `全部内容`：全部 items 数量
- `未分类`：`folder_id IS NULL` 的 items 数量
- 用户文件夹：该 folder 下 items 数量

### 当前选中态

选中某个文件夹时：

- 卡片区域只展示该文件夹内容
- 顶部 stats 改为：
  - `全部 16 篇 · 当前文件夹 5 篇`
  - 如果再叠加搜索，则：
    - `当前文件夹 5 篇 · 匹配 2 篇`

### 空态文案

- 某文件夹为空：`这个文件夹里还没有内容`
- 没有任何文件夹：`先新建一个文件夹，把常看的内容整理起来`

---

## 6. 数据结构设计

## V1：单文件夹归属

这是当前最合适的方案，简单、查询直接、改动小。

### folders 表

```sql
CREATE TABLE folders (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_folders_name ON folders(name);
```

### items 表增加字段

```sql
ALTER TABLE items ADD COLUMN folder_id TEXT REFERENCES folders(id);
CREATE INDEX idx_items_folder_id ON items(folder_id);
```

### SQLAlchemy 模型

在 [backend/models.py](/Users/hbz/everything-capture/backend/models.py#L10) 增加：

- `Folder` 模型
- `Item.folder_id`
- `Item.folder` relationship
- `Folder.items` relationship

建议字段：

- `Folder.id: String`
- `Folder.name: String`
- `Folder.created_at: DateTime`
- `Folder.updated_at: DateTime`

## 为未来多文件夹预留

V1 不直接上多对多。  
预留方式：

- API 字段命名上保留扩展空间
- 前端状态命名用 `folderId` 而不是 `category`

未来如果要支持“一条内容属于多个文件夹”，再迁移到：

- `item_folders(item_id, folder_id)`

当前不要提前复杂化。

---

## 7. 前后端实现方案

## 7.1 后端

当前后端以 [backend/routers/items.py](/Users/hbz/everything-capture/backend/routers/items.py#L476) 为核心，建议新增 `routers/folders.py`。

### 新接口

#### 文件夹列表

`GET /api/folders`

返回：

```json
[
  {
    "id": "uuid",
    "name": "AI 工具",
    "item_count": 6,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

#### 新建文件夹

`POST /api/folders`

请求：

```json
{ "name": "AI 工具" }
```

#### 重命名

`PATCH /api/folders/{folder_id}`

请求：

```json
{ "name": "AI 产品" }
```

#### 删除文件夹

`DELETE /api/folders/{folder_id}`

行为：

- 删除 folder
- 将该 folder 下的 items 设为 `NULL`

#### 单条归类

`PATCH /api/items/{item_id}/folder`

请求：

```json
{ "folder_id": "uuid" }
```

支持传 `null` 表示移出文件夹。

#### 批量归类

`POST /api/items/bulk-folder`

请求：

```json
{
  "item_ids": ["id1", "id2"],
  "folder_id": "uuid"
}
```

### 修改现有列表接口

扩展 [backend/routers/items.py](/Users/hbz/everything-capture/backend/routers/items.py#L476)：

- `folder_id: Optional[str] = None`
- `folder_scope: str = "all"`

规则：

- `folder_scope=all`：不过滤文件夹
- `folder_scope=unfiled`：`Item.folder_id.is_(None)`
- `folder_id=<uuid>`：过滤指定文件夹

这样前端不需要改整体数据流，只是给 `getActiveSearchParams()` 多加两个参数。

### 返回字段扩展

扩展 `ItemResponse`：

- `folder_id`
- `folder_name`

这样卡片不必额外查一次 folder map。

### 统计头

保留现有：

- `X-Total-Count`
- `X-Visible-Count`
- `X-Returned-Count`

可新增：

- `X-Folder-Count`

但不是必须。V1 前端可以直接复用现有 header 语义。

## 7.2 前端

当前前端状态几乎都在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L1787) 之后的 script 中维护，建议继续沿用。

### 新状态

```js
let foldersData = [];
let currentFolderScope = 'all'; // all | unfiled | folder
let currentFolderId = null;
let selectionMode = false;
let selectedItemIds = new Set();
```

### 新方法

- `fetchFolders()`
- `renderFolderSidebar()`
- `setActiveFolder(scope, folderId = null)`
- `openFolderPicker(itemId)`
- `assignItemToFolder(itemId, folderId)`
- `assignItemsToFolder(itemIds, folderId)`
- `toggleSelectionMode()`
- `toggleItemSelection(itemId)`

### 修改现有方法

#### `getActiveSearchParams()`

在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L2312) 附近扩展：

- 当前选中 `未分类` 时加 `folder_scope=unfiled`
- 当前选中文件夹时加 `folder_id=<id>`

#### `fetchItems()`

在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L2803) 附近保留原逻辑，只增加：

- 根据 folder filter 取数据
- stats 文案增加当前文件夹语义

#### `renderItems()`

在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L2901) 附近增加：

- 卡片/列表的 folder tag
- 单条“加入文件夹”按钮
- 选择模式下的 checkbox

#### `openModalByItem()`

在 [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html#L3035) 附近增加：

- `移动到文件夹` 按钮

---

## 8. 数据库变更

## 推荐做法

你当前项目已经有运行时补列逻辑，见 [backend/database.py](/Users/hbz/everything-capture/backend/database.py#L16)。  
这个项目没有正式 Alembic 迁移体系，因此 V1 可以继续沿用同样风格。

### 在 `ensure_runtime_schema()` 中增加

1. 创建 `folders` 表
2. 给 `items` 增加 `folder_id`
3. 创建索引

示意：

```python
def ensure_runtime_schema():
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS folders (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        item_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(items)").fetchall()
        }
        if "folder_id" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN folder_id VARCHAR REFERENCES folders(id)")

        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_folder_id ON items(folder_id)")
    ...
```

### 为什么不建议现在上独立迁移系统

- 当前项目整体很轻
- schema 很小
- V1 只是新增一个表和一个外键字段
- 继续沿用 runtime schema patch 能最快落地

如果后面功能开始增多，再补 Alembic。

---

## 9. 兼容现有代码的最小改动策略

## 前端最小改动

- 不拆分前端工程
- 继续在现有 `index.html` 中增量加 HTML / CSS / JS
- 不改现有卡片结构主骨架
- 不重写搜索、平台筛选、视图切换逻辑
- 文件夹仅作为一层新增 filter state

## 后端最小改动

- 继续复用 `items` 路由风格
- 新增 `folders.py` 路由
- `ItemResponse` 只追加字段，不破坏旧字段
- `/api/items` 只加可选参数，不破坏旧调用

## 数据库最小改动

- 新增 `folders`
- `items` 增加可空 `folder_id`
- 不改已有媒体和全文逻辑

---

## 10. 推荐的开发顺序

## Phase 1: 主链路

1. 数据库加 `folders` 和 `items.folder_id`
2. 后端新增 folders CRUD
3. `/api/items` 支持 folder filter
4. 前端渲染侧栏
5. 前端支持单条加入文件夹
6. 前端支持“全部 / 未分类 / 某文件夹”切换

这一步做完，就满足你的核心目标。

## Phase 2: 补齐易用性

1. 批量选择模式
2. 批量加入文件夹
3. 文件夹重命名
4. 文件夹删除
5. 移动端文件夹 chips

## Phase 3: 可选增强

1. 最近使用文件夹置顶
2. 新建后自动加入当前选中内容
3. 文件夹拖拽排序
4. 多文件夹归属

---

## 11. 我给你的最终建议

如果只做一个最稳的版本，就做下面这条：

- 左侧轻量文件夹侧栏
- 顶部不新增重入口
- 卡片加一个文件夹按钮
- 支持新建文件夹
- 支持将单条内容移入文件夹
- 支持查看“全部 / 未分类 / 某文件夹”
- 第二阶段再补批量整理

这是和你现有页面融合度最高、改动最小、上线最快的版本。
