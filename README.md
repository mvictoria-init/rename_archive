# rename_archive - Renombrador de archivos por autor y título

Pequeña app en Tkinter para seleccionar una carpeta, leer metadatos de documentos (PDF, DOCX, EPUB, TXT) y renombrar los archivos en el formato "Autor - Título.ext".

Requisitos:

- Crear un entorno virtual y luego instalar dependencias:

```powershell
python -m venv env
env\Scripts\Activate.ps1
pip install -r requirements.txt
```

Uso:

- Ejecutar `python rename_app.py`, seleccionar una carpeta, revisar la vista previa y presionar `Renombrar`.
