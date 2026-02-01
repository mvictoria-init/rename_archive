"""
Export dataset for training: produce CSV and JSONL with pairs (text -> proposed_filename).
Usage:
    python scripts/export_dataset.py --folder "D:/Ruta/A/TuCarpeta" --limit 4000

Requirements: assumes `data/index.db` created by `scripts/indexer.py` is present.
"""
from __future__ import annotations
import sys
import os
import sqlite3
import csv
import json
from pathlib import Path
import argparse

# ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from renamer.utils import normalize_authors, format_authors_for_filename, guess_title_author_from_filename

DB_PATH = ROOT / 'data' / 'index.db'


def build_proposal(title, authors, filename):
    # title may be None; authors may be None or string/list
    if title and authors:
        a = format_authors_for_filename(normalize_authors(authors), max_authors=3)
        t = str(title).strip()
        if a and t:
            return f"{a} - {t}"
    if title:
        return str(title).strip()
    if authors:
        a = format_authors_for_filename(normalize_authors(authors), max_authors=3)
        return a
    # fallback: guess from filename
    g_title, g_author = guess_title_author_from_filename(filename)
    if g_author and g_title:
        return f"{g_author} - {g_title}"
    if g_title:
        return g_title
    if g_author:
        return g_author
    return None


def _is_noisy_proposal(text: str) -> bool:
    if not text:
        return True
    if 'IndirectObject' in text:
        return True
    return False


def export(folder: Path, out_csv: Path, out_jsonl: Path, limit: int = 0, min_text_chars: int = 50, include_ocr: bool = False):
    if not DB_PATH.exists():
        print('Index DB not found at', DB_PATH)
        return 1
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    prefix = str(folder.resolve()) + os.sep
    cur.execute('SELECT id,path,size,title,authors,needs_ocr FROM files WHERE path LIKE ? ORDER BY path', (prefix + '%',))
    rows = cur.fetchall()
    print(f'Found {len(rows)} indexed files under {folder}')
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_csv.open('w', encoding='utf-8', newline='') as cf, out_jsonl.open('w', encoding='utf-8') as jf:
        writer = csv.DictWriter(cf, fieldnames=['path','text','title','authors','proposal','needs_ocr'])
        writer.writeheader()
        for rid, path_str, size, title, authors, needs_ocr in rows:
            if (not include_ocr) and needs_ocr:
                # omitir archivos marcados sin texto suficiente
                continue
            if limit and written >= limit:
                break
            # load up to first 5 text blocks
            cur.execute('SELECT text FROM texts WHERE file_id=? ORDER BY block_index LIMIT 5', (rid,))
            parts = [r[0] for r in cur.fetchall() if r[0]]
            if not parts:
                # skip entries with no extracted text
                continue
            text = '\n\n'.join(parts)
            if len(text) < min_text_chars:
                # skip too short
                continue
            # truncate text to a reasonable size for model training
            if len(text) > 2000:
                text = text[:2000]
            prop = build_proposal(title, authors, Path(path_str).name)
            if not prop or _is_noisy_proposal(prop):
                # skip if no reasonable label
                continue
            row = {'path': path_str, 'text': text, 'title': title, 'authors': authors, 'proposal': prop, 'needs_ocr': needs_ocr}
            writer.writerow(row)
            jf.write(json.dumps(row, ensure_ascii=False) + '\n')
            written += 1
    conn.close()
    print(f'Wrote {written} samples to {out_csv} and {out_jsonl}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', help='Folder (same one you indexed)')
    ap.add_argument('--limit', type=int, default=4000, help='Max number of samples to export')
    ap.add_argument('--out-csv', default=str(ROOT / 'data' / 'dataset.csv'))
    ap.add_argument('--out-jsonl', default=str(ROOT / 'data' / 'dataset.jsonl'))
    ap.add_argument('--min-text-chars', type=int, default=50)
    ap.add_argument('--include-ocr', action='store_true', help='Incluir archivos marcados como needs_ocr=1')
    args = ap.parse_args()
    folder = Path(args.folder).resolve()
    rc = export(folder, Path(args.out_csv), Path(args.out_jsonl), limit=args.limit, min_text_chars=args.min_text_chars, include_ocr=args.include_ocr)
    sys.exit(rc)
