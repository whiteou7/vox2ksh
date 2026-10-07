"""Checks GitHub releases for whiteou7/vox2ksh in the background. Shows red text only, no auto-update.
"""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from version import __version__

REPO = "whiteou7/vox2ksh"
API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO
TIMEOUT = 6


def _parse_semver(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(g) for g in m.groups())


def is_newer(latest_tag, current=__version__):
    return _parse_semver(latest_tag) > _parse_semver(current)


def fetch_latest():
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                     "User-Agent": "vox2ksh-gui"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data.get("tag_name")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            ValueError, OSError):
        return None


def check_async(on_result):
    def run():
        tag = fetch_latest()
        on_result(tag if tag and is_newer(tag) else None)
    t = threading.Thread(target=run, name="release-check", daemon=True)
    t.start()
    return t
