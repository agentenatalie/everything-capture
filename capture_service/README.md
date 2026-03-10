# Capture Service

完整部署说明见 [DEPLOYMENT.md](/Users/hbz/everything-grabber/DEPLOYMENT.md)。

Deploy this service to the cloud and keep the existing `backend/` app local. The deployed root path serves the phone capture webapp UI, and `/api/*` serves the capture endpoints.

## Responsibilities

- Accept capture requests from phone shortcuts, share sheets, web forms, extensions, or API clients
- Store them as `pending`
- Expose a small worker-facing queue API

It does not do scraping, media downloading, AI analysis, or local file sync.

## Endpoints

- `POST /api/capture`
- `GET /api/folders`
- `POST /api/folders`
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

## Phone Webapp

Open `/` on your phone to use the deployed capture webapp. It supports:

- paste text or URLs
- submit to `pending`
- choose cloud folders
- create new cloud folders

## Shortcut Response

`POST /api/capture` returns an explicit acceptance contract for shortcuts:

```json
{
  "success": true,
  "captured": true,
  "item_id": "uuid",
  "status": "pending"
}
```

The nested `item` payload is still returned for richer clients.

## Vercel Preview Packaging

To build a deploy-only package for the capture layer:

```bash
cd /Users/hbz/everything-grabber
backend/venv/bin/python scripts/prepare_capture_vercel_deploy.py /tmp/everything-grabber-capture-vercel
```

Then deploy that generated folder instead of the whole repo.

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
