"""Drives notes/convert.py + apply_chart.py for a batch of (song, difficulty)
jobs on a single background thread.

Both scripts are called in-process (imported, not subprocess'd) - notes
conversion is plain Python and fast; apply_chart.main() is what the CLI's
`__main__` block calls, unchanged, so calling it directly here reproduces
exactly what running the script would do, just without paying interpreter
startup per chart and without needing a second Python bundled into a frozen
build for subprocess use. Its module-level DSP state is reset per render
inside main() itself (FXSTATE.clear(), and every flag/global is re-derived
from args at the top of main()), so repeated in-process calls are safe -
see audio_engine.md 4.9.

Cancellation is cooperative and job-granular: a render already in progress
runs to completion (apply_chart.main() has no internal yield points to hook
into without a much more invasive change - see HANDOFF.md item 2), but the
queue stops before starting the next job. Progress is therefore also
job-granular; within one render, the debug console's streamed stdout is the
only feedback there is.
"""
import io
import os
import shutil
import sys
import threading
import traceback
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  (puts scripts/notes, scripts/audio, scripts/shared on sys.path)
import argspec  # noqa: E402
import music_db  # noqa: E402

import convert as notes_convert  # noqa: E402  (scripts/notes/convert.py)
import apply_chart  # noqa: E402


@dataclass
class Job:
    song: "music_db.Song"
    diff_key: str
    vox_path: str
    song_out_dir: str
    ksh_out: str
    audio_out: str
    s3v_path: str          # may be None -> audio render is skipped for this job
    jacket_src: str         # may be None


@dataclass
class JobResult:
    job: Job
    ok: bool
    wrote_ksh: bool = False
    wrote_audio: bool = False
    error: str = ""


@dataclass
class BatchOptions:
    se_bank_dir: str = None
    ffmpeg_path: str = None
    render_audio: bool = True
    standard_slam_gap: bool = True   # notes_convert.convert()'s slam_gap_frac - see its docstring
    advanced_values: dict = field(default_factory=dict)   # dest -> value, from the Advanced panel


class _LineForwarder(io.TextIOBase):
    """Turns writes into complete-line callbacks, for streaming a script's
    print() output into the debug console as it happens rather than only
    once the whole render finishes."""

    def __init__(self, on_line):
        self.on_line = on_line
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.on_line(line)
        return len(s)

    def flush(self):
        if self._buf:
            self.on_line(self._buf)
            self._buf = ""


def plan_jobs(songs, music_dir, output_dir, diff_keys, fallback_music_dir=None):
    """songs (already filtered to the ones selected in the table) x diff_keys
    (the globally-checked NOV/ADV/EXH/top-tier filter) -> list[Job], skipping
    (song, diff) pairs the song doesn't actually have a chart for."""
    jobs = []
    # Output folders drop the numeric song id (song.folder, e.g.
    # "2393_alive_dadadaizu") in favour of the plain ascii name - but that's
    # not always unique: two real entries share one ("gott_hommarju", ids 125
    # and 1491). Falling back to the id-prefixed name only for a name that
    # actually collides *within this batch* keeps the common case id-free
    # without letting one song's output silently overwrite another's.
    name_owner = {}
    for song in songs:
        name_owner.setdefault(song.ascii, song.id)
    def out_name(song):
        return song.folder if name_owner[song.ascii] != song.id else song.ascii

    for song in songs:
        # "top" tier: whichever of infinite/maximum this song actually has -
        # requested once as a set member, resolved per song since not every
        # song's top tier is the same tag.
        wanted = set(diff_keys)
        if "top" in wanted:
            wanted.discard("top")
            top = song.top_difficulty()
            if top:
                wanted.add(top.key)
        base_name = out_name(song)
        song_out_dir = os.path.join(output_dir, base_name)
        for key in music_db.DIFF_ORDER:
            if key not in wanted or key not in song.difficulties:
                continue
            diff = song.difficulties[key]
            vox_path = song.vox_path(music_dir, key)
            if not vox_path:
                continue
            jacket_src = song.jacket_path(music_dir, key, fallback_music_dir)
            jobs.append(Job(
                song=song, diff_key=key, vox_path=vox_path,
                song_out_dir=song_out_dir,
                ksh_out=os.path.join(song_out_dir, "%s_%s.ksh" % (base_name, diff.suffix)),
                audio_out=os.path.join(song_out_dir, "%s.ogg" % diff.suffix),
                s3v_path=song.s3v_path(music_dir, fallback_music_dir),
                jacket_src=jacket_src,
            ))
    return jobs


