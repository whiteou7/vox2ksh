#!/usr/bin/env python3
"""Cross-check a render against a gameplay recording, broken down by effect.

    python xcheck.py <song folder> <reference audio> [-d 5m]

Unlike metric.py - which is wired to the one kamui capture - this takes any
song and any recording, aligns them itself, and reports the closeness metric
per effect type. That per-effect breakdown is the point: a single global score
says the render is off, but not which DSP is wrong.

What it does:
  1. decodes the song's own .s3v (the dry track) and the reference recording
  2. estimates the recording's offset and clock drift against the dry track,
     by cross-correlating several windows and fitting a line
  3. renders the chart with apply_chart.py
  4. scores dry-vs-reference and render-vs-reference in 46 log-spaced bands
     per 46 ms frame, level-normalised (see metric.py)
  5. splits the frames by which effect is active and reports each

Reading the output: `dry` is the do-nothing baseline and `render` should beat
it. Per effect, `dry` minus `render` is how much the reimplementation of that
effect actually buys - a value near zero means that effect is contributing
nothing, and a negative one means it is making the region worse.
"""
import argparse
import os
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, os.pardir, "shared"))

from _paths import WORK, ensure_work, find_ffmpeg
from metric import bands, spectrogram, N, HOP, SR
from apply_chart import read_sections, Timeline, parse_fx_pairs, FX_NAMES


def decode(path, mono=True):
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found")
    r = subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-i", path,
                        "-f", "s16le", "-ar", str(SR), "-ac", "1" if mono else "2",
                        "pipe:1"], stdout=subprocess.PIPE, check=True)
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float64)


def _delay(a, b):
    """How far `b` lags behind `a`, in samples.

    cc[k] = sum a[n]*b[n-k] peaks at k = -delay, so the delay is the negation
    of the argmax. Getting this sign backwards silently indexes the reference
    on the wrong side of the origin and every score comes out as noise, so it
    is asserted against a known case in the self-test at the bottom.
    """
    n = 1 << (max(len(a), len(b)) - 1).bit_length()
    A = np.fft.rfft(a - a.mean(), 2 * n)
    B = np.fft.rfft(b - b.mean(), 2 * n)
    cc = np.abs(np.fft.irfft(A * np.conj(B), 2 * n))
    k = int(np.argmax(cc))
    if k > n:
        k -= 2 * n
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-9
    return -k, float(cc.max() / denom)


def align(ref, dry, windows=9, win_sec=10.0):
    """Estimate `ref`'s delay and clock drift relative to `dry`.

    Returns (delay0, slope, corr, nwindows) such that the reference sample
    matching dry position p is at  p + delay0 + slope*(p/SR).

    A single lag is not enough: the kamui capture drifts 7.9 ppm, and anything
    recorded off a screen or re-encoded can do the same. Correlating several
    windows and fitting a line recovers both terms. Windows whose correlation
    peak is weak are dropped rather than allowed to drag the fit.
    """
    span = min(len(ref), len(dry))
    w = int(win_sec * SR)
    coarse, c0 = _delay(dry[:min(span, 1 << 22)], ref[:min(span, 1 << 22)])
    pts = []
    for i in range(windows):
        s = int((i + 0.5) * (span - w) / windows)
        t = s + coarse
        if t < 0 or t + w > len(ref) or s + w > len(dry):
            continue
        d, c = _delay(dry[s:s + w], ref[t:t + w])
        if c > 0.05:
            pts.append((s / float(SR), coarse + d, c))
    if len(pts) < 3:
        return float(coarse), 0.0, c0, len(pts)
    t = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    keep = np.abs(y - np.median(y)) < 4 * SR          # reject wild windows
    if keep.sum() >= 3:
        t, y = t[keep], y[keep]
    slope, off = np.polyfit(t, y, 1)
    return float(off), float(slope), c0, len(pts)


