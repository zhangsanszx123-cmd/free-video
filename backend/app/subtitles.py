import re
from dataclasses import dataclass

TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


@dataclass
class Cue:
    start: str
    end: str
    text: str


def parse_srt(content: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", content.strip().lstrip("\ufeff")):
        lines = [l.strip() for l in block.strip().splitlines()]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        start, end = [t.strip().split(" ")[0] for t in lines[idx].split("-->")]
        text = TAG_RE.sub("", " ".join(l for l in lines[idx + 1:] if l)).strip()
        if text:
            cues.append(Cue(start, end, text))
    return _dedupe(cues)


def _dedupe(cues: list[Cue]) -> list[Cue]:
    """Merge consecutive identical lines (common in auto captions)."""
    out: list[Cue] = []
    for c in cues:
        if out and out[-1].text == c.text:
            out[-1].end = c.end
        else:
            out.append(c)
    return out


def to_plain_text(cues: list[Cue], with_time: bool = True) -> str:
    return "\n".join(f"[{c.start.split(',')[0]}] {c.text}" if with_time else c.text for c in cues)


def to_srt(cues: list[Cue], translations: list[str] | None = None) -> str:
    blocks = []
    for i, c in enumerate(cues):
        text = c.text
        if translations and i < len(translations) and translations[i]:
            text = f"{c.text}\n{translations[i]}"
        blocks.append(f"{i + 1}\n{c.start} --> {c.end}\n{text}\n")
    return "\n".join(blocks)
