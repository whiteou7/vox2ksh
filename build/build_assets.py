#!/usr/bin/env python3
"""Stage the assets a frozen build needs but the source tree doesn't ship:
the SE sample bank and an ffmpeg binary. Run this before build.py / PyInstaller.

    python build/build_assets.py [--game PATH] [--ffmpeg PATH]

--game defaults to scripts/shared/_paths.GAME (i.e. this repo's own `..` -
the game install this checkout sits inside, same resolution every other
script here uses). --ffmpeg defaults to whatever scripts/shared/_paths.py's
find_ffmpeg() locates (PATH, then a winget install).

What gets copied, and why it's OK to ship despite this project otherwise
never redistributing game data (README.md: "will not provide the
location to get it"):

    gui/assets/sound/ver5/{general_sampler,virtical_shot}.{s3p,def}
        The layered-SE sample bank (laser slams, FX chip hits) - shared
        engine furniture, not song content, and small (this is what
        HANDOFF.md item 1 asked the app to decide; the answer here is
        "ship it, since it's not song data"). Copied as-is, still
        ASF/WMA-encoded inside the .s3p - apply_chart.py already decodes
        them the same way it decodes a chart's own .s3v, no separate
        decode step needed at build time.

    gui/assets/ffmpeg/ffmpeg.exe
        A third-party binary, not this project's or the game's - only
        redistribute a build whose license permits it (a vanilla/"shared"
        LGPL build, not one with GPL-only codecs enabled unless you've
        checked that's fine for your distribution). This script copies
        whatever `--ffmpeg` / auto-detection finds; verify that build's
        license yourself before shipping it.

Never copied: data/music (charts/audio - the actual song content),
data/others/music_db.xml, or anything else identifying a specific game
install. The app requires the user to point it at their own copy of those,
same as the scripts always have.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "shared"))
import _paths  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui", "assets")

SOUND_FILES = [
    ("sound/ver5/general_sampler.s3p", "sound", "ver5", "general_sampler.s3p"),
    ("sound/ver5/general_sampler.def", "sound", "ver5", "general_sampler.def"),
    ("sound/ver5/virtical_shot.s3p", "sound", "ver5", "virtical_shot.s3p"),
    ("sound/ver5/virtical_shot.def", "sound", "ver5", "virtical_shot.def"),
]


def stage_sound_bank(game_dir, assets_dir):
    dst_dir = os.path.join(assets_dir, "sound", "ver5")
    os.makedirs(dst_dir, exist_ok=True)
    missing = []
    for label, *rel in SOUND_FILES:
        src = os.path.join(game_dir, "data", *rel)
        dst = os.path.join(assets_dir, *rel)
        if not os.path.exists(src):
            missing.append(src)
            continue
        shutil.copyfile(src, dst)
        print("staged %s (%d bytes)" % (label, os.path.getsize(dst)))
    if missing:
        print("WARNING: missing from %s/data:" % game_dir)
        for m in missing:
            print("  " + m)
        print("The build will still work, but a game/update folder that doesn't "
              "reship the SE bank itself will render without layered SE.")
    return not missing


def stage_ffmpeg(ffmpeg_path, assets_dir):
    if not ffmpeg_path or not os.path.exists(ffmpeg_path):
        print("WARNING: no ffmpeg.exe found/given - the build will need one on the "
              "user's PATH at runtime. Pass --ffmpeg to bundle one.")
        return False
    dst_dir = os.path.join(assets_dir, "ffmpeg")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "ffmpeg.exe")
    shutil.copyfile(ffmpeg_path, dst)
    print("staged ffmpeg.exe (%d bytes) from %s" % (os.path.getsize(dst), ffmpeg_path))
    print("Reminder: only redistribute an ffmpeg build whose license permits it.")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default=_paths.GAME, help="game install to copy the SE bank from "
                                                          "(default: %(default)s)")
    ap.add_argument("--ffmpeg", default=_paths.find_ffmpeg(), help="ffmpeg.exe to bundle "
                                                                     "(default: auto-detected)")
    ap.add_argument("--out", default=ASSETS, help="asset staging dir (default: gui/assets)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    ok_sound = stage_sound_bank(args.game, args.out)
    ok_ffmpeg = stage_ffmpeg(args.ffmpeg, args.out)
    print()
    print("done. sound bank: %s, ffmpeg: %s" % ("OK" if ok_sound else "MISSING",
                                                  "OK" if ok_ffmpeg else "MISSING"))


if __name__ == "__main__":
    main()
