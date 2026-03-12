# SaaS Sidebar Notes

## 目的

这份文档记录当前 Web 看板里 SaaS 风格 sidebar 的结构约定，尤其是底部用户区域的位置，方便后续给用户体系、通知、账户设置、后端连接状态等功能继续接线。

如果未来 sidebar 的 DOM 位置、选择器、交互入口有变化，必须同步更新这份文档。

## 当前侧边栏实现

主文件：

- [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html)

当前 sidebar 主容器：

- `#boardShell`
- `.folder-sidebar`
- `.folder-panel`

当前 sidebar 的 5 个主要块：

1. 顶部 header：标题、`+ 新建`、收缩按钮、搜索框
2. 文件夹列表：`#folderList`
3. 底部用户区域：`#sidebarUserArea`
4. 收缩态控制：`#toggleSidebarBtn`
5. 收起后的展开按钮：`#showSidebarBtn`

## 当前框架行为

- sidebar 是页面级固定左栏，不是居中的浮层卡片
- sidebar 贴住页面左侧，从顶部到底部占满可视高度
- 收起时为“完全隐藏”，不是窄栏，也不保留图标轨道
- 展开入口固定为页面左上角的 `#showSidebarBtn`
- 主内容区在 sidebar 收起后自动扩展

## 用户区域位置

当前用户区域 DOM 位于：

- [backend/static/index.html](/Users/hbz/everything-capture/backend/static/index.html)

位置说明：

- 用户区域是 `.folder-panel` 内的最后一个块
- 它固定处在文件夹列表 `#folderList` 的下方
- 视觉上位于 sidebar 底部，适合作为未来用户能力的稳定挂载区

核心选择器：

- `#sidebarUserArea`
- `.sidebar-user`
- `.sidebar-user-profile`
- `.sidebar-avatar-container`
- `.sidebar-avatar`
- `.sidebar-status-dot`
- `.sidebar-user-actions`

当前结构：

```html
<div class="sidebar-user" id="sidebarUserArea">
  <div class="sidebar-user-profile">
    <div class="sidebar-avatar-container">
      <div class="sidebar-avatar">...</div>
      <div class="sidebar-status-dot"></div>
    </div>
  </div>
  <div class="sidebar-user-actions">
    <button type="button" title="帮助">...</button>
    <button type="button" title="通知">...</button>
  </div>
</div>
```

## 后续接用户功能时建议挂载的位置

后续如果要加用户相关能力，优先接到这几个位置：

- 头像点击：
  - `#sidebarUserArea .sidebar-user-profile`
  - 适合挂：账户菜单、登录状态、个人资料页入口
- 右侧按钮组：
  - `#sidebarUserArea .sidebar-user-actions`
  - 适合挂：帮助中心、通知中心、设置、客服入口
- 在线状态点：
  - `.sidebar-status-dot`
  - 适合挂：连接状态、同步状态、在线/离线、授权状态

## 后端连接建议

如果后续要把这个区域接到真实后端，建议 API 分层如下：

- `GET /api/me`
  - 返回当前用户基础信息、头像、昵称、登录态
- `GET /api/notifications/summary`
  - 返回未读数、最近通知摘要
- `GET /api/account/status`
  - 返回订阅、授权、连接状态

前端上，优先新增一个独立方法：

- `fetchSidebarUserState()`

不要把用户区域状态混进 `fetchItems()` 或 `fetchFolders()`，避免把内容列表和用户状态耦合在一起。

## 更新规则

如果未来发生以下变化，必须同步更新本文件：

- `#sidebarUserArea` 被重命名
- 用户区域移动到 sidebar 其他位置
- 用户区域从 sidebar 移出
- `#showSidebarBtn` 的位置或行为变化
- 帮助 / 通知按钮的结构变化
- 头像和状态点的 DOM 结构变化
- sidebar 收缩逻辑改变，导致用户区域在收缩态有新行为

## 当前设计约束

- 用户区域目前是占位 UI，先保留，不绑定业务逻辑
- 侧边栏支持收起，且是完全隐藏式；用户区域仅在展开态显示
- 文件夹导航项不再使用左侧圆形图标
- 当前 sidebar 参考 SaaS 左栏风格，只保留一个“文件夹”导航区，不保留 `Content Types`
