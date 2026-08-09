#!/usr/bin/env python3
"""
Render a real SOUND VOLTEX chart's audio effects onto its track.

Reads a `.vox` chart + the matching `.s3v` audio, then applies every FX-button
effect and every laser (knob) effect at the exact times the chart specifies,
using the DSP in sdvx_fx.py (reverse engineered from soundvoltex.dll).

    python apply_chart.py <song folder> [-d 5m] [-o out.ogg]

The .s3v is a plain ASF/WMA stream; ffmpeg decodes it to 44100 Hz 16-bit stereo.
Decoding and encoding both go through pipes - no intermediate files are written.
Output defaults to .ogg (Vorbis); the -o extension picks the container, so pass a
.wav name when you need a lossless render - scoring against the capture with
metric.py is the case that wants one.

Chart -> DSP parameter conversions (all verified against the DLL's wrappers):
    Retrigger / Echo   length  is in BEATS      -> sec = beats * 60/BPM
    Gate               period  is in BEATS      -> sec = beats * 60/BPM
    Side Chain         period  is in BEATS      -> sec = beats * 60/BPM
    Wobble             period  is in BEATS      -> sec = beats * 60/BPM
    Flanger            period  is in MEASURES   -> rate = measures / secPerMeasure
    Tape Stop          duration is already in SECONDS (no conversion)
    Bit Crusher        rate is a raw sample count (no conversion)
"""

import argparse
import collections
import os
import shutil
import struct
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sdvx_fx as FX

TICKS_PER_BEAT = 48          # max tick seen in every shipped chart is 47
SR = FX.SR


# --------------------------------------------------------------------------
# .vox parsing
# --------------------------------------------------------------------------

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
    """'004,02,27' -> absolute tick (measure/beat are 1-based)."""
    m, b, t = (int(x) for x in s.split(","))
    return (m - 1, b - 1, t)


class Timeline:
    """measure/beat/tick <-> seconds, honouring BPM and time-signature changes."""

    def __init__(self, sec):
        self.beats = []          # (measure0, num, den)
        for line in sec.get("#BEAT INFO", []):
            f = line.split()
            mm = parse_pos(f[0])[0]
            self.beats.append((mm, int(f[1]), int(f[2])))
        if not self.beats:
            self.beats = [(0, 4, 4)]
        self.beats.sort()

        self.bpms = []           # (measure0, beat0, tick, bpm)
        for line in sec.get("#BPM INFO", []):
            f = line.split()
            mm, bb, tt = parse_pos(f[0])
            self.bpms.append((mm, bb, tt, float(f[1])))
        if not self.bpms:
            raise SystemExit("chart has no #BPM INFO")
        self.bpms.sort()

        # cumulative ticks at the start of each measure
        self._measure_tick = {}
        acc, mi = 0, 0
        for meas in range(0, 2000):
            while mi + 1 < len(self.beats) and self.beats[mi + 1][0] <= meas:
                mi += 1
            self._measure_tick[meas] = acc
            num, den = self.beats[mi][1], self.beats[mi][2]
            acc += int(num * (4.0 / den) * TICKS_PER_BEAT)

        # BPM changes as absolute ticks, plus the elapsed seconds at each
        self._bpm_pts = []
        for (mm, bb, tt, bpm) in self.bpms:
            self._bpm_pts.append((self.abs_tick(mm, bb, tt), bpm))
        self._bpm_pts.sort()
        self._bpm_sec = [0.0]
        for i in range(1, len(self._bpm_pts)):
            dt = self._bpm_pts[i][0] - self._bpm_pts[i - 1][0]
            spb = 60.0 / self._bpm_pts[i - 1][1]
            self._bpm_sec.append(self._bpm_sec[-1] + dt / TICKS_PER_BEAT * spb)

    def abs_tick(self, m0, b0, t):
        return self._measure_tick[m0] + b0 * TICKS_PER_BEAT + t

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
        return self._bpm_sec[i] + (tick - tk) / TICKS_PER_BEAT * (60.0 / bpm)

    def samples(self, tick):
        return int(round(self.seconds(tick) * SR))

    def timesig_num(self, tick):
        """The raw #BEAT INFO numerator in force at `tick`.

        The engine multiplies samplesPerBeat by this numerator verbatim
        (`imul ecx, r11d` in FUN_18062e310), so it is the numerator, not the
        num*(4/den) beat count that beats_per_measure returns.
        """
        num = self.beats[0][1]
        for (mm, n, _d) in self.beats:
            if self._measure_tick.get(mm, 0) <= tick:
                num = n
            else:
                break
        return num

    def grid_anchor(self, tick):
        """Sample position the musical grid is measured from.

        FUN_18062e310 walks the BPM list and the time-signature list, and takes
        whichever change is *later* (`cmp r10d, r8d ; cmovle r10d, r8d`). The
        grid restarts at that point rather than at the start of the song.
        """
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
    """#FXBUTTON EFFECT INFO is 12 *pairs* of lines, and each pair is a pair of
    effects applied in series - the dispatcher FUN_18062e3d0 loops its sub-index
    over {0, 1} and runs both, chaining the second onto the first's output.

    Skipping the all-zero second lines (as an earlier version did) happens to give
    the right answer only while every pair's second line is empty; on a chart that
    uses the second slot it both loses that effect and shifts every later index.
    """
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


