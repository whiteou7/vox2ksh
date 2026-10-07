#!/usr/bin/env python3

import argparse
import os
import sys

from ksh_stats import CATEGORIES, convert_and_count, ensure_work, find_pairs

LANES = {
    "BT chip": "ABCD", "BT hold": "ABCD", "FX chip": "LR", "FX hold": "LR",
    "laser runs": "LR", "laser points": "LR",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song", help="substring of the reference folder name")
    ap.add_argument("-d", "--difficulty", default=None,
                    help="only this difficulty, by ksh basename (nov, adv, exh, inf, mxm...)")
    args = ap.parse_args()

    pairs = [p for p in find_pairs() if args.song in p[2].split("/")[0]]
    songs = sorted(set(p[2].split("/")[0] for p in pairs))
    if not songs:
        sys.exit("no matched reference chart for %r (try check_all_charts.py -n 3 to see names)" % args.song)
    if len(songs) > 1:
        more = " ... (+%d more)" % (len(songs) - 12) if len(songs) > 12 else ""
        sys.exit("%r matches %d songs, narrow it: %s%s" % (args.song, len(songs), ", ".join(songs[:12]), more))
    if args.difficulty:
        pairs = [p for p in pairs if p[2].split("/")[1] == args.difficulty + ".ksh"]
        if not pairs:
            sys.exit("%s has no matched %r chart" % (songs[0], args.difficulty))

    work = ensure_work()
    failed = 0
    for vox_path, ksh_path, label in pairs:
        out_path = os.path.join(work, "check_one_%s.ksh" % label.replace("/", "_").replace(".ksh", ""))
        print("=== %s ===" % label)
        print("  vox       : %s" % vox_path)
        print("  reference : %s" % ksh_path)
        try:
            ours, theirs = convert_and_count(vox_path, ksh_path, out_path)
        except Exception as e:
            failed += 1
            print("  FAILED to convert: %r\n" % e)
            continue
        print("  ours      : %s\n" % out_path)
        print("  %-14s %7s %7s %7s   %s" % ("category", "ours", "theirs", "diff", "per lane (ours/theirs)"))
        for name, getter in CATEGORIES:
            o, t = getter(ours), getter(theirs)
            lanes = ""
            if name in LANES:
                lanes = "  ".join("%s %d/%d" % (ln, a, b) for ln, a, b in zip(LANES[name], o, t))
            print("  %-14s %7d %7d %+7d   %s" % (name, sum(o), sum(t), sum(o) - sum(t), lanes))
        print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
