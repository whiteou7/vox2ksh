"""Path resolution for the GUI, dev-run and frozen (PyInstaller) alike.

Dev run:    vox2ksh/gui/paths.py -> PROJECT = vox2ksh/, SCRIPTS = vox2ksh/scripts
Frozen run: sys._MEIPASS/gui/paths.py (or next to the exe for onedir builds) ->
            the same scripts/ tree is bundled as data files at the same
            relative layout, so the two cases resolve identically once
            BASE is picked correctly.

Bundled-only extras (built by build/build_assets.py, absent in a dev checkout
unless someone runs that script locally):
    BUNDLED_SOUND   general_sampler.s3p / virtical_shot.s3p (+ .def), so a
                    game-update folder that doesn't carry the SE bank still
                    renders layered SE - see HANDOFF.md item 1.
    BUNDLED_FFMPEG  ffmpeg.exe, so the app doesn't need one on PATH.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # PyInstaller onefile: sys._MEIPASS is the extraction tmpdir. Onedir:
    # it's the folder the exe sits in. Either way build/build_assets.py lays
    # scripts/ and gui/assets/ out under it at these same relative paths.
    BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # vox2ksh/

PROJECT = BASE
SCRIPTS = os.path.join(PROJECT, "scripts")
NOTES_DIR = os.path.join(SCRIPTS, "notes")
AUDIO_DIR = os.path.join(SCRIPTS, "audio")
CAMERA_DIR = os.path.join(SCRIPTS, "camera")
SHARED_DIR = os.path.join(SCRIPTS, "shared")

ASSETS = os.path.join(BASE, "gui", "assets")
BUNDLED_SOUND = os.path.join(ASSETS, "sound", "ver5")
BUNDLED_FFMPEG = os.path.join(ASSETS, "ffmpeg", "ffmpeg.exe")

# CAMERA_DIR is deliberately NOT added here: scripts/camera/convert.py and
# scripts/notes/convert.py share a module name ("convert"), and whichever
# directory sys.path favours wins an `import convert` ambiguously. This
# module only ever wants notes/convert.py (called with camera=True, which
# makes it import scripts/camera/camera.py itself, under the alias
# `camera_mod` - see that function's docstring) - never scripts/camera/
# convert.py's own thin CLI wrapper, so its directory is left off sys.path.
for _p in (NOTES_DIR, AUDIO_DIR, SHARED_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def default_se_bank_dir():
    """Bundled SE bank dir if the build shipped one, else None (apply_chart.py
    then falls back to deriving it from the chart folder itself)."""
    if os.path.exists(os.path.join(BUNDLED_SOUND, "general_sampler.s3p")):
        return BUNDLED_SOUND
    return None


def default_ffmpeg():
    """Bundled ffmpeg.exe if the build shipped one, else None (apply_chart.py /
    _paths.py then fall back to PATH / the FFMPEG env var themselves)."""
    if os.path.exists(BUNDLED_FFMPEG):
        return BUNDLED_FFMPEG
    return None