def parse_effects(sec, key):
    """Rows of #FXBUTTON EFFECT INFO / #TAB EFFECT INFO -> [[type, p1, ...], ...]"""
    out = []
    for line in sec.get(key, []):
        parts = [p.strip() for p in line.split(",") if p.strip() != ""]
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if not vals or all(v == 0 for v in vals):
            continue       # the all-zero "second line" of each FX definition
        out.append(vals)
    return out


# --------------------------------------------------------------------------
# chart -> DSP parameter translation
# --------------------------------------------------------------------------

FX_NAMES = {
    1: "Retrigger", 2: "Gate", 3: "Flanger", 4: "TapeStop", 5: "SideChain",
    6: "Wobble", 7: "BitCrusher", 8: "Echo(RetriggerEx)", 9: "PitchShift",
    10: "TapeStopEx", 11: "LowPassFilter", 12: "HighPassFilter", 13: "kind14",
}
TAB_NAMES = {1: "LowPassFilter", 2: "HighPassFilter", 3: "BitCrusher"}

# The default laser "peak filter" is not a per-note effect: it is one parametric
# EQ living in the sound device, driven by whichever laser is further along its
# sweep. Delay before the knob value reaches it, in seconds (FUN_180407200 pops
# its queue only once the head entry is older than this).
PEAK_DELAY = 0.08

# how a laser effect combines with what the FX buttons wrote: chain | dry | add
MODE = ["chain"]

# The engine's scratch plane is int16, not float: FUN_18063dc40 writes every
# effect's result back as clamped, truncated int16 before the next stage reads
# it (FUN_18063d9e0). Staying in float end-to-end lets levels run past full
# scale that the game would have clipped off at each stage.
STAGE_CLIP = [True]


def stage(a):
    """One pass through the engine's int16 scratch buffer."""
    if not STAGE_CLIP[0]:
        return a
    return np.trunc(np.clip(a, -32768.0, 32767.0)).astype(np.float32)

# #TRACK2/#TRACK7 C2 on a *chip* note: index into general_sampler. 0 = no sample.
CHIP_SAMPLE_NAMES = {
    1: "big snare (quiet)", 2: "big clap", 3: "short clap", 4: "big snare",
    5: "short snare", 6: "crash", 7: "kick+crash+downlifter", 8: "open hi-hat",
    9: "kick+crash alt", 10: "snare+click", 11: 'female "oh"', 12: 'male "hey"',
    13: 'male "yeah"', 14: "fireworks",
}


# Effect types whose phase is locked to the musical grid rather than to the note.
# Established by xref, not assumed: FUN_18062e310 has exactly three call sites in
# the DLL, and only ONE of them is in an FX wrapper - 0x1806310e5, inside the
# Retrigger wrapper 0x180630fa0. The Echo/RetriggerEx wrapper (0x180631390) calls
# the shared DSP at 0x1806316a7 with no snap, and so does every other wrapper.
# See audio_engine.md 5.2.
GRID_LOCKED = {1}


