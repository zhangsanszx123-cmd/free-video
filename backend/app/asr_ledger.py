"""Single-process, fail-closed budget reservations and cleanup journal, no transcript text."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP
import json
import math
import os
from pathlib import Path
import threading
import time

from . import config
from .errors import TranscriptionError


def today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or config.ASR_DIR / "usage.json"
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "entries": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            assert data["version"] == 1 and isinstance(data["entries"], dict)
            for e in data["entries"].values():
                assert e["state"] in {"reserved", "submitting", "submitted", "settled", "released", "unknown"}
                for key in ("reserved", "charged"):
                    assert Decimal(e[key]).is_finite() and Decimal(e[key]) >= 0
                assert isinstance(e["date"], str) and isinstance(e["created_at"], (int, float))
            return data
        except (ValueError, KeyError, TypeError, AssertionError, OSError):
            raise TranscriptionError("LEDGER_UNAVAILABLE", "识别用量账本异常，已暂停收费提交，请联系管理员", status=503) from None

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        except OSError:
            raise TranscriptionError("LEDGER_UNAVAILABLE", "识别用量账本写入失败，已暂停收费提交", status=503) from None

    def entries(self):
        with self.lock:
            return copy.deepcopy(self._read()["entries"])

    @staticmethod
    def _used(entries):
        # Unresolved reservations remain held across midnight and process restarts.
        return sum((Decimal(e["charged"]) if e["state"] == "settled" else Decimal(e["reserved"]))
                   for e in entries.values() if (e["state"] == "settled" and e["date"] == today())
                   or e["state"] in ("reserved", "submitting", "submitted", "unknown"))

    def reserve(self, job_id: str, duration: float, object_key: str | None, fingerprint: str | None = None):
        try:
            price, budget = Decimal(config.ASR_PRICE_PER_SECOND), Decimal(config.ASR_DAILY_BUDGET)
            if (not price.is_finite() or price <= 0 or not budget.is_finite() or budget < 0
                    or not math.isfinite(duration) or duration <= 0):
                raise ValueError()
            amount = (Decimal(math.ceil(duration)) * price).quantize(Decimal("0.000001"), rounding=ROUND_UP)
        except (ArithmeticError, ValueError, TypeError):
            raise TranscriptionError("ASR_CONFIG", "识别计费单价配置无效", status=503)
        with self.lock:
            data = self._read()
            if job_id in data["entries"]:
                raise TranscriptionError("DUPLICATE_RESERVATION", "该任务已经预占识别额度")
            if fingerprint and any(e.get("fingerprint") == fingerprint and e["state"] in ("reserved", "submitting", "submitted", "unknown") for e in data["entries"].values()):
                raise TranscriptionError("SUBMISSION_UNCERTAIN", "相同视频存在待核对的云端任务，请勿重复提交")
            if self._used(data["entries"]) + amount > budget:
                raise TranscriptionError("BUDGET_EXCEEDED", "今日识别额度不足，请明天再试或联系管理员")
            data["entries"][job_id] = {
                "date": today(), "created_at": time.time(), "state": "reserved",
                "reserved": str(amount), "charged": "0", "price": config.ASR_PRICE_PER_SECOND,
                "duration": duration, "task_id": None, "object_key": object_key,
                "provider": config.ASR_PROVIDER, "model": config.ASR_MODEL,
                "base_url": config.DASHSCOPE_BASE_URL,
                "bucket": config.OSS_BUCKET, "endpoint": config.OSS_ENDPOINT,
                "fingerprint": fingerprint,
                "transport": ("direct-http" if config.ASR_PROVIDER == "fun-asr-flash" else
                              "stream" if config.ASR_PROVIDER == "paraformer-realtime" else "file"),
            }
            self._write(data)

    def update(self, job_id, **fields):
        with self.lock:
            data = self._read()
            data["entries"][job_id].update(fields)
            self._write(data)

    def settle(self, job_id, duration: float | None = None):
        with self.lock:
            data = self._read()
            entry = data["entries"][job_id]
            if duration is not None and (not math.isfinite(duration) or duration < 0):
                raise ValueError("invalid metered duration")
            charged = (Decimal(math.ceil(duration)) * Decimal(entry["price"])) if duration is not None else Decimal(entry["reserved"])
            entry.update(state="settled", charged=str(charged), actual_duration=duration)
            self._write(data)
