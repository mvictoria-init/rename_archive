"""Pequeño script para inspeccionar de forma rápida la base `data/index.db`.

Imprime existencia y algunos conteos/muestras para depuración local.
"""
from pathlib import Path
import sqlite3
# Use project-root relative path to find data/index.db reliably
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'index.db'
print('DB path:', DB)
print('DB exists:', DB.exists())
if DB.exists():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    try:
        cur.execute('SELECT count(*) FROM files')
        print('files_count=', cur.fetchone()[0])
    except Exception as e:
        print('ERR count', e)
    try:
        cur.execute('SELECT path FROM files ORDER BY path LIMIT 10')
        for r in cur.fetchall():
            print('sample_path:', r[0])
    except Exception as e:
        print('ERR sample', e)
    conn.close()
