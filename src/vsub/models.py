"""Kiểu dữ liệu dùng chung trong pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Word:
    start: float
    end: float
    text: str  # giữ nguyên khoảng trắng đầu như Whisper trả về (" Hello")
    probability: float = 1.0


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Segment":
        words = [Word(**w) for w in d.get("words", [])]
        return Segment(
            start=d["start"],
            end=d["end"],
            text=d["text"],
            words=words,
            avg_logprob=d.get("avg_logprob", 0.0),
            no_speech_prob=d.get("no_speech_prob", 0.0),
            compression_ratio=d.get("compression_ratio", 1.0),
        )


@dataclass
class Cue:
    """Một dòng phụ đề hiển thị trên màn hình (1-2 dòng chữ)."""

    start: float
    end: float
    lines: list[str]
    words: list[Word] = field(default_factory=list, repr=False, compare=False)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)
