import tkinter as tk
from renamer.gui import RenamerApp


def main():
    root = tk.Tk()
    app = RenamerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()

