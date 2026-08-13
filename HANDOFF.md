# Handoff — vox2ksh

The reverse-engineering phase is finished and its state lives in the specs, not here. The Tkinter application (`gui/`) has landed - this file now tracks what's still open on it.

Where everything else is:

* [`README.md`](README.md) — status of the three elements (audio, notes, camera) in one table.
* [`specs/`](specs/README.md) — the writeups. Open technical questions are collected in `specs/audio_engine.md` §8, `specs/vox_format.md` "Open questions", and `specs/camera.md`.
* [`scripts/audio/README.md`](scripts/audio/README.md) — how to score a render against a cabinet recording, and how to read the metric. Read it before running any audio experiment; the columns are easy to misread.
* [`gui/README.md`](gui/README.md) — what each GUI module does. [`build/README.md`](build/README.md) — how to package it.

---

## Fixed since last pass

* **`<difnum>` is the level with its decimal point removed, not a plain integer** - `207` means level `20.7`, confirmed against `2393_alive_dadadaizu` and consistent across the rest of the loaded set (values otherwise made no sense as plain SDVX levels, old catalog songs included). `Difficulty.level_display` (`gui/music_db.py`) shows it as-is; `Difficulty.level_int` rounds and clamps to `ksh_format.md`'s required `1-20` int for the `.ksh` `level=` field.
* **jk_<id>_<n>.png's numbering is per difficulty tag (1..5: novice/advanced/exhaust/infinite/maximum), not per UI tile (1..4)** - a song with `maximum` and no `infinite` can ship `jk_<id>_5.png` with no `jk_<id>_4.png` at all (confirmed on `2393_alive_dadadaizu`), so reusing the UI tile number for the file lookup silently grabbed the wrong image (or none). `jacket_path()`/`thumb_path()` now key off the difficulty tag via `DIFF_JACKET_NUM`, separate from `DIFF_TILE` (UI placement only, still 1..4).
* **Output folder/filenames drop the numeric song id** (`alive_dadadaizu/alive_dadadaizu_1n.ksh`, not `2393_alive_dadadaizu/...`) - `convert_worker.plan_jobs()` uses `song.ascii` instead of `song.folder`. Two real entries share one ascii name (`gott_hommarju`: ids 125 and 1491), so a same-batch collision falls back to the id-prefixed name for whichever of the two is planned second, rather than one silently overwriting the other's output on disk. That fallback only sees the current batch - converting one half of a colliding pair, then the other half in a *separate* Convert run into the same output folder, would still overwrite; not worth solving for 2 songs out of 2167. `apply_chart.py`'s `decode_audio()`/`encode_pcm()` (used for the track, every SE sample in the bank, and the output encode - a dozen-plus calls per render) run ffmpeg via `subprocess.run` with no window-suppression; a windowed GUI process (`console=False`) has no console of its own, so Windows pops a fresh one for each call. Fixed with `creationflags=CREATE_NO_WINDOW` on both call sites - a no-op for the CLI, since there's nothing extra to hide when already run from a terminal.

## Resolved

* **The app is built for people who don't have a game install at all** - `contents/` is the *developer's* machine, not the intended user's. Confirmed by actually running the frozen exe with `sys._MEIPASS` as its only source of anything and no fallback folder configured: it resolved the SE bank and ffmpeg entirely from its own bundled payload and rendered real layered SE (FX chip samples, laser slams) from a chart with no game install anywhere in reach. The one thing the exe genuinely cannot supply on its own is a specific song's `.s3v` when the input folder the user points it at doesn't carry one (see "Still open" below) - everything else needed at runtime is self-contained.
* **The layered SE bank ships with the build.** `build/build_assets.py` copies `general_sampler.s3p`/`virtical_shot.s3p` (+ `.def`) as-is into `gui/assets/`, PyInstaller bundles them, and `apply_chart.py`'s new `--se-bank-dir` lets the GUI point straight at that copy. Not a redistribution problem the way song data would be - it's shared engine furniture (a handful of hit-sound samples), not game content, and small (~1.5 MB). `gui/paths.py`'s fallback order (bundled copy -> a user-configured fallback game folder -> deriving it from the chart folder, `apply_chart.py`'s original behaviour) exists for local/dev use; the bundled copy is what the *distributed* exe actually relies on.
* **Scope: batch, not single-chart.** The table supports multi-select + Select All; conversion runs one job per (song, checked difficulty).
* **Game/output folders are explicit and remembered** between runs (`gui/settings.py`, `%APPDATA%\vox2ksh-gui\settings.json`).
* **Progress/cancel are job-granular, not intra-render.** `apply_chart.main()` has no internal yield points and wasn't restructured to add any - see `convert_worker.py`'s module docstring for the reasoning. Cancel stops the queue before its next job; a render already running finishes.
* **Diagnostic flags: an Advanced panel, closed by default**, built by introspecting `apply_chart.build_arg_parser()` (`gui/argspec.py`) rather than hand-picking a subset - every flag shows its default and help text, and only ones actually changed from default get passed on the command line. `--peak-gain-scale`/`--peak-max-gain` are in there like everything else rather than singled out; nothing stops a user from finding and adjusting them, which was the actual goal.
* **Packaging**: `build/vox2ksh_gui.spec` + `build/build.py`, PyInstaller, onefile. `scripts/{notes,audio,camera,shared}` are pulled in via `pathex` (compiled into the bundle, not shipped as readable source) rather than as raw `datas`.

## Still open

* **Added: "Generate Convert Note" button** (`gui/convert_note.py`, `ConvertNoteDialog` in `app.py`) - builds a "New Songs Added"-style announcement from the table's current selection and the checked difficulty filter, one line per song as `[level/level/...]  Title` (mxm/inf -> exh -> adv -> nov priority, only the checked tiers, `Difficulty.level_display` formatting - a whole level drops its `.0`). Sorted by highest included level, descending. Opens in a small editable Toplevel with a Copy-to-clipboard button; nothing round-trips back into the app state.
* **A chart-only game update can omit a song's `.s3v`** (confirmed against a real update folder: ~20% of its songs had a `.vox` with no matching audio - the song wasn't musically changed, so it wasn't reshipped). This is a real, unfixable gap for the app's actual audience: someone with only an update folder and no other install has no fallback source for that audio, and there is nothing to default the Settings fallback-folder field *to* on a machine with no game data on it at all - `scripts/shared/_paths.GAME` (this checkout's own `contents/`) is a *developer*-machine concept and must not be used as that default, or as any other implicit fallback, in the shipped app. The Settings field stays a manual, optional override for the rarer case of someone who happens to have a second dump lying around; those songs are chart-only (no audio) for everyone else.
* **No per-song difficulty override in the table itself** - the Advanced difficulty filter (NOV/ADV/EXH/top-tier checkboxes) is global across the whole batch. Skipping one difficulty for one specific song means deselecting that song and converting it separately.
* **ffmpeg licensing is the packager's responsibility**, not something `build_assets.py` checks - see `build/README.md`'s callout. A GPL build works fine locally but shouldn't be redistributed without complying with the GPL; use an LGPL "shared" build for that.
* **No audio preview in the UI** - the jacket tiles are visual only, clicking them doesn't play anything. `data/music`'s `_pre.s3v` (a preview snippet, separate from the full track) is unused.

# To-do

* Implement Pitch Shift
* Derive spin length using regression
* "note: 2 camera event(s) past the chart's last real note were dropped" this shouldn't be a thing 
* work on removing pretilt again??