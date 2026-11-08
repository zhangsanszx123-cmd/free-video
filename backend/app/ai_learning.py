"""AI video learning engine: multi-perspective summary, mind map, and grounded Q&A."""
import os
import re
from typing import Callable, Iterator, Literal

from openai import OpenAI

from . import ai, config
from .learning_text import relevant_excerpt, sample_evenly, split_chunks

SummaryMode = Literal["general", "study", "deep"]

MAX_DIRECT_CHARS = int(os.getenv("AI_LEARNING_DIRECT_CHARS", "60000"))
MAX_MAP_REDUCE_CHARS = int(os.getenv("AI_LEARNING_MAX_CHARS", "180000"))
CHUNK_CHARS = int(os.getenv("AI_LEARNING_CHUNK_CHARS", "45000"))

FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n|\n```\s*$", re.IGNORECASE)

COMMON_RULES = """通用要求：
1. 必须严格忠于提供的视频文稿，绝不编造文稿中未出现的信息、数据或结论。
2. 引用时间点时，统一使用方括号格式（如 [02:15] 或 [1:02:15]），且只能引用文稿里真实存在的时间戳；若文稿无时间戳则不编造时间戳。
3. 使用清晰、精炼的简体中文 Markdown 输出，不要使用代码块包裹整篇回答。"""

SUMMARY_PROMPTS: dict[str, str] = {
    "general": f"""你是专业的长视频精读与知识提炼专家。请根据视频标题和带时间戳的文稿，按以下结构输出深度总结：
## 一句话核心主旨
用 60~120 字直击整支视频的核心结论与价值。

## 核心知识要点
提炼 4~7 条最重要的核心观点或干货结论，每条附带对应时间戳（如 [02:15]）并做简明展开。

## 章节时间轴大纲
按视频内容的真实推进逻辑划分为若干章节，格式示例：
### [00:00] 章节标题
- [00:45] 关键内容拆解

## 关键术语与概念解析
提取视频中出现的专有名词、核心方法论或高光金句并给出通俗解释（若为日常口播则提炼核心金句）。

## 追问建议
基于本视频内容，列出 3 个值得学习者进一步深挖的具体问题（严格每行一条 `- 问题内容？`，不要附答案）。

{COMMON_RULES}""",

    "study": f"""你是专业的课程助教与学习笔记整理专家。请将视频整理为便于复习背诵的结构化课堂笔记：
## 课程核心目标
简明概括本节视频解决什么问题、学完能掌握什么能力。

## 章节知识精讲
按时间顺序拆解课程脉络，每个知识点标注对应时间戳（如 [03:20]），梳理逻辑推导过程。

## 核心概念与方法步骤
提炼视频中的关键定义、公式原理或可执行的实操步骤（带时间戳定位）。

## 易错点与关键细节
指出视频中强调的注意事项、常见误区或边界条件（仅限视频提及内容）。

## 课后自测问答
设计 3 组「问题 + 简要参考答案」，帮助学习者自我检验掌握程度。

## 追问建议
列出 3 个针对课程重点或难点的延伸提问（严格每行一条 `- 问题内容？`，不要附答案）。

{COMMON_RULES}""",

    "deep": f"""你是资深行业研究员与逻辑拆解分析师。请对视频进行深度结构化拆解：
## 核心论点（Thesis）
提炼作者的核心主张、立场与底层逻辑。

## 论证脉络与时间轴
按「问题引入 → 分论点推进 → 核心结论」梳理全片逻辑链条，关键节点标注时间戳（如 [05:10]）。

## 关键论据与案例支撑
提取视频中引用的具体案例、对比实验、技术细节或数据支撑（附时间戳）。

## 核心洞察与金句摘录
提炼最具启发性的洞察观点或原话精粹。

## 追问建议
列出 3 个有助于批判性思考或深入探究细节的问题（严格每行一条 `- 问题内容？`，不要附答案）。

{COMMON_RULES}""",
}

SEGMENT_SYSTEM_PROMPT = """你是长视频分段信息提炼助手。你将收到长视频其中一段带时间戳的文稿。
请忠实提炼该时间段内的：1）分段章节脉络与对应 [MM:SS] 时间戳；2）核心知识点、关键术语、案例与数据细节。
要求：保留准确的 [MM:SS] / [H:MM:SS] 时间锚点，不编造原文没有的内容，字数控制在 1200 字以内。"""

MINDMAP_SYSTEM_PROMPT = """你是知识结构化与思维导图专家。请将视频内容提炼为层次清晰、结构均衡的 Markdown 思维导图树。
严格遵守以下格式规范（只输出 Markdown 标题和无序列表，不要输出任何开场白、解释或代码块标记）：
# 视频核心主题（不超过 22 字）
## 一级分支一 [00:00]
- 核心要点 A [01:20]
  - 关键细节或结论（简短精炼，每条不超过 28 字）
- 核心要点 B [03:45]
## 一级分支二 [06:10]
- 核心要点 C [07:00]

要求：
1. 必须只有 1 个 `# ` 根节点；一级分支（`## `）控制在 3~6 个；每个分支下 2~5 个要点，最多到二级缩进子项。
2. 节点文字务必凝练易读；若输入包含真实时间戳，请在一级分支或核心要点末尾保留 `[MM:SS]`，无时间戳则不写。
3. 严禁编造输入中没有的知识。"""

CHAT_SYSTEM_PROMPT = """你是《万能视频下载器》的 AI 视频助学导师。用户正在学习一支视频并向你追问细节。
请遵守以下准则：
1. 优先且严格依据下方提供的【视频文稿片段】回答问题，并在引用视频内容处标注对应的时间戳（如 [04:30]），方便用户点击跳回视频核对。
2. 如果用户询问的内容在视频文稿中未提及，请先明确说明“视频中未直接提及这一点”，随后可简要补充通用背景知识并注明为拓展参考。
3. 回答条理清晰、重点突出，使用简体中文 Markdown 格式。"""


def model_name() -> str:
    return (os.getenv("AI_LEARNING_MODEL") or "deepseek-flash").strip()


def _extra_kwargs(model: str) -> dict:
    thinking = (os.getenv("AI_LEARNING_THINKING") or "disabled").strip().lower()
    base = (config.DEEPSEEK_BASE_URL or "").lower()
    if thinking == "disabled" and ("deepseek" in base or "deepseek" in model.lower()):
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def _client() -> OpenAI:
    if not ai.enabled():
        raise ai.AIDisabled("AI 功能未启用：请在 backend/.env 中配置 DEEPSEEK_API_KEY")
    return OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL, timeout=180)


def _stream_completion(client: OpenAI, messages: list[dict], temperature: float = 0.3) -> Iterator[str]:
    mdl = model_name()
    stream = client.chat.completions.create(
        model=mdl,
        messages=messages,
        temperature=temperature,
        stream=True,
        **_extra_kwargs(mdl),
    )
    for chunk in stream:
        if chunk.choices and (delta := chunk.choices[0].delta.content):
            yield delta


def _complete_once(client: OpenAI, messages: list[dict], temperature: float = 0.2) -> str:
    mdl = model_name()
    resp = client.chat.completions.create(
        model=mdl,
        messages=messages,
        temperature=temperature,
        stream=False,
        **_extra_kwargs(mdl),
    )
    return (resp.choices[0].message.content or "").strip() if resp.choices else ""


def _summarize_segment(client: OpenAI, title: str, chunk: str, idx: int, total: int) -> str:
    return _complete_once(
        client,
        [
            {"role": "system", "content": SEGMENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"视频标题：{title}\n当前为第 {idx}/{total} 段文稿：\n{chunk}"},
        ],
        temperature=0.2,
    )


def summarize_events(
    title: str,
    transcript: str,
    mode: str = "general",
) -> Iterator[tuple[str, str]]:
    """Yield ('status', msg) and ('delta', chunk) events in real time, including Map-Reduce stages."""
    client = _client()
    prompt = SUMMARY_PROMPTS.get(mode, SUMMARY_PROMPTS["general"])
    working, sampled = sample_evenly(transcript, budget=MAX_MAP_REDUCE_CHARS)

    if len(working) <= MAX_DIRECT_CHARS:
        yield ("status", "AI 正在精读并生成结构化总结…")
        source_body = f"视频标题：{title}\n\n视频文稿：\n{working}"
    else:
        chunks = split_chunks(working, size=CHUNK_CHARS)
        notes: list[str] = []
        for idx, ch in enumerate(chunks, start=1):
            yield ("status", f"长视频分段提炼中（第 {idx}/{len(chunks)} 段）…")
            notes.append(f"【第 {idx}/{len(chunks)} 段提炼笔记】\n{_summarize_segment(client, title, ch, idx, len(chunks))}")
        yield ("status", "正在汇总全片大纲与核心知识要点…")
        merged_notes = "\n\n".join(notes)
        source_body = f"视频标题：{title}\n\n以下是按时间顺序分段提炼的全片带时间戳笔记，请整合为完整总结：\n{merged_notes}"

    for delta in _stream_completion(
        client,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": source_body},
        ],
        temperature=0.3,
    ):
        yield ("delta", delta)
    if sampled:
        yield ("delta", "\n\n> 注：原视频文稿超长，已按全片时间轴均匀采样覆盖首尾各章节。")


def summarize_stream(
    title: str,
    transcript: str,
    mode: str = "general",
    on_status: Callable[[str], None] = lambda _: None,
) -> Iterator[str]:
    """Stream structured summary; automatically performs Map-Reduce on transcripts > MAX_DIRECT_CHARS."""
    for kind, value in summarize_events(title, transcript, mode=mode):
        if kind == "status":
            on_status(value)
        else:
            yield value


def _strip_fences(md: str) -> str:
    cleaned = FENCE_RE.sub("", (md or "").strip()).strip()
    return cleaned


def generate_mindmap(title: str, transcript: str = "", summary: str = "") -> str:
    """Generate a hierarchical Markdown tree suitable for interactive MindMap rendering."""
    client = _client()
    parts: list[str] = [f"视频标题：{title or '视频知识导图'}"]
    if summary and summary.strip():
        parts.append(f"已有结构化总结：\n{summary.strip()[:30000]}")
    if transcript and transcript.strip():
        budget = 24000 if (summary and summary.strip()) else MAX_DIRECT_CHARS
        excerpt, _ = sample_evenly(transcript.strip(), budget=budget)
        parts.append(f"视频文稿参考：\n{excerpt}")
    raw = _complete_once(
        client,
        [
            {"role": "system", "content": MINDMAP_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        temperature=0.2,
    )
    cleaned = _strip_fences(raw)
    if not cleaned.startswith("#"):
        cleaned = f"# {title or '视频核心知识'}\n" + cleaned
    return cleaned


def chat_stream(title: str, transcript: str, messages: list[dict]) -> Iterator[str]:
    """Stream grounded multi-turn Q&A answers citing [MM:SS] timestamps."""
    client = _client()
    last_q = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    context = relevant_excerpt(transcript, last_q, budget=MAX_DIRECT_CHARS)
    system_content = (
        f"{CHAT_SYSTEM_PROMPT}\n\n"
        f"【视频标题】{title or '未命名视频'}\n"
        f"【视频文稿片段】\n{context}"
    )
    chat_msgs = [{"role": "system", "content": system_content}]
    for m in messages[-20:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            chat_msgs.append({"role": role, "content": content})
    yield from _stream_completion(client, chat_msgs, temperature=0.3)
