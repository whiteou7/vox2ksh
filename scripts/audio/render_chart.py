#!/usr/bin/env python3
"""Applies a chart's FX holds and lasers to its .s3v. Also does the device ParamEq, the music duck and the layered SE bank. `--help` lists the flags that switch off parts of the chain, each explained in specs/audio_engine.md section 6.

    python render_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
"""

import argparse
import collections
import math
import os
import struct
import subprocess
import sys
from typing import NamedTuple

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "shared"))
import fx_dsp as FX  # noqa: E402
import vox_parser as vox  # noqa: E402
from game_paths import find_ffmpeg  # noqa: E402

SR = FX.SR

FX_NAMES = {
    1: "Retrigger", 2: "Gate", 3: "Flanger", 4: "TapeStop", 5: "SideChain",
    6: "Wobble", 7: "BitCrusher", 8: "Echo(RetriggerEx)", 9: "PitchShift",
    10: "TapeStopEx", 11: "LowPassFilter", 12: "HighPassFilter",
    13: "PitchSpeed",
}
TAB_NAMES = {1: "LowPassFilter", 2: "HighPassFilter", 3: "BitCrusher"}

CHIP_SAMPLE_NAMES = {
    1: "big snare (quiet)", 2: "big clap", 3: "short clap", 4: "big snare",
    5: "short snare", 6: "crash", 7: "kick+crash+downlifter", 8: "open hi-hat",
    9: "kick+crash alt", 10: "snare+click", 11: 'female "oh"', 12: 'male "hey"',
    13: 'male "yeah"', 14: "fireworks",
}

PEAK_DELAY = 0.08
PARAM_ASSIGN_BLOCK = 512
# Effect ids whose phase restarts on the beat grid rather than at the note.
GRID_LOCKED = {1}
# Laser point effect column value that selects #TAB PARAM ASSIGN INFO's sweep.
PARAM_SWEEP_EFFECT = 6
# Index of the mix in an FX-button effect's parameters (row minus its id column); 0 unless listed.
MIX_PARAM = {1: 1, 8: 1, 6: 2}
# Laser positions run 0..1; the engine's knob runs 0..127.
KNOB_MAX = 127.0


def sample_index(tl, tick):
    return int(round(tl.seconds_at(tick) * SR))


def parse_fx_pairs(sec):
    rows = []
    for line in sec.get("#FXBUTTON EFFECT INFO", []):
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            pass
    return [[first if first and first[0] != 0 else None, second if second and second[0] != 0 else None]
            for first, second in zip(rows[0::2], rows[1::2])]


def parse_param_assign(sec):
    """{effect pair index: [(parameter index, low, high) per chain slot]}"""
    out = collections.defaultdict(list)
    for line in sec.get("#TAB PARAM ASSIGN INFO", []):
        parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip() != ""]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) >= 4:
            out[int(vals[0])].append((int(vals[1]), vals[2], vals[3]))
    return out


def parse_effects(sec, key):
    out = []
    for line in sec.get(key, []):
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if vals and any(v != 0 for v in vals):
            out.append(vals)
    return out


def parse_auto_tab(sec, tl):
    """(tick, length, effect pair id) per #TRACK AUTO TAB span."""
    for line in sec.get("#TRACK AUTO TAB", []):
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            length, pair_id = int(fields[1]), int(fields[2])
        except ValueError:
            continue
        yield tl.tick_of_position(fields[0]), length, pair_id


class LaserSegment(NamedTuple):
    """One laser section between two points. Knob values are 0..127 with the right lane already mirrored."""
    start_tick: int
    end_tick: int
    start_knob: float
    end_knob: float
    tab_index: int
    curve: int


def laser_segments(points, mirror):
    """A point starts a section unless it is a section's end (node type 2)."""
    def knob(position):
        return (1.0 - position if mirror else position) * KNOB_MAX
    return [LaserSegment(current.tick, following.tick, knob(current.pos), knob(following.pos),
                current.effect, current.curve_type)
            for current, following in zip(points, points[1:]) if current.node_type != 2]


def param_sweep_curve(chart, n):
    """Per-sample 0..1 sweep value and mask for lasers whose effect column selects the param sweep. Overlaps keep the larger value."""
    tl = chart.tl
    values = np.zeros(n, np.float32)
    active = np.zeros(n, bool)
    for points, mirror in zip(chart.laser, (False, True)):
        for current, following in zip(points, points[1:]):
            if current.node_type == 2 or current.effect != PARAM_SWEEP_EFFECT:
                continue
            start, stop = max(0, sample_index(tl, current.tick)), min(n, sample_index(tl, following.tick))
            if stop <= start:
                continue
            start_pos = (1.0 - current.pos) if mirror else current.pos
            end_pos = (1.0 - following.pos) if mirror else following.pos
            ramp = np.linspace(start_pos, end_pos, stop - start, endpoint=False, dtype=np.float32)
            existing = values[start:stop]
            replace = (~active[start:stop]) | (ramp > existing)
            existing[replace] = ramp[replace]
            active[start:stop][replace] = True
    return values, active


def _apply_easing(phase, curve, sin=math.sin):
    if curve == 4:
        return sin(phase * math.pi / 2.0)
    if curve == 5:
        return sin((phase - 1.0) * math.pi / 2.0) + 1.0
    return phase


def _grid_origin_sample(tl, tick):
    """The latest tempo or time-signature change at or before `tick`, in samples."""
    changes = [change_tick for change_tick, _bpm in tl.bpm_pts]
    changes += [tl.measure_start_tick(measure) for measure, _num, _den in tl.beats]
    return max((sample_index(tl, change_tick) for change_tick in changes if change_tick <= tick), default=0)


def grid_lock_lead_samples(tl, tick, length_beats):
    position = sample_index(tl, tick)
    seconds_per_beat = int(2646000.0 / tl.bpm_at(tick))
    samples_per_measure = seconds_per_beat * tl.timesig_at_measure(tl.measure_and_offset(tick)[0])[0]
    period = int(seconds_per_beat * float(length_beats))
    if samples_per_measure <= 0 or period <= 0:
        return 0
    offset = ((position - _grid_origin_sample(tl, tick)) % samples_per_measure) % period
    return 0 if offset > period - 512 else offset


