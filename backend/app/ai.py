import re
from typing import Callable, Iterator

from openai import OpenAI

from . import config
from .subtitles import Cue

MAX_SUMMARY_CHARS = 15000
TRANSLATE_CHUNK = 40
LINE_RE = re.compile(r"^\s*(\d+)\s*[|｜]\s*(.*)$")

SUMMARY_PROMPT = """你是专业的视频内容分析师。根据用户提供的视频字幕（带时间戳），用简体中文输出 Markdown：
## 一句话总结
## 核心要点（3-7 条，每条带对应时间戳）
## 详细大纲（按时间顺序分段）
## 金句摘录（如有）
要求：忠于原文，不编造字幕中没有的信息。"""

TRANSLATE_PROMPT = """你是专业字幕翻译。把每行 `序号|原文` 翻译成{lang}，严格按 `序号|译文` 逐行输出，
行数与序号必须与输入一一对应，不要合并或省略，不要输出任何额外说明。"""


class AIDisabled(Exception):
    pass


def enabled() -> bool:
    return bool(config.DEEPSEEK_API_KEY)


def _client() -> OpenAI:
    if not enabled():
        raise AIDisabled("AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")
    return OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL, timeout=120)


def _extra_kwargs(model: str) -> dict:
    base = (config.DEEPSEEK_BASE_URL or "").lower()
    if "deepseek" in base or "deepseek" in (model or "").lower():
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def summarize_stream(title: str, transcript: str) -> Iterator[str]:
    if len(transcript) > MAX_SUMMARY_CHARS:
        transcript = transcript[:MAX_SUMMARY_CHARS] + "\n…（字幕过长，已截断）"
    stream = _client().chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        stream=True,
        temperature=0.3,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": f"视频标题：{title}\n\n字幕：\n{transcript}"},
        ],
        **_extra_kwargs(config.DEEPSEEK_MODEL),
    )
    for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta


def _translate_chunk(client: OpenAI, texts: list[str], lang: str) -> list[str]:
    content = "\n".join(f"{i}|{t}" for i, t in enumerate(texts))
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": TRANSLATE_PROMPT.format(lang=lang)},
            {"role": "user", "content": content},
        ],
        **_extra_kwargs(config.DEEPSEEK_MODEL),
    )
    result = [""] * len(texts)
    for line in (resp.choices[0].message.content or "").splitlines():
        if (m := LINE_RE.match(line)) and int(m.group(1)) < len(texts):
            result[int(m.group(1))] = m.group(2).strip()
    return result


def translate_cues(cues: list[Cue], lang: str, on_progress: Callable[[float], None] = lambda _: None) -> list[str]:
    client = _client()
    out: list[str] = []
    for i in range(0, len(cues), TRANSLATE_CHUNK):
        out += _translate_chunk(client, [c.text for c in cues[i:i + TRANSLATE_CHUNK]], lang)
        on_progress(min(len(out) / len(cues) * 100, 99))
    return out
