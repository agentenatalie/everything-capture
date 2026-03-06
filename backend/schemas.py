from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MediaResponse(BaseModel):
    type: str          # image, video, cover
    url: str           # local URL path (e.g. /static/media/...)
    original_url: str = ""   # original remote URL (for matching content_blocks)
    display_order: int
    inline_position: float = -1.0  # 0.0-1.0 fractional position in article body; -1 = unknown

    class Config:
        from_attributes = True

class ClientInfo(BaseModel):
    platform: str

class IngestRequest(BaseModel):
    source_url: str
    final_url: str
    title: str
    canonical_text: str
    canonical_html: str
    client: ClientInfo

class IngestResponse(BaseModel):
    item_id: str
    status: str

class ItemResponse(BaseModel):
    id: str
    created_at: datetime
    source_url: str
    title: str
    canonical_text: Optional[str] = None
    canonical_html: Optional[str] = None
    content_blocks_json: Optional[str] = None  # JSON content blocks with inline images
    status: str
    platform: str
    media: list[MediaResponse] = []
    
    class Config:
        from_attributes = True

class NotionConnectRequest(BaseModel):
    token: str

class ObsidianConnectRequest(BaseModel):
    rest_url: str
    api_key: str

class ExtractRequest(BaseModel):
    url: str

class ExtractResponse(BaseModel):
    item_id: str
    title: str
    status: str
    platform: str
    text_length: int
    media_count: int = 0

class SettingsResponse(BaseModel):
    notion_api_token: Optional[str] = None
    notion_database_id: Optional[str] = None
    notion_client_id: Optional[str] = None
    notion_client_secret: Optional[str] = None
    notion_redirect_uri: Optional[str] = None
    obsidian_rest_api_url: Optional[str] = None
    obsidian_api_key: Optional[str] = None
    auto_sync_target: str = "none"

    class Config:
        from_attributes = True

class SettingsUpdateRequest(BaseModel):
    notion_api_token: Optional[str] = None
    notion_database_id: Optional[str] = None
    notion_client_id: Optional[str] = None
    notion_client_secret: Optional[str] = None
    notion_redirect_uri: Optional[str] = None
    obsidian_rest_api_url: Optional[str] = None
    obsidian_api_key: Optional[str] = None
    auto_sync_target: Optional[str] = None
