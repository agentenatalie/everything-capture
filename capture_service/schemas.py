from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CaptureCreateRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    source: str = "unknown"
    source_app: str | None = None
    title: str | None = None
    timestamp: datetime | None = None
    folder_names: list[str] = Field(default_factory=list)


class CaptureFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class CaptureFolderListResponse(BaseModel):
    folders: list[CaptureFolderResponse] = Field(default_factory=list)
    total_count: int = 0


class CaptureFolderCreateRequest(BaseModel):
    name: str


class CaptureItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_text: str | None = None
    raw_url: str | None = None
    title: str | None = None
    source: str
    source_app: str | None = None
    client_timestamp: datetime | None = None
    folder_names: list[str] = Field(default_factory=list)
    status: str
    lease_token: str | None = None
    error_reason: str | None = None
    local_item_id: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None

class CaptureCreateResponse(BaseModel):
    success: bool = True
    captured: bool = True
    item_id: str
    status: str = "pending"
    item: CaptureItemResponse


class CaptureListResponse(BaseModel):
    items: list[CaptureItemResponse] = Field(default_factory=list)
    total_count: int = 0


class CaptureClaimRequest(BaseModel):
    worker_id: str


class CaptureClaimResponse(BaseModel):
    success: bool
    item: CaptureItemResponse | None = None


class CaptureCompleteRequest(BaseModel):
    lease_token: str
    local_item_id: str | None = None
    result_json: str | None = None


class CaptureFailRequest(BaseModel):
    lease_token: str
    error_reason: str
