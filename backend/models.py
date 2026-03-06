from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Item(Base):
    __tablename__ = "items"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    source_url = Column(String, index=True)
    final_url = Column(String)
    title = Column(String)
    canonical_text = Column(String)
    canonical_text_length = Column(Integer)
    canonical_html = Column(String, nullable=True) # Stored sanitized HTML from article
    platform = Column(String)
    status = Column(String, default="ready") # ready, failed
    error_reason = Column(String, nullable=True)
    notion_page_id = Column(String, nullable=True)
    obsidian_path = Column(String, nullable=True)
    debug_json = Column(String, nullable=True)
    content_blocks_json = Column(String, nullable=True)  # JSON: [{type:text|image, content|url}]

    media = relationship("Media", back_populates="item", cascade="all, delete-orphan", lazy="joined")


class Media(Base):
    __tablename__ = "media"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    item_id = Column(String, ForeignKey("items.id"), nullable=False, index=True)
    type = Column(String, nullable=False)        # image, video, cover
    original_url = Column(String)
    local_path = Column(String)                  # relative to static/
    file_size = Column(Integer, default=0)
    display_order = Column(Integer, default=0)
    inline_position = Column(Float, default=-1.0)  # 0.0-1.0 fractional position within article body; -1 = unknown

    item = relationship("Item", back_populates="media")

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True, default=1)
    notion_api_token = Column(String, nullable=True)
    notion_database_id = Column(String, nullable=True)
    notion_client_id = Column(String, nullable=True)
    notion_client_secret = Column(String, nullable=True)
    notion_redirect_uri = Column(String, nullable=True)
    obsidian_rest_api_url = Column(String, nullable=True)
    obsidian_api_key = Column(String, nullable=True)
    obsidian_folder_path = Column(String, nullable=True)
    auto_sync_target = Column(String, default="none") # "none", "notion", "obsidian", "both"
