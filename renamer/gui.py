"""
Interfaz gráfica del renombrador.

Este módulo implementa la interfaz Tkinter que permite seleccionar una
carpeta, escanear archivos de libros, generar propuestas de nombres
basadas en metadatos y heurísticas, y ejecutar operaciones como
renombrado, conversión a EPUB y comparación contra una biblioteca
indexada.

Responsabilidades principales:
- Construir y aplicar estilos a la ventana y widgets (Treeview, botones,
    barra de estado).
- Obtener la lista de archivos desde el sistema de archivos o desde la
    base de datos SQLite local para renderizarla en la UI.
- Ofrecer acciones por lotes: renombrar, convertir, eliminar duplicados,
    refinar propuestas.
- Integrarse con `scripts/indexer.py` para indexar bibliotecas y comparar
    por hash de archivo.

Los docstrings y comentarios en este archivo describen cada clase y
método en español para facilitar la comprensión del flujo de UI.
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

from .utils import sanitize, normalize_authors, format_authors_for_filename, human_readable_size
from .metadata import extract_metadata
from .convert import pdf_to_epub, convert_to_epub
from .infer import suggest_for_file
import sqlite3
from .index import db_exists, files_in_folder, DB_PATH


class RenamerApp:
        """
        Clase principal de la aplicación que construye y gestiona la interfaz.

        `RenamerApp` encapsula el estado y comportamiento de la UI: crea la
        ventana principal, aplica estilos, y enlaza los eventos de los
        widgets (botones, doble clic, selección) con los métodos que realizan
        operaciones de sistema de archivos y consultas a la base de datos.

        Atributos relevantes (resumen):
        - `root`: la ventana raíz Tk proporcionada por el llamador.
        - `folder`: `tk.StringVar` con la ruta de la carpeta seleccionada.
        - `tree`: `ttk.Treeview` principal que muestra archivos y propuestas.
        - `entries`: lista de tuplas por fila: (ruta_completa, nombre_original,
            nombre_propuesto, sha256, tamaño, título, autores).
        - `item_map`: mapea identificadores del Treeview a índices en `entries`.
        - `scan_btn`, `rename_btn`, etc.: referencias a widgets para habilitar/
            deshabilitar según el estado.

        Los métodos de la clase implementan escaneo, renombrado, conversión,
        detección de duplicados e integración con el indexador. Muchos de los
        procesos que pueden ser lentos se ejecutan en hilos de background y
        actualizan la UI mediante `root.after` para mantener el mainloop
        responsivo.
        """
        docstrings below for explicit behavioral details and threading notes.
        """
    def __init__(self, root):
        self.root = root
        """
        Initialize the GUI and internal state.

        This method constructs all visible widgets, configures visual
        styles (colors, button styles, Treeview appearance), and initializes
        internal data structures used to track items and UI state. This is a
        potentially expensive method because it sets up the whole window; the
        actual file scanning is performed later by `scan()` or by indexing.

        Threading notes: some long-running operations started from the UI
        (e.g. library indexing) are launched on background threads so the
        Tkinter mainloop stays responsive. Methods that update widgets from
        those threads use `root.after(0, callback)` to schedule UI updates on
        the main thread.
        """
        root.title('Renombrador por Autor y Título')
        # Apply dark theme colors and ttk styles for a modern, low-light UI
        bg = '#1e1b22'  # main window background (very dark)
        # Accent color (mauve/purple) to mirror provided mockup
        accent = '#7b416f'
        try:
            root.configure(bg=bg)
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use('default')
        except Exception:
            pass
        # Base widget backgrounds
        style.configure('TFrame', background=bg)
        style.configure('TLabel', background=bg, foreground='#e6dfe6')
        style.configure('TButton', background=bg, foreground='#e6dfe6')
        # Treeview: dark rows with light text, subtle heading tint
        style.configure('Treeview', background='#262126', fieldbackground='#262126', foreground='#e8dfe8')
        style.configure('Treeview.Heading', background='#3a2b36', foreground='#f4eef6')
        # Accent frame/label/button styles
        style.configure('Accent.TFrame', background='#2b1f2b')
        style.configure('Accent.TLabel', background='#2b1f2b', foreground='#f4eef6')
        style.configure('Accent.TButton', background=accent, foreground='#ffffff')
        self._app_bg = bg
        self._accent = accent
        # App-wide darker background used for additional style touches
        self.bg_color = '#232023'
        try:
            # Ensure common ttk widget backgrounds align with dark theme
            try:
                style.theme_use(style.theme_use())
            except Exception:
                pass
            style.configure('TLabelframe', background=self.bg_color)
            style.configure('TLabelframe.Label', background=self.bg_color, foreground='#e6dfe6')
            style.configure('TButton', background=self.bg_color, foreground='#e6dfe6')
            style.configure('Treeview', background='#262126', fieldbackground='#262126', foreground='#e8dfe8')
        except Exception:
            pass
        try:
            root.configure(bg=self.bg_color)
        except Exception:
            pass
        # Rounded button styles: neutral and accent variants (dark)
        try:
            style.configure('Rounded.TButton', background='#2f2b2f', foreground='#e8dfe8', relief='flat', padding=(8,6), borderwidth=1)
            style.map('Rounded.TButton', background=[('active', '#3a343a')])
            style.configure('RoundedAccent.TButton', background=self._accent, foreground='#ffffff', relief='flat', padding=(8,6), borderwidth=1)
            style.map('RoundedAccent.TButton', background=[('active', '#5d335a')])
        except Exception:
            pass
        self.folder = tk.StringVar()
        # hilo de escaneo actual (para evitar overlaps)
        self._scan_thread = None
        # activar sugerencias automáticas del modelo al terminar un escaneo
        # la dejamos desactivada por defecto para evitar propuestas masivas indeseadas
        self.auto_suggest_on_scan = False

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill='both', expand=True)

        top = ttk.Frame(frm, style='Accent.TFrame')
        top.pack(fill='x')
        ttk.Button(top, text='Seleccionar carpeta', command=self.select_folder, style='RoundedAccent.TButton').pack(side='left')
        ttk.Label(top, textvariable=self.folder).pack(side='left', padx=8)

        self.status = tk.StringVar(value='')
        ttk.Label(frm, textvariable=self.status).pack(fill='x')

        content = ttk.Frame(frm)
        content.pack(fill='both', expand=True)

        # Treeview with scrollbars
        tree_frame = ttk.Frame(content)
        tree_frame.pack(fill='both', expand=True, pady=8)

        self.tree = ttk.Treeview(tree_frame, columns=('orig', 'new', 'size'), show='headings')
        self.tree.heading('orig', text='Original')
        self.tree.heading('new', text='Propuesto')
        self.tree.heading('size', text='Tamaño')

        vs = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        hs = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

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
        self.tree.bind('<Double-1>', self.on_double_click)

        bottom = ttk.Frame(frm, style='Accent.TFrame')
        bottom.pack(fill='x')
        self.scan_btn = ttk.Button(bottom, text='Escanear', command=self.scan, style='RoundedAccent.TButton')
        self.scan_btn.pack(side='left')
        self.rename_btn = ttk.Button(bottom, text='Renombrar', command=self.rename_files, style='RoundedAccent.TButton')
        self.rename_btn.pack(side='left', padx=6)
        self.rename_selected_btn = ttk.Button(bottom, text='Renombrar seleccionado', command=self.rename_selected, style='RoundedAccent.TButton')
        self.rename_selected_btn.pack(side='left', padx=6)
        self.delete_dup_btn = ttk.Button(bottom, text='Eliminar duplicados', command=self.delete_duplicates, style='RoundedAccent.TButton')
        self.delete_dup_btn.pack(side='left', padx=6)
        self.convert_btn = ttk.Button(bottom, text='Convertir a EPUB', command=self.convert_selected_to_epub, style='RoundedAccent.TButton')
        self.convert_btn.pack(side='left', padx=6)
        self.delete_file_btn = ttk.Button(bottom, text='Eliminar archivo', command=self.delete_selected_file, style='RoundedAccent.TButton')
        self.delete_file_btn.pack(side='left', padx=6)
        self.refine_btn = ttk.Button(bottom, text='Refinar propuesta', command=self.refine_selected_proposals, style='RoundedAccent.TButton')
        self.refine_btn.pack(side='left', padx=6)
        self.model_btn = ttk.Button(bottom, text='Sugerir (modelo)', command=self.suggest_with_model, style='RoundedAccent.TButton')
        self.model_btn.pack(side='left', padx=6)
        self.check_lib_dups_btn = ttk.Button(bottom, text='VS Biblioteca', command=self.check_library_duplicates, style='RoundedAccent.TButton')
        self.check_lib_dups_btn.pack(side='left', padx=6)
        
        # New button
        self.set_lib_btn = ttk.Button(bottom, text='Sel. Biblioteca', command=self.select_library_folder, style='RoundedAccent.TButton')
        self.set_lib_btn.pack(side='left', padx=6)

    def select_library_folder(self):
                                """Solicita al usuario seleccionar una carpeta que se tratará como la
                                biblioteca de referencia y, opcionalmente, la indexa usando el
                                script externo `scripts/indexer.py`.

                                Comportamiento:
                                - Abre un selector de directorio; si el usuario cancela, retorna.
                                - Pregunta si se debe ejecutar el indexador (puede tardar varios minutos).
                                - Deshabilita los botones relacionados con la biblioteca mientras
                                    se realiza el indexado y lanza un hilo en segundo plano para ello.
                                - Al completar o fallar, programa las actualizaciones de UI via
                                    `root.after` para reactivar botones y mostrar mensajes.
                                """
                d = filedialog.askdirectory(title='Seleccionar carpeta de Biblioteca')
        if not d:
            return
        
        path = Path(d)
        ans = messagebox.askyesno('Indexar Biblioteca', f'¿Desea indexar ahora la carpeta:\n{d}?\n\nEsto puede tardar unos minutos pero permitirá comparar duplicados.')
        if not ans:
            return

        self.status.set('Indexando biblioteca...')
        self.set_lib_btn.state(['disabled'])
        self.check_lib_dups_btn.state(['disabled']) # Disable check while indexing
        
        def run_indexer():
            try:
                # Import here to avoid circular imports or early init
                # We need to add scripts folder to path or simple use indexer.py logic?
                # indexer.py is in scripts/. We can add scripts/ to sys.path or direct import if we moved logic.
                # But earlier we saw `scripts/indexer.py`.
                # Let's import dynamically
                import sys
                root_proj = Path(__file__).resolve().parent.parent
                scripts_path = root_proj / 'scripts'
                if str(scripts_path) not in sys.path:
                    sys.path.insert(0, str(scripts_path))
                
                from indexer import walk_and_index
                
                walk_and_index(path, workers=4, force_reindex=False)
                
                def done():
                    self.status.set('Biblioteca indexada correctamente.')
                    messagebox.showinfo('Biblioteca', 'Indexado completado.\nYa puede usar la opción "VS Biblioteca".')
                    self.set_lib_btn.state(['!disabled'])
                    self.check_lib_dups_btn.state(['!disabled'])
                
                self.root.after(0, done)
                
            except Exception as e:
                def err():
                    messagebox.showerror('Error', f'Falló el indexado: {e}')
                    self.status.set('Error en indexado.')
                    self.set_lib_btn.state(['!disabled'])
                    self.check_lib_dups_btn.state(['!disabled'])
                self.root.after(0, err)

        t = threading.Thread(target=run_indexer, daemon=True)
        t.start()

    def check_library_duplicates(self):
                                """Compara los archivos locales mostrados con la biblioteca indexada
                                (por SHA256) y presenta un diálogo para resolver duplicados.

                                Pasos realizados:
                                - Construye un mapa de hashes locales a partir de `self.entries` (solo
                                    se consideran entradas con SHA calculado).
                                - Consulta `renamer.index.find_files_by_hash` para obtener filas de la
                                    base de datos que coinciden con cada hash.
                                - Para cada hash con coincidencias remotas (excluyendo rutas idénticas),
                                    añade un panel al diálogo mostrando la ruta local y las rutas de la
                                    biblioteca que coinciden.
                                - Presenta opciones (radio) para: mantener ambos, mantener local (y
                                    eliminar remoto) o mantener biblioteca (y eliminar local). La
                                    selección por defecto es mantener la copia de la biblioteca.
                                - Al aplicar, realiza las eliminaciones solicitadas y muestra un
                                    resumen; luego refresca la vista local llamando a `self.scan()`.

                                Nota: las consultas ligeras a la BD y la construcción de la UI se
                                realizan en el hilo principal; las eliminaciones de archivos se
                                efectúan de manera síncrona pero se esperan rápidas.
                                """
                from .index import find_files_by_hash
        # Collect current hashes
        local_hashes = {}
        for entry in self.entries:
            orig, disp, new, fh, sz, title, author = entry
            if fh:
                local_hashes[fh] = orig
        
        if not local_hashes:
            messagebox.showinfo('Info', 'No hay archivos con hash para comprobar o lista vacía.')
            return

        duplicates_found = [] # (local_path, remote_info_dict)

        self.status.set('Comprobando duplicados en biblioteca...')
        
        # Check against DB
        # To avoid UI freeze, could be thread, but let's do simple loop first as DB is local and fast enough for <1000 files
        for fh, local_path in local_hashes.items():
            matches = find_files_by_hash(fh)
            # matches includes the file itself if it was already indexed!
            # so checking path equality is crucial
            remotes = []
            for m in matches:
                # normalize paths for comparison
                p1 = os.path.normpath(str(m['path'])).lower()
                p2 = os.path.normpath(str(local_path)).lower()
                if p1 != p2:
                    remotes.append(m)
            
            if remotes:
                duplicates_found.append((local_path, remotes))
        
        self.status.set('')
        
        if not duplicates_found:
            messagebox.showinfo('Info', 'No se encontraron duplicados externos en la biblioteca.')
            return

        # Dialog to resolve
        dlg = tk.Toplevel(self.root)
        dlg.title(f'Conflicto con Biblioteca - {len(duplicates_found)} archivos')
        dlg.geometry('900x600')

        container = ttk.Frame(dlg)
        container.pack(fill='both', expand=True)
        
        canvas = tk.Canvas(container, bg=self._app_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Dictionary valid_items[local_path] = IntVar(value=0:keep_local, 1:keep_remote, 2:keep_both)
        # But wait, user wants to CHOOSE which one to keep
        # If I keep local => Delete remote?
        # If I keep remote => Delete local?
        
        # Let's group by conflict
        
        actions = {} # local_path -> StringVar(value='keep_local'/'keep_remote'/'keep_both')
        
        for idx, (local_p, remotes) in enumerate(duplicates_found):
            lf = ttk.LabelFrame(scroll_frame, text=f'Conflicto {idx+1}: {os.path.basename(local_p)}')
            lf.pack(fill='x', padx=10, pady=5, anchor='n')
            
            # Show info
            info_frame = ttk.Frame(lf)
            info_frame.pack(fill='x', padx=5, pady=2)
            
            # Local info
            l_lbl = ttk.Label(info_frame, text=f"LOCAL (Aquí): {local_p}", foreground='blue')
            l_lbl.pack(anchor='w')
            
            # Remote info (could be multiple, just show first few)
            for r in remotes:
                r_path = r['path']
                r_lbl = ttk.Label(info_frame, text=f"BIBLIOTECA: {r_path}", foreground='red')
                r_lbl.pack(anchor='w')

            # Actions
            # Default is keep_remote because user prefers library version
            act_var = tk.StringVar(value='keep_remote')
            actions[local_p] = (act_var, remotes)
            
            act_frame = ttk.Frame(lf)
            act_frame.pack(fill='x', padx=5, pady=2)
            
            ttk.Radiobutton(act_frame, text='Conservar ambos (No hacer nada)', variable=act_var, value='keep_both').pack(side='left', padx=5)
            ttk.Radiobutton(act_frame, text='Conservar LOCAL (Borrar de biblioteca)', variable=act_var, value='keep_local').pack(side='left', padx=5)
            ttk.Radiobutton(act_frame, text='Conservar BIBLIOTECA (Borrar local)', variable=act_var, value='keep_remote').pack(side='left', padx=5)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill='x', pady=10)
        
        def apply():
            deleted_local = 0
            deleted_remote = 0
            errors = []
            
            for local_p, (var, remote_list) in actions.items():
                choice = var.get()
                if choice == 'keep_both':
                    continue
                elif choice == 'keep_remote':
                    # Delete local
                    try:
                        if os.path.exists(local_p):
                            os.remove(local_p)
                            deleted_local += 1
                    except Exception as e:
                        errors.append(f"Error borrando local {local_p}: {e}")
                elif choice == 'keep_local':
                    # Delete remotes
                    for r in remote_list:
                        rp = r['path']
                        try:
                            if os.path.exists(rp):
                                os.remove(rp)
                                deleted_remote += 1
                        except Exception as e:
                            errors.append(f"Error borrando remoto {rp}: {e}")
            
            dlg.destroy()
            
            msg = []
            if deleted_local: msg.append(f"Eliminados {deleted_local} archivos locales.")
            if deleted_remote: msg.append(f"Eliminados {deleted_remote} archivos de la biblioteca.")
            if errors: msg.append(f"Errores:\n" + "\n".join(errors[:5]))
            
            if msg:
                messagebox.showinfo('Resultado', '\n'.join(msg))
                self.scan() # Refresh local view
            else:
                messagebox.showinfo('Resultado', 'No se realizaron cambios.')

        ttk.Button(btn_frame, text='Cancelar', command=dlg.destroy, style='Rounded.TButton').pack(side='right', padx=10)
        ttk.Button(btn_frame, text='Aplicar acciones', command=apply, style='Rounded.TButton').pack(side='right', padx=10)

    def suggest_with_model(self, auto: bool = False, max_dist: float = 0.6):
                                """Ejecuta el modelo de sugerencias sobre las filas seleccionadas
                                (o todas si `auto` es True) para calcular nombres propuestos.

                                Parámetros:
                                - `auto`: si es True, procesa todas las entradas (útil tras el
                                    escaneo si `auto_suggest_on_scan` está activado). Si es False,
                                    opera solo sobre las filas actualmente seleccionadas en el Treeview.
                                - `max_dist`: umbral que el modelo usa para decidir si una sugerencia
                                    está lo bastante cerca para considerarla.

                                Notas de implementación:
                                - El cálculo de sugerencias puede realizarse de forma síncrona; si
                                    hay muchas entradas, las llamadas de nivel superior deben ejecutar
                                    este método en hilos para no bloquear la UI. La llamada real al
                                    modelo es `renamer.infer.suggest_for_file`.
                                """
                sels = self.tree.selection()
        target_idxs = []
        if sels:
            for iid in sels:
                idx = self.item_map.get(iid)
                if idx is not None and idx < len(self.entries):
                    target_idxs.append(idx)
        else:
            target_idxs = list(range(len(self.entries)))

        if not target_idxs:
            if not auto:
                messagebox.showinfo('Modelo', 'No hay elementos para sugerir.')
            return

        self.model_btn.state(['disabled'])
        self.status.set('Generando sugerencias...')

        def worker():
            updated = 0
            errors = []
            for idx in target_idxs:
                try:
                    orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                    p = Path(orig)
                    suggestions = suggest_for_file(p, top=3, max_dist=max_dist)
                    if not suggestions:
                        continue
                    # elegir la propuesta más cercana (menor distancia) que no sea vacía
                    best = None
                    for dist, prop in suggestions:
                        if prop:
                            best = prop
                            break
                    if not best:
                        continue
                    newname = sanitize(best + p.suffix)
                    if newname != proposed:
                        self.entries[idx] = (orig, disp, newname, fh, sz, title, author)
                        updated += 1
                except Exception as e:
                    errors.append(str(e))

            def on_done():
                # refrescar visibles
                for iid, i in list(self.item_map.items()):
                    if i < len(self.entries):
                        orig, disp, proposed, fh, sz, title, author = self.entries[i]
                        try:
                            self.tree.item(iid, values=(disp, proposed, human_readable_size(sz)))
                        except Exception:
                            pass
                self.model_btn.state(['!disabled'])
                if errors and not auto:
                    messagebox.showwarning('Modelo', f'Sugerencias completadas con {len(errors)} errores (ver consola).')
                elif not errors and not auto:
                    messagebox.showinfo('Modelo', f'Actualizadas {updated} propuestas con el modelo')
                self.status.set('')

            self.root.after(0, on_done)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _maybe_auto_model(self):
        # evita disparar si ya hay un hilo en marcha o si el botón está deshabilitado
        """
        Ejecuta automáticamente el modelo tras un escaneo si está habilitado.

        Comprueba la bandera `auto_suggest_on_scan` y que el botón del
        modelo no esté deshabilitado. Si procede, programa una llamada a
        `suggest_with_model(auto=True)` en el siguiente ciclo del bucle
        principal para no bloquear el evento actual.
        """
        if not getattr(self, 'auto_suggest_on_scan', False):
            return
        try:
            state = self.model_btn.state()
            if 'disabled' in state:
                return
        except Exception:
            return
        # lanzar en el siguiente ciclo del loop principal para no bloquear el evento actual
        self.root.after(10, lambda: self.suggest_with_model(auto=True))

    def select_folder(self):
        """
        Abrir un selector de carpeta y almacenar la ruta seleccionada.

        Si el usuario elige una carpeta, su ruta se guarda en `self.folder`.
        El escaneo real de archivos se realiza con `self.scan()` para que
        la selección y el listado queden desacoplados.
        """
        d = filedialog.askdirectory()
        if d:
            self.folder.set(d)

     def scan(self):
          """
          Poblar la interfaz con los archivos de la carpeta seleccionada.

          Modos principales:
          1) Ruta rápida: si existe la base de datos de índice y contiene
              entradas para la carpeta, cargar desde `files_in_folder` es
              mucho más rápido porque evita recalcular hashes y extraer
              metadatos.
          2) Recorrido del sistema de archivos: si no hay índice, se
              examinan los archivos, se calcula SHA256 y se extraen
              metadatos/ propuestas si es necesario.

          La función actualiza `self.entries`, llena el `Treeview`, marca
          duplicados (mismo SHA) y lanza un worker incremental en background
          para detectar nuevos o cambiados y actualizar la DB/UI.
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
                    for r in rows:
                        p = Path(r['path'])
                        title = r.get('title')
                        author = r.get('authors')
                        ext = p.suffix
                        t = sanitize(str(title)) if title else ''
                        a = format_authors_for_filename(normalize_authors(author), max_authors=3) if author else ''
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
                        self.entries.append((str(p), p.name, new, fh, sz, title, author))
                        iid = f'i{self._next_iid}'
                        self._next_iid += 1
                        tags = ()
                        try:
                            self.tree.insert('', 'end', iid=iid, values=(p.name, new, human_readable_size(sz)), tags=tags)
                        except Exception:
                            self.tree.insert('', 'end', values=(p.name, new, human_readable_size(sz)))
                        self.item_map[iid] = idx
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
                        self.tree.tag_configure('dup', background='#ffdce0')
                    except Exception:
                        pass

                    # sugerir con modelo automáticamente si está habilitado
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
                                    new_pro, title, authors = suggest_for_file(p)
                                except Exception:
                                    pass
                                # upsert into DB
                                indexed_at = datetime.utcnow().isoformat()
                                try:
                                    cur.execute('INSERT OR REPLACE INTO files(path,relpath,size,mtime,sha256,title,authors,indexed_at) VALUES(?,?,?,?,?,?,?,?)',
                                                (sp, str(p.relative_to(folder_path)), size, mtime, fh, title, str(authors) if authors else None, indexed_at))
                                    conn.commit()
                                except Exception:
                                    pass
                                # update tree: append new entry and mark duplicates later
                                def add_row_to_tree():
                                    idx = len(self.entries)
                                    p_name = p.name
                                    new = new_pro if new_pro else p_name
                                    self.entries.append((sp, p_name, new, fh, size, title, authors))
                                    iid = f'i{self._next_iid}'
                                    self._next_iid += 1
                                    self.tree.insert('', 'end', iid=iid, values=(p_name, new, human_readable_size(size)))
                                    self.item_map[iid] = idx
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
                    new, title, author = suggest_for_file(f)

                    file_h = file_hash(str(f))
                    size_val = None
                    try:
                        size_val = f.stat().st_size
                    except Exception:
                        size_val = None
                    # store: full path, display name, proposed new name, hash, size, title, author
                    self.entries.append((str(f), f.name, new, file_h, size_val, title, author))

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

                        self.tree.insert('', 'end', iid=iid, values=(fname, nname, human_readable_size(sz)), tags=tags)
                        self.item_map[iid] = idx

                    self.root.after(0, insert_item)

            def on_done():
                self.status.set('Escaneo completado')
                self.scan_btn.state(['!disabled'])
                self.rename_btn.state(['!disabled'])
                try:
                    self.tree.tag_configure('dup', background='#ffdce0')
                except Exception:
                    pass
                # sugerir con modelo automáticamente si está habilitado
                self._maybe_auto_model()

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
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        self.rename_btn.state(['!disabled'])
        self.scan()

    def convert_selected_to_epub(self):
        """Convierte los archivos seleccionados a formato EPUB.

        Recolecta las filas seleccionadas del Treeview y lanza un hilo en segundo
        plano que llama a `convert_to_epub` para cada archivo. La interfaz muestra
        'Convirtiendo...' mientras procesa y, al finalizar, muestra los resultados
        (éxitos o errores) mediante `messagebox`.
        """
        sels = self.tree.selection()
        if not sels:
            messagebox.showinfo('Convertir', 'Seleccione uno o más archivos para convertir')
            return

        # run conversion in background to avoid blocking UI
        self.convert_btn.state(['disabled'])
        self.status.set('Convirtiendo...')

        def worker(selected_iids):
            errors = []
            converted = 0
            for iid in selected_iids:
                idx = self.item_map.get(iid)
                if idx is None or idx >= len(self.entries):
                    continue
                orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                p = Path(orig)
                # sanitize the output epub name (remove control chars from original stem)
                dst = p.with_name(sanitize(p.stem) + '.epub')
                if dst.exists():
                    base = dst.stem
                    i = 1
                    while True:
                        candidate = dst.with_name(f"{base} ({i}){dst.suffix}")
                        if not candidate.exists():
                            dst = candidate
                            break
                        i += 1

                try:
                    success, err = convert_to_epub(p, str(dst), title=title, authors=normalize_authors(author))
                except Exception as e:
                    success, err = False, str(e)

                if success:
                    converted += 1
                else:
                    errors.append((p, err))

            def on_done():
                self.convert_btn.state(['!disabled'])
                if errors:
                    messagebox.showerror('Errores', f'Ocurrieron errores al convertir {len(errors)} archivos:\n{errors[0][1]}')
                else:
                    messagebox.showinfo('Listo', f'Convertidos {converted} archivos a EPUB')
                self.status.set('')

            self.root.after(0, on_done)

        t = threading.Thread(target=worker, args=(sels,), daemon=True)
        t.start()

    def delete_selected_file(self):
        """
        Delete the selected file(s) from disk after confirmation.

        This prompts the user to select rows and then attempts to remove
        the corresponding filesystem entries. Any failures are collected
        and shown to the user. After deletion the Treeview and internal
        `entries` list are updated to reflect the removals.
        """
        sels = self.tree.selection()
        if not sels:
            messagebox.showinfo('Eliminar', 'Seleccione uno o más archivos para eliminar')
            return
        if not messagebox.askyesno('Confirmar eliminación', f'¿Eliminar {len(sels)} archivo(s)? Esta acción no se puede deshacer.'):
            return
        removed_paths = []
        errors = []
        for iid in list(sels):
            idx = self.item_map.get(iid)
            if idx is None or idx >= len(self.entries):
                continue
            orig, disp, proposed, fh, sz, title, author = self.entries[idx]
            try:
                if os.path.exists(orig):
                    os.remove(orig)
                removed_paths.append(orig)
            except Exception as e:
                errors.append((orig, str(e)))

        # remove deleted entries from internal list and rebuild tree
        if removed_paths:
            self.entries = [e for e in self.entries if e[0] not in removed_paths]
            self.tree.delete(*self.tree.get_children())
            self.item_map = {}
            # simple rebuild, without preserving duplicate tags
            # rebuild using the global iid counter to avoid collisions
            for idx, entry in enumerate(self.entries):
                orig, disp, proposed, fh, sz, title, author = entry
                iid = f'i{self._next_iid}'
                self._next_iid += 1
                self.tree.insert('', 'end', iid=iid, values=(disp, proposed, human_readable_size(sz)))
                self.item_map[iid] = idx

        if errors:
            messagebox.showerror('Errores', f'Ocurrieron errores al eliminar {len(errors)} archivos')
        else:
            messagebox.showinfo('Listo', f'Eliminados {len(removed_paths)} archivos')

    def refine_selected_proposals(self):
        """
        Recompute and improve filename proposals for selected entries.

        For each selected row (or for all entries if none selected), this
        method attempts to extract title/author information from existing
        metadata or by guessing from the filename. It then formats a new
        proposed filename using the project's author/title template and
        updates `self.entries` and the visible Treeview values.
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
                        self.tree.item(iid, values=(disp, proposed, human_readable_size(sz)))
                    except Exception:
                        pass
        messagebox.showinfo('Refinar', f'Actualizadas {changed} propuestas')

    def on_select(self):
        """Manejador de selección (placeholder).

        Actualmente no realiza ninguna acción. Está vinculado al evento de
        selección del Treeview y se deja como punto de extensión para actualizar
        la UI basada en la selección (activar/desactivar botones, mostrar una
        vista previa, etc.).
        """
        return

    def on_double_click(self, event):
        """Manejador de edición en sitio para el Treeview.

        Al hacer doble clic en una celda de la columna 1 (nombre mostrado) o
        columna 2 (nombre propuesto), coloca un widget Entry sobre la celda
        para que el usuario edite. Al presionar Enter o perder el foco, el valor
        editado se escribe de vuelta en `self.entries` y en la fila del Treeview.
        """
        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or not col:
            return
        # allow editing column 1 (Original) and column 2 (Propuesto)
        if col not in ('#1', '#2'):
            return
        bbox = self.tree.bbox(row, column=col)
        if not bbox:
            return
        x, y, width, height = bbox
        vals = list(self.tree.item(row, 'values'))
        # column mapping: #1 -> vals[0] (original display), #2 -> vals[1] (proposed)
        col_index = 0 if col == '#1' else 1
        cur = vals[col_index]
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
            vals[col_index] = newval
            self.tree.item(row, values=vals)
            idx = self.item_map.get(row)
            if idx is not None and idx < len(self.entries):
                # entries structure: (full_path, display_name, proposed_new, hash, size, title, author)
                orig, disp, proposed, fh, sz, title, author = self.entries[idx]
                if col_index == 0:
                    disp = newval
                else:
                    proposed = newval
                self.entries[idx] = (orig, disp, proposed, fh, sz, title, author)

        edit.bind('<Return>', finish)
        edit.bind('<FocusOut>', finish)

    def rename_selected(self):
        """
        Rename only the currently selected rows.

        This performs the same file-moving logic as `rename_files` but only
        for the selected Treeview items. Naming collisions are resolved by
        appending ` (n)` to the base name. After moving files, the UI is
        refreshed via `self.scan()`.
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
            except Exception as e:
                conflicts.append((src, e))
        if conflicts:
            messagebox.showerror('Errores', f'Ocurrieron errores con {len(conflicts)} archivos')
        else:
            messagebox.showinfo('Listo', 'Renombrado completado')
        self.scan()

    def delete_duplicates(self):
        """Presenta un diálogo para eliminar en bloque archivos duplicados
        encontrados en `self.entries`.

        Agrupa las entradas por SHA256 (`fh`), identifica los grupos con más
        de un miembro y los muestra en un diálogo desplazable donde el usuario
        puede elegir qué archivo(s) eliminar. No realiza borrados automáticos
        sin confirmación explícita del usuario.
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
        
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

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
