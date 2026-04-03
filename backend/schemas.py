from pydantic import BaseModel, Field
from typing import Literal, Optional
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
    obsidian_sync_state: str = "idle"
    extracted_text: Optional[str] = None
    ocr_text: Optional[str] = None
    frame_texts: list[dict] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    qr_links: list[str] = Field(default_factory=list)
    parse_status: str = "idle"
    parse_error: Optional[str] = None
    parsed_at: Optional[datetime] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    folder_ids: list[str] = Field(default_factory=list)
    folder_names: list[str] = Field(default_factory=list)
    last_viewed_at: Optional[datetime] = None
    folder_count: int = 0
    tag_ids: list[str] = Field(default_factory=list)
    tag_names: list[str] = Field(default_factory=list)
    media: list[MediaResponse] = []

    class Config:
        from_attributes = True

class GraphNode(BaseModel):
    id: str
    title: str
    platform: str
    folder_ids: list[str] = Field(default_factory=list)
    folder_names: list[str] = Field(default_factory=list)
    media_url: Optional[str] = None
    created_at: datetime

class GraphEdge(BaseModel):
    source: str
    target: str
    score: float = 0.0

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    folders: list[dict]


class NotionConnectRequest(BaseModel):
    token: str

class ObsidianConnectRequest(BaseModel):
    rest_url: str
    api_key: str

class ExtractRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    source_url: Optional[str] = None
    title: Optional[str] = None


class PhoneExtractRequest(ExtractRequest):
    folder_id: Optional[str] = None
    folder_ids: list[str] = Field(default_factory=list)

class ExtractResponse(BaseModel):
    item_id: str
    title: str
    status: str
    platform: str
    text_length: int
    media_count: int = 0

class SettingsResponse(BaseModel):
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
    ai_api_key: Optional[str] = None
    ai_api_key_saved: bool = False
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None
    ai_base_url_suggestion: Optional[str] = None
    ai_model_options: list[str] = Field(default_factory=list)
    ai_agent_can_manage_folders: bool = True
    ai_agent_can_parse_content: bool = True
    ai_agent_can_sync_obsidian: bool = False
    ai_agent_can_sync_notion: bool = False
    ai_agent_can_execute_commands: bool = False
    ai_agent_can_web_search: bool = True
    ai_agent_can_run_computer_commands: bool = False
    auto_sync_target: str = "none"
    ai_auto_tag_enabled: bool = False
    notion_ready: bool = False
    notion_missing_fields: list[str] = Field(default_factory=list)
    obsidian_ready: bool = False
    obsidian_missing_fields: list[str] = Field(default_factory=list)
    ai_ready: bool = False
    ai_missing_fields: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ComponentInstallTaskResponse(BaseModel):
    id: str
    component_id: str
    status: str
    stage: str
    message: str
    error: Optional[str] = None
    progress: float = 0.0
    latest_version: Optional[str] = None
    installed_version: Optional[str] = None
    requires_restart: bool = False
    created_at: str
    updated_at: str


class ComponentStatusResponse(BaseModel):
    id: str
    title: str
    description: str = ""
    available: bool = False
    bundled: bool = False
    status: str
    latest_version: Optional[str] = None
    installed_version: Optional[str] = None
    download_url: Optional[str] = None
    download_size_bytes: Optional[int] = None
    requires_restart: bool = False
    unavailable_reason: Optional[str] = None
    task: Optional[ComponentInstallTaskResponse] = None


class ComponentsCatalogResponse(BaseModel):
    platform: str
    manifest_source: str
    manifest_configured: bool = False
    components: list[ComponentStatusResponse] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    notion_api_token: Optional[str] = None
    notion_database_id: Optional[str] = None
    notion_client_id: Optional[str] = None
    notion_client_secret: Optional[str] = None
    notion_redirect_uri: Optional[str] = None
    obsidian_rest_api_url: Optional[str] = None
    obsidian_api_key: Optional[str] = None
    obsidian_folder_path: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None
    ai_agent_can_manage_folders: Optional[bool] = None
    ai_agent_can_parse_content: Optional[bool] = None
    ai_agent_can_sync_obsidian: Optional[bool] = None
    ai_agent_can_sync_notion: Optional[bool] = None
    ai_agent_can_execute_commands: Optional[bool] = None
    ai_agent_can_web_search: Optional[bool] = None
    ai_agent_can_run_computer_commands: Optional[bool] = None
    auto_sync_target: Optional[str] = None
    ai_auto_tag_enabled: Optional[bool] = None


class AiCitationResponse(BaseModel):
    reference_index: Optional[int] = None
    note_id: str
    library_item_id: Optional[str] = None
    title: str
    summary: Optional[str] = None
    folder: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    relative_path: str
    created_at: Optional[datetime] = None
    score: float = 0.0
    excerpt: Optional[str] = None


class AiAskRequest(BaseModel):
    question: str
    top_k: int = 6


class AiAskResponse(BaseModel):
    question: str
    answer: str
    citations: list[AiCitationResponse] = Field(default_factory=list)
    note_count: int = 0
    insufficient_context: bool = False


class AiItemAnalysisResponse(BaseModel):
    item_id: str
    note_title: str
    summary_used: Optional[str] = None
    one_liner: str
    core_points: list[str] = Field(default_factory=list)
    why_saved: str
    themes: list[str] = Field(default_factory=list)
    thinking_questions: list[str] = Field(default_factory=list)
    citations: list[AiCitationResponse] = Field(default_factory=list)


