"""Aplica el modelo ligero para generar nombres usando `name_selector.joblib`.

Si no existe modelo, el script sugiere entrenarlo con `train_name_selector.py`.
"""
import os
import sys
import json
import argparse

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import joblib
except Exception:
    print('Falta joblib (pip install joblib)')
    sys.exit(1)

from renamer.namer import format_book_filename


def load_mapping(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def featurize(entry):
    title = (entry.get('title') or '')
    subtitle = (entry.get('subtitle') or '')
    author = (entry.get('author') or '')
    fname = os.path.splitext(os.path.basename(entry.get('file') or ''))[0]
    ext = os.path.splitext(entry.get('file') or '')[1].lower()

    def cap_ratio(s):
        words = s.split()
        if not words:
            return 0.0
        up = sum(1 for w in words if w and w[0].isupper())
        return up / len(words)

    feats = [
        len(title),
        len(title.split()),
        cap_ratio(title),
        1 if subtitle else 0,
        len(subtitle.split()),
        1 if author else 0,
        author.count(',') + author.count(';'),
        1 if '-' in fname else 0,
        len(fname.split()),
        1 if ext == '.pdf' else 0,
        1 if ext == '.txt' else 0,
        1 if ext == '.epub' else 0,
        1 if ext == '.docx' else 0,
    ]
    return feats


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mapping', '-m', default=os.path.join(HERE, 'models', 'mapping.json'))
    p.add_argument('--model', default=os.path.join(HERE, 'models', 'name_selector.joblib'))
    p.add_argument('--out', '-o', default=os.path.join(HERE, 'models', 'proposals_model.json'))
    args = p.parse_args()

    if not os.path.exists(args.model):
        print('Modelo no encontrado:', args.model)
        print('Entrene uno con: python scripts/train_name_selector.py')
        sys.exit(1)

    model = joblib.load(args.model)
    mapping = load_mapping(args.mapping)

    proposals = []
    for e in mapping:
        feats = featurize(e)
        inc_a = bool(model['author'].predict([feats])[0])
        inc_s = bool(model['subtitle'].predict([feats])[0])
        path = e.get('file') or ''
        ext = os.path.splitext(path)[1]
        proposed = format_book_filename(e.get('title'), e.get('author'), e.get('subtitle'), ext, include_author=inc_a, include_subtitle=inc_s)
        proposals.append({'file': path, 'proposed': proposed, 'include_author': inc_a, 'include_subtitle': inc_s})

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(proposals, fh, ensure_ascii=False, indent=2)
    print('Saved proposals to', args.out)


if __name__ == '__main__':
    main()
