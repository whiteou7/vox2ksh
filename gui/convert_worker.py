"""Job queue on one background thread. Per (song, difficulty) it runs convert_notes.convert() with real metadata, then render_chart.main(), both in-process, and streams stdout into the debug console. po= and plength= are measured by preview_offset and cached per song. Cancelling is job-granular: a render in progress finishes, the queue stops before the next one.
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
import advanced_options  # noqa: E402
import music_db  # noqa: E402

import convert_notes as notes_convert  # noqa: E402  (scripts/notes/convert_notes.py)
import render_chart  # noqa: E402
import preview_offset  # noqa: E402


@dataclass
class Job:
    song: "music_db.Song"
    diff_key: str
    vox_path: str
    song_out_dir: str
    ksh_out: str
    audio_out: str
    s3v_path: str
    jacket_src: str
    jacket_out_name: str
    pre_s3v_path: str = None


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
    preview_meta: bool = True
    standard_slam_gap: bool = True
    ksh_version: int = 1
    pretilt_fix: bool = False
    advanced_values: dict = field(default_factory=dict)


class _LineForwarder(io.TextIOBase):
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
    jobs = []
    name_owner = {}
    for song in songs:
        name_owner.setdefault(song.ascii, song.id)
    def out_name(song):
        return song.folder if name_owner[song.ascii] != song.id else song.ascii

    for song in songs:
        wanted = set(diff_keys)
        if "top" in wanted:
            wanted.discard("top")
            top = song.top_difficulty()
            if top:
                wanted.add(top.key)
        base_name = out_name(song)
        song_out_dir = os.path.join(output_dir, base_name)

        entries = []
        for key in music_db.DIFF_ORDER:
            if key not in wanted or key not in song.difficulties:
                continue
            diff = song.difficulties[key]
            vox_path = song.vox_path(music_dir, key)
            if not vox_path:
                continue
            jacket_src = song.jacket_path(music_dir, key, fallback_music_dir)
            entries.append((key, diff, vox_path, jacket_src))

        jacket_srcs = {js for _k, _d, _v, js in entries if js}
        shared_jacket = len(jacket_srcs) == 1

        for key, diff, vox_path, jacket_src in entries:
            short = music_db.DIFF_SHORT[key].lower()
            jacket_out_name = ""
            if jacket_src:
                jacket_out_name = "jak.png" if shared_jacket else "%s.png" % short
            jobs.append(Job(
                song=song, diff_key=key, vox_path=vox_path,
                song_out_dir=song_out_dir,
                ksh_out=os.path.join(song_out_dir, "%s.ksh" % short),
                audio_out=os.path.join(song_out_dir, "%s.ogg" % short),
                s3v_path=song.s3v_path(music_dir, fallback_music_dir),
                jacket_src=jacket_src,
                jacket_out_name=jacket_out_name,
                pre_s3v_path=song.pre_s3v_path(music_dir, fallback_music_dir),
            ))
    return jobs


def _meta_for(job, preview_window=None):
    diff = job.song.difficulties[job.diff_key]
    po, plength = preview_window or (0, 0)
    return {
        "title": job.song.title,
        "artist": job.song.artist,
        "effect": diff.effected_by,
        "illustrator": diff.illustrator,
        "level": diff.level_int,
        "information": "CC: %s" % diff.level_display,
        "jacket": job.jacket_out_name,
        "m": os.path.basename(job.audio_out),
        "po": po,
        "plength": plength,
    }


def _preview_window(job, options, log, cache):
    if not options.preview_meta or not job.s3v_path or not job.pre_s3v_path:
        return None
    if job.s3v_path in cache:
        return cache[job.s3v_path]
    try:
        window = preview_offset.measure(job.s3v_path, job.pre_s3v_path)
        if window is None:
            log("-- %s: preview didn't match the track - po/plength left at 0"
                % job.song.folder)
    except Exception as e:  # noqa: BLE001 - preview metadata is never worth failing a chart over
        log("-- %s: preview offset failed (%s) - po/plength left at 0" % (job.song.folder, e))
        window = None
    cache[job.s3v_path] = window
    return window


def run_job(job, options, log, preview_cache=None):
    os.makedirs(job.song_out_dir, exist_ok=True)
    result = JobResult(job=job, ok=True)

    meta = _meta_for(job, _preview_window(job, options, log,
                                           preview_cache if preview_cache is not None else {}))
    slam_gap_frac = notes_convert.laser.SLAM_GAP_FRAC if options.standard_slam_gap else 0
    try:
        notes_convert.convert(job.vox_path, job.ksh_out, camera=True, meta=meta,
                               slam_gap_frac=slam_gap_frac,
                               pretilt_fix=options.pretilt_fix,
                               ksh_version=options.ksh_version)
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

    argv = [os.path.dirname(job.vox_path),
            "-d", job.song.difficulties[job.diff_key].suffix,
            "-a", job.s3v_path,
            "-o", job.audio_out]
    if options.se_bank_dir:
        argv += ["--se-bank-dir", options.se_bank_dir]
    argv += advanced_options.build_cli_args(options.advanced_values or {})

    if options.ffmpeg_path:
        os.environ["FFMPEG"] = options.ffmpeg_path

    old_argv, old_out, old_err = sys.argv, sys.stdout, sys.stderr
    forwarder = _LineForwarder(log)
    sys.argv = ["render_chart.py"] + argv
    sys.stdout = forwarder
    sys.stderr = forwarder
    try:
        render_chart.main()
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
    def __init__(self, jobs, options, on_log, on_progress, on_done):
        self.jobs = jobs
        self.options = options
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_done = on_done
        self._cancel = threading.Event()
        self._thread = None
        self._preview_cache = {}

    def start(self):
        self._thread = threading.Thread(target=self._run, name="convert-worker", daemon=True)
        self._thread.start()
        return self._thread

    def cancel(self):
        self._cancel.set()

    def _run(self):
        results = []
        total = len(self.jobs)
        for i, job in enumerate(self.jobs):
            if self._cancel.is_set():
                self.on_done(results, True)
                return
            self.on_progress(i, total, job)
            results.append(run_job(job, self.options, self.on_log, self._preview_cache))
        self.on_done(results, False)
