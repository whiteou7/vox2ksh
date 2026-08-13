# Handoff — vox2ksh

The reverse-engineering phase is finished and its state lives in the specs, not here. This file tracks the **current** work: turning the scripts into a Tkinter application.

Where everything else is:

* [`README.md`](README.md) — status of the three elements (audio, notes, camera) in one table.
* [`specs/`](specs/README.md) — the writeups. Open technical questions are collected in `specs/audio_engine.md` §8, `specs/vox_format.md` "Open questions", and `specs/camera.md`.
* [`scripts/audio/README.md`](scripts/audio/README.md) — how to score a render against a cabinet recording, and how to read the metric. Read it before running any audio experiment; the columns are easy to misread.

---

## 1. Bundle the layered SE with the app build

The audio render is not complete without the layered SE (`specs/audio_engine.md` §6.1): laser slams play `virtical_shot[0]` (bank `0xd`) and FX chip notes play `general_sampler[C2]` (bank 9), both from `data/sound/ver5/`, at the gains authored in each sample's `S3V0` header. `apply_chart.py` reads those banks straight out of the game install; an application that anyone can run needs them resolved some other way.

To decide:

* whether the app reads the banks from the user's own install (same as the scripts do now, via `scripts/shared/_paths.py`) or ships decoded copies with the build — the latter means redistributing game audio, which this project has otherwise avoided;
* if it ships them, what format (the decoder is `scripts/audio/s3p_decode.py`) and whether the header gains travel with them or get baked in.

## 2. The Tkinter application

Not started. What it needs to wrap is settled — chart selection, the notes/camera conversion (`scripts/notes/convert.py`, `scripts/camera/convert.py`) and the audio render (`scripts/audio/apply_chart.py`) — but nothing about the UI itself has been decided yet. Open, in rough order of what blocks what:

* **Scope of the first version.** Convert one chart end to end (`.ksh` plus rendered audio), or batch?
* **Where the game data comes from.** The scripts resolve it relative to `vox2ksh/..`; an app needs an explicit install path, remembered between runs.
* **The render is slow and single-shot.** `apply_chart.py` is a CLI that runs to completion; the app needs progress reporting and a cancel, which means either driving it as a subprocess or refactoring the render loop to yield.
* **Which of the diagnostic flags to expose.** The full list is in `specs/audio_engine.md` §6. Most are A/B switches for reverse-engineering work and do not belong in a conversion UI; `--peak-gain-scale`/`--peak-max-gain` (§7.1) are the exception, since they change how the output *sounds* rather than how faithful it is.
* **Packaging.** Python 3.12 plus `numpy` and an `ffmpeg` binary, on Windows.
