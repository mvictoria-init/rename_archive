"""Interfaz Tkinter para renombrar libros apoyada en metadatos y modelos ML.

Incluye carga de carpetas, sugerencias de nombres, comparación con biblioteca
externa e indexado incremental sobre SQLite.
"""

import os
import re
import shutil
import threading
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING
import json

from .utils import sanitize, normalize_authors, format_authors_for_filename, human_readable_size, normalize_title_case, normalize_author_case
from .metadata import extract_metadata
import sqlite3
from .index import db_exists, files_in_folder, DB_PATH

if TYPE_CHECKING:
    # No se requieren importaciones de indexer: funcionalidad eliminada.
    pass


class RenamerApp:
    """Ventana principal: lista archivos, sugiere nombres y gestiona acciones."""

    def __init__(self, root):
        self.root = root
        root.title('Renombrador por Autor y Título')
        # Apply dark theme colors and ttk styles for a modern, low-light UI
        
        bg = '#10141d'
        accent = '#38bdf8'
        text_main = '#e2e8f0'
        header_bg = '#1a1f2c'
        selection = '#2d3748'

        tabla_bg = '#1a1f2c'
        tabla_texto = text_main

        # Dialog-specific palette for contrasty cards
        dialog_bg = '#0f0c12'
        dialog_card_bg = '#1d1821'
        dialog_text = '#f4f0ff'
        dialog_muted = '#cfc7dd'
        dialog_local = '#9ad5ff'
        dialog_remote = '#f7b87b'
        try:
            root.configure(bg=bg)
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        # Base widget backgrounds
        style.configure('TFrame', background=bg)
        style.configure('TLabel', background=bg, foreground=text_main, font=('Segoe UI', 11))
        style.configure('TButton', background=bg, foreground=text_main, font=('Segoe UI', 10))

        # Minimalist scrollbar
        style.configure('Vertical.TScrollbar',
                        background=header_bg, troughcolor=bg,
                        bordercolor=bg, arrowcolor=text_main,
                        relief='flat', borderwidth=0, width=12)
        style.configure('Horizontal.TScrollbar',
                        background=header_bg, troughcolor=bg,
                        bordercolor=bg, arrowcolor=text_main,
                        relief='flat', borderwidth=0, arrowsize=12)

        # Treeview: borderless with large rowheight for air/spacing
        style.configure('Treeview', 
                        background=tabla_bg, 
                        fieldbackground=tabla_bg, 
                        foreground=tabla_texto,
                        font=('Segoe UI', 11),
                        rowheight=35,
                        borderwidth=0,
                        relief='flat')
        style.configure('Treeview.Heading', 
                        background='#222a3b', 
                        foreground=text_main,
                        font=('Segoe UI', 11, 'bold'),
                        borderwidth=0,
                        relief='flat',
                        padding=5)
        
        style.map('Treeview', 
                  background=[('selected', selection)], 
                  foreground=[('selected', '#ffffff')])
        
        style.configure('RoundedAccent.TButton', 
                        background=accent, 
                        foreground='#10141d', 
                        font=('Segoe UI', 10, 'bold'),
                        padding=(10, 8),
                        relief='flat',
                        borderwidth=0)
        style.map('RoundedAccent.TButton',
                  background=[('active', '#7dd3fc')])

        style.configure('Secondary.TButton', 
                        background='#334155', 
                        foreground=text_main, 
                        font=('Segoe UI', 10, 'bold'),
                        padding=(10, 8),
                        relief='flat',
                        borderwidth=0)
        style.map('Secondary.TButton',
                  background=[('active', '#475569')])

        # Accent frame/label styles
        style.configure('Accent.TFrame', background=header_bg)
        style.configure('Accent.TLabel', background=header_bg, foreground=text_main)
        style.configure('Accent.TButton', background=accent, foreground='#10141d')
        self._app_bg = bg
        self._accent = accent
        # Dialog colors stored for reuse
        self._dialog_bg = dialog_bg
        self._dialog_card_bg = dialog_card_bg
        self._dialog_text = dialog_text
        self._dialog_muted = dialog_muted
        self._dialog_local = dialog_local
        self._dialog_remote = dialog_remote
        # App-wide darker background used for additional style touches
        self.bg_color = '#1f1b22'
        # Persistence for edited proposals (session recovery)
        try:
            state_dir = Path(__file__).resolve().parent.parent / '.state'
            state_dir.mkdir(parents=True, exist_ok=True)
            self._state_dir = state_dir
            self._proposals_file = self._state_dir / 'proposals.json'
        except Exception:
            self._state_dir = Path('.')
            self._proposals_file = self._state_dir / 'proposals.json'
        self._saved_proposals = {}
        self._save_after_id = None
        try:
            # Ensure common ttk widget backgrounds align with dark theme
            try:
                style.theme_use(style.theme_use())
            except Exception:
                pass
            style.configure('TLabelframe', background=self.bg_color)
            style.configure('TLabelframe.Label', background=self.bg_color, foreground=text_main)
        except Exception:
            pass
        try:
            root.configure(bg=self.bg_color)
        except Exception:
            pass
        # Rounded button styles: neutral and accent variants (dark)
        try:
            style.configure('Rounded.TButton', background=header_bg, foreground=text_main, relief='flat', font=('Segoe UI', 10, 'bold'), padding=(10, 6), borderwidth=0)
            style.map('Rounded.TButton', background=[('active', '#334155')])
            style.configure('RoundedAccent.TButton', background=self._accent, foreground='#10141d', font=('Segoe UI', 10, 'bold'), relief='flat', padding=(10, 6), borderwidth=0)
            style.map('RoundedAccent.TButton', background=[('active', '#7dd3fc')])
            # Dialog specific styles
            style.configure('Dialog.TFrame', background=self._dialog_bg)
            style.configure('Dialog.TLabelframe', background=self._dialog_card_bg, borderwidth=1, relief='solid')
            style.configure('Dialog.TLabelframe.Label', background=self._dialog_card_bg, foreground=self._dialog_text)
            style.configure('Dialog.TLabel', background=self._dialog_card_bg, foreground=self._dialog_text)
            style.configure('Dialog.TRadiobutton', background=self._dialog_card_bg, foreground=self._dialog_text)
            style.map('Dialog.TRadiobutton', background=[('active', '#2a2230')], foreground=[('active', '#ffffff')])
        except Exception:
            pass
        self.folder = tk.StringVar()
        # current scan thread (to avoid overlapping scans)
        self._scan_thread = None
        # enable automatic model suggestions after a scan
        # disabled by default to avoid mass unsolicited proposals
        self.auto_suggest_on_scan = False

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill='both', expand=True)

        top = ttk.Frame(frm, style='Accent.TFrame')
        top.pack(fill='x', pady=(0,6))
        ttk.Button(top, text='Seleccionar carpeta', command=self.select_folder, style='Secondary.TButton').pack(side='left')
        ttk.Label(top, textvariable=self.folder, style='Accent.TLabel').pack(side='left', padx=8)

        self.status = tk.StringVar(value='')
        ttk.Label(frm, textvariable=self.status).pack(fill='x')

        content = ttk.Frame(frm)
        content.pack(fill='both', expand=True)

        # Treeview with scrollbars
        tree_frame = ttk.Frame(content)
        tree_frame.pack(fill='both', expand=True, pady=8)

        self.tree = ttk.Treeview(tree_frame, columns=('orig', 'new'), show='headings', style='Treeview')
        self.tree.heading('orig', text='Original')
        self.tree.heading('new', text='Propuesto')

        vs = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview, style='Vertical.TScrollbar')
        hs = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview, style='Horizontal.TScrollbar')
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        # Ensure duplicate tag has high contrast on dark theme
        try:
            self.tree.tag_configure('dup', background='#ffdce0', foreground='#3a0000')
        except Exception:
            pass

        # layout with grid so scrollbars align
        self.tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # mouse wheel scrolling (Windows/Mac/Linux adjustments)
        def _on_mousewheel(event):
            # Windows: event.delta is multiple of 120
            delta = 0
            try:
                delta = int(-1 * (event.delta / 120))
            except Exception:
                # Linux: event.num 4/5
                if hasattr(event, 'num'):
                    if event.num == 4:
                        delta = -1
                    elif event.num == 5:
                        delta = 1
            if delta:
                self.tree.yview_scroll(delta, 'units')

        # bind wheel to tree
        self.tree.bind('<MouseWheel>', _on_mousewheel)
        self.tree.bind('<Button-4>', _on_mousewheel)
        self.tree.bind('<Button-5>', _on_mousewheel)

        # (no preview panel)

        # mapping from tree item id to entries index
        self.item_map = {}
        self.entries = []
        self._next_iid = 0
        # UI bindings
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select())
        self._editing_entry = None
        self._editing_row = None
        self._editing_col = None
        self.tree.bind('<Double-1>', self.on_double_click)
        # Single-click editing (user requested)
        try:
            self.tree.bind('<ButtonRelease-1>', self.on_single_click)
        except Exception:
            pass
        # Track last clicked cell for clipboard operations
        self._last_clicked_row = None
        self._last_clicked_col = None
        # Global clipboard shortcuts
        try:
            root.bind_all('<Control-c>', self._on_copy)
            root.bind_all('<Control-x>', self._on_cut)
            root.bind_all('<Control-v>', self._on_paste)
        except Exception:
            pass

        bottom = ttk.Frame(frm, style='Accent.TFrame')
        bottom.pack(fill='x', pady=(6,0))
        self.scan_btn = ttk.Button(bottom, text='Escanear', command=self.scan, style='RoundedAccent.TButton')
        self.scan_btn.pack(side='left', padx=(0,6))
        self.rename_btn = ttk.Button(bottom, text='Renombrar', command=self.rename_files, style='RoundedAccent.TButton')
        self.rename_btn.pack(side='left', padx=6)
        self.rename_selected_btn = ttk.Button(bottom, text='Renombrar seleccionado', command=self.rename_selected, style='Secondary.TButton')
        self.rename_selected_btn.pack(side='left', padx=6)
        self.delete_dup_btn = ttk.Button(bottom, text='Eliminar duplicados', command=self.delete_duplicates, style='Secondary.TButton')
        self.delete_dup_btn.pack(side='left', padx=6)
        self.delete_file_btn = ttk.Button(bottom, text='Eliminar archivo', command=self.delete_selected_file, style='Secondary.TButton')
        self.delete_file_btn.pack(side='left', padx=6)
        self.refine_btn = ttk.Button(bottom, text='Refinar propuesta', command=self.refine_selected_proposals, style='Secondary.TButton')
        self.refine_btn.pack(side='left', padx=6)

        # load saved proposals from previous session (if any)
        try:
            self._load_saved_proposals()
        except Exception:
            self._saved_proposals = {}

    # Biblioteca / indexado eliminado: la funcionalidad de seleccionar una
    # carpeta para indexar y comparar con la biblioteca fue retirada.

    # Comparación con biblioteca eliminada: resolver duplicados externos ya no está disponible.

    def _maybe_auto_model(self):
        """Auto-suggest eliminado: placeholder no funcional."""
        return

    def select_folder(self):
        """Abre un diálogo para seleccionar la carpeta a procesar.

        Por qué: punto de entrada para elegir la raíz desde la que se escanean
        y renombrarán los archivos en la interfaz.
        """
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

    def scan(self):
        """Escanea la carpeta seleccionada y rellena la vista de archivos.

        Qué hace: intenta cargar entradas desde el índice si existe; si no,
        recorre el filesystem. Inicia un trabajador en background y actualiza
        la vista (Treeview). Por qué: cargar la lista de archivos a renombrar.
        """
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self.scan_btn.state(['disabled'])
        self.rename_btn.state(['disabled'])
        self.tree.delete(*self.tree.get_children())
        self.entries = []
        self.item_map = {}
        self._next_iid = 0
        self.status.set('Escaneando...')
        # Fast path: if an index DB exists and contains entries for this folder,
        # load from the DB instead of scanning the filesystem (much faster),
        # then run an incremental background pass to index new/changed files.
        try:
            folder_path = Path(folder).resolve()
            if db_exists():
                sha_map = {}
                rows = list(files_in_folder(folder_path))
                if rows:
                    # Filter out DB entries whose files no longer exist on disk.
                    missing = []
                    filtered_rows = []
                    for r in rows:
                        p = Path(r['path'])
                        if not p.exists():
                            missing.append(r['path'])
                            continue
                        filtered_rows.append(r)
                    # If any missing entries, remove them from the DB to avoid stale results
                    if missing:
                        try:
                            conn = sqlite3.connect(str(DB_PATH))
                            cur = conn.cursor()
                            for mp in missing:
                                try:
                                    cur.execute('DELETE FROM files WHERE path=?', (mp,))
                                except Exception:
                                    pass
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
                    rows = filtered_rows
                    for r in rows:
                        p = Path(r['path'])
                        title = r.get('title')
                        author = r.get('authors')
                        ext = p.suffix
                        # normalize title for consistent display (only initial uppercase)
                        try:
                            title_norm = normalize_title_case(title) if title else None
                        except Exception:
                            title_norm = title
                        # normalize authors for filename (comma-separated) and case
                        try:
                            auth_norm_raw = normalize_authors(author) if author else None
                        except Exception:
                            auth_norm_raw = author
                        author_for_filename = ''
                        try:
                            if auth_norm_raw:
                                if isinstance(auth_norm_raw, str):
                                    parts_ = [pp.strip() for pp in auth_norm_raw.split(',') if pp.strip()]
                                    parts_ = [normalize_author_case(pp) for pp in parts_]
                                    author_for_filename = ', '.join(parts_)
                                else:
                                    author_for_filename = auth_norm_raw
                        except Exception:
                            author_for_filename = auth_norm_raw or ''
                        t = sanitize(str(title_norm)) if title_norm else ''
                        a = format_authors_for_filename(author_for_filename, max_authors=3) if author_for_filename else ''
                        if a and t:
                            new = f"{a} - {t}{ext}"
                        elif t:
                            new = f"{t}{ext}"
                        elif a:
                            new = f"{a}{ext}"
                        else:
                            new = p.name
                        fh = r.get('sha256')
                        sz = r.get('size')
                        idx = len(self.entries)
                        # store normalized title/author in entries for consistent downstream behavior
                        self.entries.append((str(p), p.name, new, fh, sz, title_norm, author_for_filename))
                        iid = f'i{self._next_iid}'
                        self._next_iid += 1
                        tags = ()
                        try:
                            self.tree.insert('', 'end', iid=iid, values=(p.name, new), tags=tags)
                        except Exception:
                            self.tree.insert('', 'end', values=(p.name, new))
                        self.item_map[iid] = idx
                        # If the file already has the name the user previously saved,
                        # remove the saved proposal so it doesn't persist unnecessarily.
                        try:
                            sp = getattr(self, '_saved_proposals', None)
                            if sp and isinstance(sp, dict):
                                by_hash = sp.get('by_hash', {}) if isinstance(sp.get('by_hash', {}), dict) else {}
                                by_path = sp.get('by_path', {}) if isinstance(sp.get('by_path', {}), dict) else {}
                                actual_name = p.name
                                if fh and str(fh) in by_hash and by_hash.get(str(fh)) == actual_name:
                                    try:
                                        self._remove_saved_for(path=str(p), fh=fh)
                                        self._save_proposals_now()
                                    except Exception:
                                        pass
                                elif str(p) in by_path and by_path.get(str(p)) == actual_name:
                                    try:
                                        self._remove_saved_for(path=str(p), fh=fh)
                                        self._save_proposals_now()
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        if fh:
                            sha_map.setdefault(fh, []).append(iid)
                    # mark duplicates (same sha256) with tag 'dup'
                    for h, iids in sha_map.items():
                        if len(iids) > 1:
                            for ii in iids:
                                try:
                                    existing = set(self.tree.item(ii, 'tags') or ())
                                    existing.add('dup')
                                    self.tree.item(ii, tags=tuple(existing))
                                except Exception:
                                    pass
                    self.status.set('Escaneo desde índice completado')
                    self.scan_btn.state(['!disabled'])
                    self.rename_btn.state(['!disabled'])
                    try:
                        self.tree.tag_configure('dup', background='#ffdce0', foreground='#3a0000')
                    except Exception:
                        pass

                    # apply saved proposals from previous session (if any)
                    try:
                        self._apply_saved_proposals()
                    except Exception:
                        pass

                    # suggest with the model automatically if enabled
                    self._maybe_auto_model()

                    # start incremental background worker to detect new/changed files
                    def incremental_worker(folder_path):
                        try:
                            conn = sqlite3.connect(str(DB_PATH))
                            cur = conn.cursor()
                            local_sha_map = {}
                            seen_paths = set()
                            # build quick map of existing DB entries for folder
                            cur.execute('SELECT path,size,mtime,sha256,title,authors FROM files WHERE path LIKE ?', (str(folder_path) + '%',))
                            db_map = {row[0]: {'size': row[1], 'mtime': row[2], 'sha': row[3], 'title': row[4], 'authors': row[5]} for row in cur.fetchall()}
                            for p in folder_path.rglob('*'):
                                if not p.is_file():
                                    continue
                                sp = str(p)
                                try:
                                    st = p.stat()
                                except Exception:
                                    continue
                                size = st.st_size
                                mtime = st.st_mtime
                                db_row = db_map.get(sp)
                                if db_row and db_row.get('size') == size and abs((db_row.get('mtime') or 0) - mtime) < 1.0:
                                    # unchanged
                                    seen_paths.add(sp)
                                    continue
                                # new or changed: compute sha, extract metadata and upsert
                                fh = None
                                try:
                                    with open(p, 'rb') as fhf:
                                        import hashlib as _hash
                                        h = _hash.sha256()
                                        for chunk in iter(lambda: fhf.read(65536), b''):
                                            h.update(chunk)
                                        fh = h.hexdigest()
                                except Exception:
                                    fh = None
                                title = None
                                authors = None
                                new_pro = None
                                try:
                                    title, authors, subtitle = extract_metadata(p)
                                except Exception:
                                    title, authors, subtitle = (None, None, None)
                                # Normalize title and authors before building proposal and saving to DB
                                try:
                                    title_norm = normalize_title_case(title) if title else None
                                except Exception:
                                    title_norm = title
                                try:
                                    auth_norm_raw = normalize_authors(authors) if authors else None
                                except Exception:
                                    auth_norm_raw = authors
                                author_for_filename = ''
                                try:
                                    if auth_norm_raw:
                                        if isinstance(auth_norm_raw, str):
                                            parts_ = [pp.strip() for pp in auth_norm_raw.split(',') if pp.strip()]
                                            parts_ = [normalize_author_case(pp) for pp in parts_]
                                            author_for_filename = ', '.join(parts_)
                                        else:
                                            author_for_filename = auth_norm_raw
                                except Exception:
                                    author_for_filename = auth_norm_raw or ''
                                # build a filename proposal from available metadata
                                if title_norm or author_for_filename or subtitle:
                                    a = format_authors_for_filename(author_for_filename, max_authors=3) if author_for_filename else ''
                                    t = sanitize(str(title_norm)) if title_norm else ''
                                    s = sanitize(str(subtitle)) if subtitle else ''
                                    ext = p.suffix
                                    if a and t:
                                        if s:
                                            new_pro = f"{a} - {t} - {s}{ext}"
                                        else:
                                            new_pro = f"{a} - {t}{ext}"
                                    elif t:
                                        if s:
                                            new_pro = f"{t} - {s}{ext}"
                                        else:
                                            new_pro = f"{t}{ext}"
                                    elif a:
                                        new_pro = f"{a}{ext}"
                                    else:
                                        new_pro = p.name
                                # upsert into DB (store normalized values)
                                indexed_at = datetime.utcnow().isoformat()
                                try:
                                    cur.execute('INSERT OR REPLACE INTO files(path,relpath,size,mtime,sha256,title,authors,indexed_at) VALUES(?,?,?,?,?,?,?,?)',
                                                (sp, str(p.relative_to(folder_path)), size, mtime, fh, title_norm, str(author_for_filename) if author_for_filename else None, indexed_at))
                                    conn.commit()
                                except Exception:
                                    pass
                                # update tree: append new entry and mark duplicates later
                                def add_row_to_tree():
                                    idx = len(self.entries)
                                    p_name = p.name
                                    new = new_pro if new_pro else p_name
                                    # store normalized title and author in entries
                                    self.entries.append((sp, p_name, new, fh, size, title_norm, author_for_filename))
                                    iid = f'i{self._next_iid}'
                                    self._next_iid += 1
                                    try:
                                        self.tree.insert('', 'end', iid=iid, values=(p_name, new))
                                    except Exception:
                                        self.tree.insert('', 'end', values=(p_name, new))
                                    self.item_map[iid] = idx
                                    # cleanup saved proposals if file is already named as the saved proposal
                                    try:
                                        saved = getattr(self, '_saved_proposals', None)
                                        if saved and isinstance(saved, dict):
                                            by_hash = saved.get('by_hash', {}) if isinstance(saved.get('by_hash', {}), dict) else {}
                                            by_path = saved.get('by_path', {}) if isinstance(saved.get('by_path', {}), dict) else {}
                                            actual_name = p_name
                                            if fh and str(fh) in by_hash and by_hash.get(str(fh)) == actual_name:
                                                try:
                                                    self._remove_saved_for(path=str(sp), fh=fh)
                                                    self._save_proposals_now()
                                                except Exception:
                                                    pass
                                            elif str(sp) in by_path and by_path.get(str(sp)) == actual_name:
                                                try:
                                                    self._remove_saved_for(path=str(sp), fh=fh)
                                                    self._save_proposals_now()
                                                except Exception:
                                                    pass
                                    except Exception:
                                        pass
                                    if fh:
                                        local_sha_map.setdefault(fh, []).append(iid)
                                self.root.after(0, add_row_to_tree)
                            # after scanning, mark duplicates found in incremental pass
                            for h, iids in local_sha_map.items():
                                if len(iids) > 1:
                                    for ii in iids:
                                        try:
                                            existing = set(self.tree.item(ii, 'tags') or ())
                                            existing.add('dup')
                                            self.tree.item(ii, tags=tuple(existing))
                                        except Exception:
                                            pass
                            conn.close()
                            # final UI update
                            def on_done_inc():
                                self.status.set('Escaneo incremental completado')
                                try:
                                    self._apply_saved_proposals()
                                except Exception:
                                    pass
                            self.root.after(0, on_done_inc)
                        except Exception:
                            pass

                    t_inc = threading.Thread(target=incremental_worker, args=(folder_path,), daemon=True)
                    t_inc.start()
                    return
        except Exception:
            pass

        def file_hash(path, block_size=65536):
            h = hashlib.sha256()
            try:
                with open(path, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(block_size), b''):
                        h.update(chunk)
                return h.hexdigest()
            except Exception:
                return None

        def worker(folder_path):
            p = Path(folder_path)
            hash_map = {}
            for f in p.iterdir():
                if f.is_file():
                    try:
                        title, author, subtitle = extract_metadata(f)
                    except Exception:
                        title, author, subtitle = (None, None, None)
                    if not title and not author and not subtitle:
                        try:
                            from .utils import guess_title_author_from_filename
                            g_title, g_author = guess_title_author_from_filename(f.name)
                            title = title or g_title
                            author = author or g_author
                        except Exception:
                            pass
                    # Normalize title/author and build proposal
                    try:
                        title_norm = normalize_title_case(title) if title else None
                    except Exception:
                        title_norm = title
                    try:
                        auth_norm_raw = normalize_authors(author) if author else None
                    except Exception:
                        auth_norm_raw = author
                    author_for_filename = ''
                    try:
                        if auth_norm_raw:
                            if isinstance(auth_norm_raw, str):
                                parts_ = [pp.strip() for pp in auth_norm_raw.split(',') if pp.strip()]
                                parts_ = [normalize_author_case(pp) for pp in parts_]
                                author_for_filename = ', '.join(parts_)
                            else:
                                author_for_filename = auth_norm_raw
                    except Exception:
                        author_for_filename = auth_norm_raw or ''

                    a = format_authors_for_filename(author_for_filename, max_authors=3) if author_for_filename else ''
                    t = sanitize(str(title_norm)) if title_norm else ''
                    s = sanitize(str(subtitle)) if subtitle else ''
                    ext = f.suffix
                    if a and t:
                        if s:
                            new = f"{a} - {t} - {s}{ext}"
                        else:
                            new = f"{a} - {t}{ext}"
                    elif t:
                        if s:
                            new = f"{t} - {s}{ext}"
                        else:
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
                    # store: full path, display name, proposed new name, hash, size, normalized title, normalized author
                    self.entries.append((str(f), f.name, new, file_h, size_val, title_norm, author_for_filename))

                    def insert_item(fname=f.name, nname=new, fh=file_h, sz=size_val):
                        # create IID first
                        idx = len(self.entries) - 1
                        iid = f'i{self._next_iid}'
                        self._next_iid += 1
                        tags = ()
                        # If we have a file hash, check if we've seen it before
                        if fh:
                            prev_iid = hash_map.get(fh)
                            if prev_iid:
                                # mark previous item as duplicate
                                try:
                                    prev_tags = set(self.tree.item(prev_iid, 'tags') or ())
                                    prev_tags.add('dup')
                                    self.tree.item(prev_iid, tags=tuple(prev_tags))
                                except Exception:
                                    pass
                                tags = ('dup',)
                            else:
                                # first time we see this hash: record this iid
                                hash_map[fh] = iid

                        self.tree.insert('', 'end', iid=iid, values=(fname, nname), tags=tags)
                        self.item_map[iid] = idx
                        # if the file already matches a saved proposal, remove it
                        try:
                            sp = getattr(self, '_saved_proposals', None)
                            if sp and isinstance(sp, dict):
                                by_hash = sp.get('by_hash', {}) if isinstance(sp.get('by_hash', {}), dict) else {}
                                by_path = sp.get('by_path', {}) if isinstance(sp.get('by_path', {}), dict) else {}
                                actual_name = fname
                                # determine orig path from entries list (worker appended it earlier)
                                orig_path = None
                                try:
                                    if idx is not None and idx < len(self.entries):
                                        orig_path = self.entries[idx][0]
                                except Exception:
                                    orig_path = None
                                if fh and str(fh) in by_hash and by_hash.get(str(fh)) == actual_name:
                                    try:
                                        self._remove_saved_for(path=orig_path, fh=fh)
                                        self._save_proposals_now()
                                    except Exception:
                                        pass
                                elif orig_path and orig_path in by_path and by_path.get(orig_path) == actual_name:
                                    try:
                                        self._remove_saved_for(path=orig_path, fh=fh)
                                        self._save_proposals_now()
                                    except Exception:
                                        pass
                                else:
                                    # fallback: if basename unique in by_path and equals actual_name
                                    if orig_path is None:
                                        bname = fname
                                        cands = [k for k in by_path.keys() if os.path.basename(k) == bname]
                                        if len(cands) == 1:
                                            try:
                                                self._remove_saved_for(path=cands[0], fh=fh)
                                                self._save_proposals_now()
                                            except Exception:
                                                pass
                        except Exception:
                            pass

                    self.root.after(0, insert_item)

            def on_done():
                self.status.set('Escaneo completado')
                self.scan_btn.state(['!disabled'])
                self.rename_btn.state(['!disabled'])
                try:
                    self.tree.tag_configure('dup', background='#ffdce0', foreground='#3a0000')
                except Exception:
                    pass
                # apply saved proposals from previous session (if any)
                try:
                    self._apply_saved_proposals()
                except Exception:
                    pass
                # suggest with the model automatically if enabled
                self._maybe_auto_model()

            self.root.after(0, on_done)

        t = threading.Thread(target=worker, args=(folder,), daemon=True)
        self._scan_thread = t
        t.start()

    def rename_files(self):
        """Renombra todos los archivos listados según la propuesta actual.

        Qué hace: mueve/renombra archivos en la carpeta seleccionada, manejando
        colisiones de nombres y acumulando errores para informar al usuario.
        Por qué: operación principal que aplica las propuestas generadas.
        """
        if not self.entries:
            messagebox.showinfo('Nada', 'No hay archivos para renombrar. Escanee primero.')
            return
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        self.rename_btn.state(['disabled'])
        conflicts = []
        renamed_paths = []
        for orig, disp, new, fh, sz, title, author in list(self.entries):
            src = Path(orig)
            safe_new = sanitize(new)
            dst = Path(folder) / safe_new
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
                renamed_paths.append((orig, fh))
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        self.rename_btn.state(['!disabled'])
        # remove saved proposals for files that were successfully renamed
        if renamed_paths:
            try:
                for p, fh in renamed_paths:
                    try:
                        self._remove_saved_for(path=str(p), fh=fh)
                    except Exception:
                        pass
                # persist immediately so a crash won't resurrect old proposals
                try:
                    self._save_proposals_now()
                except Exception:
                    try:
                        self._schedule_save_proposals()
                    except Exception:
                        pass
            except Exception:
                pass
        self.scan()

    # Conversión a EPUB eliminada: la funcionalidad fue removida.

    def delete_selected_file(self):
        """Elimina los archivos seleccionados del disco y actualiza la vista.

        Qué hace: confirma con el usuario, borra los ficheros y reconstruye la
        lista interna y el Treeview. Por qué: permitir limpiar elementos no
        deseados antes de renombrar o exportar.
        """
        sels = self.tree.selection()
        if not sels:
            messagebox.showinfo('Eliminar', 'Seleccione uno o más archivos para eliminar')
            return
        if not messagebox.askyesno('Confirmar eliminación', f'¿Eliminar {len(sels)} archivo(s)? Esta acción no se puede deshacer.'):
            return
        removed_items = []
        errors = []
        for iid in list(sels):
            idx = self.item_map.get(iid)
            if idx is None or idx >= len(self.entries):
                continue
            orig, disp, proposed, fh, sz, title, author = self.entries[idx]
            try:
                if os.path.exists(orig):
                    os.remove(orig)
                removed_items.append((orig, fh))
            except Exception as e:
                errors.append((orig, str(e)))

        # remove deleted entries from internal list and rebuild tree
        if removed_items:
            # remove any saved proposals for the files that were deleted
            try:
                for p, fh in removed_items:
                    try:
                        self._remove_saved_for(path=str(p), fh=fh)
                    except Exception:
                        pass
                try:
                    self._save_proposals_now()
                except Exception:
                    try:
                        self._schedule_save_proposals()
                    except Exception:
                        pass
            except Exception:
                pass
            self.entries = [e for e in self.entries if e[0] not in set([it[0] for it in removed_items])]
            self.tree.delete(*self.tree.get_children())
            self.item_map = {}
            # simple rebuild, without preserving duplicate tags
            # rebuild using the global iid counter to avoid collisions
            for idx, entry in enumerate(self.entries):
                orig, disp, proposed, fh, sz, title, author = entry
                iid = f'i{self._next_iid}'
                self._next_iid += 1
                self.tree.insert('', 'end', iid=iid, values=(disp, proposed))
                self.item_map[iid] = idx
            try:
                self._schedule_save_proposals()
            except Exception:
                pass

        if errors:
            messagebox.showerror('Errores', f'Ocurrieron errores al eliminar {len(errors)} archivos')
        else:
            messagebox.showinfo('Listo', f'Eliminados {len(removed_items)} archivos')

    def refine_selected_proposals(self):
        """Refina las propuestas usando metadata y heurísticas del filename.

        Qué hace: para los elementos seleccionados (o todos si no hay selección)
        intenta mejorar la propuesta combinando metadata y heurísticas.
        Por qué: ofrecer nombres más precisos antes de aplicar cambios.
        """
        from .utils import guess_title_author_from_filename
        sels = self.tree.selection()
        target_idxs = []
        if sels:
            for iid in sels:
                idx = self.item_map.get(iid)
                if idx is not None and idx < len(self.entries):
                    target_idxs.append(idx)
        else:
            target_idxs = list(range(len(self.entries)))

        changed = 0
        for idx in target_idxs:
            orig, disp, proposed, fh, sz, title, author = self.entries[idx]
            # try metadata first
            tmeta, ameta = title, author
            # if no useful metadata, try to guess from filename or display name
            if not tmeta and not ameta:
                g_title, g_author = guess_title_author_from_filename(disp or orig)
            else:
                g_title, g_author = None, None

            final_title = tmeta or g_title
            final_author = ameta or g_author

            # format proposal
            a = format_authors_for_filename(normalize_authors(final_author), max_authors=3) if final_author else ''
            t = sanitize(final_title) if final_title else ''
            ext = Path(orig).suffix
            if a and t:
                newname = f"{a} - {t}{ext}"
            elif t:
                newname = f"{t}{ext}"
            elif a:
                newname = f"{a}{ext}"
            else:
                newname = disp or os.path.basename(orig)

            # sanitize the final filename proposal to avoid invalid chars
            newname = sanitize(newname)
            if newname != proposed:
                self.entries[idx] = (orig, disp, newname, fh, sz, final_title, final_author)
                changed += 1

        if changed:
            # refresh tree values for visible items
            for iid, idx in list(self.item_map.items()):
                if idx < len(self.entries):
                    orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                    try:
                        self.tree.item(iid, values=(disp, proposed))
                    except Exception:
                        pass
            try:
                self._schedule_save_proposals()
            except Exception:
                pass
        messagebox.showinfo('Refinar', f'Actualizadas {changed} propuestas')

    def on_select(self):
        """Handler para selección en la Treeview (actualmente placeholder)."""
        return

    def on_double_click(self, event):
        """Permite editar en línea la celda doble-clicada (original/propuesto).

        Qué hace: crea un `Entry` temporal sobre la celda, captura el nuevo
        valor y lo escribe en `self.entries`. Por qué: permitir correcciones
        rápidas sin salir de la UI.
        """
        # Cancel any scheduled single-click editing to avoid conflict
        if getattr(self, '_single_click_after_id', None):
            try:
                self.root.after_cancel(self._single_click_after_id)
            except Exception:
                pass
            self._single_click_after_id = None

        # Open inline editor on double-click and select all text
        if getattr(self, '_single_click_after_id', None):
            try:
                self.root.after_cancel(self._single_click_after_id)
            except Exception:
                pass
            self._single_click_after_id = None

        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or not col:
            return
        col_index = 0 if col == '#1' else 1
        self._last_clicked_row = row
        self._last_clicked_col = col_index
        try:
            self.tree.focus(row)
            self.tree.selection_set(row)
        except Exception:
            pass
        # start inline edit and select all text for convenience
        try:
            self._start_inline_edit(row, col_index, select_all=True)
        except Exception:
            try:
                self._start_inline_edit(row, col_index)
            except Exception:
                pass
        return 'break'

    def _start_inline_edit(self, row, col_index, select_all=False):
        """Inicia el editor inline en la celda indicada."""
        col = '#1' if col_index == 0 else '#2'
        bbox = self.tree.bbox(row, column=col)
        if not bbox:
            return
        x, y, width, height = bbox
        vals = list(self.tree.item(row, 'values') or ('', ''))
        # ensure the list has at least two entries
        while len(vals) < 2:
            vals.append('')
        cur = vals[col_index]
        if self._editing_entry:
            try:
                self._editing_entry.destroy()
            except Exception:
                pass
        # use tk.Entry (avoid -undo option which is not supported on all Tk builds)
        edit = tk.Entry(self.tree, width=40)
        try:
            edit.insert(0, cur)
        except Exception:
            pass
        edit.place(x=x, y=y, width=width, height=height)
        edit.focus_set()
        self._editing_entry = edit
        # keep a single-level previous value to provide a Ctrl+Z undo fallback
        try:
            self._editing_prev_text = str(cur)
        except Exception:
            self._editing_prev_text = None
        # widget-local key bindings to override global handlers and enable undo
        def _entry_copy(evt=None):
            try:
                sel = None
                try:
                    sel = edit.selection_get()
                except Exception:
                    sel = edit.get()
                if sel is None:
                    sel = ''
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(str(sel))
                    self.status.set('Copiado al portapapeles')
                except Exception:
                    pass
            except Exception:
                pass
            return 'break'

        def _entry_cut(evt=None):
            try:
                # copy first
                _entry_copy()
                cur_text = ''
                try:
                    cur_text = edit.get()
                except Exception:
                    cur_text = ''
                new_text = ''
                try:
                    if hasattr(edit, 'selection_present') and edit.selection_present():
                        start = edit.index('sel.first')
                        end = edit.index('sel.last')
                        new_text = cur_text[:start] + cur_text[end:]
                    else:
                        new_text = ''
                except Exception:
                    try:
                        sel = edit.selection_get()
                        if sel:
                            idx = cur_text.find(sel)
                            if idx >= 0:
                                new_text = cur_text[:idx] + cur_text[idx+len(sel):]
                            else:
                                new_text = ''
                        else:
                            new_text = ''
                    except Exception:
                        new_text = ''
                try:
                    edit.delete(0, tk.END)
                    if new_text:
                        edit.insert(0, new_text)
                except Exception:
                    pass
                # reflect in tree and entries immediately
                row = getattr(self, '_editing_row', None)
                col_index_local = getattr(self, '_editing_col', None)
                if row is not None:
                    try:
                        vals = list(self.tree.item(row, 'values') or ('', ''))
                        while len(vals) <= (col_index_local or 1):
                            vals.append('')
                        vals[col_index_local if col_index_local is not None else 1] = edit.get()
                        try:
                            self.tree.item(row, values=vals)
                        except Exception:
                            pass
                        ent_idx = self.item_map.get(row)
                        if ent_idx is not None and ent_idx < len(self.entries):
                            orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                            if col_index_local == 0:
                                disp = edit.get()
                            else:
                                proposed = edit.get()
                            self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
                    except Exception:
                        pass
                try:
                    self._schedule_save_proposals()
                except Exception:
                    pass
            except Exception:
                pass
            return 'break'

        def _entry_paste(evt=None):
            try:
                data = None
                try:
                    data = self.root.clipboard_get()
                except Exception:
                    data = ''
                if data is None:
                    data = ''
                # insert at cursor or replace selection
                try:
                    if hasattr(edit, 'selection_present') and edit.selection_present():
                        start = edit.index('sel.first')
                        end = edit.index('sel.last')
                        edit.delete(start, end)
                        edit.insert(start, data)
                    else:
                        edit.insert(tk.INSERT, data)
                except Exception:
                    try:
                        edit.insert(tk.INSERT, data)
                    except Exception:
                        pass
                # reflect change
                row = getattr(self, '_editing_row', None)
                col_index_local = getattr(self, '_editing_col', None)
                if row is not None:
                    try:
                        vals = list(self.tree.item(row, 'values') or ('', ''))
                        while len(vals) <= (col_index_local or 1):
                            vals.append('')
                        vals[col_index_local if col_index_local is not None else 1] = edit.get()
                        try:
                            self.tree.item(row, values=vals)
                        except Exception:
                            pass
                        ent_idx = self.item_map.get(row)
                        if ent_idx is not None and ent_idx < len(self.entries):
                            orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                            if col_index_local == 0:
                                disp = edit.get()
                            else:
                                proposed = edit.get()
                            self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
                    except Exception:
                        pass
                try:
                    self._schedule_save_proposals()
                except Exception:
                    pass
            except Exception:
                pass
            return 'break'

        def _entry_undo(evt=None):
            try:
                prev = getattr(self, '_editing_prev_text', None)
                if prev is not None:
                    try:
                        edit.delete(0, tk.END)
                        edit.insert(0, prev)
                    except Exception:
                        pass
                    # reflect change in tree and entries
                    row_local = getattr(self, '_editing_row', None)
                    col_idx_local = getattr(self, '_editing_col', None)
                    if row_local is not None:
                        try:
                            vals2 = list(self.tree.item(row_local, 'values') or ('', ''))
                            while len(vals2) <= (col_idx_local or 1):
                                vals2.append('')
                            vals2[col_idx_local if col_idx_local is not None else 1] = edit.get()
                            try:
                                self.tree.item(row_local, values=vals2)
                            except Exception:
                                pass
                            ent_idx = self.item_map.get(row_local)
                            if ent_idx is not None and ent_idx < len(self.entries):
                                orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                                if col_idx_local == 0:
                                    disp = edit.get()
                                else:
                                    proposed = edit.get()
                                self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
                        except Exception:
                            pass
                    # single-level undo only
                    try:
                        self._editing_prev_text = None
                    except Exception:
                        pass
                    try:
                        self._schedule_save_proposals()
                    except Exception:
                        pass
            except Exception:
                pass
            return 'break'

        try:
            edit.bind('<Control-c>', _entry_copy)
            edit.bind('<Control-x>', _entry_cut)
            edit.bind('<Control-v>', _entry_paste)
            edit.bind('<Control-z>', _entry_undo)
        except Exception:
            pass
        # record which row/col is being edited so keyboard handlers can update immediately
        try:
            self._editing_row = row
            self._editing_col = col_index
        except Exception:
            self._editing_row = None
            self._editing_col = None

        def finish(event=None):
            try:
                newval = edit.get().strip()
            except Exception:
                newval = ''
            try:
                edit.destroy()
            except Exception:
                pass
            self._editing_entry = None
            try:
                vals[col_index] = newval
                self.tree.item(row, values=vals)
            except Exception:
                pass
            idx = self.item_map.get(row)
            if idx is not None and idx < len(self.entries):
                orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                if col_index == 0:
                    disp = newval
                else:
                    proposed = newval
                self.entries[idx] = (orig, disp, proposed, fh, sz, title, author)
                try:
                    self._schedule_save_proposals()
                except Exception:
                    pass
            # clear editing markers
            try:
                self._editing_row = None
                self._editing_col = None
            except Exception:
                pass

        def cancel(event=None):
            try:
                edit.destroy()
            except Exception:
                pass
            self._editing_entry = None
            try:
                self._editing_row = None
                self._editing_col = None
            except Exception:
                pass

        edit.bind('<Return>', finish)
        edit.bind('<FocusOut>', finish)
        edit.bind('<Escape>', cancel)

    def on_single_click(self, event):
        """Programar edición inline con debounce para evitar choque con doble clic."""
        # cancelar programaciones previas
        if getattr(self, '_single_click_after_id', None):
            try:
                self.root.after_cancel(self._single_click_after_id)
            except Exception:
                pass
            self._single_click_after_id = None

        try:
            x = event.x
            y = event.y
            self._single_click_after_id = self.root.after(220, lambda x=x, y=y: self._handle_single_click_coords(x, y))
        except Exception:
            try:
                self._handle_single_click_coords(event.x, event.y)
            except Exception:
                pass

    def _handle_single_click_coords(self, x, y):
        region = self.tree.identify('region', x, y)
        if region != 'cell':
            return
        col = self.tree.identify_column(x)
        row = self.tree.identify_row(y)
        if not row or not col:
            return
        if col not in ('#1', '#2'):
            return
        col_index = 0 if col == '#1' else 1
        self._last_clicked_row = row
        self._last_clicked_col = col_index
        self._start_inline_edit(row, col_index)

    def _on_copy(self, event=None):
        """Copiar texto de la celda activa o del editor inline al portapapeles."""
        # If focus is inside an input widget, let its local handlers run
        try:
            fw = self.root.focus_get()
            if fw is not None and (fw is self._editing_entry or isinstance(fw, tk.Entry) or isinstance(fw, tk.Text)):
                return 'break'
        except Exception:
            pass

        text = None
        try:
            # Prefer the widget with keyboard focus (handles Entry/Text reliably)
            fw = self.root.focus_get()
            if fw is not None:
                # try to get selected text from the focused widget
                try:
                    text = fw.selection_get()
                except Exception:
                    # fallback to full content if widget exposes get()
                    try:
                        text = fw.get()
                    except Exception:
                        text = None
            # If nothing from focus, fallback to inline editor reference
            if not text and self._editing_entry:
                try:
                    text = self._editing_entry.selection_get()
                except Exception:
                    try:
                        text = self._editing_entry.get()
                    except Exception:
                        text = None
            # Finally, fallback to treeview-selected cell
            if not text:
                row = self._last_clicked_row
                col = self._last_clicked_col
                if not row:
                    sels = self.tree.selection()
                    row = sels[0] if sels else None
                if row:
                    vals = list(self.tree.item(row, 'values') or ())
                    idx = col if col is not None else 1
                    if idx is None:
                        idx = 1
                    try:
                        text = vals[idx]
                    except Exception:
                        text = vals[-1] if vals else ''
        except Exception:
            text = None
        if text is not None:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(str(text))
                self.status.set('Copiado al portapapeles')
            except Exception:
                pass
        return 'break'

    def _on_cut(self, event=None):
        """Cortar (copiar y borrar) la celda/entrada actual."""
        # If focus is inside an input widget, let its local handlers run
        try:
            fw = self.root.focus_get()
            if fw is not None and (fw is self._editing_entry or isinstance(fw, tk.Entry) or isinstance(fw, tk.Text)):
                return 'break'
        except Exception:
            pass

        try:
            self._on_copy(event)
        except Exception:
            pass
        try:
            if self._editing_entry:
                try:
                    cur_text = ''
                    try:
                        cur_text = self._editing_entry.get()
                    except Exception:
                        cur_text = ''
                    # delete selection if present, else clear all
                        # Prefer using selection_present/index, but fallback to selection_get if needed
                        new_text = ''
                        try:
                            if hasattr(self._editing_entry, 'selection_present') and self._editing_entry.selection_present():
                                start = self._editing_entry.index('sel.first')
                                end = self._editing_entry.index('sel.last')
                                new_text = cur_text[:start] + cur_text[end:]
                            else:
                                # try to obtain selected substring and remove its first occurrence
                                try:
                                    sel = self._editing_entry.selection_get()
                                    if sel:
                                        idx = cur_text.find(sel)
                                        if idx >= 0:
                                            new_text = cur_text[:idx] + cur_text[idx+len(sel):]
                                        else:
                                            new_text = ''
                                    else:
                                        new_text = ''
                                except Exception:
                                    new_text = ''
                        except Exception:
                            try:
                                sel = self._editing_entry.selection_get()
                                if sel:
                                    idx = cur_text.find(sel)
                                    if idx >= 0:
                                        new_text = cur_text[:idx] + cur_text[idx+len(sel):]
                                    else:
                                        new_text = ''
                                else:
                                    new_text = ''
                            except Exception:
                                new_text = ''
                        # update entry widget
                        try:
                            self._editing_entry.delete(0, tk.END)
                            if new_text:
                                self._editing_entry.insert(0, new_text)
                        except Exception:
                            pass
                        # reflect change in treeview and entries immediately
                        row = getattr(self, '_editing_row', None)
                        col_index = getattr(self, '_editing_col', None)
                        if row is not None:
                            try:
                                vals = list(self.tree.item(row, 'values') or ('', ''))
                                # ensure list long enough
                                while len(vals) <= (col_index or 1):
                                    vals.append('')
                                vals[col_index if col_index is not None else 1] = new_text
                                try:
                                    self.tree.item(row, values=vals)
                                except Exception:
                                    pass
                                ent_idx = self.item_map.get(row)
                                if ent_idx is not None and ent_idx < len(self.entries):
                                    orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                                    if col_index == 0:
                                        disp = new_text
                                    else:
                                        proposed = new_text
                                    self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
                                try:
                                    self._schedule_save_proposals()
                                except Exception:
                                    pass
                            except Exception:
                                pass
                    except Exception:
                        try:
                            self._editing_entry.delete(0, tk.END)
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                row = self._last_clicked_row
                col = self._last_clicked_col
                if not row:
                    sels = self.tree.selection()
                    row = sels[0] if sels else None
                if row is not None:
                    vals = list(self.tree.item(row, 'values') or ())
                    idx = col if col is not None else 1
                    if idx is None:
                        idx = 1
                    if len(vals) > idx:
                        vals[idx] = ''
                        try:
                            self.tree.item(row, values=vals)
                        except Exception:
                            pass
                        ent_idx = self.item_map.get(row)
                        if ent_idx is not None and ent_idx < len(self.entries):
                            orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                            if idx == 0:
                                disp = ''
                            else:
                                proposed = ''
                            self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
        except Exception:
            pass
        try:
            self._schedule_save_proposals()
        except Exception:
            pass
        return 'break'

    def _on_paste(self, event=None):
        """Pegar contenido del portapapeles en la celda/entrada activa."""
        # If focus is inside an input widget, let its local handlers run
        try:
            fw = self.root.focus_get()
            if fw is not None and (fw is self._editing_entry or isinstance(fw, tk.Entry) or isinstance(fw, tk.Text)):
                return 'break'
        except Exception:
            pass

        try:
            data = self.root.clipboard_get()
        except Exception:
            data = None
        if not data:
            return 'break'
        try:
            if self._editing_entry:
                try:
                    self._editing_entry.insert(tk.INSERT, data)
                except Exception:
                    try:
                        self._editing_entry.delete(0, tk.END)
                        self._editing_entry.insert(0, data)
                    except Exception:
                        pass
            else:
                row = self._last_clicked_row
                col = self._last_clicked_col
                if not row:
                    sels = self.tree.selection()
                    row = sels[0] if sels else None
                if row is not None:
                    vals = list(self.tree.item(row, 'values') or ())
                    idx = col if col is not None else 1
                    if idx is None:
                        idx = 1
                    while len(vals) <= idx:
                        vals.append('')
                    vals[idx] = data
                    try:
                        self.tree.item(row, values=vals)
                    except Exception:
                        pass
                    ent_idx = self.item_map.get(row)
                    if ent_idx is not None and ent_idx < len(self.entries):
                        orig, disp, proposed, fh, sz, title, author = self.entries[ent_idx]
                        if idx == 0:
                            disp = data
                        else:
                            proposed = data
                        self.entries[ent_idx] = (orig, disp, proposed, fh, sz, title, author)
        except Exception:
            pass
        try:
            self._schedule_save_proposals()
        except Exception:
            pass
        return 'break'

    def rename_selected(self):
        """Renombra únicamente las filas seleccionadas.

        Qué hace: similar a `rename_files` pero limitado a la selección
        actual. Por qué: ofrecer control fino al usuario sobre qué aplicar.
        """
        sels = self.tree.selection()
        if not sels:
            messagebox.showinfo('Seleccionar', 'Seleccione una o más filas para renombrar')
            return
        folder = self.folder.get()
        if not folder:
            messagebox.showwarning('Carpeta', 'Seleccione una carpeta primero')
            return
        conflicts = []
        renamed_paths = []
        for iid in sels:
            idx = self.item_map.get(iid)
            if idx is None or idx >= len(self.entries):
                continue
            orig, disp, new, fh, sz, title, author = self.entries[idx]
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
                renamed_paths.append((orig, fh))
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        # remove saved proposals corresponding to successfully renamed files
        if renamed_paths:
            try:
                for p, fh in renamed_paths:
                    try:
                        self._remove_saved_for(path=str(p), fh=fh)
                    except Exception:
                        pass
                try:
                    self._save_proposals_now()
                except Exception:
                    try:
                        self._schedule_save_proposals()
                    except Exception:
                        pass
            except Exception:
                pass
        self.scan()

    def delete_duplicates(self):
        """Interfaz para detectar y eliminar archivos duplicados locales.

        Qué hace: agrupa por hash y presenta un diálogo que permite marcar
        archivos para eliminar, proponiendo heurísticas para conservar uno
        por grupo. Por qué: ayudar a limpiar copias duplicadas antes de
        renombrar o consolidar la biblioteca.
        """
        groups = {}
        for orig, disp, new, fh, sz, title, author in self.entries:
            if not fh:
                continue
            groups.setdefault(fh, []).append((orig, sz))
        dup_groups = {h: items for h, items in groups.items() if len(items) > 1}
        if not dup_groups:
            messagebox.showinfo('Duplicados', 'No se encontraron archivos duplicados')
            return

        dlg = tk.Toplevel(self.root)
        dlg.title('Gestionar duplicados - Seleccione archivos para ELIMINAR')
        dlg.geometry('900x600')
        
        main_container = ttk.Frame(dlg)
        main_container.pack(fill='both', expand=True)

        canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient='vertical', command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        # Ensure resizing works
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor='nw')

        def configure_canvas(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", configure_canvas)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        delete_vars = {}
        group_info = []
        for h, items in dup_groups.items():
            group_info.append((h, items))

        for gi, (h, items) in enumerate(group_info):
            # Try to distinguish groups visually
            lf = ttk.LabelFrame(scroll_frame, text=f'Grupo {gi+1} — {len(items)} archivos')
            lf.pack(fill='x', padx=10, pady=5, anchor='n')
            
            # Simple heuristic: uncheck (keep) the first one found, or check by length?
            # Let's verify file existence to be safe
            valid_items = []
            for p, sz in items:
                if os.path.exists(p):
                    valid_items.append((p, sz))
            
            if not valid_items:
                continue

            # Pick "best" to keep -> unchecked. Default: Keep first one.
            # Could improve to keep longest name or largest size.
            best_idx = 0
            # Example: keep the one with longest filename length (assuming more descriptive)
            max_len = -1
            for idx, (p, sz) in enumerate(valid_items):
                if len(os.path.basename(p)) > max_len:
                    max_len = len(os.path.basename(p))
                    best_idx = idx
            
            for idx, (p, sz) in enumerate(valid_items):
                should_delete = (idx != best_idx)
                var = tk.BooleanVar(value=should_delete)
                delete_vars[p] = var
                
                # Checkbox
                chk = ttk.Checkbutton(lf, text=f"{os.path.basename(p)}\n{p}", variable=var, onvalue=True, offvalue=False)
                chk.pack(fill='x', padx=4, pady=2, anchor='w')

        btns = ttk.Frame(dlg)
        btns.pack(fill='x', pady=10)
        
        def on_cancel():
            dlg.destroy()
            
        def on_apply():
            files_to_delete = [p for p, var in delete_vars.items() if var.get()]
            if not files_to_delete:
                messagebox.showinfo('Info', 'No se seleccionaron archivos para eliminar.')
                return

            if not messagebox.askyesno('Confirmar', f'¿Está seguro de eliminar {len(files_to_delete)} archivos permanentemente?'):
                return

            errors = []
            deleted = 0
            for p in files_to_delete:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        deleted += 1
                except Exception as e:
                    errors.append((p, e))
            
            dlg.destroy()
            
            if errors:
                msg = '\n'.join([f"{os.path.basename(p)}: {e}" for p, e in errors[:5]])
                messagebox.showerror('Errores', f'Ocurrieron errores al eliminar {len(errors)} archivos:\n{msg}')
            
            if deleted > 0:
                messagebox.showinfo('Listo', f'Eliminados {deleted} archivos duplicados.')
                self.scan()

        ttk.Button(btns, text='Cancelar', command=on_cancel, style='Rounded.TButton').pack(side='right', padx=6)
        ttk.Button(btns, text='Eliminar seleccionados', command=on_apply, style='Rounded.TButton').pack(side='right')

    # --- Persistence helpers: save/load modified proposals to disk ---
    def _load_saved_proposals(self):
        """Carga un JSON con propuestas guardadas.

        Nueva estructura soportada (compatibilidad hacia atrás):
        {
          "by_hash": { "<sha256>": "propuesta" },
          "by_path": { "<abs_path>": "propuesta" },
          "updated_at": "..."
        }

        Si el fichero está en el formato antiguo (`saved`: {path:propuesta})
        se migran las entradas a `by_path` internamente.
        """
        try:
            by_hash = {}
            by_path = {}
            if self._proposals_file and self._proposals_file.exists():
                with open(str(self._proposals_file), 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        # New format
                        if isinstance(data.get('by_hash'), dict):
                            for k, v in data.get('by_hash', {}).items():
                                if isinstance(v, str):
                                    by_hash[k] = v
                        if isinstance(data.get('by_path'), dict):
                            for k, v in data.get('by_path', {}).items():
                                if isinstance(v, str):
                                    by_path[k] = v
                        # Old format compatibility (saved or flat mapping)
                        if 'saved' in data and isinstance(data['saved'], dict):
                            for k, v in data['saved'].items():
                                if not isinstance(v, str):
                                    continue
                                # heuristic: if key looks like sha256, put in by_hash
                                if isinstance(k, str) and re.fullmatch(r'[0-9a-fA-F]{64}', k):
                                    by_hash[k] = v
                                else:
                                    by_path[k] = v
                        else:
                            # flat mapping (legacy) - consider keys that are not metadata keys
                            for k, v in data.items():
                                if k == 'updated_at':
                                    continue
                                if not isinstance(v, str):
                                    continue
                                if isinstance(k, str) and re.fullmatch(r'[0-9a-fA-F]{64}', k):
                                    by_hash[k] = v
                                else:
                                    by_path[k] = v
            self._saved_proposals = {'by_hash': by_hash, 'by_path': by_path}
        except Exception:
            self._saved_proposals = {'by_hash': {}, 'by_path': {}}

    def _apply_saved_proposals(self):
        """Aplica las propuestas guardadas a las entradas actuales (si existen)."""
        try:
            sp = getattr(self, '_saved_proposals', None)
            if not sp:
                return
            by_hash = sp.get('by_hash', {}) if isinstance(sp, dict) else {}
            by_path = sp.get('by_path', {}) if isinstance(sp, dict) else {}
            changed = False
            for iid, idx in list(self.item_map.items()):
                if idx is None or idx >= len(self.entries):
                    continue
                orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                if not orig:
                    continue
                candidate = None
                # prefer match by file hash when available
                if fh and isinstance(fh, str) and fh in by_hash:
                    candidate = by_hash.get(fh)
                # then exact path
                if candidate is None and orig in by_path:
                    candidate = by_path.get(orig)
                # fallback: match by basename if unique (helps when folder renamed)
                if candidate is None:
                    bname = os.path.basename(orig)
                    cands = [k for k in by_path.keys() if os.path.basename(k) == bname]
                    if len(cands) == 1:
                        candidate = by_path.get(cands[0])

                if candidate and candidate != proposed:
                    self.entries[idx] = (orig, disp, candidate, fh, sz, title, author)
                    try:
                        self.tree.item(iid, values=(disp, candidate))
                    except Exception:
                        pass
                    changed = True
            if changed:
                try:
                    self.status.set('Propuestas restauradas desde sesión anterior')
                except Exception:
                    pass
        except Exception:
            pass

    def _schedule_save_proposals(self):
        """Debounce para guardar propuestas modificadas en disco."""
        try:
            if getattr(self, '_save_after_id', None):
                try:
                    self.root.after_cancel(self._save_after_id)
                except Exception:
                    pass
            self._save_after_id = self.root.after(800, self._save_proposals_now)
        except Exception:
            # fallback immediate
            try:
                self._save_proposals_now()
            except Exception:
                pass

    def _save_proposals_now(self):
        """Escribe el JSON de propuestas de forma atómica."""
        try:
            by_hash = {}
            by_path = {}
            for orig, disp, proposed, fh, sz, title, author in self.entries:
                if not orig:
                    continue
                if proposed and proposed != disp:
                    if fh:
                        by_hash[str(fh)] = str(proposed)
                    else:
                        by_path[str(orig)] = str(proposed)
            tmp = self._proposals_file.with_suffix('.tmp')
            payload = {'by_hash': by_hash, 'by_path': by_path, 'updated_at': datetime.utcnow().isoformat()}
            try:
                with open(str(tmp), 'w', encoding='utf-8') as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                os.replace(str(tmp), str(self._proposals_file))
            except Exception:
                try:
                    with open(str(self._proposals_file), 'w', encoding='utf-8') as fh:
                        json.dump(payload, fh, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            self._saved_proposals = {'by_hash': by_hash, 'by_path': by_path}
            try:
                self.status.set('Propuestas guardadas')
            except Exception:
                pass
        except Exception:
            pass

    def _remove_saved_for(self, path=None, fh=None):
        """Elimina las entradas guardadas asociadas a `path` y/o `fh`.

        No falla si la entrada no existe. No persiste automáticamente;
        el llamador puede invocar `_save_proposals_now()` o `_schedule_save_proposals()`.
        """
        try:
            sp = getattr(self, '_saved_proposals', None)
            if not sp or not isinstance(sp, dict):
                return
            by_hash = sp.get('by_hash', {}) if isinstance(sp.get('by_hash', {}), dict) else {}
            by_path = sp.get('by_path', {}) if isinstance(sp.get('by_path', {}), dict) else {}
            if fh:
                try:
                    by_hash.pop(str(fh), None)
                except Exception:
                    pass
            if path:
                try:
                    by_path.pop(str(path), None)
                except Exception:
                    pass
            self._saved_proposals = {'by_hash': by_hash, 'by_path': by_path}
        except Exception:
            pass
