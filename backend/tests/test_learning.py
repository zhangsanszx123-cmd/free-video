"""Unit tests for AI video learning modules (learning_text, ai_learning, ai_learning_api)."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import ai_learning, ai_learning_api, asr, config, downloader, main
from app.errors import EmptySubtitles, NoSubtitles, VideoError
from app.learning_text import (
    compact_from_cues,
    compact_from_timed_text,
    fmt_ts,
    parse_ts,
    relevant_excerpt,
    sample_evenly,
    split_chunks,
)
from app.subtitles import Cue
from app.transcriptions import Transcription


def _parse_sse(body: str) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    for block in body.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln and not ln.startswith(":")]
        if not lines:
            continue
        ev = "message"
        data_lines: list[str] = []
        for ln in lines:
            if ln.startswith("event:"):
                ev = ln.split(":", 1)[1].strip()
            elif ln.startswith("data:"):
                data_lines.append(ln.split(":", 1)[1].lstrip(" "))
        if data_lines:
            raw = "\n".join(data_lines)
            events.append((ev, json.loads(raw)))
    return events


class FakeCompletions:
    def __init__(self, stream_reply: list[str] | None = None, sync_reply: str = "分段提炼结果 [01:20]"):
        self.calls: list[dict] = []
        self.stream_reply = stream_reply or ["## 一句话核心主旨\n", "核心内容 [00:10]"]
        self.sync_reply = sync_reply

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            def gen():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])
                for part in self.stream_reply:
                    yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=part))])
            return gen()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.sync_reply))]
        )


def _fake_openai(stream_reply: list[str] | None = None, sync_reply: str = "分段提炼结果 [01:20]"):
    comp = FakeCompletions(stream_reply=stream_reply, sync_reply=sync_reply)
    client_obj = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return client_obj, comp


def test_parse_and_fmt_ts():
    assert parse_ts("02:15") == 135
    assert parse_ts("[1:02:15]") == 3735
    assert parse_ts("00:00:09,500") == 9
    assert parse_ts("12:60") is None
    assert parse_ts("bad") is None
    assert fmt_ts(135) == "02:15"
    assert fmt_ts(3735) == "1:02:15"


def test_compact_from_cues_and_timed_text_preserves_words():
    cues = [
        Cue("00:00:01,000", "00:00:03,000", "大家好"),
        Cue("00:00:05,000", "00:00:08,000", "今天讲解神经网络"),
        Cue("00:00:25,000", "00:00:28,000", "进入第二部分反向传播"),
    ]
    compact = compact_from_cues(cues, window=20)
    lines = compact.splitlines()
    assert len(lines) == 2
    assert lines[0] == "[00:01] 大家好 今天讲解神经网络"
    assert lines[1] == "[00:25] 进入第二部分反向传播"

    from_fe = compact_from_timed_text("[00:00:01] 第一句\n[00:00:04] 第二句\n[00:00:30] 第三句", window=20)
    assert from_fe == "[00:01] 第一句 第二句\n[00:30] 第三句"
    assert compact_from_timed_text("无时间戳纯文本第一行\n第二行") == "无时间戳纯文本第一行\n第二行"


def test_split_chunks_sample_and_relevant_excerpt():
    long_text = "\n".join(f"[{fmt_ts(i * 10)}] 第{i}段测试内容，包含特定主题词{('Transformer注意力机制' if i == 25 else '普通铺垫')}" for i in range(60))
    chunks = split_chunks(long_text, size=400)
    assert all(len(c) <= 400 for c in chunks)
    assert "\n".join(chunks) == long_text

    sampled, was_sampled = sample_evenly(long_text, budget=500, windows=5)
    assert was_sampled and len(sampled) <= 500
    assert "[00:00]" in sampled

    excerpt = relevant_excerpt(long_text, "请解释 Transformer注意力机制 的细节", budget=500, block_chars=120)
    assert len(excerpt) <= 500
    assert "Transformer注意力机制" in excerpt
    assert "[00:00]" in excerpt  # opening context preserved


def test_ai_learning_modes_thinking_param_and_map_reduce(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AI_LEARNING_MODEL", "deepseek-flash")
    monkeypatch.setenv("AI_LEARNING_THINKING", "disabled")
    monkeypatch.setattr(ai_learning, "MAX_DIRECT_CHARS", 70)
    monkeypatch.setattr(ai_learning, "CHUNK_CHARS", 50)

    fake_client, comp = _fake_openai(stream_reply=["## 课程核心目标\n", "掌握核心方法 [00:20]"], sync_reply="- [00:10] 阶段要点")
    monkeypatch.setattr(ai_learning, "_client", lambda: fake_client)

    # Long input (> 120 chars) triggers Map-Reduce: 2 sync segment calls + 1 streaming reduce call
    long_transcript = "\n".join([
        "[00:00] 第一章讲解线性代数矩阵乘法与特征值分解的基础几何意义与工程背景",
        "[05:00] 第二章深入讲解梯度下降优化器与自适应学习率调度的收敛性证明过程",
        "[10:00] 第三章结合实际代码案例演示如何排查训练过程中的梯度消失与爆炸问题",
    ])
    statuses: list[str] = []
    out = "".join(ai_learning.summarize_stream("深度学习公开课", long_transcript, mode="study", on_status=statuses.append))
    assert "课程核心目标" in out
    assert any("分段提炼中" in s for s in statuses)
    assert any("汇总全片" in s for s in statuses)
    assert len(comp.calls) >= 3
    for call in comp.calls:
        assert call["model"] == "deepseek-flash"
        assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "课后自测问答" in comp.calls[-1]["messages"][0]["content"]


def test_learn_api_summary_reuses_loaded_transcript_without_subtitle_fetch(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    ai_learning_api._peer_hits.clear()

    def forbidden_sub(*_a, **_kw):
        raise AssertionError("Should not download subtitles when transcript is provided")

    monkeypatch.setattr(ai_learning_api, "read_subtitles", forbidden_sub)
    fake_client, comp = _fake_openai(stream_reply=["## 一句话核心主旨\n", "无需重下字幕 [00:05]"])
    monkeypatch.setattr(ai_learning, "_client", lambda: fake_client)

    resp = client.post(
        "/api/learn/summary",
        json={
            "url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "mode": "general",
            "title": "测试课程",
            "transcript": "[00:00:05] 这里是前端已经提取好的字幕文本",
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = _parse_sse(resp.text)
    names = [e[0] for e in events]
    assert "meta" in names and "delta" in names and "done" in names
    meta = next(d for e, d in events if e == "meta")
    assert meta["source"] == "loaded_transcript"
    assert comp.calls[0]["messages"][1]["content"].count("[00:05]") == 1


def test_learn_api_no_subtitles_emits_need_asr_and_zero_asr_calls(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(asr, "enabled", lambda: True)
    ai_learning_api._peer_hits.clear()

    asr_called = 0

    def forbid_asr(*_a, **_kw):
        nonlocal asr_called
        asr_called += 1
        raise AssertionError("Paid ASR must NEVER be triggered implicitly")

    monkeypatch.setattr(asr, "get_provider", forbid_asr)
    monkeypatch.setattr(
        ai_learning_api,
        "read_subtitles",
        lambda *_a, **_kw: (_ for _ in ()).throw(NoSubtitles("本项目暂未提取到该抖音作品的字幕，可使用音频转文字")),
    )

    resp = client.post("/api/learn/summary", json={"url": "https://v.douyin.com/abc123/"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    need = next((d for e, d in events if e == "need_asr"), None)
    assert need is not None
    assert need["asr_enabled"] is True
    assert "音频转文字" in need["message"]
    assert asr_called == 0

    # Mindmap endpoint returns 409 NEED_ASR when neither summary nor subtitles exist
    mm = client.post("/api/learn/mindmap", json={"url": "https://v.douyin.com/abc123/"})
    assert mm.status_code == 409
    assert mm.json()["code"] == "NEED_ASR"
    assert asr_called == 0


def test_learn_api_session_isolation_for_owned_transcriptions(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    ai_learning_api._peer_hits.clear()
    fake_client, _ = _fake_openai(stream_reply=["会话复用成功 [00:08]"])
    monkeypatch.setattr(ai_learning, "_client", lambda: fake_client)
    monkeypatch.setattr(
        ai_learning_api,
        "read_subtitles",
        lambda *_a, **_kw: (_ for _ in ()).throw(EmptySubtitles("空字幕")),
    )

    # Establish Session A and register a completed ASR job owned by Session A
    r_sess = client.get("/api/transcription-session")
    assert r_sess.status_code == 200
    from app import transcription_auth
    from starlette.requests import Request as StarletteRequest

    cookie_val = client.cookies.get(transcription_auth.COOKIE)
    scope = {"type": "http", "headers": [(b"cookie", f"{transcription_auth.COOKIE}={cookie_val}".encode())]}
    owner_a = transcription_auth.owner(StarletteRequest(scope))

    url = "https://v.douyin.com/owned1/"
    job = Transcription(
        id="ownedjob001",
        owner=owner_a,
        key="k1",
        url=url,
        lang=None,
        allow_asr=True,
        status="done",
        stage="done",
        title="抖音口播干货",
        result={"text": "转写内容", "timed_text": "[00:00:08] 语音识别出来的干货内容", "source": "asr", "cues": 1, "srt": ""},
    )
    with main.transcription_manager.lock:
        main.transcription_manager.jobs[job.id] = job

    try:
        # Session A automatically reuses its own ASR result by URL without re-running ASR
        ok_resp = client.post("/api/learn/summary", json={"url": url})
        ok_events = _parse_sse(ok_resp.text)
        assert any(e == "meta" and d["source"] == "asr" for e, d in ok_events)
        assert any(e == "delta" and "会话复用成功" in d for e, d in ok_events)

        # Session B (fresh client without Session A's cookie) CANNOT read job.id="ownedjob001"
        attacker = TestClient(main.app)
        attacker.get("/api/transcription-session")
        steal = attacker.post("/api/learn/summary", json={"url": url, "transcription_id": "ownedjob001"})
        steal_events = _parse_sse(steal.text)
        assert not any(e == "delta" for e, _ in steal_events)
        assert any(e == "error" for e, _ in steal_events)
    finally:
        with main.transcription_manager.lock:
            main.transcription_manager.jobs.pop(job.id, None)


def test_learn_mindmap_and_chat_and_rate_limit(client: TestClient, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "k")
    ai_learning_api._peer_hits.clear()

    fake_client, comp = _fake_openai(
        stream_reply=["根据视频 [01:30]，核心原因是注意力权重退化。"],
        sync_reply="```markdown\n# Transformer 架构精讲\n## 核心机制 [01:30]\n- 自注意力计算 [02:00]\n```",
    )
    monkeypatch.setattr(ai_learning, "_client", lambda: fake_client)

    mm = client.post(
        "/api/learn/mindmap",
        json={"url": "https://b23.tv/x", "title": "Transformer", "summary": "## 总结\n自注意力 [01:30]"},
    )
    assert mm.status_code == 200
    md = mm.json()["markdown"]
    assert md.startswith("# Transformer 架构精讲")
    assert "```" not in md

    chat = client.post(
        "/api/learn/chat",
        json={
            "url": "https://b23.tv/x",
            "title": "Transformer",
            "transcript": "[00:01:30] 核心原因是注意力权重退化",
            "messages": [{"role": "user", "content": "为什么会退化？"}],
        },
    )
    assert chat.status_code == 200
    chat_events = _parse_sse(chat.text)
    assert any(e == "delta" and "[01:30]" in d for e, d in chat_events)
    assert any(e == "done" for e, _ in chat_events)
    assert len(comp.calls) == 2

    # Rate limit check
    monkeypatch.setenv("AI_LEARNING_RATE_LIMIT", "2")
    assert client.post("/api/learn/mindmap", json={"title": "T", "summary": "S"}).status_code == 429

    # AI disabled check
    ai_learning_api._peer_hits.clear()
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", None)
    assert client.post("/api/learn/summary", json={"url": "https://b23.tv/x"}).status_code == 503
    assert client.post("/api/learn/mindmap", json={"url": "https://b23.tv/x"}).status_code == 503
    assert client.post("/api/learn/chat", json={"url": "https://b23.tv/x", "messages": [{"role": "user", "content": "hi"}]}).status_code == 503
