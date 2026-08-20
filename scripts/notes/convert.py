#!/usr/bin/env python3
"""
.vox -> .ksh: buttons and lasers.

    python convert.py <chart.vox> [-o out.ksh]

Scope, per HANDOFF.md 3.1: BT/FX/laser note data, timing (BPM/time-signature
changes, needed to build the grid at all), laser slams, curve types, chip vs
hold. Explicitly NOT in scope, by direction: track/song metadata (title,
artist, jacket, audio filename, ...) - written as placeholders - and every
sound-fx parameter (FX-button effect defs, laser filter defs, FX hold's own
effect index, FX chip's sample id) since those are already baked into the
audio track (see the audio element) and have no bearing on the note grid.
`fx-l`/`fx-r` are always reset to blank right before a hold starts, matching
every reference conversion in scripts/shared/reference/ksh - they don't
carry real effect data either.

Grid resolution is picked per measure, independently: the minimum number of
equal-width lines that lets every real event in that measure (a BT/FX note
edge, or a laser point surviving decimation - see laser.py) land exactly on
a line, via gcd. This is always exact and never requires resampling on the
button/hold side; ticks are integers throughout and vox's own grid (48
cells/1-4-note by default) is always a whole multiple of whatever ksh
resolution gets picked.

`camera=True` additionally places tilt/zoom_top/zoom_bottom option lines and
lane-spin tokens computed by ../camera/camera.py into the same grid. Off by
default so every existing caller (notably notes/xcheck.py) keeps its exact
prior output; see specs/camera.md for what's approximate about the camera
values themselves - this module only places them, it doesn't compute them.

`meta`, if given, is a dict of real track metadata (title/artist/effect/
jacket/illustrator/difficulty/level/m) that overrides the placeholders
_header() would otherwise write - see its docstring for the exact keys. This
is how a caller with an actual data source (music_db.xml, for the GUI) gets
a real header instead of "artist=" left blank; every existing caller passes
nothing and gets the old placeholder behaviour unchanged.

`slam_gap_frac` is forwarded to laser.build_runs() - see its docstring and
laser.py's module docstring ("true vox slam") for what it controls. CLI
`--no-slam-gap` sets it to 0.

`ksh_version` picks which of the two laser writings comes out, and nothing else about the file changes with it (`ver=` stays 171 either way - the v2 laser options are new syntax, not a new behaviour version, and none of ksh_format.md's `ver` history entries gates them). 1, the default, is what this converter has always written: a curve becomes interpolated points and the engine joins them straight. 2 re-fits every curve into `laser_l_curve`/`laser_r_curve` bezier segments over far fewer points - see laser.py's "ksh v2: laser curves" section and specs/notes.md. KSM v1.xx ignores an option it doesn't know, so a v2 file opened there draws the remaining points as straight lines, which is why this is a choice and not an upgrade.
"""

import argparse
import bisect
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared"))
import vox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import laser


BT_CHIP, BT_HOLD = "1", "2"
FX_CHIP, FX_HOLD = "2", "1"     # swapped vs BT - ksh_format.md's "historical reasons"


# --------------------------------------------------------------------------
# lane lookups
# --------------------------------------------------------------------------

class HoldLane:
    """Sorted (start, end) intervals + a set of chip ticks for one BT/FX lane."""

    def __init__(self, notes):
        holds = sorted((n.tick, n.end_tick) for n in notes if n.is_hold)
        self.starts = [h[0] for h in holds]
        self.ends = [h[1] for h in holds]
        self.chips = set(n.tick for n in notes if not n.is_hold)
        self.sfx_chips = set(n.tick for n in notes if not n.is_hold and n.c2 > 0)

    def char_at(self, tick, chip_char, hold_char):
        if tick in self.chips:
            return chip_char
        i = bisect.bisect_right(self.starts, tick) - 1
        if i >= 0 and tick < self.ends[i]:
            return hold_char
        return "0"

    def hold_starting_at(self, tick):
        return tick in self.starts

    def anchors(self):
        out = set(self.chips)
        for s, e in zip(self.starts, self.ends):
            out.add(s)
            out.add(e)
        return out


