"""Helpers to read the index DB created by `scripts/indexer.py`.

Functions:
- db_path(): path to data/index.db
- files_in_folder(folder): yield dicts for files whose absolute path starts with `folder`
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'data' / 'index.db'


def db_exists() -> bool:
    return DB_PATH.exists()


def _connect():
    return sqlite3.connect(str(DB_PATH))


def files_in_folder(folder: Path) -> Iterator[dict]:
    """Yield rows for files inside `folder`.

    Each yielded dict contains: path, size, sha256, title, authors
    """
    folder = Path(folder).resolve()
    if not db_exists():
        return
    conn = _connect()
    cur = conn.cursor()
    # Use parameterized LIKE to match paths under the folder
    # Normalize to string with trailing separator to avoid prefix collisions
    prefix = str(folder) + os_sep()
    try:
        cur.execute('SELECT path,size,sha256,title,authors FROM files WHERE path LIKE ? ORDER BY path', (prefix + '%',))
    except Exception:
        # Fallback: try without trailing separator
        cur.execute('SELECT path,size,sha256,title,authors FROM files WHERE path LIKE ? ORDER BY path', (str(folder) + '%',))
    for row in cur.fetchall():
        path, size, sha, title, authors = row
        yield {'path': path, 'size': size, 'sha256': sha, 'title': title, 'authors': authors}
    conn.close()


def find_files_by_hash(sha256: str) -> list[dict]:
    """Return list of dicts for files with the given SHA256."""
    if not db_exists():
        return []
    conn = _connect()
    cur = conn.cursor()
    cur.execute('SELECT path,size,sha256,title,authors FROM files WHERE sha256 = ?', (sha256,))
    rows = []
    for row in cur.fetchall():
        path, size, sha, title, authors = row
        rows.append({'path': path, 'size': size, 'sha256': sha, 'title': title, 'authors': authors})
    conn.close()
    return rows


def os_sep() -> str:
    # sqlite LIKE expects backslashes to match literally; return os-specific separator
    import os
    return os.sep
