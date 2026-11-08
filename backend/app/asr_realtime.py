"""Paraformer duplex WebSocket transport: API Key only, no hosted audio URL."""
import json
import math
from pathlib import Path
import threading
import time
from typing import Callable

from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from . import config
from .errors import TranscriptionError


class ParaformerRealtime:
    streaming = True

    @staticmethod
    def configured() -> bool:
        return bool(config.DASHSCOPE_API_KEY and config.ASR_MODEL == "paraformer-realtime-v2"
                    and config.DASHSCOPE_WS_URL.startswith("wss://"))

    def recognize(self, pcm: Path, on_submit: Callable[[str], None], cancel: threading.Event):
        from .asr import Recognition, normalize_sentences
        import uuid

        task_id = str(uuid.uuid4())
        deadline = time.monotonic() + config.ASR_TIMEOUT
        stop = threading.Event()
        finish_sent = threading.Event()
        sender = None
        sender_error = []
        sentences = {}
        duration = None

        def command(action):
            payload = {"input": {}}
            if action == "run-task":
                payload.update(task_group="audio", task="asr", function="recognition", model=config.ASR_MODEL,
                               parameters={"format": "pcm", "sample_rate": 16000,
                                           "disfluency_removal_enabled": False,
                                           "semantic_punctuation_enabled": False})
            return json.dumps({"header": {"action": action, "task_id": task_id, "streaming": "duplex"},
                               "payload": payload})

        def send_audio(ws):
            try:
                with pcm.open("rb") as source:
                    while not stop.is_set() and not cancel.is_set():
                        chunk = source.read(3200)  # 100ms mono 16kHz s16le, bounded memory
                        if not chunk:
                            finish_sent.set()
                            ws.send(command("finish-task"))
                            return
                        ws.send(chunk)
                        stop.wait(len(chunk) / 32000)  # stream at approximately real time
            except Exception:
                sender_error.append(True)

        try:
            with connect(config.DASHSCOPE_WS_URL,
                         additional_headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"},
                         open_timeout=20, close_timeout=3, max_size=2 * 1024 * 1024,
                         ping_interval=20, ping_timeout=20) as ws:
                if cancel.is_set():
                    raise TranscriptionError("STREAM_CANCELLED", "识别连接已停止，请稍后重试", True)
                # Journal before sending run-task: connection loss afterwards is ambiguous.
                on_submit(task_id)
                ws.send(command("run-task"))
                started = False
                while time.monotonic() < deadline and not cancel.is_set():
                    if sender_error:
                        raise TranscriptionError("STREAM_INTERRUPTED", "音频发送中断，已保留额度，请管理员核对")
                    try:
                        raw = ws.recv(timeout=min(1, max(0.01, deadline - time.monotonic())))
                    except TimeoutError:
                        continue
                    event = json.loads(raw)
                    header = event.get("header", {})
                    if header.get("task_id") != task_id:
                        raise TranscriptionError("INVALID_RESULT", "识别服务返回了不匹配的任务标识")
                    name = header.get("event")
                    payload = event.get("payload") or {}
                    usage = (payload.get("usage") or {}).get("duration")
                    if type(usage) in (int, float) and math.isfinite(usage) and usage >= 0:
                        duration = max(duration or 0, usage)  # cumulative, not sum per sentence
                    if name == "task-started":
                        if started:
                            raise TranscriptionError("INVALID_RESULT", "识别服务重复启动任务")
                        started = True
                        sender = threading.Thread(target=send_audio, args=(ws,), daemon=True, name="asr-audio")
                        sender.start()
                    elif name == "result-generated":
                        if not started:
                            raise TranscriptionError("INVALID_RESULT", "识别服务事件顺序异常")
                        sentence = (payload.get("output") or {}).get("sentence") or {}
                        if sentence.get("heartbeat") or not sentence.get("sentence_end"):
                            continue
                        if not sentence.get("text", "").strip():
                            continue
                        # The documented final event may omit end_time; word end times
                        # are valid evidence. Never invent a timing from text length.
                        if sentence.get("end_time") is None:
                            ends = [w["end_time"] for w in sentence.get("words", []) if type(w.get("end_time")) is int]
                            if ends:
                                sentence = {**sentence, "end_time": max(ends)}
                        normalize_sentences({"transcripts": [{"sentences": [sentence]}]})
                        sentences[(sentence["begin_time"], sentence["end_time"])] = sentence
                    elif name == "task-failed":
                        # Explicit terminal failure: keep known usage or conservatively
                        # account the reservation if audio may have been sent.
                        return Recognition("FAILED", duration=duration if started else 0)
                    elif name == "task-finished":
                        if not started or not finish_sent.is_set() or sender_error:
                            raise TranscriptionError("STREAM_INCOMPLETE", "识别提前结束，未返回完整音频结果")
                        ordered = [sentences[k] for k in sorted(sentences)]
                        cues = normalize_sentences({"transcripts": [{"sentences": ordered}]})
                        return Recognition("SUCCEEDED", cues=cues, duration=duration)
                raise TranscriptionError("STREAM_INTERRUPTED", "识别超时或连接已停止，已保留额度，请管理员核对")
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise TranscriptionError("CLOUD_AUTH", "百炼 Key 无效或没有模型权限，请检查配置") from None
            raise TranscriptionError("CLOUD_NETWORK", "无法建立识别连接，请稍后重试", True) from None
        except (OSError, TimeoutError, WebSocketException):
            raise TranscriptionError("CLOUD_NETWORK", "识别连接中断，请管理员核对后重试", True) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise TranscriptionError("INVALID_RESULT", "识别服务返回的数据格式异常") from None
        finally:
            stop.set()
            if sender:
                sender.join(timeout=5)
