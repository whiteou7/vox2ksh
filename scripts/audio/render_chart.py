#!/usr/bin/env python3
"""Applies a chart's FX holds and lasers to its .s3v. Also does the device ParamEq, the music duck and the layered SE bank. `--help` lists the flags that switch off parts of the chain, each explained in specs/audio_engine.md section 6.

    python render_chart.py ../data/music/2229_kamui_tjhangneil -d 5m -o output/kamui_fx.ogg
"""

import argparse
import collections
import math
import os
import shutil
import struct
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fx_dsp as FX

DEFAULT_TICKS_PER_BEAT = 48
TICKS_PER_BEAT = DEFAULT_TICKS_PER_BEAT
SR = FX.SR


def read_sections(path):
    txt = open(path, "r", encoding="cp932", errors="replace").read()
    out, cur = {}, None
    for line in txt.splitlines():
        ls = line.strip()
        if ls.startswith("//"):
            continue
        if ls.startswith("#END"):
            cur = None
            continue
        if ls.startswith("#"):
            cur = ls
            out.setdefault(cur, [])
            continue
        if cur is not None and ls:
            out[cur].append(ls)
    return out


def parse_pos(s):
    m, b, t = (int(x) for x in s.split(","))
    return (m - 1, b - 1, t)


class Timeline:
    def __init__(self, sec, res=None):
        if res is None:
            rl = sec.get("#BEAT RESOLUTION")
            res = int(rl[0].strip()) if rl else DEFAULT_TICKS_PER_BEAT
        self.res = int(res)

        self.beats = []
        for line in sec.get("#BEAT INFO", []):
            f = line.split()
            mm = parse_pos(f[0])[0]
            self.beats.append((mm, int(f[1]), int(f[2])))
        if not self.beats:
            self.beats = [(0, 4, 4)]
        self.beats.sort()

        self.bpms = []
        for line in sec.get("#BPM INFO", []):
            f = line.split()
            mm, bb, tt = parse_pos(f[0])
            self.bpms.append((mm, bb, tt, float(f[1])))
        if not self.bpms:
            raise SystemExit("chart has no #BPM INFO")
        self.bpms.sort()

        self._measure_tick = {}
        self._measure_cpb = {}
        acc, mi = 0, 0
        for meas in range(0, 2000):
            while mi + 1 < len(self.beats) and self.beats[mi + 1][0] <= meas:
                mi += 1
            self._measure_tick[meas] = acc
            num, den = self.beats[mi][1], self.beats[mi][2]
            cpb = int(round((4.0 / den) * self.res))
            self._measure_cpb[meas] = cpb
            acc += num * cpb

        self._bpm_pts = []
        for (mm, bb, tt, bpm) in self.bpms:
            self._bpm_pts.append((self.abs_tick(mm, bb, tt), bpm))
        self._bpm_pts.sort()
        self._bpm_sec = [0.0]
        for i in range(1, len(self._bpm_pts)):
            dt = self._bpm_pts[i][0] - self._bpm_pts[i - 1][0]
            spb = 60.0 / self._bpm_pts[i - 1][1]
            self._bpm_sec.append(self._bpm_sec[-1] + dt / self.res * spb)

    def abs_tick(self, m0, b0, t):
        return self._measure_tick[m0] + b0 * self._measure_cpb[m0] + t

    def tick_of(self, poss):
        return self.abs_tick(*parse_pos(poss))

    def bpm_at(self, tick):
        bpm = self._bpm_pts[0][1]
        for (tk, v) in self._bpm_pts:
            if tk <= tick:
                bpm = v
            else:
                break
        return bpm

    def beats_per_measure(self, tick):
        meas = 0
        for m, tk in sorted(self._measure_tick.items()):
            if tk <= tick:
                meas = m
            else:
                break
        num, den = 4, 4
        for (mm, n, d) in self.beats:
            if mm <= meas:
                num, den = n, d
        return num * (4.0 / den)

    def seconds(self, tick):
        i = 0
        for k, (tk, _) in enumerate(self._bpm_pts):
            if tk <= tick:
                i = k
            else:
                break
        tk, bpm = self._bpm_pts[i]
        return self._bpm_sec[i] + (tick - tk) / self.res * (60.0 / bpm)

    def samples(self, tick):
        return int(round(self.seconds(tick) * SR))

    def timesig_num(self, tick):
        num = self.beats[0][1]
        for (mm, n, _d) in self.beats:
            if self._measure_tick.get(mm, 0) <= tick:
                num = n
            else:
                break
        return num

    def grid_anchor(self, tick):
        a = 0
        for (tk, _bpm) in self._bpm_pts:
            if tk <= tick:
                a = max(a, self.samples(tk))
            else:
                break
        for (mm, _n, _d) in self.beats:
            tk = self._measure_tick.get(mm, 0)
            if tk <= tick:
                a = max(a, self.samples(tk))
            else:
                break
        return a


