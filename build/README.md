# Building vox-multiconvert

Packs `gui/` and `scripts/` into one Windows `.exe` with PyInstaller, bundling the SE sample bank and ffmpeg.

## Setup

```bash
pip install -r requirements-gui.txt
pip install pyinstaller
```

## Build

```bash
python build/build.py
```

Two steps:

1. `build/build_assets.py` copies the SE bank from the game install into `gui/assets/sound/ver5/` and finds ffmpeg on `PATH` or in a winget install.
2. PyInstaller, using `build/vox2ksh_gui.spec`, writes `build/dist/vox-multiconvert.exe`.

Options:

```bash
python build/build.py --game "D:\some\other\install"
python build/build.py --skip-assets
```

Or by hand:

```bash
python build/build_assets.py --ffmpeg "C:\tools\ffmpeg-lgpl\bin\ffmpeg.exe"
pyinstaller build/vox2ksh_gui.spec
```

## ffmpeg license

`build_assets.py` bundles whatever ffmpeg it finds. A full build (the default from `winget install Gyan.FFmpeg`) is GPL, so redistributing it means offering the source. Only decoding and Vorbis/PCM encoding are used, so for a build you share, pass `--ffmpeg` an LGPL build (Gyan `*-lgpl-shared`, BtbN `*-lgpl`).

## Not bundled

Charts, audio, jackets and `music_db.xml`. Users point the app at their own folder.

## Output

`build/dist/vox-multiconvert.exe` (a few hundred MB, mostly ffmpeg and numpy). `build/work/`, `build/dist/` and `gui/assets/` are git-ignored.
