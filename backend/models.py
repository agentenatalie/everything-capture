from sqlalchemy import Column, String, Integer, DateTime
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
    platform = Column(String)
    status = Column(String, default="ready") # ready, failed
    error_reason = Column(String, nullable=True)
    notion_page_id = Column(String, nullable=True)
    obsidian_path = Column(String, nullable=True)
    debug_json = Column(String, nullable=True)
