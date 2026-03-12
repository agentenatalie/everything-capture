from sqlalchemy import Boolean, Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from tenant import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID
import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    slug = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    items = relationship("Item", back_populates="workspace")
    media = relationship("Media", back_populates="workspace")
    folders = relationship("Folder", back_populates="workspace")
    settings = relationship("Settings", back_populates="workspace")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    phone_e164 = Column(String, nullable=True, unique=True, index=True)
    google_sub = Column(String, nullable=True, unique=True, index=True)
    avatar_url = Column(String, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    email_verified_at = Column(DateTime, nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    items = relationship("Item", back_populates="user")
    media = relationship("Media", back_populates="user")
    folders = relationship("Folder", back_populates="user")
    settings = relationship("Settings", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user")
    verification_codes = relationship("AuthVerificationCode", back_populates="user")


class Item(Base):
    __tablename__ = "items"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
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
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)
    extracted_text = Column(String, nullable=True)
    ocr_text = Column(String, nullable=True)
    frame_texts_json = Column(String, nullable=True)
    urls_json = Column(String, nullable=True)
    qr_links_json = Column(String, nullable=True)
    parse_status = Column(String, nullable=False, default="idle")
    parse_error = Column(String, nullable=True)
    parsed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="items", lazy="joined")
    workspace = relationship("Workspace", back_populates="items", lazy="joined")
    media = relationship("Media", back_populates="item", cascade="all, delete-orphan", lazy="joined")
    folder = relationship("Folder", back_populates="items", lazy="joined")
    folder_links = relationship("ItemFolderLink", back_populates="item", cascade="all, delete-orphan", lazy="selectin")


class Media(Base):
    __tablename__ = "media"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    item_id = Column(String, ForeignKey("items.id"), nullable=False, index=True)
    type = Column(String, nullable=False)        # image, video, cover
    original_url = Column(String)
    local_path = Column(String)                  # relative to static/
    file_size = Column(Integer, default=0)
    display_order = Column(Integer, default=0)
    inline_position = Column(Float, default=-1.0)  # 0.0-1.0 fractional position within article body; -1 = unknown

    user = relationship("User", back_populates="media", lazy="joined")
    workspace = relationship("Workspace", back_populates="media", lazy="joined")
    item = relationship("Item", back_populates="media")


class Folder(Base):
    __tablename__ = "folders"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    name = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="folders", lazy="joined")
    workspace = relationship("Workspace", back_populates="folders", lazy="joined")
    items = relationship("Item", back_populates="folder")
    item_links = relationship("ItemFolderLink", back_populates="folder", cascade="all, delete-orphan")


class ItemFolderLink(Base):
    __tablename__ = "item_folder_links"

    item_id = Column(String, ForeignKey("items.id"), primary_key=True)
    folder_id = Column(String, ForeignKey("folders.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    item = relationship("Item", back_populates="folder_links")
    folder = relationship("Folder", back_populates="item_links", lazy="joined")


class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    notion_api_token = Column(String, nullable=True)
    notion_database_id = Column(String, nullable=True)
    notion_client_id = Column(String, nullable=True)
    notion_client_secret = Column(String, nullable=True)
    notion_redirect_uri = Column(String, nullable=True)
    obsidian_rest_api_url = Column(String, nullable=True)
    obsidian_api_key = Column(String, nullable=True)
    obsidian_folder_path = Column(String, nullable=True)
    auto_sync_target = Column(String, default="none") # "none", "notion", "obsidian", "both"

    user = relationship("User", back_populates="settings", lazy="joined")
    workspace = relationship("Workspace", back_populates="settings", lazy="joined")


class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    google_oauth_client_id = Column(String, nullable=True)
    google_oauth_client_secret = Column(String, nullable=True)
    google_oauth_redirect_uri = Column(String, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    provider = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)

    user = relationship("User", back_populates="sessions", lazy="joined")


class AuthVerificationCode(Base):
    __tablename__ = "auth_verification_codes"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    channel = Column(String, nullable=False, index=True)
    target = Column(String, nullable=False, index=True)
    code_salt = Column(String, nullable=False)
    code_hash = Column(String, nullable=False)
    purpose = Column(String, nullable=False, index=True, default="login")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="verification_codes", lazy="joined")
