# PyInstaller spec for vox2ksh.
#
#     python build/build_assets.py          # stages gui/assets/{sound,ffmpeg}
#     pyinstaller build/vox2ksh_gui.spec    # or just: python build/build.py
#
# Everything under scripts/ (notes, audio, camera, shared) is reached via
# `pathex` rather than shipped as raw `datas` - gui/*.py imports those
# modules by plain name (e.g. `import apply_chart`) after inserting their
# directories onto sys.path at runtime (gui/paths.py; see that module's
# docstring), and pathex tells PyInstaller's analysis to resolve the same
# names the same way ahead of time. The result is that the conversion
# scripts end up compiled into the bundle's PYZ archive like any other
# dependency, not sitting alongside the exe as readable .py source - see
# build_assets.py's docstring for why that split matters (game/engine
# assets are fine to ship, this project's own source is kept out of the
# distributed build).
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
GUI = os.path.join(ROOT, "gui")
SCRIPTS = os.path.join(ROOT, "scripts")
ASSETS = os.path.join(GUI, "assets")

datas = []
if os.path.isdir(ASSETS):
    # gui/assets/{sound/ver5/*, ffmpeg/ffmpeg.exe} -> same relative layout
    # next to the exe, read back by gui/paths.py's BUNDLED_* constants.
    for dirpath, _dirnames, filenames in os.walk(ASSETS):
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(dirpath, GUI)
            datas.append((src, os.path.join("gui", rel)))

a = Analysis(
    [os.path.join(GUI, "main.py")],
    pathex=[
        GUI,
        os.path.join(SCRIPTS, "notes"),
        os.path.join(SCRIPTS, "audio"),
        os.path.join(SCRIPTS, "camera"),
        os.path.join(SCRIPTS, "shared"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=["numpy"],
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

# Passing a.binaries/a.datas straight into EXE() (rather than to a separate
# COLLECT()) is what makes this a onefile build - everything self-extracts
# to a temp dir at launch (gui/paths.py's sys._MEIPASS).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="vox2ksh",
    console=False,
)
