# Capture Service

Deploy this service to the cloud and keep the existing `backend/` app local.

## Responsibilities

- Accept capture requests from phone shortcuts, share sheets, web forms, extensions, or API clients
- Store them as `pending`
- Expose a small worker-facing queue API

It does not do scraping, media downloading, AI analysis, or local file sync.

## Endpoints

- `POST /api/capture`
- `GET /api/items?status=pending&limit=20`
- `POST /api/items/{id}/claim`
- `POST /api/items/{id}/complete`
- `POST /api/items/{id}/fail`

## Environment

- `CAPTURE_SERVICE_DB_PATH` optional SQLite path
- `CAPTURE_SERVICE_TOKEN` optional bearer token for all queue endpoints

## Run

```bash
cd /Users/hbz/everything-grabber
backend/venv/bin/uvicorn capture_service.api:app --host 0.0.0.0 --port 9000
```

## Local Worker

Point the local app at the deployed capture service:

```bash
export CAPTURE_SERVICE_URL=http://127.0.0.1:9000
export CAPTURE_SERVICE_TOKEN=your-token
```

Then run the local processing worker:

```bash
cd /Users/hbz/everything-grabber/backend
../backend/venv/bin/python processing_worker.py --once
```
