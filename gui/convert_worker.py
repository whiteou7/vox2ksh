"""Runs chart jobs on configurable isolated worker processes. po= and plength= are measured once per song and cached in the parent process. Cancelling stops new jobs and lets active jobs finish.
"""
import concurrent.futures
import contextlib
import io
import multiprocessing
import os
import queue
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

MAX_PARALLEL_CHARTS = 32
_PROCESS_LOG_QUEUE = None


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
    max_parallel_charts: int = 2
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
    def output_folder_name(song):
        return song.folder if name_owner[song.ascii] != song.id else song.ascii

    for song in songs:
        wanted = song.resolve_diff_keys(diff_keys)
        base_name = output_folder_name(song)
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


def _chart_metadata(job, preview_window=None):
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


def _measured_preview_window(job, options, log, cache):
    if not options.preview_meta or not job.s3v_path or not job.pre_s3v_path:
        return None
    if job.s3v_path in cache:
        return cache[job.s3v_path]
    try:
        window = preview_offset.measure_preview_window(job.s3v_path, job.pre_s3v_path)
        if window is None:
            log("-- %s: preview didn't match the track - po/plength left at 0"
                % job.song.folder)
    except Exception as e:  # noqa: BLE001 - preview metadata is never worth failing a chart over
        log("-- %s: preview offset failed (%s) - po/plength left at 0" % (job.song.folder, e))
        window = None
    cache[job.s3v_path] = window
    return window


