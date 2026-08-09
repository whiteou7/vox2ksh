"""Path resolution for every script in this project.

Nothing here is hard-coded to one machine: paths are derived from this file's
location, with environment-variable overrides for the things that live outside
the repo (the game install, the Ghidra symbol dump, ffmpeg).

    PROJECT   .../contents/vox2ksh
    GAME      .../contents                 the game install (override: SDVX_GAME)
    DLL       GAME/modules/soundvoltex.dll (override: SDVX_DLL)
    MUSIC     GAME/data/music              the .vox / .s3v charts
    SOUND     GAME/data/sound              the .s3p sample banks
    OUTPUT    PROJECT/output               git-ignored, all script output
    WORK      PROJECT/output/work          git-ignored, big intermediate WAVs
    SYMS      C:/rev/out/syms_all.txt      Ghidra symbol dump (override: SDVX_SYMS)

WORK is not checked in. Regenerate the two WAVs the audio metric needs with:

    ffmpeg -i <MUSIC>/2229_kamui_tjhangneil/2229_kamui_tjhangneil.s3v \
           -ar 44100 -ac 2 -c:a pcm_s16le -y <WORK>/kamui_dry.wav
    ffmpeg -i scripts/audio/reference/kamui_goal.ogg \
           -ar 44100 -ac 2 -c:a pcm_s16le -y <WORK>/goal.wav

and copy whatever render you are scoring to <WORK>/best.wav.
"""
import os

SHARED = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(SHARED)
PROJECT = os.path.dirname(SCRIPTS)

GAME = os.environ.get("SDVX_GAME") or os.path.dirname(PROJECT)
DLL = os.environ.get("SDVX_DLL") or os.path.join(GAME, "modules", "soundvoltex.dll")
MUSIC = os.path.join(GAME, "data", "music")
SOUND = os.path.join(GAME, "data", "sound")

OUTPUT = os.path.join(PROJECT, "output")
WORK = os.path.join(OUTPUT, "work")

SYMS = os.environ.get("SDVX_SYMS") or r"C:\rev\out\syms_all.txt"

REFERENCE = os.path.join(SCRIPTS, "audio", "reference")


def ensure_work():
    """Create the work directory on demand and return it."""
    os.makedirs(WORK, exist_ok=True)
    return WORK


def find_ffmpeg():
    """ffmpeg from FFMPEG env var, then PATH, then a winget install."""
    env = os.environ.get("FFMPEG")
    if env and os.path.exists(env):
        return env
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    root = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(root):
        for dp, _dn, fns in os.walk(root):
            if "ffmpeg.exe" in fns:
                return os.path.join(dp, "ffmpeg.exe")
    return None
