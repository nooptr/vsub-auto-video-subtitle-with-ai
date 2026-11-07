"""Lọc các câu Whisper hay "bịa" ra (hallucination)."""

from __future__ import annotations

import re
import unicodedata

from .models import Segment

# Cụm từ gần như chắc chắn là bịa (lấy từ dữ liệu YouTube Whisper đã học) — bỏ luôn.
ALWAYS_DROP = [
    "subscribe", "đăng ký kênh", "đăng kí kênh", "ghiền mì gõ", "amara.org",
    "subtitles by", "subtitle by", "sub by", "transcribed by", "vietsub",
    "字幕", "明镜", "點點", "点点", "請不吝", "请不吝", "ご視聴",
    "like và share", "nhấn chuông",
]

# Cụm từ có thể là thoại thật, chỉ bỏ khi model không chắc chắn.
DROP_IF_UNSURE = [
    "thanks for watching", "thank you for watching", "cảm ơn các bạn đã theo dõi",
    "cảm ơn các bạn đã xem", "hẹn gặp lại các bạn", "see you in the next video",
    "谢谢观看", "謝謝觀看",
]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def _strip_punct(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text, flags=re.UNICODE).strip()


def is_hallucination(seg: Segment) -> bool:
    t = _norm(seg.text)
    if not _strip_punct(t):
        return True
    if any(p in t for p in ALWAYS_DROP):
        return True
    unsure = seg.avg_logprob < -0.6 or seg.no_speech_prob > 0.4
    if unsure and any(p in t for p in DROP_IF_UNSURE):
        return True
    # Whisper tự đánh giá: chữ lặp nhiều (nén được nhiều) = lặp vòng
    if seg.compression_ratio > 2.4:
        return True
    # Model cho rằng không có tiếng nói và cũng không tự tin về chữ
    if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
        return True
    # Cả câu toàn từ xác suất rất thấp
    if seg.words and max(w.probability for w in seg.words) < 0.15:
        return True
    return False


_PREFIX = re.compile(r"^\s*字幕\s*[:：]\s*")
_CJK = "\u3040-\u30ff\u3400-\u9fff"
_ARTIFACTS = [
    (re.compile(rf"(?<=[{_CJK}])[1１](?=[{_CJK}]|$)"), "。"),   # "１" bắt chước từ "！" của câu mồi cũ
    (re.compile(rf"(?<=[{_CJK}])：(?=.)"), "、"),
    (re.compile(rf"(?<=[{_CJK}])：$"), "。"),
]


def repair(seg: Segment) -> Segment:
    """Sửa đoạn bị chép lại câu mồi kiểu cũ ("字幕：…", "：", "１") — giữ lời thoại thật."""
    from dataclasses import replace as _replace

    text, words = seg.text, list(seg.words)
    m = _PREFIX.match(text)
    if m:
        cut = len(m.group(0).strip())
        text = text[m.end():]
        acc = ""
        while words and len(acc.strip()) < cut:
            acc += words.pop(0).text
    def fix(s: str) -> str:
        for rx, rep in _ARTIFACTS:
            s = rx.sub(rep, s)
        return s
    if m or any(rx.search(text) for rx, _ in _ARTIFACTS) or any(
        rx.search(w.text) for w in words for rx, _ in _ARTIFACTS
    ):
        words = [_replace(w, text=fix(w.text)) for w in words]
        return _replace(seg, text=fix(text), words=words, start=words[0].start if words else seg.start)
    return seg


def _overlap_ratio(seg: Segment, zones: list[tuple[float, float]]) -> float:
    dur = max(seg.end - seg.start, 1e-6)
    return sum(max(0.0, min(seg.end, b) - max(seg.start, a)) for a, b in zones) / dur


def is_unsure_in_noise(seg: Segment) -> bool:
    """Câu nằm trong vùng VAD cho là không có tiếng nói (nhạc nền, tiếng ồn):
    chỉ giữ khi Whisper khá tự tin, để tránh chữ bịa ở đoạn chỉ có nhạc."""
    return seg.no_speech_prob > 0.5 or seg.avg_logprob < -0.8 or seg.compression_ratio > 2.0


def clean_segments(
    segments: list[Segment], max_repeat: int = 2, repeat_window_s: float = 4.0,
    uncertain: list[tuple[float, float]] | None = None,
) -> list[Segment]:
    """Bỏ câu bịa và bỏ một câu lặp lại sát nhau quá `max_repeat` lần.

    Chỉ tính là "lặp" khi các câu nối tiếp nhau trong vòng `repeat_window_s` giây
    (vòng lặp của Whisper); cùng một câu xuất hiện ở hai cảnh khác nhau vẫn giữ.
    """
    out: list[Segment] = []
    run_text, run_len, run_end = None, 0, -1e9
    for seg in segments:
        seg = repair(seg)
        if is_hallucination(seg):
            continue
        if uncertain and _overlap_ratio(seg, uncertain) > 0.6 and is_unsure_in_noise(seg):
            continue
        key = _strip_punct(_norm(seg.text))
        if key == run_text and seg.start - run_end <= repeat_window_s:
            run_len += 1
            run_end = seg.end
            if run_len > max_repeat:
                continue
        else:
            run_text, run_len, run_end = key, 1, seg.end
        out.append(seg)
    return out
