#!/usr/bin/env python3
"""
Where a song's selection-screen preview sits inside the full track.

    python preview.py <song-folder | song.s3v> [...]
    python preview.py --patch <converted-folder> [--music DIR] [--dry-run]

SDVX ships the preview as its own pre-cut file, `<folder>_pre.s3v`, next to the track's `<folder>.s3v`; nothing in `music_db.xml` records where in the song that clip was cut from. `.ksh` wants the opposite representation - one audio file plus a `po=` start offset and a `plength=` window into it (see `specs/ksh_format.md`) - so the offset has to be recovered by finding the clip inside the track.

That is a normalised cross-correlation, and over the whole library (2184 songs scored) the winning lag's median score is 0.973, 5th percentile 0.905, 1st percentile 0.831. Nothing here assumes a clip length: `plength` is measured, because two conventions ship side by side. The common one is ~10 s with a ~0.5 s fade-in and ~1 s fade-out baked in, which is what keeps a good score off 1.0 - the samples between the fades are the track's. The rare one, seen on three recent songs (`2120_hbfs_daffpunk`, `2168_garasuno_kneesormx_korsk`, `2170_icbmoflove_odenpa`), is a ~20 s cut starting at exactly 30.000 s with no fade at all, flat at unity edge to edge; those score 0.995+, the highest in the corpus, precisely because there is no fade to disagree about. Either way `po` is the start of the clip, which is what it should be - KSM fades the preview in itself.

`MIN_NCC = 0.5` guards one failure: a `_pre.s3v` that is not the same audio as this track. That is not always as coarse as a re-recorded long version - a tail of songs ship a preview cut from a *different render* of the same passage, matching in envelope and spectrum but not waveform (`2336_ticktackchikupa_risyuu` scores 0.698, and 0.734 even over the unfaded middle at its exact peak lag, with the spectral centroid matching to 2 Hz). Those still place correctly, which is why the floor is 0.5 rather than up near the 0.83 a 1st percentile suggests. It refuses 6 of the 2184, all under 0.45; refusing is the right answer there, since a wrong offset is worse than none.

It is not a uniqueness test, and `locate()`'s `runner_up` is a diagnostic rather than a second gate - a song with a literally repeated passage scores nearly as well at both (`0785_voltexes3_sota_fujimori`: 0.974 vs 0.950), and there the two lags are the same audio, so either is a correct preview.

The clip is only ever cut on a coarse grid, so 11025 Hz mono (0.09 ms per lag step) is far more resolution than the answer needs, and decoding at that rate keeps a whole song under half a second. This does not reuse apply_chart.decode_audio(): that one is fixed at 44100 Hz stereo because the DSP needs it there, and importing it would drag the whole effect engine into a notes-only conversion for the sake of one ffmpeg call.

`plength` is rounded to 10 ms, which folds WMA decoder padding back out without pretending to a precision the clip doesn't have: 2154 of the 2184 land on 10000, 27 on 9980, and the three long ones on 19970.
"""

import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "shared"))
from _paths import find_ffmpeg, MUSIC

RATE = 11025            # analysis rate, mono - see module docstring
MIN_NCC = 0.5           # below this, report "not found" rather than a lag
PRE_SUFFIX = "_pre.s3v"
LENGTH_QUANTUM = 10     # ms; plength is rounded to this

BOM = b"\xef\xbb\xbf"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW, so a frozen GUI build doesn't flash a console


def pre_path(s3v_path):
    """The `_pre.s3v` beside a track's `.s3v`, or None if it isn't there."""
    if not s3v_path:
        return None
    p = os.path.splitext(s3v_path)[0] + PRE_SUFFIX
    return p if os.path.exists(p) else None


def _decode_mono(path, rate=RATE):
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg not found - needed to decode the preview (ASF/WMA)")
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-i", path,
         "-f", "s16le", "-ar", str(rate), "-ac", "1", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed to decode %s:\n%s"
                           % (os.path.basename(path), r.stderr.decode("utf8", "replace").strip()))
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float64)


def _ncc(song, clip):
    """Normalised cross-correlation of `clip` against every lag in `song`.

    The numerator is the plain FFT correlation; the denominator is the norm of the song window under each lag, taken from a prefix sum of the squares, so a loud passage can't out-score the right one just by being loud.
    """
    ns, nc = len(song), len(clip)
    n = 1
    while n < ns + nc:
        n *= 2
    num = np.fft.irfft(np.fft.rfft(song, n) * np.conj(np.fft.rfft(clip, n)), n)[:ns - nc + 1]
    csum = np.concatenate(([0.0], np.cumsum(song * song)))
    energy = csum[nc:nc + len(num)] - csum[:len(num)]
    return num / (np.sqrt(np.maximum(energy, 1e-9)) * max(np.linalg.norm(clip), 1e-9))


