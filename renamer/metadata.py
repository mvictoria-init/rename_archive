import re
import zipfile
from pathlib import Path
from .utils import normalize_authors, is_suspect_title, is_suspicious_author, guess_title_author_from_filename


"""Extracción flexible de metadatos (título, autor) para distintos formatos.

Cada extractor intenta múltiples estrategias (librerías externas y
heurísticas) y devuelve una tupla (title, author). Las funciones están
diseñadas para ser tolerantes: si falla un método, prueban otra alternativa.
"""


def extract_pdf_metadata(path):
    """Extrae título y autor de un PDF.

    Qué hace: intenta PyMuPDF (fitz) primero; si falla usa PyPDF2 y,
    en última instancia, heurísticas sobre el texto de la primera página.
    Por qué: los PDF contienen metadatos en distintos formatos y esta
    función unifica la extracción de forma tolerante.
    """
    # Try PyMuPDF (fitz) first as it is generally more robust
    try:
        import fitz
        doc = fitz.open(path)
        meta = doc.metadata
        title = meta.get('title')
        author = meta.get('author')
        subtitle = None

        # Solo inspeccionar páginas si los metadatos base están vacíos o sospechosos (Optimization para colecciones grandes)
        if (not title or is_suspect_title(title) or not author or is_suspicious_author(author)) and doc.page_count > 0:
            try:
                spans = []
                idx = 0
                # Ampliado a 10 páginas para capturar bien los títulos largos o portadas desplazadas
                pages_to_check = min(10, doc.page_count)
                for pno in range(pages_to_check):
                    page = doc[pno]
                    try:
                        d = page.get_text('dict')
                    except Exception:
                        # fallback to blocks/text
                        blocks = page.get_text('blocks')
                        for b in blocks:
                            txt = b[4].strip()
                            if txt:
                                spans.append({'page': pno, 'y': b[1], 'text': txt, 'size': None, 'idx': idx})
                                idx += 1
                        continue

                    for block in d.get('blocks', []):
                        if block.get('type') != 0:
                            continue
                        for line in block.get('lines', []):
                            y = line.get('bbox', [0, 0, 0, 0])[1]
                            for span in line.get('spans', []):
                                text = span.get('text', '').strip()
                                if not text:
                                    continue
                                size = span.get('size', 0) or 0
                                font = span.get('font', '')
                                color = span.get('color', None)
                                spans.append({'page': pno, 'y': y, 'text': text, 'size': size, 'font': font, 'color': color, 'idx': idx})
                                idx += 1

                # group spans into lines per page preserving order
                page_lines = {}
                for s in spans:
                    key = (s['page'], int(round(s['y'])))
                    if key not in page_lines:
                        page_lines[key] = {'page': s['page'], 'y': s['y'], 'spans': []}
                    page_lines[key]['spans'].append(s)

                # build ordered lines per page
                lines_by_page = {}
                for (pno, y), data in sorted(page_lines.items(), key=lambda kv: (kv[0][0], kv[1]['y'])):
                    spans_list = sorted(data['spans'], key=lambda x: x['idx'])
                    text = ' '.join([sp['text'] for sp in spans_list]).strip()
                    max_size = max([sp.get('size') or 0 for sp in spans_list]) if spans_list else 0
                    lines_by_page.setdefault(pno, []).append({'y': data['y'], 'text': text, 'size': max_size})

                # Unificar todas las líneas de todas las páginas para encontrar el máximo global
                all_lines = []
                for pno, lns in lines_by_page.items():
                    if pno >= 10: break
                    for l in lns:
                        # ignorar lineas muy cortas o pura putuacion/números
                        if l.get('size') and len(l.get('text', '').strip()) > 3:
                            all_lines.append(l)

                found_title = None
                found_author = None
                found_sub = None
                
                if all_lines:
                    # Encontrar el tamaño máximo global
                    max_size = max([l['size'] for l in all_lines])
                    
                    # Titulo: El texto de tamano maximo (umbral 95% para ser mas selectivo)
                    title_candidates = [l for l in all_lines if l['size'] >= max_size * 0.95]
                    if title_candidates:
                        primary = sorted(title_candidates, key=lambda z: (z.get('size', 0), len(z.get('text', ''))), reverse=True)[0]
                        found_title = primary.get('text')
                        primary_size = primary.get('size', max_size)
                        
                        # Quitar el titulo de las lineas disponibles
                        all_lines = [l for l in all_lines if l != primary]
                        
                    # Autor: El segundo tamaño más grande (o basado en keywords)
                    if all_lines:
                        # Buscar por keyword 'por' o 'by'
                        for l in all_lines[:30]: # buscar en las primeras lineas
                            m = re.search(r'(?:by|por)\s+(.+)', l['text'], flags=re.IGNORECASE)
                            if m and len(m.group(1).split()) <= 6:
                                found_author = m.group(1)
                                break
                        
                        if not found_author:
                            # Tomar el segundo tamaño más grande global
                            # Solo aceptar si parece un nombre propio (pocas palabras sin artículos)
                            second_max_size = max([l['size'] for l in all_lines])
                            author_cands = [l for l in all_lines if l['size'] >= second_max_size * 0.8]
                            author_cands = sorted(author_cands, key=lambda z: z.get('size', 0), reverse=True)
                            _stopwords_author = {'el', 'la', 'los', 'las', 'un', 'una', 'como',
                                                  'para', 'por', 'que', 'del', 'de', 'con', 'en',
                                                  'the', 'a', 'an', 'and', 'of', 'to', 'in'}
                            for ac in author_cands:
                                txt = ac.get('text', '')
                                words = txt.split()
                                # Nombre propio: 1-5 palabras, primera palabra en mayuscula,
                                # ninguna palabra es stopword tipica de subtitulos
                                if (1 <= len(words) <= 5
                                        and words[0][:1].isupper()
                                        and not any(w.lower() in _stopwords_author for w in words)
                                        and not is_suspect_title(txt)):
                                    found_author = txt
                                    break

                if found_title and not title:
                    # ignore obviously bad title candidates
                    if not is_suspect_title(found_title):
                        title = found_title
                    else:
                        found_title = None
                if found_author and not author:
                    author = found_author
                if found_sub:
                    subtitle = found_sub
            except Exception:
                pass

        doc.close()
        # normalize and sanity-check
        # if title appears suspect (credits, translators, repeated text), fallback to filename guess
        if title and is_suspect_title(title):
            title = None
        if subtitle and is_suspect_title(subtitle):
            subtitle = None
        # try to recover from filename if metadata seems unreliable
        if not title or (author and is_suspicious_author(author)):
            try:
                gtitle, gauthor = guess_title_author_from_filename(path)
                if (not title or is_suspect_title(title)) and gtitle:
                    title = gtitle
                if (not author or is_suspicious_author(author)) and gauthor:
                    author = gauthor
            except Exception:
                pass

        author = normalize_authors(author)
        title = title.strip() if title else title
        if subtitle:
            subtitle = subtitle.strip()
        return (title, author, subtitle)
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
        return (title, author, None)
    except Exception:
        return (None, None, None)


