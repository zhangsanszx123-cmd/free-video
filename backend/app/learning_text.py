"""Pure text utilities for compacting timestamped transcripts and retrieving context."""
import re

from .subtitles import Cue

TS_LINE_RE = re.compile(r"^\s*\[(\d{1,2}:\d{2}(?::\d{2})?(?:[,.]\d{1,3})?)\]\s*(.*)$")
WORD_RE = re.compile(r"[a-zA-Z0-9]{2,}")
CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def parse_ts(label: str) -> int | None:
    """Parse 'MM:SS', 'HH:MM:SS', or 'HH:MM:SS,mmm' into non-negative seconds."""
    if not label or not isinstance(label, str):
        return None
    head = label.strip().strip("[]").split(",")[0].split(".")[0]
    parts = head.split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if len(nums) == 2:
        minutes, seconds = nums
        if seconds >= 60:
            return None
        return minutes * 60 + seconds
    hours, minutes, seconds = nums
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def fmt_ts(seconds: int) -> str:
    """Format seconds as compact 'MM:SS' (<1h) or 'H:MM:SS' (>=1h)."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


def _merge_timed_pairs(pairs: list[tuple[int, str]], window: int = 20, max_chars: int = 220) -> str:
    groups: list[tuple[int, list[str], int]] = []
    for sec, raw in pairs:
        txt = raw.strip()
        if not txt:
            continue
        if not groups:
            groups.append((sec, [txt], len(txt)))
            continue
        start_sec, items, char_len = groups[-1]
        if (sec - start_sec) >= window or (char_len + 1 + len(txt)) > max_chars:
            groups.append((sec, [txt], len(txt)))
        else:
            items.append(txt)
            groups[-1] = (start_sec, items, char_len + 1 + len(txt))
    return "\n".join(f"[{fmt_ts(start)}] {' '.join(items)}" for start, items, _ in groups)


def compact_from_cues(cues: list[Cue], window: int = 20, max_chars: int = 220) -> str:
    """Merge fine-grained SRT cues into compact '[MM:SS] paragraph' lines without dropping words."""
    pairs: list[tuple[int, str]] = []
    for cue in cues:
        sec = parse_ts(cue.start)
        pairs.append((0 if sec is None else sec, cue.text))
    return _merge_timed_pairs(pairs, window=window, max_chars=max_chars)


def compact_from_timed_text(text: str, window: int = 20, max_chars: int = 220) -> str:
    """Compact '[HH:MM:SS] line' text from frontend, or preserve plain text lines verbatim."""
    if not text:
        return ""
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        return ""
    parsed: list[tuple[int, str]] = []
    timed_count = 0
    for ln in raw_lines:
        m = TS_LINE_RE.match(ln)
        if m and (sec := parse_ts(m.group(1))) is not None:
            timed_count += 1
            parsed.append((sec, m.group(2)))
        else:
            parsed.append((-1, ln))
    if timed_count == 0:
        return "\n".join(raw_lines)
    # Flush untimed lines in place while grouping consecutive timed lines.
    out: list[str] = []
    buf: list[tuple[int, str]] = []
    for sec, content in parsed:
        if sec < 0:
            if buf:
                out.append(_merge_timed_pairs(buf, window=window, max_chars=max_chars))
                buf = []
            out.append(content)
        else:
            buf.append((sec, content))
    if buf:
        out.append(_merge_timed_pairs(buf, window=window, max_chars=max_chars))
    return "\n".join(s for s in out if s)


def split_chunks(text: str, size: int = 45000) -> list[str]:
    """Split text on line boundaries into chronological chunks each <= size chars."""
    if size <= 0:
        raise ValueError("size must be positive")
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in text.splitlines():
        while len(line) > size:
            if cur:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            chunks.append(line[:size])
            line = line[size:]
        added = len(line) + (1 if cur else 0)
        if cur and cur_len + added > size:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += added
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def sample_evenly(text: str, budget: int = 180000, windows: int = 24) -> tuple[str, bool]:
    """Uniformly sample across the entire timeline when ultra-long text exceeds budget."""
    if len(text) <= budget:
        return text, False
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text[:budget], True
    slots = max(2, min(windows, len(lines)))
    per_slot = max(40, budget // slots)
    step = len(lines) / slots
    picked: list[str] = []
    used_idx: set[int] = set()
    for s in range(slots):
        idx = min(int(s * step), len(lines) - 1)
        acc = 0
        while idx < len(lines) and acc < per_slot:
            if idx not in used_idx:
                used_idx.add(idx)
                picked.append(lines[idx])
                acc += len(lines[idx]) + 1
            idx += 1
    joined = "\n".join(picked)
    return (joined[:budget] if len(joined) > budget else joined), True


def _query_terms(question: str) -> set[str]:
    terms = {w.lower() for w in WORD_RE.findall(question or "")}
    for run in CJK_RUN_RE.findall(question or ""):
        if len(run) == 1:
            terms.add(run)
        else:
            for i in range(len(run) - 1):
                terms.add(run[i:i + 2])
    return terms


def relevant_excerpt(text: str, question: str, budget: int = 60000, block_chars: int = 1600) -> str:
    """Select chronological blocks relevant to question (plus opening & closing context) within budget."""
    if len(text) <= budget:
        return text
    blocks = split_chunks(text, max(200, min(block_chars, budget // 3 or 200)))
    if len(blocks) <= 2:
        return text[:budget]
    terms = _query_terms(question)
    scored: list[tuple[int, int]] = []
    for idx in range(1, len(blocks) - 1):
        low = blocks[idx].lower()
        score = sum(low.count(t) for t in terms) if terms else 0
        scored.append((score, idx))
    # Sort by highest keyword overlap; break ties by even timeline coverage.
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = {0, len(blocks) - 1}
    total = len(blocks[0]) + len(blocks[-1]) + 2
    for _, idx in scored:
        need = len(blocks[idx]) + 1
        if total + need <= budget:
            chosen.add(idx)
            total += need
    ordered = [blocks[i] for i in sorted(chosen)]
    return "\n".join(ordered)[:budget]
