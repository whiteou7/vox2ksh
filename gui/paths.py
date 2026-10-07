"""Path resolution for source runs and frozen builds, including where a build's bundled SE bank and ffmpeg live.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    BASE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROJECT = BASE
SCRIPTS = os.path.join(PROJECT, "scripts")
NOTES_DIR = os.path.join(SCRIPTS, "notes")
AUDIO_DIR = os.path.join(SCRIPTS, "audio")
CAMERA_DIR = os.path.join(SCRIPTS, "camera")
SHARED_DIR = os.path.join(SCRIPTS, "shared")

ASSETS = os.path.join(BASE, "gui", "assets")
BUNDLED_SOUND = os.path.join(ASSETS, "sound", "ver5")
BUNDLED_FFMPEG = os.path.join(ASSETS, "ffmpeg", "ffmpeg.exe")

for _p in (NOTES_DIR, AUDIO_DIR, SHARED_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def default_se_bank_dir():
    if os.path.exists(os.path.join(BUNDLED_SOUND, "general_sampler.s3p")):
        return BUNDLED_SOUND
    return None


def default_ffmpeg():
    if os.path.exists(BUNDLED_FFMPEG):
        return BUNDLED_FFMPEG
    return None