def grid_snap_offset(tl, tick, length_beats):
    """FUN_18062e310: how far into its period grid an effect start sits.

        samplesPerBeat = trunc(2646000 / BPM)          # 2646000 = 44100*60
        samplesPerMeasure = samplesPerBeat * timeSigNumerator
        period = trunc(samplesPerBeat * lengthBeats)
        offset = ((pos - anchor) % samplesPerMeasure) % period
        if offset > period - 512: offset = 0           # snap forward when close

    The wrapper then starts the effect at `pos - offset`, so the repeat cycle is
    aligned to the song's grid and a note that begins mid-cycle joins it partway
    through - including replaying audio from before the note.
    """
    pos = tl.samples(tick)
    bpm = tl.bpm_at(tick)
    spb = int(2646000.0 / bpm)              # truncating divide, as the engine does
    spm = spb * tl.timesig_num(tick)
    period = int(spb * float(length_beats))
    if spm <= 0 or period <= 0:
        return 0
    off = ((pos - tl.grid_anchor(tick)) % spm) % period
    return 0 if off > period - 512 else off


# Persistent per-effect DSP state, keyed by .vox effect type.
#
# The engine keeps these counters as members of one long-lived object - Wobble's
# LFO lives at this+0x238 and is written back every block - so they run on across
# notes instead of restarting at each one. There is one counter per effect type,
# not per chart definition or per note, which is why this is keyed by type.
# Cleared per render in main(). See audio_engine.md 4.9.
FXSTATE = {}
PERSIST = {6}           # effect types whose state is threaded (6 = Wobble)


MIXSCALE = [1.0]        # diagnostic: scale every effect's wet/dry mix parameter


def _mx(v):
    return v * MIXSCALE[0]


def run_fx(L, R, eff, tl, tick, block, knob=None):
    """Apply one #FXBUTTON effect definition. Returns (L, R) or None if unsupported."""
    t = int(eff[0])
    p = list(eff[1:])
    # position of the mix% field differs per effect type
    mixidx = {1: 1, 8: 1, 6: 2}.get(t, 0)
    if mixidx < len(p):
        p[mixidx] = _mx(p[mixidx])
    bpm = tl.bpm_at(tick)
    spb = 60.0 / bpm                        # seconds per beat
    spm = spb * tl.beats_per_measure(tick)  # seconds per measure

    if t in (1, 8):                                     # Retrigger / Echo
        cnt, mix, ln, fb, gt, rel = int(p[0]), p[1], p[2], p[3], p[4], p[5]
        return FX.fx_retrigger(L, R, mix, ln * spb, fb, cnt, gt, rel, block=block)
    if t == 2:                                          # Gate
        mix, steps, per = p[0], int(p[1]), p[2]
        return FX.fx_gate(L, R, mix, steps, per * spb, block=block)
    if t == 3:                                          # Flanger
        mix, delay_ms, per_meas, depth, stages = p[0], p[1], p[2], int(p[3]), p[4]
        return FX.fx_flanger(L, R, mix, delay_ms, per_meas / spm, depth, stages,
                             block=block)
    if t == 4:                                          # Tape Stop (seconds!)
        return FX.fx_tapestop(L, R, p[0], p[1], p[2], block=block)
    if t == 5:                                          # Side Chain
        mix, per, a, h, rl = p[0], p[1], int(p[2]), int(p[3]), int(p[4])
        return FX.fx_sidechain(L, R, mix, per * spb, a, h, rl, block=block)
    if t == 6:                                          # Wobble
        ftype, wtype, mix, fa, fb_, per, q = (int(p[0]), int(p[1]), p[2],
                                              p[3], p[4], p[5], p[6])
        return FX.fx_wobble(L, R, mix, ftype, wtype, fa, fb_, per * spb, q,
                            block=block,
                            state=FXSTATE.setdefault(t, {}) if t in PERSIST else None)
    if t == 7:                                          # Bit Crusher
        return FX.fx_bitcrush(L, R, p[0], int(p[1]), block=block)
    if t == 11:                                         # Low Pass Filter
        return FX.fx_laser_lpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block)
    if t == 12:                                         # High Pass Filter
        return FX.fx_laser_hpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block)
    return None                                         # 9, 10, 13 -> not implemented


