"""Ghi/đọc file phụ đề SRT và WebVTT."""

from __future__ import annotations

import re

from .models import Cue


def _ts(seconds: float, sep: str) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


TOP_TAG = "{\\an8}"  # tag ASS trong SRT: đặt phụ đề giữa-trên (IINA, VLC, mpv, Plex... đều hiểu)


def to_srt(cues: list[Cue], position: str = "bottom") -> str:
    tag = TOP_TAG if position == "top" else ""
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{tag}{c.text}\n")
    return "\n".join(blocks)


def to_vtt(cues: list[Cue], position: str = "bottom") -> str:
    setting = " line:0" if position == "top" else ""
    blocks = ["WEBVTT\n"]
    for c in cues:
        blocks.append(f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}{setting}\n{c.text}\n")
    return "\n".join(blocks)


def write_subs(cues: list[Cue], path: str, position: str = "bottom") -> None:
    if path.lower().endswith(".vtt"):
        text = to_vtt(cues, position)
    else:
        text = to_srt(cues, position)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def srt_position(text: str) -> str:
    """Đoán vị trí của file SRT có sẵn (để bản dịch giữ nguyên vị trí)."""
    n_top = text.count(TOP_TAG)
    n = max(1, len(_TS_RE.findall(text)))
    return "top" if n_top >= n / 2 else "bottom"


_TS_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})"
)


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            m = _TS_RE.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                body = [re.sub(r"\{\\[^}]*\}", "", ln) for ln in lines[i + 1 :]]
                cues.append(Cue(start, end, [ln for ln in body if ln.strip()]))
                break
    return cues
