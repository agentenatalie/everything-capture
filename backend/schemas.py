from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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
    status: str
    platform: str
    
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