def s3v_header_gain(header):
    if header[:4] != b"S3V0":
        return 1.0
    g0, g1 = struct.unpack_from("<hh", header, 0x14)
    return 10.0 ** (((g0 + g1) / 256.0) / 20.0)


def s3p_header_gains(path):
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        data = f.read()
    magic, count = struct.unpack_from("<4sI", data, 0)
    if magic != b"S3P0":
        return []
    offsets = [struct.unpack_from("<II", data, 8 + i * 8)[0] for i in range(count)]
    return [s3v_header_gain(data[offset:offset + 32]) for offset in offsets]


class Sample(NamedTuple):
    name: str
    left: np.ndarray
    right: np.ndarray
    gain: float


def load_sample_bank(path):
    """One Sample per entry, named from the .def file beside it when there is one."""
    names = []
    def_path = os.path.splitext(path)[0] + ".def"
    if os.path.exists(def_path):
        with open(def_path) as f:
            names = [w[1] for w in map(str.split, f) if len(w) >= 3 and w[0] == "#define"]
    with open(path, "rb") as f:
        data = f.read()
    magic, count = struct.unpack_from("<4sI", data, 0)
    if magic != b"S3P0":
        raise SystemExit("%s is not an S3P0 container" % path)
    out = []
    for i in range(count):
        offset, size = struct.unpack_from("<II", data, 8 + i * 8)
        blob = data[offset:offset + size]
        hmagic, hsize = struct.unpack_from("<4sI", blob, 0)
        payload = blob[hsize:] if hmagic == b"S3V0" else blob
        left, right = decode_audio(blob=payload, what="SE sample %d of %s" % (i, os.path.basename(path)))
        name = names[i] if i < len(names) else "idx%02d" % i
        out.append(Sample(name, left, right, s3v_header_gain(blob[:32])))
    return out


def _copies(left, right, start, stop):
    """Independent copies of both channels over [start, stop), for an effect to work on."""
    return left[start:stop].copy(), right[start:stop].copy()


def mix_sample_into(left, right, position, sample, gain, cut_at=None):
    """Mixes `sample` into L/R from `position`, stopping at `cut_at` when given."""
    n = min(sample.left.size, left.size - position)
    if cut_at is not None:
        n = min(n, max(0, cut_at - position))
    if n <= 0:
        return
    left[position:position + n] += sample.left[:n] * gain
    right[position:position + n] += sample.right[:n] * gain


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def decode_audio(src=None, blob=None, what="audio"):
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found - needed to decode the %s (ASF/WMA)" % what)
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error",
         "-i", src if blob is None else "pipe:0",
         "-f", "s16le", "-ar", str(SR), "-ac", "2", "pipe:1"],
        input=blob, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise SystemExit("ffmpeg failed to decode the %s:\n%s"
                         % (what, r.stderr.decode("utf8", "replace").strip()))
    d = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32).reshape(-1, 2)
    return d[:, 0].copy(), d[:, 1].copy()


def encode_pcm(frames, out, sr, quality=6):
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found - needed to encode %s. Write a .wav "
                         "instead, or put ffmpeg on PATH" % os.path.basename(out))
    cmd = [ff, "-hide_banner", "-loglevel", "error",
           "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", "pipe:0"]
    if os.path.splitext(out)[1].lower() == ".ogg":
        cmd += ["-c:a", "libvorbis", "-q:a", str(quality)]
    cmd += ["-y", out]
    try:
        subprocess.run(cmd, input=frames.tobytes(), check=True, creationflags=_NO_WINDOW)
    except subprocess.CalledProcessError:
        raise SystemExit("ffmpeg failed to encode %s (is libvorbis available in "
                         "this build?). Write a .wav instead." % os.path.basename(out))
    return out


def write_audio(path, left, right, sr, quality=6):
    if os.path.splitext(path)[1].lower() == ".wav":
        FX.write_wav(path, left, right, sr)
        return path
    return encode_pcm(FX.writeback(left, right), path, sr, quality)


