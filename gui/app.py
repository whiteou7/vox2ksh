"""vox2ksh: the Tkinter application wrapping notes/convert.py +
apply_chart.py for batch .vox -> .ksh (+ rendered audio) conversion.

See HANDOFF.md item 2 for the design questions this answers: batch (not
single-chart) conversion, an explicit + remembered game folder, job-granular
progress/cancel (apply_chart.py has no internal yield points), and a debug/
advanced split so the diagnostic CLI flags stay out of the way by default.
"""
import os
import queue
import sys
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argspec       # noqa: E402
import convert_note   # noqa: E402
import convert_worker  # noqa: E402
import music_db       # noqa: E402
import paths          # noqa: E402
import release_check  # noqa: E402
import settings as settings_store  # noqa: E402
from version import __version__  # noqa: E402

DIFF_FILTERS = [("novice", "NOV"), ("advanced", "ADV"), ("exhaust", "EXH"), ("top", "INF/MXM")]


class ScrollableFrame(ttk.Frame):
    """A vertically-scrolling Frame - used for the Advanced panel, which has
    ~35 options and needs to fit in a fixed-height strip."""

    def __init__(self, master, height=180, **kw):
        super().__init__(master, **kw)
        canvas = tk.Canvas(self, height=height, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)
        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        # mouse wheel only while hovering this panel, so it doesn't fight the
        # song table's own scrolling
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", self._wheel(canvas)))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    @staticmethod
    def _wheel(canvas):
        def handler(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        return handler


class App:
    def __init__(self, root):
        self.root = root
        root.title("vox2ksh")
        root.geometry("980x760")
        root.minsize(760, 560)

        self.settings = settings_store.load()
        self.songs = []
        self.music_dir = None
        self.fallback_music_dir = music_db.fallback_music_dir(self.settings.get("fallback_game_folder"))
        self.row_to_song = {}
        self.jacket_cache = {}
        self.worker = None
        self.events = queue.Queue()

        self._build_menu()
        self._build_banner()
        self._build_toolbar()
        self._build_table()
        self._build_preview()
        self._build_advanced()
        self._build_debug()
        self._build_status()

        self._apply_toggle_states()
        self._poll_events()

        game_folder = self.settings.get("game_folder")
        if game_folder and os.path.isdir(game_folder):
            self.load_game_folder(game_folder, quiet=True)

        release_check.check_async(lambda tag: self.events.put(("update", tag)))

    # ------------------------------------------------------------------ menu

    def _build_menu(self):
        m = tk.Menu(self.root)
        self.root.config(menu=m)

        file_menu = tk.Menu(m, tearoff=False)
        file_menu.add_command(label="Open Game / Update Folder...", command=self.on_open_game_folder)
        file_menu.add_command(label="Set Output Folder...", command=self.on_choose_output_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Open Output Folder", command=self.on_reveal_output_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        m.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(m, tearoff=False)
        edit_menu.add_command(label="Select All", command=self.on_select_all)
        edit_menu.add_command(label="Select None", command=self.on_select_none)
        edit_menu.add_separator()
        edit_menu.add_command(label="Settings...", command=self.on_open_settings)
        m.add_cascade(label="Edit", menu=edit_menu)

        help_menu = tk.Menu(m, tearoff=False)
        help_menu.add_command(label="About", command=self.on_about)
        m.add_cascade(label="Help", menu=help_menu)

    # --------------------------------------------------------------- banner

    def _build_banner(self):
        self.update_label = tk.Label(self.root, text="", fg="#c0392b", cursor="hand2")
        self.update_label.pack(side="top", fill="x", padx=6)
        self.update_label.bind("<Button-1>", lambda e: webbrowser.open(release_check.RELEASES_URL))

    # -------------------------------------------------------------- toolbar

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text="Game update folder:").grid(row=0, column=0, sticky="w")
        self.game_folder_var = tk.StringVar(value=self.settings.get("game_folder", ""))
        ttk.Entry(bar, textvariable=self.game_folder_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=4)
        ttk.Button(bar, text="Browse...", command=self.on_open_game_folder).grid(row=0, column=2)

        ttk.Label(bar, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.output_folder_var = tk.StringVar(value=self.settings.get("output_folder", ""))
        ttk.Entry(bar, textvariable=self.output_folder_var, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(bar, text="Browse...", command=self.on_choose_output_folder).grid(row=1, column=2, pady=(4, 0))
        bar.columnconfigure(1, weight=1)

        filt = ttk.Frame(self.root, padding=(6, 0))
        filt.pack(side="top", fill="x")
        ttk.Label(filt, text="Difficulties:").pack(side="left")
        self.diff_vars = {}
        saved = set(self.settings.get("difficulties") or [])
        for key, label in DIFF_FILTERS:
            var = tk.BooleanVar(value=(key in saved) if saved else True)
            ttk.Checkbutton(filt, text=label, variable=var, command=self._save_diff_filters).pack(
                side="left", padx=(6, 0))
            self.diff_vars[key] = var

        ttk.Frame(filt, width=20).pack(side="left")
        self.debug_var = tk.BooleanVar(value=bool(self.settings.get("debug")))
        ttk.Checkbutton(filt, text="Debug", variable=self.debug_var,
                         command=self._apply_toggle_states).pack(side="left", padx=(6, 0))
        self.advanced_var = tk.BooleanVar(value=bool(self.settings.get("advanced")))
        ttk.Checkbutton(filt, text="Advanced", variable=self.advanced_var,
                         command=self._apply_toggle_states).pack(side="left", padx=(6, 0))

        ttk.Frame(filt, width=20).pack(side="left")
        ttk.Label(filt, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_table())
        ttk.Entry(filt, textvariable=self.search_var, width=22).pack(side="left", padx=(4, 0))

    def _save_diff_filters(self):
        self.settings["difficulties"] = [k for k, v in self.diff_vars.items() if v.get()]
        settings_store.save(self.settings)

    def _save_slam_gap(self):
        # notes_convert.convert()'s slam_gap_frac (laser.py's SLAM_GAP_FRAC when
        # checked, 0 when unchecked - see convert_worker.run_job).
        self.settings["standard_slam_gap"] = self.slam_gap_var.get()
        settings_store.save(self.settings)

    def _save_pretilt_fix(self):
        # notes_convert.convert()'s pretilt_fix - camera.py brackets the lasers
        # KSM would tilt into early. Off by default; see specs/camera.md.
        self.settings["pretilt_fix"] = self.pretilt_var.get()
        settings_store.save(self.settings)

    # ---------------------------------------------------------------- table

    def _build_table(self):
        frame = ttk.Frame(self.root, padding=(6, 4))
        frame.pack(side="top", fill="both", expand=True)

        cols = ("id", "title", "artist", "source")
        headings = {"id": "ID", "title": "Title", "artist": "Artist", "source": "Source"}
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, w, anchor in (("id", 50, "e"), ("title", 340, "w"), ("artist", 220, "w"), ("source", 130, "w")):
            self.tree.heading(c, text=headings[c], command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "title"))
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        self._sort_state = {"col": "id", "reverse": False}

    def _sort_by(self, col):
        rev = self._sort_state["col"] == col and not self._sort_state["reverse"]
        self._sort_state = {"col": col, "reverse": rev}
        rows = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children("")]
        key = (lambda v: int(v[0])) if col == "id" else (lambda v: v[0].lower())
        rows.sort(key=key, reverse=rev)
        for i, (_, iid) in enumerate(rows):
            self.tree.move(iid, "", i)

    # -------------------------------------------------------------- preview

    def _build_preview(self):
        frame = ttk.Frame(self.root, padding=(6, 4))
        frame.pack(side="top", fill="x")

        tiles = ttk.Frame(frame)
        tiles.pack(side="left")
        self.tile_widgets = []
        for i in range(4):
            col = ttk.Frame(tiles, padding=4)
            col.grid(row=0, column=i)
            lvl = ttk.Label(col, text="---")
            lvl.pack()
            canvas = tk.Canvas(col, width=84, height=84, bg="#2b2b2b", highlightthickness=1,
                                highlightbackground="#555")
            canvas.pack()
            name = ttk.Label(col, text="---", width=10, anchor="center")
            name.pack()
            self.tile_widgets.append({"level": lvl, "canvas": canvas, "name": name, "image": None})

        meta = ttk.Frame(frame, padding=(16, 0))
        meta.pack(side="left", fill="x", expand=True)
        self.title_var = tk.StringVar()
        self.artist_var = tk.StringVar()
        self.source_var = tk.StringVar(value="")
        self.date_var = tk.StringVar(value="")
        ttk.Label(meta, text="Title").grid(row=0, column=0, sticky="w")
        ttk.Entry(meta, textvariable=self.title_var, state="readonly").grid(row=0, column=1, sticky="ew")
        ttk.Label(meta, text="Artist").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Entry(meta, textvariable=self.artist_var, state="readonly").grid(row=1, column=1, sticky="ew", pady=(2, 0))
        ttk.Label(meta, text="Source").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(meta, textvariable=self.source_var).grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(meta, text="Date released").grid(row=3, column=0, sticky="w")
        ttk.Label(meta, textvariable=self.date_var).grid(row=3, column=1, sticky="w")
        meta.columnconfigure(1, weight=1)

    def _placeholder_note(self, canvas):
        canvas.delete("all")
        canvas.create_text(42, 42, text="♪", fill="#888", font=("Segoe UI", 28))

    def _on_selection_changed(self, _event=None):
        self._update_selected_count()
        iid = self.tree.focus()
        song = self.row_to_song.get(iid)
        if song:
            self._show_song(song)

    def _show_song(self, song):
        self.title_var.set(song.title)
        self.artist_var.set(song.artist)
        self.source_var.set(song.version_name)
        self.date_var.set(song.distribution_date or "-")

        by_tile = dict(song.tiles())
        for i in range(4):
            tile = i + 1
            w = self.tile_widgets[i]
            diff = by_tile.get(tile)
            if not diff:
                w["level"].config(text="---")
                w["name"].config(text="---")
                self._placeholder_note(w["canvas"])
                w["image"] = None
                continue
            w["level"].config(text=diff.level_display)
            w["name"].config(text=music_db.DIFF_SHORT[diff.key])
            img = self._get_thumb(song.thumb_path(self.music_dir, diff.key, self.fallback_music_dir))
            w["canvas"].delete("all")
            if img is not None:
                w["canvas"].create_image(42, 42, image=img)
            else:
                self._placeholder_note(w["canvas"])
            w["image"] = img  # keep a reference - PhotoImage is GC'd otherwise

    def _get_thumb(self, path):
        if not path:
            return None
        if path in self.jacket_cache:
            return self.jacket_cache[path]
        try:
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
        w = img.width()
        if w > 90:
            factor = max(1, w // 84)
            img = img.subsample(factor, factor)
        self.jacket_cache[path] = img
        return img

    # ------------------------------------------------------------- advanced

    def _build_advanced(self):
        self.advanced_frame = ttk.Labelframe(self.root, text="Advanced", padding=6)

        # notes_convert.py option (laser.py's SLAM_GAP_FRAC vs. slam_gap_frac=0
        # - see _save_slam_gap) - not an apply_chart.py flag, so it gets its
        # own row above that list instead of blending into it.
        notes_row = ttk.Frame(self.advanced_frame, padding=(2, 3))
        notes_row.pack(fill="x", anchor="w")
        self.slam_gap_var = tk.BooleanVar(value=bool(self.settings.get("standard_slam_gap", True)))
        ttk.Checkbutton(notes_row, text="Standard slam gap", variable=self.slam_gap_var,
                         command=self._save_slam_gap).pack(anchor="w")
        self.pretilt_var = tk.BooleanVar(value=bool(self.settings.get("pretilt_fix", False)))
        ttk.Checkbutton(notes_row, text="Remove pretilt",
                         variable=self.pretilt_var,
                         command=self._save_pretilt_fix).pack(anchor="w")

        ttk.Label(self.advanced_frame, text="apply_chart.py options",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 0))
        self.advanced_vars = {}   # dest -> (spec, tk.Variable)
        scroller = ScrollableFrame(self.advanced_frame, height=190)
        scroller.pack(fill="both", expand=True)

        saved_values = self.settings.get("advanced_values") or {}
        for spec in argspec.advanced_options():
            row = ttk.Frame(scroller.inner, padding=(2, 3))
            row.pack(fill="x", anchor="w")
            label = "%s (default: %s)" % (spec.flag, spec.default)
            if spec.kind == "bool":
                var = tk.BooleanVar(value=bool(saved_values.get(spec.dest, spec.default)))
                ttk.Checkbutton(row, text=label, variable=var).pack(anchor="w")
            elif spec.kind == "choice":
                sub = ttk.Frame(row)
                sub.pack(fill="x")
                ttk.Label(sub, text=label).pack(side="left")
                var = tk.StringVar(value=str(saved_values.get(spec.dest, spec.default)))
                ttk.Combobox(sub, textvariable=var, values=spec.choices, width=10,
                             state="readonly").pack(side="left", padx=6)
            else:
                sub = ttk.Frame(row)
                sub.pack(fill="x")
                ttk.Label(sub, text=label).pack(side="left")
                var = tk.StringVar(value=str(saved_values.get(spec.dest, spec.default)))
                ttk.Entry(sub, textvariable=var, width=12).pack(side="left", padx=6)
            if spec.help:
                ttk.Label(row, text=spec.help, foreground="#777", wraplength=820,
                          justify="left", font=("Segoe UI", 8)).pack(anchor="w")
            self.advanced_vars[spec.dest] = (spec, var)

    def _read_advanced_values(self):
        out = {}
        for dest, (spec, var) in self.advanced_vars.items():
            raw = var.get()
            if spec.kind == "bool":
                out[dest] = bool(raw)
                continue
            if raw == "" or str(raw) == str(spec.default):
                out[dest] = spec.default
                continue
            try:
                if spec.kind == "float":
                    out[dest] = float(raw)
                elif spec.kind == "int":
                    out[dest] = int(raw)
                else:
                    out[dest] = raw
            except ValueError:
                self._log("!! ignoring invalid value %r for %s (keeping default %r)"
                           % (raw, spec.flag, spec.default))
                out[dest] = spec.default
        self.settings["advanced_values"] = {k: v for k, v in out.items()
                                             if v != self.advanced_vars[k][0].default}
        settings_store.save(self.settings)
        return out

    # ---------------------------------------------------------------- debug

    def _build_debug(self):
        self.debug_frame = ttk.Labelframe(self.root, text="Debug: script output", padding=6)
        text_frame = ttk.Frame(self.debug_frame)
        text_frame.pack(fill="both", expand=True)
        self.console = tk.Text(text_frame, height=10, state="disabled", wrap="none",
                                bg="#111", fg="#ddd", font=("Consolas", 9))
        vsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=vsb.set)
        self.console.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _log(self, line):
        self.console.config(state="normal")
        self.console.insert("end", line + "\n")
        self.console.see("end")
        self.console.config(state="disabled")

    def _apply_toggle_states(self):
        self.advanced_frame.pack_forget()
        self.debug_frame.pack_forget()
        if self.advanced_var.get():
            self.advanced_frame.pack(side="top", fill="x", padx=6, pady=(0, 4), before=self.status_bar
                                      if hasattr(self, "status_bar") else None)
        if self.debug_var.get():
            self.debug_frame.pack(side="top", fill="both", expand=True, padx=6, pady=(0, 4),
                                   before=self.status_bar if hasattr(self, "status_bar") else None)
        self.settings["debug"] = self.debug_var.get()
        self.settings["advanced"] = self.advanced_var.get()
        settings_store.save(self.settings)

    # --------------------------------------------------------------- status

    def _build_status(self):
        self.status_bar = ttk.Frame(self.root, padding=6)
        self.status_bar.pack(side="bottom", fill="x")

        self.selected_var = tk.StringVar(value="Selected 0/0 songs")
        ttk.Label(self.status_bar, textvariable=self.selected_var).pack(side="left")

        self.progress_var = tk.StringVar(value="")
        ttk.Label(self.status_bar, textvariable=self.progress_var).pack(side="left", padx=12)
        self.progress = ttk.Progressbar(self.status_bar, mode="determinate", length=220)
        self.progress.pack(side="left")

        self.convert_btn = ttk.Button(self.status_bar, text="Convert", command=self.on_convert)
        self.convert_btn.pack(side="right")
        self.cancel_btn = ttk.Button(self.status_bar, text="Cancel", command=self.on_cancel, state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 6))
        ttk.Button(self.status_bar, text="Select All", command=self.on_select_all).pack(side="right", padx=(0, 6))
        ttk.Button(self.status_bar, text="Generate Convert Note",
                   command=self.on_generate_note).pack(side="right", padx=(0, 6))

    def _update_selected_count(self):
        self.selected_var.set("Selected %d/%d songs" % (len(self.tree.selection()), len(self.songs)))

    # ------------------------------------------------------------- actions

    def on_open_game_folder(self):
        d = filedialog.askdirectory(title="Select the game / update folder")
        if d:
            self.load_game_folder(d)

    def load_game_folder(self, folder, quiet=False):
        try:
            songs, music_dir = music_db.load_library(folder)
        except FileNotFoundError as e:
            if not quiet:
                messagebox.showerror(
                    "Invalid game folder",
                    "Couldn't find:\n%s\n\nA game/update folder needs data/others/music_db.xml "
                    "and data/music." % e)
            return
        self.songs = songs
        self.music_dir = music_dir
        self.game_folder_var.set(folder)
        self.settings["game_folder"] = folder
        settings_store.save(self.settings)
        self._populate_table()

    def _populate_table(self):
        self.tree.delete(*self.tree.get_children())
        self.row_to_song = {}
        query = self.search_var.get().strip().lower()
        for song in sorted(self.songs, key=lambda s: s.id):
            if query and query not in song.title.lower() and query not in song.artist.lower():
                continue
            iid = self.tree.insert("", "end", values=(song.id, song.title, song.artist, song.version_name))
            self.row_to_song[iid] = song
        self._update_selected_count()

    def on_choose_output_folder(self):
        d = filedialog.askdirectory(title="Select the output folder")
        if d:
            self.output_folder_var.set(d)
            self.settings["output_folder"] = d
            settings_store.save(self.settings)

    def on_reveal_output_folder(self):
        d = self.output_folder_var.get()
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa: S606 - Windows-only app, user's own folder
        else:
            messagebox.showinfo("No output folder", "Set an output folder first.")

    def on_select_all(self):
        self.tree.selection_set(self.tree.get_children(""))

    def on_select_none(self):
        self.tree.selection_remove(self.tree.get_children(""))

    def on_generate_note(self):
        selected = [self.row_to_song[iid] for iid in self.tree.selection() if iid in self.row_to_song]
        if not selected:
            messagebox.showinfo("Nothing selected", "Select at least one song first.")
            return
        diff_keys = {k for k, v in self.diff_vars.items() if v.get()}
        if not diff_keys:
            messagebox.showwarning("No difficulties", "Check at least one difficulty first.")
            return
        text = convert_note.generate(selected, diff_keys)
        ConvertNoteDialog(self.root, text)

    def on_open_settings(self):
        SettingsDialog(self)

    def on_about(self):
        messagebox.showinfo("About vox2ksh",
                             "vox2ksh %s\nhttps://github.com/%s"
                             % (__version__, release_check.REPO))

    # ------------------------------------------------------------- convert

    def on_convert(self):
        if self.worker is not None:
            return
        if not self.music_dir:
            messagebox.showwarning("No game folder", "Open a game/update folder first.")
            return
        selected = [self.row_to_song[iid] for iid in self.tree.selection() if iid in self.row_to_song]
        if not selected:
            messagebox.showinfo("Nothing selected", "Select at least one song to convert.")
            return
        out_dir = self.output_folder_var.get()
        if not out_dir:
            messagebox.showwarning("No output folder", "Set an output folder first.")
            return
        diff_keys = {k for k, v in self.diff_vars.items() if v.get()}
        if not diff_keys:
            messagebox.showwarning("No difficulties", "Check at least one difficulty to convert.")
            return
        os.makedirs(out_dir, exist_ok=True)

        jobs = convert_worker.plan_jobs(selected, self.music_dir, out_dir, diff_keys,
                                         fallback_music_dir=self.fallback_music_dir)
        if not jobs:
            messagebox.showinfo("Nothing to do",
                                 "None of the selected songs have a chart for the checked difficulties.")
            return

        opts = convert_worker.BatchOptions(
            se_bank_dir=self._resolve_se_bank_dir(),
            ffmpeg_path=self._resolve_ffmpeg(),
            render_audio=True,
            standard_slam_gap=self.slam_gap_var.get(),
            pretilt_fix=self.pretilt_var.get(),
            advanced_values=self._read_advanced_values(),
        )
        self._log("=== starting: %d job(s) across %d song(s) -> %s ===" % (len(jobs), len(selected), out_dir))
        self.progress.configure(maximum=len(jobs), value=0)
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.worker = convert_worker.ConvertWorker(
            jobs, opts,
            on_log=lambda line: self.events.put(("log", line)),
            on_progress=lambda i, total, job: self.events.put(("progress", i, total, job)),
            on_done=lambda results, cancelled: self.events.put(("done", results, cancelled)),
        )
        self.worker.start()

    def on_cancel(self):
        if self.worker is not None:
            self.cancel_btn.configure(state="disabled")
            self._log("-- cancelling after the current file --")
            self.worker.cancel()

    def _resolve_se_bank_dir(self):
        override = self.settings.get("se_bank_dir")
        if override and os.path.isdir(override):
            return override
        bundled = paths.default_se_bank_dir()
        if bundled:
            return bundled
        if self.fallback_music_dir:
            cand = os.path.join(os.path.dirname(self.fallback_music_dir), "sound", "ver5")
            if os.path.exists(os.path.join(cand, "general_sampler.s3p")):
                return cand
        return None

    def _resolve_ffmpeg(self):
        override = self.settings.get("ffmpeg_path")
        if override and os.path.exists(override):
            return override
        return paths.default_ffmpeg()

    # --------------------------------------------------------------- queue

    def _poll_events(self):
        try:
            while True:
                kind, *payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload[0])
                elif kind == "progress":
                    self._on_progress(*payload)
                elif kind == "done":
                    self._on_done(*payload)
                elif kind == "update":
                    self._on_update_check(payload[0])
        except queue.Empty:
            pass
        self.root.after(50, self._poll_events)

    def _on_progress(self, i, total, job):
        self.progress.configure(maximum=total, value=i)
        self.progress_var.set("Converting %d/%d: %s (%s)" %
                               (i + 1, total, job.song.title, music_db.DIFF_SHORT[job.diff_key]))

    def _on_done(self, results, cancelled):
        self.worker = None
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        # _on_progress sets value=i (the index a job *starts* at), so the last
        # job's start only ever pushes it to total-1/total - snap it the rest
        # of the way here. Also correct when cancelled: len(results) is how
        # many jobs actually ran, which is genuinely a partial fill, not a bug.
        self.progress.configure(value=len(results))
        ok = sum(1 for r in results if r.ok)
        audio = sum(1 for r in results if r.wrote_audio)
        msg = "%s: %d/%d job(s) ok (%d with audio rendered)" % \
              ("Cancelled" if cancelled else "Done", ok, len(results), audio)
        self.progress_var.set(msg)
        self._log("=== %s ===" % msg)
        failed = [r for r in results if not r.ok]
        if failed:
            self._log("failed:")
            for r in failed:
                self._log("  %s (%s): %s" % (r.job.song.folder, r.job.diff_key, r.error))

    def _on_update_check(self, tag):
        if tag:
            self.update_label.config(
                text="A newer version is available (%s) - click to open the releases page." % tag)
        else:
            self.update_label.config(text="")