class LaserLane:
    """A laser-track's runs, ordered and queryable by tick."""

    def __init__(self, runs):
        self.runs = sorted(runs, key=lambda r: r.start_tick)
        self.run_starts = [r.start_tick for r in self.runs]
        self.curve_ticks = self._build_curve_ticks()

    def _build_curve_ticks(self):
        """tick -> the (a, b) that tick's `laser_x_curve` option should carry (ksh v2; empty in v1, where Run.curves is all None).

        A curve option belongs on the line of the laser point its segment *starts* at - except coming out of a slam, where ksh_format.md puts it on the slam's own starting line instead ("should be placed just before the slam ... Should not be placed at the line just before the line laser after the slam"). That never collides with another option: the segment starting at a slam's start line *is* the slam, and a slam is never a curve.
        """
        out = {}
        for r in self.runs:
            for i, curve in enumerate(r.curves):
                if curve is None:
                    continue
                tick = r.points[i][0]
                if i > 0 and r.slam_after[i - 1]:
                    tick = r.points[i - 1][0]
                out.setdefault(tick, curve)
        return out

    def curve_at(self, tick):
        return self.curve_ticks.get(tick)

    def run_at(self, tick):
        i = bisect.bisect_right(self.run_starts, tick) - 1
        if i >= 0 and self.runs[i].start_tick <= tick <= self.runs[i].end_tick:
            return self.runs[i]
        return None

    def char_at(self, tick):
        r = self.run_at(tick)
        if r is None:
            return "-"
        ticks = [p[0] for p in r.points]
        j = bisect.bisect_left(ticks, tick)
        if j < len(ticks) and ticks[j] == tick:
            return laser.pos_to_char(r.points[j][1])
        return ":"

    def run_starting_at(self, tick):
        i = bisect.bisect_left(self.run_starts, tick)
        return self.runs[i] if i < len(self.runs) and self.runs[i].start_tick == tick else None

    def anchors(self):
        """Every kept point, plus one tick into every gap between runs.

        Without the latter, a gap that no *other* lane happens to need a
        grid line inside of gets no line at all - the output would go
        straight from one run's last explicit char to the next run's first
        with no '-' between them, silently splicing two separate vox runs
        into what reads as one continuous laser. A one-tick gap has no room
        for a third distinct row and so cannot be separated here at all,
        which is why laser.py's `_separate_runs` guarantees every pair of
        runs `MIN_RUN_GAP_TICKS` (2) apart before this ever runs - the two
        halves of one fix, and the reason the `>= 2` below is a check rather
        than a limitation.
        """
        out = set()
        for r in self.runs:
            for (t, _v) in r.points:
                out.add(t)
        for a, b in zip(self.runs, self.runs[1:]):
            if b.start_tick - a.end_tick >= 2:
                out.add(a.end_tick + 1)
        return out


# --------------------------------------------------------------------------
# grid resolution
# --------------------------------------------------------------------------

