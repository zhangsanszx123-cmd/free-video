"""FastAPI router (/api/learn/*) for AI video summary, mind map, and Q&A."""
from collections.abc import Iterable
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from . import ai, ai_learning, asr, config, downloader, transcription_auth, usage
from .errors import AccountError, EmptySubtitles, NoSubtitles, TranscriptionError, VideoError
from .learning_text import compact_from_cues, compact_from_timed_text
from .transcriptions import read_subtitles

log = logging.getLogger("freevideo.ai_learning")
router = APIRouter(prefix="/api/learn", tags=["ai-learning"])

_rate_lock = threading.Lock()
_peer_hits: dict[str, list[float]] = {}


class NeedAsrConfirmation(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LearnSummaryReq(BaseModel):
    url: str = Field(max_length=2000)
    mode: Literal["general", "study", "deep"] = "general"
    transcript: str | None = Field(default=None, max_length=300000)
    transcription_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=300)
    lang: str | None = Field(default=None, max_length=32)


class LearnMindmapReq(BaseModel):
    url: str = Field(default="", max_length=2000)
    transcript: str | None = Field(default=None, max_length=300000)
    summary: str | None = Field(default=None, max_length=100000)
    transcription_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=300)
    lang: str | None = Field(default=None, max_length=32)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class LearnChatReq(BaseModel):
    url: str = Field(max_length=2000)
    messages: list[ChatTurn] = Field(min_length=1, max_length=20)
    transcript: str | None = Field(default=None, max_length=300000)
    transcription_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=300)
    lang: str | None = Field(default=None, max_length=32)


def _uid(request: Request) -> int:
    return request.state.account_user['id']


def _check_ai_enabled():
    if not ai.enabled():
        raise HTTPException(status_code=503, detail="AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")


def _check_rate_limit(request: Request):
    limit = int(os.getenv("AI_LEARNING_RATE_LIMIT", "20"))
    peer = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        for k in list(_peer_hits):
            _peer_hits[k] = [t for t in _peer_hits[k] if now - t < 60]
            if not _peer_hits[k]:
                del _peer_hits[k]
        hits = _peer_hits.get(peer, [])
        if len(hits) >= limit:
            raise HTTPException(status_code=429, detail="AI 学习请求过于频繁，请一分钟后再试")
        _peer_hits.setdefault(peer, []).append(now)


def _get_transcription_manager():
    main_mod = sys.modules.get("app.main") or sys.modules.get("backend.app.main")
    return getattr(main_mod, "transcription_manager", None)


def _lookup_owned_transcription(request: Request, clean_url: str, explicit_id: str | None):
    tm = _get_transcription_manager()
    if tm is None:
        if explicit_id:
            raise TranscriptionError("NOT_FOUND", "转写任务不存在或已过期", status=404)
        return None
    if explicit_id:
        transcription_auth.check_origin(request)
        user = getattr(request.state, 'account_user', None)
        owner = f"user:{user['id']}" if user else transcription_auth.owner(request)
        job = tm.get(explicit_id, owner)
        if job.status != "done" or not job.result:
            raise VideoError("语音转写尚未完成，请等待转写结束后再试")
        return job
    user = getattr(request.state, 'account_user', None)
    if not user and transcription_auth.COOKIE not in request.cookies:
        return None
    try:
        transcription_auth.check_origin(request)
        owner = f"user:{user['id']}" if user else transcription_auth.owner(request)
    except TranscriptionError:
        return None
    with tm.lock:
        candidates = [
            j for j in tm.jobs.values()
            if j.owner == owner and j.status == "done" and j.result and j.url == clean_url
        ]
    return max(candidates, key=lambda j: j.created_at) if candidates else None


def resolve_transcript(
    request: Request,
    url: str,
    title: str | None = None,
    transcript: str | None = None,
    transcription_id: str | None = None,
    lang: str | None = None,
) -> tuple[str, str, str]:
    """Resolve transcript in strict order:
    1) client-supplied loaded transcript -> 2) same-session owned ASR job -> 3) free platform subtitles.
    Never triggers paid cloud ASR implicitly.
    """
    if transcript and transcript.strip():
        compacted = compact_from_timed_text(transcript)
        if compacted:
            return (title or "视频学习笔记", compacted, "loaded_transcript")

    clean_url = downloader.extract_url(url) if url and url.strip() else ""
    if transcription_id or clean_url:
        owned = _lookup_owned_transcription(request, clean_url, transcription_id)
        if owned and owned.result:
            raw = owned.result.get("timed_text") or owned.result.get("text") or ""
            compacted = compact_from_timed_text(raw)
            if compacted:
                return (
                    title or owned.title or "视频学习笔记",
                    compacted,
                    owned.result.get("source") or "asr",
                )

    if not clean_url:
        raise VideoError("请粘贴有效的视频分享链接")

    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=config.DOWNLOAD_DIR) as tmp:
            info, cues, metadata = read_subtitles(clean_url, Path(tmp), lang)
    except (NoSubtitles, EmptySubtitles) as e:
        raise NeedAsrConfirmation(str(e)) from e

    compacted = compact_from_cues(cues)
    if not compacted:
        raise NeedAsrConfirmation("字幕内容为空，可使用音频转文字后继续总结")
    return (
        title or info.get("title") or "视频学习笔记",
        compacted,
        metadata.get("source") or "platform_subtitle",
    )


