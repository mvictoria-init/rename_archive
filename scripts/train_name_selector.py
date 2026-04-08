"""Entrena un modelo ligero (LogisticRegression) para decidir plantillas de nombre.

Este script es deliberadamente simple y está pensado para máquinas con pocos
recursos. Genera dos modelos binarios: incluir autor y incluir subtítulo.

Si `scikit-learn` no está disponible el script muestra instrucciones para
instalarlo y sale sin cambios.
"""
import os
import sys
import json
import argparse

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    from sklearn.dummy import DummyClassifier
    import joblib
except Exception:
    print('Falta scikit-learn o joblib. Instale con: pip install scikit-learn joblib')
    sys.exit(1)


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
        words = [w for w in s.split() if w]
        if not words:
            return 0.0
        up = sum(1 for w in words if any(ch.isupper() for ch in w))
        return up / len(words)

    def uppercase_word_count(s):
        return sum(1 for w in s.split() if w.isupper())

    def digit_ratio(s):
        if not s:
            return 0.0
        digits = sum(1 for ch in s if ch.isdigit())
        return digits / max(1, len(s))

    def avg_word_len(s):
        words = [w for w in s.split() if w]
        if not words:
            return 0.0
        return sum(len(w) for w in words) / len(words)

    feats = [
        len(title),
        len(title.split()),
        cap_ratio(title),
        uppercase_word_count(title),
        digit_ratio(title),
        avg_word_len(title),
        1 if subtitle else 0,
        len(subtitle.split()),
        cap_ratio(subtitle),
        avg_word_len(subtitle),
        1 if author else 0,
        author.count(',') + author.count(';'),
        len(fname.split()),
        1 if '-' in fname else 0,
        1 if ':' in title else 0,
        1 if '(' in title or ')' in title else 0,
        1 if ext == '.pdf' else 0,
        1 if ext == '.txt' else 0,
        1 if ext == '.epub' else 0,
        1 if ext == '.docx' else 0,
    ]
    return feats


def build_labels(entry):
    # heurísticas simples para generar etiquetas iniciales
    author = entry.get('author')
    subtitle = entry.get('subtitle')
    include_author = 1 if author and str(author).strip() else 0
    include_subtitle = 0
    if subtitle and 2 < len(str(subtitle).split()) < 20:
        include_subtitle = 1
    return include_author, include_subtitle


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mapping', '-m', default=os.path.join(HERE, 'models', 'mapping.json'))
    p.add_argument('--out', '-o', default=os.path.join(HERE, 'models', 'name_selector.joblib'))
    args = p.parse_args()

    mapping_path = os.path.abspath(args.mapping)
    if not os.path.exists(mapping_path):
        print('mapping.json no encontrado en', mapping_path)
        sys.exit(1)
    entries = load_mapping(mapping_path)
    X = [featurize(e) for e in entries]
    ys_author = []
    ys_sub = []
    for e in entries:
        a, s = build_labels(e)
        ys_author.append(a)
        ys_sub.append(s)

    ya_unique = set(ys_author)
    ys_unique = set(ys_sub)

    if len(X) < 4:
        print('Dataset pequeño (<4), entrenando con todos los ejemplos sin test de validación.')
        # Usar DummyClassifier si la etiqueta es constante
        if len(ya_unique) == 1:
            const = next(iter(ya_unique))
            model_a = DummyClassifier(strategy='constant', constant=const)
            model_a.fit(X, ys_author)
        else:
            model_a = LogisticRegression(max_iter=500)
            model_a.fit(X, ys_author)

        if len(ys_unique) == 1:
            const = next(iter(ys_unique))
            model_s = DummyClassifier(strategy='constant', constant=const)
            model_s.fit(X, ys_sub)
        else:
            model_s = LogisticRegression(max_iter=500)
            model_s.fit(X, ys_sub)

        joblib.dump({'author': model_a, 'subtitle': model_s}, args.out)
        print('Modelos guardados en', args.out)
        return

    X_train, X_test, ya_train, ya_test, ys_train, ys_test = train_test_split(X, ys_author, ys_sub, test_size=0.2, random_state=42)
    # Si alguna partición tiene una sola clase, usar DummyClassifier ahí
    if len(set(ya_train)) == 1:
        const = next(iter(set(ya_train)))
        model_a = DummyClassifier(strategy='constant', constant=const)
        model_a.fit(X_train, ya_train)
    else:
        # usar RandomForest para captar reglas más complejas
        model_a = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42)
        model_a.fit(X_train, ya_train)

    if len(set(ys_train)) == 1:
        const = next(iter(set(ys_train)))
        model_s = DummyClassifier(strategy='constant', constant=const)
        model_s.fit(X_train, ys_train)
    else:
        model_s = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42)
        model_s.fit(X_train, ys_train)

    pred_a = model_a.predict(X_test)
    pred_s = model_s.predict(X_test)
    print('== Include author ==')
    if len(set(ya_test)) > 1:
        print(classification_report(ya_test, pred_a))
    else:
        print('Prueba contiene una sola clase, saltando reporte de clasificación.')
    print('== Include subtitle ==')
    if len(set(ys_test)) > 1:
        print(classification_report(ys_test, pred_s))
    else:
        print('Prueba contiene una sola clase, saltando reporte de clasificación.')

    joblib.dump({'author': model_a, 'subtitle': model_s}, args.out)
    print('Modelos guardados en', args.out)


if __name__ == '__main__':
    main()
