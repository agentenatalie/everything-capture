import sqlite3
import sys

db_file = 'backend/everything.db'

try:
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        
        # Check if column exists, if not add it
        cursor.execute("PRAGMA table_info(settings)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'notion_client_id' not in columns:
            cursor.execute('ALTER TABLE settings ADD COLUMN notion_client_id TEXT;')
        if 'notion_client_secret' not in columns:
            cursor.execute('ALTER TABLE settings ADD COLUMN notion_client_secret TEXT;')
        if 'notion_redirect_uri' not in columns:
            cursor.execute('ALTER TABLE settings ADD COLUMN notion_redirect_uri TEXT;')
            
        conn.commit()
        print('Settings schema updated successfully.')
except Exception as e:
    print(f'Error updating schema: {e}')
    sys.exit(1)