def measure(s3v_path, pre_s3v_path=None, min_ncc=MIN_NCC):
    """(po_ms, plength_ms) for a track, or None if the preview can't be placed.

    None covers every "no answer" case - no `_pre.s3v`, no ffmpeg, a clip that decodes empty or longer than the track it is supposed to come from, and a best correlation under `min_ncc`. Callers write `po=0 plength=0` for all of them; a wrong offset is worse than none.
    """
    r = locate(s3v_path, pre_s3v_path, min_ncc)
    return None if r is None else (r[0], r[1])


def locate(s3v_path, pre_s3v_path=None, min_ncc=MIN_NCC):
    """measure() plus the diagnostics: (po_ms, plength_ms, ncc, runner_up).

    `runner_up` is the best score at least 2 s away from the winner, which is how repetitive a song is rather than how good the answer is - see the module docstring on why it isn't a gate.
    """
    pre = pre_s3v_path or pre_path(s3v_path)
    if not pre or not s3v_path or not os.path.exists(s3v_path):
        return None
    try:
        song = _decode_mono(s3v_path)
        clip = _decode_mono(pre)
    except RuntimeError:
        return None
    if len(clip) == 0 or len(clip) >= len(song):
        return None

    c = _ncc(song, clip)
    k = int(np.argmax(c))
    best = float(c[k])
    guard = 2 * RATE
    rival = c.copy()
    rival[max(0, k - guard):k + guard] = -1.0
    runner_up = float(rival.max()) if rival.size else -1.0
    if best < min_ncc:
        return None

    po = int(round(k * 1000.0 / RATE))
    plength = int(round(len(clip) * 1000.0 / RATE / LENGTH_QUANTUM) * LENGTH_QUANTUM)
    song_ms = int(len(song) * 1000.0 / RATE)
    plength = max(0, min(plength, song_ms - po))
    return po, plength, best, runner_up


# --------------------------------------------------------------------------
# --patch: filling the fields into charts that already exist
# --------------------------------------------------------------------------

def _split_header(raw):
    """`raw` bytes -> (all lines with endings kept, index of the `--` line)."""
    lines = raw.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().lstrip(BOM) == b"--":
            return lines, i
    return lines, len(lines)


def read_header(ksh_path):
    """A `.ksh`'s header as a plain dict - order and duplicates not preserved."""
    lines, end = _split_header(open(ksh_path, "rb").read())
    out = {}
    for line in lines[:end]:
        text = line.decode("utf-8", "replace").lstrip("\ufeff").strip()
        if "=" in text:
            k, v = text.split("=", 1)
            out[k] = v
    return out


def patch_header(ksh_path, po, plength):
    """Rewrite only this file's `po=`/`plength=`, leaving every other byte alone.

    A hand-refined chart is the whole reason this exists rather than a re-conversion, so it edits the two lines in the byte stream instead of re-emitting a header: line endings, the BOM, field order, and any field the charter added or removed all survive untouched. A field that isn't there at all is appended at the end of the header rather than at `notes/convert.py:_header()`'s position for it, since by then the order is the charter's and not ours. Returns True if the file changed.
    """
    raw = open(ksh_path, "rb").read()
    lines, end = _split_header(raw)
    want = [(b"po", str(po).encode()), (b"plength", str(plength).encode())]
    crlf = raw.count(b"\r\n")
    eol = b"\r\n" if crlf and crlf >= raw.count(b"\n") - crlf else b"\n"

    seen = set()
    for i in range(end):
        body = lines[i].lstrip(BOM)
        if b"=" not in body:
            continue
        key = body.split(b"=", 1)[0].strip()
        for k, v in want:
            if key == k:
                seen.add(k)
                bom = lines[i][:len(lines[i]) - len(body)]     # keep the BOM if it led this line
                lines[i] = bom + k + b"=" + v + eol
    for k, v in want:
        if k not in seen:
            lines.insert(end, k + b"=" + v + eol)
            end += 1

    new = b"".join(lines)
    if new == raw:
        return False
    open(ksh_path, "wb").write(new)
    return True


