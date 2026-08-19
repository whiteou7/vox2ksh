#!/usr/bin/env python3
"""Survey every .vox chart's camera-relevant data: #SPCONTROLER Tilt/CAM_RotX/CAM_Radi
rows, and the laser tracks' roll/swing column (C3) with its length column. Tabulates
value ranges and combinations so the camera element's parameter layout and value
ranges can be *observed* rather than assumed - same approach as ../shared/voxsurvey.py
used for the audio effect sections.

    python survey.py [--limit N]
    python survey.py --locate 6,7      # pinpoint exact chart/measure occurrences
    python survey.py --lasercols       # the roll-length column, per format version

Every tabulation here is keyed on the format version, because the roll length does
not live in a fixed column: format 13 inserted a new column after the curve type and
pushed the length from C8 to C9 (and cells-per-chain from C9 to C10). Pooling the
versions is what made an earlier pass read the v13 length column as "near-universally
0" - see specs/vox_format.md and --lasercols below.

A base game install carries no format-13 charts at all: they arrive in the update
folders, which are separate partial installs. Pass --root to include one, e.g.

    python survey.py --lasercols --root "<update folder>/data/music"
"""
import argparse
import collections
import glob
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from _paths import MUSIC as ROOT

def length_col(ver):
    """Index of the roll/swing length column for a chart of format `ver`.

    The game's own row parser (`soundvoltex.dll`, the laser branch of the
    #TRACK1/#TRACK8 reader) has three version branches - `< 12`, `== 12`,
    `>= 13` - and the >= 13 one adds one extra conversion after the curve
    type, feeding the same struct field the older branches feed from the
    column before it. The parser has not looked at the roll type at that
    point, so this shift applies to every roll type alike.
    """
    return 9 if ver >= 13 else 8


def cells_col(ver):
    """Index of the cells-per-chain column - one to the right of the length."""
    return length_col(ver) + 1


def format_version(sec):
    try:
        return int(sec.get("#FORMAT VERSION", ["10"])[0].strip())
    except Exception:
        return 10


def sections(path):
    try:
        txt = open(path, "r", encoding="cp932", errors="replace").read()
    except Exception:
        return {}
    out, cur = {}, None
    for line in txt.splitlines():
        ls = line.strip()
        token = ls.split("//", 1)[0].strip()
        if token == "#END":
            cur = None
            continue
        if ls.startswith("#"):
            cur = ls
            out.setdefault(cur, [])
            continue
        if cur is not None and ls:
            out[cur].append(ls)
    return out


def locate(roll_types, files):
    """Print every raw #TRACK1/#TRACK8 row whose roll_type (C3) is in
    `roll_types`, tagged with chart/difficulty/side/timing, so specific
    occurrences can be looked up in-game or in an editor - see
    specs/camera.md's roll_type=6/7 discussion.
    """
    n = 0
    for p in files:
        s = sections(p)
        name = os.path.basename(p)
        ver = format_version(s)
        col = length_col(ver)
        for tag in ("#TRACK1", "#TRACK8"):
            for l in s.get(tag, []):
                f = l.split()
                if len(f) > 3 and f[3] in roll_types:
                    side = "L" if tag == "#TRACK1" else "R"
                    length = f[col] if len(f) > col else "0"
                    print("  roll_type=%s  %-55s v%-3d side=%s  pos=%s  len(C%d)=%s" % (
                        f[3], name, ver, side, f[0], col, length))
                    n += 1
    print("\ntotal: %d row(s)" % n)


