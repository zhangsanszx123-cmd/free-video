"""One lifetime guest video summary; cookie ownership, cookie+IP quota, shared ASR ledger.

No account is synthesized and no guest usage is merged into account quotas. SQL
claims outlive result retention. All provider work runs outside transaction locks.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import logging
import math
import re
import threading
import time
import uuid

from . import account_store as store, ai, ai_learning, config, downloader, membership, usage
from .errors import AccountError, TranscriptionError, VideoError
from .learning_text import compact_from_timed_text
from .subtitles import parse_srt
from .transcriptions import result_payload

log = logging.getLogger('freevideo.guest_ai')
MAX_SECONDS = 180
TERMINAL = {'done', 'error', 'uncertain'}
PUBLIC = ('id', 'url', 'status', 'stage', 'message', 'error', 'error_code', 'retryable',
          'info', 'summary', 'transcript', 'created_at', 'finished_at')


def _decode(row):
    if row and isinstance(row['payload'], str):
        row['payload'] = json.loads(row['payload'])
    return row


def _row(owner, trial_id=None):
    with store._cursor() as cur:
        sql = 'SELECT * FROM guest_ai_trials WHERE owner=%s AND expires_at>%s'
        args = [owner, store.utcnow()]
        if trial_id:
            sql += ' AND id=%s'
            args.append(trial_id)
        cur.execute(sql + ' ORDER BY created_at DESC,id DESC LIMIT 1', args)
        return _decode(cur.fetchone())


def _reserve(owner, subjects, url):
    """Sorted row locks serialize even first-ever requests sharing an IP."""
    now = store.utcnow()
    key = usage.video_key(url)
    with store._cursor() as cur:
        for subject in subjects:
            cur.execute('INSERT IGNORE INTO guest_ai_subjects(subject) VALUES (%s)', (subject,))
        cur.execute('SELECT * FROM guest_ai_subjects WHERE subject IN %s ORDER BY subject FOR UPDATE', (tuple(subjects),))
        claims = list(cur.fetchall())
        cur.execute('SELECT * FROM guest_ai_trials WHERE owner=%s AND (raw_key=%s OR video_key=%s) '
                    'AND expires_at>%s ORDER BY created_at DESC,id DESC LIMIT 1', (owner, key, key, now))
        previous = _decode(cur.fetchone())
        if previous and (previous['state'] != 'error' or previous['payload'].get('summary', '').strip()):
            return previous, False
        if any(c['state'] != 'available' for c in claims):
            raise AccountError('GUEST_AI_LIMIT', '游客累计可免费总结 1 个视频，体验名额已使用或处理中，请登录后继续', 403)
        trial_id = uuid.uuid4().hex
        payload = dict(id=trial_id, url=url, status='queued', stage='queued', message='等待体验任务处理…',
                       error=None, error_code=None, retryable=False, info=None, summary='', transcript=None,
                       created_at=membership.iso(now), finished_at=None)
        # A failed summary does not pay for the same speech a second time.
        if previous:
            payload.update(info=previous['payload'].get('info'), transcript=previous['payload'].get('transcript'))
        row = dict(id=trial_id, owner=owner, raw_key=key, video_key=key, state='queued', payload=payload,
                   transcription_id=None, created_at=now, updated_at=now, expires_at=now + timedelta(days=30))
        cur.execute('INSERT INTO guest_ai_trials(id,owner,raw_key,video_key,state,payload,created_at,updated_at,expires_at) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (trial_id, owner, key, key, 'queued', json.dumps(payload, ensure_ascii=False), now, now, row['expires_at']))
        cur.execute("UPDATE guest_ai_subjects SET trial_id=%s,state='reserved' WHERE subject IN %s",
                    (trial_id, tuple(subjects)))
        return row, True


def _save(row, *, claim=None, **fields):
    payload = {**row['payload'], **fields}
    now = store.utcnow()
    with store._cursor() as cur:
        # Match admission lock order: claims first, trial row second.
        cur.execute('SELECT subject FROM guest_ai_subjects WHERE trial_id=%s ORDER BY subject FOR UPDATE', (row['id'],))
        cur.fetchall()
        cur.execute('UPDATE guest_ai_trials SET state=%s,payload=%s,updated_at=%s WHERE id=%s',
                    (payload['status'], json.dumps(payload, ensure_ascii=False, allow_nan=False), now, row['id']))
        if claim:
            cur.execute('UPDATE guest_ai_subjects SET state=%s WHERE trial_id=%s', (claim, row['id']))
    row.update(payload=payload, state=payload['status'], updated_at=now)


def _bind(row, job):
    with store._cursor() as cur:
        cur.execute('UPDATE guest_ai_trials SET transcription_id=%s WHERE id=%s', (job.id, row['id']))
    row['transcription_id'] = job.id


def _duration(info):
    try:
        seconds = float(info.get('duration') or 0)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise AccountError('GUEST_AI_DURATION_UNKNOWN', '暂时无法确认视频时长，请登录后继续总结', 403) from None
    if seconds > MAX_SECONDS:
        raise AccountError('GUEST_AI_TOO_LONG', '游客体验仅支持 3 分钟以内的视频，请登录后总结更长视频', 403)


def _check_transcript(result):
    # Also reject stale metadata paired with captions beyond the trial boundary.
    for cue in parse_srt(result.get('srt') or ''):
        try:
            hours, minutes, rest = cue.end.replace('.', ',').split(':')
            seconds = float(rest.replace(',', '.')) + 60 * int(minutes) + 3600 * int(hours)
            if seconds > MAX_SECONDS:
                raise AccountError('GUEST_AI_TOO_LONG', '视频字幕超过 3 分钟体验上限，请登录后继续', 403)
        except (ValueError, TypeError):
            raise VideoError('字幕时间轴无效，请更换视频') from None
    text = compact_from_timed_text(result.get('timed_text') or result.get('text') or '')
    if not text.strip():
        raise VideoError('没有可用于总结的有效文稿，请更换视频')
    if len(text) > 20000:
        raise AccountError('GUEST_AI_TEXT_TOO_LONG', '视频文稿超过游客体验处理上限，请登录后继续', 403)
    return text


class TrialManager:
    def __init__(self, get_transcription_manager):
        self.get_tm = get_transcription_manager
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='guest-ai')
        self.active = set()
        self.stopping = threading.Event()
        self.ready = False

    @staticmethod
    def public(row):
        return {key: row['payload'].get(key) for key in PUBLIC}

    def start(self):
        self.stopping.clear()
        self.recover()

    def stop(self):
        self.stopping.set()

    def status(self, owner, subjects):
        with self.lock:
            self.recover()
            with store._cursor() as cur:
                cur.execute("SELECT 1 FROM guest_ai_subjects WHERE subject IN %s AND state<>'available' LIMIT 1", (tuple(subjects),))
                available = cur.fetchone() is None
            row = _row(owner)
            return dict(available=available, max_seconds=MAX_SECONDS, task=self.public(row) if row else None)

    def get(self, owner, trial_id):
        with self.lock:
            self.recover()
            row = _row(owner, trial_id)
            if not row:
                raise AccountError('NOT_FOUND', '体验任务不存在或已过期', 404)
            return self.public(row)

    def submit(self, owner, subjects, text):
        url = downloader.extract_url(text)
        if not ai.enabled():
            raise AccountError('AI_DISABLED', 'AI 服务暂未启用，请稍后再试', 503)
        with self.lock:
            self.recover()
            if len(self.active) >= 8:
                raise AccountError('GUEST_AI_QUEUE_FULL', '体验任务较多，请稍后再试', 429)
            row, fresh = _reserve(owner, subjects, url)
            if fresh:
                self.active.add(row['id'])
                try:
                    future = self.pool.submit(self._run, row)
                    future.add_done_callback(lambda _: self._finished(row['id']))
                except RuntimeError:
                    self.active.discard(row['id'])
                    _save(row, status='error', stage='error', error='服务正在停止，请稍后再试',
                          error_code='INTERRUPTED', retryable=True, message='体验任务未启动',
                          finished_at=membership.iso(store.utcnow()), claim='available')
                    raise AccountError('GUEST_AI_UNAVAILABLE', '服务正在停止，请稍后再试', 503) from None
            return self.public(row)

    def _finished(self, trial_id):
        with self.lock:
            self.active.discard(trial_id)

    def _write(self, row, **fields):
        with self.lock:
            _save(row, **fields)

    def _run(self, row):
        summary = ''
        try:
            self._write(row, status='running', stage='parse', message='正在解析体验视频…')
            info = row['payload'].get('info') or downloader.parse(row['payload']['url'])
            _duration(info)
            with self.lock:
                canonical = info.get('url') or row['payload']['url']
                key = usage.video_key(canonical)
                with store._cursor() as cur:
                    cur.execute('UPDATE guest_ai_trials SET video_key=%s WHERE id=%s', (key, row['id']))
                row['video_key'] = key
                _save(row, info=info)
            transcript = row['payload'].get('transcript')
            if transcript is None:
                self._write(row, stage='transcribing', message='正在提取字幕；无字幕时免费识别视频语音…')
                tm = self.get_tm()
                with self.lock:
                    # Persist the ID before the shared manager can send any audio.
                    job = tm.submit('trial:' + row['owner'], canonical, allow_asr=True, max_duration=MAX_SECONDS,
                                    on_accept=lambda job: _bind(row, job))
                while job.status not in ('done', 'error'):
                    if self.stopping.wait(.1):
                        raise TranscriptionError('SUBMISSION_UNCERTAIN', '体验处理中断，请勿重复提交，稍后查询处理状态')
                    job = tm.get(job.id, 'trial:' + row['owner'])
                if job.status != 'done' or not job.result:
                    code = 'GUEST_AI_TOO_LONG' if job.error_code == 'AUDIO_TOO_LONG' else job.error_code or 'TRANSCRIPTION_FAILED'
                    message = '实际音轨超过 3 分钟体验上限，请登录后继续' if code == 'GUEST_AI_TOO_LONG' else job.error or '文稿提取失败'
                    raise TranscriptionError(code, message, job.retryable)
                transcript = job.result
                # Save a reusable result BEFORE starting the second paid service.
                self._write(row, transcript=transcript)
            compacted = _check_transcript(transcript)
            self._write(row, stage='summarizing', message='AI 正在为你总结视频…')
            last_save = time.monotonic()
            saved_output = False
            for kind, value in ai_learning.summarize_events(info.get('title') or '视频总结', compacted, mode='general'):
                if self.stopping.is_set():
                    raise VideoError('服务中断，已生成的内容将保留')
                if kind != 'delta' or not isinstance(value, str):
                    continue
                summary += value
                if summary.strip() and (not saved_output or time.monotonic() - last_save >= .5):
                    self._write(row, summary=summary, claim='used')
                    saved_output = True
                    last_save = time.monotonic()
            if not summary.strip():
                raise VideoError('本次未生成有效总结，未消耗体验名额，请稍后重试')
            self._write(row, summary=summary, status='done', stage='done', message='体验总结已完成',
                        finished_at=membership.iso(store.utcnow()), claim='used')
        except (AccountError, TranscriptionError, VideoError) as exc:
            code = getattr(exc, 'code', 'SUMMARY_FAILED')
            unknown = code in ('SUBMISSION_UNCERTAIN', 'PARTIAL_RECOGNITION', 'DUPLICATE_RESERVATION')
            try:
                if isinstance(exc, AccountError) and exc.code.startswith('DB_'):
                    entry = self.get_tm().ledger.entries().get(row.get('transcription_id'), {})
                    unknown = unknown or entry.get('state') in ('submitting', 'submitted', 'unknown') or (
                        entry.get('state') == 'settled' and not row['payload'].get('transcript'))
                self._write(row, status='uncertain' if unknown else 'error', stage='error',
                            error=str(exc), error_code='SUBMISSION_UNCERTAIN' if unknown else code, summary=summary,
                            retryable=not unknown and not summary.strip(), message='处理状态待核对' if unknown else '体验处理未完成',
                            finished_at=membership.iso(store.utcnow()),
                            claim='used' if summary.strip() else 'uncertain' if unknown else 'available')
            except (AccountError, TranscriptionError):
                log.error('guest trial %s state save pending', row['id'])
        except Exception:
            # Unknown provider/DB errors may include credentials or private response URLs.
            log.error('guest trial %s failed (details redacted)', row['id'])
            try:
                tid = row.get('transcription_id')
                entry = self.get_tm().ledger.entries().get(tid, {})
                unknown = entry.get('state') in ('submitting', 'submitted', 'unknown') or (
                    entry.get('state') == 'settled' and not row['payload'].get('transcript'))
                self._write(row, status='uncertain' if unknown else 'error', stage='error', summary=summary,
                            error='体验处理异常，请稍后查询或登录后继续', error_code='SUBMISSION_UNCERTAIN' if unknown else 'SUMMARY_FAILED',
                            retryable=not unknown and not summary.strip(), message='体验处理未完成',
                            finished_at=membership.iso(store.utcnow()),
                            claim='used' if summary.strip() else 'uncertain' if unknown else 'available')
            except (AccountError, TranscriptionError):
                log.error('guest trial %s recovery pending', row['id'])

    def recover(self):
        """Reconcile orphaned records; never enqueue ASR or AI automatically."""
        with self.lock:
            with store._cursor() as cur:
                cur.execute("SELECT * FROM guest_ai_trials WHERE state IN ('queued','running','uncertain')")
                rows = [_decode(row) for row in cur.fetchall()]
            entries = self.get_tm().ledger.entries() if rows else {}
            for row in rows:
                if row['id'] in self.active:
                    continue
                payload = row['payload']
                summary = payload.get('summary') or ''
                transcript = payload.get('transcript')
                tid = row.get('transcription_id')
                entry = entries.get(tid, {})
                unknown = entry.get('state') in ('submitting', 'submitted', 'unknown')
                if entry.get('state') == 'settled' and not transcript:
                    # Files only supplement a settled journal, never justify resending audio.
                    path = config.ASR_DIR / 'results' / str(tid) / 'transcript.srt'
                    if re.fullmatch(r'[a-f0-9]{32}', str(tid)) and path.is_file():
                        cues = parse_srt(path.read_text(encoding='utf-8'))
                        if cues:
                            transcript = result_payload(cues, 'asr')
                    if transcript is None:
                        unknown = True
                if row['state'] == 'uncertain' and unknown:
                    continue
                if not unknown and not summary.strip() and not tid and row['state'] == 'uncertain':
                    # Missing cost evidence after an uncertain write stays fail closed.
                    continue
                _save(row, status='uncertain' if unknown else 'error', stage='error', summary=summary, transcript=transcript,
                      error='语音识别状态待核对，请勿重复提交，可稍后查询或联系管理员' if unknown else
                            '服务中断，已保留生成内容' if summary.strip() else '服务中断，本次未生成总结，可重新提交',
                      error_code='SUBMISSION_UNCERTAIN' if unknown else 'INTERRUPTED',
                      retryable=not unknown and not summary.strip(), message='处理状态待核对' if unknown else '体验处理已中断',
                      finished_at=membership.iso(store.utcnow()), claim='used' if summary.strip() else 'uncertain' if unknown else 'available')
            with store._cursor() as cur:
                # Quota rows deliberately have no FK, so deleting text never resets a claim.
                cur.execute("DELETE FROM guest_ai_trials WHERE expires_at<=%s AND state IN ('done','error','uncertain')", (store.utcnow(),))
            self.ready = True