class Render:
    """One render: the working L/R track, the untouched dry copy, and the tallies reported at the end. Stages run in engine order in `run`."""

    def __init__(self, args, chart, left, right):
        self.args = args
        self.chart = chart
        self.sec = chart.sec
        self.tl = chart.tl
        self.left, self.right = left, right
        self.n = left.size
        self.dry_left, self.dry_right = left.copy(), right.copy()
        self.fxdefs = parse_fx_pairs(self.sec)
        self.tabdefs = parse_effects(self.sec, "#TAB EFFECT INFO")
        self.applied = collections.Counter()
        self.skipped = collections.Counter()
        self.snapped = collections.Counter()
        self.wobble_state = {} if args.wobble_persist else None

    # -- effect dispatch --------------------------------------------------

    def quantize_stage(self, values):
        """Rounds a stage's output the way the engine's int16 buffers do, unless --no-stage-clip."""
        if self.args.no_stage_clip:
            return values
        return np.trunc(np.clip(values, -32768.0, 32767.0)).astype(np.float32)

    def quantize_stereo(self, rendered, skip=0):
        """(left, right) of a stage result, quantized, without its first `skip` samples."""
        return self.quantize_stage(rendered[0][skip:]), self.quantize_stage(rendered[1][skip:])

    def apply_button_effect(self, left, right, effect, tick, lookahead=None):
        """One FX-button effect over a span. None when the effect is unimplemented or switched off."""
        args, tl, block = self.args, self.tl, self.args.block
        effect_id = int(effect[0])
        params = list(effect[1:])
        mix_param = MIX_PARAM.get(effect_id, 0)
        if mix_param < len(params):
            params[mix_param] *= args.mix_scale
        beat = 60.0 / tl.bpm_at(tick)
        resonance = dict(res_scale=args.filter_resonance_scale, res_max_db=args.filter_max_resonance)

        if effect_id in (1, 8):
            count, mix, beats, feedback, gate, release = params[:6]
            return FX.fx_retrigger(left, right, mix, beats * beat, feedback, int(count), gate, release,
                                   block=block)
        if effect_id == 2:
            mix, steps, beats = params[:3]
            return FX.fx_gate(left, right, mix, int(steps), beats * beat, block=block,
                              hard_binary=args.gate_hard_binary)
        if effect_id == 3:
            mix, delay_ms, measures, depth, stages = params[:5]
            measure = beat * tl.beats_per_measure_at(tick)
            return FX.fx_flanger(left, right, mix, delay_ms, measures / measure, int(depth), stages,
                                 block=block)
        if effect_id == 4:
            return FX.fx_tapestop(left, right, *params[:3], block=block)
        if effect_id == 5:
            mix, beats, attack, hold, release = params[:5]
            return FX.fx_sidechain(left, right, mix, beats * beat, int(attack), int(hold), int(release),
                                   block=block)
        if effect_id == 6:
            filter_type, wave_type, mix, freq_a, freq_b, rate, q = params[:7]
            rate = float(rate)
            period = rate * beat if args.wobble_legacy_period else beat / max(rate, 1e-6)
            return FX.fx_wobble(left, right, mix, int(filter_type), int(wave_type), freq_a, freq_b, period, q,
                                block=block, state=self.wobble_state)
        if effect_id == 7:
            mix, rate = params[:2]
            return FX.fx_bitcrush(left, right, mix, int(rate), block=block,
                                  continuous=args.bitcrush_continuous)
        if effect_id == 9 and not args.no_pitchshift:
            mix, amount = params[:2]
            return FX.fx_pitchshift(left, right, mix, amount, block=block,
                                    legacy_cursor=args.pitchshift_legacy_cursor)
        if effect_id == 10 and not args.no_tapestop_ex:
            mix, speed, *beats = params[:5]
            duration, preroll, window = (b * beat for b in beats)
            if args.tapestop_ex_3phase:
                return FX.fx_tapestop_ex_3phase(left, right, mix, speed, duration, preroll, window,
                                                block=block, lookahead=lookahead)
            return FX.fx_tapestop_ex(left, right, mix, speed, duration, preroll, window, block=block,
                                     lookahead=lookahead, floor=args.tapestop_ex_floor)
        if effect_id == 11:
            return FX.fx_laser_lpf(left, right, *params[:4], block=block, **resonance)
        if effect_id == 12:
            return FX.fx_laser_hpf(left, right, *params[:4], block=block, **resonance)
        if effect_id == 13 and not args.no_pitch_speed:
            return FX.fx_pitch_speed(left, right, *params[:3], block=block, lookahead=lookahead)
        return None

    def apply_laser_effect(self, left, right, effect, knob):
        """A laser's own effect over a span, driven by `knob` automation. None for unknown types."""
        args = self.args
        effect_id = int(effect[0])
        params = list(effect[1:])
        params[0] *= args.mix_scale
        resonance = dict(res_scale=args.filter_resonance_scale, res_max_db=args.filter_max_resonance)
        if effect_id == 1:
            return FX.fx_laser_lpf(left, right, *params[:4], knob=knob, block=args.block, **resonance)
        if effect_id == 2:
            return FX.fx_laser_hpf(left, right, *params[:4], knob=knob, block=args.block, **resonance)
        if effect_id == 3:
            return FX.fx_laser_bitcrush(left, right, *params[:2], knob=knob, block=args.block)
        return None

    # -- stages -----------------------------------------------------------

    def _grid_lead_samples(self, effect, start_tick):
        """Samples a grid-locked effect's phase starts before its note."""
        if self.args.no_grid_snap or int(effect[0]) not in GRID_LOCKED or len(effect) <= 3:
            return 0
        return grid_lock_lead_samples(self.tl, start_tick, effect[3])

    def _sample_range(self, start_tick, end_tick):
        """Sample range between two ticks, clipped to the track."""
        return (max(0, sample_index(self.tl, start_tick)),
                min(self.n, sample_index(self.tl, end_tick)))

    def apply_fx_buttons(self):
        args = self.args
        lanes = (("FX-L", self.chart.fx[0]), ("FX-R", self.chart.fx[1]))
        for label, notes in lanes[::-1] if args.fx_order_rl else lanes:
            for note in notes:
                pair_index = note.c2 - 2
                if note.length <= 0 or pair_index < 0 or pair_index >= len(self.fxdefs):
                    continue
                start, stop = self._sample_range(note.tick, note.tick + note.length)
                if stop - start < 16:
                    continue

                plan = [(effect, self._grid_lead_samples(effect, note.tick))
                        for effect in self.fxdefs[pair_index] if effect is not None]
                if not plan:
                    continue

                # Grid-locked effects start their phase before the note, so render from there.
                lead_start = max(0, start - max(snap for _effect, snap in plan))
                if args.fx_chain_overlap:
                    source_left, source_right = self.left, self.right
                else:
                    source_left, source_right = self.dry_left, self.dry_right
                work_left, work_right = _copies(source_left, source_right, lead_start, stop)

                wrote = False
                for effect, snap in plan:
                    offset = max(0, start - snap) - lead_start
                    lookahead = (source_left, source_right, lead_start + offset)
                    rendered = self.apply_button_effect(
                        *_copies(work_left, work_right, offset, None), effect, note.tick, lookahead=lookahead)
                    name = FX_NAMES.get(int(effect[0]), "?")
                    if rendered is None:
                        self.skipped[name] += 1
                        continue
                    work_left[offset:], work_right[offset:] = self.quantize_stereo(rendered)
                    wrote = True
                    key = "%s (%s)" % (name, label)
                    self.applied[key] += 1
                    if snap:
                        self.snapped[key] += 1
                if wrote:
                    skip = start - lead_start
                    self.left[start:stop], self.right[start:stop] = work_left[skip:], work_right[skip:]

    def apply_auto_tab(self):
        """#TRACK AUTO TAB spans: a laser borrows an FX-button effect pair, optionally with a laser-driven parameter sweep."""
        sweep = not self.args.no_param_assign_sweep
        assign_table = parse_param_assign(self.sec) if sweep else {}
        sweep_value = sweep_active = None
        if sweep:
            sweep_value, sweep_active = param_sweep_curve(self.chart, self.n)

        for start_tick, length, pair_id in parse_auto_tab(self.sec, self.tl):
            pair_index = pair_id - 2
            if length <= 0 or pair_index < 0 or pair_index >= len(self.fxdefs):
                continue
            start, stop = self._sample_range(start_tick, start_tick + length)
            if stop - start < 16:
                continue
            assigns = assign_table.get(pair_index, [])
            for slot, effect in enumerate(self.fxdefs[pair_index]):
                if effect is None:
                    continue
                name = FX_NAMES.get(int(effect[0]), "?")
                assignment = None
                if sweep and slot < len(assigns):
                    param_index = assigns[slot][0]
                    if 0 < param_index < len(effect) and np.any(sweep_active[start:stop]):
                        assignment = assigns[slot]

                if assignment is None:
                    self._apply_borrowed_effect(effect, name, start_tick, start, stop)
                else:
                    self._apply_borrowed_effect_swept(effect, name, start_tick, start, stop, assignment,
                                         (sweep_value, sweep_active))

    def _apply_borrowed_effect(self, effect, name, start_tick, start, stop):
        left, right = self.left, self.right
        lead_start = max(0, start - self._grid_lead_samples(effect, start_tick))
        rendered = self.apply_button_effect(*_copies(left, right, lead_start, stop), effect, start_tick,
                                            lookahead=(left, right, lead_start))
        if rendered is None:
            self.skipped[name] += 1
            return
        skip = start - lead_start
        left[start:stop], right[start:stop] = self.quantize_stereo(rendered, skip)
        self.applied["%s (AUTO TAB)" % name] += 1

    def _apply_borrowed_effect_swept(self, effect, name, start_tick, start, stop, assignment, sweep):
        """Runs the effect in short blocks, setting one parameter from the laser's position in each."""
        left, right = self.left, self.right
        sweep_value, sweep_active = sweep
        param_index, low, high = assignment

        def swept_blocks():
            """(block start, block end, parameter value or None where no control laser is active)."""
            for block_start in range(start, stop, PARAM_ASSIGN_BLOCK):
                block_end = min(block_start + PARAM_ASSIGN_BLOCK, stop)
                active = sweep_active[block_start:block_end]
                value = None
                if np.any(active):
                    position = float(np.mean(sweep_value[block_start:block_end][active]))
                    value = low + (high - low) * max(0.0, min(1.0, position))
                yield block_start, block_end, value

        if param_index == 1 + MIX_PARAM.get(int(effect[0]), 0):
            # The engine renders the span once and reads the swept mix as a function of time (0x1806371f0,
            # evaluator 0x180637cc0), so effect state never restarts. Output is affine in each effect's wet
            # share, so blending the mix-0 and mix-100 renders by that share gives the same result.
            # shortcut: Flanger's feedback is not affine in mix, so only its constant-mix stretches are exact;
            # render it in one pass with a time-varying mix if a moving Flanger sweep sounds off.
            renders = []
            for mix in (0.0, 100.0):
                fixed = list(effect)
                fixed[param_index] = mix
                rendered = self.apply_button_effect(*_copies(left, right, start, stop), fixed, start_tick,
                                                    lookahead=(left, right, start))
                if rendered is None:
                    self.skipped[name] += 1
                    return
                renders.append(rendered)
            weight = np.full(stop - start, effect[param_index], np.float32)
            for block_start, block_end, value in swept_blocks():
                if value is not None:
                    weight[block_start - start:block_end - start] = value
            weight = np.clip(weight / 100.0, 0.0, 1.0)
            if int(effect[0]) == 13:
                weight = FX.pitch_speed_wet(weight)
            (dry_left, dry_right), (wet_left, wet_right) = renders
            left[start:stop], right[start:stop] = self.quantize_stereo(
                (dry_left + weight * (wet_left - dry_left), dry_right + weight * (wet_right - dry_right)))
            self.applied["%s (AUTO TAB sweep)" % name] += 1
            return

        any_applied = False
        for block_start, block_end, value in swept_blocks():
            block_effect = effect
            if value is not None:
                block_effect = list(effect)
                block_effect[param_index] = value
            rendered = self.apply_button_effect(*_copies(left, right, block_start, block_end), block_effect,
                                                start_tick, lookahead=(left, right, block_start))
            if rendered is None:
                self.skipped[name] += 1
                continue
            left[block_start:block_end], right[block_start:block_end] = self.quantize_stereo(rendered)
            any_applied = True
        if any_applied:
            self.applied["%s (AUTO TAB sweep)" % name] += 1

    def apply_lasers(self):
        """Applies each laser's own effect and returns the per-sample knob and the mask of lasers that bypass the device ParamEq."""
        args, n = self.args, self.n
        peak_knob = np.zeros(n, np.float32)
        peak_disabled = np.zeros(n, bool)
        # The engine snapshots its source once before dispatching any run, so lasers don't stack.
        chain = (self.left, self.right) if args.laser_chain_overlap else (self.left.copy(), self.right.copy())
        if args.no_laser:
            return peak_knob, peak_disabled

        for label, points, mirror in (("VOL-L", self.chart.laser[0], False),
                                      ("VOL-R", self.chart.laser[1], True)):
            segs = laser_segments(points, mirror)
            for seg in segs:
                start, stop = self._sample_range(seg.start_tick, seg.end_tick)
                if stop <= start:
                    continue
                if args.laser_easing and seg.curve in (4, 5):
                    phase = np.arange(stop - start, dtype=np.float64) / max(stop - start, 1)
                    eased = _apply_easing(phase, seg.curve, np.sin)
                    ramp = (seg.start_knob + (seg.end_knob - seg.start_knob) * eased).astype(np.float32)
                else:
                    ramp = np.linspace(seg.start_knob, seg.end_knob, stop - start, endpoint=False,
                                       dtype=np.float32)
                np.maximum(peak_knob[start:stop], ramp, out=peak_knob[start:stop])
                if seg.tab_index != 0:
                    peak_disabled[start:stop] = True

            for run in self._group_into_runs(segs):
                self._apply_laser_run(run, label, chain)
        return peak_knob, peak_disabled

    @staticmethod
    def _group_into_runs(segs):
        """Contiguous sections with the same effect column form one run."""
        runs = []
        for seg in segs:
            previous = runs[-1][-1] if runs else None
            if previous and previous.end_tick == seg.start_tick and previous.tab_index == seg.tab_index:
                runs[-1].append(seg)
            else:
                runs.append([seg])
        return runs

    def _apply_laser_run(self, run, label, chain):
        args, tl = self.args, self.tl
        tab_index = run[0].tab_index
        if tab_index >= 6 or (tab_index > 0 and tab_index - 1 >= len(self.tabdefs)):
            return
        start_tick, end_tick = run[0].start_tick, run[-1].end_tick
        if end_tick <= start_tick:
            return
        start, stop = self._sample_range(start_tick, end_tick)
        if stop - start < args.block:
            return
        if tab_index == 0:
            self.applied["PeakFilter (%s)" % label] += 1
            return

        base = tl.seconds_at(start_tick)
        knob = []
        for seg in run:
            start_seconds = max(tl.seconds_at(seg.start_tick) - base, 0.0)
            if args.laser_easing and seg.curve in (4, 5):
                duration = max(tl.seconds_at(seg.end_tick) - base, 0.0) - start_seconds
                nsteps = max(2, int(duration * SR / max(args.block, 1)))
                for k in range(nsteps):
                    phase = _apply_easing(k / float(nsteps), seg.curve)
                    value = seg.start_knob + (seg.end_knob - seg.start_knob) * phase
                    knob.append((start_seconds + duration * (k / float(nsteps)), value))
            else:
                knob.append((start_seconds, seg.start_knob))
        knob.append((max(tl.seconds_at(run[-1].end_tick) - base, 0.0), run[-1].end_knob))

        effect = self.tabdefs[tab_index - 1]
        source_left, source_right = (chain if args.laser_mode == "chain" else (self.dry_left, self.dry_right))
        rendered = self.apply_laser_effect(*_copies(source_left, source_right, start, stop), effect, knob)
        name = TAB_NAMES.get(int(effect[0]), "?")
        if rendered is None:
            self.skipped[name] += 1
            return

        left, right = self.left, self.right
        if args.laser_mode == "add":
            # Both lasers' deltas from the dry track are summed onto the chain.
            left[start:stop] = self.quantize_stage(left[start:stop] + rendered[0] - self.dry_left[start:stop])
            right[start:stop] = self.quantize_stage(
                right[start:stop] + rendered[1] - self.dry_right[start:stop])
        else:
            left[start:stop], right[start:stop] = self.quantize_stereo(rendered)
        self.applied["%s (%s)" % (name, label)] += 1

    def paramq_knob(self, peak_knob, peak_disabled):
        """Per-sample knob for the device ParamEq: gated to default-EQ lasers, then delayed by the engine's queue lag."""
        args = self.args
        knob = peak_knob.copy()
        if not args.peak_always:
            knob[peak_disabled] = 0.0
        delay_samples = int(round(args.peak_delay * SR))
        if delay_samples > 0:
            knob = np.concatenate([np.zeros(delay_samples, np.float32), knob[:-delay_samples]])
        return knob

    def apply_music_duck(self, knob):
        """Scales L/R by the music-voice gain the game applies alongside the default laser EQ."""
        args = self.args
        per_block = knob[::args.block].astype(np.int32)
        step = np.inf if args.duck_rate is None else args.duck_rate * args.block / float(SR)
        gains = np.empty(per_block.size, np.float64)
        gain = 1.0
        for i, knob_value in enumerate(per_block):
            if not (args.duck_hold and knob_value < FX.PEAK_KNOB_DEADZONE):
                target = FX.peak_duck_target(knob_value)
                gain += max(-step, min(step, target - gain))
            gains[i] = gain
        envelope = np.repeat(gains, args.block)[:self.n].astype(np.float32)
        self.left *= envelope
        self.right *= envelope

    def knob_per_block(self, knob):
        """The knob sampled once per block, padded with zeros to cover the whole track."""
        block = self.args.block
        block_count = (self.n + block - 1) // block
        sampled = knob[::block][:block_count]
        if sampled.size < block_count:
            sampled = np.concatenate([sampled, np.zeros(block_count - sampled.size, np.float32)])
        return sampled

    def _print_paramq_activity(self, knob_per_block):
        block = self.args.block
        active = int((knob_per_block >= FX.PEAK_KNOB_DEADZONE).sum())
        print("device ParamEq: active in %d/%d blocks (%.1f s), peak knob %d\n"
              % (active, knob_per_block.size, active * block / float(SR), int(knob_per_block.max())))

    def apply_device_paramq(self, knob_per_block):
        args = self.args
        self.left[:], self.right[:] = FX.fx_laser_peak(
            self.left, self.right, block=args.block, knob_per_block=knob_per_block,
            gain_scale=args.peak_gain_scale, max_gain_db=args.peak_max_gain)

    def mix_layered_se(self, folder):
        args, tl, n = self.args, self.tl, self.n
        bank_dir = args.se_bank_dir or os.path.join(os.path.dirname(os.path.dirname(folder)), "sound", "ver5")
        s3p = os.path.join(bank_dir, "general_sampler.s3p")
        if not os.path.exists(s3p):
            print("note: %s not found, skipping layered SE" % s3p)
            return
        bank = load_sample_bank(s3p)
        vgains = s3p_header_gains(os.path.join(os.path.dirname(s3p), "virtical_shot.s3p"))
        if args.slam_gain is not None:
            slam_level = args.slam_gain
        elif args.slam_index < len(vgains):
            slam_level = vgains[args.slam_index] * args.se_trim
        else:
            slam_level = bank[args.slam_index].gain * args.se_trim

        def chip_level(idx):
            return args.se_gain if args.se_gain is not None else bank[idx].gain * args.se_trim

        def play(onsets, sample, level):
            # One voice per sample: a re-trigger cuts the previous one off.
            for k, onset in enumerate(onsets):
                cut_at = onsets[k + 1] if not args.se_polyphonic and k + 1 < len(onsets) else None
                mix_sample_into(self.left, self.right, onset, sample, level, cut_at)

        slam_onsets = []
        for points in self.chart.laser:
            slam_onsets += [sample_index(tl, before.tick) for before, after in zip(points, points[1:])
                            if before.tick == after.tick and abs(before.pos - after.pos) > 1e-6
                            and before.node_type != 2]
        slam_onsets = sorted({o for o in slam_onsets if 0 <= o < n})
        play(slam_onsets, bank[args.slam_index], slam_level)
        counts = collections.Counter({"laser slam @ %.4f" % slam_level: len(slam_onsets)})

        chips = collections.defaultdict(list)
        for label, notes in (("FX-L", self.chart.fx[0]), ("FX-R", self.chart.fx[1])):
            for note in notes:
                idx = note.c2
                if note.length != 0 or not (1 <= idx <= 14) or idx >= len(bank):
                    continue
                onset = sample_index(tl, note.tick)
                if 0 <= onset < n:
                    chips[idx].append(onset)
                    counts["FX chip %d %s (%s) @ %.4f"
                           % (idx, CHIP_SAMPLE_NAMES.get(idx, "?"), label, chip_level(idx))] += 1
        for idx, onsets in chips.items():
            play(sorted(set(onsets)), bank[idx], chip_level(idx))

        print("layered SE:")
        for k in sorted(counts):
            print("  %-40s x%d" % (k, counts[k]))
        print()

    def apply_chain(self, folder):
        """The whole chain in engine order. Returns after the final master gain, ready to write."""
        args = self.args
        if not args.no_fx:
            self.apply_fx_buttons()
        if not args.no_auto_tab:
            self.apply_auto_tab()

        peak_knob, peak_disabled = self.apply_lasers()

        knob_per_block = None
        if not (args.no_laser or args.no_peak):
            knob = self.paramq_knob(peak_knob, peak_disabled)
            if not args.no_duck:
                self.apply_music_duck(knob)
            knob_per_block = self.knob_per_block(knob)
            self._print_paramq_activity(knob_per_block)
        # EQ slot 0 sits on the music path, upstream of the SE voices.
        if knob_per_block is not None and not args.peak_post_se:
            self.apply_device_paramq(knob_per_block)
            knob_per_block = None

        if not args.no_se:
            self.mix_layered_se(folder)
        if knob_per_block is not None:
            self.apply_device_paramq(knob_per_block)

        if args.master_gain != 1.0:
            self.left *= args.master_gain
            self.right *= args.master_gain

    def print_summary(self):
        if self.snapped:
            print("grid-locked (phase started before the note):")
            for k in sorted(self.snapped):
                print("  %-34s x%d" % (k, self.snapped[k]))
        print("applied:")
        for k in sorted(self.applied):
            print("  %-34s x%d" % (k, self.applied[k]))
        if self.skipped:
            print("skipped (not implemented):")
            for k in sorted(self.skipped):
                print("  %-34s x%d" % (k, self.skipped[k]))


