"""Kiểm tra video có phụ đề in sẵn (hardsub) không, để đặt phụ đề mới tránh đè lên.

Cách làm: lấy ~24 khung hình ở các đoạn có thoại, chạy bộ dò chữ (RapidOCR / PP-OCR det,
model ONNX có sẵn trong gói), rồi tìm hộp chữ:
- nằm giữa theo chiều ngang (phụ đề luôn căn giữa, chữ trong cảnh thì không),
- thấp (1-2 dòng), ở dải dưới (hoặc trên) khung hình,
- lặp lại ở cùng một dải trong nhiều khung hình.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

WIDTH = 960


@dataclass
class HardsubInfo:
    frames: int = 0
    bottom_ratio: float = 0.0
    top_ratio: float = 0.0
    bottom_band: tuple[float, float] | None = None  # (y0, y1) theo tỉ lệ chiều cao
    top_band: tuple[float, float] | None = None
    error: str | None = None
    samples: list = field(default_factory=list, repr=False)

    @property
    def bottom(self) -> bool:
        return self.bottom_ratio >= 0.35

    @property
    def top(self) -> bool:
        return self.top_ratio >= 0.35

    def suggest_position(self) -> str:
        if self.bottom and not self.top:
            return "top"
        if self.top and self.bottom:
            return "top" if self.top_ratio < self.bottom_ratio else "bottom"
        return "bottom"

    def describe(self) -> str:
        if self.error:
            return f"Không kiểm tra được phụ đề có sẵn ({self.error})"
        parts = []
        if self.bottom:
            parts.append(f"phía dưới ({self.bottom_ratio:.0%} khung hình)")
        if self.top:
            parts.append(f"phía trên ({self.top_ratio:.0%} khung hình)")
        if not parts:
            return f"Không thấy phụ đề in sẵn ({self.frames} khung hình)"
        return "Video có phụ đề in sẵn " + ", ".join(parts)


def _grab(video: str, t: float) -> np.ndarray | None:
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
         "-vf", f"scale={WIDTH}:-2", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True,
    ).stdout
    if not raw or len(raw) % (WIDTH * 3):
        return None
    return np.frombuffer(raw, np.uint8).reshape(-1, WIDTH, 3)


def caption_boxes(boxes, h: int, w: int = WIDTH) -> list[tuple[float, float]]:
    """Lọc các hộp chữ trông giống phụ đề; trả (y0, y1) theo tỉ lệ."""
    out = []
    for b in boxes or []:
        b = np.asarray(b, dtype=float)
        x0, y0 = b.min(0)
        x1, y1 = b.max(0)
        cx, bw, bh = (x0 + x1) / 2 / w, (x1 - x0) / w, (y1 - y0) / h
        if abs(cx - 0.5) <= 0.06 and bw >= 0.04 and bh <= 0.12:
            out.append((y0 / h, y1 / h))
    return out


def _band(hits: list[list[tuple[float, float]]], lo: float, hi: float):
    """Tỉ lệ khung hình có phụ đề trong vùng [lo, hi], gom theo dải 3% để loại chữ ngẫu nhiên."""
    q = 0.03
    per_frame = []
    for boxes in hits:
        ys = [(y0, y1) for y0, y1 in boxes if lo <= (y0 + y1) / 2 <= hi]
        per_frame.append(ys)
    keys = Counter()
    for ys in per_frame:
        for k in {round((y0 + y1) / 2 / q) for y0, y1 in ys}:
            keys[k] += 1
    if not keys:
        return 0.0, None
    best, _ = keys.most_common(1)[0]
    near = lambda y0, y1: abs(round((y0 + y1) / 2 / q) - best) <= 1
    frames = [ys for ys in per_frame if any(near(*y) for y in ys)]
    sel = [y for ys in frames for y in ys if near(*y)]
    band = (min(y0 for y0, _ in sel), max(y1 for _, y1 in sel))
    return len(frames) / max(len(hits), 1), band


def detect_hardsubs(video: str, times: list[float], max_frames: int = 24) -> HardsubInfo:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return HardsubInfo(error="chưa cài rapidocr_onnxruntime")
    if not times:
        return HardsubInfo(error="không có đoạn thoại")
    step = max(1, len(times) // max_frames)
    picks = times[::step][:max_frames]
    ocr = RapidOCR()
    hits = []
    for t in picks:
        img = _grab(video, t)
        if img is None:
            continue
        res, _ = ocr(img, use_det=True, use_cls=False, use_rec=False)
        hits.append(caption_boxes(res, img.shape[0]))
    if not hits:
        return HardsubInfo(error="không đọc được khung hình")
    br, bb = _band(hits, 0.62, 1.0)
    tr, tb = _band(hits, 0.0, 0.30)
    return HardsubInfo(len(hits), br, tr, bb, tb, samples=hits)
