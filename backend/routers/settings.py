from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Settings
from schemas import SettingsResponse, SettingsUpdateRequest
from typing import Optional
import re

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"]
)

_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")

def _clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None

def _build_settings_response(settings_obj: Optional[Settings]) -> SettingsResponse:
    if not settings_obj:
        return SettingsResponse()

    notion_api_token = _clean_optional_string(settings_obj.notion_api_token)
    notion_database_id = _clean_optional_string(settings_obj.notion_database_id)
    notion_missing_fields = []
    if not notion_api_token:
        notion_missing_fields.append("notion_api_token")
    if not notion_database_id or not _NOTION_ID_RE.search(notion_database_id):
        notion_missing_fields.append("notion_database_id")

    obsidian_rest_api_url = _clean_optional_string(settings_obj.obsidian_rest_api_url)
    obsidian_api_key = _clean_optional_string(settings_obj.obsidian_api_key)
    obsidian_folder_path = _clean_optional_string(settings_obj.obsidian_folder_path)
    obsidian_missing_fields = []
    if not obsidian_rest_api_url:
        obsidian_missing_fields.append("obsidian_rest_api_url")
    if not obsidian_api_key:
        obsidian_missing_fields.append("obsidian_api_key")

    return SettingsResponse(
        notion_api_token=notion_api_token,
        notion_database_id=notion_database_id,
        notion_client_id=_clean_optional_string(settings_obj.notion_client_id),
        notion_client_secret=_clean_optional_string(settings_obj.notion_client_secret),
        notion_redirect_uri=_clean_optional_string(settings_obj.notion_redirect_uri),
        obsidian_rest_api_url=obsidian_rest_api_url,
        obsidian_api_key=obsidian_api_key,
        obsidian_folder_path=obsidian_folder_path,
        auto_sync_target=settings_obj.auto_sync_target or "none",
        notion_ready=len(notion_missing_fields) == 0,
        notion_missing_fields=notion_missing_fields,
        obsidian_ready=len(obsidian_missing_fields) == 0,
        obsidian_missing_fields=obsidian_missing_fields,
    )

@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    settings_obj = db.query(Settings).first()
    return _build_settings_response(settings_obj)

@router.post("", response_model=SettingsResponse)
def update_settings(request: SettingsUpdateRequest, db: Session = Depends(get_db)):
    settings_obj = db.query(Settings).first()
    
    if not settings_obj:
        settings_obj = Settings()
        db.add(settings_obj)

    if request.notion_api_token is not None:
        settings_obj.notion_api_token = _clean_optional_string(request.notion_api_token)
    if request.notion_database_id is not None:
        settings_obj.notion_database_id = _clean_optional_string(request.notion_database_id)
    if request.notion_client_id is not None:
        settings_obj.notion_client_id = _clean_optional_string(request.notion_client_id)
    if request.notion_client_secret is not None:
        settings_obj.notion_client_secret = _clean_optional_string(request.notion_client_secret)
    if request.notion_redirect_uri is not None:
        settings_obj.notion_redirect_uri = _clean_optional_string(request.notion_redirect_uri)
    if request.obsidian_rest_api_url is not None:
        settings_obj.obsidian_rest_api_url = _clean_optional_string(request.obsidian_rest_api_url)
    if request.obsidian_api_key is not None:
        settings_obj.obsidian_api_key = _clean_optional_string(request.obsidian_api_key)
    if request.obsidian_folder_path is not None:
        settings_obj.obsidian_folder_path = _clean_optional_string(request.obsidian_folder_path)
    if request.auto_sync_target is not None:
        settings_obj.auto_sync_target = request.auto_sync_target

    db.commit()
    db.refresh(settings_obj)
    
    return _build_settings_response(settings_obj)
