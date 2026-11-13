"""Key-only Fun-ASR-Flash HTTP adapter; submissions are never retried."""
import base64
import json
import logging
import math
import time
import uuid

import httpx

from . import config
from .errors import TranscriptionError
from .subtitles import Cue, timestamp_from_ms

log = logging.getLogger('freevideo.asr_flash')


def snapshot_cues(sentences, full_text, offset_ms=0):
    """Replace cumulative snapshots sharing a start time, retaining real word times."""
    latest = {}
    for sentence in sentences:
        latest[sentence.get("begin_time")] = sentence
    ordered = sorted(latest.values(), key=lambda s: s["begin_time"])
    if "".join(s["text"] for s in ordered) != full_text:
        raise TranscriptionError("INVALID_RESULT", "识别文字与时间轴不完整，请管理员核对")
    cues, group = [], []
    previous = -1

    def flush():
        if group:
            cues.append(Cue(timestamp_from_ms(group[0][0] + offset_ms),
                            timestamp_from_ms(group[-1][1] + offset_ms),
                            "".join(w[2] for w in group)))
            group.clear()

    for sentence in ordered:
        words = sentence.get("words") or []
        if not words and sentence.get("text"):
            words = [sentence]
        rebuilt = ""
        for word in words:
            start, end = word.get("begin_time"), word.get("end_time")
            text = word.get("text")
            punctuation = word.get("punctuation") or ""
            if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                    or start < previous or not isinstance(text, str) or not isinstance(punctuation, str)):
                raise TranscriptionError("INVALID_RESULT", "识别结果时间轴无效，请管理员核对")
            previous = start
            text += punctuation
            rebuilt += text
            if group and (sum(len(w[2]) for w in group) + len(text) > 36 or end - group[0][0] > 8000):
                flush()
            group.append((start, end, text))
            if punctuation and sum(len(w[2]) for w in group) >= 12:
                flush()
        if rebuilt != sentence["text"]:
            raise TranscriptionError("INVALID_RESULT", "识别词时间轴与文字不一致，请管理员核对")
        flush()
    return cues


class FunASRFlash:
    direct = True

    @staticmethod
    def configured():
        return bool(config.DASHSCOPE_API_KEY and config.ASR_MODEL == "fun-asr-flash-2026-06-15"
                    and config.DASHSCOPE_BASE_URL.startswith("https://"))

    def recognize(self, path, on_submit, cancel, duration=None, offset_ms=0):
        from .asr import Recognition
        if duration is not None and duration > 300:
            raise TranscriptionError("AUDIO_TOO_LONG", "快速接口单段音频不能超过 5 分钟")
        audio_format = "wav" if path.suffix.lower() == ".wav" else "mp3"
        payload = {"model": config.ASR_MODEL, "input": {"messages": [{"role": "user", "content": [{
            "type": "input_audio", "input_audio": {
                "data": f"data:audio/{audio_format};base64," + base64.b64encode(path.read_bytes()).decode("ascii")}
        }]}]}, "parameters": {"format": audio_format, "sample_rate": "16000"}}
        if cancel.is_set():
            raise TranscriptionError("CANCELLED", "识别已停止")
        started = time.monotonic()
        sentences, full_text, usage, final = [], "", None, False
        on_submit(uuid.uuid4().hex)  # persist before any request bytes can leave
        try:
            with httpx.stream("POST", config.DASHSCOPE_BASE_URL + "/services/aigc/multimodal-generation/generation",
                              headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
                                       "X-DashScope-SSE": "enable"}, json=payload,
                              timeout=httpx.Timeout(min(config.ASR_TIMEOUT, 180), connect=20, write=60)) as response:
                if response.status_code in (400, 401, 403, 404, 422, 429):
                    code = "CLOUD_AUTH" if response.status_code in (401, 403) else "CLOUD_REJECTED"
                    raise TranscriptionError(code, "识别请求被拒绝，请检查 Key、模型权限和地域配置")
                if response.is_error:
                    log.warning('Flash ASR HTTP failure: status=%s', response.status_code)
                response.raise_for_status()
                size = 0
                for line in response.iter_lines():
                    size += len(line)
                    if size > 20 * 1024 * 1024:
                        raise TranscriptionError("INVALID_RESULT", "识别结果超过大小限制")
                    if cancel.is_set() or time.monotonic() - started > config.ASR_TIMEOUT:
                        raise TranscriptionError("CLOUD_NETWORK", "识别连接已中断，需核对用量")
                    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                        continue
                    event = json.loads(line[5:].strip())
                    if event.get("code") and event["code"] != "Success":
                        # The raw response body can contain private data; log only a bounded error code.
                        code = str(event['code'])
                        safe_code = code if len(code) <= 64 and all(c.isalnum() or c in '._-' for c in code) else 'REDACTED'
                        log.warning('Flash ASR service error: code=%s', safe_code)
                        raise TranscriptionError("CLOUD_NETWORK", "识别服务处理异常，请管理员核对")
                    output = event.get("output") or {}
                    sentence = output.get("sentence") or {}
                    if 'sentence_end' in sentence:
                        final = sentence['sentence_end'] is True
                    if isinstance(output.get("text"), str):
                        full_text = output["text"]
                    if final and sentence.get("text"):
                        sentences.append(sentence)
                    value = (event.get("usage") or {}).get("duration")
                    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                        usage = max(usage or 0, value)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            log.warning('Flash ASR response failed: exception=%s elapsed_seconds=%.1f',
                        type(exc).__name__, time.monotonic() - started)
            raise TranscriptionError("CLOUD_NETWORK", "识别连接或结果异常，请管理员核对用量") from None
        # usage is a provider processing/billing metric reported at sentence boundaries,
        # not a proof that all input seconds contain speech. A shorter usage value must
        # not turn a normally closed response with final, consistent text into a failure.
        if not final:
            log.warning('Flash ASR incomplete response: final=%s expected_seconds=%s usage_seconds=%s',
                        final, duration, usage)
            raise TranscriptionError("CLOUD_NETWORK", "识别结果尚未完整返回，请管理员核对用量")
        cues = snapshot_cues(sentences, full_text, offset_ms)
        return Recognition("SUCCEEDED", cues, usage)