def measure_resolution(length, anchor_offsets):
    """Minimum number of equal lines so every offset in (0, length) lands
    exactly on one - gcd-based, always exact (see module docstring).
    """
    g = length
    for o in anchor_offsets:
        if 0 < o < length:
            g = math.gcd(g, o)
    if g <= 0:
        g = length
    return max(1, length // g)


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------

DIFF_MAP = {"1n": "light", "2a": "challenge", "3e": "extended",
            "4i": "infinite", "5m": "infinite"}


def convert(vox_path, out_path, camera=False, meta=None, slam_gap_frac=laser.SLAM_GAP_FRAC,
            pretilt_fix=False, ksh_version=1):
    chart = vox.load(vox_path)
    tl = chart.tl

    curves = ksh_version >= 2
    bt_lanes = [HoldLane(notes) for notes in chart.bt]
    fx_lanes = [HoldLane(notes) for notes in chart.fx]
    laser_lanes = [LaserLane(laser.build_runs(pts, tl, slam_gap_frac=slam_gap_frac, curves=curves))
                   for pts in chart.laser]

    # camera: tick -> pending "option=value" line(s), and tick -> spin suffix.
    # Computed here (not passed in) since it needs the same VoxChart this
    # function already loaded - see ../camera/camera.py for the actual math.
    # `camera` (the bool param) is never rebound below - the module is
    # imported under the alias `camera_mod` specifically to avoid that.
    cam_opts = {}    # tick -> [line, ...]   (each already "option=value")
    cam_spin = {}    # tick -> "@(24" etc (side already resolved/dropped)
    if camera:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "camera"))
        import camera as camera_mod
        # pretilt_fix only reaches the tilt track, and only means anything
        # with camera=True - there is no tilt output at all otherwise.
        for (t, value) in camera_mod.compute_tilt_events(chart, pretilt_fix=pretilt_fix):
            cam_opts.setdefault(t, []).append("tilt=" + value)
        for (t, line) in camera_mod.compute_zoom_events(chart):
            cam_opts.setdefault(t, []).append(line)
        for t, (_side, token) in camera_mod.compute_spin_tokens(chart).items():
            cam_spin[t] = token

    tight_runs = sum(1 for lane in laser_lanes for r in lane.runs if r.tight)
    if tight_runs:
        print("note: %d laser run(s) needed a sub-24th-note gap to keep their true "
              "shape (see laser.py's docstring, point 3) - real, unavoidable "
              "given .ksh's grid" % tight_runs, file=sys.stderr)

    # BPM / time-signature change points, as body option lines
    bpm_changes = []   # (tick, bpm)
    seen_bpm = None
    for (mm, bb, tt, bpm) in tl.bpms:
        tick = tl.abs_tick(mm, bb, tt)
        if bpm != seen_bpm:
            bpm_changes.append((tick, bpm))
            seen_bpm = bpm
    beat_changes = []  # (measure0, num, den) - only meaningful at measure starts
    for (mm, num, den) in tl.beats:
        beat_changes.append((mm, num, den))

    # How far the chart goes. Deliberately NOT chart.end_tick: vox's
    # #END POSITION is the arcade chart's official end (used for gauge/score
    # purposes) and routinely runs well past the last real event - a trailing
    # note-less outro adds measures no reference conversion bothers keeping.
    # Crosschecked via xcheck.py: ending at the last real event lands on or
    # within 1 measure of every one of the 5 matched reference conversions;
    # #END POSITION overshoots all of them, by 8 measures on the worst one.
    #
    # Camera events count too: a tilt/zoom/spin can outlast the last note or
    # laser into what would otherwise look like a note-less outro (e.g. a
    # zoom hold that resolves after the chart's last hit) - dropping those
    # events silently threw away real camera motion the charter placed on
    # purpose, so the chart is extended to cover them instead (previously:
    # "note: N camera event(s) past the chart's last real note were dropped",
    # user-reported as unwanted - the reference-conversion overshoot this
    # section otherwise guards against is about vox's #END POSITION running
    # measures past everything, not about a camera event a few ticks past
    # the last note).
    last_tick = 0
    for lane in bt_lanes + fx_lanes:
        if lane.ends:
            last_tick = max(last_tick, lane.ends[-1])
        if lane.chips:
            last_tick = max(last_tick, max(lane.chips))
    for lane in laser_lanes:
        for r in lane.runs:
            last_tick = max(last_tick, r.end_tick)
    if camera:
        if cam_opts:
            last_tick = max(last_tick, max(cam_opts))
        if cam_spin:
            last_tick = max(last_tick, max(cam_spin))
    last_measure, _ = tl.measure_of_tick(last_tick)

    # When the chart only has one BPM the whole way through, the header's
    # single-value "t=" already says it and no body line is needed. But the
    # instant there's more than one, the header's "t=" becomes a "min-max"
    # range (see _header) that doesn't by itself say which end the chart
    # *starts* on - KSM's own editor always restates the actual starting
    # tempo as a body "t=" right at measure 0 in that case (confirmed
    # against every multi-BPM reference chart in scripts/shared/reference/
    # ksh: single-BPM charts never get a measure-0 "t=", every multi-BPM one
    # does). Skipping bpm_changes[0] unconditionally left that line out,
    # so a chart's first measure(s) played back at whatever the engine
    # defaults to instead of the vox's actual starting BPM - found against
    # 2397_ultracharge_yutaimai_5m, whose "t=55-220" header did not by
    # itself establish that the chart starts at 220 (user-reported).
    # "beat=" doesn't have this problem: it's a single value in the header
    # to begin with, so KSM's habit of restating it at measure 0 is just
    # convention, not information the range-header case is missing here.
    bpm_by_measure = {}
    multi_bpm = len(set(b for _t, b in bpm_changes)) > 1
    for (tick, bpm) in bpm_changes if multi_bpm else bpm_changes[1:]:
        m, off = tl.measure_of_tick(tick)
        bpm_by_measure.setdefault(m, []).append((off, bpm))
    beat_by_measure = {mm: (num, den) for (mm, num, den) in beat_changes}

    lines = []
    lines.extend(_header(chart, bpm_changes, beat_changes, meta=meta))

    cur_num, cur_den = None, None

    for m in range(0, last_measure + 1):
        mlen = tl.measure_length(m)
        m_start = tl.measure_start_tick(m)

        anchors = set()
        for lane in bt_lanes + fx_lanes:
            anchors |= {t - m_start for t in lane.anchors()
                        if m_start <= t < m_start + mlen}
        for lane in laser_lanes:
            anchors |= {t - m_start for t in lane.anchors()
                        if m_start <= t < m_start + mlen}
        for (off, _bpm) in bpm_by_measure.get(m, []):
            anchors.add(off)
        if camera:
            anchors |= {t - m_start for t in cam_opts if m_start <= t < m_start + mlen}
            anchors |= {t - m_start for t in cam_spin if m_start <= t < m_start + mlen}

        res = measure_resolution(mlen, anchors)
        step = mlen // res

        if m in beat_by_measure:
            num, den = beat_by_measure[m]
            # KSM's own editor always restates "beat=" for measure 0, even
            # though it duplicates the header default; later measures only
            # get one when the time signature actually changes.
            if m == 0 or (num, den) != (cur_num, cur_den):
                lines.append("beat=%d/%d" % (num, den))
            cur_num, cur_den = num, den

        bpm_here = dict(bpm_by_measure.get(m, []))

        for k in range(res):
            tick = m_start + k * step
            if k in bpm_here:
                lines.append("t=%s" % _fmt_bpm(bpm_here[k]))
            if camera:
                for opt_line in cam_opts.get(tick, ()):
                    lines.append(opt_line)

            for li, lane in enumerate(fx_lanes):
                side = "l" if li == 0 else "r"

                if lane.hold_starting_at(tick):
                    lines.append("fx-%s=" % side)

                if tick in lane.sfx_chips:
                    lines.append("fx-%s_se=clap;0" % side)

            for li, lane in enumerate(laser_lanes):
                side = "l" if li == 0 else "r"
                run = lane.run_starting_at(tick)
                if run is not None and run.width == 2:
                    lines.append("laserrange_%s=2x" % side)
                if curves:
                    curve = lane.curve_at(tick)
                    if curve is not None:
                        lines.append("laser_%s_curve=%s" % (side, _fmt_curve(curve)))

            bt_chars = "".join(lane.char_at(tick, BT_CHIP, BT_HOLD) for lane in bt_lanes)
            fx_chars = "".join(lane.char_at(tick, FX_CHIP, FX_HOLD) for lane in fx_lanes)
            laser_chars = "".join(lane.char_at(tick) for lane in laser_lanes)
            spin_suffix = cam_spin.get(tick, "") if camera else ""
            lines.append("%s|%s|%s%s" % (bt_chars, fx_chars, laser_chars, spin_suffix))

        lines.append("--")

    with open(out_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def _fmt_bpm(bpm):
    s = "%.3f" % bpm
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_curve(curve):
    """A fitted (a, b) -> the `laser_l_curve`/`laser_r_curve` payload, "<a>;<b>".

    Two decimals, matching ksh_format.md's own examples and the precision laser.py already rounds its fits to: b moves the drawn position by at most 2*s*(1-s) <= 0.5 of whatever it changes by, so a hundredth of b is a two-hundredth of a lane - a quarter of one of ksh's 51 laser steps.
    """
    return "%.2f;%.2f" % curve


def _header(chart, bpm_changes, beat_changes, meta=None):
    """`meta` keys, all optional, override the corresponding placeholder:
    title, artist, effect (chart author, ksh_format.md's name for it),
    jacket (filename), illustrator, difficulty (light/challenge/extended/
    infinite - overrides the DIFF_MAP guess from the filename suffix),
    level (difnum, 1..20), m (audio filename, overrides "dummy.ogg").
    """
    meta = meta or {}
    base = os.path.splitext(os.path.basename(chart.path))[0]
    diff_suffix = base.rsplit("_", 1)[-1] if "_" in base else ""
    difficulty = meta.get("difficulty") or DIFF_MAP.get(diff_suffix, "infinite")

    bpms = sorted(set(b for _t, b in bpm_changes)) or [120.0]
    if len(bpms) == 1:
        t_val = _fmt_bpm(bpms[0])
    else:
        t_val = "%s-%s" % (_fmt_bpm(min(bpms)), _fmt_bpm(max(bpms)))
    num0, den0 = (beat_changes[0][1], beat_changes[0][2]) if beat_changes else (4, 4)

    h = [
        "title=%s" % meta.get("title", base),
        "artist=%s" % meta.get("artist", ""),
        "effect=%s" % meta.get("effect", ""),
        "jacket=%s" % meta.get("jacket", ""),
        "illustrator=%s" % meta.get("illustrator", ""),
        "difficulty=%s" % difficulty,
        "level=%s" % meta.get("level", "1"),
        "t=%s" % t_val,
        "to=0",
        "beat=%d/%d" % (num0, den0),
        "m=%s" % meta.get("m", "dummy.ogg"),
        "mvol=100",
        "o=0",
        "bg=desert",
        "layer=arrow",
        "po=0",
        "plength=0",
        "total=0",
        "chokkakuvol=0",
        "chokkakuautovol=1",
        "filtertype=peak",
        "pfiltergain=0",
        "pfilterdelay=40",
        "ver=171",
        "--",
    ]
    return h


def build_arg_parser():
    """Split out of main() so a caller (the GUI) can introspect the option
    list without duplicating it or invoking main() itself - same reasoning
    as apply_chart.py's build_arg_parser()."""
    ap = argparse.ArgumentParser()
    ap.add_argument("vox", help="path to a .vox chart")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--ksh-version", type=int, choices=(1, 2), default=1,
                     help="1 (default) writes every laser curve as interpolated points, which is "
                          "all KSM v1.xx can read. 2 re-fits each curve and writes it as a "
                          "laser_l_curve/laser_r_curve bezier over far fewer points - smoother and "
                          "closer to the vox shape, but KSM v1.xx ignores the option lines and "
                          "draws the remaining points straight. See specs/notes.md")
    ap.add_argument("--no-slam-gap", action="store_true",
                     help="place a genuine same-tick vox slam's landing point on the "
                          "very next free tick instead of ksh's standard 1/64-of-a-measure "
                          "gap (laser.py's SLAM_GAP_FRAC). On by default, since the bare "
                          "next-free-tick placement renders as a near-invisible hairline "
                          "and can force a measure's grid down to near-native resolution "
                          "to fit just one point - see laser.py's module docstring")
    return ap


def main():
    args = build_arg_parser().parse_args()
    out = args.output or os.path.splitext(os.path.basename(args.vox))[0] + ".ksh"
    slam_gap_frac = 0 if args.no_slam_gap else laser.SLAM_GAP_FRAC
    path = convert(args.vox, out, slam_gap_frac=slam_gap_frac, ksh_version=args.ksh_version)
    print("wrote %s" % path)


if __name__ == "__main__":
    main()
