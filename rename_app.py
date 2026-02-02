"""
Aplicación ejecutable: inicializa la interfaz gráfica y arranca el
mainloop de Tkinter.

Este módulo contiene el entrypoint `main()` usado cuando se ejecuta
`python rename_app.py` desde la línea de comandos.
"""

import tkinter as tk
from renamer.gui import RenamerApp


def main():
    root = tk.Tk()
    app = RenamerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()

