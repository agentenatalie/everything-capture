from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app_settings import clean_optional_string
from database import get_db
from models import Settings
from security import encrypt_secret, has_secret_value
from services.components import ComponentServiceError, get_install_task, install_component, list_components
from services.ai_defaults import (
    AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS,
    AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
    AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
    AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
    AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
    AI_AGENT_DEFAULT_CAN_WEB_SEARCH,
    AI_AGENT_DEFAULT_CAN_RUN_COMPUTER_COMMANDS,
    AI_DEFAULT_BASE_URL,
    AI_DEFAULT_MODEL,
    AI_MODEL_OPTIONS,
    coerce_bool,
)
from services.knowledge_base import detect_knowledge_base_path
from schemas import (
    ComponentInstallTaskResponse,
    ComponentsCatalogResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from tenant import get_current_user_id
from typing import Optional
import re

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"]
)

_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")


def _has_configured_value(value: Optional[str]) -> bool:
    return has_secret_value(value)


def _settings_bool(value: Optional[bool], default: bool) -> bool:
    return coerce_bool(value, default)


def _build_settings_response(settings_obj: Optional[Settings], db: Session) -> SettingsResponse:
    ai_knowledge_base_path = detect_knowledge_base_path()
    default_ai_base_url = clean_optional_string(AI_DEFAULT_BASE_URL)
    if not settings_obj:
        return SettingsResponse(
            ai_base_url=default_ai_base_url,
            ai_model=AI_DEFAULT_MODEL,
            ai_base_url_suggestion=default_ai_base_url,
            ai_ready=False,
            ai_missing_fields=["ai_api_key", "ai_base_url"],
            ai_model_options=AI_MODEL_OPTIONS,
            ai_agent_can_manage_folders=AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
            ai_agent_can_parse_content=AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
            ai_agent_can_sync_obsidian=AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
            ai_agent_can_sync_notion=AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
            ai_agent_can_execute_commands=AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS,
            ai_agent_can_web_search=AI_AGENT_DEFAULT_CAN_WEB_SEARCH,
            ai_agent_can_run_computer_commands=AI_AGENT_DEFAULT_CAN_RUN_COMPUTER_COMMANDS,
            ai_auto_tag_enabled=False,
            ai_knowledge_base_path=ai_knowledge_base_path,
            ai_knowledge_base_available=bool(ai_knowledge_base_path),
        )

    notion_api_token_saved = _has_configured_value(settings_obj.notion_api_token)
    notion_database_id = clean_optional_string(settings_obj.notion_database_id)
    notion_missing_fields = []
    if not notion_api_token_saved:
        notion_missing_fields.append("notion_api_token")
    if not notion_database_id or not _NOTION_ID_RE.search(notion_database_id):
        notion_missing_fields.append("notion_database_id")

    obsidian_rest_api_url = clean_optional_string(settings_obj.obsidian_rest_api_url)
    obsidian_api_key_saved = _has_configured_value(settings_obj.obsidian_api_key)
    obsidian_folder_path = clean_optional_string(settings_obj.obsidian_folder_path)
    obsidian_missing_fields = []
    if not obsidian_rest_api_url:
        obsidian_missing_fields.append("obsidian_rest_api_url")
    if not obsidian_api_key_saved:
        obsidian_missing_fields.append("obsidian_api_key")

    ai_base_url = clean_optional_string(settings_obj.ai_base_url) or default_ai_base_url
    ai_model = clean_optional_string(settings_obj.ai_model) or AI_DEFAULT_MODEL
    ai_api_key_saved = _has_configured_value(settings_obj.ai_api_key)
    ai_missing_fields = []
    if not ai_api_key_saved:
        ai_missing_fields.append("ai_api_key")
    if not ai_base_url:
        ai_missing_fields.append("ai_base_url")

    return SettingsResponse(
        notion_api_token=None,
        notion_api_token_saved=notion_api_token_saved,
        notion_database_id=notion_database_id,
        notion_client_id=clean_optional_string(settings_obj.notion_client_id),
        notion_client_secret=None,
        notion_client_secret_saved=_has_configured_value(settings_obj.notion_client_secret),
        notion_redirect_uri=clean_optional_string(settings_obj.notion_redirect_uri),
        obsidian_rest_api_url=obsidian_rest_api_url,
        obsidian_api_key=None,
        obsidian_api_key_saved=obsidian_api_key_saved,
        obsidian_folder_path=obsidian_folder_path,
        ai_api_key=None,
        ai_api_key_saved=ai_api_key_saved,
        ai_base_url=ai_base_url,
        ai_model=ai_model,
        ai_base_url_suggestion=default_ai_base_url,
        ai_model_options=AI_MODEL_OPTIONS,
        ai_agent_can_manage_folders=_settings_bool(
            settings_obj.ai_agent_can_manage_folders,
            AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
        ),
        ai_agent_can_parse_content=_settings_bool(
            settings_obj.ai_agent_can_parse_content,
            AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
        ),
        ai_agent_can_sync_obsidian=_settings_bool(
            settings_obj.ai_agent_can_sync_obsidian,
            AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
        ),
        ai_agent_can_sync_notion=_settings_bool(
            settings_obj.ai_agent_can_sync_notion,
            AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
        ),
        ai_agent_can_execute_commands=_settings_bool(
            settings_obj.ai_agent_can_execute_commands,
            AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS,
        ),
        ai_agent_can_web_search=_settings_bool(
            settings_obj.ai_agent_can_web_search,
            AI_AGENT_DEFAULT_CAN_WEB_SEARCH,
        ),
        ai_agent_can_run_computer_commands=_settings_bool(
            settings_obj.ai_agent_can_run_computer_commands,
            AI_AGENT_DEFAULT_CAN_RUN_COMPUTER_COMMANDS,
        ),
        auto_sync_target=settings_obj.auto_sync_target or "none",
        ai_auto_tag_enabled=_settings_bool(
            getattr(settings_obj, "ai_auto_tag_enabled", False),
            False,
        ),
        notion_ready=len(notion_missing_fields) == 0,
        notion_missing_fields=notion_missing_fields,
        obsidian_ready=len(obsidian_missing_fields) == 0,
        obsidian_missing_fields=obsidian_missing_fields,
        ai_ready=len(ai_missing_fields) == 0,
        ai_missing_fields=ai_missing_fields,
        ai_knowledge_base_path=ai_knowledge_base_path,
        ai_knowledge_base_available=bool(ai_knowledge_base_path),
    )

