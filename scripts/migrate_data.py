#!/usr/bin/env python3
"""Everything Capture — data migration utility.

One-time migration script: move user data from the project directory
to the external data directory (everything-capture-data/).

Usage:
    cd everything-capture
    python scripts/migrate_data.py [--move]

By default files are COPIED (safe). Pass --move to move instead.
"""
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

# Resolve the same DATA_ROOT as paths.py
DATA_ROOT = Path(
    os.getenv("DATA_DIR")
    or str(PROJECT_ROOT.parent / "everything-capture-data")
).resolve()

OLD_DB = BACKEND_DIR / "items.db"
OLD_MEDIA = BACKEND_DIR / "static" / "media"
OLD_LOCAL = BACKEND_DIR / ".local"

NEW_DB = DATA_ROOT / "app.db"
NEW_MEDIA = DATA_ROOT / "media"
NEW_LOCAL = DATA_ROOT / ".local"


def migrate(use_move: bool = False):
    action = "Moving" if use_move else "Copying"
    transfer = shutil.move if use_move else shutil.copy2
    transfer_tree = shutil.move if use_move else shutil.copytree

    DATA_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. Local state (master.key)
    master_src = OLD_LOCAL / "master.key"
    master_dst = NEW_LOCAL / "master.key"
    if master_src.exists() and not master_dst.exists():
        NEW_LOCAL.mkdir(parents=True, exist_ok=True)
        transfer(str(master_src), str(master_dst))
        if not use_move:
            os.chmod(str(master_dst), 0o600)
        print(f"  {action} master.key -> {master_dst}")
    else:
        print(f"  master.key: skipped (src missing or dst exists)")

    # 2. Database
    if OLD_DB.exists() and not NEW_DB.exists():
        transfer(str(OLD_DB), str(NEW_DB))
        print(f"  {action} items.db -> {NEW_DB}")
        for suffix in ("-wal", "-shm"):
            wal = OLD_DB.with_name(OLD_DB.name + suffix)
            if wal.exists():
                transfer(str(wal), str(NEW_DB.with_name(NEW_DB.name + suffix)))
                print(f"  {action} {wal.name}")
    else:
        print(f"  database: skipped (src missing or dst exists)")

    # 3. Media directory
    if OLD_MEDIA.exists() and not (NEW_MEDIA / "users").exists():
        NEW_MEDIA.mkdir(parents=True, exist_ok=True)
        for child in OLD_MEDIA.iterdir():
            dst = NEW_MEDIA / child.name
            if dst.exists():
                continue
            if child.is_dir():
                transfer_tree(str(child), str(dst))
            else:
                transfer(str(child), str(dst))
            print(f"  {action} media/{child.name} -> {dst}")
    else:
        print(f"  media: skipped (src missing or dst exists)")

    # 4. Create empty dirs
    (DATA_ROOT / "exports").mkdir(parents=True, exist_ok=True)

    print(f"\nDone! Data directory: {DATA_ROOT}")


if __name__ == "__main__":
    use_move = "--move" in sys.argv
    print(f"Migrating data to: {DATA_ROOT}")
    print(f"Mode: {'MOVE' if use_move else 'COPY (safe, old files preserved)'}\n")
    migrate(use_move)
