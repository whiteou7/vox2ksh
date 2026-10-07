#!/usr/bin/env python3
"""Matches each reference .ksh to its .vox and correlates vox camera data with the hand-charted camera lines by tick: zoom and tilt regressions, spin kind and direction tables, and the spin length derivation.
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from game_paths import MUSIC, SCRIPTS
import vox_parser as vox

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")

DIFF_SUFFIX = {
    "nov": "1n", "adv": "2a", "exh": "3e",
    "inf": "4i", "grv": "4i", "hvn": "4i", "vvd": "4i", "xcd": "4i",
    "mxm": "5m",
}

LINE_RE = re.compile(r"^([012]{4})\|([012]{2})\|([^|@S]{2})([@S][()<>]\d+(?:;\d+){0,3})?$")


def match_songs():
    music = {}
    for d in sorted(os.listdir(MUSIC)):
        m = re.match(r"^(\d+)_(.*)$", d)
        if m:
            music.setdefault(m.group(2).replace("_", ""), d)
    out = {}
    for r in sorted(os.listdir(REF)):
        if not os.path.isdir(os.path.join(REF, r)):
            continue
        key = r.replace("_", "")
        cand = [v for k, v in music.items() if k.startswith(key) or key.startswith(k)]
        if cand:
            out[r] = cand[0]
    return out


def find_pairs():
    pairs = []
    for ref_name, folder in sorted(match_songs().items()):
        rd = os.path.join(REF, ref_name)
        for fn in sorted(os.listdir(rd)):
            base, ext = os.path.splitext(fn)
            if ext.lower() != ".ksh":
                continue
            suffix = DIFF_SUFFIX.get(base.lower())
            if suffix is None:
                continue
            vox_path = os.path.join(MUSIC, folder, "%s_%s.vox" % (folder, suffix))
            if os.path.exists(vox_path):
                pairs.append((vox_path, os.path.join(rd, fn), "%s/%s" % (ref_name, fn)))
    return pairs


class KshEvents:
    def __init__(self):
        self.opt = {"tilt": [], "zoom_top": [], "zoom_bottom": []}
        self.spin = []


def parse_ksh_events(path, tl):
    raw = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    lines = raw.splitlines()

    body_start = None
    for i, l in enumerate(lines):
        if l.strip() == "--":
            body_start = i + 1
            break
    if body_start is None:
        return KshEvents()

    measures = [[]]
    for l in lines[body_start:]:
        ls = l.strip()
        if not ls or ls.startswith("//") or ls.startswith("#"):
            continue
        if ls == "--":
            measures.append([])
            continue
        measures[-1].append(ls)
    if measures and not measures[-1]:
        measures.pop()

    ev = KshEvents()
    pending_opts = []

    for m, block in enumerate(measures):
        chart_idx = [i for i, l in enumerate(block) if LINE_RE.match(l)]
        R = len(chart_idx)
        mlen = tl.measure_length(m)
        m_start = tl.measure_start_tick(m)

        def tick_for(k):
            if R == 0:
                return m_start
            k = min(k, R - 1)
            step = mlen / R
            return m_start + k * step

        seen_chart_lines = 0
        for l in block:
            cm = LINE_RE.match(l)
            if cm is None:
                for kind in ("tilt", "zoom_top", "zoom_bottom"):
                    if l.startswith(kind + "="):
                        pending_opts.append((kind, l[len(kind) + 1:]))
                continue
            t = tick_for(seen_chart_lines)
            for (kind, val) in pending_opts:
                ev.opt[kind].append((t, val))
            pending_opts = []
            laser2, spin = cm.group(3), cm.group(4)
            if spin:
                ev.spin.append((t, laser2[0], laser2[1], spin))
            seen_chart_lines += 1

    if pending_opts:
        t = tl.measure_start_tick(len(measures))
        for (kind, val) in pending_opts:
            ev.opt[kind].append((t, val))

    return ev


def parse_tilt_value(raw):
    presets = {"normal": 0.0, "zero": 0.0, "bigger": None, "biggest": None,
               "keep_normal": None, "keep_bigger": None, "keep_biggest": None,
               "big": None, "keep": None}
    if raw in presets:
        return presets[raw]
    try:
        return float(raw)
    except ValueError:
        return None


TICK_TOL = 3


def nearest(pairs_sorted, tick):
    if not pairs_sorted:
        return None
    import bisect
    ticks = [p[0] for p in pairs_sorted]
    i = bisect.bisect_left(ticks, tick)
    best = None
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(pairs_sorted):
            d = abs(pairs_sorted[j][0] - tick)
            if best is None or d < best[1]:
                best = (pairs_sorted[j][1], d)
    return best


def collect_camera_pairs(chart, ev, vox_key, ksh_key, out_pairs, out_samples, dump):
    segs = chart.camera[vox_key]
    ksh_opts = sorted(ev.opt[ksh_key], key=lambda x: x[0])
    ksh_vals = [(t, parse_tilt_value(v) if ksh_key == "tilt" else _num(v)) for (t, v) in ksh_opts]
    ksh_vals = [(t, v) for (t, v) in ksh_vals if v is not None]
    for seg in segs:
        for tick, voxval in ((seg.tick, seg.start), (seg.end_tick, seg.end)):
            hit = nearest(ksh_vals, tick)
            if hit is None:
                continue
            kval, dtick = hit
            if dtick <= TICK_TOL:
                out_pairs.append((voxval, kval))
                if len(out_samples) < dump:
                    out_samples.append((tick, voxval, kval, dtick))


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None


def outgoing_dirsign(lst, i, max_lookahead=5):
    base = lst[i].pos
    for j in range(i + 1, min(i + 1 + max_lookahead, len(lst))):
        if lst[j].pos != base:
            return (lst[j].pos > base) - (lst[j].pos < base)
    return None


def collect_spin_pairs(chart, ev, out_rows, label=None):
    for (tick, lchar, rchar, token) in ev.spin:
        best = None
        for side, lst in (("L", chart.laser[0]), ("R", chart.laser[1])):
            for i, p in enumerate(lst):
                if abs(p.tick - tick) <= TICK_TOL and p.roll_type != 0:
                    d = abs(p.tick - tick)
                    if best is None or d < best[4]:
                        dirsign = outgoing_dirsign(lst, i)
                        best = (side, p.roll_type, p.roll_length, dirsign, d)
        if best:
            side, roll_type, roll_length, dirsign, d = best
            ksh_len = int(re.search(r"(\d+)", token).group(1))
            out_rows.append((roll_type, roll_length, side, dirsign, token,
                             (label, chart.version, ksh_len)))


def laser_pos_at(lst, tick):
    if not lst:
        return None
    import bisect
    ticks = [p.tick for p in lst]
    i = bisect.bisect_right(ticks, tick) - 1
    if i < 0 or i >= len(lst) - 1:
        if i == len(lst) - 1 and lst[i].tick == tick:
            return lst[i].pos
        return None
    a, b = lst[i], lst[i + 1]
    if a.tick == b.tick:
        return a.pos
    if not (a.tick <= tick <= b.tick):
        return None
    frac = (tick - a.tick) / (b.tick - a.tick)
    return a.pos + frac * (b.pos - a.pos)


def collect_tilt_vs_laser(chart, ev, out_rows):
    manual_ranges = [(s.tick, s.end_tick) for s in chart.camera["tilt"]]

    def in_manual(t):
        return any(a - TICK_TOL <= t <= b + TICK_TOL for (a, b) in manual_ranges)

    for (t, raw) in ev.opt["tilt"]:
        if in_manual(t):
            continue
        val = parse_tilt_value(raw)
        if val is None:
            continue
        posL = laser_pos_at(chart.laser[0], t)
        posR = laser_pos_at(chart.laser[1], t)
        out_rows.append((t, posL, posR, val))


def ksh_ver(path):
    for l in open(path, "r", encoding="utf-8-sig", errors="replace"):
        l = l.strip()
        if l == "--":
            break
        if l.startswith("ver="):
            try:
                return int(l[4:])
            except ValueError:
                return None
    return None


def linreg(pairs):
    n = len(pairs)
    if n < 2:
        return None
    sx = sum(a for a, b in pairs)
    sy = sum(b for a, b in pairs)
    sxx = sum(a * a for a, b in pairs)
    sxy = sum(a * b for a, b in pairs)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    mean_y = sy / n
    ss_tot = sum((b - mean_y) ** 2 for a, b in pairs)
    ss_res = sum((b - (slope * a + intercept)) ** 2 for a, b in pairs)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return slope, intercept, r2


def main():
    import collections

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--dump", type=int, default=15, help="sample rows to print per category")
    ap.add_argument("--per-song", action="store_true", help="print zoom regression per song too")
    args = ap.parse_args()

    pairs = find_pairs()
    if args.only:
        pairs = [p for p in pairs if args.only in p[2]]
    print("matched %d chart(s)" % len(pairs))

    tilt_pairs, rotx_pairs, radi_pairs = [], [], []
    tilt_samples, rotx_samples, radi_samples = [], [], []
    spin_rows = []
    tilt_laser_rows = []
    per_song_zoom = []
    failures = []

    for (vox_path, ksh_path, label) in pairs:
        try:
            chart = vox.load(vox_path)
            ev = parse_ksh_events(ksh_path, chart.tl)
        except Exception as e:
            failures.append((label, repr(e)))
            continue
        song_rotx, song_radi = [], []
        collect_camera_pairs(chart, ev, "tilt", "tilt", tilt_pairs, tilt_samples, args.dump)
        collect_camera_pairs(chart, ev, "cam_rotx", "zoom_top", song_rotx, rotx_samples, args.dump)
        collect_camera_pairs(chart, ev, "cam_radi", "zoom_bottom", song_radi, radi_samples, args.dump)
        rotx_pairs.extend(song_rotx)
        radi_pairs.extend(song_radi)
        collect_spin_pairs(chart, ev, spin_rows, label)
        collect_tilt_vs_laser(chart, ev, tilt_laser_rows)
        per_song_zoom.append((label, ksh_ver(ksh_path), song_rotx, song_radi))

    print("\nfailed: %d" % len(failures))
    for label, err in failures[:10]:
        print("  %s: %s" % (label, err))

    for name, pairs_, samples in (
        ("tilt -> tilt (manual vox Tilt track only)", tilt_pairs, tilt_samples),
        ("cam_rotx -> zoom_top (pooled, all vers)", rotx_pairs, rotx_samples),
        ("cam_radi -> zoom_bottom (pooled, all vers)", radi_pairs, radi_samples),
    ):
        print("\n==== %s ====  n=%d" % (name, len(pairs_)))
        if pairs_:
            lr = linreg(pairs_)
            if lr:
                slope, intercept, r2 = lr
                print("  linreg: ksh = %.4f * vox + %.4f   (R^2=%.4f)" % (slope, intercept, r2))
            print("  sample (tick, vox_val, ksh_val, dtick):")
            for row in samples:
                print("   ", row)

    print("\n==== per-song zoom regression (ver, n_rotx, rotx slope/intercept/R2, n_radi, radi slope/intercept/R2) ====")
    for (label, ver, sr, sd) in per_song_zoom:
        lr1 = linreg(sr)
        lr2 = linreg(sd)
        s1 = "slope=%.2f b=%.2f R2=%.3f" % lr1 if lr1 else "n/a"
        s2 = "slope=%.2f b=%.2f R2=%.3f" % lr2 if lr2 else "n/a"
        print("  ver=%-4s n=%-4d/%-4d  rotx[%s]  radi[%s]  %s" % (
            ver, len(sr), len(sd), s1, s2, label))

    print("\n==== tilt (auto, non-manual) vs laser position ====  n=%d" % len(tilt_laser_rows))
    both = [(pl, pr, v) for (t, pl, pr, v) in tilt_laser_rows if pl is not None and pr is not None]
    only_l = [(pl, v) for (t, pl, pr, v) in tilt_laser_rows if pl is not None and pr is None]
    only_r = [(pr, v) for (t, pl, pr, v) in tilt_laser_rows if pr is not None and pl is None]
    neither = sum(1 for (t, pl, pr, v) in tilt_laser_rows if pl is None and pr is None)
    print("  both lasers active: %d   only-L: %d   only-R: %d   neither: %d" % (
        len(both), len(only_l), len(only_r), neither))
    if neither:
        vals = [v for (t, pl, pr, v) in tilt_laser_rows if pl is None and pr is None]
        print("  tilt value when neither laser active (should cluster at 0): %s" %
              collections.Counter(vals).most_common(10))
    if only_l:
        lr = linreg(only_l)
        print("  only-L: tilt vs posL linreg: %s" % (lr,))
        print("  sample:", only_l[:10])
    if only_r:
        lr = linreg(only_r)
        print("  only-R: tilt vs posR linreg: %s" % (lr,))
        print("  sample:", only_r[:10])
    if both:
        diff_pairs = [(pr - pl, v) for (pl, pr, v) in both]
        lr = linreg(diff_pairs)
        print("  both: tilt vs (posR - posL) linreg: %s" % (lr,))
        print("  sample (posL,posR,tilt):", both[:10])

    ROLL_KIND = {1: "roll", 2: "roll", 3: "roll", 4: "roll", 5: "swing", 6: "roll", 7: "roll"}
    FULL_CHARS = {"@(", "@)"}
    HALF_CHARS = {"@<", "@>"}

    print("\n==== spin: roll_type kind (roll/swing) vs ksh symbol kind (full/half) ====")
    kind_tab = collections.Counter()
    for (rt, rl, side, ds, tok, _x) in spin_rows:
        base = re.match(r"[@S][()<>]", tok).group(0)
        symkind = "full" if base in FULL_CHARS else ("half" if base in HALF_CHARS else "other:" + base)
        kind_tab[(ROLL_KIND.get(rt, "?%d" % rt), symkind)] += 1
    for k, c in sorted(kind_tab.items(), key=lambda kv: -kv[1]):
        print("  vox=%-5s -> ksh=%-6s  count=%d" % (k[0], k[1], c))

    print("\n==== spin direction: outgoing-slam dirsign vs ksh symbol ====  (user hypothesis: "
          "right-to-left slam [dirsign=-1] = clockwise = @( or @<;  left-to-right [dirsign=+1] "
          "= counterclockwise = @) or @>)")
    dir_tab = collections.Counter()
    for (rt, rl, side, ds, tok, _x) in spin_rows:
        if ds is None:
            continue
        base = re.match(r"[@S][()<>]", tok).group(0)
        dir_tab[(ds, base)] += 1
    for k, c in sorted(dir_tab.items(), key=lambda kv: -kv[1]):
        print("  dirsign=%-2d -> %-2s   count=%d" % (k[0], k[1], c))
    hits = misses = 0
    for (ds, base), c in dir_tab.items():
        predicted_cw = base in ("@(", "@<")
        actual_cw = ds < 0
        if predicted_cw == actual_cw:
            hits += c
        else:
            misses += c
    if hits + misses:
        print("  hypothesis match rate: %d/%d = %.1f%%" % (hits, hits + misses, 100.0 * hits / (hits + misses)))

    print("\n  spin token length(192nds) distribution by roll_type:")
    lens_by_type = collections.defaultdict(collections.Counter)
    for (rt, rl, side, ds, tok, _x) in spin_rows:
        mlen = re.search(r"(\d+)", tok)
        if mlen:
            lens_by_type[rt][int(mlen.group(1))] += 1
    for rt in sorted(lens_by_type):
        print("   roll_type=%d: %s" % (rt, dict(lens_by_type[rt].most_common(10))))

    print("\n  spin token length(192nds) distribution by kind (roll vs swing):")
    lens_by_kind = collections.defaultdict(collections.Counter)
    for (rt, rl, side, ds, tok, _x) in spin_rows:
        mlen = re.search(r"(\d+)", tok)
        if mlen:
            lens_by_kind[ROLL_KIND.get(rt, "?")][int(mlen.group(1))] += 1
    for k in sorted(lens_by_kind):
        print("   %s: %s" % (k, dict(lens_by_kind[k].most_common(15))))

    spin_length_report(spin_rows)


def spin_length_report(spin_rows):
    import collections
    import statistics

    def vox_quarter_notes(rt, length):
        if rt in (6, 7):
            return (length or 0) / 8.0
        return float(length) if length else float(camera_defaults.get(rt, 3))

    camera_defaults = {1: 6, 2: 2, 3: 3, 4: 12, 5: 3}

    rows = []
    for (rt, length, side, ds, tok, extra) in spin_rows:
        label, ver, ksh_len = extra
        rows.append((label, rt, length, ver, ksh_len,
                     vox_quarter_notes(rt, length)))
    if not rows:
        print("\n==== spin length ====  no samples")
        return

    print("\n==== spin length: ksh_len / vox quarter note, per song (the charter's scale) ====")
    bysong = collections.defaultdict(list)
    for (label, rt, length, ver, ksh_len, qn) in rows:
        if length and qn:
            bysong[label].append(ksh_len / qn)
    scale = {}
    for label, v in bysong.items():
        scale[label] = collections.Counter(round(x, 3) for x in v).most_common(1)[0][0]
    print("   modal scale per song: %s" % dict(collections.Counter(scale.values()).most_common(8)))
    print("   -> %d/%d songs sit at exactly 24" % (
        sum(1 for s in scale.values() if s == 24.0), len(scale)))

    print("\n   exact-match rate of `ksh_len = SCALE * vox quarter notes`:")
    for s in (24, 32):
        hit = sum(1 for r in rows if abs(r[4] - s * r[5]) < 1e-6)
        print("     SCALE=%-3d %d/%d = %.1f%%" % (s, hit, len(rows), 100.0 * hit / len(rows)))
    print("   ratio of observed to predicted at SCALE=24 (residual is charter style):")
    rat = collections.Counter(round(r[4] / (24.0 * r[5]), 3) for r in rows if r[5])
    for v, c in rat.most_common(6):
        print("     x%-6s n=%-4d (%4.1f%%)  = scale %g" % (v, c, 100.0 * c / len(rows), 24 * v))

    print("\n   per roll_type, split by explicit C8 vs C8=0 default:")
    for rt in sorted(set(r[1] for r in rows)):
        for tag, sel in (("explicit", [r for r in rows if r[1] == rt and r[2]]),
                         ("default ", [r for r in rows if r[1] == rt and not r[2]])):
            if not sel:
                continue
            hit = sum(1 for r in sel if abs(r[4] - 24 * r[5]) < 1e-6)
            print("     rt=%d %s n=%-4d exact@24=%-4d (%5.1f%%)  median ratio=%.3f" % (
                rt, tag, len(sel), hit, 100.0 * hit / len(sel),
                statistics.median([r[4] / (24.0 * r[5]) for r in sel])))

    print("\n==== C8=0 defaults, in songs whose explicit-C8 scale is exactly 24 ====")
    print("   (the implied vox default duration, in quarter notes - compare vox_format.md's names)")
    n24 = {k for k, v in scale.items() if v == 24.0}
    for rt in sorted(set(r[1] for r in rows)):
        sel = [r for r in rows if r[1] == rt and not r[2] and r[0] in n24]
        if not sel:
            continue
        imp = collections.Counter(r[4] / 24.0 for r in sel)
        print("   rt=%-2d name=%-3s n=%-4d median=%.2f  observed: %s" % (
            rt, camera_defaults.get(rt, "?"), len(sel),
            statistics.median([r[4] / 24.0 for r in sel]), dict(imp.most_common(5))))

    print("\n==== scale-free cross-check: ratio between two types' defaults in the SAME song ====")
    print("   (needs no charter scale at all - it cancels; names predict 6:2:3:3 for rt 1:2:3:5)")
    d = collections.defaultdict(list)
    for (label, rt, length, ver, ksh_len, qn) in rows:
        if not length:
            d[(label, rt)].append(ksh_len)
    med = {k: statistics.median(v) for k, v in d.items()}
    songs = {k[0] for k in med}
    for (a, b) in ((3, 5), (1, 5), (1, 3), (2, 5)):
        pr = [(med[(s, a)], med[(s, b)]) for s in songs if (s, a) in med and (s, b) in med]
        if not pr:
            continue
        exp = camera_defaults[a] / float(camera_defaults[b])
        print("   rt%d/rt%d  names predict %.3f   n_songs=%-3d median=%.3f   %s" % (
            a, b, exp, len(pr), statistics.median([x / y for x, y in pr]),
            dict(collections.Counter(round(x / y, 3) for x, y in pr).most_common(4))))


if __name__ == "__main__":
    main()
