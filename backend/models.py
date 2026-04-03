from sqlalchemy import Boolean, Column, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, backref
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
    ai_conversations = relationship("AiConversation", back_populates="workspace")
    page_notes = relationship("ItemPageNote", back_populates="workspace")
    highlights = relationship("Highlight", back_populates="workspace")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    items = relationship("Item", back_populates="user")
    media = relationship("Media", back_populates="user")
    folders = relationship("Folder", back_populates="user")
    settings = relationship("Settings", back_populates="user")
    ai_conversations = relationship("AiConversation", back_populates="user")
    page_notes = relationship("ItemPageNote", back_populates="user")
    highlights = relationship("Highlight", back_populates="user")


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
    obsidian_last_synced_hash = Column(String, nullable=True)
    obsidian_last_synced_at = Column(DateTime, nullable=True)
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
    parse_started_at = Column(DateTime, nullable=True)
    parsed_at = Column(DateTime, nullable=True)
    parse_retry_count = Column(Integer, nullable=False, default=0)
    last_viewed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="items", lazy="joined")
    workspace = relationship("Workspace", back_populates="items", lazy="joined")
    media = relationship("Media", back_populates="item", cascade="all, delete-orphan", lazy="joined")
    folder = relationship("Folder", back_populates="items", lazy="joined")
    folder_links = relationship("ItemFolderLink", back_populates="item", cascade="all, delete-orphan", lazy="selectin")
    ai_conversations = relationship("AiConversation", back_populates="current_item")
    page_notes = relationship("ItemPageNote", back_populates="item", cascade="all, delete-orphan")
    highlights = relationship("Highlight", back_populates="item", cascade="all, delete-orphan")
    tag_links = relationship("ItemTagLink", back_populates="item", cascade="all, delete-orphan", lazy="selectin")


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
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    parent_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="folders", lazy="joined")
    workspace = relationship("Workspace", back_populates="folders", lazy="joined")
    items = relationship("Item", back_populates="folder")
    item_links = relationship("ItemFolderLink", back_populates="folder", cascade="all, delete-orphan")
    children = relationship("Folder", backref=backref("parent", remote_side="Folder.id"), lazy="selectin")


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
    ai_api_key = Column(String, nullable=True)
    ai_base_url = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    ai_agent_can_manage_folders = Column(Boolean, nullable=False, default=True)
    ai_agent_can_parse_content = Column(Boolean, nullable=False, default=True)
    ai_agent_can_sync_obsidian = Column(Boolean, nullable=False, default=False)
    ai_agent_can_sync_notion = Column(Boolean, nullable=False, default=False)
    ai_agent_can_execute_commands = Column(Boolean, nullable=False, default=False)
    ai_agent_can_web_search = Column(Boolean, nullable=False, default=True)
    ai_agent_can_run_computer_commands = Column(Boolean, nullable=False, default=False)
    auto_sync_target = Column(String, default="none") # "none", "notion", "obsidian", "both"
    ai_auto_tag_enabled = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="settings", lazy="joined")
    workspace = relationship("Workspace", back_populates="settings", lazy="joined")


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    current_item_id = Column(String, ForeignKey("items.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    mode = Column(String, nullable=False, default="chat")
    messages_json = Column(Text, nullable=False, default="[]")
    search_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_message_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="ai_conversations", lazy="joined")
    workspace = relationship("Workspace", back_populates="ai_conversations", lazy="joined")
    current_item = relationship("Item", back_populates="ai_conversations", lazy="joined")
    page_notes = relationship("ItemPageNote", back_populates="ai_conversation")


class ItemPageNote(Base):
    __tablename__ = "item_page_notes"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    item_id = Column(String, ForeignKey("items.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    ai_conversation_id = Column(String, ForeignKey("ai_conversations.id"), nullable=True, index=True)
    ai_message_index = Column(Integer, nullable=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    item = relationship("Item", back_populates="page_notes", lazy="joined")
    user = relationship("User", back_populates="page_notes", lazy="joined")
    workspace = relationship("Workspace", back_populates="page_notes", lazy="joined")
    ai_conversation = relationship("AiConversation", back_populates="page_notes", lazy="joined")


class Highlight(Base):
    __tablename__ = "highlights"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    item_id = Column(String, ForeignKey("items.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False, index=True, default=DEFAULT_WORKSPACE_ID)
    color = Column(String(16), nullable=False, default="yellow")
    text = Column(Text, nullable=False)
    selector_path = Column(String, nullable=False)
    start_text_node_index = Column(Integer, nullable=False, default=0)
    start_offset = Column(Integer, nullable=False)
    end_selector_path = Column(String, nullable=False)
    end_text_node_index = Column(Integer, nullable=False, default=0)
    end_offset = Column(Integer, nullable=False)
    context_before = Column(Text, nullable=False, default="")
    context_after = Column(Text, nullable=False, default="")
    page_note_id = Column(String, ForeignKey("item_page_notes.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    item = relationship("Item", back_populates="highlights", lazy="joined")
    user = relationship("User", back_populates="highlights", lazy="joined")
    workspace = relationship("Workspace", back_populates="highlights", lazy="joined")
    page_note = relationship("ItemPageNote", lazy="joined")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")
    item_links = relationship("ItemTagLink", back_populates="tag", cascade="all, delete-orphan")


class ItemTagLink(Base):
    __tablename__ = "item_tag_links"

    item_id = Column(String, ForeignKey("items.id"), primary_key=True)
    tag_id = Column(String, ForeignKey("tags.id"), primary_key=True)
    source = Column(String, nullable=False, default="manual")  # "manual" or "ai"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    item = relationship("Item", back_populates="tag_links")
    tag = relationship("Tag", back_populates="item_links", lazy="joined")


class AiMemory(Base):
    __tablename__ = "ai_memories"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True, default=DEFAULT_USER_ID)
    type = Column(String, nullable=False, default="learned")  # learned, preference, correction
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User")

