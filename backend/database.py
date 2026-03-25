from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from paths import DB_PATH
from security import encrypt_secret
from tenant import (
    DEFAULT_USER_EMAIL,
    DEFAULT_USER_ID,
    DEFAULT_USER_NAME,
    DEFAULT_WORKSPACE_ID,
    DEFAULT_WORKSPACE_NAME,
    DEFAULT_WORKSPACE_SLUG,
)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=5,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-32000")  # 32MB
    cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _table_columns(connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    }


def _encrypt_existing_settings(connection) -> None:
    secret_columns = [
        "notion_api_token",
        "notion_client_secret",
        "obsidian_api_key",
        "ai_api_key",
    ]
    settings_columns = _table_columns(connection, "settings")
    available_columns = [column for column in secret_columns if column in settings_columns]
    if not available_columns:
        return

    select_sql = "SELECT id, " + ", ".join(available_columns) + " FROM settings"
    for row in connection.exec_driver_sql(select_sql).mappings():
        updates: dict[str, str] = {}
        for column in available_columns:
            encrypted = encrypt_secret(row[column])
            if encrypted and encrypted != row[column]:
                updates[column] = encrypted

        if not updates:
            continue

        assignment_sql = ", ".join(f"{column} = :{column}" for column in updates)
        params = {"id": row["id"], **updates}
        connection.exec_driver_sql(
            f"UPDATE settings SET {assignment_sql} WHERE id = :id",
            params,
        )



