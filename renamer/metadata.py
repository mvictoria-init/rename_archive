import re
import zipfile
from pathlib import Path
from .utils import normalize_authors


def extract_pdf_metadata(path):
    try:
        from PyPDF2 import PdfReader
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
        try:
            z = zipfile.ZipFile(path)
            opf_path = None
            if 'META-INF/container.xml' in z.namelist():
                import xml.etree.ElementTree as ET
                cont = z.read('META-INF/container.xml')
                root = ET.fromstring(cont)
                ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
                rf = root.find('.//c:rootfile', ns)
                if rf is not None:
                    opf_path = rf.get('full-path')
            if not opf_path:
                for name in z.namelist():
                    if name.endswith('.opf'):
                        opf_path = name
                        break
            if opf_path:
                data = z.read(opf_path)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(data)
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
