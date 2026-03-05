from fastapi import APIRouter

router = APIRouter(
    prefix="/api/connect",
    tags=["connect"]
)

@router.post("/notion")
def connect_notion():
    # Placeholder for Phase 2
    return {"status": "ok", "message": "Notion connected (placeholder)"}

@router.post("/obsidian")
def connect_obsidian():
    # Placeholder for Phase 2
    return {"status": "ok", "message": "Obsidian connected (placeholder)"}
