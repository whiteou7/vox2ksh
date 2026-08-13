"""Small persisted-settings store for the GUI - game/output folders and the
optional overrides (fallback install, ffmpeg, SE bank dir), remembered
between runs so the user isn't re-picking the same folders every launch
(HANDOFF.md item 2: "an app needs an explicit install path, remembered
between runs")."""
import json
import os

_DEFAULTS = {
    "game_folder": "",
    "output_folder": "",
    "fallback_game_folder": "",
    "ffmpeg_path": "",
    "se_bank_dir": "",
    "difficulties": ["novice", "advanced", "exhaust", "top"],
    "debug": False,
    "advanced": False,
    "advanced_values": {},
}


def _store_path():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(root, "vox2ksh-gui")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


def load():
    path = _store_path()
    data = dict(_DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except (OSError, ValueError):
            pass  # corrupt/unreadable settings file -> fall back to defaults
    return data


def save(data):
    try:
        with open(_store_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass  # best-effort; not being able to persist settings isn't fatal
