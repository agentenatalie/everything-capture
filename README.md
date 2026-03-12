# Everything Capture

一个本地优先的内容收录与知识库整理仓库，核心目标是：

- 抓取网页 / 社交平台内容
- 下载并保存本地媒体
- 在站内统一浏览、整理、搜索内容
- 同步到 Notion / Obsidian
- 基于同一套知识源提供 AI Chat / Agent 能力

## 仓库结构

```text
everything-capture/
├── backend/            FastAPI 主应用、前端静态资源、同步与 AI 能力
├── capture_service/    可选的云端 capture 队列服务
├── md-docs/            交接文档、架构说明、实现备忘
├── scripts/            部署/打包辅助脚本
├── tasks/              本地任务与经验记录
└── run                 本地启动入口
```

## 主要目录

- [backend](backend)
  站内主应用。包含 API 路由、SQLAlchemy 模型、同步服务、AI 服务，以及前端静态页面。
- [capture_service](capture_service)
  面向手机 WebApp / Shortcut 的可选 capture 队列服务。
- [md-docs](md-docs)
  历史设计说明和项目背景。适合补上下文，不适合作为运行入口。

## 本地运行

仓库自带一个 `run` 脚本，默认会：

- 启动 `backend.main:app`
- 监听 `0.0.0.0:8000`
- 在配置了 `CAPTURE_SERVICE_URL` 时自动拉起本地 processing worker

示例：

```bash
./run
```

如果你只想手动起后端，也可以直接用 `uvicorn`，但这个仓库当前默认工作流是走 [`run`](run)。

## 上传 GitHub 前的约定

以下内容默认不应提交：

- 本地数据库，例如 `*.db`
- 虚拟环境，例如 `backend/venv/`
- 下载媒体与运行缓存，例如 `backend/static/media/`、`backend/.local/`
- 临时截图、调试文件，例如 `tmp-*`
- 本地 IDE / Claude 配置

这些规则已经写进 [`.gitignore`](.gitignore)。

## 文档入口

- 总体背景说明：[`md-docs/README.md`](md-docs/README.md)
- 云端 capture 服务说明：[`capture_service/README.md`](capture_service/README.md)

## 备注

这个仓库现在是“源码 + 本地运行状态”混在一起使用的形态。上传 GitHub 时，建议只保留源码、文档、脚本和测试，把所有本地运行产物留在忽略规则里。