def build_arg_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="e.g. data/music/2229_kamui_tjhangneil")
    ap.add_argument("-d", "--difficulty", default=None,
                    help="chart suffix: 1n 2a 3e 4i 5m (default: hardest present)")
    ap.add_argument("-a", "--audio", default=None,
                    help="path to the .s3v to render (default: <folder>/<song>.s3v). "
                         "Set this when the chart came from an update that didn't "
                         "reship its (unchanged) audio - see HANDOFF.md item 1")
    ap.add_argument("-o", "--output", default=None,
                    help="output file; the extension picks the container "
                         "(default <song>_fx.ogg). Use a .wav name for a "
                         "lossless render - e.g. when scoring against the "
                         "capture with spectral_metric.py")
    ap.add_argument("--ogg-quality", type=float, default=6,
                    help="libvorbis -q:a for .ogg output, -1..10 (default 6, "
                         "~192 kbps). Ignored for .wav")
    ap.add_argument("-b", "--block", type=int, default=512,
                    help="per-block coefficient/LFO update size in frames "
                         "(the engine uses the audio callback size; 512 measured "
                         "closest against a capture)")
    ap.add_argument("--wobble-persist", action="store_true",
                    help="diagnostic: carry Wobble's LFO counter across notes "
                         "instead of restarting it at each one. The wrapper "
                         "zeroes the counter per note (0x1806329eb), so this is "
                         "the wrong model - it exists to A/B the difference")
    ap.add_argument("--no-grid-snap", action="store_true",
                    help="diagnostic: start grid-locked effects at the note "
                         "instead of at the previous grid boundary. The engine "
                         "snaps (FUN_18062e310), so this is the wrong model - it "
                         "exists to A/B the difference. See audio_engine.md 5.2")
    ap.add_argument("--tapestop-ex-floor", type=float, default=FX.TAPESTOP_EX_FLOOR,
                    help="level Tape Stop Ex's envelope ramps up FROM, 0..1 "
                         "(default %(default)g). The engine keeps this in a "
                         "struct field nothing was traced to, so it is the one "
                         "fitted number in that effect rather than a "
                         "transcribed one - see audio_engine.md 4.6b")
    ap.add_argument("--wobble-legacy-period", action="store_true",
                    help="diagnostic: treat Wobble's C6 as a period in beats "
                         "rather than a rate in cycles per beat. The wrapper "
                         "takes its reciprocal, so this is the wrong model - it "
                         "exists to A/B the difference")
    ap.add_argument("--gate-hard-binary", action="store_true",
                    help="diagnostic: Gate as a plain 50%% duty cycle instead "
                         "of the transcribed 16-entry pattern table (audio_engine.md 9.3)")
    ap.add_argument("--bitcrush-continuous", action="store_true",
                    help="diagnostic: BitCrusher's hold grid runs once across "
                         "the whole segment instead of realigning every block "
                         "(audio_engine.md 9.3)")
    ap.add_argument("--laser-easing", action="store_true",
                    help="diagnostic: apply the laser's C7 curve type to the "
                         "knob value, not just linear interpolation of "
                         "position (audio_engine.md 9.3)")
    ap.add_argument("--tapestop-ex-3phase", action="store_true",
                    help="diagnostic: model Tape Stop Ex as attack/hold/release "
                         "instead of this project's preroll/spin-up "
                         "(audio_engine.md 9.3)")
    ap.add_argument("--no-param-assign-sweep", action="store_true",
                    help="skip #TAB PARAM ASSIGN INFO's laser-driven parameter "
                         "sweep on #TRACK AUTO TAB spans (a C4=6 laser drives "
                         "one parameter of the borrowed effect). On by default: "
                         "+0.698 dB mean over 16 charts, 5 improved/3 worsened/8 "
                         "unaffected (audio_engine.md 9.5)")
    ap.add_argument("--no-tapestop-ex", action="store_true",
                    help="diagnostic: leave Tape Stop Ex (.vox id 10) notes dry, "
                         "which is what this renderer did before 4.6b was "
                         "transcribed. Exists to A/B the implementation")
    ap.add_argument("--no-pitchshift", action="store_true",
                    help="diagnostic: leave Pitch Shift (.vox id 9) notes dry, "
                         "which is what this renderer did before 4.10 was "
                         "transcribed. Exists to A/B the implementation")
    ap.add_argument("--laser-chain-overlap", action="store_true",
                    help="diagnostic: let a second laser run read what the "
                         "first one wrote, so VOL-L and VOL-R stack. The engine "
                         "snapshots its source once before dispatching any run "
                         "(FUN_18062ef70), so this is the wrong model - it "
                         "doubles every overlapping laser. Exists to A/B it")
    ap.add_argument("--fx-chain-overlap", action="store_true",
                    help="diagnostic: let a second FX-button note read what the "
                         "first one wrote, instead of the dry track. The engine "
                         "restores the generator's source between notes "
                         "(FUN_18062e3d0), so this is the wrong model - it "
                         "doubles every simultaneous FX-L/FX-R hold. Exists to "
                         "A/B the difference")
    ap.add_argument("--fx-order-rl", action="store_true",
                    help="diagnostic: process FX-R before FX-L, so FX-L wins "
                         "where the two overlap. Which note the engine puts "
                         "last is the order of the list at gen+0x20, which was "
                         "not traced")
    ap.add_argument("--no-pitch-speed", action="store_true",
                    help="diagnostic: leave composite kind 14 (.vox id 13) "
                         "notes dry, which is what this renderer did before "
                         "4.11. Worth having: the parameter contract is "
                         "transcribed but the phase vocoder underneath is a "
                         "stand-in for PhaseGear, not a transcription of it")
    ap.add_argument("--pitchshift-legacy-cursor", action="store_true",
                    help="diagnostic: advance Pitch Shift's input cursor by a "
                         "running TOTAL of hops rather than the current pass's "
                         "hop, an early misreading of the disassembly that "
                         "makes the read position accelerate through a held "
                         "note. Measured -0.8 dB against the default over 8 "
                         "charts; kept only to reproduce that (audio_engine.md 4.10)")
    ap.add_argument("--no-auto-tab", action="store_true",
                    help="skip #TRACK AUTO TAB spans, where a laser borrows an "
                         "FX-button effect pair (33.8%% of charts use this). "
                         "Applying them is worth +1.07 dB over these spans and "
                         "helped on 11 of 11 charts measured, so it is on by "
                         "default - but note the paired #TAB PARAM ASSIGN INFO "
                         "parameter sweep is still unimplemented, so borrowed "
                         "effects run at their authored parameters only")
    ap.add_argument("--no-fx", action="store_true", help="skip FX-button effects")
    ap.add_argument("--no-laser", action="store_true", help="skip laser effects")
    ap.add_argument("--dry", default=None,
                    help="also write the untouched decode here; the extension "
                         "picks the container, same as --output")
    ap.add_argument("--no-se", action="store_true",
                    help="skip the layered hit sounds (laser slams / FX chips)")
    ap.add_argument("--se-bank-dir", default=None,
                    help="directory holding general_sampler.s3p and virtical_shot.s3p "
                         "(default: <folder>/../../sound/ver5, i.e. resolved relative "
                         "to the chart the same way the game install lays it out). Set "
                         "this when `folder` comes from an update that does not carry "
                         "the sample bank itself")
    ap.add_argument("--se-gain", type=float, default=None,
                    help="override the level for FX chip samples. By default each "
                         "sample uses the gain in its own S3V0 header (-13.00 dB "
                         "-> 0.2239 for general_sampler[2..13]) times --se-trim")
    ap.add_argument("--se-trim", type=float, default=1.2,
                    help="global multiplier on every header-derived SE gain "
                         "(default %(default)g). This is the one fudge factor left: "
                         "the headers put the slam at 0.5513 but the capture fits "
                         "best at ~0.69, and the ~2 dB between them is unexplained "
                         "(specs/audio_engine.md 6.1.4). Set 1.0 to hear exactly what the files say")
    ap.add_argument("--peak-delay", type=float, default=PEAK_DELAY,
                    help="seconds the knob value lags before it reaches the device "
                         "ParamEq (default %g, the engine's queue threshold)"
                         % PEAK_DELAY)
    ap.add_argument("--duck-rate", type=float, default=None,
                    help="diagnostic: chase the music-voice duck at this many gain "
                         "units per second instead of applying it instantly (the old "
                         "model used %g, the voice's fade rate)" % FX.PEAK_DUCK_RAMP)
    ap.add_argument("--peak-always", action="store_true",
                    help="diagnostic: run the device ParamEq during every laser, "
                         "not only C4 = 0 ones")
    ap.add_argument("--peak-post-se", action="store_true",
                    help="diagnostic: run the device ParamEq after the layered SE are "
                         "mixed in. Measurably wrong - EQ slot 0 sits on the music "
                         "path, upstream of where the SE voices join")
    ap.add_argument("--duck-hold", action="store_true",
                    help="diagnostic: freeze the music-voice duck target while no "
                         "laser is on the queue, instead of letting it return to "
                         "unity. FUN_1805c7a00 only runs when GameAudio::Update "
                         "case 3 pops an entry, so between lasers the engine may "
                         "never re-target")
    ap.add_argument("--no-duck", action="store_true",
                    help="skip the music-voice gain the game applies alongside the "
                         "default laser EQ")
    ap.add_argument("--laser-mode", choices=("chain", "dry", "add"), default="chain",
                    help="how laser effects combine with FX-button output: chain = "
                         "laser processes the FX result (default); dry = laser "
                         "processes the dry track and overwrites; add = both process "
                         "dry and their deltas are summed")
    ap.add_argument("--mix-scale", type=float, default=1.0,
                    help="diagnostic: multiply every effect's wet/dry mix parameter")
    ap.add_argument("--no-stage-clip", action="store_true",
                    help="keep full float precision between effect stages instead of "
                         "round-tripping through int16 as the engine does")
    ap.add_argument("--no-peak", action="store_true",
                    help="skip the default (C4=0) laser peak filter")
    ap.add_argument("--peak-gain-scale", type=float, default=1.0,
                    help="NOT authentic - multiplies the default laser EQ's resonant "
                         "boost (default %(default)g; the transcribed engine value is "
                         "1.0, up to +15 dB - pass --peak-gain-scale 1.0 for that). The "
                         "default peak filter can produce a loud, distracting 'whoosh' "
                         "at some knob positions; this tames it for listening comfort. "
                         "Everything in specs/audio_engine.md §7.1/§9 was measured at "
                         "1.0 - see that section's 'deliberate deviation' note")
    ap.add_argument("--peak-max-gain", type=float, default=15,
                    help="NOT authentic - hard ceiling in dB on the default laser EQ's "
                         "boost (default %(default)g dB; the transcribed engine is "
                         "unclamped up to +15 dB - pass --peak-max-gain 15 to disable "
                         "the cap in practice). Applied after --peak-gain-scale")
    ap.add_argument("--filter-resonance-scale", type=float, default=1.0,
                    help="NOT authentic - fraction of the resonant boost to keep on "
                         "every LPF/HPF that takes a chart Q, laser (#TAB EFFECT INFO "
                         "types 1-2) and FX-button (ids 11-12) alike. An RBJ filter "
                         "peaks at 20*log10(Q) dB at its cutoff, so 0.5 halves that "
                         "figure in dB and 0 removes the resonance entirely. The "
                         "engine always runs the authored Q (default %(default)g). "
                         "Half the corpus's laser filters are authored at Q 3 or 5, "
                         "i.e. +9.5 or +14 dB, which is the loud sweep 'whoosh'; this "
                         "is the LPF/HPF twin of --peak-gain-scale. Does not touch "
                         "Wobble, whose filter carries its own makeup gain")
    ap.add_argument("--filter-max-resonance", type=float, default=99.0,
                    help="NOT authentic - hard ceiling in dB on that same resonant "
                         "boost (default %(default)g dB; the engine is uncapped - pass "
                         "--filter-max-resonance 99 for that). This is the flag that "
                         "tames the sweep 'whoosh' by default: it pulls the corpus's "
                         "two loud presets (Q 3 = +9.5 dB, Q 5 = +14.0 dB) down to one "
                         "ceiling while leaving Q <= 2 untouched, where "
                         "--filter-resonance-scale would thin every filter "
                         "proportionally. Applied after --filter-resonance-scale. The "
                         "boost is authentic and capping it costs 0.157 dB against the "
                         "cabinet corpus - see specs/audio_engine.md 4.1b")
    ap.add_argument("--master-gain", type=float, default=1.0,
                    help="output gain before the hard clip (the game's "
                         "CGainWithHardLimiter stage). Use e.g. 0.9 to buy headroom")
    ap.add_argument("--se-polyphonic", action="store_true",
                    help="diagnostic: let overlapping slam samples sum instead of "
                         "cutting each one off at the next slam. The engine holds one "
                         "voice per (bank, index), so a re-trigger restarts it - "
                         "polyphonic layering is measurably wrong (1.889 vs 1.858)")
    ap.add_argument("--slam-index", type=int, default=0,
                    help="which virtical_shot sample a laser slam plays (0 or 1). The "
                         "engine takes it from the scheduled event, so it is authored "
                         "upstream; 0 is what this chart's capture matches")
    ap.add_argument("--slam-gain", type=float, default=None,
                    help="override the level for the laser slam sample. By default "
                         "it is virtical_shot[N]'s own header gain (-5.17 dB -> "
                         "0.5513 for index 0) times --se-trim")
    return ap


