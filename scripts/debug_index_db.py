from pathlib import Path
import sqlite3
DB=Path('data/index.db')
print('DB exists:', DB.exists())
if DB.exists():
    conn=sqlite3.connect(str(DB))
    cur=conn.cursor()
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
