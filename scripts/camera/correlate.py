#!/usr/bin/env python3
"""
Correlate every matched (vox, hand-charted ksh) reference pair to derive the
camera value mappings empirically, per the project's rule for this element:
settle vox -> ksh camera value mapping from the manual reference conversions
in scripts/shared/reference/ksh BEFORE reverse-engineering the DLL.

    python correlate.py [--only substring] [--dump N]

For each pair this reads the ksh body once to get every `tilt=`/`zoom_top=`/
`zoom_bottom=` option line and every chart-line lane-spin token, each tagged
with its absolute tick (computed the same way scripts/notes/convert.py builds
grid lines: per-measure line count -> tick step, using the *vox* chart's
Timeline since bar-for-bar alignment between a hand chart and its vox source
is already established - see specs/notes.md). It then matches those against
the vox #SPCONTROLER Tilt/CAM_RotX/CAM_Radi segments and laser roll/swing
columns at the same tick and reports the observed vox-value -> ksh-value
relationship (regression + raw pairs for inspection).
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
from _paths import MUSIC, SCRIPTS
import vox

REF = os.path.join(SCRIPTS, "shared", "reference", "ksh")

DIFF_SUFFIX = {
    "nov": "1n", "adv": "2a", "exh": "3e",
    "inf": "4i", "grv": "4i", "hvn": "4i", "vvd": "4i", "xcd": "4i",
    "mxm": "5m",
}

# laser chars: anything but the pipe; spin suffix per ksh_format.md
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


# --------------------------------------------------------------------------
# ksh body -> tick-tagged options + spin tokens
# --------------------------------------------------------------------------

class KshEvents:
    def __init__(self):
        self.opt = {"tilt": [], "zoom_top": [], "zoom_bottom": []}   # (tick, raw_str)
        self.spin = []    # (tick, laser_l_char, laser_r_char, spin_token)


def parse_ksh_events(path, tl):
    """tl: the *vox* chart's vox.Timeline, used for measure_start_tick/length -
    see module docstring for why this is valid."""
    raw = open(path, "r", encoding="utf-8-sig", errors="replace").read()
    lines = raw.splitlines()

    # split body (after the first '--') into measure blocks of non-comment lines
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
    pending_opts = []   # [(kind, raw_str), ...] waiting for the next chart-line's tick

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
        # opts with nothing left in this measure fall through to next measure's start

    # flush any trailing pending opts (rare: option lines after the last chart line)
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


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

TICK_TOL = 3   # cells; allow rounding slop from per-measure step division


def nearest(pairs_sorted, tick):
    """pairs_sorted: [(tick, val), ...] sorted by tick. -> (val, dtick) of nearest, or None."""
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
    """Sign of the movement *out of* point i, toward whatever comes next -
    per raw-data inspection (see specs/camera.md), the roll/swing tag sits
    on the point immediately BEFORE a same-tick slam, not after one, so the
    direction that matters is the outgoing jump, not the incoming one.
    Looks a few points ahead for the first differing position (handles the
    common case of an exact same-tick slam, and smooth-curve cases where
    the very next sampled point hasn't moved yet).
    """
    base = lst[i].pos
    for j in range(i + 1, min(i + 1 + max_lookahead, len(lst))):
        if lst[j].pos != base:
            return (lst[j].pos > base) - (lst[j].pos < base)
    return None


def collect_spin_pairs(chart, ev, out_rows):
    """out_rows: (roll_type, roll_length, side, dirsign, token). dirsign is
    the sign of the slam/movement immediately following the roll-tagged
    point (see outgoing_dirsign) - a candidate discriminator for
    @( vs @) / @< vs @> since vox's roll_type alone doesn't encode direction.
    """
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
            out_rows.append((roll_type, roll_length, side, dirsign, token))


def laser_pos_at(lst, tick):
    """Interpolated laser position at `tick` from a sorted vox.LaserPoint list,
    or None if `tick` falls outside every point's range. Vox pre-samples
    curves densely (up to 1/64 measure) so nearest-neighbour among the
    surrounding two points is an adequate approximation of the true curve.
    """
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
    """out_rows: (tick, posL_or_None, posR_or_None, tilt_val). Manual vox
    Tilt segments are excluded via a tick-range check, isolating the *auto*
    tilt lines this project hasn't explained yet (see module docstring on
    correlate.py's tilt->tilt result: only 758/8103 charts carry a manual
    Tilt track at all, yet every reference chart has thousands of tilt=
    lines - most of it must be SDVX's own laser-driven auto-tilt, not a
    replay of vox's Tilt track).
    """
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
    # R^2
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
    per_song_zoom = []   # (label, ver, rotx_pairs, radi_pairs)
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
        collect_spin_pairs(chart, ev, spin_rows)
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

    # user-supplied mapping: vox "roll" (1,2,3,4,6,7) -> ksh full spin @(/@);
    # vox "swing" (5) -> ksh half spin @</@>. S</S> intentionally omitted -
    # confirmed unused in the reference set.
    ROLL_KIND = {1: "roll", 2: "roll", 3: "roll", 4: "roll", 5: "swing", 6: "roll", 7: "roll"}
    FULL_CHARS = {"@(", "@)"}
    HALF_CHARS = {"@<", "@>"}

    print("\n==== spin: roll_type kind (roll/swing) vs ksh symbol kind (full/half) ====")
    kind_tab = collections.Counter()
    for (rt, rl, side, ds, tok) in spin_rows:
        base = re.match(r"[@S][()<>]", tok).group(0)
        symkind = "full" if base in FULL_CHARS else ("half" if base in HALF_CHARS else "other:" + base)
        kind_tab[(ROLL_KIND.get(rt, "?%d" % rt), symkind)] += 1
    for k, c in sorted(kind_tab.items(), key=lambda kv: -kv[1]):
        print("  vox=%-5s -> ksh=%-6s  count=%d" % (k[0], k[1], c))

    print("\n==== spin direction: outgoing-slam dirsign vs ksh symbol ====  (user hypothesis: "
          "right-to-left slam [dirsign=-1] = clockwise = @( or @<;  left-to-right [dirsign=+1] "
          "= counterclockwise = @) or @>)")
    dir_tab = collections.Counter()
    for (rt, rl, side, ds, tok) in spin_rows:
        if ds is None:
            continue
        base = re.match(r"[@S][()<>]", tok).group(0)
        dir_tab[(ds, base)] += 1
    for k, c in sorted(dir_tab.items(), key=lambda kv: -kv[1]):
        print("  dirsign=%-2d -> %-2s   count=%d" % (k[0], k[1], c))
    # hit rate against the hypothesis
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
    for (rt, rl, side, ds, tok) in spin_rows:
        mlen = re.search(r"(\d+)", tok)
        if mlen:
            lens_by_type[rt][int(mlen.group(1))] += 1
    for rt in sorted(lens_by_type):
        print("   roll_type=%d: %s" % (rt, dict(lens_by_type[rt].most_common(10))))

    print("\n  spin token length(192nds) distribution by kind (roll vs swing):")
    lens_by_kind = collections.defaultdict(collections.Counter)
    for (rt, rl, side, ds, tok) in spin_rows:
        mlen = re.search(r"(\d+)", tok)
        if mlen:
            lens_by_kind[ROLL_KIND.get(rt, "?")][int(mlen.group(1))] += 1
    for k in sorted(lens_by_kind):
        print("   %s: %s" % (k, dict(lens_by_kind[k].most_common(15))))


if __name__ == "__main__":
    main()