def run_tab(L, R, eff, knob, block):
    t = int(eff[0])
    p = list(eff[1:])
    p[0] = _mx(p[0])
    if t == 1:
        return FX.fx_laser_lpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block)
    if t == 2:
        return FX.fx_laser_hpf(L, R, p[0], p[1], p[2], p[3], knob=knob, block=block)
    if t == 3:
        return FX.fx_laser_bitcrush(L, R, p[0], p[1], knob=knob, block=block)
    return None


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------

def s3v_gain(hdr):
    """Engine gain for one S3V0 entry, from its 32-byte header.

    +0x14 and +0x16 are two int16 in **8.8 fixed-point decibels**. The bank loader
    (0x1805ce7b0) sums them, divides by 256 for the fixed point and by 20 for the
    decibels, and calls powf(10, .) - then writes the result to the voice's mixer
    connection (VoiceImpl::vtable+0xd0 -> MixerConnectionImpl::vtable+0x20 =
    0x1802fbf40, a single `movss [conn+0x20]`). Set once at bank-load time and never
    touched again, which is why it is invisible from the Play/SetVolume side.

    This is the only per-sample level the engine applies. README 6.1.4.
    """
    if hdr[:4] != b"S3V0":
        return 1.0
    g0, g1 = struct.unpack_from("<hh", hdr, 0x14)
    return 10.0 ** (((g0 + g1) / 256.0) / 20.0)


def s3p_gains(path):
    """Per-sample engine gains from an S3P0 container, without decoding any audio."""
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
    """Konami S3P0 container -> list of (name, L, R, gain) at 44100 Hz.

    Layout: 'S3P0', u32 count, then count * (u32 offset, u32 size). Each entry is
    'S3V0', u32 headerSize, u32 payloadSize, u32 checksum, u32, i16 gain, i16 trim,
    u32, i16 pan, ... then an ASF/WMA stream at +headerSize. `gain` is the level the
    engine plays that sample at - see s3v_gain.
    """
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
    """Add one SE sample into the track at frame `pos` (no clipping here;
    the int16 writeback clamps, exactly as the game's mixer output does).

    `cut` truncates the sample there. The sound manager holds ONE voice per
    (bank, sample index) - FUN_1805c6ec0 calls Start on banks[b].voices[i] - so
    re-triggering the same sample restarts that voice instead of layering a
    second copy. Passing the next onset as `cut` reproduces that.
    """
    name, sl, sr, _ = sample
    n = min(sl.size, L.size - pos)
    if cut is not None:
        n = min(n, max(0, cut - pos))
    if n <= 0:
        return
    L[pos:pos + n] += sl[:n] * gain
    R[pos:pos + n] += sr[:n] * gain


def find_ffmpeg():
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


def decode_audio(src=None, blob=None, what="audio"):
    """Decode anything ffmpeg can read to float32 L/R at SR, in memory.

    `src` is a path, `blob` is the encoded bytes (fed on stdin - the ASF/WMA
    payloads inside an .s3p are slices of a larger file, so they have no path
    of their own). Returns the raw int16 magnitudes as float32, the same
    +-32768 domain the engine's own scratch buffers use.
    """
    ff = find_ffmpeg()
    if not ff:
        raise SystemExit("ffmpeg not found - needed to decode the %s (ASF/WMA)" % what)
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error",
         "-i", src if blob is None else "pipe:0",
         "-f", "s16le", "-ar", str(SR), "-ac", "2", "pipe:1"],
        input=blob, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise SystemExit("ffmpeg failed to decode the %s:\n%s"
                         % (what, r.stderr.decode("utf8", "replace").strip()))
    d = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32).reshape(-1, 2)
    return d[:, 0].copy(), d[:, 1].copy()


def encode_pcm(frames, out, sr, quality=6):
    """Encode raw interleaved 16-bit stereo PCM to `out` via ffmpeg's stdin.

    The extension picks the container; only .ogg (Vorbis) is given an explicit
    codec, anything else is left to ffmpeg's default for that container. Fed
    through a pipe rather than a temp file - the engine writeback already
    produces exactly the bytes ffmpeg wants as -f s16le.
    """
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
        subprocess.run(cmd, input=frames.tobytes(), check=True)
    except subprocess.CalledProcessError:
        raise SystemExit("ffmpeg failed to encode %s (is libvorbis available in "
                         "this build?). Write a .wav instead." % os.path.basename(out))
    return out


