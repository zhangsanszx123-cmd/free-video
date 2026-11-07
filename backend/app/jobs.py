"""In-memory job queue (no database). Files live in DOWNLOAD_DIR/<job_id>/ and expire after a TTL."""
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import config
from .ai import AIDisabled
from .downloader import VideoError

log = logging.getLogger("freevideo.jobs")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | processing | done | error
    progress: float = 0
    speed: float | None = None
    eta: int | None = None
    title: str | None = None
    thumbnail: str | None = None
    message: str | None = None
    error: str | None = None
    filename: str | None = None
    items: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    filepath: Path | None = field(default=None, repr=False)

    @property
    def dir(self) -> Path:
        return config.DOWNLOAD_DIR / self.id

    def update(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("filepath")
        d["ready"] = self.status == "done" and self.filepath is not None
        return d


class JobManager:
    def __init__(self, workers: int = config.MAX_WORKERS):
        self.jobs: dict[str, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._cleaner: threading.Thread | None = None

    def submit(self, kind: str, fn: Callable[[Job], Path], title: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title)
        self.jobs[job.id] = job
        self.pool.submit(self._run, job, fn)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def _run(self, job: Job, fn: Callable[[Job], Path]):
        job.update(status="running")
        try:
            path = fn(job)
            job.update(status="done", progress=100, filepath=path, filename=path.name, speed=None, eta=None, message=None)
        except (VideoError, AIDisabled) as e:
            job.update(status="error", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job.id)
            job.update(status="error", error=f"处理失败：{e}"[:200])

    def cleanup(self, now: float | None = None):
        now = now or time.time()
        for job_id, job in list(self.jobs.items()):
            if now - job.created_at > config.FILE_TTL_SECONDS and job.status in ("done", "error"):
                shutil.rmtree(job.dir, ignore_errors=True)
                self.jobs.pop(job_id, None)
        if config.DOWNLOAD_DIR.exists():  # orphan dirs from previous runs
            for d in config.DOWNLOAD_DIR.iterdir():
                if d.name not in self.jobs and now - d.stat().st_mtime > config.FILE_TTL_SECONDS:
                    shutil.rmtree(d, ignore_errors=True)

    def start_cleaner(self, interval: int = 60):
        def loop():
            while True:
                time.sleep(interval)
                try:
                    self.cleanup()
                except Exception:  # noqa: BLE001
                    log.exception("cleanup failed")

        if not self._cleaner:
            self._cleaner = threading.Thread(target=loop, daemon=True, name="cleaner")
            self._cleaner.start()
