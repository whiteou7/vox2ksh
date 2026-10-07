"""Matches the folders in scripts/shared/reference/ksh to charts in data/music by name (41 of 86 folders match). Each folder holds a hand-made .ksh conversion and gameplay recordings with effects applied (not the clean song). The highest difficulty present is what was recorded (mxm > exh > adv > nov). Used by the audio-refcheck and notes-refcheck skills. feelsseasickness isn't in the set; its recording is at the project root.
"""
import collections
import os
import re

from game_paths import MUSIC, SCRIPTS

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")

DIFF_SUFFIX = {
    "nov": "1n", "adv": "2a", "exh": "3e",
    "inf": "4i", "grv": "4i", "hvn": "4i", "vvd": "4i", "xcd": "4i",
    "mxm": "5m",
}


def music_index():
    music = collections.defaultdict(list)
    for d in sorted(os.listdir(MUSIC)):
        m = re.match(r"^(\d+)_(.*)$", d)
        if m:
            music[m.group(2).replace("_", "")].append(d)
    return music


def match_songs():
    music = music_index()

    out = {}
    for r in sorted(os.listdir(REF)):
        if not os.path.isdir(os.path.join(REF, r)):
            continue
        key = r.replace("_", "")
        if key in music:
            cands = music[key]
        else:
            cands = [(k, v) for k, vs in music.items()
                     for v in vs if (k.startswith(key) or key.startswith(k))]
            cands = [v for k, v in cands]
            keyed = [(k, v) for k, vs in music.items() for v in vs if k.startswith(key)]
            if len(keyed) >= 1 and len(cands) > 1 and len(keyed) <= 5:
                keyed.sort(key=lambda kv: len(kv[0]) - len(key))
                if len(keyed) == 1 or len(keyed[0][0]) < len(keyed[1][0]):
                    cands = [keyed[0][1]]
        if len(cands) == 1:
            out[r] = cands[0]
    return out
