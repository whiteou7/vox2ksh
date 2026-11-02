#!/usr/bin/env python3
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main_window import App  # noqa: E402


def main():
    root = tk.Tk()
    try:
        from tkinter import ttk
        ttk.Style().theme_use("vista" if "vista" in ttk.Style().theme_names() else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
