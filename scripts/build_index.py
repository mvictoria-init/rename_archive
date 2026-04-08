"""Construye un índice vectorial local (hnswlib) con embeddings de libros.

- Extrae metadatos usando `renamer.metadata.extract_metadata`.
- Extrae texto (PDF/DOCX/EPUB/TXT) con métodos tolerantes.
- Chunkea el texto y crea embeddings con `sentence-transformers`.
- Indexa vectores con `hnswlib` y guarda mapping JSON.

Uso sugerido:
  python scripts/build_index.py --root "D:/ruta/a/mis/libros" --out "models/index"

Requiere (recomendado):
  pip install -r scripts/requirements_models.txt
"""

import os
import argparse
import json
import hashlib
from pathlib import Path
import sys
import random

# Asegurar que el paquete renamer (ubicado en ../) esté en sys.path
HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from renamer.metadata import extract_metadata
from renamer.utils import format_authors_for_filename, normalize_authors, sanitize, normalize_author_case, normalize_title_case


def file_sha256(path, block_size=65536):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(block_size), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_text_simple(path: str, max_pages: int = None) -> str:
    """Extrae texto plano de formatos comunes; tolerante a fallos.

    max_pages: si se especifica, limita la extracción de PDFs/EPUBs
    a las primeras N páginas/items.
    """
    ext = Path(path).suffix.lower()
    try:
        if ext == '.pdf':
            try:
                import fitz, contextlib, os
                parts = []
                try:
                    with open(os.devnull, 'w') as devnull:
                        with contextlib.redirect_stderr(devnull):
                            doc = fitz.open(path)
                            try:
                                page_count = doc.page_count
                                limit = page_count if not max_pages else min(page_count, int(max_pages))
                                for pno in range(limit):
                                    try:
                                        parts.append(doc[pno].get_text('text') or '')
                                    except Exception:
                                        pass
                            finally:
                                try:
                                    doc.close()
                                except Exception:
                                    pass
                except Exception:
                    return ''
                return '\n'.join(parts)
            except Exception:
                return ''
        if ext == '.docx':
            try:
                from docx import Document
                doc = Document(path)
                paras = [p.text for p in doc.paragraphs if p.text]
                return '\n'.join(paras)
            except Exception:
                return ''
        if ext == '.epub':
            try:
                from ebooklib import epub
                from ebooklib import ITEM_DOCUMENT
                book = epub.read_epub(path)
                texts = []
                count = 0
                for item in book.get_items():
                    try:
                        if item.get_type() != ITEM_DOCUMENT:
                            continue
                        raw = item.get_content()
                        try:
                            s = raw.decode('utf-8')
                        except Exception:
                            s = raw.decode('latin-1', errors='replace')
                        texts.append(s)
                        count += 1
                        if max_pages and count >= int(max_pages):
                            break
                    except Exception:
                        pass
                return '\n'.join(texts)
            except Exception:
                return ''
        # fallback for plain text and other readable files
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                return fh.read()
        except Exception:
            return ''
    except Exception:
        return ''


def _worker_extract(path, max_pages, q):
    try:
        t = extract_text_simple(path, max_pages=max_pages)
    except Exception:
        t = ''
    try:
        q.put(t)
    except Exception:
        pass


def extract_text_with_timeout(path, timeout=10, max_pages=None):
    """Extrae texto usando un proceso separado y lo termina si excede `timeout` segundos.
    Devuelve `None` si hubo timeout, cadena (posiblemente vacía) si terminó correctamente.
    """
    from multiprocessing import Process, Queue
    q = Queue()
    p = Process(target=_worker_extract, args=(path, max_pages, q))
    p.start()
    p.join(timeout)
    if p.is_alive():
        try:
            p.terminate()
        except Exception:
            pass
        p.join()
        return None
    try:
        if not q.empty():
            return q.get_nowait()
    except Exception:
        return ''
    return ''


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200):
    if not text:
        return []
    L = len(text)
    chunks = []
    start = 0
    while start < L:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append((start, min(end, L), chunk))
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