def find_track(folder_name, music_dirs):
    """A converted folder's name -> that song's `.s3v` in the game data, or None.

    `gui/convert_worker.plan_jobs` names an output folder after the song's `ascii`, falling back to the id-prefixed `<id>_<ascii>` only when two songs in one batch share an ascii, so both spellings have to resolve back to the same `<id>_<ascii>` game folder.
    """
    for d in music_dirs:
        if not d or not os.path.isdir(d):
            continue
        exact = os.path.join(d, folder_name, folder_name + ".s3v")
        if os.path.exists(exact):
            return exact
        for name in os.listdir(d):
            head, _, tail = name.partition("_")
            if tail == folder_name and head.isdigit():
                cand = os.path.join(d, name, name + ".s3v")
                if os.path.exists(cand):
                    return cand
    return None


def patch_folder(root, music_dirs, dry_run=False, log=print):
    """Fill `po=`/`plength=` into every already-converted `.ksh` under `root`.

    Measured once per song folder against the game's own `.s3v` rather than per chart against each rendered `.ogg`: the render is sample-aligned with the source (apply_chart.py writes its effects in place over the decoded track), so both give the same lag, but the dry track correlates far better - a heavily effected MXM render can pull an otherwise-fine song under MIN_NCC even where the answer is known good. The local audio named by `m=` is the fallback for when the game folder isn't reachable at all.

    Returns (changed, unchanged, failed) counted in files.
    """
    changed = unchanged = failed = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        kshs = sorted(f for f in filenames if f.lower().endswith(".ksh"))
        if not kshs:
            continue
        name = os.path.basename(os.path.normpath(dirpath))
        s3v = find_track(name, music_dirs)
        source, pre = s3v, pre_path(s3v)
        if source is None:
            m = read_header(os.path.join(dirpath, kshs[0])).get("m", "")
            local = os.path.join(dirpath, m) if m else ""
            if not os.path.exists(local):
                log("!! %s: no game folder and no local audio - %d file(s) left alone"
                    % (name, len(kshs)))
                failed += len(kshs)
                continue
            source, pre = local, None
            log("-- %s: no game folder found, measuring against %s" % (name, m))

        r = locate(source, pre)
        if r is None:
            log("!! %s: preview not placed (no _pre.s3v, or under MIN_NCC) - %d file(s) left alone"
                % (name, len(kshs)))
            failed += len(kshs)
            continue

        po, plength, ncc, runner_up = r
        log("%-34s po=%-8d plength=%-6d ncc=%.3f (next %.3f)" % (name, po, plength, ncc, runner_up))
        for f in kshs:
            path = os.path.join(dirpath, f)
            was = read_header(path)
            if dry_run:
                log("   %-36s po=%s plength=%s -> po=%d plength=%d"
                    % (f, was.get("po"), was.get("plength"), po, plength))
                unchanged += 1
            elif patch_header(path, po, plength):
                changed += 1
            else:
                unchanged += 1
    return changed, unchanged, failed


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _resolve(arg):
    """A song folder name, a folder path, or an .s3v path -> the .s3v path."""
    if arg.lower().endswith(".s3v"):
        return arg
    d = arg if os.path.isdir(arg) else os.path.join(MUSIC, arg)
    return os.path.join(d, os.path.basename(os.path.normpath(d)) + ".s3v")


USAGE = ("usage: python preview.py <song-folder | song.s3v> [...]\n"
         "       python preview.py --patch <converted-folder> [--music DIR] [--dry-run]")


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(USAGE)

    if args[0] == "--patch":
        rest = args[1:]
        dry_run = "--dry-run" in rest
        rest = [a for a in rest if a != "--dry-run"]
        music_dirs, roots = [], []
        i = 0
        while i < len(rest):
            if rest[i] == "--music":
                if i + 1 >= len(rest):
                    raise SystemExit("--music needs a directory")
                music_dirs.append(rest[i + 1])
                i += 2
            else:
                roots.append(rest[i])
                i += 1
        if not roots:
            raise SystemExit(USAGE)
        music_dirs.append(MUSIC)      # the install this checkout sits in, searched last
        for root in roots:
            changed, unchanged, failed = patch_folder(root, music_dirs, dry_run=dry_run)
            print("\n%s: %d changed, %d unchanged, %d left alone%s"
                  % (root, changed, unchanged, failed, "  (dry run)" if dry_run else ""))
        return

    print("%-36s %8s %9s %7s %7s" % ("track", "po_ms", "plength", "ncc", "next"))
    for a in args:
        s3v = _resolve(a)
        name = os.path.splitext(os.path.basename(s3v))[0]
        r = locate(s3v)
        if r is None:
            print("%-36s %8s" % (name, "not found"))
        else:
            print("%-36s %8d %9d %7.3f %7.3f" % (name, r[0], r[1], r[2], r[3]))


if __name__ == "__main__":
    main()