def _selftest():
    """Guard the sign convention: a known delay must come back positive."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal(1 << 17)
    pad = 5000
    delayed = np.concatenate([np.zeros(pad), x])       # `delayed` lags x by pad
    d, c = _delay(x, delayed)
    assert abs(d - pad) <= 1, "delay sign/scale wrong: got %d, want %d" % (d, pad)
    return d, c


def frame_masks(sec, tl, nframes, n):
    """One boolean mask per effect name, plus 'laser' and 'idle'."""
    pairs = parse_fx_pairs(sec)
    masks = {}

    def mark(name, a, b):
        m = masks.setdefault(name, np.zeros(nframes, bool))
        m[max(0, a // HOP):min(nframes, b // HOP + 1)] = True

    for trk in ("#TRACK2", "#TRACK7"):
        for line in sec.get(trk, []):
            f = line.split()
            if len(f) < 3:
                continue
            try:
                ln, ev = int(f[1]), int(f[2])
            except ValueError:
                continue
            if ln <= 0 or ev < 2 or ev - 2 >= len(pairs):
                continue
            t0 = tl.tick_of(f[0])
            a, b = tl.samples(t0), tl.samples(t0 + ln)
            for eff in pairs[ev - 2]:
                if eff is not None:
                    mark(FX_NAMES.get(int(eff[0]), "?"), a, b)

    # Only span consecutive points that belong to the SAME laser. C2 is the node
    # type (0 mid / 1 start / 2 end); bridging across an "end" would paint every
    # gap between lasers as laser-active and make the row meaningless.
    laser = np.zeros(nframes, bool)
    for trk in ("#TRACK1", "#TRACK8"):
        pts = []
        for line in sec.get(trk, []):
            f = line.split()
            if len(f) >= 3:
                try:
                    pts.append((tl.samples(tl.tick_of(f[0])), int(f[2])))
                except ValueError:
                    continue
        pts.sort()
        for i in range(len(pts) - 1):
            if pts[i][1] == 2:                 # this point ends a laser
                continue
            a, b = pts[i][0], pts[i + 1][0]
            if b > a:
                laser[max(0, a // HOP):min(nframes, b // HOP + 1)] = True
    masks["laser"] = laser

    busy = np.zeros(nframes, bool)
    for m in masks.values():
        busy |= m
    masks["idle"] = ~busy
    return masks


def score_frames(a_log, b_log, act):
    """mean |dB| difference over `act`, after matching one global level."""
    if act.sum() < 8:
        return float("nan"), 0
    a, b = a_log[act], b_log[act]
    off = np.median(a - b)
    return float((20.0 * np.abs((a - b) - off)).mean()), int(act.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("reference")
    ap.add_argument("-d", "--difficulty", default=None)
    ap.add_argument("-b", "--block", type=int, default=512)
    ap.add_argument("--render", default=None,
                    help="reuse an existing render instead of making one")
    ap.add_argument("--work-tag", default=None,
                    help="disambiguate the render filename (default: the difficulty). "
                         "Needed when multiple xcheck.py runs for the same song folder "
                         "(different difficulties) may be in flight at once, e.g. from "
                         "masscheck.py -j - otherwise they'd race on the same temp WAV.")
    ap.add_argument("--extra", default="",
                    help="extra flags passed through to apply_chart.py")
    ap.add_argument("--quiet", action="store_true",
                    help="silence apply_chart's own output (the report still prints)")
    ap.add_argument("--no-report", action="store_true",
                    help="compute only; for batch callers that format their own output")
    args = ap.parse_args()

    folder = os.path.abspath(args.folder)
    base = os.path.basename(folder)
    s3v = os.path.join(folder, base + ".s3v")
    if not os.path.exists(s3v):
        raise SystemExit("missing " + s3v)

    voxes = sorted(f for f in os.listdir(folder) if f.endswith(".vox"))
    order = ["5m", "4i", "3e", "2a", "1n"]
    if args.difficulty:
        vox = next((v for v in voxes if v.endswith("_%s.vox" % args.difficulty)), None)
        if vox is None:
            raise SystemExit("no chart for difficulty " + args.difficulty)
    else:
        vox = next((v for d in order for v in voxes if v.endswith("_%s.vox" % d)), voxes[0])

    ensure_work()
    render = args.render
    if render is None:
        tag = args.work_tag or args.difficulty or "auto"
        render = os.path.join(WORK, "%s_%s_xcheck.wav" % (base, tag))
        cmd = [sys.executable, os.path.join(_HERE, "apply_chart.py"), folder,
               "-o", render, "-b", str(args.block)]
        if args.difficulty:
            cmd += ["-d", args.difficulty]
        cmd += args.extra.split()
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL if args.quiet else None)

    dry = decode(s3v)
    ref = decode(args.reference)
    mine = decode(render)

    off, slope, c0, npts = align(ref, dry)
    if not args.no_report:
        print("chart     : %s" % vox)
        print("reference : %s (%.1f s)" % (os.path.basename(args.reference), len(ref) / float(SR)))
        print("align     : offset %+.3f s, drift %+.3f samples/s (corr %.3f, %d windows)"
              % (off / SR, slope, c0, npts))

    n = min(len(dry), len(mine))
    nframes = (n - N) // HOP
    if nframes < 32:
        raise SystemExit("too short to score")
    offs = np.array([int(round(off + slope * (k * HOP / float(SR))))
                     for k in range(nframes)])

    R = spectrogram(ref, nframes, offs)
    D = spectrogram(dry, nframes)
    M = spectrogram(mine, nframes)
    lr = np.log10(np.maximum(R, 1e-3))
    ld = np.log10(np.maximum(D, 1e-3))
    lm = np.log10(np.maximum(M, 1e-3))
    live = (R.mean(axis=1) > 20) & (D.mean(axis=1) > 20) & (M.mean(axis=1) > 20)

    sec = read_sections(os.path.join(folder, vox))
    tl = Timeline(sec)
    masks = frame_masks(sec, tl, nframes, n)

    # A frame can have several effects live at once (both FX buttons, plus a
    # laser). Scoring the raw mask therefore measures everything in that region,
    # not the named effect - so also score the frames where this effect is the
    # ONLY FX effect running. That is the column to trust for attribution.
    fx_names = [k for k in masks if k not in ("laser", "idle")]
    d_all, na = score_frames(ld, lr, live)
    m_all, _ = score_frames(lm, lr, live)
    rows = [("ALL", d_all, m_all, na, float("nan"), 0, float("nan"))]
    for name in sorted(masks):
        act = masks[name] & live
        if act.sum() < 8:
            continue
        dv, cnt = score_frames(ld, lr, act)
        mv, _ = score_frames(lm, lr, act)
        ex = act.copy()
        if name in fx_names:
            for other in fx_names:
                if other != name:
                    ex &= ~masks[other]
        edv, ecnt = score_frames(ld, lr, ex)
        emv, _ = score_frames(lm, lr, ex)
        # How far the effect moved the audio at all, regardless of direction.
        # Distinguishes "doing too little" from "doing plenty, but wrong":
        # a big `moved` with a gain near zero means the DSP is active and
        # audible but heading away from the reference.
        emoved, _ = score_frames(ld, lm, ex)
        rows.append((name, dv, mv, cnt, (edv - emv) if ecnt else float("nan"),
                     ecnt, emoved if ecnt else float("nan")))

    if not args.no_report:
        print()
        print("  %-22s %8s %8s %8s %7s %10s %6s %7s"
              % ("region", "dry", "render", "gain", "frames", "excl gain", "excl", "moved"))
        for name, dv, mv, cnt, eg, ecnt, emv in rows:
            eg_s = "     -" if ecnt == 0 or eg != eg else "%+10.3f" % eg
            mv_s = "      -" if ecnt == 0 or emv != emv else "%7.3f" % emv
            print("  %-22s %8.3f %8.3f %+8.3f %7d %10s %6d %7s"
                  % (name, dv, mv, dv - mv, cnt, eg_s, ecnt, mv_s))
        print()
        print("  'gain' = dry - render; positive means the render is closer than")
        print("  doing nothing. 'excl gain' is the same over frames where this is")
        print("  the only FX effect running - use that one for attribution, since")
        print("  overlapping effects otherwise contaminate a region's score.")
        print("  'moved' = how far the effect shifted the audio from dry, in the")
        print("  same units. Big 'moved' with ~zero gain = the DSP is doing plenty,")
        print("  just not toward the reference. That is a wrong algorithm, not an")
        print("  inactive one.")
    return rows


if __name__ == "__main__":
    main()