def collect_chunks(root: str, chunk_size=1000, overlap=200, exts=('.pdf', '.docx', '.epub', '.txt', '.md'), sample_size: int = None, max_pages: int = None, per_file_timeout: int = 10):
    files = []
    for dp, dns, fns in os.walk(root):
        # skip internal state directories
        if '.state' in Path(dp).parts:
            continue
        for fn in fns:
            if fn.lower().endswith(exts):
                files.append(os.path.join(dp, fn))

    if not files:
        print('No se encontraron archivos en', root, flush=True)
        return []

    total_files = len(files)
    if sample_size and total_files > sample_size:
        sampled = random.sample(files, sample_size)
        print(f'Se muestrearon aleatoriamente {len(sampled)} archivos (de {total_files})', flush=True)
    else:
        sampled = files
        print(f'Procesando {len(sampled)} archivos (de {total_files})', flush=True)

    chunks = []
    seen = set()
    for idx, p in enumerate(sampled, start=1):
        print(f'[{idx}/{len(sampled)}] Procesando: {p}', flush=True)
        try:
            fh = file_sha256(p)
        except Exception:
            fh = None
        key = fh if fh else os.path.abspath(p)
        if key in seen:
            print('  - Archivo duplicado (sha256) saltado:', p, flush=True)
            continue
        seen.add(key)
        title, author, subtitle = extract_metadata(Path(p))
        # Normalizar capitalización según reglas: autores (Nombre Apellido), títulos (solo primera palabra en mayúscula)
        try:
            author = normalize_author_case(author) if author else None
        except Exception:
            pass
        try:
            title = normalize_title_case(title) if title else None
        except Exception:
            pass
        try:
            subtitle = normalize_title_case(subtitle) if subtitle else None
        except Exception:
            pass

        # Extraer texto con timeout y límite de páginas
        try:
            text = extract_text_with_timeout(p, timeout=per_file_timeout, max_pages=max_pages)
            if text is None:
                print(f'  - Timeout (> {per_file_timeout}s) extrayendo {p}; saltando', flush=True)
                continue
        except Exception as e:
            print('  - Error extrayendo', p, ':', e, flush=True)
            continue

        if not text:
            # still keep a placeholder entry (use filename as context)
            chunks.append({'file': p, 'sha256': fh, 'title': title, 'author': author, 'subtitle': subtitle, 'chunk_idx': 0, 'start': 0, 'end': 0, 'text': ''})
            continue
        cks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not cks:
            chunks.append({'file': p, 'sha256': fh, 'title': title, 'author': author, 'subtitle': subtitle, 'chunk_idx': 0, 'start': 0, 'end': 0, 'text': text[:chunk_size]})
            continue
        for jdx, (s, e, chunk) in enumerate(cks):
            chunks.append({'file': p, 'sha256': fh, 'title': title, 'author': author, 'subtitle': subtitle, 'chunk_idx': jdx, 'start': s, 'end': e, 'text': chunk})
    return chunks


def save_json(obj, path):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', '-r', default='D:\\Mv\\Documentos\\Libros\\-Todos los libros por guardar', help='Carpeta raíz a escanear (contiene libros)')
    p.add_argument('--out', '-o', default=os.path.join(HERE, 'models'), help='Carpeta de salida para índice y mapping')
    p.add_argument('--model', default='all-MiniLM-L6-v2', help='Modelo sentence-transformers a usar')
    p.add_argument('--chunk_size', type=int, default=1000)
    p.add_argument('--overlap', type=int, default=200)
    p.add_argument('--sample-size', type=int, default=800, help='Número máximo de archivos a muestrear aleatoriamente')
    p.add_argument('--max-pages', type=int, default=5, help='Máximo de páginas a extraer por PDF/EPUB')
    p.add_argument('--per-file-timeout', type=int, default=10, help='Timeout en segundos por archivo')
    args = p.parse_args()

    root = args.root
    out = args.out
    os.makedirs(out, exist_ok=True)

    print('Recolectando chunks desde', root, flush=True)
    chunks = collect_chunks(root, chunk_size=args.chunk_size, overlap=args.overlap, sample_size=args.sample_size, max_pages=args.max_pages, per_file_timeout=args.per_file_timeout)
    print('Chunks recolectados:', len(chunks), flush=True)
    if not chunks:
        print('No se encontraron fragments para indexar. Salir.', flush=True)
        return

    # cargar modelo y crear embeddings (importar aquí para evitar requerir deps solo al importar el script)
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except Exception as e:
        print('Falta `sentence-transformers` o `numpy`:', e, flush=True)
        print('Instale con: pip install -r scripts/requirements_models.txt', flush=True)
        return

    model = SentenceTransformer(args.model)

    # preparar textos (metadata + chunk)
    texts = []
    mapping = []
    for c in chunks:
        parts = []
        if c.get('title'):
            parts.append(str(c['title']))
        if c.get('author'):
            parts.append(str(c['author']))
        if c.get('subtitle'):
            parts.append(str(c['subtitle']))
        parts.append(os.path.basename(c['file']))
        prefix = ' — '.join([p for p in parts if p])
        combined = prefix + '\n\n' + (c.get('text') or '')
        texts.append(combined)
        mapping.append({'file': c['file'], 'sha256': c['sha256'], 'title': c['title'], 'author': c['author'], 'subtitle': c['subtitle'], 'chunk_idx': c['chunk_idx'], 'start': c['start'], 'end': c['end']})

    batch = 32
    embs = []
    for i in range(0, len(texts), batch):
        batch_texts = texts[i:i+batch]
        emb = model.encode(batch_texts, show_progress_bar=False, convert_to_numpy=True)
        embs.append(emb)
    import numpy as _np
    X = _np.vstack(embs)
    dim = X.shape[1]
    print('Embeddings shape:', X.shape, flush=True)

    # Numpy-backed index: guardamos los embeddings en disco (.npy)
    # Ventaja: no requiere compilar extensiones nativas en Windows.
    index_path = os.path.join(out, 'embeddings.npy')
    mapping_path = os.path.join(out, 'mapping.json')
    meta_path = os.path.join(out, 'index_meta.json')

    try:
        # guardar embeddings como float32 para ahorrar espacio
        _np.save(index_path, X.astype('float32'))
    except Exception as e:
        print('Error guardando embeddings:', e, flush=True)
        return

    save_json({'model': args.model, 'created_at': __import__('datetime').datetime.utcnow().isoformat(), 'num_items': int(X.shape[0]), 'backend': 'npy', 'index_path': os.path.basename(index_path)}, meta_path)
    save_json(mapping, mapping_path)
    print('Embeddings guardados en', index_path, 'Items:', X.shape[0], flush=True)


if __name__ == '__main__':
    main()
