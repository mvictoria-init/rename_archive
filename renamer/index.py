"""Acceso ligero a la base de datos de índice `data/index.db`.

Qué hace: funciones auxiliares para comprobar existencia del fichero DB,
conectar y obtener listados filtrados por carpeta o por hash. Diseñado
para usarse desde la GUI y los scripts de indexado.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'data' / 'index.db'


def db_exists() -> bool:
    """Devuelve True si `data/index.db` existe.

    Por qué: evitar errores al intentar conectar si la base de datos no existe.
    """
    return DB_PATH.exists()


def _connect():
    """Crear y devolver una nueva conexión sqlite3 al archivo de índice."""
    return sqlite3.connect(str(DB_PATH))


def files_in_folder(folder: Path) -> Iterator[dict]:
    """Generador de filas para archivos cuyo path absoluto empieza por `folder`.

    Cada dict yieldeado contiene: path, size, sha256, title, authors.
    Por qué: permitir cargar rápidamente la vista de la GUI desde el índice.
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
    """Devuelve una lista de filas (dict) de archivos con el SHA256 especificado."""
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
    """Devuelve el separador de ruta del sistema operativo.

    Nota: sqlite LIKE trata las barras invertidas literalmente en Windows,
    por eso se maneja el separador de forma explícita.
    """
    import os
    return os.sep
