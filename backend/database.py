from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from paths import DB_PATH

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_runtime_schema():
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_name ON folders(name)")

        item_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(items)").fetchall()
        }
        if "folder_id" not in item_columns:
            connection.exec_driver_sql("ALTER TABLE items ADD COLUMN folder_id VARCHAR REFERENCES folders(id)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_items_folder_id ON items(folder_id)")

        settings_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(settings)").fetchall()
        }
        if "obsidian_folder_path" not in settings_columns:
            connection.exec_driver_sql("ALTER TABLE settings ADD COLUMN obsidian_folder_path VARCHAR")


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
