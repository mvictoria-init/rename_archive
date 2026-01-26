import re
import os

def sanitize(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[<>:\"/\\|?*]', '', s)
    return s.strip()


def normalize_authors(author_field):
    if not author_field:
        return None
    items = []
    if isinstance(author_field, (list, tuple)):
        for a in author_field:
            if a and isinstance(a, str):
                items.append(a.strip())
    else:
        s = str(author_field).strip()
        parts = re.split(r'[;/\\|&]|\band\b|\by\b', s, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and p.strip()]
        if len(parts) > 1:
            items = parts
        else:
            if ',' in s:
                comma_count = s.count(',')
                if comma_count >= 2 and comma_count % 2 == 1:
                    tokens = [t.strip() for t in s.split(',') if t.strip()]
                    paired = []
                    for i in range(0, len(tokens), 2):
                        if i+1 < len(tokens):
                            paired.append(tokens[i] + ', ' + tokens[i+1])
                        else:
                            paired.append(tokens[i])
                    items = paired
                else:
                    items = [p.strip() for p in s.split(',') if p.strip()]
            else:
                items = [s]
    normalized = []
    for it in items:
        if not it:
            continue
        m = re.match(r'^([^,]+),\s*(.+)$', it)
        if m:
            last = m.group(1).strip()
            first = m.group(2).strip()
            name = f"{first} {last}"
        else:
            name = it
        name = re.sub(r'\s+', ' ', name).strip()
        normalized.append(name)
    seen = set()
    out = []
    for n in normalized:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return ', '.join(out) if out else None


def format_authors_for_filename(auth_norm, max_authors=3):
    if not auth_norm:
        return ''
    if isinstance(auth_norm, str):
        authors = [a.strip() for a in auth_norm.split(',') if a.strip()]
    elif isinstance(auth_norm, (list, tuple)):
        authors = [str(a).strip() for a in auth_norm if a and str(a).strip()]
    else:
        authors = [str(auth_norm).strip()]
    authors = [sanitize(a) for a in authors if a]
    if not authors:
        return ''
    if len(authors) <= max_authors:
        return ', '.join(authors)
    return ', '.join(authors[:max_authors]) + ' et al.'


def human_readable_size(n):
    try:
        n = int(n)
    except Exception:
        return ''
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024.0:
            return f"{n:.0f} {unit}"
        n /= 1024.0
    return f"{n:.0f} PB"


def guess_title_author_from_filename(filename):
    """Heuristics to extract (title, author) from a messy filename.

    Returns (title, author) where any may be None.
    """
    if not filename:
        return None, None
    name = os.path.splitext(os.path.basename(filename))[0]

    def clean_filename_text(text: str) -> str:
        if not text:
            return ''
        t = text
        # normalize separators
        t = re.sub(r'[._]+', ' ', t)
        t = t.replace('—', '-').replace('–', '-')
        # remove common noise tokens and words
        t = re.sub(r'\b(Microsoft Word|Documento|Document|Scan|IMG|IMG_?\d+|Page_?\d+|Document1|Documento1)\b', '', t, flags=re.IGNORECASE)
        # remove bracketed sections
        t = re.sub(r'\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}', '', t)
        # remove stray 'cf', 'cf.' and similar references
        t = re.sub(r'\b(cf|cf\.|cf:)\b', '', t, flags=re.IGNORECASE)
        # remove standalone single letters (likely artifacts)
        t = re.sub(r'\b[a-zA-Z]\b', '', t)
        # remove long runs of non-word characters
        t = re.sub(r'[^\w\s\-]', ' ', t)
        # collapse multiple separators/spaces
        t = re.sub(r'\s+', ' ', t)
        t = t.strip(' -_.,')
        return t.strip()

    s = clean_filename_text(name)

    # Prefer splits on ' - ' or ' -' or '- '
    if '-' in s:
        parts = [p.strip() for p in s.split('-') if p.strip()]
        # If two parts, guess which is author/title
        if len(parts) == 2:
            left, right = parts
            # if left contains comma (Last, First) or short (<=3 words) treat as author
            left_words = left.split()
            right_words = right.split()
            if ',' in left or len(left_words) <= 3 and len(right_words) > 1:
                author = left
                title = right
            elif ',' in right or len(right_words) <= 3 and len(left_words) > 1:
                author = right
                title = left
            else:
                # default: author first
                author = left
                title = right
            return sanitize(title), sanitize(author)
        else:
            # more than two parts: likely Author - Title - extra; take first as author, second as title
            author = parts[0]
            title = ' '.join(parts[1:])
            return sanitize(title), sanitize(author)

    # if comma separated with Last, First
    if ',' in s:
        parts = [p.strip() for p in s.split(',') if p.strip()]
        if len(parts) >= 2:
            author = parts[0] + (', ' + parts[1] if len(parts) > 1 else '')
            title = ' '.join(parts[2:]) if len(parts) > 2 else None
            return (sanitize(title) if title else None), sanitize(author)

    # fallback: if string has many uppercase words, assume title; if short, assume author
    words = s.split()
    if len(words) <= 3:
        return None, sanitize(s)
    return sanitize(s), None
