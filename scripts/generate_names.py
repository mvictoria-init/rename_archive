"""Genera propuestas de nombres canónicos a partir de `models/mapping.json`.

Uso:
  python rename_archive/scripts/generate_names.py --mapping rename_archive/models/mapping.json --out rename_archive/models/proposed_names.json

Opciones:
  --apply    Aplica los renombres en disco (usar con precaución).
"""
import os
import sys
import json
import argparse

# Asegurar que el paquete renamer (ubicado en ../) esté en sys.path
HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from renamer.namer import filename_from_mapping_entry, format_book_filename
from renamer.utils import sanitize
try:
    import joblib
except Exception:
    joblib = None


def featurize(entry):
    """Compute the same lightweight features used by `train_name_selector.py`.

    Returns a list of numeric features for a single mapping entry.
    """
    title = (entry.get('title') or '')
    subtitle = (entry.get('subtitle') or '')
    author = (entry.get('author') or '')
    fname = os.path.splitext(os.path.basename(entry.get('file') or ''))[0]
    ext = os.path.splitext(entry.get('file') or '')[1].lower()

    def cap_ratio(s):
        words = [w for w in str(s).split() if w]
        if not words:
            return 0.0
        up = sum(1 for w in words if any(ch.isupper() for ch in w))
        return up / len(words)

    def uppercase_word_count(s):
        return sum(1 for w in str(s).split() if w.isupper())

    def digit_ratio(s):
        s = str(s)
        if not s:
            return 0.0
        digits = sum(1 for ch in s if ch.isdigit())
        return digits / max(1, len(s))

    def avg_word_len(s):
        words = [w for w in str(s).split() if w]
        if not words:
            return 0.0
        return sum(len(w) for w in words) / len(words)

    feats = [
        len(str(title)),
        len(str(title).split()),
        cap_ratio(title),
        uppercase_word_count(title),
        digit_ratio(title),
        avg_word_len(title),
        1 if subtitle else 0,
        len(str(subtitle).split()),
        cap_ratio(subtitle),
        avg_word_len(subtitle),
        1 if author else 0,
        str(author).count(',') + str(author).count(';'),
        len(str(fname).split()),
        1 if '-' in fname else 0,
        1 if ':' in str(title) else 0,
        1 if '(' in str(title) or ')' in str(title) else 0,
        1 if ext == '.pdf' else 0,
        1 if ext == '.txt' else 0,
        1 if ext == '.epub' else 0,
        1 if ext == '.docx' else 0,
    ]
    return feats


def load_mapping(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def generate_proposals(mapping_entries, selector_path=None):
    sel = None
    model_author = None
    model_sub = None
    if selector_path and joblib:
        try:
            sel = joblib.load(selector_path)
            if isinstance(sel, dict):
                model_author = sel.get('author')
                model_sub = sel.get('subtitle')
            else:
                # tolerant: try attribute access
                model_author = getattr(sel, 'author', None)
                model_sub = getattr(sel, 'subtitle', None)
        except Exception:
            sel = None

    out = []
    for e in mapping_entries:
        orig = e.get('file')
        try:
            if sel and (model_author or model_sub):
                feats = featurize(e)
                X = [feats]
                try:
                    pred_a = int(model_author.predict(X)[0]) if model_author else 1 if e.get('author') else 0
                except Exception:
                    pred_a = 1 if e.get('author') else 0
                try:
                    pred_s = int(model_sub.predict(X)[0]) if model_sub else 1 if e.get('subtitle') else 0
                except Exception:
                    pred_s = 1 if e.get('subtitle') else 0
                # build filename honoring model decisions
                ext = os.path.splitext(orig)[1] if orig else ''
                proposed = format_book_filename(e.get('title'), e.get('author'), e.get('subtitle'), ext, include_author=bool(pred_a), include_subtitle=bool(pred_s))
            else:
                proposed = filename_from_mapping_entry(e)
        except Exception:
            proposed = filename_from_mapping_entry(e)
        out.append({'file': orig, 'proposed': proposed})
    return out


def apply_proposals(proposals):
    for p in proposals:
        src = p.get('file')
        prop = p.get('proposed')
        if not src or not os.path.exists(src):
            print('Skipping missing:', src)
            continue
        folder = os.path.dirname(src) or '.'
        dst = os.path.join(folder, sanitize(prop))
        # if already same path, skip
        try:
            if os.path.abspath(src) == os.path.abspath(dst):
                print('Already named:', src)
                continue
        except Exception:
            pass
        base, ext = os.path.splitext(dst)
        idx = 1
        while os.path.exists(dst):
            dst = f"{base} ({idx}){ext}"
            idx += 1
        try:
            os.rename(src, dst)
            print('Renamed:', src, '->', dst)
        except Exception as ex:
            print('Error renaming', src, ex)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mapping', '-m', default=os.path.join(os.path.dirname(__file__), '..', 'models', 'mapping.json'), help='Path to mapping.json')
    p.add_argument('--out', '-o', default=None, help='File to write proposals (JSON)')
    p.add_argument('--apply', action='store_true', help='Apply renames on disk')
    args = p.parse_args()

    mapping_path = os.path.abspath(args.mapping)
    if not os.path.exists(mapping_path):
        print('Mapping not found:', mapping_path)
        sys.exit(1)

    entries = load_mapping(mapping_path)
    # usar el selector entrenado si existe
    default_selector = os.path.join(HERE, 'models', 'name_selector.joblib')
    selector_to_use = default_selector if os.path.exists(default_selector) else None
    proposals = generate_proposals(entries, selector_path=selector_to_use)

    # Deduplicate proposals: mapping.json contains varias entradas por fichero (chunks).
    # Elegimos la propuesta más frecuente por ruta de fichero.
    from collections import Counter, defaultdict
    grouped = defaultdict(list)
    for p in proposals:
        grouped[p.get('file')].append(p.get('proposed'))
    deduped = []
    for fpath, props in grouped.items():
        if not props:
            continue
        most = Counter(props).most_common(1)[0][0]
        deduped.append({'file': fpath, 'proposed': most})
    proposals = deduped

    if args.out:
        out_path = os.path.abspath(args.out)
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(proposals, fh, ensure_ascii=False, indent=2)
        print('Saved proposals to', out_path)
    else:
        print(json.dumps(proposals, ensure_ascii=False, indent=2))

    if args.apply:
        print('Applying proposals...')
        apply_proposals(proposals)


if __name__ == '__main__':
    main()