def pick_vox_filename(folder, difficulty):
    voxes = sorted(f for f in os.listdir(folder) if f.endswith(".vox"))
    if not voxes:
        raise SystemExit("no .vox in " + folder)
    if difficulty:
        pick = [v for v in voxes if v.endswith("_%s.vox" % difficulty)]
        if not pick:
            raise SystemExit("no chart for difficulty " + difficulty)
        return pick[0]
    return next((v for d in ("5m", "4i", "3e", "2a", "1n") for v in voxes if v.endswith("_%s.vox" % d)),
                voxes[0])


def print_effect_tables(chart, fxdefs, tabdefs):
    print("format: v%s   BPM %s   %d FX defs, %d laser defs\n"
          % (chart.version, ", ".join("%g" % b for _, b in chart.tl.bpm_pts), len(fxdefs), len(tabdefs)))
    print("FX definitions in this chart (each is a pair, applied in series):")
    for i, pair in enumerate(fxdefs):
        desc = " + ".join("%s(%s)" % (FX_NAMES.get(int(e[0]), "?"), ", ".join("%g" % v for v in e[1:]))
                          for e in pair if e) or "(empty)"
        print("  [%2d] %s" % (i, desc))
    print("laser definitions:")
    for i, e in enumerate(tabdefs):
        print("  [%2d] type %-2d %-18s %s" % (i, int(e[0]), TAB_NAMES.get(int(e[0]), "?"),
                                              ", ".join("%g" % v for v in e[1:])))
    print()


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    folder = os.path.abspath(args.folder)
    base = os.path.basename(folder)
    vox_name = pick_vox_filename(folder, args.difficulty)
    s3v = args.audio or os.path.join(folder, base + ".s3v")
    if not os.path.exists(s3v):
        raise SystemExit("missing " + s3v)

    out = args.output or (base + "_fx.ogg")
    print("chart : %s" % vox_name)
    print("audio : %s" % os.path.basename(s3v))
    left, right = decode_audio(s3v, what="track")
    if args.dry:
        write_audio(args.dry, left, right, SR, args.ogg_quality)
    print("track : %d frames (%.2f s) @ %d Hz" % (left.size, left.size / float(SR), SR))

    chart = vox.load(os.path.join(folder, vox_name))
    render = Render(args, chart, left, right)
    print_effect_tables(chart, render.fxdefs, render.tabdefs)

    render.apply_chain(folder)
    write_audio(out, left, right, SR, args.ogg_quality)
    render.print_summary()
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
