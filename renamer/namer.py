"""Formateo canónico de nombres de libros a partir de metadatos.

Funciones útiles para construir nombres del estilo:

  Autor(es) - Título - Subtítulo.ext

Incluye el subtítulo solo si está presente y usa las utilidades
de `renamer.utils` para normalizar y sanitizar los campos.
"""
import os
from .utils import sanitize, normalize_authors, format_authors_for_filename, guess_title_author_from_filename, is_suspect_title, is_suspicious_author, normalize_title_case, normalize_author_case


def format_book_filename(title, author=None, subtitle=None, ext='', include_author=True, include_subtitle=True):
    """Devuelve un nombre de fichero propuesto a partir de metadatos.

    `ext` puede incluir o no el punto inicial (ej. '.pdf' o 'pdf').
    Los flags `include_author`/`include_subtitle` permiten controlar si
    se incluyen esos elementos en la propuesta (útil para modelos ligeros).
    """
    auth_norm = normalize_authors(author) if author else None
    a = format_authors_for_filename(auth_norm, max_authors=3) if auth_norm and include_author else ''
    t = sanitize(str(title)) if title else ''
    s = sanitize(str(subtitle)) if subtitle and include_subtitle else ''

    if ext and not ext.startswith('.'):
        ext = '.' + ext

    if a and t:
        if s:
            name = f"{a} - {t} - {s}{ext}"
        else:
            name = f"{a} - {t}{ext}"
    elif t:
        if s:
            name = f"{t} - {s}{ext}"
        else:
            name = f"{t}{ext}"
    elif a:
        name = f"{a}{ext}"
    else:
        name = f"Unknown{ext}"

    return name


def filename_from_mapping_entry(entry: dict):
    """Construye el nombre propuesto a partir de una entrada del mapping.

    La entrada debe contener al menos las claves: `file`, `title`, `author`, `subtitle`.
    """
    path = entry.get('file') or ''
    ext = os.path.splitext(path)[1] if path else ''

    title = entry.get('title')
    author = entry.get('author')
    subtitle = entry.get('subtitle')

    # normalize cases where possible
    try:
        title = normalize_title_case(title) if title else None
    except Exception:
        pass
    try:
        subtitle = normalize_title_case(subtitle) if subtitle else None
    except Exception:
        pass
    try:
        author = normalize_author_case(author) if author else None
    except Exception:
        pass

    # guess title/author from filename as fallback or to override suspicious metadata
    try:
        guessed_title, guessed_author = guess_title_author_from_filename(path)
    except Exception:
        guessed_title, guessed_author = (None, None)

    if (not title or is_suspect_title(title)) and guessed_title:
        title = guessed_title
    # prefer guessed author when metadata is missing/suspicious or filename contains a more complete author
    try:
        author_short = len(str(author).split()) if author else 0
    except Exception:
        author_short = 0
    try:
        guessed_author_words = len(str(guessed_author).split()) if guessed_author else 0
    except Exception:
        guessed_author_words = 0

    if guessed_author and ((not author) or is_suspicious_author(author) or (author_short == 1 and guessed_author_words > 1)):
        author = guessed_author

    # if subtitle looks like content/credits or is very long, drop it to avoid noisy filenames
    try:
        subtitle_words = len(str(subtitle).split()) if subtitle else 0
    except Exception:
        subtitle_words = 0
    if subtitle and (is_suspect_title(subtitle) or len(str(subtitle)) > 120 or subtitle_words >= 10):
        subtitle = None

    return format_book_filename(title, author, subtitle, ext)


__all__ = ["format_book_filename", "filename_from_mapping_entry"]
