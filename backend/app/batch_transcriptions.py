"""Session-owned batches orchestrate the existing bounded, budgeted ASR queue."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
import copy
import re
import threading
import time
import uuid
import zipfile

from . import config, tasks
from .errors import TranscriptionError, VideoError


@dataclass
class BatchTranscript:
    id: str
    owner: str
    urls: list[str]
    status: str = 'queued'
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    items: list[dict] = field(default_factory=list)


class BatchTranscriptionManager:
    def __init__(self, transcription_manager):
        self.transcription_manager = transcription_manager
        self.lock = threading.RLock()
        self.jobs = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='batch-transcript')
        self.stopping = threading.Event()

    def cleanup(self):
        with self.lock:
            for key, job in list(self.jobs.items()):
                if job.finished_at and time.time() - job.finished_at > config.FILE_TTL_SECONDS:
                    del self.jobs[key]

    def submit(self, owner, texts, max_links=None, plan_name=None):
        urls = tasks.dedupe_urls(texts)
        cap = min(max_links or config.MAX_BATCH, config.MAX_BATCH)
        if urls and len(urls) > cap and plan_name:
            raise TranscriptionError('BATCH_LIMIT', f'{plan_name}单次最多批量处理 {cap} 条链接，当前 {len(urls)} 条，'
                                     '可在定价页升级会员提高上限', status=403)
        if not urls or len(urls) > cap:
            raise TranscriptionError('INVALID_BATCH', f'请输入 1～{cap} 条有效链接')
        self.cleanup()
        with self.lock:
            for job in self.jobs.values():
                if job.owner == owner and job.urls == urls:
                    return self.public(job)
            if sum(j.status not in ('done', 'error') for j in self.jobs.values()) >= 10:
                raise TranscriptionError('QUEUE_FULL', '批量提取任务已满，请稍后再试', True, 429)
            job = BatchTranscript(uuid.uuid4().hex, owner, urls)
            job.items = [dict(url=u, status='queued', stage='queued', title='', message='等待提取',
                              error=None, result=None, transcription_id=None) for u in urls]
            self.jobs[job.id] = job
            self.pool.submit(self._run, job)
            return self.public(job)

    def public(self, job):
        with self.lock:
            items = copy.deepcopy(job.items)
            return dict(id=job.id, status=job.status, created_at=job.created_at,
                        finished_at=job.finished_at, ttl_seconds=config.FILE_TTL_SECONDS,
                        total=len(items), completed=sum(i['status'] in ('done', 'error') for i in items),
                        succeeded=sum(i['status'] == 'done' for i in items),
                        failed=sum(i['status'] == 'error' for i in items), items=items)

    def get(self, job_id, owner):
        self.cleanup()
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.owner != owner:
                raise TranscriptionError('NOT_FOUND', '批量任务不存在或已过期', status=404)
            return job

    def _run(self, job):
        with self.lock:
            job.status = 'running'
        for item in job.items:
            try:
                if self.stopping.is_set():
                    raise VideoError('服务已停止，请核对原转写任务后再操作')
                manager = self.transcription_manager()
                # Server-side creation does not bypass queue limits, ownership, dedupe or billing.
                child = manager.submit(job.owner, item['url'], allow_asr=True)
                while True:
                    child = manager.get(child.id, job.owner)
                    with self.lock:
                        item.update(status=child.status, stage=child.stage, title=child.title,
                                    message=child.message, error=child.error, transcription_id=child.id)
                    if child.status in ('done', 'error'):
                        with self.lock:
                            item['result'] = copy.deepcopy(child.result) if child.status == 'done' else None
                        break
                    if self.stopping.wait(.5):
                        raise VideoError('服务已停止，请核对原转写任务后再操作')
            except Exception as exc:
                with self.lock:
                    item.update(status='error', stage='error', error=str(exc)[:200]
                                if isinstance(exc, (VideoError, TranscriptionError)) else '提取失败，请稍后核对任务')
        with self.lock:
            job.status = 'done' if any(i['status'] == 'done' for i in job.items) else 'error'
            job.finished_at = time.time()

    def archive(self, job_id, owner):
        job = self.get(job_id, owner)
        snapshot = self.public(job)
        if snapshot['status'] not in ('done', 'error'):
            raise TranscriptionError('BATCH_RUNNING', '请等待本批次提取结束后再打包', status=409)
        if not snapshot['succeeded']:
            raise TranscriptionError('EMPTY_BATCH', '没有可打包的字幕结果', status=409)
        output = BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for index, item in enumerate(snapshot['items'], 1):
                if item['status'] != 'done' or not item['result']:
                    continue
                title = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', item['title'])[:80].strip(' .') or '字幕'
                archive.writestr(f'{index:02d}_{title}.srt', item['result']['srt'])
        return output.getvalue()
