"""Locates the game install, the DLL, data/music, data/sound, the output and work directories, the Ghidra symbol dump and ffmpeg. Overrides: SDVX_GAME, SDVX_DLL, SDVX_SYMS, FFMPEG. Nothing else should hard-code a path.

Everything scripts write goes under output/, which is git-ignored and safe to delete. The calibration WAVs live in output/work/ (created on demand by ensure_work): kamui_dry.wav (the song decoded from its .s3v), goal.wav (kamui_goal.ogg decoded) and best.wav (the render being scored), all made with ffmpeg, and gs/ (the general_sampler bank, from unpack_s3p.py).
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
    os.makedirs(WORK, exist_ok=True)
    return WORK


def find_ffmpeg():
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
