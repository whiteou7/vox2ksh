"""GitHub release check for github.com/whiteou7/vox2ksh.

Requirement is narrow and deliberate: if a newer release exists, show red
text telling the user to update - nothing more. No download, no auto-update,
no dialog. Runs on a background thread (network) and reports back through a
callback so it never blocks the UI.
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
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3) for comparison; missing/odd parts
    become 0 rather than raising, since a release tag isn't guaranteed to be
    strict semver and a malformed tag should just fail the "is newer" check,
    not crash the whole app."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    if not m:
        return (0, 0, 0)
    return tuple(int(g) for g in m.groups())


def is_newer(latest_tag, current=__version__):
    return _parse_semver(latest_tag) > _parse_semver(current)


def fetch_latest():
    """-> tag_name (str) for the repo's latest release, or None if there is
    no release yet / the request failed for any reason (offline, rate
    limited, etc.) - all treated the same: nothing to show the user."""
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
    """Fire-and-forget background check. `on_result(tag_or_none)` is called
    from the worker thread - the caller marshals it back onto the UI thread
    (e.g. via Tk's `after`), this module has no UI dependency."""
    def run():
        tag = fetch_latest()
        on_result(tag if tag and is_newer(tag) else None)
    t = threading.Thread(target=run, name="release-check", daemon=True)
    t.start()
    return t