def parse_fx_pairs(sec):
    rows = []
    for line in sec.get("#FXBUTTON EFFECT INFO", []):
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        try:
            rows.append([float(p) for p in parts])
        except ValueError:
            pass
    pairs = []
    for i in range(0, len(rows) - 1, 2):
        a, b = rows[i], rows[i + 1]
        pairs.append([a if a and a[0] != 0 else None,
                      b if b and b[0] != 0 else None])
    return pairs


def parse_param_assign(sec):
    out = collections.defaultdict(list)
    for line in sec.get("#TAB PARAM ASSIGN INFO", []):
        parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip() != ""]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) < 4:
            continue
        pair = int(vals[0])
        out[pair].append((int(vals[1]), vals[2], vals[3]))
    return out


def param_assign_curve(sec, tl, n):
    values = np.zeros(n, np.float32)
    active = np.zeros(n, bool)
    for trk, mir in (("#TRACK1", False), ("#TRACK8", True)):
        pts = []
        for line in sec.get(trk, []):
            f = line.split()
            if len(f) < 7:
                continue
            tick = tl.tick_of(f[0])
            pos = float(f[1])
            if pos > 1.0:
                pos /= 127.0
            pts.append((tick, pos, int(f[2]), int(f[4])))
        pts.sort(key=lambda x: x[0])
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a[2] == 2 or a[3] != 6:
                continue
            i0, i1 = max(0, tl.samples(a[0])), min(n, tl.samples(b[0]))
            if i1 <= i0:
                continue
            va = (1.0 - a[1]) if mir else a[1]
            vb = (1.0 - b[1]) if mir else b[1]
            seg = np.linspace(va, vb, i1 - i0, endpoint=False, dtype=np.float32)
            cur = values[i0:i1]
            upd = (~active[i0:i1]) | (seg > cur)
            cur[upd] = seg[upd]
            active[i0:i1][upd] = True
    return values, active


def parse_effects(sec, key):
    out = []
    for line in sec.get(key, []):
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if not vals or all(v == 0 for v in vals):
            continue
        out.append(vals)
    return out


FX_NAMES = {
    1: "Retrigger", 2: "Gate", 3: "Flanger", 4: "TapeStop", 5: "SideChain",
    6: "Wobble", 7: "BitCrusher", 8: "Echo(RetriggerEx)", 9: "PitchShift",
    10: "TapeStopEx", 11: "LowPassFilter", 12: "HighPassFilter",
    13: "PitchSpeed",
}
TAB_NAMES = {1: "LowPassFilter", 2: "HighPassFilter", 3: "BitCrusher"}

PEAK_DELAY = 0.08

MODE = ["chain"]

STAGE_CLIP = [True]


def stage(a):
    if not STAGE_CLIP[0]:
        return a
    return np.trunc(np.clip(a, -32768.0, 32767.0)).astype(np.float32)


CHIP_SAMPLE_NAMES = {
    1: "big snare (quiet)", 2: "big clap", 3: "short clap", 4: "big snare",
    5: "short snare", 6: "crash", 7: "kick+crash+downlifter", 8: "open hi-hat",
    9: "kick+crash alt", 10: "snare+click", 11: 'female "oh"', 12: 'male "hey"',
    13: 'male "yeah"', 14: "fireworks",
}


GRID_LOCKED = {1}


def grid_snap_offset(tl, tick, length_beats):
    pos = tl.samples(tick)
    bpm = tl.bpm_at(tick)
    spb = int(2646000.0 / bpm)
    spm = spb * tl.timesig_num(tick)
    period = int(spb * float(length_beats))
    if spm <= 0 or period <= 0:
        return 0
    off = ((pos - tl.grid_anchor(tick)) % spm) % period
    return 0 if off > period - 512 else off


FXSTATE = {}
PERSIST = set()


MIXSCALE = [1.0]

PITCHSHIFT = [True]

PITCHSHIFT_LEGACY_CURSOR = [False]

TAPESTOP_EX = [True]

PITCH_SPEED = [True]

WOBBLE_LEGACY = [False]

