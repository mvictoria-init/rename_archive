"""Consulta el índice local y propone nombres para un archivo.

Uso:
  python scripts/query_suggester.py --index models --file "ruta/al/libro.pdf"

El script carga `models/index.bin` y `models/mapping.json`, genera el embedding
para el archivo objetivo y devuelve los vecinos más cercanos para construir
una propuesta basada en metadatos similares.
"""

import os
import argparse
import json

# ensure renamer package is importable
import sys
HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from renamer.metadata import extract_metadata
from renamer.utils import format_authors_for_filename, normalize_authors, sanitize, normalize_author_case, normalize_title_case
from pathlib import Path


def extract_text_simple(path: str) -> str:
    from pathlib import Path
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
                                for p in range(doc.page_count):
                                    try:
                                        parts.append(doc[p].get_text('text') or '')
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
                book = epub.read_epub(path)
                texts = []
                for item in book.get_items():
                    try:
                        raw = item.get_content()
                        try:
                            s = raw.decode('utf-8')
                        except Exception:
                            s = raw.decode('latin-1', errors='replace')
                        texts.append(s)
                    except Exception:
                        pass
                return '\n'.join(texts)
            except Exception:
                return ''
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                return fh.read()
        except Exception:
            return ''
    except Exception:
        return ''


def suggest(file_path: str, index_dir: str, model_name: str = 'all-MiniLM-L6-v2', top_k: int = 5):
    mapping_path = os.path.join(index_dir, 'mapping.json')
    meta_path = os.path.join(index_dir, 'index_meta.json')
    if not os.path.exists(mapping_path) or not os.path.exists(meta_path):
        raise FileNotFoundError('Index or mapping/meta not found in ' + str(index_dir))
    mapping = json.load(open(mapping_path, 'r', encoding='utf-8'))
    # detect backend from metadata if present; default to numpy-backed embeddings
    backend = 'npy'
    index_file = os.path.join(index_dir, 'embeddings.npy')
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, 'r', encoding='utf-8'))
            backend = meta.get('backend', backend)
            if meta.get('index_path'):
                index_file = os.path.join(index_dir, meta.get('index_path'))
        except Exception:
            pass

    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except Exception as e:
        raise RuntimeError('Missing sentence-transformers or numpy: ' + str(e))

    model = SentenceTransformer(model_name)

    title, author, subtitle = extract_metadata(Path(file_path))
    # Normalizar metadatos antes de construir la consulta
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
    text = extract_text_simple(file_path)
    parts = []
    if title: parts.append(str(title))
    if author: parts.append(str(author))
    if subtitle: parts.append(str(subtitle))
    parts.append(os.path.basename(file_path))
    query = '\n\n'.join([' — '.join([p for p in parts if p]), (text or '')[:2000]])

    # Query using the configured backend
    labels = []
    distances = []
    if backend == 'hnswlib':
        try:
            import hnswlib
        except Exception as e:
            raise RuntimeError('Index backend is hnswlib but hnswlib is not installed: ' + str(e))
        p = hnswlib.Index(space='cosine', dim=model.get_sentence_embedding_dimension())
        p.load_index(index_file)
        p.set_ef(50)
        q_emb = model.encode([query], convert_to_numpy=True)
        labels, distances = p.knn_query(q_emb, k=top_k)
        labels = labels[0]
        distances = distances[0]
    elif backend == 'annoy':
        try:
            from annoy import AnnoyIndex
        except Exception as e:
            raise RuntimeError('Index backend is annoy but annoy is not installed: ' + str(e))
        dim = model.get_sentence_embedding_dimension()
        a = AnnoyIndex(dim, 'angular')
        a.load(index_file)
        q_emb = model.encode([query], convert_to_numpy=True)[0]
        try:
            labels, distances = a.get_nns_by_vector(q_emb.tolist(), top_k, include_distances=True)
        except TypeError:
            # older Annoy versions may not support include_distances
            labels = a.get_nns_by_vector(q_emb.tolist(), top_k)
            distances = [None] * len(labels)
    elif backend == 'npy' or backend not in ('hnswlib', 'annoy'):
        # numpy-backed index: load embeddings and compute cosine similarity
        emb_file = index_file
        try:
            import numpy as _np
            X = _np.load(emb_file, mmap_mode='r')
        except Exception as e:
            raise RuntimeError('No se pudo cargar embeddings numpy: ' + str(e))
        q_emb = model.encode([query], convert_to_numpy=True)[0]
        try:
            import numpy as _np
            # compute cosine similarities
            q_norm = _np.linalg.norm(q_emb) + 1e-12
            X_norms = _np.linalg.norm(X, axis=1) + 1e-12
            sims = (X @ q_emb) / (X_norms * q_norm)
            # top k
            idxs = _np.argsort(-sims)[:top_k]
            labels = idxs.tolist()
            distances = (1.0 - sims[idxs]).tolist()
        except Exception as e:
            raise RuntimeError('Error al calcular similitudes: ' + str(e))
    else:
        raise RuntimeError('Unsupported index backend: ' + str(backend))

    neighbors = []
    for lab, dist in zip(labels, distances):
        try:
            m = mapping[int(lab)]
        except Exception:
            m = None
        if m:
            dval = float(dist) if dist is not None else None
            neighbors.append({'file': m.get('file'), 'title': m.get('title'), 'author': m.get('author'), 'subtitle': m.get('subtitle'), 'dist': dval})

    # aggregate neighbors for a proposed name: prefer the most common (title, author)
    from collections import Counter
    title_counts = Counter([n['title'] for n in neighbors if n.get('title')])
    author_counts = Counter([n['author'] for n in neighbors if n.get('author')])
    best_title = title_counts.most_common(1)[0][0] if title_counts else None
    best_author = author_counts.most_common(1)[0][0] if author_counts else None

    ext = os.path.splitext(file_path)[1]
    if best_author and best_title:
        a = format_authors_for_filename(normalize_authors(best_author), max_authors=3)
        proposed = f"{a} - {sanitize(best_title)}{ext}" if a else f"{sanitize(best_title)}{ext}"
    elif best_title:
        proposed = f"{sanitize(best_title)}{ext}"
    elif best_author:
        a = format_authors_for_filename(normalize_authors(best_author), max_authors=3)
        proposed = f"{a}{ext}"
    else:
        proposed = os.path.basename(file_path)

    return {'proposed': proposed, 'neighbors': neighbors}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--index', '-i', default='models', help='Carpeta que contiene index.bin y mapping.json')
    p.add_argument('--file', '-f', required=True, help='Archivo objetivo para generar sugerencia')
    p.add_argument('--model', default='all-MiniLM-L6-v2')
    p.add_argument('--k', type=int, default=5)
    args = p.parse_args()
    out = suggest(args.file, args.index, model_name=args.model, top_k=args.k)
    print('Propuesta:', out['proposed'])
    print('\nVecinos:')
    for n in out['neighbors']:
        print(n)
