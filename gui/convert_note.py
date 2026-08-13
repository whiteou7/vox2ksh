"""Generates a plain-text "convert note" - a New-Songs-Added-style announcement
listing the selected songs and the levels of whichever difficulties were
selected for them, for pasting into a forum post/changelog by hand. Purely a
text-formatting helper; no file I/O, no dependency on gui/app.py.
"""
SEPARATOR = "-" * 50


def _wanted_diffs_for(song, diff_keys):
    """diff_keys (the checked NOV/ADV/EXH/top filter) resolved for one song,
    in mxm/inf -> exh -> adv -> nov priority - the order the bracket is
    written in, highest level first."""
    wanted = set(diff_keys)
    if "top" in wanted:
        wanted.discard("top")
        top = song.top_difficulty()
        if top:
            wanted.add(top.key)

    order = []
    top = song.top_difficulty()
    if top and top.key in wanted:
        order.append(top)
    for key in ("exhaust", "advanced", "novice"):
        d = song.difficulties.get(key)
        if d and key in wanted:
            order.append(d)
    return order


def generate(songs, diff_keys, header="New Songs Added"):
    """songs: iterable of music_db.Song (the table's current selection).
    diff_keys: the checked difficulty filter, same set convert_worker.plan_jobs
    takes ("novice"/"advanced"/"exhaust"/"top").

    Songs with none of the checked difficulties present are skipped (nothing
    to show for them). Sorted by the bracket's first (highest) level,
    descending - same order the hand-written example follows.
    """
    entries = []
    for song in songs:
        diffs = _wanted_diffs_for(song, diff_keys)
        if not diffs:
            continue
        bracket = "/".join(d.level_display for d in diffs)
        entries.append((diffs[0].difnum, bracket, song.title))
    entries.sort(key=lambda e: -e[0])

    width = max((len(b) + 2 for _, b, _ in entries), default=0)  # +2 for the [ ]
    lines = [header, SEPARATOR]
    for _, bracket, title in entries:
        cell = ("[%s]" % bracket).ljust(width)
        lines.append("%s    %s" % (cell, title))
    lines += ["", SEPARATOR, "Contributors & Testers", SEPARATOR]
    return "\n".join(lines)
