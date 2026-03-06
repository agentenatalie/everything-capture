from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Settings
from schemas import SettingsResponse, SettingsUpdateRequest
from typing import Optional

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"]
)

@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    settings_obj = db.query(Settings).first()
    if not settings_obj:
        # Default settings if none exist
        return SettingsResponse()
    return settings_obj

@router.post("", response_model=SettingsResponse)
def update_settings(request: SettingsUpdateRequest, db: Session = Depends(get_db)):
    settings_obj = db.query(Settings).first()
    
    if not settings_obj:
        settings_obj = Settings()
        db.add(settings_obj)

    if request.notion_api_token is not None:
        settings_obj.notion_api_token = request.notion_api_token
    if request.notion_database_id is not None:
        settings_obj.notion_database_id = request.notion_database_id
    if request.notion_client_id is not None:
        settings_obj.notion_client_id = request.notion_client_id
    if request.notion_client_secret is not None:
        settings_obj.notion_client_secret = request.notion_client_secret
    if request.notion_redirect_uri is not None:
        settings_obj.notion_redirect_uri = request.notion_redirect_uri
    if request.obsidian_rest_api_url is not None:
        settings_obj.obsidian_rest_api_url = request.obsidian_rest_api_url
    if request.obsidian_api_key is not None:
        settings_obj.obsidian_api_key = request.obsidian_api_key
    if request.auto_sync_target is not None:
        settings_obj.auto_sync_target = request.auto_sync_target

    db.commit()
    db.refresh(settings_obj)
    
    return settings_obj
