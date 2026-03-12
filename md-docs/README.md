# Everything Capture

**Everything Capture** 是一个跨平台的高质量内容抓取与知识管理系统，旨在帮助用户从各个主流平台（如小红书、微信公众号、抖音、X/Twitter 等）一键无缝抓取网页内容、解析正文，并将内容与多媒体资源永久保存。当前系统由 **FastAPI 服务端**、**网页看板**，以及面向手机浏览器 / iOS WebApp / Shortcut 的移动收录入口组成。

## 🌟 核心特性

- **跨平台深度抓取**：原生支持并优化了小红书、微信公众平台、抖音、X 等具有复杂动态加载与防抓取机制的平台内容提取。
- **手机 WebApp / Shortcut 收录**：在同一套 Web 前端中提供移动收录入口，可作为 iOS WebApp 保存到主屏，也可通过 Shortcut 直接投递到本地或云端 capture 队列。
- **服务端智能解析引擎**：结合 [Jina Reader](https://jina.ai/reader/) 增强解析与服务端定制提取逻辑，精准抽取页面内的正文、标题、平台来源。
- **全媒体资产沉淀**：自动嗅探并下载文章中的封面、配图以及视频，进行本地化持久存储（图片与视频资源均保存在服务端本地）。
- **完善的知识重组与输出**：内置对接 Notion 和 Obsidian 的同步逻辑，助力个人构建强大的数字大脑与知识库。
- **内容质量门禁 (Quality Gate)**：过滤死链、无效内容或 App 下载引导页，确保入库的内容都是干净、完整的高质量文本。

---

## 📁 核心架构及目录

项目主要分为两大部分：

```text
everything-capture/
├── backend/               # FastAPI Python 后端服务
│   ├── main.py            # 应用入口与路由注册
│   ├── routers/           # API 路由 (ingest, extract, items, connect 等)
│   ├── services/          # 核心抓取/解析服务 (extractor.py) 和媒体下载服务 (downloader.py)
│   ├── schemas.py         # Pydantic 数据规范与校验模型
│   ├── models.py          # SQLAlchemy 数据库 ORM (SQLite 默认)
│   └── static/            # 前端页面以及本地持久化的图片/视频资源存储区
├── capture_service/       # 可选的云端收录队列服务，供手机 WebApp / Shortcut 转发
└── md-docs/               # 项目交接文档、基线说明与实现备忘
```

---

## 🚀 快速启动

### 1. 启动后端服务 (Backend)

后端服务基于 Python 3 的 FastAPI 框架构建。推荐使用局部虚拟环境。

```bash
# 进入后端目录
cd backend

# 创建并激活虚拟环境 (可选)
python -m venv venv
source venv/bin/activate  # macOS / Linux
# .\venv\Scripts\activate   # Windows

# 安装依赖项 (假设有 requirements.txt, 或者直接安装主要模块)
pip install fastapi uvicorn sqlalchemy pydantic httpx requests  # 依实际情况而定

# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
> 服务启动后，可以在浏览器中访问 `http://127.0.0.1:8000/docs` 来查看自动生成的 Swagger UI 接口文档。

### 2. 打开手机端收录入口
1. 启动后端后，在 iPhone Safari 中打开同一服务地址。
2. 页面会自动切换到移动收录壳层，可直接粘贴链接或文字。
3. 如需长期使用，可通过 Safari 的“添加到主屏幕”保存为 iOS WebApp。
4. 如已配置 Shortcut 或 `capture_service/`，也可以继续走手机快捷收录链路。

---

## ⚙️ 环境变量与配置

为获得最佳的网页提取效果，您可能需要在 `backend/` 目录下创建一个 `.env` 文件。相关的变量包括：
- `JINA_API_KEY`: 如果您使用了 Jina AI 的 Reader 服务，可在此填入您的 API Key 来解锁高并发和高级反爬模式请求。

---

## 🔗 数据集成及延申

在 `backend/routers/connect.py` 中，Everything Capture 原生支持系统数据的导出与同步：
- **Notion**: 通过 Integration Token 可将您的收藏夹内容推送到指定的 Notion Database 中。
- **Obsidian**: 凭借 Obsidian Local REST API 插件，可实现将 Markdown 格式的正文与结构化信息无缝同步至本地 Vault 中。

---

## 🤝 贡献与反馈
有任何抓取异常、需要新增平台适配需求或者遇到 Bug，欢迎提交 Issue。
