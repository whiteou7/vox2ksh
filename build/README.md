# Building vox-multiconvert

Packages `gui/` (the Tkinter app) plus everything under `scripts/{notes,audio,camera,shared}` it calls into into a single Windows `.exe` via [PyInstaller](https://pyinstaller.org/), with the layered-SE sample bank and an `ffmpeg` binary staged into it so a user doesn't need either lying around separately - see `gui/paths.py` and `HANDOFF.md` item 1 for why.

## One-time setup

```bash
pip install -r requirements-gui.txt
pip install pyinstaller
```

`pyinstaller` is deliberately not in `requirements-gui.txt` - it's a build-time tool, not something the app imports at runtime.

## Build

```bash
python build/build.py
```

This runs two steps (also runnable separately, see below):

1. **`build/build_assets.py`** stages `gui/assets/sound/ver5/{general_sampler,virtical_shot}.{s3p,def}` (copied from the game install this checkout sits inside, i.e. `scripts/shared/_paths.GAME` - same resolution every other script here uses) and `gui/assets/ffmpeg/ffmpeg.exe` (auto-detected from PATH or a winget install). Both are read back at runtime by `gui/paths.py`.
2. **PyInstaller**, via `build/vox2ksh_gui.spec`, builds a single onefile exe at `build/dist/vox-multiconvert.exe`. `scripts/{notes,audio,camera,shared}` are pulled in through `pathex` (compiled into the bundle's PYZ archive, the same way any other Python dependency is - not copied in as readable `.py` source) rather than as raw data files - see the spec's own comment for why that split matters.

Point it at a different install, or reuse assets you already staged:

```bash
python build/build.py --game "D:\some\other\install"     # different game copy
python build/build.py --skip-assets                      # reuse gui/assets/ as-is
```

Run the two steps by hand if you want more control (e.g. a specific ffmpeg build):

```bash
python build/build_assets.py --ffmpeg "C:\tools\ffmpeg-lgpl\bin\ffmpeg.exe"
pyinstaller build/vox2ksh_gui.spec
```

## ffmpeg licensing - read before shipping a build to anyone else

`build_assets.py` bundles whatever `ffmpeg.exe` it finds (PATH, then a winget install) without checking its license. A "full" build (e.g. the default from `winget install Gyan.FFmpeg`) is GPL, which obliges you to also offer the corresponding source if you redistribute the binary. This project only needs ffmpeg to decode `.s3v`/`.s3p` (ASF/WMA) and encode Vorbis/PCM - no GPL-only component (libx264, etc.) is exercised - so point `--ffmpeg` at an **LGPL "shared" build** (e.g. Gyan's `*-lgpl-shared` builds, or BtbN's `*-lgpl` builds) if you plan to distribute the exe. A GPL build is fine for building and running locally.

## What's NOT bundled, on purpose

Charts, audio, jackets, and `music_db.xml` - i.e. anything identifying a specific game install - are never copied into the build. The app requires the user to point it at their own game/update folder at runtime, same as the scripts have always required (top-level `README.md`: "This writeup discusses arcade game data but will not provide the location to get it").

## Running from source instead

No build needed for this - just:

```bash
python gui/main.py
```

`gui/paths.py` falls back to PATH/winget-detected ffmpeg and to deriving the SE bank location from whatever folder is open (or a fallback game folder set in Settings) when `gui/assets/` hasn't been staged.

## Output

`build/dist/vox-multiconvert.exe` - a few hundred MB, dominated by the bundled ffmpeg binary and numpy. `build/work/` is PyInstaller's intermediate build directory; both are git-ignored, along with `gui/assets/`, since all three are fully regenerable from this directory.
