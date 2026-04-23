import re
import os

"""Utilidades pequeñas para normalizar textos y metadatos.

Cada función incluye una descripción breve en español indicando qué hace
y por qué existe: facilitar la generación de nombres de archivo,
normalizar autores y presentar tamaños legibles para la interfaz.
"""


def remove_banned_phrases(text: str) -> str:
    """Elimina expresiones no deseadas del texto (ej. 'spanish version').
    
    Qué hace: busca en una lista de expresiones regulares y las elimina,
    limpiando también los paréntesis vacíos que puedan quedar.
    Por qué: evitar que el nombre final del archivo contenga spam o tags.
    """
    if not text:
        return text
    
    banned_regexes = [
        r'\b(?:spanish|english)\s+(?:version|edition|ed)\b',
        r'\bedici[oó]n\s+en\s+espa[nñ]ol\b',
        r'\bedici[oó]n(?: revisada| especial)?\b',
        r'\(c\)\s*proyecto\s*espartaco',
        r'---private---',
        r'nueva\s*carpeta',
        r'\(author\)',
        r'\(spanish edition\)',
        r'\.(?:pdf|epub|doc|docx|rtf|txt|html)(?:\.(?:pdf|epub|doc|docx|rtf|txt|html))?$',
    ]
    t = str(text)
    for b in banned_regexes:
        t = re.sub(b, '', t, flags=re.IGNORECASE)
    
    # Limpiar posibles paréntesis o corchetes que hayan quedado vacíos
    t = re.sub(r'\(\s*\)', '', t)
    t = re.sub(r'\[\s*\]', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip(' -_.,()[]{}')


def sanitize(s: str) -> str:
    """Devuelve una cadena segura para usar como nombre de fichero.

    Qué hace: elimina caracteres de control, caracteres reservados en
    Windows, colapsa espacios y recorta puntos/espacios finales.
    Por qué: asegurar que los nombres propuestos sean válidos y legibles.
    """
    if not s:
        return "Unknown"
    # normalize whitespace
    s = re.sub(r'\s+', ' ', s)
    # remove C0 control chars and DEL
    s = re.sub(r'[\x00-\x1f\x7f]', '', s)
    # remove characters invalid on Windows filenames
    s = re.sub(r'[<>:\\"/\\|?*]', '', s)
    # remove other problematic characters (unprintable, unusual separators)
    s = s.strip()
    # Windows forbids names that end with space or dot
    s = s.rstrip(' .')
    # reserved device names on Windows (CON, PRN, AUX, NUL, COM1..COM9, LPT1..LPT9)
    if re.match(r'^(con|prn|aux|nul|com\d|lpt\d)$', s.strip(), flags=re.IGNORECASE):
        s = '_' + s
    # limit length to reasonable filename size
    if len(s) > 200:
        s = s[:200].rstrip()
    if not s:
        return 'Unknown'
    return s


def normalize_authors(author_field):
    """Normaliza distintos formatos de autor a una cadena única.

    Qué hace: acepta listas, cadenas separadas por comas o separadores
    comunes y devuelve "Nombre Apellido, Nombre2 Apellido2" o None.
    Por qué: unificar formatos heterogéneos para mostrar/autogenerar nombres.
    """
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
        key = n.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return ', '.join(out) if out else None


def format_authors_for_filename(auth_norm, max_authors=3):
    """Formatea autores normalizados para incluir en un nombre de fichero.

    Qué hace: toma la cadena normalizada y devuelve una lista limitada
    (ej. "Autor1, Autor2") o una cadena vacía si no hay autores.
    Por qué: generar prefijos de autor compactos para los nombres propuestos.
    """
    if not auth_norm:
        return ''
    if isinstance(auth_norm, str):
        authors = [a.strip() for a in auth_norm.split(',') if a.strip()]
    elif isinstance(auth_norm, (list, tuple)):
        authors = [str(a).strip() for a in auth_norm if a and str(a).strip()]
    else:
        authors = [str(auth_norm).strip()]
    authors = [sanitize(a) for a in authors if a]
    authors = [re.sub(r'\.(pdf|epub|doc|docx|rtf|txt|html)$', '', a, flags=re.IGNORECASE) for a in authors]
    if not authors:
        return ''
    if len(authors) <= max_authors:
        return ', '.join(authors)
    return ', '.join(authors[:max_authors]) + ' et al.'


def human_readable_size(n):
    """Convierte bytes a una cadena legible (KB, MB, GB...).

    Qué hace: formatea un entero de bytes en unidades humanas.
    Por qué: presentar tamaños en la interfaz de forma comprensible.
    """
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
    """Intentos heurísticos para extraer (título, autor) de un nombre de fichero.

    Qué hace: limpia tokens ruidosos, detecta patrones "Autor - Título" y
    devuelve una tupla (title, author) donde cualquiera puede ser None.
    Por qué: ofrecer sugerencias razonables cuando faltan metadatos internos.
    """
    if not filename:
        return None, None
    name = os.path.splitext(os.path.basename(filename))[0]

    def clean_filename_text(text: str) -> str:
        if not text:
            return ''
        t = text
        # Clean double extensions first
        t = re.sub(r'\.(pdf|epub|doc|docx|rtf|txt|html)\.(pdf|epub|doc|docx|rtf|txt|html)$', r'.\1', t, flags=re.IGNORECASE)
        
        # Remove technical noise
        noise = [r'---private---', r'\(c\)\s*proyecto\s*espartaco', r'nueva\s*carpeta', r'copy\s*of', r'copia\s*de']
        for n in noise:
            t = re.sub(n, '', t, flags=re.IGNORECASE)

        # if underscores are used as separators (pattern: Title_Author or Author_Title)
        if '_' in t and '-' not in t:
            # check if it looks like Title_Author_Name
            t = t.replace('_', ' - ')
        
        # normalize remaining dots (but not the one before extension if present, though splitext already removed it)
        t = re.sub(r'\s+', ' ', t)
        t = t.strip(' -_.,')
        return t.strip()

    s = clean_filename_text(name)
    
    # Handle (Categoria) prefix: e.g. "(Ingles) Autor - Titulo"
    m_cat = re.match(r'^\(([^)]+)\)\s+(.+)', s)
    if m_cat:
        s = m_cat.group(2).strip()

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
        # Ignore starting articles as authors
        if words[0].lower() in ['el', 'la', 'los', 'las', 'un', 'una', 'en']:
             return sanitize(s), None
        return None, sanitize(s)
    return sanitize(s), None


def normalize_author_case(author: str) -> str:
    """Normaliza la capitalización de un autor: primera letra mayúscula y resto minúsculas por palabra.

    Maneja compuestos, guiones y apóstrofes. Devuelve `None` si `author` es falsy.
    """
    if not author:
        return None
    # Si ya es lista o separado por comas, conservar tal como está (caller debe decidir)
    s = str(author).strip()
    def cap_part(p):
        # mantén apóstrofes y guiones, capitalizando subpartes
        parts = re.split(r"([\-'])", p)
        out = []
        for part in parts:
            if part in ("-", "'"):
                out.append(part)
            else:
                if part:
                    out.append(part[0].upper() + part[1:].lower() if len(part) > 1 else part.upper())
        return ''.join(out)

    words = [w for w in re.split(r"\s+", s) if w]
    normalized_words = [cap_part(w) for w in words]
    res = ' '.join(normalized_words)
    # Final cleanup for residual brackets
    res = re.sub(r'\(.*$', '', res).strip(' ,(')
    return res


def normalize_title_case(title: str) -> str:
    """Normaliza un título usando el estilo Titulo (Title Case) para idiomas latinos/inglés.

    Ejemplo: 'CIEN AÑOS DE SOLEDAD' -> 'Cien Años de Soledad'
    Ejemplo: 'el señor de los anillos' -> 'El Señor de los Anillos'
    Mantiene minúsculas las palabras de enlace a menos que sean la primera palabra.
    Devuelve `None` si `title` es falsy.
    """
    if not title:
        return None
    s = str(title).strip()
    # collapse whitespace
    s = re.sub(r'\s+', ' ', s)
    words = s.split(' ')
    if not words:
        return None
    
    stopwords = {
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 
        'de', 'del', 'a', 'ante', 'con', 'en', 'para', 'por', 'y', 'e', 'o', 'u', 'al',
        'the', 'an', 'and', 'but', 'or', 'for', 'nor', 'on', 'at', 'to', 'from', 'by', 'of', 'in'
    }

    out = []
    for i, w in enumerate(words):
        w_lower = w.lower()
        if i == 0 or w_lower not in stopwords:
            # Capitalizar primera letra, dejar el resto minúscula
            capitalized = w_lower.capitalize()
            out.append(capitalized)
        else:
            out.append(w_lower)
            
    return ' '.join(out)


def extract_series_from_text(text: str):
    """Extrae la información de serie y número de un texto.
    
    Devuelve una tupla (nueva_cadena_limpia, nombre_serie, numero_serie).
    Si no encuentra nada, devuelve (text, None, None).
    """
    if not text:
        return (text, None, None)
    
    patterns = [
        # (Nombre Serie - 1) o (Nombre Serie 1)
        r'\((.*?)\s*[-#]?\s*(\d+)\)',
        # [Nombre Serie - 1]
        r'\[(.*?)\s*[-#]?\s*(\d+)\]',
        # Serie Nombre #2 o Libro Nombre 3
        r'\b(?:saga|serie|libro|volumen|vol\.?|book)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+?)\s*#?\s*(\d+)\b',
        # Nombre Serie #3
        r'([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]+?)\s+#\s*(\d+)\b'
    ]
    
    import re
    t = str(text)
    for pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            series_name = m.group(1).strip()
            series_num = m.group(2).strip()
            full_match = m.group(0)
            clean_text = t.replace(full_match, '').strip(' -_.()[]{}')
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            # Limpiar ruido del nombre de la serie
            series_name = re.sub(r'^(?:saga|serie|libro|volumen|vol\.?|book)\s+', '', series_name, flags=re.IGNORECASE).strip()
            if series_name and series_num:
                return (clean_text, series_name, series_num)
            
    return (text, None, None)


def is_suspect_title(title: str) -> bool:
    """Detecta títulos que probablemente no son títulos reales (créditos, traducciones, repetidos).

    Regla práctica: busca tokens típicos de créditos/traducción/edición, títulos excesivamente largos
    o frases repetitivas que suelen aparecer en páginas de créditos y no en la portada.
    """
    if not title:
        return True
    s = title.lower()
    # tokens que suelen indicar que no es el título
    bad_tokens = [
        'traducción', 'traduccion', 'tradu', 'corrección', 'correccion', 'grupo', 'grupo de',
        'editorial', 'editor', 'documento', 'document', 'microsoft word', 'documento1', 'document1',
        'scan', 'scanned', 'copyright', '©', 'licencia', 'versión', 'version', 'www.', 'http', 'anonimo', 'anonymous',
        '@gmail', '@yahoo', '@hotmail', '.com', '.org', '.net', 's.a.', 's.l.', 'school', 'edicion',
        'impresión', 'impresion', 'fax', 'predef', 'uso académico', 'uso academico', 'comercial',
        'freedom press', 'diaspar', 'pc', 'gerson o.', 'bullzip', 'www.bullzip',
        'rene contreras', 'marina cruz', 'andres ruiz', 'andres ruiz kdm', 'yuste',
        'jesus villacorta', 'antonio garcia', 'cristo pantoja', 'equipo 1', 'jesus', 'antonio'
    ]
    for bt in bad_tokens:
        if bt in s:
            return True
    # títulos excesivamente largos o con mucha repetición
    if len(s) > 220:
        return True
    tokens = [t for t in s.split() if t]
    if len(tokens) < 1:
        return True
    # detectar frases con poca variación (p. ej. el mismo término repetido varias veces)
    uniq = set(tokens)
    if len(tokens) >= 6 and len(uniq) <= max(3, len(tokens) // 4):
        return True
    return False


def is_suspicious_author(author: str) -> bool:
    """Heurísticas simples para detectar autores que parecen basura o créditos de edición.

    Devuelve True si el autor es claramente irrelevante ("Administrator", tokens de traducción,
    nombres demasiado genéricos, etc.).
    """
    if not author:
        return True
    s = str(author).strip().lower()
    bad = ['administrator', 'admin', 'unknown', 'autor', 'autor:', 'user', 'anonimo', 'anonymous',
           'editorial', 'editor', 'grupo', 'tradu', 'img', 'doc', 'pdf', '©', 'copyright',
           'www.', 'http', '.com', '.org', 's.a.', 's.l.', 'school', '@gmail', '@yahoo', '@hotmail',
           'freedom press', 'diaspar', 'pc', 'predef', 'fax', 'comercial',
           'gerson o.', 'bullzip', 'dt', 'montse', 'juan', 'papoto', 'funda2', 'writer',
           'rene contreras', 'marina cruz', 'andres ruiz', 'andres ruiz kdm', 'yuste',
           'facultad de educacion', 'facultad de', 'universidad de', 'departamento de',
           'jesus villacorta', 'antonio garcia', 'cristo pantoja', 'equipo 1', 'jesus', 'antonio']
    for b in bad:
        if b in s:
            return True
    parts = [p for p in re.split(r'[,;\\/]|\band\b|\by\b', s) if p.strip()]
    # si solo hay un caracter suelto, considerarlo sospechoso, pero permitir autores cortos como Poe o Eco
    if len(parts) == 1:
        token = parts[0].strip()
        if len(token) <= 1:
            return True
    return False