GATE_HARD_BINARY = [False]
BITCRUSH_CONTINUOUS = [False]
LASER_EASING = [False]
TAPESTOP_EX_3PHASE = [False]
PARAM_ASSIGN_SWEEP = [True]
PARAM_ASSIGN_BLOCK = 512

RES_SCALE = [1.0]
RES_MAX_DB = [6.0]


def _laser_ease(phase, curve):
    if curve == 4:
        return math.sin(phase * math.pi / 2.0)
    if curve == 5:
        return math.sin((phase - 1.0) * math.pi / 2.0) + 1.0
    return phase


TSE_FLOOR = [FX.TAPESTOP_EX_FLOOR]


def _mx(v):
    return v * MIXSCALE[0]


def run_fx(L, R, eff, tl, tick, block, knob=None, lookahead=None):
    t = int(eff[0])
    p = list(eff[1:])
    mixidx = {1: 1, 8: 1, 6: 2}.get(t, 0)
    if mixidx < len(p):
        p[mixidx] = _mx(p[mixidx])
    bpm = tl.bpm_at(tick)
    spb = 60.0 / bpm
    spm = spb * tl.beats_per_measure(tick)

    if t in (1, 8):
        cnt, mix, ln, fb, gt, rel = int(p[0]), p[1], p[2], p[3], p[4], p[5]
        return FX.fx_retrigger(L, R, mix, ln * spb, fb, cnt, gt, rel, block=block)
    if t == 2:
        mix, steps, per = p[0], int(p[1]), p[2]
        return FX.fx_gate(L, R, mix, steps, per * spb, block=block,
                          hard_binary=GATE_HARD_BINARY[0])
    if t == 3:
        mix, delay_ms, per_meas, depth, stages = p[0], p[1], p[2], int(p[3]), p[4]
        return FX.fx_flanger(L, R, mix, delay_ms, per_meas / spm, depth, stages,
                             block=block)
    if t == 4:
        return FX.fx_tapestop(L, R, p[0], p[1], p[2], block=block)
    if t == 5:
        mix, per, a, h, rl = p[0], p[1], int(p[2]), int(p[3]), int(p[4])
        return FX.fx_sidechain(L, R, mix, per * spb, a, h, rl, block=block)
    if t == 6:
        ftype, wtype, mix, fa, fb_, rate, q = (int(p[0]), int(p[1]), p[2],
                                               p[3], p[4], p[5], p[6])
        period = (float(rate) * spb if WOBBLE_LEGACY[0]
                  else spb / max(float(rate), 1e-6))
        return FX.fx_wobble(L, R, mix, ftype, wtype, fa, fb_, period, q,
                            block=block,
                            state=FXSTATE.setdefault(t, {}) if t in PERSIST else None)
    if t == 7:
        return FX.fx_bitcrush(L, R, p[0], int(p[1]), block=block,
                              continuous=BITCRUSH_CONTINUOUS[0])
    if t == 9 and PITCHSHIFT[0]:
        return FX.fx_pitchshift(L, R, p[0], p[1], block=block,
                                legacy_cursor=PITCHSHIFT_LEGACY_CURSOR[0])
    if t == 10 and TAPESTOP_EX[0]:
        if TAPESTOP_EX_3PHASE[0]:
            return FX.fx_tapestop_ex_3phase(L, R, p[0], p[1], p[2] * spb, p[3] * spb,
                                            p[4] * spb, block=block, lookahead=lookahead)
        return FX.fx_tapestop_ex(L, R, p[0], p[1], p[2] * spb, p[3] * spb,
                                 p[4] * spb, block=block, lookahead=lookahead,
                                 floor=TSE_FLOOR[0])
    if t == 11:
        return FX.fx_laser_lpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block,
                               res_scale=RES_SCALE[0], res_max_db=RES_MAX_DB[0])
    if t == 12:
        return FX.fx_laser_hpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block,
                               res_scale=RES_SCALE[0], res_max_db=RES_MAX_DB[0])
    if t == 13 and PITCH_SPEED[0]:
        return FX.fx_pitch_speed(L, R, p[0], p[1], p[2], block=block,
                                 lookahead=lookahead)
    return None


def run_tab(L, R, eff, knob, block):
    t = int(eff[0])
    p = list(eff[1:])
    p[0] = _mx(p[0])
    if t == 1:
        return FX.fx_laser_lpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block,
                               res_scale=RES_SCALE[0], res_max_db=RES_MAX_DB[0])
    if t == 2:
        return FX.fx_laser_hpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block,
                               res_scale=RES_SCALE[0], res_max_db=RES_MAX_DB[0])
    if t == 3:
        return FX.fx_laser_bitcrush(L, R, p[0], p[1], knob=knob, block=block)
    return None


