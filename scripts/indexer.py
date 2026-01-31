"""
Indexador rápido para la colección de libros.
- Uso: python scripts/indexer.py <folder> [--rebuild]
- Crea/usa `data/index.db` con tablas `files` y `texts`.
- Es incremental: si un archivo ya está en la BD con el mismo mtime y tamaño, se salta.
- Extrae metadata mínima usando `renamer.metadata.extract_metadata` y textos con los extractores de `renamer.convert`.
"""
from __future__ import annotations
import sys
import os
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / 'data'
DB_PATH = DB_DIR / 'index.db'


# Make sure the project root is on sys.path so `renamer` package can be imported
sys.path.insert(0, str(ROOT))

# reuse existing extractors
from renamer.metadata import extract_metadata
from renamer.convert import _extract_text_from_docx, _extract_text_from_html, _extract_text_from_txt

BUF_SIZE = 65536


def ensure_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        path TEXT UNIQUE,
        relpath TEXT,
        size INTEGER,
        mtime REAL,
        sha256 TEXT,
        title TEXT,
        authors TEXT,
        needs_ocr INTEGER DEFAULT 0,
        indexed_at TEXT
    )''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS texts (
        file_id INTEGER,
        block_index INTEGER,
        text TEXT,
        FOREIGN KEY(file_id) REFERENCES files(id)
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime)')
    conn.commit()
    return conn


def file_sha256(path: Path) -> str | None:
    h = hashlib.sha256()
    try:
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(BUF_SIZE), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def extract_text_for_index(path: Path):
    suffix = path.suffix.lower()
    if suffix == '.docx':
        return _extract_text_from_docx(path)
    if suffix in ('.html', '.htm'):
        return _extract_text_from_html(path)
    if suffix == '.txt':
        return _extract_text_from_txt(path)
    # fallback: try reading raw text
    try:
        txt = path.read_text(encoding='utf-8', errors='ignore')
        # split into paragraphs
        parts = [p.strip() for p in txt.split('\n\n') if p.strip()][:10]
        return parts
    except Exception:
        return []


def index_file(conn: sqlite3.Connection, root_folder: Path, path: Path, force_reindex=False):
    rel = str(path.relative_to(root_folder))
    stat = None
    try:
        stat = path.stat()
    except Exception:
        return False, 'stat_failed'
    size = stat.st_size
    mtime = stat.st_mtime
    cur = conn.cursor()
    cur.execute('SELECT id,size,mtime,sha256 FROM files WHERE path=?', (str(path),))
    row = cur.fetchone()
    if row and not force_reindex:
        fid, old_size, old_mtime, old_sha = row
        if old_size == size and abs(old_mtime - mtime) < 1.0:
            return False, 'skipped'
    # compute sha256
    sha = file_sha256(path)
    title, authors = (None, None)
    try:
        meta = extract_metadata(path)
        title = meta.get('title') if isinstance(meta, dict) else None
        authors = meta.get('authors') if isinstance(meta, dict) else None
    except Exception:
        pass
    # insert or update file row
    now = datetime.utcnow().isoformat()
    if row:
        cur.execute('''UPDATE files SET relpath=?, size=?, mtime=?, sha256=?, title=?, authors=?, indexed_at=? WHERE id=?''',
                    (rel, size, mtime, sha, str(authors) if authors else None, now, row[0]))
        fid = row[0]
        cur.execute('DELETE FROM texts WHERE file_id=?', (fid,))
    else:
        cur.execute('''INSERT OR REPLACE INTO files(path,relpath,size,mtime,sha256,title,authors,indexed_at) VALUES(?,?,?,?,?,?,?,?)''',
                    (str(path), rel, size, mtime, sha, title, str(authors) if authors else None, now))
        fid = cur.lastrowid

    # extract text blocks (limit to first 10 blocks and first 5000 chars each)
    parts = extract_text_for_index(path)[:10]
    for i, block in enumerate(parts):
        if not block:
            continue
        text = str(block)[:5000]
        cur.execute('INSERT INTO texts(file_id,block_index,text) VALUES(?,?,?)', (fid, i, text))
    conn.commit()
    return True, 'indexed'


def walk_and_index(root_folder: Path, workers=6, force_reindex=False):
    conn = ensure_db()
    files = []
    for p in root_folder.rglob('*'):
        if p.is_file():
            files.append(p)
    total = len(files)
    print(f'Found {total} files; indexing with {workers} workers')
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(index_file, conn, root_folder, p, force_reindex): p for p in files}
        done = 0
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                ok, msg = fut.result()
            except Exception as e:
                ok, msg = False, str(e)
            done += 1
            if done % 50 == 0 or not ok:
                print(f'[{done}/{total}] {p} -> {msg}')
    conn.close()
    print('Indexing completed')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', nargs='?', default='.', help='Root folder to index')
    ap.add_argument('--workers', type=int, default=min(8, (os.cpu_count() or 4)), help='Number of worker threads')
    ap.add_argument('--rebuild', action='store_true', help='Force re-index all files')
    args = ap.parse_args()
    root = Path(args.folder).resolve()
    if not root.exists():
        print('Folder not found:', root)
        sys.exit(1)
    walk_and_index(root, workers=args.workers, force_reindex=args.rebuild)