def extract_docx_metadata(path):
    """Extrae título y autor de un documento .docx.

    Qué hace: usa python-docx para leer propiedades del documento
    (core_properties). Por qué: muchos .docx incluyen metadatos útiles.
    """
    try:
        from docx import Document
        doc = Document(path)
        props = doc.core_properties
        title = props.title or None
        author = props.author or None
        author = normalize_authors(author)
        # Try to obtain a subtitle from first paragraphs if not present
        subtitle = None
        try:
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            if not title and paras:
                title = paras[0]
                if len(paras) > 1:
                    cand = paras[1]
                    if 3 < len(cand.split()) < 12:
                        subtitle = cand
        except Exception:
            pass
        return (title, author, subtitle)
    except Exception:
        return (None, None, None)


def extract_epub_metadata(path):
    """Extrae título y autor de un EPUB.

    Qué hace: intenta usar ebooklib; si falla, abre el ZIP y busca
    el OPF/metadata de forma tolerante. Por qué: soportar EPUBs creados
    con distintas herramientas y codificaciones.
    """
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
        return (title, author, None)
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
                return (title, author, None)
        except Exception:
            return (None, None, None)
        return (None, None, None)


def extract_txt_metadata(path):
    """Extrae título/autor de archivos de texto plano mediante heurísticas.

    Qué hace: lee las primeras líneas buscando patrones "Title:" o "Author:";
    por qué: muchos textos simples incluyen cabeceras con metadatos.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read(4000)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            title = None
            author = None
            subtitle = None
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
            # attempt subtitle detection: if second line is short and not an author, treat as subtitle
            if len(lines) > 1:
                second = lines[1]
                if not re.search(r'author\s*[:\-]|by\s+', second, flags=re.IGNORECASE):
                    if 2 < len(second.split()) < 12:
                        subtitle = second
            author = normalize_authors(author)
            return (title, author, subtitle)
    except Exception:
        return (None, None, None)


def extract_metadata(path: Path):
    """Selector de extractor por extensión.

    Devuelve (title, author, subtitle) usando el extractor apropiado según la extensión.
    """
    ext = path.suffix.lower()
    if ext == '.pdf':
        return extract_pdf_metadata(str(path))
    if ext == '.docx':
        return extract_docx_metadata(str(path))
    if ext == '.epub':
        return extract_epub_metadata(str(path))
    if ext in ('.txt', '.md'):
        return extract_txt_metadata(str(path))
    return (None, None, None)
