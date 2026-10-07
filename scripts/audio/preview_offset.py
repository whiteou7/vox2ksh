#!/usr/bin/env python3
"""Finds a song's _pre.s3v preview inside the full track by cross-correlation, to fill the po= and plength= header fields (specs/notes.md). `--patch` fills them into charts that already exist. `--music` can be repeated, and this install's data/music is always searched last, so use it for batches converted from an update folder.

    python preview_offset.py 0001_albida_muryoku 2229_kamui_tjhangneil
    python preview_offset.py --patch <converted-folder> --music <game folder>/data/music --dry-run
"""

import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "shared"))
from game_paths import find_ffmpeg, MUSIC

RATE = 11025
MIN_NCC = 0.5
PRE_SUFFIX = "_pre.s3v"
LENGTH_QUANTUM = 10

BOM = b"\xef\xbb\xbf"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def pre_path(s3v_path):
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
    ns, nc = len(song), len(clip)
    n = 1
    while n < ns + nc:
        n *= 2
    num = np.fft.irfft(np.fft.rfft(song, n) * np.conj(np.fft.rfft(clip, n)), n)[:ns - nc + 1]
    csum = np.concatenate(([0.0], np.cumsum(song * song)))
    energy = csum[nc:nc + len(num)] - csum[:len(num)]
    return num / (np.sqrt(np.maximum(energy, 1e-9)) * max(np.linalg.norm(clip), 1e-9))


def measure(s3v_path, pre_s3v_path=None, min_ncc=MIN_NCC):
    r = locate(s3v_path, pre_s3v_path, min_ncc)
    return None if r is None else (r[0], r[1])


def locate(s3v_path, pre_s3v_path=None, min_ncc=MIN_NCC):
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


def _split_header(raw):
    lines = raw.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().lstrip(BOM) == b"--":
            return lines, i
    return lines, len(lines)


def read_header(ksh_path):
    lines, end = _split_header(open(ksh_path, "rb").read())
    out = {}
    for line in lines[:end]:
        text = line.decode("utf-8", "replace").lstrip("\ufeff").strip()
        if "=" in text:
            k, v = text.split("=", 1)
            out[k] = v
    return out


def patch_header(ksh_path, po, plength):
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
                bom = lines[i][:len(lines[i]) - len(body)]
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


def _resolve(arg):
    if arg.lower().endswith(".s3v"):
        return arg
    d = arg if os.path.isdir(arg) else os.path.join(MUSIC, arg)
    return os.path.join(d, os.path.basename(os.path.normpath(d)) + ".s3v")


USAGE = ("usage: python preview_offset.py <song-folder | song.s3v> [...]\n"
         "       python preview_offset.py --patch <converted-folder> [--music DIR] [--dry-run]")


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
        music_dirs.append(MUSIC)
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
