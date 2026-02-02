"""
Módulo de sugerencias: heurísticas y asistente basado en KNN/Tf-idf.

Proporciona una función de alto nivel `suggest_for_file` que intenta
generar un nombre propuesto del tipo "Autor - Título" para un archivo
de libro. El flujo de decisión es:
1. Extraer metadatos embebidos (si están disponibles).
2. Aplicar heurísticas sobre el nombre de fichero.
3. (Opcional) Consultar modelos TF-IDF + kNN entrenados para recuperar
    propuestas similares desde un dataset previo.

El resto del archivo inicializa y carga los modelos serializados desde
`data/models/` si están presentes.
"""

import os
import re
import pickle
import logging
from pathlib import Path
from .metadata import extract_metadata
from .utils import normalize_authors, format_authors_for_filename, sanitize, guess_title_author_from_filename

# Optional ML dependencies
try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    HAS_ML = True
except ImportError:
    HAS_ML = False

MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
VEC_PATH = MODEL_DIR / "vectorizer.pkl"
KNN_PATH = MODEL_DIR / "knn.pkl"
PROPS_PATH = MODEL_DIR / "proposals.pkl"

_models_loaded = False
_vec = None
_knn = None
_proposals = None

def load_models():
    global _models_loaded, _vec, _knn, _proposals
    if _models_loaded:
        return True
    if not HAS_ML:
        return False
    if not (VEC_PATH.exists() and KNN_PATH.exists() and PROPS_PATH.exists()):
        return False
    try:
        with VEC_PATH.open("rb") as f:
            _vec = pickle.load(f)
        with KNN_PATH.open("rb") as f:
            _knn = pickle.load(f)
        with PROPS_PATH.open("rb") as f:
            _proposals = pickle.load(f)
        _models_loaded = True
        return True
    except Exception as e:
        print(f"Error loading models: {e}")
        return False

def suggest_for_file(filepath: str | Path):
        """
        Devuelve una tupla (propuesta_nombre, title, author) para `filepath`.

        Estrategia:
        - Intenta usar metadatos internos (PDF/DOCX/EPUB/TXT).
        - Si faltan metadatos, aplica heurísticas sobre el nombre de archivo.
        - Si los modelos ML están disponibles y la similitud es alta, usa la
            propuesta recuperada por el KNN.

        Retorna: `(proposed_filename, title_or_None, author_or_None)`.
        Si no hay sugerencia, devuelve el nombre actual y `None` para los
        campos de título/autor.
        """
    path = Path(filepath)
    ext = path.suffix
    
    # 1. Metadata check
    title, author = extract_metadata(path)
    
    # 2. Heuristics from filename (often more reliable than internal metadata)
    h_title, h_author = guess_title_author_from_filename(path.name)
    
    # Decide between metadata and heuristics
    # If metadata Author looks like a real name (not "Microsoft Word" etc) prefer it
    # But if heuristic author is present and metadata is "Unknown", use heuristic
    
    final_title = title or h_title
    final_author = author or h_author

    # 3. ML / KNN check (if enabled and models exist)
    # We strip common prefixes to get cleaner text for query
    if HAS_ML and load_models():
        try:
            # simple text representation: just the cleaned filename for now
            # In a real app, we might want to extract text content, but that's slow
            query_text = path.stem + " " + str(final_title or "") + " " + str(final_author or "")
            xq = _vec.transform([query_text])
            dists, idxs = _knn.kneighbors(xq, n_neighbors=1)
            dist = dists[0][0]
            if dist < 0.3: # Threshold for similarity
                idx = idxs[0][0]
                best_proposal = _proposals[idx]
                if best_proposal:
                    # try to parse the proposal back into author/title
                    # assuming "Author - Title" format
                    parts = best_proposal.split(' - ', 1)
                    if len(parts) == 2:
                        return f"{best_proposal}{ext}", parts[1], parts[0]
                    return f"{best_proposal}{ext}", None, None
        except Exception:
            pass

    # Fallback construction
    t = sanitize(final_title) if final_title else ''
    a = format_authors_for_filename(normalize_authors(final_author), max_authors=3) if final_author else ''

    if a and t:
        new_name = f"{a} - {t}{ext}"
    elif t:
        new_name = f"{t}{ext}"
    elif a:
        new_name = f"{a}{ext}"
    else:
        new_name = path.name

    return sanitize(new_name), final_title, final_author