def s3v_gain(hdr):
    if hdr[:4] != b"S3V0":
        return 1.0
    g0, g1 = struct.unpack_from("<hh", hdr, 0x14)
    return 10.0 ** (((g0 + g1) / 256.0) / 20.0)


def s3p_gains(path):
    if not os.path.exists(path):
        return []
    data = open(path, "rb").read()
    magic, count = struct.unpack_from("<4sI", data, 0)
    if magic != b"S3P0":
        return []
    out = []
    for i in range(count):
        off, _ = struct.unpack_from("<II", data, 8 + i * 8)
        out.append(s3v_gain(data[off:off + 32]))
    return out


def load_s3p(path):
    names = []
    defp = os.path.splitext(path)[0] + ".def"
    if os.path.exists(defp):
        for line in open(defp):
            p = line.split()
            if len(p) >= 3 and p[0] == "#define":
                names.append(p[1])
    data = open(path, "rb").read()
    magic, count = struct.unpack_from("<4sI", data, 0)
    if magic != b"S3P0":
        raise SystemExit("%s is not an S3P0 container" % path)
    out = []
    for i in range(count):
        off, size = struct.unpack_from("<II", data, 8 + i * 8)
        blob = data[off:off + size]
        hmagic, hsize = struct.unpack_from("<4sI", blob, 0)
        payload = blob[hsize:] if hmagic == b"S3V0" else blob
        l, r = decode_audio(blob=payload, what="SE sample %d of %s"
                            % (i, os.path.basename(path)))
        out.append((names[i] if i < len(names) else "idx%02d" % i, l, r,
                    s3v_gain(blob[:32])))
    return out


def mix_in(L, R, pos, sample, gain, cut=None):
    name, sl, sr, _ = sample
    n = min(sl.size, L.size - pos)
    if cut is not None:
        n = min(n, max(0, cut - pos))
    if n <= 0:
        return
    L[pos:pos + n] += sl[:n] * gain
    R[pos:pos + n] += sr[:n] * gain


def find_ffmpeg():
    env = os.environ.get("FFMPEG")
    if env and os.path.exists(env):
        return env
    for c in ("ffmpeg", "ffmpeg.exe"):
        p = shutil.which(c)
        if p:
            return p
    root = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(root):
        for dp, _, fns in os.walk(root):
            if "ffmpeg.exe" in fns:
                return os.path.join(dp, "ffmpeg.exe")
    return None


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


def write_audio(path, L, R, sr, quality=6):
    if os.path.splitext(path)[1].lower() == ".wav":
        FX.write_wav(path, L, R, sr)
        return path
    return encode_pcm(FX.writeback(L, R), path, sr, quality)


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