@router.post(
    "/summary",
    response_class=EventSourceResponse,
    dependencies=[Depends(_check_ai_enabled), Depends(_check_rate_limit)],
)
def learn_summary(req: LearnSummaryReq, request: Request) -> Iterable[ServerSentEvent]:
    ticket = None
    keep = False
    try:
        ticket = usage.ai_begin(_uid(request), req.url, req.title or "")
        if not (req.transcript and req.transcript.strip()):
            yield ServerSentEvent(event="status", data="正在获取视频字幕文稿…")
        resolved_title, compacted, source = resolve_transcript(
            request,
            url=req.url,
            title=req.title,
            transcript=req.transcript,
            transcription_id=req.transcription_id,
            lang=req.lang,
        )
        segmented = len(compacted) > ai_learning.MAX_DIRECT_CHARS
        yield ServerSentEvent(
            event="meta",
            data={
                "title": resolved_title,
                "source": source,
                "chars": len(compacted),
                "segmented": segmented,
                "mode": req.mode,
            },
        )
        for kind, value in ai_learning.summarize_events(resolved_title, compacted, mode=req.mode):
            keep = keep or kind == "delta"
            yield ServerSentEvent(event=kind, data=value)
        yield ServerSentEvent(event="done", data=True)
    except NeedAsrConfirmation as e:
        yield ServerSentEvent(
            event="need_asr",
            data={"message": e.message, "asr_enabled": asr.enabled()},
        )
    except (AccountError, TranscriptionError) as e:
        yield ServerSentEvent(event="error", data=str(e))
    except (VideoError, ai.AIDisabled) as e:
        yield ServerSentEvent(event="error", data=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("learn_summary failed")
        yield ServerSentEvent(event="error", data=f"AI 总结生成失败：{e}"[:200])
    finally:
        if keep:
            usage.ai_commit(ticket)
        else:
            usage.ai_release(ticket)


@router.post("/mindmap", dependencies=[Depends(_check_ai_enabled), Depends(_check_rate_limit)])
def learn_mindmap(req: LearnMindmapReq, request: Request):
    ticket = usage.ai_begin(_uid(request), req.url, req.title or "")
    keep = False
    try:
        resolved_title = req.title or "视频知识导图"
        compacted = ""
        source = "summary"
        if req.transcript and req.transcript.strip():
            compacted = compact_from_timed_text(req.transcript)
            source = "loaded_transcript"
        elif not (req.summary and req.summary.strip()):
            resolved_title, compacted, source = resolve_transcript(
                request,
                url=req.url,
                title=req.title,
                transcript=req.transcript,
                transcription_id=req.transcription_id,
                lang=req.lang,
            )
        markdown = ai_learning.generate_mindmap(
            title=resolved_title,
            transcript=compacted,
            summary=req.summary or "",
        )
        keep = True
        return {"title": resolved_title, "markdown": markdown, "source": source}
    except NeedAsrConfirmation as e:
        return JSONResponse(
            status_code=409,
            content={"detail": e.message, "code": "NEED_ASR", "asr_enabled": asr.enabled()},
        )
    except TranscriptionError:
        raise
    except (VideoError, ai.AIDisabled) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("learn_mindmap failed")
        raise HTTPException(status_code=500, detail="思维导图生成失败，请稍后重试") from e
    finally:
        if keep:
            usage.ai_commit(ticket)
        else:
            usage.ai_release(ticket)


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    dependencies=[Depends(_check_ai_enabled), Depends(_check_rate_limit)],
)
def learn_chat(req: LearnChatReq, request: Request) -> Iterable[ServerSentEvent]:
    ticket = None
    chat_token = None
    keep = False
    try:
        ticket = usage.ai_begin(_uid(request), req.url, req.title or "")
        chat_token = usage.chat_begin(_uid(request))
        resolved_title, compacted, _ = resolve_transcript(
            request,
            url=req.url,
            title=req.title,
            transcript=req.transcript,
            transcription_id=req.transcription_id,
            lang=req.lang,
        )
        turns = [{"role": m.role, "content": m.content} for m in req.messages]
        for delta in ai_learning.chat_stream(resolved_title, compacted, turns):
            keep = True
            yield ServerSentEvent(event="delta", data=delta)
        yield ServerSentEvent(event="done", data=True)
    except NeedAsrConfirmation as e:
        yield ServerSentEvent(
            event="need_asr",
            data={"message": e.message, "asr_enabled": asr.enabled()},
        )
    except (AccountError, TranscriptionError) as e:
        yield ServerSentEvent(event="error", data=str(e))
    except (VideoError, ai.AIDisabled) as e:
        yield ServerSentEvent(event="error", data=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("learn_chat failed")
        yield ServerSentEvent(event="error", data=f"AI 追问失败：{e}"[:200])
    finally:
        if keep:
            usage.ai_commit(ticket)
        else:
            usage.ai_release(ticket)
            usage.chat_release(chat_token)
