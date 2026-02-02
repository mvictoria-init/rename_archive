"""
Extractores de metadatos para distintos formatos de libro.

Este módulo contiene funciones específicas para PDF, DOCX, EPUB y TXT
que intentan leer título y autor usando bibliotecas disponibles (PyMuPDF,
PyPDF2, python-docx, ebooklib) con fallbacks tolerantes y heurísticas de
decodificación cuando los metadatos son incompletos o inconsistentes.
"""

import re
import zipfile
from pathlib import Path
from .utils import normalize_authors


def extract_pdf_metadata(path):
    # Try PyMuPDF (fitz) first as it is generally more robust
    try:
        import fitz
        doc = fitz.open(path)
        meta = doc.metadata
        title = meta.get('title')
        author = meta.get('author')
        if not title or not author:
            # simple text extraction fallback for first page
            # often title is first line, author is second
             if doc.page_count > 0:
                p = doc[0]
                # get text blocks
                blocks = p.get_text("blocks")
                blocks.sort(key=lambda b: b[1]) # sort by vertical position
                lines = []
                for b in blocks:
                    # block text; b[4]
                    txt = b[4].strip()
                    if txt:
                        lines.append(txt)
                if not title and lines:
                    title = lines[0].split('\n')[0]
                if not author and len(lines) > 1:
                    # heuristic: look for "By X" or just second line
                    sec = lines[1].replace('\n', ' ')
                    m = re.search(r'(?:by|por)\s+([\w\s\.]+)', sec, flags=re.IGNORECASE)
                    if m:
                        author = m.group(1)
                    else:
                        author = sec
        doc.close()
        author = normalize_authors(author)
        title = title.strip() if title else title
        return (title, author)
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to PyPDF2
    try:
        from PyPDF2 import PdfReader
        # suppress noisy messages from PyPDF2 by redirecting stderr temporarily
        import os
        import contextlib
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                reader = PdfReader(path)
        info = reader.metadata
        title = None
        author = None
        if info:
            if isinstance(info, dict):
                title = info.get('/Title') or info.get('Title')
                author = info.get('/Author') or info.get('Author')
            else:
                title = getattr(info, 'title', None)
                author = getattr(info, 'author', None)
        # algunos objetos de PyPDF2 son IndirectObject; forzar a str si no son str
        if title is not None and not isinstance(title, str):
            try:
                title = str(title)
            except Exception:
                title = None
        if author is not None and not isinstance(author, str):
            try:
                author = str(author)
            except Exception:
                author = None
        # limpiar valores basura típicos de PyPDF2 (IndirectObject)
        if isinstance(title, str) and 'IndirectObject' in title:
            title = None
        if isinstance(author, str) and 'IndirectObject' in author:
            author = None
        author = normalize_authors(author)
        title = title.strip() if title and isinstance(title, str) else title
        if not title or not author:
            try:
                if len(reader.pages) > 0:
                    text = reader.pages[0].extract_text() or ''
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    if not title and lines:
                        title = lines[0]
                    if not author and len(lines) > 1:
                        second = lines[1]
                        m = re.search(r'by\s+(.+)', second, flags=re.IGNORECASE)
                        if m:
                            author = m.group(1)
                        else:
                            if re.match(r'^[\w\-\., ]+$', second):
                                author = second
            except Exception:
                pass
        return (title, author)
    except Exception:
        return (None, None)


def extract_docx_metadata(path):
    try:
        from docx import Document
        doc = Document(path)
        props = doc.core_properties
        title = props.title or None
        author = props.author or None
        author = normalize_authors(author)
        return (title, author)
    except Exception:
        return (None, None)


def extract_epub_metadata(path):
    try:
        from ebooklib import epub
        import contextlib, os
        # suppress noisy stderr from underlying parsers
        with open(os.devnull, 'w') as devnull:
            with contextlib.redirect_stderr(devnull):
                book = epub.read_epub(path)
        titles = book.get_metadata('DC', 'title')
        creators = book.get_metadata('DC', 'creator')
        title = None
        if titles:
            title = titles[0][0]
        author = None
        if creators:
            auths = [c[0] for c in creators if c and c[0]]
            author = normalize_authors(auths)
        return (title, author)
    except Exception:
        # Fallback: attempt tolerant ZIP/OPF parsing and liberal decoding
        try:
            z = zipfile.ZipFile(path)
            opf_path = None
            if 'META-INF/container.xml' in z.namelist():
                import xml.etree.ElementTree as ET
                try:
                    cont = z.read('META-INF/container.xml')
                    # try utf-8, else latin-1
                    try:
                        cont_s = cont.decode('utf-8')
                    except Exception:
                        cont_s = cont.decode('latin-1', errors='replace')
                    root = ET.fromstring(cont_s)
                    ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
                    rf = root.find('.//c:rootfile', ns)
                    if rf is not None:
                        opf_path = rf.get('full-path')
                except Exception:
                    opf_path = None
            if not opf_path:
                for name in z.namelist():
                    if name.endswith('.opf'):
                        opf_path = name
                        break
            if opf_path:
                data = z.read(opf_path)
                import xml.etree.ElementTree as ET
                # decode with fallback
                try:
                    data_s = data.decode('utf-8')
                except Exception:
                    data_s = data.decode('latin-1', errors='replace')
                root = ET.fromstring(data_s)
                title = None
                author = None
                for elem in root.iter():
                    tag = elem.tag.lower()
                    if tag.endswith('title') and not title:
                        title = elem.text
                    if tag.endswith('creator'):
                        if not author:
                            author = elem.text
                        else:
                            author = author + ', ' + (elem.text or '')
                author = normalize_authors(author)
                return (title, author)
        except Exception:
            return (None, None)
    return (None, None)


def extract_txt_metadata(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read(4000)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            title = None
            author = None
            for ln in lines[:10]:
                m_t = re.match(r'Title\s*[:\-]\s*(.+)', ln, flags=re.IGNORECASE)
                m_a = re.match(r'Author\s*[:\-]\s*(.+)', ln, flags=re.IGNORECASE)
                if m_t and not title:
                    title = m_t.group(1).strip()
                if m_a and not author:
                    author = m_a.group(1).strip()
            if not title and lines:
                title = lines[0]
            if not author and len(lines) > 1:
                second = lines[1]
                m = re.search(r'by\s+(.+)', second, flags=re.IGNORECASE)
                if m:
                    author = m.group(1).strip()
            author = normalize_authors(author)
            return (title, author)
    except Exception:
        return (None, None)


def extract_metadata(path: Path):
    ext = path.suffix.lower()
    if ext == '.pdf':
        return extract_pdf_metadata(str(path))
    if ext == '.docx':
        return extract_docx_metadata(str(path))
    if ext == '.epub':
        return extract_epub_metadata(str(path))
    if ext in ('.txt', '.md'):
        return extract_txt_metadata(str(path))
    return (None, None)
