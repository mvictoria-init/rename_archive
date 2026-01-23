import os
import re
import shutil
import zipfile
import threading
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

def sanitize(s: str) -> str:
    if not s:
        return ""
    # Normalize whitespace and remove illegal Windows filename chars
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[<>:\"/\\|?*]', '', s)
    s = s.strip()
    return s


def normalize_authors(author_field):
    """Return a single string with authors separated by comma and space.

    Accepts None, a single string, or an iterable of strings.
    Splits strings by common separators if needed.
    """
    if not author_field:
        return None

    # Build initial list of candidate author strings
    items = []
    if isinstance(author_field, (list, tuple)):
        # treat each list element as one author entry
        for a in author_field:
            if a and isinstance(a, str):
                items.append(a.strip())
    else:
        s = str(author_field).strip()
        # Prefer splitting on semicolon, pipe, slash, ampersand, ' and ', ' y '
        parts = re.split(r'[;/\\|&]|\band\b|\by\b', s, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and p.strip()]
        if len(parts) > 1:
            items = parts
        else:
            # If only one part, try smarter splitting if commas resemble multiple authors
            if ',' in s:
                # if there are multiple commas and they likely form pairs 'Last, First, Last2, First2'
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
                    # fallback: split on comma if no other separators
                    items = [p.strip() for p in s.split(',') if p.strip()]
            else:
                items = [s]

    # Normalize each item: if it matches 'Last, First' -> reorder to 'First Last'
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
        # collapse whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        normalized.append(name)

    # remove duplicates preserving order
    seen = set()
    out = []
    for n in normalized:
        if n not in seen:
            seen.add(n)
            out.append(n)

    return ', '.join(out) if out else None


def format_authors_for_filename(auth_norm, max_authors=3):
    """Return a filename-safe authors string limited to max_authors, appending 'et al.' if truncated."""
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

def extract_pdf_metadata(path):
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        info = reader.metadata
        title = None
        author = None
        if info:
            if isinstance(info, dict):
                title = info.get('/Title') or info.get('Title')
                author = info.get('/Author') or info.get('Author')
            else:
                title = getattr(info, 'title', None)
                author = getattr(info, 'author', None)
        # normalize authors if present
        author = normalize_authors(author)
        title = title.strip() if title and isinstance(title, str) else title
        # Fallback: try to extract simple text from first page if no metadata
        if not title or not author:
            try:
                # read first page text
                if len(reader.pages) > 0:
                    text = reader.pages[0].extract_text() or ''
                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    if not title and lines:
                        title = lines[0]
                    if not author and len(lines) > 1:
                        # look for patterns like 'by Author'
                        second = lines[1]
                        m = re.search(r'by\\s+(.+)', second, flags=re.IGNORECASE)
                        if m:
                            author = m.group(1)
                        else:
                            # if the second line looks like a name (contains space and no punctuation), accept it
                            if re.match(r'^[\\w\\-\\., ]+$', second):
                                author = second
            except Exception:
                pass
        return (title, author)
    except Exception:
        return (None, None)

def extract_docx_metadata(path):
    try:
        from docx import Document
        doc = Document(path)
        props = doc.core_properties
        title = props.title or None
        author = props.author or None
        author = normalize_authors(author)
        return (title, author)
    except Exception:
        return (None, None)

def extract_epub_metadata(path):
    # Try ebooklib first
    try:
        from ebooklib import epub
        book = epub.read_epub(path)
        titles = book.get_metadata('DC', 'title')
        creators = book.get_metadata('DC', 'creator')
        title = None
        if titles:
            # titles is list of (value, attrs)
            title = titles[0][0]
        author = None
        if creators:
            # gather all creator values
            auths = [c[0] for c in creators if c and c[0]]
            author = normalize_authors(auths)
        return (title, author)
    except Exception:
        # Fallback: parse OPF inside zip
        try:
            z = zipfile.ZipFile(path)
            opf_path = None
            # locate the package document (container.xml)
            if 'META-INF/container.xml' in z.namelist():
                import xml.etree.ElementTree as ET
                cont = z.read('META-INF/container.xml')
                root = ET.fromstring(cont)
                # Find rootfile element
                ns = {'c': 'urn:oasis:names:tc:opendocument:xmlns:container'}
                rf = root.find('.//c:rootfile', ns)
                if rf is not None:
                    opf_path = rf.get('full-path')
            if not opf_path:
                # try common locations
                for name in z.namelist():
                    if name.endswith('.opf'):
                        opf_path = name
                        break
            if opf_path:
                data = z.read(opf_path)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(data)
                # try find title and creator in metadata
                title = None
                author = None
                for elem in root.iter():
                    tag = elem.tag.lower()
                    if tag.endswith('title') and not title:
                        title = elem.text
                    if tag.endswith('creator'):
                        # collect possible multiple creators
                        if not author:
                            author = elem.text
                        else:
                            author = author + ', ' + (elem.text or '')
                author = normalize_authors(author)
                return (title, author)
        except Exception:
            return (None, None)
    return (None, None)

def extract_txt_metadata(path):
    # Very naive: first non-empty line as title, second as author if contains 'by'
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read(4000)
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            title = None
            author = None
            # look for explicit fields
            for ln in lines[:10]:
                m_t = re.match(r'Title\s*[:\-]\s*(.+)', ln, flags=re.IGNORECASE)
                m_a = re.match(r'Author\s*[:\-]\s*(.+)', ln, flags=re.IGNORECASE)
                if m_t and not title:
                    title = m_t.group(1).strip()
                if m_a and not author:
                    author = m_a.group(1).strip()
            if not title and lines:
                title = lines[0]
            if not author and len(lines) > 1:
                second = lines[1]
                m = re.search(r'by\s+(.+)', second, flags=re.IGNORECASE)
                if m:
                    author = m.group(1).strip()
            author = normalize_authors(author)
            return (title, author)
    except Exception:
        return (None, None)

def extract_metadata(path: Path):
    ext = path.suffix.lower()
    if ext == '.pdf':
        return extract_pdf_metadata(str(path))
    if ext == '.docx':
        return extract_docx_metadata(str(path))
    if ext == '.epub':
        return extract_epub_metadata(str(path))
    if ext in ('.txt', '.md'):
        return extract_txt_metadata(str(path))
    return (None, None)

class RenamerApp:
    def __init__(self, root):
        self.root = root
        root.title('Renombrador por Autor y Título')
        self.folder = tk.StringVar()

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill='both', expand=True)

        top = ttk.Frame(frm)
        top.pack(fill='x')
        ttk.Button(top, text='Seleccionar carpeta', command=self.select_folder).pack(side='left')
        ttk.Label(top, textvariable=self.folder).pack(side='left', padx=8)

        self.status = tk.StringVar(value='')
        ttk.Label(frm, textvariable=self.status).pack(fill='x')

        content = ttk.Frame(frm)
        content.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(content, columns=('orig','new','size'), show='headings')
        self.tree.heading('orig', text='Original')
        self.tree.heading('new', text='Propuesto')
        self.tree.heading('size', text='Tamaño')
        self.tree.pack(side='left', fill='both', expand=True, pady=8)

        # (no preview panel)

        # mapping from tree item id to entries index
        self.item_map = {}

        # bind selection
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select())
        # bind double click for inline edit of 'Propuesto' column
        self._editing_entry = None
        self.tree.bind('<Double-1>', self.on_double_click)

        bottom = ttk.Frame(frm)
        bottom.pack(fill='x')
        self.scan_btn = ttk.Button(bottom, text='Escanear', command=self.scan)
        self.scan_btn.pack(side='left')
        self.rename_btn = ttk.Button(bottom, text='Renombrar', command=self.rename_files)
        self.rename_btn.pack(side='left', padx=6)
        self.rename_selected_btn = ttk.Button(bottom, text='Renombrar seleccionado', command=self.rename_selected)
        self.rename_selected_btn.pack(side='left', padx=6)
        self.delete_dup_btn = ttk.Button(bottom, text='Eliminar duplicados', command=self.delete_duplicates)
        self.delete_dup_btn.pack(side='left', padx=6)

        self._scan_thread = None

        self.entries = []

    def select_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

    def scan(self):
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        # prevent double scans
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self.scan_btn.state(['disabled'])
        self.rename_btn.state(['disabled'])
        self.tree.delete(*self.tree.get_children())
        self.entries = []
        self.status.set('Escaneando...')
        def file_hash(path, block_size=65536):
            h = hashlib.sha256()
            try:
                with open(path, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(block_size), b''):
                        h.update(chunk)
                return h.hexdigest()
            except Exception:
                return None

        # use global human_readable_size

        def worker(folder_path):
            p = Path(folder_path)
            hash_map = {}  # hash -> first tree item id
            for f in p.iterdir():
                if f.is_file():
                    title, author = extract_metadata(f)
                    ext = f.suffix
                    t = sanitize(title) if title else ''
                    # normalize and sanitize multiple authors
                    a = ''
                    auth_norm = normalize_authors(author)
                    a = format_authors_for_filename(auth_norm, max_authors=3)
                    if a and t:
                        new = f"{a} - {t}{ext}"
                    elif t:
                        new = f"{t}{ext}"
                    elif a:
                        new = f"{a}{ext}"
                    else:
                        new = f.name

                    file_h = file_hash(str(f))
                    size_val = None
                    try:
                        size_val = f.stat().st_size
                    except Exception:
                        size_val = None
                    # store title and author as well for manual editing
                    self.entries.append((str(f), new, file_h, size_val, title, author))
                    # schedule UI update with duplicate tagging
                    def insert_item(fname=f.name, nname=new, fh=file_h, sz=size_val):
                        # if hash already seen, mark both as duplicates
                        tags = ()
                        if fh and fh in hash_map:
                            # mark existing item as duplicate
                            first_id = hash_map[fh]
                            prev_tags = set(self.tree.item(first_id, 'tags') or ())
                            prev_tags.add('dup')
                            self.tree.item(first_id, tags=tuple(prev_tags))
                            tags = ('dup',)
                        else:
                            if fh:
                                hash_map[fh] = None  # placeholder; will update after insert
                        # index of the entry is len(self.entries)-1
                        idx = len(self.entries) - 1
                        iid = f'i{idx}'
                        self.tree.insert('', 'end', iid=iid, values=(fname, nname, human_readable_size(sz)), tags=tags)
                        # map item id to index and record first seen id for hash
                        self.item_map[iid] = idx
                        if fh and hash_map.get(fh) is None:
                            hash_map[fh] = iid
                    self.root.after(0, insert_item)
            # finished
            def on_done():
                self.status.set('Escaneo completado')
                self.scan_btn.state(['!disabled'])
                self.rename_btn.state(['!disabled'])
                # configure duplicate tag style
                try:
                    self.tree.tag_configure('dup', background='#ffdce0')
                except Exception:
                    pass
            self.root.after(0, on_done)
        t = threading.Thread(target=worker, args=(folder,), daemon=True)
        self._scan_thread = t
        t.start()

    def rename_files(self):
        if not self.entries:
            messagebox.showinfo('Nada', 'No hay archivos para renombrar. Escanee primero.')
            return
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        self.rename_btn.state(['disabled'])
        conflicts = []
        for orig, new, fh, sz, title, author in list(self.entries):
            src = Path(orig)
            dst = Path(folder) / new
            if dst.exists():
                base = dst.stem
                idx = 1
                while True:
                    candidate = Path(folder) / f"{base} ({idx}){dst.suffix}"
                    if not candidate.exists():
                        dst = candidate
                        break
                    idx += 1
            try:
                shutil.move(str(src), str(dst))
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        self.rename_btn.state(['!disabled'])
        self.scan()

    def on_select(self):
        # selection handler left intentionally minimal (no preview panel)
        return

    

    def on_double_click(self, event):
        # identify cell
        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or not col:
            return
        # we only allow editing the 'new' column (#2)
        if col != '#2':
            return
        # get bbox of cell
        bbox = self.tree.bbox(row, column=col)
        if not bbox:
            return
        x, y, width, height = bbox
        # get current value
        vals = list(self.tree.item(row, 'values'))
        cur = vals[1]
        # create entry
        if self._editing_entry:
            self._editing_entry.destroy()
        edit = ttk.Entry(self.tree, width=40)
        edit.insert(0, cur)
        edit.place(x=x, y=y, width=width, height=height)
        edit.focus_set()
        self._editing_entry = edit

        def finish(event=None):
            newval = edit.get().strip()
            edit.destroy()
            self._editing_entry = None
            # update tree
            vals[1] = newval
            self.tree.item(row, values=vals)
            # update entries data
            idx = self.item_map.get(row)
            if idx is not None and idx < len(self.entries):
                orig, old_new, fh, sz, title, author = self.entries[idx]
                # store updated new filename
                self.entries[idx] = (orig, newval, fh, sz, title, author)

        edit.bind('<Return>', finish)
        edit.bind('<FocusOut>', finish)

    def rename_selected(self):
        sels = self.tree.selection()
        if not sels:
            messagebox.showinfo('Seleccionar', 'Seleccione una o más filas para renombrar')
            return
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        conflicts = []
        for iid in sels:
            idx = self.item_map.get(iid)
            if idx is None or idx >= len(self.entries):
                continue
            orig, new, fh, sz, title, author = self.entries[idx]
            src = Path(orig)
            dst = Path(folder) / new
            if dst.exists():
                base = dst.stem
                i = 1
                while True:
                    candidate = Path(folder) / f"{base} ({i}){dst.suffix}"
                    if not candidate.exists():
                        dst = candidate
                        break
                    i += 1
            try:
                shutil.move(str(src), str(dst))
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        # refresh view
        self.scan()

    def delete_duplicates(self):
        # build groups: hash -> list of (path, size)
        groups = {}
        for orig, new, fh, sz in self.entries:
            if not fh:
                continue
            groups.setdefault(fh, []).append((orig, sz))
        dup_groups = {h: items for h, items in groups.items() if len(items) > 1}
        if not dup_groups:
            messagebox.showinfo('Duplicados', 'No se encontraron archivos duplicados')
            return

        # Create selection dialog
        dlg = tk.Toplevel(self.root)
        dlg.title('Seleccionar copias a conservar')
        dlg.geometry('800x500')
        frm = ttk.Frame(dlg)
        frm.pack(fill='both', expand=True)

        canvas = tk.Canvas(frm)
        scrollbar = ttk.Scrollbar(frm, orient='vertical', command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        group_vars = {}
        group_info = []  # list of (hash, list of (path,size))
        for h, items in dup_groups.items():
            group_info.append((h, items))

        for gi, (h, items) in enumerate(group_info):
            lf = ttk.LabelFrame(scroll_frame, text=f'Grupo {gi+1} — {len(items)} archivos')
            lf.pack(fill='x', padx=6, pady=6, anchor='n')
            var = tk.IntVar(value=0)
            # default: keep largest file
            max_idx = 0
            max_size = -1
            for idx, (p, sz) in enumerate(items):
                if sz and sz > max_size:
                    max_size = sz
                    max_idx = idx
            var.set(max_idx)
            group_vars[h] = var
            for idx, (p, sz) in enumerate(items):
                text = f"{os.path.basename(p)} — {human_readable_size(sz)}\n{p}"
                rb = ttk.Radiobutton(lf, text=text, variable=var, value=idx)
                rb.pack(fill='x', padx=4, pady=2, anchor='w')

        btns = ttk.Frame(dlg)
        btns.pack(fill='x', pady=6)
        def on_cancel():
            dlg.destroy()
        def on_apply():
            errors = []
            deleted = 0
            for h, items in group_info:
                keep_idx = group_vars[h].get()
                for idx, (p, sz) in enumerate(items):
                    if idx == keep_idx:
                        continue
                    try:
                        os.remove(p)
                        deleted += 1
                    except Exception as e:
                        errors.append((p, e))
            dlg.destroy()
            if errors:
                messagebox.showerror('Errores', f'Ocurrieron errores al eliminar {len(errors)} archivos')
            else:
                messagebox.showinfo('Listo', f'Eliminados {deleted} archivos duplicados')
            self.scan()

        ttk.Button(btns, text='Cancelar', command=on_cancel).pack(side='right', padx=6)
        ttk.Button(btns, text='Eliminar seleccionados', command=on_apply).pack(side='right')

if __name__ == '__main__':
    root = tk.Tk()
    app = RenamerApp(root)
    root.mainloop()
