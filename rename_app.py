import tkinter as tk
from renamer.gui import RenamerApp


def main():
    """Arranca la aplicación gráfica `RenamerApp`.

    Por qué: punto de entrada sencillo para lanzar la interfaz desde
    la instalación o el entorno de desarrollo.
    """
    root = tk.Tk()
    app = RenamerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()

