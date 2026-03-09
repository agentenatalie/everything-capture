from pydantic import BaseModel, Field
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
    notion_page_id: Optional[str] = None
    obsidian_path: Optional[str] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
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
    google_oauth_client_id: Optional[str] = None
    google_oauth_client_secret: Optional[str] = None
    google_oauth_client_secret_saved: bool = False
    google_oauth_redirect_uri: Optional[str] = None
    google_oauth_ready: bool = False
    google_oauth_missing_fields: list[str] = Field(default_factory=list)
    google_oauth_managed_by: str = "settings"
    notion_api_token: Optional[str] = None
    notion_api_token_saved: bool = False
    notion_database_id: Optional[str] = None
    notion_client_id: Optional[str] = None
    notion_client_secret: Optional[str] = None
    notion_client_secret_saved: bool = False
    notion_redirect_uri: Optional[str] = None
    obsidian_rest_api_url: Optional[str] = None
    obsidian_api_key: Optional[str] = None
    obsidian_api_key_saved: bool = False
    obsidian_folder_path: Optional[str] = None
    auto_sync_target: str = "none"
    notion_ready: bool = False
    notion_missing_fields: list[str] = Field(default_factory=list)
    obsidian_ready: bool = False
    obsidian_missing_fields: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True

class SettingsUpdateRequest(BaseModel):
    google_oauth_client_id: Optional[str] = None
    google_oauth_client_secret: Optional[str] = None
    google_oauth_redirect_uri: Optional[str] = None
    notion_api_token: Optional[str] = None
    notion_database_id: Optional[str] = None
    notion_client_id: Optional[str] = None
    notion_client_secret: Optional[str] = None
    notion_redirect_uri: Optional[str] = None
    obsidian_rest_api_url: Optional[str] = None
    obsidian_api_key: Optional[str] = None
    obsidian_folder_path: Optional[str] = None
    auto_sync_target: Optional[str] = None


class FolderResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    item_count: int = 0

    class Config:
        from_attributes = True


class FolderListResponse(BaseModel):
    folders: list[FolderResponse] = Field(default_factory=list)
    total_count: int = 0
    unfiled_count: int = 0


class FolderCreateRequest(BaseModel):
    name: str


class FolderUpdateRequest(BaseModel):
    name: str


class ItemFolderUpdateRequest(BaseModel):
    folder_id: Optional[str] = None


class BulkFolderUpdateRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    folder_id: Optional[str] = None


class BulkFolderUpdateResponse(BaseModel):
    updated_count: int


class AuthUserResponse(BaseModel):
    id: str
    email: Optional[str] = None
    phone_e164: Optional[str] = None
    display_name: str
    avatar_url: Optional[str] = None


class AuthProvidersResponse(BaseModel):
    google_enabled: bool = False
    email_enabled: bool = False
    phone_enabled: bool = False
    email_delivery_mode: str = "disabled"
    phone_delivery_mode: str = "disabled"


class AuthSessionResponse(BaseModel):
    authenticated: bool = False
    user: Optional[AuthUserResponse] = None
    providers: AuthProvidersResponse = Field(default_factory=AuthProvidersResponse)


class EmailCodeRequest(BaseModel):
    email: str


class EmailCodeVerifyRequest(BaseModel):
    email: str
    code: str
    display_name: Optional[str] = None


class PhoneCodeRequest(BaseModel):
    phone: str


class PhoneCodeVerifyRequest(BaseModel):
    phone: str
    code: str
    display_name: Optional[str] = None


class CodeDeliveryResponse(BaseModel):
    status: str
    delivery_mode: str
    target_masked: str
    dev_code: Optional[str] = None