class ConvertNoteDialog(tk.Toplevel):
    """Read-write text preview of a generated convert note - editable in
    place (nothing here round-trips back into the app, it's a one-shot text
    artifact for pasting elsewhere) with a one-click Copy."""

    def __init__(self, root, text):
        super().__init__(root)
        self.title("Convert Note")
        self.geometry("520x480")
        self.transient(root)

        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", font=("Consolas", 10))
        vsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.text.insert("1.0", text)

        btns = ttk.Frame(frame, padding=(0, 8, 0, 0))
        btns.pack(fill="x")
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Copy to Clipboard", command=self._copy).pack(side="right", padx=(0, 6))

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end-1c"))


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.title("Settings")
        self.resizable(False, False)
        self.transient(app.root)

        fields = [
            ("fallback_game_folder", "Fallback / base game folder",
             "Used to find audio (.s3v) and jackets a chart-only update didn't reship. Optional.", True),
            ("ffmpeg_path", "ffmpeg.exe path",
             "Leave blank to auto-detect (bundled copy, then PATH, then a winget install).", False),
            ("se_bank_dir", "SE sample bank folder",
             "Folder containing general_sampler.s3p / virtical_shot.s3p. Leave blank to auto-detect "
             "(bundled copy, then the fallback game folder above).", True),
        ]
        self.vars = {}
        for row, (key, label, desc, is_dir) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=row * 2, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))
            var = tk.StringVar(value=app.settings.get(key, ""))
            self.vars[key] = var
            ttk.Entry(self, textvariable=var, width=52).grid(row=row * 2 + 1, column=0, sticky="ew", padx=(8, 4))
            cmd = (lambda v=var, d=is_dir: self._browse(v, d))
            ttk.Button(self, text="Browse...", command=cmd).grid(row=row * 2 + 1, column=1, padx=(0, 8))
            ttk.Label(self, text=desc, foreground="#777", wraplength=440, justify="left",
                      font=("Segoe UI", 8)).grid(row=row * 2 + 2, column=0, columnspan=2, sticky="w", padx=8)

        btns = ttk.Frame(self, padding=8)
        btns.grid(row=99, column=0, columnspan=2, sticky="e")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=self._save).pack(side="right", padx=(0, 6))
        self.columnconfigure(0, weight=1)

    def _browse(self, var, is_dir):
        if is_dir:
            d = filedialog.askdirectory(title="Select folder")
        else:
            d = filedialog.askopenfilename(title="Select file")
        if d:
            var.set(d)

    def _save(self):
        for key, var in self.vars.items():
            self.app.settings[key] = var.get()
        settings_store.save(self.app.settings)
        self.app.fallback_music_dir = music_db.fallback_music_dir(
            self.app.settings.get("fallback_game_folder"))
        self.destroy()
