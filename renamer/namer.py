"""Formateo canónico de nombres de libros a partir de metadatos.

Funciones útiles para construir nombres del estilo:

  Autor(es) - Título - Subtítulo.ext

Incluye el subtítulo solo si está presente y usa las utilidades
de `renamer.utils` para normalizar y sanitizar los campos.
"""
import os
from .utils import sanitize, normalize_authors, format_authors_for_filename, guess_title_author_from_filename, is_suspect_title, is_suspicious_author, normalize_title_case, normalize_author_case, remove_banned_phrases, extract_series_from_text


def format_book_filename(title, author=None, subtitle=None, series=None, series_num=None, ext='', include_author=True, include_subtitle=True):
    """Devuelve un nombre de fichero propuesto a partir de metadatos.

    `ext` puede incluir o no el punto inicial (ej. '.pdf' o 'pdf').
    Los flags `include_author`/`include_subtitle` permiten controlar si
    se incluyen esos elementos en la propuesta (útil para modelos ligeros).
    """
    auth_norm = normalize_authors(author) if author else None
    a = format_authors_for_filename(auth_norm, max_authors=3) if auth_norm and include_author else ''
    t = sanitize(str(title)) if title else ''
    s = sanitize(str(subtitle)) if subtitle and include_subtitle else ''
    ser = sanitize(str(series)) if series else ''
    ser_n = sanitize(str(series_num)) if series_num else ''

    if ext and not ext.startswith('.'):
        ext = '.' + ext

    # Formato estilo: Autor - Serie - N - Titulo. Subtitulo
    parts = []
    if a:
        parts.append(a)
    if ser and ser_n:
        parts.append(f"{ser} - {ser_n}")
    elif ser:
        parts.append(ser)
    
    title_part = t
    if s:
        title_part = f"{t}. {s}"
        
    if title_part:
        parts.append(title_part)
        
    if not parts:
        name = f"Unknown{ext}"
    else:
        name = " - ".join(parts) + ext

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

    # Extraer serie del titulo
    series = None
    series_num = None
    if title:
        title, series, series_num = extract_series_from_text(title)

    # normalize cases where possible
    try:
        title = remove_banned_phrases(title) if title else None
        title = normalize_title_case(title) if title else None
    except Exception:
        pass
    try:
        if series:
            series = normalize_title_case(series)
    except Exception:
        pass
    try:
        subtitle = remove_banned_phrases(subtitle) if subtitle else None
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
        
    # Extraer series del guessed title si recien lo asignamos y no habia serie
    if title and not series:
        title, series, series_num = extract_series_from_text(title)
        if series:
            series = normalize_title_case(series)
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
    if subtitle and (is_suspect_title(subtitle) or len(str(subtitle)) > 80 or subtitle_words >= 8):
        subtitle = None

    if title and author and title.lower().strip() == author.lower().strip():
        author = None

    return format_book_filename(title, author, subtitle, series, series_num, ext)


__all__ = ["format_book_filename", "filename_from_mapping_entry"]