class AiRelatedNotesResponse(BaseModel):
    item_id: str
    related: list[AiCitationResponse] = Field(default_factory=list)
    note_count: int = 0


class AiConversationMessage(BaseModel):
    role: str
    content: str


class AiAssistantRequest(BaseModel):
    mode: str = "chat"
    messages: list[AiConversationMessage] = Field(default_factory=list)
    top_k: int = 6
    current_item_id: Optional[str] = None


class AiToolEventResponse(BaseModel):
    name: str
    status: str = "completed"
    summary: str
    detail: Optional[str] = None
    download_url: Optional[str] = None


class AiPendingApprovalResponse(BaseModel):
    approval_id: str
    command: str
    description: str
    working_directory: Optional[str] = None


class AiAssistantResponse(BaseModel):
    mode: str
    message: str
    citations: list[AiCitationResponse] = Field(default_factory=list)
    tool_events: list[AiToolEventResponse] = Field(default_factory=list)
    note_count: int = 0
    insufficient_context: bool = False
    agent_permissions: list[str] = Field(default_factory=list)
    updated_items: list[ItemResponse] = Field(default_factory=list)
    pending_approval: Optional[AiPendingApprovalResponse] = None


class AiApprovalRequest(BaseModel):
    approval_id: str
    approved: bool


class AiApprovalResponse(BaseModel):
    status: str
    output: str = ""
    exit_code: int = 0


class AiConversationStoredMessage(BaseModel):
    role: str
    content: str
    mode: str = "chat"
    citations: list[AiCitationResponse] = Field(default_factory=list)
    tool_events: list[AiToolEventResponse] = Field(default_factory=list)
    note_count: int = 0
    insufficient_context: bool = False
    is_error: bool = False
    created_at: Optional[datetime] = None


class AiConversationSaveRequest(BaseModel):
    conversation_id: Optional[str] = None
    mode: str = "chat"
    current_item_id: Optional[str] = None
    title: Optional[str] = None
    messages: list[AiConversationStoredMessage] = Field(default_factory=list)


class AiConversationSummaryResponse(BaseModel):
    id: str
    title: str
    mode: str = "chat"
    current_item_id: Optional[str] = None
    current_item_title: Optional[str] = None
    message_count: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AiConversationResponse(AiConversationSummaryResponse):
    messages: list[AiConversationStoredMessage] = Field(default_factory=list)


class AiConversationListResponse(BaseModel):
    conversations: list[AiConversationSummaryResponse] = Field(default_factory=list)


class ItemPageNoteResponse(BaseModel):
    id: str
    item_id: str
    ai_conversation_id: Optional[str] = None
    ai_message_index: Optional[int] = None
    title: str
    content: str = ""
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ItemPageNoteListResponse(BaseModel):
    notes: list[ItemPageNoteResponse] = Field(default_factory=list)


class ItemPageNoteCreateRequest(BaseModel):
    title: Optional[str] = None
    content: str = ""
    ai_conversation_id: Optional[str] = None
    ai_message_index: Optional[int] = None


class ItemPageNoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class HighlightResponse(BaseModel):
    id: str
    item_id: str
    color: str
    text: str
    selector_path: str
    start_text_node_index: int
    start_offset: int
    end_selector_path: str
    end_text_node_index: int
    end_offset: int
    context_before: str = ""
    context_after: str = ""
    page_note_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HighlightListResponse(BaseModel):
    highlights: list[HighlightResponse] = Field(default_factory=list)


class HighlightCreateRequest(BaseModel):
    color: Literal["yellow", "green", "blue", "red"] = "yellow"
    text: str
    selector_path: str
    start_text_node_index: int = 0
    start_offset: int
    end_selector_path: str
    end_text_node_index: int = 0
    end_offset: int
    context_before: str = ""
    context_after: str = ""
    page_note_id: Optional[str] = None


class HighlightUpdateRequest(BaseModel):
    color: Optional[Literal["yellow", "green", "blue", "red"]] = None
    page_note_id: Optional[str] = None


class FolderResponse(BaseModel):
    id: str
    name: str
    sort_order: int = 0
    parent_id: Optional[str] = None
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
    parent_id: Optional[str] = None


class FolderUpdateRequest(BaseModel):
    name: str


class FolderMoveRequest(BaseModel):
    parent_id: Optional[str] = None


class FolderReorderRequest(BaseModel):
    folder_ids: list[str] = Field(default_factory=list)
    parent_id: Optional[str] = None


class TagResponse(BaseModel):
    id: str
    name: str
    color: Optional[str] = None
    item_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    tags: list[TagResponse] = Field(default_factory=list)


class TagCreateRequest(BaseModel):
    name: str
    color: Optional[str] = None


class TagUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class ItemTagUpdateRequest(BaseModel):
    tag_ids: list[str] = Field(default_factory=list)


class ItemFolderUpdateRequest(BaseModel):
    folder_id: Optional[str] = None
    folder_ids: list[str] = Field(default_factory=list)


class ItemContentUpdateRequest(BaseModel):
    title: Optional[str] = None
    canonical_text: Optional[str] = None
    canonical_html: Optional[str] = None


class ItemNoteUpdateRequest(BaseModel):
    extracted_text: str = ""


class BulkFolderUpdateRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    folder_id: Optional[str] = None
    folder_ids: list[str] = Field(default_factory=list)


class BulkFolderUpdateResponse(BaseModel):
    updated_count: int