def main():
    args = build_arg_parser().parse_args()

    MODE[0] = args.laser_mode
    STAGE_CLIP[0] = not args.no_stage_clip
    MIXSCALE[0] = args.mix_scale
    TAPESTOP_EX[0] = not args.no_tapestop_ex
    TSE_FLOOR[0] = args.tapestop_ex_floor
    PITCHSHIFT[0] = not args.no_pitchshift
    PITCH_SPEED[0] = not args.no_pitch_speed
    PITCHSHIFT_LEGACY_CURSOR[0] = args.pitchshift_legacy_cursor
    WOBBLE_LEGACY[0] = args.wobble_legacy_period
    GATE_HARD_BINARY[0] = args.gate_hard_binary
    BITCRUSH_CONTINUOUS[0] = args.bitcrush_continuous
    LASER_EASING[0] = args.laser_easing
    TAPESTOP_EX_3PHASE[0] = args.tapestop_ex_3phase
    PARAM_ASSIGN_SWEEP[0] = not args.no_param_assign_sweep
    RES_SCALE[0] = args.filter_resonance_scale
    RES_MAX_DB[0] = args.filter_max_resonance
    if args.wobble_persist:
        PERSIST.add(6)
    folder = os.path.abspath(args.folder)
    base = os.path.basename(folder)
    voxes = sorted(f for f in os.listdir(folder) if f.endswith(".vox"))
    if not voxes:
        raise SystemExit("no .vox in " + folder)
    order = ["5m", "4i", "3e", "2a", "1n"]
    if args.difficulty:
        pick = [v for v in voxes if v.endswith("_%s.vox" % args.difficulty)]
        if not pick:
            raise SystemExit("no chart for difficulty " + args.difficulty)
        vox = pick[0]
    else:
        vox = next((v for d in order for v in voxes if v.endswith("_%s.vox" % d)), voxes[0])
    vox_path = os.path.join(folder, vox)

    s3v = args.audio or os.path.join(folder, base + ".s3v")
    if not os.path.exists(s3v):
        raise SystemExit("missing " + s3v)

    out = args.output or (base + "_fx.ogg")
    print("chart : %s" % vox)
    print("audio : %s" % os.path.basename(s3v))
    L, R = decode_audio(s3v, what="track")
    sr = SR
    if args.dry:
        write_audio(args.dry, L, R, sr, args.ogg_quality)
    n = L.size
    print("track : %d frames (%.2f s) @ %d Hz" % (n, n / float(sr), sr))

    sec = read_sections(vox_path)
    tl = Timeline(sec)
    fxdefs = parse_fx_pairs(sec)
    tabdefs = parse_effects(sec, "#TAB EFFECT INFO")
    ver = (sec.get("#FORMAT VERSION") or ["?"])[0].strip()
    print("format: v%s   BPM %s   %d FX defs, %d laser defs\n"
          % (ver, ", ".join("%g" % b for _, b in tl._bpm_pts), len(fxdefs), len(tabdefs)))

    print("FX definitions in this chart (each is a pair, applied in series):")
    for i, pair in enumerate(fxdefs):
        desc = " + ".join("%s(%s)" % (FX_NAMES.get(int(e[0]), "?"),
                                      ", ".join("%g" % v for v in e[1:]))
                          for e in pair if e) or "(empty)"
        print("  [%2d] %s" % (i, desc))
    print("laser definitions:")
    for i, e in enumerate(tabdefs):
        print("  [%2d] type %-2d %-18s %s" % (i, int(e[0]), TAB_NAMES.get(int(e[0]), "?"),
                                              ", ".join("%g" % v for v in e[1:])))
    print()

    applied, skipped, snapped = {}, {}, {}
    FXSTATE.clear()

    dryL, dryR = L.copy(), R.copy()

    if not args.no_fx:
        order = (("#TRACK7", "FX-R"), ("#TRACK2", "FX-L")) if args.fx_order_rl \
            else (("#TRACK2", "FX-L"), ("#TRACK7", "FX-R"))
        for trk, label in order:
            for line in sec.get(trk, []):
                f = line.split()
                if len(f) < 3:
                    continue
                length, ev = int(f[1]), int(f[2])
                if length <= 0 or ev < 2:
                    continue
                di = ev - 2
                if di >= len(fxdefs):
                    continue
                t0 = tl.tick_of(f[0])
                i0, i1 = tl.samples(t0), tl.samples(t0 + length)
                i0, i1 = max(0, i0), min(n, i1)
                if i1 - i0 < 16:
                    continue

                plan = []
                for eff in fxdefs[di]:
                    if eff is None:
                        continue
                    snap = 0
                    if (not args.no_grid_snap and int(eff[0]) in GRID_LOCKED
                            and len(eff) > 3):
                        snap = grid_snap_offset(tl, t0, eff[3])
                    plan.append((eff, snap))
                if not plan:
                    continue

                jmin = max(0, i0 - max(s for _, s in plan))
                srcL, srcR = (L, R) if args.fx_chain_overlap else (dryL, dryR)
                wl, wr = srcL[jmin:i1].copy(), srcR[jmin:i1].copy()

                wrote = False
                for eff, snap in plan:
                    off = max(0, i0 - snap) - jmin
                    res = run_fx(wl[off:].copy(), wr[off:].copy(), eff, tl, t0,
                                 args.block, lookahead=(srcL, srcR, jmin + off))
                    name = FX_NAMES.get(int(eff[0]), "?")
                    if res is None:
                        skipped[name] = skipped.get(name, 0) + 1
                        continue
                    wl[off:], wr[off:] = stage(res[0]), stage(res[1])
                    wrote = True
                    key = "%s (%s)" % (name, label)
                    applied[key] = applied.get(key, 0) + 1
                    if snap:
                        snapped[key] = snapped.get(key, 0) + 1
                if wrote:
                    L[i0:i1], R[i0:i1] = wl[i0 - jmin:], wr[i0 - jmin:]

    assign_table = parse_param_assign(sec) if PARAM_ASSIGN_SWEEP[0] else {}
    assign_curve = assign_val = assign_active = None
    if PARAM_ASSIGN_SWEEP[0]:
        assign_val, assign_active = param_assign_curve(sec, tl, n)

    if not args.no_auto_tab:
        for line in sec.get("#TRACK AUTO TAB", []):
            f = line.split()
            if len(f) < 3:
                continue
            try:
                length, ev = int(f[1]), int(f[2])
            except ValueError:
                continue
            if length <= 0 or ev < 2:
                continue
            di = ev - 2
            if di >= len(fxdefs):
                continue
            t0 = tl.tick_of(f[0])
            i0, i1 = max(0, tl.samples(t0)), min(n, tl.samples(t0 + length))
            if i1 - i0 < 16:
                continue
            for chain_index, eff in enumerate(fxdefs[di]):
                if eff is None:
                    continue
                name = FX_NAMES.get(int(eff[0]), "?")

                assign = None
                if PARAM_ASSIGN_SWEEP[0] and chain_index < len(assign_table.get(di, [])):
                    pidx, lo, hi = assign_table[di][chain_index]
                    if pidx > 0 and pidx < len(eff) and np.any(assign_active[i0:i1]):
                        assign = (pidx, lo, hi)

                if assign is None:
                    snap = 0
                    if (not args.no_grid_snap and int(eff[0]) in GRID_LOCKED
                            and len(eff) > 3):
                        snap = grid_snap_offset(tl, t0, eff[3])
                    j0 = max(0, i0 - snap)
                    pre = i0 - j0
                    res = run_fx(L[j0:i1].copy(), R[j0:i1].copy(), eff, tl, t0,
                                 args.block, lookahead=(L, R, j0))
                    if res is None:
                        skipped[name] = skipped.get(name, 0) + 1
                        continue
                    L[i0:i1], R[i0:i1] = stage(res[0][pre:]), stage(res[1][pre:])
                    key = "%s (AUTO TAB)" % name
                    applied[key] = applied.get(key, 0) + 1
                    continue

                pidx, lo, hi = assign
                any_applied = False
                for bs in range(i0, i1, PARAM_ASSIGN_BLOCK):
                    be = min(bs + PARAM_ASSIGN_BLOCK, i1)
                    blk_active = assign_active[bs:be]
                    blk_eff = eff
                    if np.any(blk_active):
                        v = float(np.mean(assign_val[bs:be][blk_active]))
                        v = max(0.0, min(1.0, v))
                        blk_eff = list(eff)
                        blk_eff[pidx] = lo + (hi - lo) * v
                    res = run_fx(L[bs:be].copy(), R[bs:be].copy(), blk_eff, tl, t0,
                                 args.block, lookahead=(L, R, bs))
                    if res is None:
                        skipped[name] = skipped.get(name, 0) + 1
                        continue
                    L[bs:be], R[bs:be] = stage(res[0]), stage(res[1])
                    any_applied = True
                if any_applied:
                    key = "%s (AUTO TAB sweep)" % name
                    applied[key] = applied.get(key, 0) + 1

    peak_knob = np.zeros(n, np.float32)
    peak_off = np.zeros(n, bool)

    chainL, chainR = (L, R) if args.laser_chain_overlap else (L.copy(), R.copy())
    if not args.no_laser:
        for trk, label in (("#TRACK1", "VOL-L"), ("#TRACK8", "VOL-R")):
            pts = []
            for line in sec.get(trk, []):
                f = line.split()
                if len(f) < 7:
                    continue
                tick = tl.tick_of(f[0])
                pos = float(f[1])
                if pos > 1.0:
                    pos /= 127.0
                flag = int(f[2])
                filt = int(f[4])
                curve = int(f[7]) if len(f) > 7 else 0
                pts.append((tick, pos, flag, filt, curve))
            pts.sort(key=lambda x: (x[0],))

            events = []
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if a[2] == 2:
                    continue
                events.append((a[0], b[0], a[1], b[1], a[3], a[4]))

            runs = []
            for e in events:
                if runs and runs[-1][-1][1] == e[0] and runs[-1][-1][4] == e[4]:
                    runs[-1].append(e)
                else:
                    runs.append([e])

            mir = (label == "VOL-R")
            for (ta, tb, pa, pb, ef, curve) in events:
                i0, i1 = max(0, tl.samples(ta)), min(n, tl.samples(tb))
                if i1 <= i0:
                    continue
                va = (1.0 - pa if mir else pa) * 127.0
                vb = (1.0 - pb if mir else pb) * 127.0
                if LASER_EASING[0] and curve in (4, 5):
                    phase = np.arange(i1 - i0, dtype=np.float64) / max(i1 - i0, 1)
                    eased = np.sin(phase * math.pi / 2.0) if curve == 4 else \
                        np.sin((phase - 1.0) * math.pi / 2.0) + 1.0
                    seg = (va + (vb - va) * eased).astype(np.float32)
                else:
                    seg = np.linspace(va, vb, i1 - i0, endpoint=False, dtype=np.float32)
                np.maximum(peak_knob[i0:i1], seg, out=peak_knob[i0:i1])
                if ef != 0:
                    peak_off[i0:i1] = True

            for run in runs:
                _apply_run(L, R, dryL, dryR, chainL, chainR, run, tabdefs, tl,
                           args.block, applied, skipped, label, n)

    peak_kb = None
    if not (args.no_laser or args.no_peak):
        knob = peak_knob.copy()
        if not args.peak_always:
            knob[peak_off] = 0.0
        d = int(round(args.peak_delay * sr))
        if d > 0:
            knob = np.concatenate([np.zeros(d, np.float32), knob[:-d]])

        if not args.no_duck:
            tgt = np.array([FX.peak_duck_target(v) for v in
                            knob[::args.block].astype(np.int32)], np.float64)
            step = (np.inf if args.duck_rate is None
                    else args.duck_rate * args.block / float(sr))
            g = np.empty_like(tgt)
            cur = 1.0
            kb = knob[::args.block].astype(np.int32)
            for i, t in enumerate(tgt):
                if args.duck_hold and kb[i] < FX.PEAK_KNOB_DEADZONE:
                    g[i] = cur
                    continue
                cur += max(-step, min(step, t - cur))
                g[i] = cur
            env = np.repeat(g, args.block)[:n].astype(np.float32)
            L *= env
            R *= env

        nb = (n + args.block - 1) // args.block
        peak_kb = knob[::args.block][:nb]
        if peak_kb.size < nb:
            peak_kb = np.concatenate([peak_kb, np.zeros(nb - peak_kb.size, np.float32)])
        active = int((peak_kb >= FX.PEAK_KNOB_DEADZONE).sum())
        print("device ParamEq: active in %d/%d blocks (%.1f s), peak knob %d\n"
              % (active, nb, active * args.block / float(sr), int(peak_kb.max())))

    if peak_kb is not None and not args.peak_post_se:
        L[:], R[:] = FX.fx_laser_peak(L, R, block=args.block, knob_per_block=peak_kb,
                                      gain_scale=args.peak_gain_scale,
                                      max_gain_db=args.peak_max_gain)
        peak_kb = None

    if not args.no_se:
        bank_dir = args.se_bank_dir or os.path.join(
            os.path.dirname(os.path.dirname(folder)), "sound", "ver5")
        s3p = os.path.join(bank_dir, "general_sampler.s3p")
        if not os.path.exists(s3p):
            print("note: %s not found, skipping layered SE" % s3p)
        else:
            samples = load_s3p(s3p)
            se_counts = collections.Counter()

            vgains = s3p_gains(os.path.join(os.path.dirname(s3p),
                                            "virtical_shot.s3p"))
            if args.slam_gain is not None:
                slam_level = args.slam_gain
            elif args.slam_index < len(vgains):
                slam_level = vgains[args.slam_index] * args.se_trim
            else:
                slam_level = samples[args.slam_index][3] * args.se_trim

            def chip_level(idx):
                if args.se_gain is not None:
                    return args.se_gain
                return samples[idx][3] * args.se_trim

            slam_onsets = []
            for trk, label in (("#TRACK1", "VOL-L"), ("#TRACK8", "VOL-R")):
                pts = []
                for line in sec.get(trk, []):
                    f = line.split()
                    if len(f) < 7:
                        continue
                    pos = float(f[1])
                    if pos > 1.0:
                        pos /= 127.0
                    pts.append((tl.tick_of(f[0]), pos, int(f[2])))
                pts.sort(key=lambda x: (x[0],))
                onsets = [tl.samples(pts[i][0]) for i in range(len(pts) - 1)
                          if pts[i][0] == pts[i + 1][0]
                          and abs(pts[i][1] - pts[i + 1][1]) > 1e-6
                          and pts[i][2] != 2]
                slam_onsets.extend(onsets)

            slam_onsets = sorted(set(o for o in slam_onsets if 0 <= o < n))
            for k, p in enumerate(slam_onsets):
                cut = slam_onsets[k + 1] if (not args.se_polyphonic
                                             and k + 1 < len(slam_onsets)) else None
                mix_in(L, R, p, samples[args.slam_index], slam_level, cut)
            se_counts["laser slam @ %.4f" % slam_level] += len(slam_onsets)

            chips = collections.defaultdict(list)
            for trk, label in (("#TRACK2", "FX-L"), ("#TRACK7", "FX-R")):
                for line in sec.get(trk, []):
                    f = line.split()
                    if len(f) < 3 or int(f[1]) != 0:
                        continue
                    idx = int(f[2])
                    if not (1 <= idx <= 14) or idx >= len(samples):
                        continue
                    p = tl.samples(tl.tick_of(f[0]))
                    if 0 <= p < n:
                        chips[idx].append(p)
                        se_counts["FX chip %d %s (%s) @ %.4f"
                                  % (idx, CHIP_SAMPLE_NAMES.get(idx, "?"), label,
                                     chip_level(idx))] += 1
            for idx, ps in chips.items():
                ps = sorted(set(ps))
                for k, p in enumerate(ps):
                    cut = ps[k + 1] if (not args.se_polyphonic
                                        and k + 1 < len(ps)) else None
                    mix_in(L, R, p, samples[idx], chip_level(idx), cut)

            print("layered SE:")
            for k in sorted(se_counts):
                print("  %-40s x%d" % (k, se_counts[k]))
            print()

    if peak_kb is not None:
        L[:], R[:] = FX.fx_laser_peak(L, R, block=args.block, knob_per_block=peak_kb,
                                      gain_scale=args.peak_gain_scale,
                                      max_gain_db=args.peak_max_gain)

    if args.master_gain != 1.0:
        L *= args.master_gain
        R *= args.master_gain
    write_audio(out, L, R, sr, args.ogg_quality)

    if snapped:
        print("grid-locked (phase started before the note):")
        for k in sorted(snapped):
            print("  %-34s x%d" % (k, snapped[k]))
    print("applied:")
    for k in sorted(applied):
        print("  %-34s x%d" % (k, applied[k]))
    if skipped:
        print("skipped (not implemented):")
        for k in sorted(skipped):
            print("  %-34s x%d" % (k, skipped[k]))
    print("\nwrote %s" % out)
    return 0