def _quant(counter):
    """[min q25 median q75 max] + mean over a Counter's nonzero values."""
    vals = sorted(v for v, n in counter.items() for _ in range(n) if v != 0)
    if not vals:
        return "        (never nonzero)"
    n = len(vals)
    return "n=%-6d [%d, %d, %g, %d, %d] mean=%.1f" % (
        n, vals[0], vals[n // 4], statistics.median(vals), vals[(3 * n) // 4],
        vals[-1], statistics.fmean(vals))


def lasercols(files):
    """Which column holds the roll/swing length, measured rather than assumed.

    Two columns are candidates on every laser row - call them by position, C8
    and C9 - and which one is the length depends on the format version, not on
    the roll type. The discriminator that needs no external data: a length can
    only be meaningful on a row that carries a roll, so the length column is
    the one that is *never* nonzero on a roll_type=0 row, while cells-per-chain
    is a property of the laser segment and appears regardless. That test comes
    out unambiguous in both directions and agrees with the game's own parser.

    Also reported: the tab-token count per row, which is what the parser's
    accepted-conversion-count check keys on, and the format-13-only C8 field,
    whose meaning is still unknown.
    """
    ntok = collections.defaultdict(collections.Counter)
    col_by = collections.defaultdict(collections.Counter)      # (ver, rt, col) -> value -> n
    rows_by = collections.Counter()                            # (ver, rt) -> rows
    both = collections.defaultdict(list)                       # ver -> [(chart, rt, c8, c9)]
    fmtver = collections.Counter()

    for p in files:
        s = sections(p)
        ver = format_version(s)
        fmtver[ver] += 1
        for tag in ("#TRACK1", "#TRACK8"):
            for line in s.get(tag, []):
                f = line.split("\t")
                if len(f) < 4:
                    continue
                ntok[ver][len(f)] += 1
                try:
                    rt = int(f[3])
                except ValueError:
                    continue
                rows_by[(ver, rt)] += 1
                vals = {}
                for c in (8, 9, 10):
                    try:
                        vals[c] = int(f[c]) if len(f) > c else 0
                    except ValueError:
                        vals[c] = 0
                    col_by[(ver, rt, c)][vals[c]] += 1
                if rt and vals[8] and vals[9]:
                    both[ver].append((os.path.basename(p), rt, vals[8], vals[9]))

    print("\ncharts per FORMAT VERSION:", dict(sorted(fmtver.items())))
    if 13 not in fmtver:
        print("  !! no format-13 charts in this corpus - pass --root <update folder>/data/music")

    print("\n==== tab tokens per laser row (token 0 is the timing, and 3 conversions) ====")
    print("     the game keeps a row only if its scan consumed 9, 11 or 12 conversions, i.e. 7, 9")
    print("     or 10 tokens - and every shape the corpus actually contains is one of those three.")
    print("     A format-13 row filling all ten of its data columns would be 11 tokens and 13")
    print("     conversions, which the check rejects; no such row exists.")
    for ver in sorted(ntok):
        print("  v%-3d %s" % (ver, dict(sorted(ntok[ver].items()))))

    print("\n==== the roll/swing-only column: which one is dead on non-roll rows ====")
    for ver in sorted(fmtver):
        rolls = sum(n for (v, rt), n in rows_by.items() if v == ver and rt)
        plain = rows_by.get((ver, 0), 0)
        print("\n  v%d - %d row(s) with a roll, %d without" % (ver, rolls, plain))
        for c in (8, 9, 10):
            nz_roll = sum(n for value, n in _merge(col_by, ver, c, roll=True).items() if value)
            nz_plain = sum(n for value, n in _merge(col_by, ver, c, roll=False).items() if value)
            print("    C%-2d nonzero on %6d/%-7d roll rows, %6d/%-7d non-roll rows   %s" % (
                c, nz_roll, rolls, nz_plain, plain,
                _quant(_merge(col_by, ver, c, roll=True))))

    print("\n==== per (version, roll_type): both candidate columns side by side ====")
    for (ver, rt) in sorted(rows_by):
        if not rt:
            continue
        n = rows_by[(ver, rt)]
        print("  v%-3d rt=%d  rows=%-6d" % (ver, rt, n))
        for c in (8, 9):
            print("        C%d: %s" % (c, _quant(col_by[(ver, rt, c)])))

    print("\n==== rows with a roll and BOTH C8 and C9 nonzero ====")
    for ver in sorted(both):
        rows = both[ver]
        print("  v%d: %d row(s)" % (ver, len(rows)))
        for (fn, rt), k in collections.Counter((r[0], r[1]) for r in rows).most_common(12):
            ex = [(r[2], r[3]) for r in rows if r[0] == fn and r[1] == rt][:3]
            print("     %-52s rt=%d n=%-4d C8/C9 = %s" % (fn, rt, k, ex))


def _merge(col_by, ver, c, roll):
    """Values of column `c` across all roll types (roll=True) or only
    roll_type=0 (roll=False), for one format version."""
    out = collections.Counter()
    for (v, rt, cc), cnt in col_by.items():
        if v == ver and cc == c and (bool(rt) == roll):
            out.update(cnt)
    return out


def collect_files(extra_roots, limit=0):
    """Charts from _paths.MUSIC plus any --root, later roots shadowing earlier
    ones by filename the way a game update folder shadows the base install.
    """
    seen = {}
    for root in [ROOT] + list(extra_roots or []):
        for p in sorted(glob.glob(os.path.join(root, "*", "*.vox"))):
            seen[os.path.basename(p).lower()] = p
    files = [seen[k] for k in sorted(seen)]
    return files[:limit] if limit else files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--locate", default=None,
                     help="comma-separated roll_type values to pinpoint chart/measure occurrences for, e.g. 6,7")
    ap.add_argument("--root", action="append", default=[],
                     help="extra data/music directory to survey alongside the game install's - "
                          "repeatable. Needed for any format-13 coverage: those charts only ship "
                          "in the update folders.")
    ap.add_argument("--lasercols", action="store_true",
                     help="report the roll length / cells-per-chain columns per format version")
    args = ap.parse_args()

    files = collect_files(args.root, args.limit)
    print("vox files:", len(files))

    if args.locate:
        locate(set(args.locate.split(",")), files)
        return

    if args.lasercols:
        lasercols(files)
        return

    fmtver = collections.Counter()

    # #SPCONTROLER: control-type -> stats
    ctrl_count = collections.Counter()             # control type -> row count
    ctrl_files = collections.defaultdict(set)       # control type -> set of files containing it
    cam_len = collections.defaultdict(collections.Counter)     # type -> length(cells) -> count
    cam_val = collections.defaultdict(list)         # type -> [start, end, ...] values (sampled)
    tilt_nodetype = collections.Counter()
    other_c2 = collections.defaultdict(collections.Counter)    # type -> C2 value -> count (should be const "2")
    other_c7 = collections.defaultdict(collections.Counter)    # type -> C7 value -> count (should be const 0, except Tilt's C6 slot differs)

    # laser roll/swing: (version, roll_type) -> count, and roll_length distribution per type
    roll_count = collections.Counter()
    roll_length = collections.defaultdict(collections.Counter)   # (version, roll_type) -> length -> count
    roll_effect_width = collections.Counter()        # sanity: roll_type co-occurrence with width

    n_with_camera = 0
    n_with_tilt = 0
    n_with_rollswing = 0

    for i, p in enumerate(files):
        s = sections(p)
        ver = format_version(s)
        fmtver[ver] += 1

        sp = s.get("#SPCONTROLER", [])
        had_camera = False
        had_tilt = False
        for line in sp:
            f = line.split("\t")
            if len(f) < 2:
                continue
            ctype = f[1]
            ctrl_count[ctype] += 1
            ctrl_files[ctype].add(p)
            if ctype in ("Tilt", "CAM_RotX", "CAM_Radi"):
                had_camera = True
                if ctype == "Tilt":
                    had_tilt = True
                if len(f) >= 6:
                    try:
                        length = int(float(f[3]))
                        start = float(f[4])
                        end = float(f[5])
                    except ValueError:
                        continue
                    cam_len[ctype][length] += 1
                    if len(cam_val[ctype]) < 200000:
                        cam_val[ctype].append(start)
                        cam_val[ctype].append(end)
                    try:
                        c2 = float(f[2])
                        other_c2[ctype][c2] += 1
                    except (IndexError, ValueError):
                        pass
                    if len(f) > 6:
                        try:
                            c6 = float(f[6])
                            if ctype == "Tilt":
                                tilt_nodetype[c6] += 1
                            else:
                                other_c7[ctype][c6] += 1
                        except ValueError:
                            pass
                    if len(f) > 7:
                        try:
                            c7 = float(f[7])
                            other_c7[ctype + ":C7"][c7] += 1
                        except ValueError:
                            pass
        if had_camera:
            n_with_camera += 1
        if had_tilt:
            n_with_tilt += 1

        had_roll = False
        for tag in ("#TRACK1", "#TRACK8"):
            for line in s.get(tag, []):
                f = line.split()
                if len(f) < 4:
                    continue
                try:
                    roll_type = int(f[3])
                except ValueError:
                    continue
                if roll_type == 0:
                    continue
                had_roll = True
                roll_count[(ver, roll_type)] += 1
                col = length_col(ver)
                rlen = int(f[col]) if len(f) > col else 0
                roll_length[(ver, roll_type)][rlen] += 1
                width = int(f[5]) if len(f) > 5 else 1
                roll_effect_width[(roll_type, width)] += 1
        if had_roll:
            n_with_rollswing += 1

    print("\nFORMAT VERSION counts:", dict(fmtver))
    print("\ncharts with any camera (Tilt/CAM_RotX/CAM_Radi):", n_with_camera, "/", len(files))
    print("charts with manual Tilt:", n_with_tilt, "/", len(files))
    print("charts with laser roll/swing:", n_with_rollswing, "/", len(files))

    print("\n==== #SPCONTROLER control-type inventory (all types seen) ====")
    for ctype, cnt in ctrl_count.most_common():
        print("  %-16s rows=%-8d files=%d" % (ctype, cnt, len(ctrl_files[ctype])))

    print("\n==== Tilt / CAM_RotX / CAM_Radi value ranges ====")
    for ctype in ("Tilt", "CAM_RotX", "CAM_Radi"):
        vals = cam_val[ctype]
        if not vals:
            continue
        print("\n %s: n=%d min=%.4f max=%.4f" % (ctype, len(vals), min(vals), max(vals)))
        lens = cam_len[ctype]
        top_lens = lens.most_common(15)
        print("   length(cells) top: " + ", ".join("%d:%d" % kv for kv in top_lens))
        print("   length(cells) max seen: %d, distinct: %d" % (max(lens), len(lens)))
        print("   C2 (should be const 2): %s" % dict(other_c2[ctype]))
        if ctype != "Tilt":
            print("   C7 slot (index 6, should be const 0): %s" % dict(other_c7[ctype]))
        c7b = other_c7.get(ctype + ":C7")
        if c7b:
            print("   C7 slot (index 7, should be const 0): %s" % dict(c7b))

    print("\n Tilt node-type (C6) distribution:", dict(tilt_nodetype))

    print("\n==== laser roll/swing (C3) x format version ====")
    for (ver, rt), cnt in sorted(roll_count.items()):
        print("  v%-3d roll_type=%d  count=%d" % (ver, rt, cnt))

    print("\n==== (version, roll_type) -> length(1/4-notes, or 1/32 for types 6/7) distribution ====")
    print("     read from C8 up to format 12 and from C9 from format 13 - never pool the two,")
    print("     see --lasercols and specs/vox_format.md")
    for (ver, rt) in sorted(roll_length):
        lens = roll_length[(ver, rt)]
        print("  v%-3d roll_type=%d: %s  (n=%d, distinct=%d)" % (
            ver, rt, dict(lens.most_common(10)), sum(lens.values()), len(lens)))

    print("\n==== roll_type x laser width (C5) ====")
    for (rt, w), cnt in sorted(roll_effect_width.items()):
        print("  roll_type=%d width=%d count=%d" % (rt, w, cnt))


if __name__ == "__main__":
    main()