def ensure_runtime_schema():
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR PRIMARY KEY,
                email VARCHAR NOT NULL UNIQUE,
                display_name VARCHAR NOT NULL,
                is_default BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO users (id, email, display_name, is_default) VALUES (?, ?, ?, 1)",
            (DEFAULT_USER_ID, DEFAULT_USER_EMAIL, DEFAULT_USER_NAME),
        )
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_users_is_default ON users(is_default)")

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
                id VARCHAR PRIMARY KEY,
                slug VARCHAR NOT NULL UNIQUE,
                name VARCHAR NOT NULL,
                is_default BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO workspaces (id, slug, name, is_default) VALUES (?, ?, ?, 1)",
            (DEFAULT_WORKSPACE_ID, DEFAULT_WORKSPACE_SLUG, DEFAULT_WORKSPACE_NAME),
        )
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_slug ON workspaces(slug)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_workspaces_is_default ON workspaces(is_default)")

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id VARCHAR PRIMARY KEY,
                workspace_id VARCHAR NOT NULL REFERENCES workspaces(id),
                name VARCHAR NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql("DROP INDEX IF EXISTS ix_folders_name")
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_folders_name")

        item_columns = _table_columns(connection, "items")
        if "user_id" not in item_columns:
            connection.exec_driver_sql(
                "ALTER TABLE items ADD COLUMN user_id VARCHAR REFERENCES users(id)"
            )
        if "workspace_id" not in item_columns:
            connection.exec_driver_sql(
                "ALTER TABLE items ADD COLUMN workspace_id VARCHAR REFERENCES workspaces(id)"
            )
        if "folder_id" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN folder_id VARCHAR REFERENCES folders(id)")
        if "extracted_text" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN extracted_text VARCHAR")
        if "ocr_text" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN ocr_text VARCHAR")
        if "frame_texts_json" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN frame_texts_json VARCHAR")
        if "urls_json" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN urls_json VARCHAR")
        if "qr_links_json" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN qr_links_json VARCHAR")
        if "parse_status" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN parse_status VARCHAR NOT NULL DEFAULT 'idle'")
        if "parse_error" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN parse_error VARCHAR")
        if "parsed_at" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN parsed_at DATETIME")
        if "obsidian_last_synced_hash" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN obsidian_last_synced_hash VARCHAR")
        if "obsidian_last_synced_at" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN obsidian_last_synced_at DATETIME")
        connection.exec_driver_sql(
            "UPDATE items SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE items SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE items SET parse_status = 'idle' WHERE parse_status IS NULL OR trim(parse_status) = ''"
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_workspace_id ON items(workspace_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_folder_id ON items(folder_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_parse_status ON items(parse_status)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_parsed_at ON items(parsed_at)")

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS item_folder_links (
                item_id VARCHAR NOT NULL REFERENCES items(id),
                folder_id VARCHAR NOT NULL REFERENCES folders(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (item_id, folder_id)
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT OR IGNORE INTO item_folder_links (item_id, folder_id, created_at)
            SELECT id, folder_id, CURRENT_TIMESTAMP
            FROM items
            WHERE folder_id IS NOT NULL AND trim(folder_id) != ''
            """
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_item_folder_links_item_id ON item_folder_links(item_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_item_folder_links_folder_id ON item_folder_links(folder_id)")

        media_columns = _table_columns(connection, "media")
        if "user_id" not in media_columns:
            connection.exec_driver_sql(
                "ALTER TABLE media ADD COLUMN user_id VARCHAR REFERENCES users(id)"
            )
        if "workspace_id" not in media_columns:
            connection.exec_driver_sql(
                "ALTER TABLE media ADD COLUMN workspace_id VARCHAR REFERENCES workspaces(id)"
            )
        connection.exec_driver_sql(
            """
            UPDATE media
            SET user_id = COALESCE(
                (SELECT items.user_id FROM items WHERE items.id = media.item_id),
                ?
            )
            WHERE user_id IS NULL OR trim(user_id) = ''
            """,
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            """
            UPDATE media
            SET workspace_id = COALESCE(
                (SELECT items.workspace_id FROM items WHERE items.id = media.item_id),
                ?
            )
            WHERE workspace_id IS NULL OR trim(workspace_id) = ''
            """,
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_media_user_id ON media(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_media_workspace_id ON media(workspace_id)")

        folder_columns = _table_columns(connection, "folders")
        if "user_id" not in folder_columns:
            connection.exec_driver_sql(
                "ALTER TABLE folders ADD COLUMN user_id VARCHAR REFERENCES users(id)"
            )
        if "workspace_id" not in folder_columns:
            connection.exec_driver_sql(
                "ALTER TABLE folders ADD COLUMN workspace_id VARCHAR REFERENCES workspaces(id)"
            )
        if "sort_order" not in folder_columns:
            connection.exec_driver_sql(
                "ALTER TABLE folders ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
        connection.exec_driver_sql(
            "UPDATE folders SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE folders SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        folder_sort_rows = connection.exec_driver_sql(
            """
            SELECT id
            FROM folders
            ORDER BY
                COALESCE(sort_order, 2147483647) ASC,
                updated_at DESC,
                created_at DESC,
                lower(name) ASC,
                id ASC
            """
        ).fetchall()
        for index, row in enumerate(folder_sort_rows):
            connection.exec_driver_sql(
                "UPDATE folders SET sort_order = ? WHERE id = ?",
                (index, row[0]),
            )
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_folders_workspace_name")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_folders_workspace_id ON folders(workspace_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_folders_user_sort_order ON folders(user_id, sort_order)")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_user_name ON folders(user_id, name)"
        )

        settings_columns = _table_columns(connection, "settings")
        if "user_id" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN user_id VARCHAR REFERENCES users(id)"
            )
        if "workspace_id" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN workspace_id VARCHAR REFERENCES workspaces(id)"
            )
        if "obsidian_folder_path" not in settings_columns:
            connection.exec_driver_sql("ALTER TABLE settings ADD COLUMN obsidian_folder_path VARCHAR")
        if "ai_api_key" not in settings_columns:
            connection.exec_driver_sql("ALTER TABLE settings ADD COLUMN ai_api_key VARCHAR")
        if "ai_base_url" not in settings_columns:
            connection.exec_driver_sql("ALTER TABLE settings ADD COLUMN ai_base_url VARCHAR")
        if "ai_model" not in settings_columns:
            connection.exec_driver_sql("ALTER TABLE settings ADD COLUMN ai_model VARCHAR")
        if "ai_agent_can_manage_folders" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_manage_folders BOOLEAN NOT NULL DEFAULT 1"
            )
        if "ai_agent_can_parse_content" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_parse_content BOOLEAN NOT NULL DEFAULT 1"
            )
        if "ai_agent_can_sync_obsidian" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_sync_obsidian BOOLEAN NOT NULL DEFAULT 0"
            )
        if "ai_agent_can_sync_notion" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_sync_notion BOOLEAN NOT NULL DEFAULT 0"
            )
        if "ai_agent_can_execute_commands" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_execute_commands BOOLEAN NOT NULL DEFAULT 0"
            )
        if "ai_agent_can_web_search" not in settings_columns:
            connection.exec_driver_sql(
                "ALTER TABLE settings ADD COLUMN ai_agent_can_web_search BOOLEAN NOT NULL DEFAULT 1"
            )
        connection.exec_driver_sql(
            "UPDATE settings SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE settings SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_manage_folders = 1 WHERE ai_agent_can_manage_folders IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_parse_content = 1 WHERE ai_agent_can_parse_content IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_sync_obsidian = 0 WHERE ai_agent_can_sync_obsidian IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_sync_notion = 0 WHERE ai_agent_can_sync_notion IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_execute_commands = 0 WHERE ai_agent_can_execute_commands IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE settings SET ai_agent_can_web_search = 1 WHERE ai_agent_can_web_search IS NULL"
        )
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_settings_workspace_id")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_settings_user_id ON settings(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_settings_workspace_id ON settings(workspace_id)")
        _encrypt_existing_settings(connection)

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                workspace_id VARCHAR NOT NULL REFERENCES workspaces(id),
                current_item_id VARCHAR REFERENCES items(id),
                title VARCHAR NOT NULL,
                mode VARCHAR NOT NULL DEFAULT 'chat',
                messages_json TEXT NOT NULL DEFAULT '[]',
                search_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_message_at DATETIME
            )
            """
        )
        ai_conversation_columns = _table_columns(connection, "ai_conversations")
        if "current_item_id" not in ai_conversation_columns:
            connection.exec_driver_sql(
                "ALTER TABLE ai_conversations ADD COLUMN current_item_id VARCHAR REFERENCES items(id)"
            )
        if "mode" not in ai_conversation_columns:
            connection.exec_driver_sql(
                "ALTER TABLE ai_conversations ADD COLUMN mode VARCHAR NOT NULL DEFAULT 'chat'"
            )
        if "messages_json" not in ai_conversation_columns:
            connection.exec_driver_sql(
                "ALTER TABLE ai_conversations ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "search_text" not in ai_conversation_columns:
            connection.exec_driver_sql("ALTER TABLE ai_conversations ADD COLUMN search_text TEXT")
        if "last_message_at" not in ai_conversation_columns:
            connection.exec_driver_sql("ALTER TABLE ai_conversations ADD COLUMN last_message_at DATETIME")
        connection.exec_driver_sql(
            "UPDATE ai_conversations SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE ai_conversations SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE ai_conversations SET mode = 'chat' WHERE mode IS NULL OR trim(mode) = ''"
        )
        connection.exec_driver_sql(
            "UPDATE ai_conversations SET messages_json = '[]' WHERE messages_json IS NULL OR trim(messages_json) = ''"
        )
        connection.exec_driver_sql(
            "UPDATE ai_conversations SET last_message_at = COALESCE(last_message_at, updated_at, created_at)"
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_id ON ai_conversations(user_id)")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_ai_conversations_current_item_id ON ai_conversations(current_item_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_updated_at ON ai_conversations(user_id, updated_at DESC)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_last_message_at ON ai_conversations(user_id, last_message_at DESC)"
        )

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS item_page_notes (
                id VARCHAR PRIMARY KEY,
                item_id VARCHAR NOT NULL REFERENCES items(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                workspace_id VARCHAR NOT NULL REFERENCES workspaces(id),
                ai_conversation_id VARCHAR REFERENCES ai_conversations(id),
                ai_message_index INTEGER,
                title VARCHAR NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        item_page_note_columns = _table_columns(connection, "item_page_notes")
        if "ai_conversation_id" not in item_page_note_columns:
            connection.exec_driver_sql(
                "ALTER TABLE item_page_notes ADD COLUMN ai_conversation_id VARCHAR REFERENCES ai_conversations(id)"
            )
        if "ai_message_index" not in item_page_note_columns:
            connection.exec_driver_sql("ALTER TABLE item_page_notes ADD COLUMN ai_message_index INTEGER")
        if "content" not in item_page_note_columns:
            connection.exec_driver_sql(
                "ALTER TABLE item_page_notes ADD COLUMN content TEXT NOT NULL DEFAULT ''"
            )
        connection.exec_driver_sql(
            "UPDATE item_page_notes SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE item_page_notes SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_item_page_notes_item_id ON item_page_notes(item_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_item_page_notes_user_id ON item_page_notes(user_id)")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS idx_item_page_notes_ai_conversation_id ON item_page_notes(ai_conversation_id)"
        )

        # --- highlights ---
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS highlights (
                id VARCHAR PRIMARY KEY,
                item_id VARCHAR NOT NULL REFERENCES items(id),
                user_id VARCHAR NOT NULL REFERENCES users(id),
                workspace_id VARCHAR NOT NULL REFERENCES workspaces(id),
                color VARCHAR(16) NOT NULL DEFAULT 'yellow',
                text TEXT NOT NULL,
                selector_path VARCHAR NOT NULL,
                start_text_node_index INTEGER NOT NULL DEFAULT 0,
                start_offset INTEGER NOT NULL,
                end_selector_path VARCHAR NOT NULL,
                end_text_node_index INTEGER NOT NULL DEFAULT 0,
                end_offset INTEGER NOT NULL,
                context_before TEXT NOT NULL DEFAULT '',
                context_after TEXT NOT NULL DEFAULT '',
                page_note_id VARCHAR REFERENCES item_page_notes(id) ON DELETE SET NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_highlights_item_id ON highlights(item_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_highlights_user_id ON highlights(user_id)")

        # --- ai_memories ---
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS ai_memories (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                type VARCHAR NOT NULL DEFAULT 'learned',
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ai_memories_user_id ON ai_memories(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_ai_memories_user_type ON ai_memories(user_id, type)")



def init_search_index():
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                item_id UNINDEXED,
                title,
                content,
                source_url,
                tokenize = 'trigram'
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                INSERT INTO items_fts (item_id, title, content, source_url)
                VALUES (
                    new.id,
                    coalesce(new.title, ''),
                    coalesce(new.canonical_text, ''),
                    coalesce(new.source_url, '')
                );
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                DELETE FROM items_fts WHERE item_id = old.id;
            END
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE OF title, canonical_text, source_url ON items BEGIN
                DELETE FROM items_fts WHERE item_id = old.id;
                INSERT INTO items_fts (item_id, title, content, source_url)
                VALUES (
                    new.id,
                    coalesce(new.title, ''),
                    coalesce(new.canonical_text, ''),
                    coalesce(new.source_url, '')
                );
            END
            """
        )
        connection.exec_driver_sql("DELETE FROM items_fts")
        connection.exec_driver_sql(
            """
            INSERT INTO items_fts (item_id, title, content, source_url)
            SELECT
                id,
                coalesce(title, ''),
                coalesce(canonical_text, ''),
                coalesce(source_url, '')
            FROM items
            """
        )

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
