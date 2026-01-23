import os
import re
import shutil
import threading
import hashlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from .utils import sanitize, normalize_authors, format_authors_for_filename, human_readable_size
from .metadata import extract_metadata


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
        # UI bindings
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.on_select())
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

        def worker(folder_path):
            p = Path(folder_path)
            hash_map = {}
            for f in p.iterdir():
                if f.is_file():
                    title, author = extract_metadata(f)
                    ext = f.suffix
                    t = sanitize(title) if title else ''
                    a = format_authors_for_filename(normalize_authors(author), max_authors=3)
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
                    self.entries.append((str(f), new, file_h, size_val, title, author))

                    def insert_item(fname=f.name, nname=new, fh=file_h, sz=size_val):
                        tags = ()
                        if fh and fh in hash_map:
                            first_id = hash_map[fh]
                            prev_tags = set(self.tree.item(first_id, 'tags') or ())
                            prev_tags.add('dup')
                            self.tree.item(first_id, tags=tuple(prev_tags))
                            tags = ('dup',)
                        else:
                            if fh:
                                hash_map[fh] = None
                        idx = len(self.entries) - 1
                        iid = f'i{idx}'
                        self.tree.insert('', 'end', iid=iid, values=(fname, nname, human_readable_size(sz)), tags=tags)
                        self.item_map[iid] = idx
                        if fh and hash_map.get(fh) is None:
                            hash_map[fh] = iid

                    self.root.after(0, insert_item)

            def on_done():
                self.status.set('Escaneo completado')
                self.scan_btn.state(['!disabled'])
                self.rename_btn.state(['!disabled'])
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
        return

    def on_double_click(self, event):
        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or not col:
            return
        if col != '#2':
            return
        bbox = self.tree.bbox(row, column=col)
        if not bbox:
            return
        x, y, width, height = bbox
        vals = list(self.tree.item(row, 'values'))
        cur = vals[1]
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
            vals[1] = newval
            self.tree.item(row, values=vals)
            idx = self.item_map.get(row)
            if idx is not None and idx < len(self.entries):
                orig, old_new, fh, sz, title, author = self.entries[idx]
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
        self.scan()

    def delete_duplicates(self):
        groups = {}
        for orig, new, fh, sz, title, author in self.entries:
            if not fh:
                continue
            groups.setdefault(fh, []).append((orig, sz))
        dup_groups = {h: items for h, items in groups.items() if len(items) > 1}
        if not dup_groups:
            messagebox.showinfo('Duplicados', 'No se encontraron archivos duplicados')
            return

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
        group_info = []
        for h, items in dup_groups.items():
            group_info.append((h, items))

        for gi, (h, items) in enumerate(group_info):
            lf = ttk.LabelFrame(scroll_frame, text=f'Grupo {gi+1} — {len(items)} archivos')
            lf.pack(fill='x', padx=6, pady=6, anchor='n')
            var = tk.IntVar(value=0)
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
