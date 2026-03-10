import datetime as dt
import uuid

from sqlalchemy import Column, DateTime, String, Text

from capture_service.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class CaptureItem(Base):
    __tablename__ = "capture_items"

    id = Column(String, primary_key=True, default=generate_uuid)
    raw_text = Column(Text, nullable=True)
    raw_url = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    source = Column(String, nullable=False, default="unknown", index=True)
    source_app = Column(String, nullable=True)
    client_timestamp = Column(DateTime, nullable=True)
    folder_names_json = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)
    lease_token = Column(String, nullable=True, unique=True, index=True)
    leased_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    error_reason = Column(Text, nullable=True)
    local_item_id = Column(String, nullable=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class CaptureFolder(Base):
    __tablename__ = "capture_folders"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)