def write_audio(path, L, R, sr, quality=6):
    """Write the render to `path`; the extension picks the container.

    The int16 writeback is the engine's own output stage (FUN_18063dc40), so it
    always happens - a lossy container is applied on top of it, never instead.
    """
    if os.path.splitext(path)[1].lower() == ".wav":
        FX.write_wav(path, L, R, sr)
        return path
    return encode_pcm(FX.writeback(L, R), path, sr, quality)


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="e.g. data/music/2229_kamui_tjhangneil")
    ap.add_argument("-d", "--difficulty", default=None,
                    help="chart suffix: 1n 2a 3e 4i 5m (default: hardest present)")
    ap.add_argument("-o", "--output", default=None,
                    help="output file; the extension picks the container "
                         "(default <song>_fx.ogg). Use a .wav name for a "
                         "lossless render - e.g. when scoring against the "
                         "capture with metric.py")
    ap.add_argument("--ogg-quality", type=float, default=10,
                    help="libvorbis -q:a for .ogg output, -1..10 (default 6, "
                         "~192 kbps). Ignored for .wav")
    ap.add_argument("-b", "--block", type=int, default=512,
                    help="per-block coefficient/LFO update size in frames "
                         "(the engine uses the audio callback size; 512 measured "
                         "closest against a capture)")
    ap.add_argument("--no-persist", action="store_true",
                    help="diagnostic: restart each effect's internal counter at "
                         "every note instead of resuming. The engine keeps them "
                         "in object members, so this is the wrong model - it "
                         "exists to A/B the difference")
    ap.add_argument("--no-grid-snap", action="store_true",
                    help="diagnostic: start grid-locked effects at the note "
                         "instead of at the previous grid boundary. The engine "
                         "snaps (FUN_18062e310), so this is the wrong model - it "
                         "exists to A/B the difference. See audio_engine.md 5.2")
    ap.add_argument("--no-fx", action="store_true", help="skip FX-button effects")
    ap.add_argument("--no-laser", action="store_true", help="skip laser effects")
    ap.add_argument("--dry", default=None,
                    help="also write the untouched decode here; the extension "
                         "picks the container, same as --output")
    ap.add_argument("--no-se", action="store_true",
                    help="skip the layered hit sounds (laser slams / FX chips)")
    ap.add_argument("--se-gain", type=float, default=None,
                    help="override the level for FX chip samples. By default each "
                         "sample uses the gain in its own S3V0 header (-13.00 dB "
                         "-> 0.2239 for general_sampler[2..13]) times --se-trim")
    ap.add_argument("--se-trim", type=float, default=1.25,
                    help="global multiplier on every header-derived SE gain "
                         "(default %(default)g). This is the one fudge factor left: "
                         "the headers put the slam at 0.5513 but the capture fits "
                         "best at ~0.69, and the ~2 dB between them is unexplained "
                         "(README 6.1.4). Set 1.0 to hear exactly what the files say")
    ap.add_argument("--peak-delay", type=float, default=PEAK_DELAY,
                    help="seconds the knob value lags before it reaches the device "
                         "ParamEq (default %g, the engine's queue threshold)"
                         % PEAK_DELAY)
    ap.add_argument("--duck-rate", type=float, default=FX.PEAK_DUCK_RAMP,
                    help="how fast the music-voice gain chases its target, in gain "
                         "units per second (default %g)" % FX.PEAK_DUCK_RAMP)
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
    args = ap.parse_args()

    MODE[0] = args.laser_mode
    STAGE_CLIP[0] = not args.no_stage_clip
    MIXSCALE[0] = args.mix_scale
    if args.no_persist:
        PERSIST.clear()
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

    s3v = os.path.join(folder, base + ".s3v")
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
    FXSTATE.clear()          # persistent DSP counters are per-render


    # The FX dispatcher (FUN_18062e3d0) chains its two buttons by swapping the
    # generator's source pointer to the partial result... but on the way out it
    # RESTORES the source to the original track:
    #     if (1 < lVar19) { puVar5 = *param_1; *puVar5 = param_2; ... }
    # The laser dispatcher FUN_18062ea60 then runs against that restored source
    # and memcpy's its result over the destination. So lasers read the DRY track
    # and OVERWRITE whatever the FX buttons wrote - the two stages do not stack.
    dryL, dryR = L.copy(), R.copy()

    # ---------------- FX buttons: TRACK2 = FX-L, TRACK7 = FX-R --------------
    if not args.no_fx:
        for trk, label in (("#TRACK2", "FX-L"), ("#TRACK7", "FX-R")):
            for line in sec.get(trk, []):
                f = line.split()
                if len(f) < 3:
                    continue
                length, ev = int(f[1]), int(f[2])
                if length <= 0 or ev < 2:
                    continue                       # chip note, or "no effect"
                di = ev - 2                        # the DLL does param[4] - 2
                if di >= len(fxdefs):
                    continue
                t0 = tl.tick_of(f[0])
                i0, i1 = tl.samples(t0), tl.samples(t0 + length)
                i0, i1 = max(0, i0), min(n, i1)
                if i1 - i0 < 16:
                    continue
                # both halves of the pair, chained, as the dispatcher does
                for eff in fxdefs[di]:
                    if eff is None:
                        continue
                    # Grid-locked effects start their phase at the previous grid
                    # boundary, which is BEFORE the note - so feed the DSP that
                    # much extra audio and keep only the part the note covers.
                    snap = 0
                    if (not args.no_grid_snap and int(eff[0]) in GRID_LOCKED
                            and len(eff) > 3):
                        snap = grid_snap_offset(tl, t0, eff[3])
                    j0 = max(0, i0 - snap)
                    pre = i0 - j0
                    res = run_fx(L[j0:i1].copy(), R[j0:i1].copy(), eff, tl, t0,
                                 args.block)
                    name = FX_NAMES.get(int(eff[0]), "?")
                    if res is None:
                        skipped[name] = skipped.get(name, 0) + 1
                        continue
                    L[i0:i1], R[i0:i1] = stage(res[0][pre:]), stage(res[1][pre:])
                    key = "%s (%s)" % (name, label)
                    applied[key] = applied.get(key, 0) + 1
                    if snap:
                        snapped[key] = snapped.get(key, 0) + 1

    # ---------------- lasers: TRACK1 = VOL-L, TRACK8 = VOL-R ----------------
    #
    # The engine builds ONE event per consecutive point pair, then groups
    # events into runs that are contiguous AND share the same effect index
    # (FUN_18062ef70). A run shorter than one audio block is dropped by the
    # wrapper (`if (blockSize <= duration)`), which is why a laser SLAM - two
    # points on the same tick - contributes a *step* in the knob curve inside a
    # run rather than an effect of its own.
    peak_knob = np.zeros(n, np.float32)     # device-EQ knob, 0..127, per sample
    peak_off = np.zeros(n, bool)            # a laser with C4 != 0 mutes the EQ
    if not args.no_laser:
        for trk, label in (("#TRACK1", "VOL-L"), ("#TRACK8", "VOL-R")):
            pts = []
            for line in sec.get(trk, []):
                f = line.split()
                if len(f) < 7:
                    continue
                tick = tl.tick_of(f[0])
                pos = float(f[1])
                if pos > 1.0:                      # format v10 stores 0..127
                    pos /= 127.0
                flag = int(f[2])
                # C4 is the laser effect. (C7 is the *curve type* - using it here
                # was a bug: it ranges 0..5 too, so it looked plausible.)
                #   0     : peak filter (the SDVX default laser sound)
                #   1..5  : index into #TAB EFFECT INFO, 1-indexed
                #   6     : no effect
                filt = int(f[4])
                pts.append((tick, pos, flag, filt))
            pts.sort(key=lambda x: (x[0],))

            # one event per adjacent pair, not crossing a section end (flag 2)
            events = []
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                if a[2] == 2:
                    continue
                events.append((a[0], b[0], a[1], b[1], a[3]))

            # group into runs: contiguous in time and same filter index
            runs = []
            for e in events:
                if runs and runs[-1][-1][1] == e[0] and runs[-1][-1][4] == e[4]:
                    runs[-1].append(e)
                else:
                    runs.append([e])

            # Rasterise the knob feed for the device ParamEq. This is global, not
            # per run: FUN_180407200 case 3 keeps ONE accumulator per tick and
            # takes max(effective position) over every laser event, where the
            # effective position is `pos` for VOL-L and `1 - pos` for VOL-R.
            mir = (label == "VOL-R")
            for (ta, tb, pa, pb, ef) in events:
                i0, i1 = max(0, tl.samples(ta)), min(n, tl.samples(tb))
                if i1 <= i0:
                    continue
                va = (1.0 - pa if mir else pa) * 127.0
                vb = (1.0 - pb if mir else pb) * 127.0
                seg = np.linspace(va, vb, i1 - i0, endpoint=False, dtype=np.float32)
                np.maximum(peak_knob[i0:i1], seg, out=peak_knob[i0:i1])
                if ef != 0:
                    peak_off[i0:i1] = True

            for run in runs:
                _apply_run(L, R, dryL, dryR, run, tabdefs, tl, args.block,
                           applied, skipped, label, n)

    # ---------------- the default laser sound: one device-level ParamEq -----
    #
    # FUN_180407200 case 3 accumulates max(effective laser position) per tick,
    # queues it, and 80 ms later hands it to FUN_1805c7a00, which looks the knob
    # up in the 128-entry centre-frequency table at DAT_18090c050 and writes a
    # _DSFXParamEq into slot 0 of the device's EQ array (FUN_180626b30). The same
    # call ducks the music voice (bank 2 = the song's own track).
    peak_kb = None
    if not (args.no_laser or args.no_peak):
        knob = peak_knob.copy()
        if not args.peak_always:
            knob[peak_off] = 0.0               # C4 != 0 -> the game mutes the EQ
        d = int(round(args.peak_delay * sr))
        if d > 0:
            knob = np.concatenate([np.zeros(d, np.float32), knob[:-d]])

        if not args.no_duck:
            # voice target gain, reached at PEAK_DUCK_RAMP gain-units per second
            tgt = np.array([FX.peak_duck_target(v) for v in
                            knob[::args.block].astype(np.int32)], np.float64)
            step = args.duck_rate * args.block / float(sr)
            g = np.empty_like(tgt)
            cur = 1.0
            kb = knob[::args.block].astype(np.int32)
            for i, t in enumerate(tgt):
                if args.duck_hold and kb[i] < FX.PEAK_KNOB_DEADZONE:
                    g[i] = cur                 # no laser event -> no call -> target frozen
                    continue
                cur += max(-step, min(step, t - cur))
                g[i] = cur
            env = np.repeat(g, args.block)[:n].astype(np.float32)
            L *= env
            R *= env

        # per-block knob, sampled the way the game's per-callback update does
        nb = (n + args.block - 1) // args.block
        peak_kb = knob[::args.block][:nb]
        if peak_kb.size < nb:
            peak_kb = np.concatenate([peak_kb, np.zeros(nb - peak_kb.size, np.float32)])
        active = int((peak_kb >= FX.PEAK_KNOB_DEADZONE).sum())
        print("device ParamEq: active in %d/%d blocks (%.1f s), peak knob %d\n"
              % (active, nb, active * args.block / float(sr), int(peak_kb.max())))

    if peak_kb is not None and not args.peak_post_se:
        L[:], R[:] = FX.fx_laser_peak(L, R, block=args.block, knob_per_block=peak_kb)
        peak_kb = None

    # ---------------- layered SE: laser slams and FX chip notes -------------
    #
    # These are NOT produced by the effect engine - they are samples the game
    # mixes on top of the track from data/sound/ver5/general_sampler.s3p:
    #   index 0  fs00_virtical_se01  -> laser slam
    #   index 2..14 fs02_shot01..fs14_shot13 -> FX chip notes
    # An FX chip's 3rd chart column selects the sample; 255 / -1 means "default".
    if not args.no_se:
        s3p = os.path.join(os.path.dirname(os.path.dirname(folder)),
                           "sound", "ver5", "general_sampler.s3p")
        if not os.path.exists(s3p):
            print("note: %s not found, skipping layered SE" % s3p)
        else:
            samples = load_s3p(s3p)
            se_counts = collections.Counter()

            # Each sample carries its own level in its S3V0 header (README 6.1.4).
            # The slam is played out of bank 0xd = virtical_shot, not out of the
            # general_sampler copy loaded above - the audio is byte-identical but
            # the two banks give index 1 *different* header gains, so read the
            # slam's level from the bank the engine actually plays it from.
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

            # laser slams: two points on the same tick with different positions
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
                    pts.append((tl.tick_of(f[0]), pos))
                pts.sort(key=lambda x: (x[0],))
                onsets = [tl.samples(pts[i][0]) for i in range(len(pts) - 1)
                          if pts[i][0] == pts[i + 1][0]
                          and abs(pts[i][1] - pts[i + 1][1]) > 1e-6]
                slam_onsets.extend(onsets)

            slam_onsets = sorted(set(o for o in slam_onsets if 0 <= o < n))
            for k, p in enumerate(slam_onsets):
                cut = slam_onsets[k + 1] if (not args.se_polyphonic
                                             and k + 1 < len(slam_onsets)) else None
                mix_in(L, R, p, samples[args.slam_index], slam_level, cut)
            se_counts["laser slam @ %.4f" % slam_level] += len(slam_onsets)

            # FX chip notes. C2 names the sample directly, and **0 means no sample**
            # - which is the overwhelmingly common case. There is no "default".
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
            # Same one-voice rule as the slams (6.1.2), but keyed per sample index:
            # bank 9 holds a separate voice per index, so two *different* chips do
            # layer, while a repeat of the *same* chip restarts its voice.
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

    if peak_kb is not None:      # --peak-post-se only
        L[:], R[:] = FX.fx_laser_peak(L, R, block=args.block, knob_per_block=peak_kb)

    # Output stage, matching BMSoundLib2017::CGainWithHardLimiter (0x18069f090):
    # multiply by a gain, then hard-clip to +-limit. No knee, no lookahead - the
    # shipped game really does just clip, which is why it can mix SE hot.
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


