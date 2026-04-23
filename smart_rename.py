import os, re, sys, json, unicodedata, datetime
import urllib.request, urllib.parse

# Forzar salida de consola a UTF-8 para evitar UnicodeEncodeError en Windows
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Insertar el path de la aplicación para poder importar módulos de 'renamer'
sys.path.insert(0, r'D:\Mv\Documentos\Renameapp\rename_archive')

import fitz # PyMuPDF
import docx # python-docx
from renamer.utils import (
    guess_title_author_from_filename, is_suspicious_author, is_suspect_title,
    normalize_author_case, normalize_title_case, sanitize
)

# --- CONFIGURACIÓN ---
TARGET_FOLDERS = [
    r'D:\Mv\Documentos\Libros\pdf',
    r'D:\Mv\Documentos\Libros\Nueva carpeta',
    r'D:\Mv\Documentos\Libros\todos los libros sin arreglar'
]
LOG_FILE      = r'D:\Mv\Documentos\Libros\renombrado_fase3_log.json'
DRY_RUN       = False

def get_metadata_docx(file_path):
    try:
        doc = docx.Document(file_path)
        # Extraer de propiedades del documento
        props = doc.core_properties
        title = props.title
        author = props.author
        
        # Fallback: si no hay metadatos, intentar con el primer párrafo con texto
        if not title:
            for p in doc.paragraphs:
                if p.text.strip():
                    title = p.text.strip()
                    break
        return {'title': title, 'author': author}
    except:
        return {}

def get_metadata_pymupdf(file_path):
    try:
        with fitz.open(file_path) as doc:
            meta = doc.metadata
            return {
                'title': meta.get('title'),
                'author': meta.get('author'),
                'subject': meta.get('subject')
            }
    except:
        return {}

def get_openlibrary_metadata(title, author=None):
    if not title or len(title) < 5: return None
    try:
        q = f'title:{title}'
        if author: q += f' author:{author}'
        url = f"https://openlibrary.org/search.json?q={urllib.parse.quote(q)}&limit=1"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data['docs']:
                doc = data['docs'][0]
                return {
                    'title': doc.get('title'),
                    'author': doc.get('author_name', [None])[0],
                    'subtitle': doc.get('subtitle')
                }
    except:
        pass
    return None

def process_file(file_path):
    base_name = os.path.basename(file_path)
    # Get proper extension and clean double extensions
    ext = os.path.splitext(base_name.lower())[1]
    if ext == '.pdf' and base_name.lower().endswith('.pdf.pdf'):
        pass # ext is already .pdf
    
    # 1. Intentar adivinar del nombre de archivo (como anclaje)
    guess_t, guess_a = guess_title_author_from_filename(base_name)
    
    final_title = guess_t
    final_author = guess_a
    final_subtitle = None
    confidence = "low"

    # 2. Intentar metadatos según extensión
    if ext == '.pdf':
        meta = get_metadata_pymupdf(file_path)
    elif ext == '.docx':
        meta = get_metadata_docx(file_path)
    else:
        meta = {}

    if meta:
        internal_t = meta.get('title')
        internal_a = meta.get('author')
        
        # Validar metadatos internos
        if internal_t and not is_suspect_title(internal_t):
            final_title = internal_t
            confidence = "medium"
        
        if internal_a and not is_suspicious_author(internal_a):
            # Si el autor interno es bueno y tiene al menos 2 palabras, alta confianza
            if len(str(internal_a).split()) >= 2:
                final_author = internal_a
                confidence = "high"

    # 3. Validación Cruzada / API si la confianza es baja
    if confidence == "low" or not final_author:
        api = get_openlibrary_metadata(final_title or guess_t, final_author or guess_a)
        if api:
            final_title = api['title']
            final_author = api['author']
            final_subtitle = api['subtitle']
            confidence = "api"

    # 4. Normalización Final
    # Limpiar autores complejos como "Banana, Flavita, 1987- Author, Illustrator"
    if final_author:
        final_author = str(final_author)
        final_author = re.sub(r',\s*\d{4}-.*$', '', final_author)
        final_author = re.sub(r'\s*author.*$', '', final_author, flags=re.IGNORECASE)
        final_author = re.sub(r'\s*illustrator.*$', '', final_author, flags=re.IGNORECASE)
        # Limpiar extensiones que se cuelan en el autor
        final_author = re.sub(r'\.(pdf|epub|doc|docx|rtf|txt|html)$', '', final_author, flags=re.IGNORECASE)

    if final_title:
        final_title = str(final_title)
        # Limpiar extensiones que se cuelan en el título
        final_title = re.sub(r'\.(pdf|epub|doc|docx|rtf|txt|html)$', '', final_title, flags=re.IGNORECASE)

    final_author = normalize_author_case(final_author)
    final_title = normalize_title_case(final_title)
    final_subtitle = normalize_title_case(final_subtitle)
    
    if final_subtitle:
        final_subtitle = re.sub(r'\.(pdf|epub|doc|docx|rtf|txt|html)$', '', str(final_subtitle), flags=re.IGNORECASE)
    
    if not final_author or is_suspicious_author(final_author):
        return None, "Autor no confiable"
    
    if not final_title or is_suspect_title(final_title):
        return None, "Título no confiable"

    # Construir nombre Gold Standard: "Autor - Título. Subtítulo.ext"
    new_name = f"{final_author} - {final_title}"
    if final_subtitle:
        new_name += f". {final_subtitle}"
    
    new_name = sanitize(new_name) + ext
    
    if new_name.lower() == base_name.lower():
        return None, "Ya está correcto"
        
    return new_name, f"Confianza: {confidence}"

def main():
    results = []
    try:
        if sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass
    
    print(f"--- INICIANDO FASE 3 (DRY_RUN={DRY_RUN}) ---")
    
    for folder in TARGET_FOLDERS:
        if not os.path.exists(folder): continue
        print(f"\nProcesando carpeta: {folder}")
        
        for root, dirs, files in os.walk(folder):
            for f in files:
                if not f.lower().endswith(('.pdf', '.epub', '.docx', '.txt')): continue
                
                full_path = os.path.join(root, f)
                print(f"Buscando metadatos para: {f}...", end="\r")
                new_name, reason = process_file(full_path)
                
                if new_name:
                    new_path = os.path.join(root, new_name)
                    
                    if not DRY_RUN:
                        try:
                            os.rename(full_path, new_path)
                            status = "RENAMED"
                        except Exception as e:
                            status = f"ERROR: {str(e)}"
                    else:
                        status = "DRY_OK"

                    results.append({
                        'original': f,
                        'proposicion': new_name,
                        'folder': folder,
                        'reason': reason,
                        'status': status
                    })
                    print(f"[{status}] {f} -> {new_name}")
                else:
                    # Opcional: log de skips
                    pass

    # Guardar log
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump({'date': str(datetime.datetime.now()), 'results': results}, f, indent=4)
    
    print(f"\nReporte generado en: {LOG_FILE}")
    print(f"Total propuestos: {len(results)}")

if __name__ == "__main__":
    main()
