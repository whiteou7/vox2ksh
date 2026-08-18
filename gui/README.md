# gui/

The Tkinter application: batch `.vox` -> `.ksh` + rendered audio, wrapping `scripts/notes/convert.py` and `scripts/audio/apply_chart.py`. Packaging: [`../build/README.md`](../build/README.md).

## Running from source

```bash
pip install -r ../requirements-gui.txt
python main.py
```

## The pieces

| file | what it does |
|---|---|
| `app.py` | The window: song table, difficulty filters, jacket/metadata preview, Debug console, Advanced options panel, Settings dialog. `main.py` is the thin entry point. |
| `music_db.py` | Parses `data/others/music_db.xml` (cp932) and cross-references it against `data/music`, producing `Song`/`Difficulty` objects - titles, artists, jackets, levels, illustrators, which difficulties actually have a chart on disk. |
| `convert_worker.py` | The background job queue: per (song, difficulty), calls `notes/convert.py`'s `convert()` (with real metadata via its `meta=` param) then `apply_chart.py`'s `main()`, in-process, on one worker thread. Streams stdout into the Debug console. |
| `argspec.py` | Introspects `apply_chart.build_arg_parser()` into the Advanced panel's controls, skipping whatever the worker already computes per chart (`-d`, `-a`, `-o`, `--se-bank-dir`, `--dry`). The two chart-side checkboxes at the top of that panel - **Standard slam gap** and **Remove pretilt** - are `notes/convert.py` arguments rather than `apply_chart.py` flags, so `app.py` places them by hand above the introspected list. |
| `release_check.py` | Background GitHub-releases check against `whiteou7/vox2ksh` - red text only, no auto-update. |
| `paths.py` | Dev-vs-frozen path resolution; where a build's bundled SE bank / ffmpeg live. |
| `settings.py` | Persists folder choices and panel state between runs (`%APPDATA%\vox2ksh-gui\settings.json`). |

## A game-update folder can be missing things

An input folder (`data/others/music_db.xml` + `data/music`) doesn't have to be a full install - it can be a patch that only ships the songs it actually changed. The distributed app is built for exactly this: someone with an update folder and nothing else, no `contents/` game install anywhere on their machine. Two consequences `music_db.py`/`convert_worker.py` handle differently:

* The SE sample bank (`data/sound/ver5/*.s3p` - laser slams, FX chip hits) and ffmpeg are **fully self-contained in a build** - staged into `gui/assets/` at build time (`../build/README.md`) and read back from the frozen exe's own extracted payload at runtime, no external install needed. Verified by running the actual frozen exe with no fallback folder configured and confirming it still rendered real layered SE.
* A chart-only update (a difficulty retune, say) can carry a `.vox` with no matching `.s3v` - the song's audio didn't change, so it wasn't reshipped, and there is genuinely nowhere on a fallback-less machine to get it from. The Settings **fallback game folder** is a manual, optional field for the rarer case where a user happens to have a second, older dump to point at; it is never defaulted to anything (in particular, never to `scripts/shared/_paths.GAME` - that's this checkout's own dev-machine folder, meaningless once there's no `vox2ksh` checkout at all). Without one, those specific songs convert chart-only (no audio, `.ksh` still written).