def _meta_for(job):
    diff = job.song.difficulties[job.diff_key]
    jacket_name = ""
    if job.jacket_src:
        jacket_name = "%s.png" % diff.suffix
    return {
        "title": job.song.title,
        "artist": job.song.artist,
        "effect": diff.effected_by,
        "illustrator": diff.illustrator,
        "level": diff.level_int,
        "jacket": jacket_name,
        "m": os.path.basename(job.audio_out),
    }


def run_job(job, options, log):
    """One (song, difficulty): notes conversion, jacket copy, audio render.
    Never raises - failures are reported in the returned JobResult so one bad
    chart doesn't stop the batch."""
    os.makedirs(job.song_out_dir, exist_ok=True)
    result = JobResult(job=job, ok=True)

    meta = _meta_for(job)
    slam_gap_frac = notes_convert.laser.SLAM_GAP_FRAC if options.standard_slam_gap else 0
    try:
        notes_convert.convert(job.vox_path, job.ksh_out, camera=True, meta=meta,
                               slam_gap_frac=slam_gap_frac)
        result.wrote_ksh = True
    except Exception as e:  # noqa: BLE001 - one bad chart must not abort the batch
        result.ok = False
        result.error = "notes conversion failed: %s" % e
        log("!! %s: %s" % (os.path.basename(job.vox_path), e))
        return result

    if meta["jacket"] and job.jacket_src:
        try:
            shutil.copyfile(job.jacket_src, os.path.join(job.song_out_dir, meta["jacket"]))
        except OSError as e:
            log("!! jacket copy failed for %s: %s" % (job.song.folder, e))

    if not options.render_audio:
        return result

    if not job.s3v_path:
        log("-- %s (%s): no .s3v found (not in the input folder or the fallback "
            "install) - .ksh written, audio skipped" % (job.song.folder, job.diff_key))
        return result

    # apply_chart.py's positional `folder` is the INPUT chart folder it globs
    # *.vox in - not the output folder we're writing into.
    argv = [os.path.dirname(job.vox_path),
            "-d", job.song.difficulties[job.diff_key].suffix,
            "-a", job.s3v_path,
            "-o", job.audio_out]
    if options.se_bank_dir:
        argv += ["--se-bank-dir", options.se_bank_dir]
    argv += argspec.build_cli_args(options.advanced_values or {})

    if options.ffmpeg_path:
        os.environ["FFMPEG"] = options.ffmpeg_path

    old_argv, old_out, old_err = sys.argv, sys.stdout, sys.stderr
    forwarder = _LineForwarder(log)
    sys.argv = ["apply_chart.py"] + argv
    sys.stdout = forwarder
    sys.stderr = forwarder
    try:
        apply_chart.main()
        result.wrote_audio = True
    except SystemExit as e:
        if e.code not in (0, None):
            result.ok = False
            result.error = "audio render failed: %s" % e.code
    except Exception as e:  # noqa: BLE001
        result.ok = False
        result.error = "audio render failed: %s" % e
        log("!! %s" % traceback.format_exc())
    finally:
        forwarder.flush()
        sys.argv, sys.stdout, sys.stderr = old_argv, old_out, old_err

    return result


class ConvertWorker:
    """Runs plan_jobs() output on one background thread. All callbacks fire
    from that thread - the caller is responsible for marshaling onto the Tk
    main thread (e.g. `root.after(0, lambda: ...)`), same convention as
    release_check.check_async."""

    def __init__(self, jobs, options, on_log, on_progress, on_done):
        self.jobs = jobs
        self.options = options
        self.on_log = on_log
        self.on_progress = on_progress      # (index, total, job) -> None, before each job starts
        self.on_done = on_done              # (list[JobResult], cancelled: bool) -> None
        self._cancel = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="convert-worker", daemon=True)
        self._thread.start()
        return self._thread

    def cancel(self):
        """Stops the queue before its next job. Does not interrupt a render
        already running - see module docstring."""
        self._cancel.set()

    def _run(self):
        results = []
        total = len(self.jobs)
        for i, job in enumerate(self.jobs):
            if self._cancel.is_set():
                self.on_done(results, True)
                return
            self.on_progress(i, total, job)
            results.append(run_job(job, self.options, self.on_log))
        self.on_done(results, False)
