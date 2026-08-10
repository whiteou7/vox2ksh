#!/usr/bin/env python3
"""Survey every .vox chart's camera-relevant data: #SPCONTROLER Tilt/CAM_RotX/CAM_Radi
rows, and the laser tracks' roll/swing column (C3, plus C8 length in v12). Tabulates
value ranges and combinations so the camera element's parameter layout and value
ranges can be *observed* rather than assumed - same approach as ../shared/voxsurvey.py
used for the audio effect sections.

    python survey.py [--limit N]
    python survey.py --locate 6,7      # pinpoint exact chart/measure occurrences
"""
import argparse
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from _paths import MUSIC as ROOT


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
        for tag in ("#TRACK1", "#TRACK8"):
            for l in s.get(tag, []):
                f = l.split()
                if len(f) > 3 and f[3] in roll_types:
                    side = "L" if tag == "#TRACK1" else "R"
                    length = f[8] if len(f) > 8 else "0"
                    print("  roll_type=%s  %-55s side=%s  pos=%s  len(C8)=%s" % (
                        f[3], name, side, f[0], length))
                    n += 1
    print("\ntotal: %d row(s)" % n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--locate", default=None,
                     help="comma-separated roll_type values to pinpoint chart/measure occurrences for, e.g. 6,7")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(ROOT, "*", "*.vox")))
    if args.limit:
        files = files[: args.limit]
    print("vox files:", len(files))

    if args.locate:
        locate(set(args.locate.split(",")), files)
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
    roll_length = collections.defaultdict(collections.Counter)   # roll_type -> C8 length -> count
    roll_effect_width = collections.Counter()        # sanity: roll_type co-occurrence with width

    n_with_camera = 0
    n_with_tilt = 0
    n_with_rollswing = 0

    for i, p in enumerate(files):
        s = sections(p)
        ver_lines = s.get("#FORMAT VERSION", ["10"])
        try:
            ver = int(ver_lines[0].strip())
        except Exception:
            ver = 10
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
                rlen = int(f[8]) if len(f) > 8 else 0
                roll_length[roll_type][rlen] += 1
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

    print("\n==== roll_type -> C8 length(1/4-notes, or 1/32 for type 6) distribution ====")
    for rt in sorted(roll_length):
        lens = roll_length[rt]
        print("  roll_type=%d: %s  (n=%d, distinct=%d)" % (
            rt, dict(lens.most_common(10)), sum(lens.values()), len(lens)))

    print("\n==== roll_type x laser width (C5) ====")
    for (rt, w), cnt in sorted(roll_effect_width.items()):
        print("  roll_type=%d width=%d count=%d" % (rt, w, cnt))


if __name__ == "__main__":
    main()
