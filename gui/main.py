#!/usr/bin/env python3
"""Entry point: `python gui/main.py`, or the frozen exe built by build/build.py."""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import App  # noqa: E402


def main():
    root = tk.Tk()
    try:
        # a plain ttk theme reads better than the platform default on most
        # Windows builds for this layout (Treeview + custom canvases mixed in)
        from tkinter import ttk
        ttk.Style().theme_use("vista" if "vista" in ttk.Style().theme_names() else "clam")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