def _apply_run(L, R, dryL, dryR, run, tabdefs, tl, block, applied, skipped, label, n):
    """One contiguous run of laser events that all share the same filter index.

    Reads from the DRY track and overwrites the output, matching the engine -
    see the note in main() about FUN_18062e3d0 restoring the source pointer.
    """
    filt = run[0][4]
    if filt >= 6 or (filt > 0 and (filt - 1) >= len(tabdefs)):
        return                             # 6 = explicitly no effect
    eff = tabdefs[filt - 1] if filt > 0 else None
    t0, t1 = run[0][0], run[-1][1]
    if t1 <= t0:
        return
    i0, i1 = max(0, tl.samples(t0)), min(n, tl.samples(t1))
    if i1 - i0 < block:                    # the wrapper needs at least one block
        return

    # knob breakpoints: each event contributes its start, and the run its end.
    # A slam is an event with t_start == t_end, which lands as a step here -
    # exactly what the engine's per-block knob lookup produces.
    # The laser value driving the filter is MIRRORED on one side: the rasteriser
    # FUN_1802409f0 stores either `v` or `1 - v` depending on which laser it is.
    # Confirmed against a capture: with VOL-L raw and VOL-R mirrored, the measured
    # peak-filter centre frequency rises monotonically for both.
    mir = (label == "VOL-R")

    def kv(v):
        return (1.0 - v if mir else v) * 127.0

    base = tl.seconds(t0)
    knob = []
    for (ta, tb, pa, pb, _f) in run:
        knob.append((max(tl.seconds(ta) - base, 0.0), kv(pa)))
    knob.append((max(tl.seconds(run[-1][1]) - base, 0.0), kv(run[-1][3])))

    # Which signal does a laser effect read, and how does its result combine with
    # what the FX buttons already wrote? Three models, see audio_engine.md 8.1 -
    # the disassembly points at "dry", the capture prefers "chain", and "chain"
    # is what ships.
    if MODE[0] == "chain":
        srcL, srcR = L[i0:i1].copy(), R[i0:i1].copy()
    else:
        srcL, srcR = dryL[i0:i1].copy(), dryR[i0:i1].copy()

    if filt == 0:
        # C4 = 0 selects no SVO effect at all: FUN_18062ea60 keys its map on
        # noteField[4] - 1, so 0 lands on the "kind 0 = nothing" sentinel. The
        # audible default laser sound is the device ParamEq, applied globally in
        # main() rather than here.
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
