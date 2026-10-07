import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
GUI = os.path.join(ROOT, "gui")
SCRIPTS = os.path.join(ROOT, "scripts")
ASSETS = os.path.join(GUI, "assets")

datas = []
if os.path.isdir(ASSETS):
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="vox2ksh",
    console=False,
)
