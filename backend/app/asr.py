"""Replaceable file-ASR provider. No SDK details escape this module."""
from dataclasses import dataclass
import math
from typing import Protocol
from urllib.parse import urlparse

import httpx

from . import config
from .errors import TranscriptionError
from .subtitles import Cue, timestamp_from_ms
from .asr_realtime import ParaformerRealtime
from .asr_flash import FunASRFlash


@dataclass
class Recognition:
    status: str
    cues: list[Cue] | None = None
    duration: float | None = None
    language: str | None = None


class Provider(Protocol):
    @staticmethod
    def configured() -> bool: ...
    def submit(self, audio_url: str) -> str: ...
    def query(self, task_id: str) -> Recognition: ...


def normalize_sentences(data: dict) -> list[Cue]:
    sentences = [s for t in data.get("transcripts", []) if t.get("channel_id", 0) == 0
                 for s in t.get("sentences", [])]
    cues = []
    previous = -1
    for sentence in sentences:
        text = sentence.get("text", "")
        if not isinstance(text, str):
            raise TranscriptionError("INVALID_RESULT", "识别结果文字格式无效")
        if not text.strip():
            continue
        start, end = sentence.get("begin_time"), sentence.get("end_time")
        if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                or start < previous):
            raise TranscriptionError("INVALID_RESULT", "识别结果时间轴无效，请联系管理员")
        previous = start
        cues.append(Cue(timestamp_from_ms(start), timestamp_from_ms(end), text.strip()))
    return cues


class Paraformer:
    """Documented DashScope async HTTP API; never retry a submission automatically."""
    @staticmethod
    def configured() -> bool:
        return bool(config.DASHSCOPE_API_KEY)

    def _request(self, method, path, **kwargs):
        try:
            response = httpx.request(method, config.DASHSCOPE_BASE_URL + path,
                                     headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
                                              "X-DashScope-Async": "enable"}, timeout=30, **kwargs)
        except httpx.HTTPError:
            raise TranscriptionError("CLOUD_NETWORK", "连接识别服务失败，请稍后查询任务状态", True) from None
        if response.status_code >= 500 or response.status_code == 408:
            raise TranscriptionError("CLOUD_NETWORK", "识别服务暂时不可用，请稍后查询", True)
        if response.status_code in (401, 403):
            raise TranscriptionError("CLOUD_AUTH", "识别服务鉴权失败，请管理员检查百炼配置")
        if response.status_code == 429:
            raise TranscriptionError("CLOUD_LIMIT", "识别服务请求限流，请稍后重试", True)
        if not response.is_success:
            raise TranscriptionError("CLOUD_REJECTED", "识别服务拒绝了请求，请检查模型、地域和音频配置")
        try:
            return response.json()
        except ValueError:
            raise TranscriptionError("CLOUD_NETWORK", "识别服务返回异常，暂无法确认任务状态", True) from None

    def submit(self, audio_url: str) -> str:
        data = self._request("POST", "/services/audio/asr/transcription", json={
            "model": config.ASR_MODEL, "input": {"file_urls": [audio_url]},
            "parameters": {"channel_id": [0], "disfluency_removal_enabled": False,
                           "diarization_enabled": False},
        })
        task_id = data.get("output", {}).get("task_id")
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise TranscriptionError("CLOUD_NETWORK", "识别任务提交状态不明，已保留额度，请管理员核对")
        return task_id

    def query(self, task_id: str) -> Recognition:
        from urllib.parse import quote
        data = self._request("GET", "/tasks/" + quote(task_id, safe=""))
        output = data.get("output", {})
        status = output.get("task_status")
        duration = data.get("usage", {}).get("duration")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            duration = None
        if status in ("PENDING", "RUNNING"):
            return Recognition(status)
        if status in ("FAILED", "CANCELED"):
            return Recognition("FAILED", duration=duration)
        if status != "SUCCEEDED":
            raise TranscriptionError("CLOUD_NETWORK", "无法确认云端任务状态，请管理员核对", True)
        results = output.get("results") or []
        if not results or results[0].get("subtask_status") != "SUCCEEDED":
            return Recognition("FAILED", duration=duration)
        # Result URLs are service supplied, fetched without credentials. Never log them.
        url = results[0].get("transcription_url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".aliyuncs.com"):
            raise TranscriptionError("INVALID_RESULT", "识别结果地址无效")
        try:
            with httpx.stream("GET", url, timeout=30, follow_redirects=False) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 20 * 1024 * 1024:
                        raise TranscriptionError("INVALID_RESULT", "识别结果超过大小限制")
            import json
            cues = normalize_sentences(json.loads(content))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise TranscriptionError("RESULT_DOWNLOAD", "识别已完成，但结果获取失败，请稍后查询", True) from None
        return Recognition("SUCCEEDED", cues=cues, duration=duration)


# Add a factory here to support another provider; UI and jobs use only Provider/Recognition.
PROVIDERS = {"paraformer": Paraformer, "paraformer-realtime": ParaformerRealtime,
             "fun-asr-flash": FunASRFlash}


def is_direct() -> bool:
    return bool(getattr(PROVIDERS.get(config.ASR_PROVIDER), "direct", False))


def is_streaming() -> bool:
    return bool(getattr(PROVIDERS.get(config.ASR_PROVIDER), "streaming", False))


def get_provider() -> Provider | ParaformerRealtime | FunASRFlash:
    factory = PROVIDERS.get(config.ASR_PROVIDER)
    if not factory:
        raise TranscriptionError("ASR_CONFIG", "识别服务类型未配置正确", status=503)
    return factory()


def enabled() -> bool:
    factory = PROVIDERS.get(config.ASR_PROVIDER)
    if not factory or not factory.configured():
        return False
    if is_streaming() or is_direct():
        return True
    return bool(config.OSS_BUCKET
                and config.OSS_ACCESS_KEY_ID and config.OSS_ACCESS_KEY_SECRET
                and config.OSS_URL_TTL >= config.ASR_TIMEOUT + 300)


def require_enabled():
    if not enabled():
        raise TranscriptionError("ASR_DISABLED", "音频转文字尚未配置，请联系管理员；平台字幕仍可正常提取", status=503)
