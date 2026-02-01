"""Inferencia de nombres usando modelo TF-IDF + kNN guardado en data/models.

Expone utilidades mínimas para cargar el modelo y generar propuestas
aprovechando los extractores existentes.
"""
from pathlib import Path
import pickle
import os
import contextlib

from renamer.convert import (
    _extract_text_from_docx,
    _extract_text_from_html,
    _extract_text_from_txt,
)
from renamer.metadata import extract_pdf_metadata

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except Exception:
    _HAS_FITZ = False

try:
    from PyPDF2 import PdfReader
    _HAS_PYPDF2 = True
except Exception:
    _HAS_PYPDF2 = False


MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
VEC_PATH = MODELS_DIR / "vectorizer.pkl"
KNN_PATH = MODELS_DIR / "knn.pkl"
PROPOSALS_PATH = MODELS_DIR / "proposals.pkl"


_MODEL_CACHE = {
    "vec": None,
    "knn": None,
    "props": None,
}


def load_model():
    """Carga perezosa del vectorizador, knn y lista de propuestas."""
    if _MODEL_CACHE["vec"] is not None:
        return _MODEL_CACHE["vec"], _MODEL_CACHE["knn"], _MODEL_CACHE["props"]
    if not (VEC_PATH.exists() and KNN_PATH.exists() and PROPOSALS_PATH.exists()):
        raise FileNotFoundError("Modelos no encontrados en data/models; ejecuta prototype_knn.py --build")
    with VEC_PATH.open("rb") as fh:
        vec = pickle.load(fh)
    with KNN_PATH.open("rb") as fh:
        knn = pickle.load(fh)
    with PROPOSALS_PATH.open("rb") as fh:
        props = pickle.load(fh)
    _MODEL_CACHE["vec"] = vec
    _MODEL_CACHE["knn"] = knn
    _MODEL_CACHE["props"] = props
    return vec, knn, props


def _extract_text_from_pdf(path: Path, max_pages: int = 4):
    parts = []
    if _HAS_FITZ:
        try:
            doc = fitz.open(str(path))
            pages = min(doc.page_count, max_pages)
            for i in range(pages):
                page = doc.load_page(i)
                txt = page.get_text().strip()
                if txt:
                    parts.append(txt)
            doc.close()
        except Exception:
            parts = []
    if not parts and _HAS_PYPDF2:
        try:
            with open(os.devnull, "w") as devnull:
                with contextlib.redirect_stderr(devnull):
                    reader = PdfReader(str(path))
            for page in reader.pages[:max_pages]:
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                if txt.strip():
                    parts.append(txt.strip())
        except Exception:
            parts = []
    return parts


def get_text_snippet(path: Path, max_chars: int = 2000):
    """Extrae un texto breve para consulta al modelo."""
    suffix = path.suffix.lower()
    parts = []
    if suffix == ".pdf":
        parts = _extract_text_from_pdf(path)
    elif suffix == ".docx":
        parts = _extract_text_from_docx(path)
    elif suffix in (".html", ".htm"):
        parts = _extract_text_from_html(path)
    elif suffix == ".txt":
        parts = _extract_text_from_txt(path)
    else:
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
            parts = [p.strip() for p in txt.split("\n\n") if p.strip()]
        except Exception:
            parts = []
    if not parts:
        return None
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def suggest_from_text(text: str, top: int = 3):
    """Devuelve [(distancia, propuesta), ...] usando kNN."""
    if not text:
        return []
    vec, knn, props = load_model()
    Xq = vec.transform([text])
    dists, idxs = knn.kneighbors(Xq, n_neighbors=top)
    dists = dists[0]
    idxs = idxs[0]
    out = []
    for dist, idx in zip(dists, idxs):
        try:
            prop = props[idx]
        except Exception:
            prop = None
        out.append((float(dist), prop))
    return out


def suggest_for_file(path: Path, top: int = 3):
    text = get_text_snippet(path)
    if not text:
        return []
    return suggest_from_text(text, top=top)