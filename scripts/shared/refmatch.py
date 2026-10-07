"""Match the reference corpus (scripts/shared/reference/ksh) to charts in data/music.

Both refcheck skills (.claude/skills/audio-refcheck, notes-refcheck) pair a
hand-made or captured reference with the game's own chart, so the matching
lives here once rather than being re-implemented per skill. The duplicate that
used to live in the notes check had the same ambiguous-title bug this one's
match_songs() used to have - fixing it in one place is the point.
"""
import collections
import os
import re

from _paths import MUSIC, SCRIPTS

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")

# ksh/ogg basename -> vox difficulty suffix. inf/grv/hvn/vvd/xcd are all the
# same difficulty *slot* (the one above EXH) under different game-version
# skins, not synonyms for mxm.
DIFF_SUFFIX = {
    "nov": "1n", "adv": "2a", "exh": "3e",
    "inf": "4i", "grv": "4i", "hvn": "4i", "vvd": "4i", "xcd": "4i",
    "mxm": "5m",
}


def music_index():
    """normalized title (no underscores) -> [data/music folder, ...]"""
    music = collections.defaultdict(list)
    for d in sorted(os.listdir(MUSIC)):
        m = re.match(r"^(\d+)_(.*)$", d)
        if m:
            music[m.group(2).replace("_", "")].append(d)
    return music


def match_songs():
    """reference folder -> data/music folder, preferring an exact
    normalized-title match over a substring one.

    A short reference folder name (e.g. "e", "oz", "akasha") can be a prefix
    of several unrelated data/music titles ("evans", "ozone", "akasha
    assembly mizonokuchi" vs the real match "akasha"). Matching on substring
    alone silently picks whichever sorts first, which is wrong more than
    once in this corpus - "oz" -> "ozone" and "akasha" -> "akasha assembly
    mizonokuchi" were both confirmed wrong this way (the wrong candidate's
    hardest chart differs in difficulty from what the capture actually is).

    Resolution order:
      1. exact normalized-title match
      2. unambiguous substring match (exactly one candidate)
      3. a *small* (<=5), substring-matching candidate set where the
         data/music folder name is `<ref title>_<artist>` - in that case the
         part of each candidate's name AFTER the ref key is (usually) just
         the artist, and the real match is reliably the SHORTEST such
         remainder: junk matches are prefixes of a much longer, unrelated
         title ("akasha" + "assemblymizonokuchi", 20 chars) while the real
         match is "akasha" + an artist name ("blacky", 6 chars). Only trusted
         when the shortest remainder is strictly shorter than the next one,
         and the candidate pool is small enough that a false rescue is
         implausible - a key like "e" has 70+ candidates and is left
         unmatched rather than guessed at.
    """
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
        # otherwise ambiguous or absent - skip rather than guess; the audio
        # check_all_charts.py logs these under --verbose-match
    return out
