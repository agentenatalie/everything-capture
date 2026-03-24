# Everything Capture

[中文文档](./README_CN.md)

A local-first content capture and personal knowledge base system. Capture URLs, articles, social media posts, videos, and text from any device — extract, store, and organize everything on your own machine.

## Why

Most "read-it-later" services store your data on their servers. Everything Capture keeps all content, media, and metadata in a local SQLite database on your machine. An optional cloud capture service lets your phone queue items, but the heavy extraction always runs locally.

## Features

- **Multi-source capture** — Desktop browser, mobile web, iOS Shortcuts, Share Sheet
- **Content extraction** — Articles, social media posts, images, videos, covers
- **Local media storage** — Downloads all media (images, videos) to your disk
- **Web UI** — Browse, search, edit, and organize your knowledge base with folders
- **Optional sync** — Push to Notion or Obsidian
- **Optional AI** — Q&A and analysis over your knowledge base (supports any OpenAI-compatible API)
- **Optional cloud inbox** — Deploy a lightweight capture service (e.g. on Vercel) so your phone can submit URLs anytime

## Architecture

```
Desktop browser / local UI
    → backend/ (FastAPI serves UI + API on port 8000)
    → ../everything-capture-data/app.db + media/

Phone / Share Sheet / Shortcut
    → optional cloud capture_service/
    → pending queue
    → local processing_worker
    → backend extraction pipeline
    → ../everything-capture-data/app.db + media/
```

**TL;DR:** Run `./run` for local-only use. Deploy `capture_service/` if you want mobile capture.

## Project Structure

```
everything-capture/
├── backend/              FastAPI API, extraction, sync, AI
│   ├── routers/          API route modules
│   ├── models.py         SQLAlchemy models
│   ├── database.py       DB setup and migrations
│   ├── security.py       Encryption for API keys
│   ├── processing_worker.py  Cloud queue consumer
│   └── main.py           App entry point
├── capture_service/      Deployable cloud capture inbox
├── frontend/             Vanilla JS web UI
│   ├── index.html
│   ├── css/
│   └── js/
├── scripts/              Deployment helpers
├── run                   Local start script
├── requirements.txt      Python dependencies
└── LICENSE
```

## Quick Start

### Prerequisites

- Python 3.11+
- (Optional) `ffmpeg` for video processing

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/everything-capture.git
cd everything-capture

# Create virtualenv
python3 -m venv backend/venv
backend/venv/bin/pip install -r requirements.txt

# Start
./run
```

This launches the local app at:
- `http://127.0.0.1:8000`

The web UI and `/api/*` endpoints are served from the same origin.

### Data Storage

All data is stored **outside** the repo in a sibling directory:

```
../everything-capture-data/
├── app.db              SQLite database
├── media/              Downloaded media files
├── .local/master.key   Encryption key for API secrets
└── exports/            Data exports
```

Override with environment variables: `DATA_DIR`, `SQLITE_PATH`, `MEDIA_DIR`, `EXPORTS_DIR`.

## Mobile / Cloud Capture

To capture from your phone, deploy the lightweight `capture_service/` (e.g. to Vercel):

```bash
# Generate a Vercel-ready deploy package
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py ./deploy_output
cd deploy_output && vercel
```

Then configure locally:

```bash
mkdir -p backend/.local
echo 'CAPTURE_SERVICE_URL="https://your-deployment.vercel.app"' > backend/.local/capture_service.env
```

The local `processing_worker` will automatically pull from the cloud queue when you run `./run`.

See [capture_service/README.md](./capture_service/README.md) for details.

## Optional Integrations

Configure these through the web UI settings page — no config files needed:

| Integration | Purpose |
|---|---|
| Notion | Sync items to a Notion database |
| Obsidian | Export items as Markdown to an Obsidian vault |
| AI (OpenAI-compatible) | Knowledge base Q&A and analysis |

API keys are encrypted at rest using Fernet encryption.

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `../everything-capture-data/` | Root data directory |
| `SQLITE_PATH` | `$DATA_DIR/app.db` | Database path |
| `MEDIA_DIR` | `$DATA_DIR/media/` | Media storage path |
| `CAPTURE_SERVICE_URL` | *(none)* | Cloud capture service URL |
| `RUN_RELOAD` | `1` | Enable uvicorn hot-reload |
| `EVERYTHING_CAPTURE_FRONTEND_ORIGIN` | *(none)* | Optional public frontend origin override for OAuth callbacks / reverse proxy setups |

## Development

```bash
# Run tests
backend/venv/bin/python -m pytest backend/tests/ -v

# Install optional dependencies
backend/venv/bin/pip install playwright tiktoken huggingface-hub
playwright install chromium
```

## License

[MIT](./LICENSE)