@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    settings_obj = db.query(Settings).filter(Settings.user_id == user_id).first()
    return _build_settings_response(settings_obj, db)


@router.get("/components", response_model=ComponentsCatalogResponse)
def get_components_catalog():
    try:
        return list_components()
    except ComponentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/components/{component_id}/install", response_model=ComponentInstallTaskResponse, status_code=202)
def install_settings_component(component_id: str):
    try:
        return install_component(component_id)
    except ComponentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/components/tasks/{task_id}", response_model=ComponentInstallTaskResponse)
def get_component_install_task(task_id: str):
    try:
        return get_install_task(task_id)
    except ComponentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("", response_model=SettingsResponse)
def update_settings(request: SettingsUpdateRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    settings_obj = db.query(Settings).filter(Settings.user_id == user_id).first()

    if not settings_obj:
        settings_obj = Settings(user_id=user_id)
        db.add(settings_obj)

    if request.notion_api_token is not None:
        settings_obj.notion_api_token = encrypt_secret(request.notion_api_token)
    if request.notion_database_id is not None:
        settings_obj.notion_database_id = clean_optional_string(request.notion_database_id)
    if request.notion_client_id is not None:
        settings_obj.notion_client_id = clean_optional_string(request.notion_client_id)
    if request.notion_client_secret is not None:
        settings_obj.notion_client_secret = encrypt_secret(request.notion_client_secret)
    if request.notion_redirect_uri is not None:
        settings_obj.notion_redirect_uri = clean_optional_string(request.notion_redirect_uri)
    if request.obsidian_rest_api_url is not None:
        settings_obj.obsidian_rest_api_url = clean_optional_string(request.obsidian_rest_api_url)
    if request.obsidian_api_key is not None:
        settings_obj.obsidian_api_key = encrypt_secret(request.obsidian_api_key)
    if request.obsidian_folder_path is not None:
        settings_obj.obsidian_folder_path = clean_optional_string(request.obsidian_folder_path)
    if request.ai_api_key is not None:
        settings_obj.ai_api_key = encrypt_secret(request.ai_api_key)
    if request.ai_base_url is not None:
        settings_obj.ai_base_url = clean_optional_string(request.ai_base_url)
    if request.ai_model is not None:
        settings_obj.ai_model = clean_optional_string(request.ai_model)
    if request.ai_agent_can_manage_folders is not None:
        settings_obj.ai_agent_can_manage_folders = request.ai_agent_can_manage_folders
    if request.ai_agent_can_parse_content is not None:
        settings_obj.ai_agent_can_parse_content = request.ai_agent_can_parse_content
    if request.ai_agent_can_sync_obsidian is not None:
        settings_obj.ai_agent_can_sync_obsidian = request.ai_agent_can_sync_obsidian
    if request.ai_agent_can_sync_notion is not None:
        settings_obj.ai_agent_can_sync_notion = request.ai_agent_can_sync_notion
    if request.ai_agent_can_execute_commands is not None:
        settings_obj.ai_agent_can_execute_commands = request.ai_agent_can_execute_commands
    if request.ai_agent_can_web_search is not None:
        settings_obj.ai_agent_can_web_search = request.ai_agent_can_web_search
    if request.ai_agent_can_run_computer_commands is not None:
        settings_obj.ai_agent_can_run_computer_commands = request.ai_agent_can_run_computer_commands
    if request.auto_sync_target is not None:
        settings_obj.auto_sync_target = request.auto_sync_target
    if request.ai_auto_tag_enabled is not None:
        settings_obj.ai_auto_tag_enabled = request.ai_auto_tag_enabled

    db.commit()
    db.refresh(settings_obj)

    return _build_settings_response(settings_obj, db)
