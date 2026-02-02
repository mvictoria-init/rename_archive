"""
Prototipo: sugeridor TF-IDF + kNN para propuestas "Autor - Título".

Uso:
    python scripts\prototype_knn.py --dataset data/dataset.jsonl --build
    python scripts\prototype_knn.py --dataset data/dataset.jsonl --query "texto de ejemplo" --top 5
    python scripts\prototype_knn.py --dataset data/dataset.jsonl --interactive

Requisitos:
    Instalar `scikit-learn` si se quiere construir o consultar modelos.

Este script entrena un `TfidfVectorizer` y un `NearestNeighbors` y
guarda los artefactos en `data/models/` cuando se ejecuta con
`--build`.
"""
from __future__ import annotations
import argparse
import json
import os
import pickle
from pathlib import Path
from typing import List

DATA_MODELS_DIR = Path("data/models")


def check_dependencies() -> None:
    try:
        import sklearn  # noqa: F401
    except Exception:
        print("This prototype requires scikit-learn. Install with:")
        print("  pip install scikit-learn")
        raise SystemExit(1)


def load_dataset(path: Path) -> List[dict]:
    items = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def build_models(dataset_path: Path, save_dir: Path):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors
    import numpy as np

    items = load_dataset(dataset_path)
    texts = [it.get("text", "") for it in items]
    proposals = [it.get("proposal", "") for it in items]

    print(f"Loaded {len(texts)} dataset items.")
    vec = TfidfVectorizer(max_features=50000, ngram_range=(1,2))
    X = vec.fit_transform(texts)
    print("TF-IDF matrix shape:", X.shape)

    knn = NearestNeighbors(n_neighbors=10, metric="cosine", algorithm="brute")
    knn.fit(X)

    save_dir.mkdir(parents=True, exist_ok=True)
    with (save_dir / "vectorizer.pkl").open("wb") as fh:
        pickle.dump(vec, fh)
    with (save_dir / "knn.pkl").open("wb") as fh:
        pickle.dump(knn, fh)
    with (save_dir / "proposals.pkl").open("wb") as fh:
        pickle.dump(proposals, fh)

    print("Models saved to", save_dir)


def load_models(save_dir: Path):
    with (save_dir / "vectorizer.pkl").open("rb") as fh:
        vec = pickle.load(fh)
    with (save_dir / "knn.pkl").open("rb") as fh:
        knn = pickle.load(fh)
    with (save_dir / "proposals.pkl").open("rb") as fh:
        proposals = pickle.load(fh)
    return vec, knn, proposals


def query_text(vec, knn, proposals, text: str, top: int = 5):
    Xq = vec.transform([text])
    dists, idxs = knn.kneighbors(Xq, n_neighbors=top)
    dists = dists[0]
    idxs = idxs[0]
    results = []
    for dist, idx in zip(dists, idxs):
        results.append((float(dist), proposals[idx]))
    return results


def interactive_mode(dataset_path: Path, save_dir: Path):
    check_dependencies()
    if not (save_dir / "vectorizer.pkl").exists():
        print("Models not found. Build first with --build")
        raise SystemExit(1)
    vec, knn, proposals = load_models(save_dir)
    print("Interactive mode. Enter query text (empty to exit)")
    while True:
        try:
            q = input("Query> ")
        except EOFError:
            break
        q = q.strip()
        if not q:
            break
        results = query_text(vec, knn, proposals, q, top=5)
        for dist, prop in results:
            print(f"{dist:.4f}\t{prop}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.jsonl"))
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    if args.build:
        check_dependencies()
        build_models(args.dataset, DATA_MODELS_DIR)
        return

    if args.interactive:
        interactive_mode(args.dataset, DATA_MODELS_DIR)
        return

    if args.query:
        check_dependencies()
        if not DATA_MODELS_DIR.exists():
            print("Models not found. Run with --build first.")
            raise SystemExit(1)
        vec, knn, proposals = load_models(DATA_MODELS_DIR)
        results = query_text(vec, knn, proposals, args.query, top=args.top)
        for dist, prop in results:
            print(f"{dist:.4f}\t{prop}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
