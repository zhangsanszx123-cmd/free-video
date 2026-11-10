"""Isolated bounded queue for subtitle-first transcription and safe cloud recovery."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hashlib
import json
import logging
import math
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
import wave

from . import asr, config, downloader
from .asr_ledger import Ledger
from .errors import EmptySubtitles, NoSubtitles, TranscriptionError, VideoError
from .storage import TemporaryStorage
from .subtitles import parse_srt, to_plain_text, to_srt

log = logging.getLogger("freevideo.transcriptions")
TERMINAL = {"done", "error"}


def read_subtitles(url: str, directory: Path, lang: str | None = None):
    path, info = downloader.download_subtitle(url, directory, lang)
    cues = parse_srt(path.read_text(encoding="utf-8", errors="ignore"))
    if not cues:
        raise EmptySubtitles("字幕内容为空，可手动使用音频转文字")
    language = lang or downloader.choose_subtitle(info)
    track = next((s for s in downloader.list_subtitles(info) if s["lang"] == language), {})
    return info, cues, {"source": "automatic_subtitle" if track.get("auto") else "platform_subtitle",
                         "language": language}


def result_payload(cues, source, language=None):
    return {"text": "\n".join(c.text for c in cues), "timed_text": to_plain_text(cues),
            "cues": len(cues), "source": source, "language": language, "srt": to_srt(cues)}


def probe_audio(path: Path):
    try:
        proc = subprocess.run([config.FFPROBE_BINARY, "-v", "error", "-show_entries",
                               "format=duration:stream=codec_type,duration", "-of", "json", str(path)],
                              capture_output=True, timeout=30)
        if proc.returncode:
            raise ValueError()
        data = json.loads(proc.stdout)
        audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
        if not audio:
            raise TranscriptionError("NO_AUDIO", "视频没有可识别的音轨")
        duration = float(data.get("format", {}).get("duration") or audio[0].get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        if duration > config.ASR_MAX_DURATION:
            raise TranscriptionError("AUDIO_TOO_LONG", f"音频超过 {config.ASR_MAX_DURATION // 60} 分钟上限")
        return duration
    except FileNotFoundError:
        raise TranscriptionError("MEDIA_TOOLS", "服务器未配置 ffprobe，请联系管理员", status=503) from None
    except (ValueError, TypeError, subprocess.TimeoutExpired):
        raise TranscriptionError("INVALID_AUDIO", "无法读取音频时长或文件格式") from None


def acquire_audio(url: str, directory: Path, report):
    # downloader's audio path extracts the actual video soundtrack, including Douyin.
    source = downloader.download(url, directory / "source", kind="audio",
                                 report=lambda **f: report(stage="audio", message=f.get("message") or "正在获取视频音轨…"))
    probe_audio(source)
    target = directory / "input.mp3"
    try:
        proc = subprocess.run([config.FFMPEG_BINARY, "-y", "-loglevel", "error", "-i", str(source),
                               "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                               "-c:a", "libmp3lame", "-b:a", "64k", str(target)],
                              capture_output=True, timeout=600)
    except FileNotFoundError:
        raise TranscriptionError("MEDIA_TOOLS", "服务器未配置 ffmpeg，请联系管理员", status=503) from None
    except subprocess.TimeoutExpired:
        raise TranscriptionError("AUDIO_TIMEOUT", "音频转换超时，请换用较短视频", True) from None
    if proc.returncode or not target.is_file():
        raise TranscriptionError("AUDIO_CONVERSION", "视频音轨转换失败")
    duration = probe_audio(target)
    if target.stat().st_size > config.ASR_MAX_FILESIZE_MB * 1024 * 1024:
        raise TranscriptionError("AUDIO_TOO_LARGE", f"识别音频超过 {config.ASR_MAX_FILESIZE_MB}MB 上限")
    return target, duration


def prepare_pcm(source: Path) -> Path:
    """Decode the size-checked MP3 to raw mono PCM before any paid connection."""
    target = source.with_suffix(".pcm")
    try:
        proc = subprocess.run([config.FFMPEG_BINARY, "-y", "-loglevel", "error", "-i", str(source),
                               "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                               "-f", "s16le", "-c:a", "pcm_s16le", str(target)],
                              capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        raise TranscriptionError("AUDIO_CONVERSION", "识别音轨转换失败，请检查服务器 FFmpeg 配置", True) from None
    if proc.returncode or not target.is_file() or target.stat().st_size == 0:
        raise TranscriptionError("AUDIO_CONVERSION", "视频没有有效的识别音轨")
    return target


def prepare_segments(source: Path, duration: float):
    """Exact non-overlapping sample ranges, all prepared before any paid request."""
    if duration <= 300:
        return [(source, duration, 0)]
    pcm = prepare_pcm(source)
    root = source.parent / "segments"
    root.mkdir(exist_ok=True)
    segments, samples = [], 0
    with pcm.open("rb") as audio:
        while data := audio.read(280 * 32000):
            if len(data) % 2:
                raise TranscriptionError("INVALID_AUDIO", "音频采样数据不完整")
            path = root / f"{len(segments):03}.wav"
            with wave.open(str(path), "wb") as part:
                part.setnchannels(1)
                part.setsampwidth(2)
                part.setframerate(16000)
                part.writeframes(data)
            segments.append((path, len(data) / 32000, samples * 1000 // 16000))
            samples += len(data) // 2
    if not segments:
        raise TranscriptionError("INVALID_AUDIO", "音频分段结果为空")
    return segments


@dataclass
class Transcription:
    id: str
    owner: str
    key: str
    url: str
    lang: str | None
    allow_asr: bool
    status: str = "queued"
    stage: str = "queued"
    message: str = "等待处理…"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    title: str = "视频文稿"
    result: dict | None = None
    reuse_id: str | None = None

    @property
    def directory(self):
        return config.ASR_DIR / "results" / self.id

    def public(self):
        return {k: getattr(self, k) for k in ("id", "status", "stage", "message", "created_at", "finished_at",
                                             "error", "error_code", "retryable", "title", "result")}


class TranscriptionManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: dict[str, Transcription] = {}
        self.keys: dict[str, str] = {}
        self.pool = ThreadPoolExecutor(max_workers=max(1, config.ASR_WORKERS), thread_name_prefix="transcription")
        self.ledger = Ledger()
        self._stop = threading.Event()
        self._maintenance = None
        self.recovery_ready = False

    def submit(self, owner, url, lang=None, allow_asr=False):
        url = downloader.extract_url(url)
        # Canonical URL from /api/parse is used by the UI. Alternate share URLs are
        # additionally canonicalized before any paid submission, inside _run.
        key = self._key(owner, url, lang, allow_asr)
        with self.lock:
            existing = self.jobs.get(self.keys.get(key))
            if existing and (existing.status not in TERMINAL or existing.status == "done" or not existing.retryable):
                if existing.reuse_id and existing.reuse_id in self.jobs:
                    return self.jobs[existing.reuse_id]
                return existing
            active = sum(j.status not in TERMINAL for j in self.jobs.values())
            if active >= config.ASR_WORKERS + config.ASR_MAX_QUEUE:
                raise TranscriptionError("QUEUE_FULL", "转写任务已满，请稍后重试", True, 429)
            if allow_asr and not self.recovery_ready:
                raise TranscriptionError("RECOVERING", "识别服务正在核对未决任务，请稍后重试", True, 503)
            job = Transcription(uuid.uuid4().hex, owner, key, url, lang, allow_asr)
            self.jobs[job.id] = job
            self.keys[key] = job.id
            self.pool.submit(self._run, job)
            return job

    @staticmethod
    def _key(owner, url, lang, allow_asr):
        return hashlib.sha256(json.dumps([owner, url, lang, allow_asr, config.ASR_PROVIDER, config.ASR_MODEL]).encode()).hexdigest()

    def get(self, job_id, owner):
        self.cleanup()
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.owner != owner:
                raise TranscriptionError("NOT_FOUND", "任务不存在或已过期", status=404)
            if job.reuse_id:
                reused = self.jobs.get(job.reuse_id)
                if not reused or reused.owner != owner:
                    raise TranscriptionError("NOT_FOUND", "任务不存在或已过期", status=404)
                return reused
            return job

    def _update(self, job, **fields):
        with self.lock:
            for key, value in fields.items():
                setattr(job, key, value)

    def _run(self, job):
        reserved = False
        uncertain = False
        cloud_terminal = False
        streaming = asr.is_streaming()
        direct = asr.is_direct()
        object_key = None if streaming or direct else config.OSS_PREFIX + job.id + ".mp3"
        storage = None
        try:
            self._update(job, status="running", stage="subtitles", message="正在检查可下载字幕…")
            job.directory.mkdir(parents=True, exist_ok=True)
            try:
                info, cues, metadata = read_subtitles(job.url, job.directory / "subtitles", job.lang)
                self._finish(job, cues, info.get("title"), **metadata)
                return
            except (NoSubtitles, EmptySubtitles) as exc:
                if isinstance(exc, NoSubtitles) and '登录' in str(exc):
                    raise VideoError(str(exc)) from exc
                if not job.allow_asr:
                    raise TranscriptionError("ASR_REQUIRED", "无可用文字字幕，请点击音频转文字", True)
            # Re-parse on the server, don't trust browser-supplied duration/id.
            info = downloader.parse(job.url)
            canonical = info.get("url") or job.url
            # Subtitle-language selection does not change ASR parameters (no translation).
            # Reuse the same speech result even when two empty tracks were selected.
            canonical_key = self._key(job.owner, canonical, None, job.allow_asr)
            with self.lock:
                previous = self.jobs.get(self.keys.get(canonical_key))
                if previous and previous.id != job.id and (previous.status != "error" or not previous.retryable):
                    # Alias requests read the same owned job, including its exports.
                    self._update(job, reuse_id=previous.id, status="done", stage="done", finished_at=time.time())
                    return
                self.keys[canonical_key] = job.id
            asr.require_enabled()
            if info.get("duration") and info["duration"] > config.ASR_MAX_DURATION:
                raise TranscriptionError("AUDIO_TOO_LONG", f"音频超过 {config.ASR_MAX_DURATION // 60} 分钟上限")
            self._update(job, title=info.get("title") or job.title, stage="audio", message="正在获取视频音轨…")
            path, duration = acquire_audio(canonical, job.directory, lambda **f: self._update(job, **f))
            if direct:
                segments = prepare_segments(path, duration)
                self.ledger.reserve(job.id, sum(math.ceil(d) for _, d, _ in segments), None, canonical_key)
                reserved = True
                states = [{"state": "reserved", "duration": d, "offset_ms": offset}
                          for _, d, offset in segments]
                state_lock = threading.RLock()
                self.ledger.update(job.id, segments=states)

                def recognize_part(index):
                    audio, seconds, offset = segments[index]
                    def submitted(request_id):
                        with state_lock:
                            states[index].update(state="submitting", request_id=request_id)
                            self.ledger.update(job.id, state="submitting", segments=states)
                    try:
                        result = asr.get_provider().recognize(audio, submitted, self._stop,
                                                              duration=seconds, offset_ms=offset)
                    except Exception as exc:
                        with state_lock:
                            rejected = isinstance(exc, TranscriptionError) and exc.code in ("CLOUD_AUTH", "CLOUD_REJECTED")
                            states[index]["state"] = ("released" if rejected or states[index]["state"] == "reserved" else "unknown")
                            self.ledger.update(job.id, segments=states)
                        raise
                    with state_lock:
                        billed = result.duration if result.duration is not None else seconds
                        states[index].update(state="settled", actual_duration=billed)
                        self.ledger.update(job.id, segments=states)
                        completed = sum(s["state"] == "settled" for s in states)
                        self._update(job, message=f"快速识别中：已完成 {completed}/{len(segments)} 段…")
                    return result

                self._update(job, stage="recognizing", message=f"正在快速识别音频，共 {len(segments)} 段…")
                results, failures = [], []
                # A per-video bounded pool accelerates long videos; output follows segment order.
                with ThreadPoolExecutor(max_workers=max(1, min(4, config.ASR_SEGMENT_WORKERS))) as pool:
                    futures = [pool.submit(recognize_part, i) for i in range(len(segments))]
                    for future in futures:
                        try:
                            results.append(future.result())
                        except Exception as exc:
                            failures.append(exc)
                uncertain = any(s["state"] in ("submitting", "unknown") for s in states)
                if not uncertain:
                    cloud_terminal = True
                    if any(s["state"] == "settled" for s in states):
                        self.ledger.settle(job.id, sum(math.ceil(s["actual_duration"]) for s in states if s["state"] == "settled"))
                    else:
                        self.ledger.update(job.id, state="released")
                if failures:
                    # Completed chunks must not be paid again by retrying the whole video.
                    if any(s["state"] == "settled" for s in states):
                        raise TranscriptionError("PARTIAL_RECOGNITION", "部分音频识别失败，请管理员核对；请勿重复提交整条视频")
                    raise failures[0]
                cues = [cue for result in results for cue in (result.cues or [])]
                if any(result.status != "SUCCEEDED" for result in results):
                    raise TranscriptionError("RECOGNITION_FAILED", "语音识别失败，请管理员核对")
                if not cues:
                    raise TranscriptionError("NO_SPEECH", "没有识别到人声或文字，可能是静音或纯音乐")
                self._finish(job, cues, job.title, "asr", results[0].language)
                return
            if streaming:
                audio = prepare_pcm(path)
                self.ledger.reserve(job.id, duration, None, canonical_key)
                reserved = True

                def on_submit(task_id):
                    nonlocal uncertain
                    self.ledger.update(job.id, state="submitting", task_id=task_id)
                    uncertain = True

                self._update(job, stage="recognizing", message="音频实时发送与识别中，耗时与音频长度有关…")
                result = asr.get_provider().recognize(audio, on_submit, self._stop)
                cloud_terminal = True
                self.ledger.settle(job.id, result.duration)
                uncertain = False
                if result.status != "SUCCEEDED":
                    raise TranscriptionError("RECOGNITION_FAILED", "语音识别失败，请检查音频或模型配置后重试", True)
                if not result.cues:
                    raise TranscriptionError("NO_SPEECH", "没有识别到人声或文字，可能是静音或纯音乐")
                self._finish(job, result.cues, job.title, "asr", result.language)
                return
            # Persist the object key BEFORE any upload, so partial uploads can be reclaimed.
            self.ledger.reserve(job.id, duration, object_key, canonical_key)
            reserved = True
            storage = TemporaryStorage()
            self._update(job, stage="upload", message="正在上传临时音频…")
            audio_url = storage.upload(object_key, path)
            provider = asr.get_provider()
            self.ledger.update(job.id, state="submitting")
            uncertain = True  # crash/network timeout from here must never auto-resubmit
            self._update(job, stage="recognizing", message="语音识别中（含云端排队），请稍候…")
            try:
                task_id = provider.submit(audio_url)
            except TranscriptionError as e:
                if e.code in ("CLOUD_AUTH", "CLOUD_LIMIT", "CLOUD_REJECTED"):
                    uncertain = False
                raise
            self.ledger.update(job.id, state="submitted", task_id=task_id)
            deadline = time.monotonic() + config.ASR_TIMEOUT
            while time.monotonic() < deadline and not self._stop.is_set():
                try:
                    result = provider.query(task_id)
                except TranscriptionError as e:
                    if e.retryable:
                        self._update(job, message="识别状态暂时无法获取，正在重新查询（不会重复提交）…")
                        self._stop.wait(config.ASR_POLL_SECONDS)
                        continue
                    raise
                if result.status in ("SUCCEEDED", "FAILED"):
                    cloud_terminal = True
                    self.ledger.settle(job.id, result.duration)
                    uncertain = False
                    if result.status == "FAILED":
                        raise TranscriptionError("RECOGNITION_FAILED", "语音识别失败，请检查音频或稍后重试", True)
                    if not result.cues:
                        raise TranscriptionError("NO_SPEECH", "没有识别到人声或文字，可能是静音或纯音乐")
                    self._finish(job, result.cues, job.title, "asr", result.language)
                    return
                self._stop.wait(config.ASR_POLL_SECONDS)
            raise TranscriptionError("CLOUD_PENDING", "云端识别尚未结束，已保留额度并继续后台核对；请勿重复提交")
        except (TranscriptionError, VideoError) as e:
            if uncertain:
                # Keep the user from retrying into a second paid request.
                message = ("识别连接已中断，无法自动续传；已保留额度，请管理员核对后再试" if streaming
                           else "云端提交或处理状态待核对，已保留额度；请勿重复提交")
                error = TranscriptionError("SUBMISSION_UNCERTAIN", message)
            else:
                error = e if isinstance(e, TranscriptionError) else TranscriptionError("VIDEO_FAILED", str(e), True)
            self._update(job, status="error", stage="error", error=str(error), error_code=error.code,
                         retryable=error.retryable, message="处理失败", finished_at=time.time())
        except Exception:
            # Avoid logging exceptions containing signed URLs or provider response bodies.
            self._update(job, status="error", stage="error", error="转写处理异常，请联系管理员核对",
                         error_code="SUBMISSION_UNCERTAIN" if uncertain else "INTERNAL_ERROR",
                         retryable=not uncertain, finished_at=time.time())
            log.error("transcription %s failed (details redacted)", job.id)
        finally:
            if reserved:
                try:
                    if not uncertain and not cloud_terminal:
                        self.ledger.update(job.id, state="released")
                    elif uncertain:
                        self.ledger.update(job.id, state="unknown")
                    if not uncertain and object_key:
                        self._delete_object(job.id, object_key, storage)
                except Exception:
                    log.error("transcription %s journal/cleanup pending", job.id)
            shutil.rmtree(job.directory / "source", ignore_errors=True)
            shutil.rmtree(job.directory / "segments", ignore_errors=True)
            for name in ("input.mp3", "input.pcm"):
                try:
                    (job.directory / name).unlink(missing_ok=True)
                except OSError:
                    pass
            if job.result is not None and job.status != "error":
                self._update(job, status="done", stage="done", message="提取完成", finished_at=time.time())

    def _finish(self, job, cues, title, source, language=None):
        self._update(job, stage="export", message="正在生成文字与字幕…")
        payload = result_payload(cues, source, language)
        safe_title = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title or "视频文稿")[:80].strip(" .") or "视频文稿"
        for ext in ("txt", "srt"):
            content = payload["text"] if ext == "txt" else payload["srt"]
            (job.directory / f"transcript.{ext}").write_text(content, encoding="utf-8", newline="\n")
        self._update(job, title=safe_title, result=payload)

    def _delete_object(self, job_id, key, storage=None):
        try:
            (storage or TemporaryStorage()).delete(key)
            self.ledger.update(job_id, object_key=None)
        except Exception:
            # Key stays in journal; maintenance retries, OSS lifecycle is the last fallback.
            log.warning("temporary object cleanup pending for %s", job_id)

    def reconcile(self):
        entries = self.ledger.entries()
        for job_id, entry in entries.items():
            with self.lock:
                job = self.jobs.get(job_id)
                if job and job.status not in TERMINAL:
                    continue
            if entry.get("transport") in ("stream", "direct-http"):
                if entry["state"] == "reserved":
                    self.ledger.update(job_id, state="released")  # no run-task was journaled
                elif entry["state"] in ("submitting", "submitted"):
                    self.ledger.update(job_id, state="unknown")
                # A WebSocket UUID is not a queryable file-task ID. Keep the hold,
                # never replay audio after process death or connection loss.
                continue
            if (entry.get("bucket") != config.OSS_BUCKET or entry.get("endpoint") != config.OSS_ENDPOINT
                    or entry.get("provider") != config.ASR_PROVIDER or entry.get("base_url") != config.DASHSCOPE_BASE_URL):
                continue  # Never delete/query with credentials for a different configuration.
            state = entry["state"]
            if state == "reserved":
                self.ledger.update(job_id, state="released")  # upload may have happened, submission did not
                state = "released"
            if state in ("submitted", "submitting", "unknown"):
                if entry.get("task_id") and asr.enabled():
                    try:
                        result = asr.get_provider().query(entry["task_id"])
                        if result.status in ("SUCCEEDED", "FAILED"):
                            self.ledger.settle(job_id, result.duration)
                            state = "settled"
                            if job and job.error_code == "SUBMISSION_UNCERTAIN":
                                if result.status == "SUCCEEDED" and result.cues:
                                    self._finish(job, result.cues, job.title, "asr", result.language)
                                    self._update(job, status="done", stage="done", message="提取完成", error=None,
                                                 error_code=None, retryable=False, finished_at=time.time())
                                else:
                                    self._update(job, error="未识别到文字或云端识别失败", error_code="RECOGNITION_FAILED", retryable=True)
                    except TranscriptionError:
                        pass
                # Unknown submissions without task IDs retain their reservation permanently.
                # After the signed input URL has expired, reclaim the input; never resubmit.
                expired = time.time() - entry["created_at"] > config.OSS_URL_TTL + 3600
                if state not in ("settled", "released") and not expired:
                    continue
            if entry.get("object_key"):
                self._delete_object(job_id, entry["object_key"])

    def cleanup(self, now=None):
        now = now or time.time()
        with self.lock:
            for job_id, job in list(self.jobs.items()):
                reused = self.jobs.get(job.reuse_id) if job.reuse_id else None
                finished_at = reused.finished_at if reused else job.finished_at
                if finished_at and now - finished_at > config.FILE_TTL_SECONDS:
                    shutil.rmtree(job.directory, ignore_errors=True)
                    del self.jobs[job_id]
                    self.keys = {k: v for k, v in self.keys.items() if v != job_id}
            root = config.ASR_DIR / "results"
            if root.exists():
                for directory in root.iterdir():
                    if directory.is_dir() and directory.name not in self.jobs and now - directory.stat().st_mtime > config.FILE_TTL_SECONDS:
                        shutil.rmtree(directory, ignore_errors=True)

    def start(self):
        if self._maintenance and self._maintenance.is_alive():
            return
        self._stop.clear()
        def maintain():
            while not self._stop.is_set():
                try:
                    self.reconcile()
                    self.recovery_ready = True
                    self.cleanup()
                except Exception:
                    self.recovery_ready = False
                    log.error("ASR journal unavailable; new paid submissions paused")
                self._stop.wait(60)
        self._maintenance = threading.Thread(target=maintain, daemon=True, name="asr-maintenance")
        self._maintenance.start()

    def stop(self):
        self._stop.set()
        if self._maintenance:
            self._maintenance.join(timeout=1)
