from sqlalchemy import create_engine
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
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
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


def _encrypt_existing_app_config(connection) -> None:
    app_config_columns = _table_columns(connection, "app_config")
    if "google_oauth_client_secret" not in app_config_columns:
        return

    for row in connection.exec_driver_sql(
        "SELECT id, google_oauth_client_secret FROM app_config"
    ).mappings():
        encrypted = encrypt_secret(row["google_oauth_client_secret"])
        if not encrypted or encrypted == row["google_oauth_client_secret"]:
            continue
        connection.exec_driver_sql(
            "UPDATE app_config SET google_oauth_client_secret = :secret WHERE id = :id",
            {"id": row["id"], "secret": encrypted},
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
        user_columns = _table_columns(connection, "users")
        if "phone_e164" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN phone_e164 VARCHAR")
        if "google_sub" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN google_sub VARCHAR")
        if "avatar_url" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_url VARCHAR")
        if "email_verified_at" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN email_verified_at DATETIME")
        if "phone_verified_at" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN phone_verified_at DATETIME")
        if "last_login_at" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_e164 ON users(phone_e164)")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)")

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
        connection.exec_driver_sql(
            "UPDATE items SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE items SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_user_id ON items(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_workspace_id ON items(workspace_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_folder_id ON items(folder_id)")

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
        connection.exec_driver_sql(
            "UPDATE folders SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE folders SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_folders_workspace_name")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_folders_workspace_id ON folders(workspace_id)")
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
        connection.exec_driver_sql(
            "UPDATE settings SET user_id = ? WHERE user_id IS NULL OR trim(user_id) = ''",
            (DEFAULT_USER_ID,),
        )
        connection.exec_driver_sql(
            "UPDATE settings SET workspace_id = ? WHERE workspace_id IS NULL OR trim(workspace_id) = ''",
            (DEFAULT_WORKSPACE_ID,),
        )
        connection.exec_driver_sql("DROP INDEX IF EXISTS idx_settings_workspace_id")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_settings_user_id ON settings(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_settings_workspace_id ON settings(workspace_id)")
        _encrypt_existing_settings(connection)

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_oauth_client_id VARCHAR,
                google_oauth_client_secret VARCHAR,
                google_oauth_redirect_uri VARCHAR
            )
            """
        )
        app_config_columns = _table_columns(connection, "app_config")
        if "google_oauth_client_id" not in app_config_columns:
            connection.exec_driver_sql("ALTER TABLE app_config ADD COLUMN google_oauth_client_id VARCHAR")
        if "google_oauth_client_secret" not in app_config_columns:
            connection.exec_driver_sql("ALTER TABLE app_config ADD COLUMN google_oauth_client_secret VARCHAR")
        if "google_oauth_redirect_uri" not in app_config_columns:
            connection.exec_driver_sql("ALTER TABLE app_config ADD COLUMN google_oauth_redirect_uri VARCHAR")
        _encrypt_existing_app_config(connection)

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                token_hash VARCHAR NOT NULL UNIQUE,
                provider VARCHAR NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen_at DATETIME,
                expires_at DATETIME NOT NULL,
                revoked_at DATETIME,
                user_agent VARCHAR,
                ip_address VARCHAR
            )
            """
        )
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_sessions_token_hash ON auth_sessions(token_hash)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at)")

        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS auth_verification_codes (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR REFERENCES users(id),
                channel VARCHAR NOT NULL,
                target VARCHAR NOT NULL,
                code_salt VARCHAR NOT NULL,
                code_hash VARCHAR NOT NULL,
                purpose VARCHAR NOT NULL DEFAULT 'login',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                consumed_at DATETIME,
                attempt_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_codes_user_id ON auth_verification_codes(user_id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_codes_target ON auth_verification_codes(target)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_codes_channel ON auth_verification_codes(channel)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_codes_purpose ON auth_verification_codes(purpose)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_auth_codes_expires_at ON auth_verification_codes(expires_at)")


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