def run_job(job, options, log, preview_cache=None, copy_jacket=True):
    os.makedirs(job.song_out_dir, exist_ok=True)
    result = JobResult(job=job, ok=True)

    meta = _chart_metadata(job, _measured_preview_window(job, options, log,
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

    if copy_jacket and meta["jacket"] and job.jacket_src:
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

    result.error = _render_audio(job, options, log)
    result.ok = not result.error
    result.wrote_audio = result.ok
    return result


def _render_audio(job, options, log):
    """Runs render_chart in-process, streaming its output to `log`. Returns an error message, or "" on success."""
    argv = [os.path.dirname(job.vox_path),
            "-d", job.song.difficulties[job.diff_key].suffix,
            "-a", job.s3v_path,
            "-o", job.audio_out]
    if options.se_bank_dir:
        argv += ["--se-bank-dir", options.se_bank_dir]
    argv += advanced_options.build_cli_args(options.advanced_values or {})

    if options.ffmpeg_path:
        os.environ["FFMPEG"] = options.ffmpeg_path

    forwarder = _LineForwarder(log)
    try:
        with contextlib.redirect_stdout(forwarder), contextlib.redirect_stderr(forwarder):
            render_chart.main(argv)
    except SystemExit as e:
        # render_chart reports its own failures as SystemExit("message").
        return "audio render failed: %s" % e.code if e.code not in (0, None) else ""
    except Exception as e:  # noqa: BLE001 - one bad render must not abort the batch
        log("!! %s" % traceback.format_exc())
        return "audio render failed: %s" % e
    finally:
        forwarder.flush()
    return ""


def _run_isolated_job(job, options, preview_window):
    """Runs one job with process-local stdout/stderr and returns its log lines."""
    lines = []
    log = _PROCESS_LOG_QUEUE.put if _PROCESS_LOG_QUEUE is not None else lines.append
    forwarder = _LineForwarder(log)
    cache = {job.s3v_path: preview_window} if job.s3v_path else {}
    try:
        with contextlib.redirect_stdout(forwarder), contextlib.redirect_stderr(forwarder):
            result = run_job(job, options, log, cache, copy_jacket=False)
    finally:
        forwarder.flush()
    return result, lines


def _initialize_process_worker(log_queue):
    global _PROCESS_LOG_QUEUE
    _PROCESS_LOG_QUEUE = log_queue


class ConvertWorker:
    def __init__(self, jobs, options, on_log, on_progress, on_done, on_status=None):
        if (not isinstance(options.max_parallel_charts, int)
                or isinstance(options.max_parallel_charts, bool)
                or not 1 <= options.max_parallel_charts <= MAX_PARALLEL_CHARTS):
            raise ValueError("max_parallel_charts must be between 1 and %d"
                             % MAX_PARALLEL_CHARTS)
        self.jobs = jobs
        self.options = options
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_done = on_done
        self.on_status = on_status
        self._cancel = threading.Event()
        self._thread = None
        self._preview_cache = {}

    def start(self):
        self._thread = threading.Thread(target=self._run_queue, name="convert-worker", daemon=True)
        self._thread.start()
        return self._thread

    def cancel(self):
        self._cancel.set()

    def _run_queue(self):
        total = len(self.jobs)
        worker_count = min(self.options.max_parallel_charts, total)
        completed = {}
        copied_jackets = set()
        next_index = 0
        cancelled = False

        def notify_status(active_jobs):
            active_jobs = list(active_jobs)
            names = ", ".join(os.path.basename(job.vox_path) for job in active_jobs)
            status = "Completed %d/%d | Processing %d/%d: %s" % (
                len(completed), total, len(active_jobs), worker_count, names or "none")
            terminal = getattr(sys, "__stdout__", None) or sys.stdout
            if terminal is not None:
                print("[convert] " + status, file=terminal, flush=True)
            if self.on_status:
                self.on_status(status)

        def finish_job(index, job, result, lines):
            for line in lines:
                self.on_log(line)
            if result.wrote_ksh and job.jacket_src and job.jacket_out_name:
                jacket_out = os.path.join(job.song_out_dir, job.jacket_out_name)
                if jacket_out not in copied_jackets:
                    try:
                        shutil.copyfile(job.jacket_src, jacket_out)
                        copied_jackets.add(jacket_out)
                    except OSError as e:
                        self.on_log("!! jacket copy failed for %s: %s" % (job.song.folder, e))
            completed[index] = result
            self.on_progress(len(completed), total, job)

        def run_sequential(index, job):
            active = {index: job}
            notify_status(active.values())
            _measured_preview_window(job, self.options, self.on_log, self._preview_cache)
            try:
                result = run_job(job, self.options, self.on_log,
                                 self._preview_cache, copy_jacket=False)
            except Exception as e:  # noqa: BLE001 - one failed job must not abort the batch
                result = JobResult(job=job, ok=False,
                                   error="conversion worker failed: %s" % e)
                self.on_log("!! %s" % traceback.format_exc())
            finish_job(index, job, result, [])
            active.clear()
            notify_status(active.values())

        if worker_count <= 1:
            for index, job in enumerate(self.jobs):
                if self._cancel.is_set():
                    cancelled = True
                    break
                run_sequential(index, job)
        else:
            pending = {}
            retry_sequential = []
            context = multiprocessing.get_context("spawn")
            log_queue = context.Queue()

            def drain_logs():
                while True:
                    try:
                        self.on_log(log_queue.get_nowait())
                    except queue.Empty:
                        return

            try:
                pool = concurrent.futures.ProcessPoolExecutor(
                    max_workers=worker_count,
                    mp_context=context,
                    initializer=_initialize_process_worker,
                    initargs=(log_queue,))
            except Exception as e:  # noqa: BLE001 - retain conversion if process startup is unavailable
                self.on_log("-- parallel workers unavailable (%s); continuing sequentially" % e)
                log_queue.close()
                for index, job in enumerate(self.jobs):
                    if self._cancel.is_set():
                        cancelled = True
                        break
                    run_sequential(index, job)
            else:
                with pool:
                    while next_index < total or pending:
                        drain_logs()
                        while (not self._cancel.is_set() and next_index < total
                               and len(pending) < worker_count):
                            index = next_index
                            job = self.jobs[index]
                            preview = _measured_preview_window(
                                job, self.options, self.on_log, self._preview_cache)
                            try:
                                future = pool.submit(
                                    _run_isolated_job, job, self.options, preview)
                            except Exception as e:  # noqa: BLE001 - report worker startup failures
                                self.on_log(
                                    "-- parallel worker unavailable for %s (%s); retrying sequentially"
                                    % (os.path.basename(job.vox_path), e))
                                retry_sequential.append((index, job))
                            else:
                                pending[future] = (index, job)
                                notify_status(job for _i, job in pending.values())
                            next_index += 1

                        if self._cancel.is_set():
                            cancelled = True
                            for future in pending:
                                future.cancel()
                        running = [future for future in pending if not future.cancelled()]
                        if not running:
                            break
                        done, _ = concurrent.futures.wait(
                            running, timeout=0.1,
                            return_when=concurrent.futures.FIRST_COMPLETED)
                        drain_logs()
                        changed = bool(done)
                        for future in done:
                            index, job = pending.pop(future)
                            try:
                                result, lines = future.result()
                            except Exception as e:  # noqa: BLE001 - one failed job must not abort the batch
                                self.on_log(
                                    "-- parallel worker failed for %s (%s); retrying sequentially"
                                    % (os.path.basename(job.vox_path), e))
                                self.on_log("!! %s" % traceback.format_exc())
                                retry_sequential.append((index, job))
                            else:
                                finish_job(index, job, result, lines)
                        for future in tuple(pending):
                            if future.cancelled():
                                pending.pop(future)
                                changed = True
                        if changed:
                            notify_status(job for _i, job in pending.values())
                drain_logs()
                log_queue.close()
                log_queue.join_thread()
                for index, job in sorted(retry_sequential):
                    run_sequential(index, job)

        if cancelled:
            notify_status(())
        results = [completed[index] for index in sorted(completed)]
        self.on_done(results, cancelled)
