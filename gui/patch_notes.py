"""Generates the "New Songs Added" patch-note text for a set of songs and difficulties.
"""
SEPARATOR = "-" * 50


def _difficulties_in_display_order(song, diff_keys):
    wanted = song.resolve_diff_keys(diff_keys)

    order = []
    top = song.top_difficulty()
    if top and top.key in wanted:
        order.append(top)
    for key in ("exhaust", "advanced", "novice"):
        d = song.difficulties.get(key)
        if d and key in wanted:
            order.append(d)
    return order


def generate_new_songs_note(songs, diff_keys, header="New Songs Added"):
    entries = []
    for song in songs:
        diffs = _difficulties_in_display_order(song, diff_keys)
        if not diffs:
            continue
        bracket = "/".join(d.level_display for d in diffs)
        entries.append((diffs[0].difnum, bracket, song.title))
    entries.sort(key=lambda e: -e[0])

    width = max((len(b) + 2 for _, b, _ in entries), default=0)
    lines = [header, SEPARATOR]
    for _, bracket, title in entries:
        cell = ("[%s]" % bracket).ljust(width)
        lines.append("%s    %s" % (cell, title))
    lines += ["", SEPARATOR, "Contributors & Testers", SEPARATOR]
    return "\n".join(lines)