def _apply_run(L, R, dryL, dryR, chainL, chainR, run, tabdefs, tl, block,
               applied, skipped, label, n):
    filt = run[0][4]
    if filt >= 6 or (filt > 0 and (filt - 1) >= len(tabdefs)):
        return
    eff = tabdefs[filt - 1] if filt > 0 else None
    t0, t1 = run[0][0], run[-1][1]
    if t1 <= t0:
        return
    i0, i1 = max(0, tl.samples(t0)), min(n, tl.samples(t1))
    if i1 - i0 < block:
        return

    mir = (label == "VOL-R")

    def kv(v):
        return (1.0 - v if mir else v) * 127.0

    base = tl.seconds(t0)
    knob = []
    for (ta, tb, pa, pb, _f, curve) in run:
        sa = max(tl.seconds(ta) - base, 0.0)
        if LASER_EASING[0] and curve in (4, 5):
            sb = max(tl.seconds(tb) - base, 0.0)
            dur = sb - sa
            nsteps = max(2, int(dur * SR / max(block, 1)))
            for k in range(nsteps):
                phase = _laser_ease(k / float(nsteps), curve)
                knob.append((sa + dur * (k / float(nsteps)), kv(pa) + (kv(pb) - kv(pa)) * phase))
        else:
            knob.append((sa, kv(pa)))
    knob.append((max(tl.seconds(run[-1][1]) - base, 0.0), kv(run[-1][3])))

    if MODE[0] == "chain":
        srcL, srcR = chainL[i0:i1].copy(), chainR[i0:i1].copy()
    else:
        srcL, srcR = dryL[i0:i1].copy(), dryR[i0:i1].copy()

    if filt == 0:
        applied["PeakFilter (%s)" % label] = applied.get("PeakFilter (%s)" % label, 0) + 1
        return
    res = run_tab(srcL, srcR, eff, knob, block)
    name = TAB_NAMES.get(int(eff[0]), "?")
    if res is None:
        skipped[name] = skipped.get(name, 0) + 1
        return

    if MODE[0] == "add":
        L[i0:i1] = stage(L[i0:i1] + res[0] - dryL[i0:i1])
        R[i0:i1] = stage(R[i0:i1] + res[1] - dryR[i0:i1])
    else:
        L[i0:i1], R[i0:i1] = stage(res[0]), stage(res[1])
    key = "%s (%s)" % (name, label)
    applied[key] = applied.get(key, 0) + 1


if __name__ == "__main__":
    sys.exit(main())
