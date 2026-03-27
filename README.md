<div align="center">

# Everything Capture

**Local-first content capture & personal knowledge base**

Capture URLs, articles, social media, videos, and text from any device — extract, store, and organize everything on your own machine.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_+_FTS5-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](./LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS_|_Linux-lightgrey?style=flat-square&logo=apple&logoColor=white)](https://github.com/agentenatalie/everything-capture)
[![GitHub stars](https://img.shields.io/github/stars/agentenatalie/everything-capture?style=flat-square&logo=github)](https://github.com/agentenatalie/everything-capture/stargazers)
[![GitHub last commit](https://img.shields.io/github/last-commit/agentenatalie/everything-capture?style=flat-square)](https://github.com/agentenatalie/everything-capture/commits/main)

[中文文档](./README_CN.md) · [Landing Page](https://agentenatalie.github.io/everything-capture/)

</div>

---

## Why

Most "read-it-later" services store your data on their servers. Everything Capture keeps **all content, media, and metadata in a local SQLite database** on your machine. An optional cloud capture service lets your phone queue items, but the heavy extraction always runs locally.

## Features

| | Feature | Description |
|---|---|---|
| 📥 | **Multi-source capture** | Web UI (paste URL or ⌘K command palette), server-side extraction API |
| 📄 | **Smart extraction** | Articles, social posts (Xiaohongshu, Douyin, Twitter/X, WeChat), images, videos |
| 💾 | **Local media storage** | All media (images, videos, covers) downloaded to your disk |
| 🔍 | **Full-text search** | SQLite FTS5 trigram index for fast Chinese + English search |
| 🗂️ | **Folder organization** | Drag-and-drop folders, multi-folder assignment, batch operations |
| 🤖 | **AI assistant** | Chat & agent mode with knowledge base Q&A, content analysis, auto-organization |
| 🎙️ | **Local transcription** | On-device speech-to-text via mlx-whisper (Apple Silicon) |
| 👁️ | **OCR** | Image text extraction + QR code detection via macOS Vision framework |
| 📤 | **Sync to Notion/Obsidian** | Push items to your existing knowledge management tools |
| 📱 | **Cloud inbox** | Optional — deploy a lightweight capture service for mobile/Shortcuts submissions (self-hosted) |
| 🖥️ | **Desktop app** | *Coming soon* — macOS .app bundle with PyInstaller, code-signed and notarized |

## Quick Start

### One-line install (recommended)

```bash
curl -O https://raw.githubusercontent.com/agentenatalie/everything-capture/main/setup.sh && bash setup.sh
```

This automatically installs Python 3, ffmpeg, downloads the code, sets up dependencies, and starts the app.

### Manual install

```bash
git clone https://github.com/agentenatalie/everything-capture.git
cd everything-capture
python3 -m venv backend/venv
backend/venv/bin/pip install -r requirements.txt
./run
```

Open **http://localhost:8000** in your browser.

### System requirements

| Dependency | Purpose | Install |
|---|---|---|
| Python 3.11+ | Backend runtime | `brew install python3` / `apt install python3` |
| ffmpeg | Video transcription & subtitle extraction | `brew install ffmpeg` / `apt install ffmpeg` |
| Swift (macOS built-in) | Image OCR + QR code detection | `xcode-select --install` |

> **Note:** `mlx` and `mlx-whisper` (for local speech-to-text) are only installed on macOS Apple Silicon. Other platforms skip them automatically.

## Architecture

```
Desktop browser / Web UI
    → backend/ (FastAPI on :8000, serves UI + API)
    → ../everything-capture-data/app.db + media/

Phone / Share Sheet / Shortcuts
    → optional cloud capture_service/
    → pending queue
    → local processing_worker polls & extracts
    → ../everything-capture-data/app.db + media/
```

## Project Structure

```
everything-capture/
├── backend/                FastAPI API, extraction engine, sync, AI
│   ├── routers/            API route modules (items, ingest, ai, folders, settings, connect)
│   ├── services/           Business logic (extractor, downloader, ai_client, knowledge_base)
│   ├── models.py           SQLAlchemy ORM models
│   ├── database.py         DB setup, migrations, FTS5 indexes
│   └── main.py             App entry point
├── frontend/               Vanilla HTML/CSS/JS SPA (no build tools)
│   ├── index.html          Single-page app entry
│   ├── css/index.css       All styles
│   └── js/                 app-core, app-items, app-ai, app-folders, etc.
├── capture_service/        Deployable cloud capture inbox (optional)
├── desktop/                macOS .app packaging (PyInstaller + DMG)
│   ├── launcher/           App launcher with backend lifecycle management
│   ├── spec/               Build specs, manifests, entitlements
│   └── scripts/            Build, sign, notarize, release scripts
├── docs/                   Landing page (static site)
├── logo/                   SVG logo assets
├── setup.sh                One-line installer script
├── run                     Dev start script (backend + frontend + worker)
└── requirements.txt        Python dependencies
```

## Data Storage

All data lives **outside** the repo in a sibling directory:

```
../everything-capture-data/
├── app.db              SQLite database (WAL mode)
├── media/              Downloaded images, videos, covers
├── .local/master.key   Fernet encryption key for API secrets
├── exports/            AI sandbox exports
└── components/         Installed optional components
```

Override with env vars: `DATA_DIR`, `SQLITE_PATH`, `MEDIA_DIR`, `EXPORTS_DIR`.

## Mobile / Cloud Capture (Optional, Self-hosted)

To capture from your phone or iOS Shortcuts, deploy the lightweight `capture_service/` yourself:

```bash
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py ./deploy_output
cd deploy_output && vercel
```

Then configure locally:

```bash
mkdir -p backend/.local
echo 'CAPTURE_SERVICE_URL="https://your-deployment.vercel.app"' > backend/.local/capture_service.env
```

The local `processing_worker` automatically pulls from the cloud queue when you run `./run`.

See [capture_service/README.md](./capture_service/README.md) for details.

## Integrations

Configure through the web UI settings — no config files needed:

| Integration | Purpose |
|---|---|
| **Notion** | Sync items to a Notion database (OAuth) |
| **Obsidian** | Export as Markdown via Obsidian REST API plugin |
| **AI** (OpenAI-compatible) | Knowledge base Q&A, content analysis, auto-organization |

All API keys are encrypted at rest with Fernet.

## AI Features

The built-in AI assistant supports two modes:

- **Chat mode** — Conversational Q&A with knowledge base context, content analysis
- **Agent mode** — Tool-calling with search, folder management, sync, export, sandbox execution, and system commands

The **Reader sidebar AI** uses agent mode automatically — it decides whether to use tools based on your request, no manual mode switching needed.

**System command execution** — The agent can run commands on your computer (git clone, brew install, etc.) with a per-command approval popup. You see the exact command and must click "Allow" before it runs. The agent interprets each command's output before deciding the next step.

**Persistent AI memory** — The agent learns and remembers your preferences across conversations. It observes how you organize folders, what topics you care about, and how you like responses — then applies that knowledge automatically. When organizing content, it first studies your existing folder structure and classification patterns before making any assignments. Corrections are saved immediately so the same mistake doesn't happen twice.

Supports reasoning/thinking models with `<think>` tag streaming. Works with any OpenAI-compatible API (OpenAI, Claude, local models, etc.).

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `../everything-capture-data/` | Root data directory |
| `SQLITE_PATH` | `$DATA_DIR/app.db` | Database path |
| `MEDIA_DIR` | `$DATA_DIR/media/` | Media storage path |
| `CAPTURE_SERVICE_URL` | *(none)* | Cloud capture service URL |
| `CAPTURE_SERVICE_TOKEN` | *(none)* | Cloud service auth token |
| `RUN_RELOAD` | `1` | Enable uvicorn hot-reload |
| `USE_FTS5_SEARCH` | `true` | Enable FTS5 full-text search |
| `EVERYTHING_CAPTURE_FRONTEND_ORIGIN` | *(none)* | Frontend origin override for OAuth / reverse proxy |

## Development

```bash
# Run backend tests
cd backend && source venv/bin/activate
PYTHONPATH="$(pwd)/..:$(pwd)" python -m pytest tests/ -v

# Run capture service tests
PYTHONPATH="$(pwd)/.." python -m pytest ../capture_service/tests/ -v
```

## License

[MIT](./LICENSE)
