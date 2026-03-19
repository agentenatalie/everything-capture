# Everything Capture

本地优先的内容采集与个人知识库系统。从任何设备抓取网址、文章、社交媒体帖子、视频和文本 — 提取、存储、整理，全部在你自己的机器上完成。

## 为什么做这个

大多数「稍后阅读」服务把你的数据存在他们的服务器上。Everything Capture 把所有内容、媒体和元数据存在你本机的 SQLite 数据库里。可选的云端采集服务允许手机提交链接，但真正的内容提取始终在本地运行。

## 功能

- **多端采集** — 桌面浏览器、手机网页、iOS 快捷指令、分享菜单
- **内容提取** — 文章正文、社交媒体帖子、图片、视频、封面
- **本地媒体存储** — 所有媒体（图片、视频）下载到本地磁盘
- **Web UI** — 浏览、搜索、编辑内容，用文件夹整理知识库
- **可选同步** — 推送到 Notion 或 Obsidian
- **可选 AI** — 基于知识库的问答与分析（支持任意 OpenAI 兼容 API）
- **可选云端收件箱** — 部署一个轻量采集服务（如 Vercel），手机随时投递链接

## 架构

```
桌面浏览器 / 本地 UI
    → frontend/ (静态文件，端口 8010)
    → backend/ (FastAPI，端口 8000)
    → ../everything-capture-data/app.db + media/

手机 / 分享菜单 / 快捷指令
    → 可选云端 capture_service/
    → 待处理队列
    → 本地 processing_worker
    → backend 提取流水线
    → ../everything-capture-data/app.db + media/
```

**一句话版本：** 只在本地用就跑 `backend/`；想让手机也能采集就再部署 `capture_service/`。

## 项目结构

```
everything-capture/
├── backend/              FastAPI API、内容提取、同步、AI
│   ├── routers/          API 路由模块
│   ├── models.py         SQLAlchemy 数据模型
│   ├── database.py       数据库初始化与迁移
│   ├── security.py       API 密钥加密
│   ├── processing_worker.py  云端队列消费者
│   └── main.py           应用入口
├── capture_service/      可独立部署的云端采集收件箱
├── frontend/             原生 JS Web UI
│   ├── index.html
│   ├── css/
│   └── js/
├── scripts/              部署辅助脚本
├── run                   本地启动脚本
├── requirements.txt      Python 依赖
└── LICENSE
```

## 快速开始

### 前提条件

- Python 3.11+
- （可选）`ffmpeg`，用于视频处理

### 安装与启动

```bash
git clone https://github.com/YOUR_USERNAME/everything-capture.git
cd everything-capture

# 创建虚拟环境
python3 -m venv backend/venv
backend/venv/bin/pip install -r requirements.txt

# 启动
./run
```

启动后：
- 后端 API：`http://127.0.0.1:8000`
- 前端 UI：`http://127.0.0.1:8010`

### 数据存储

所有数据存储在仓库**外部**的同级目录中：

```
../everything-capture-data/
├── app.db              SQLite 数据库
├── media/              下载的媒体文件
├── .local/master.key   API 密钥加密用的主密钥
└── exports/            数据导出
```

可通过环境变量覆盖：`DATA_DIR`、`SQLITE_PATH`、`MEDIA_DIR`、`EXPORTS_DIR`。

## 手机端 / 云端采集

从手机采集内容，需要部署轻量的 `capture_service/`（例如部署到 Vercel）：

```bash
# 生成 Vercel 部署包
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py ./deploy_output
cd deploy_output && vercel
```

然后在本地配置：

```bash
mkdir -p backend/.local
echo 'CAPTURE_SERVICE_URL="https://your-deployment.vercel.app"' > backend/.local/capture_service.env
```

运行 `./run` 时，本地 `processing_worker` 会自动从云端队列拉取任务。

详见 [capture_service/README.md](./capture_service/README.md)。

## 可选集成

在 Web UI 的设置页面中配置，无需手动编辑配置文件：

| 集成 | 用途 |
|---|---|
| Notion | 同步条目到 Notion 数据库 |
| Obsidian | 导出条目为 Markdown 到 Obsidian 仓库 |
| AI（OpenAI 兼容） | 知识库问答与分析 |

API 密钥使用 Fernet 加密存储。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DATA_DIR` | `../everything-capture-data/` | 数据根目录 |
| `SQLITE_PATH` | `$DATA_DIR/app.db` | 数据库路径 |
| `MEDIA_DIR` | `$DATA_DIR/media/` | 媒体存储路径 |
| `FRONTEND_PORT` | `8010` | 前端服务端口 |
| `CAPTURE_SERVICE_URL` | *（无）* | 云端采集服务地址 |
| `RUN_RELOAD` | `1` | 启用 uvicorn 热重载 |

## 开发

```bash
# 运行测试
backend/venv/bin/python -m pytest backend/tests/ -v

# 安装可选依赖
backend/venv/bin/pip install playwright tiktoken huggingface-hub
playwright install chromium
```

## 许可证

[MIT](./LICENSE)
