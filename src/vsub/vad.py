"""Tìm các đoạn có giọng nói (VAD) rồi gom thành chunk để đưa vào Whisper.

Lý do: phim có nhiều đoạn nhạc/im lặng dài. Nếu đưa nguyên cả phim vào Whisper,
model hay "bịa" chữ ở những đoạn đó ("Hãy subscribe kênh...", lặp một câu mãi)
và timestamp bị trôi. Cắt theo VAD giúp mỗi chunk ngắn và có thoại thật.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio import SAMPLE_RATE


@dataclass
class Chunk:
    start: float  # giây, tính trên toàn bộ video
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def speech_regions(
    audio: np.ndarray,
    threshold: float = 0.4,
    min_silence_ms: int = 400,
    speech_pad_ms: int = 200,
) -> list[tuple[float, float]]:
    """Trả về danh sách (start, end) tính bằng giây của các đoạn có thoại."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(
        threshold=threshold,
        min_speech_duration_ms=150,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
        max_speech_duration_s=25,
    )
    stamps = get_speech_timestamps(audio, vad_options=opts, sampling_rate=SAMPLE_RATE)
    return [(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in stamps]


def group_regions(
    regions: list[tuple[float, float]],
    max_chunk_s: float = 28.0,
    max_gap_s: float = 1.5,
    pad_s: float = 0.15,
    total_s: float | None = None,
) -> list[Chunk]:
    """Gom các đoạn thoại gần nhau thành chunk ≤ max_chunk_s (vừa cửa sổ 30s của Whisper)."""
    chunks: list[Chunk] = []
    cur: Chunk | None = None
    for start, end in regions:
        if cur is not None and (
            start - cur.end <= max_gap_s and end - cur.start <= max_chunk_s
        ):
            cur.end = end
            continue
        if cur is not None:
            chunks.append(cur)
        cur = Chunk(start, end)
    if cur is not None:
        chunks.append(cur)

    limit = total_s if total_s is not None else float("inf")
    for i, c in enumerate(chunks):
        lo = chunks[i - 1].end if i > 0 else 0.0
        hi = chunks[i + 1].start if i + 1 < len(chunks) else limit
        c.start = max(lo, c.start - pad_s, 0.0)
        c.end = min(hi, c.end + pad_s, limit)
    return chunks


def slice_audio(audio: np.ndarray, chunk: Chunk) -> np.ndarray:
    a = int(chunk.start * SAMPLE_RATE)
    b = int(chunk.end * SAMPLE_RATE)
    return audio[a:b]


def loudness_db(audio: np.ndarray, start: float, end: float, win: float = 0.25) -> float:
    """Độ to (dB) mức phân vị 90 của các khung `win` giây trong [start, end]."""
    a = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
    n = int(win * SAMPLE_RATE)
    if len(a) < n:
        return -120.0
    frames = a[: len(a) // n * n].reshape(-1, n)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9
    return float(20 * np.log10(np.percentile(rms, 90)))


def fill_loud_gaps(
    regions: list[tuple[float, float]],
    audio: np.ndarray,
    total_s: float,
    min_gap_s: float = 0.8,
    loud_db: float = -38.0,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Silero VAD hay bỏ sót lời nói lẫn nhạc nền / giọng qua điện thoại, TV.
    Khoảng trống nào giữa các đoạn thoại mà audio vẫn to thì cũng đưa vào Whisper.

    Trả về (regions_đã_bù, các_khoảng_bù) — khoảng bù là vùng "VAD không chắc"."""
    out, added = [], []
    prev_end = 0.0
    for s, e in list(regions) + [(total_s, total_s)]:
        if s - prev_end >= min_gap_s and loudness_db(audio, prev_end, s) > loud_db:
            out.append((prev_end, s))
            added.append((prev_end, s))
        if e > s:
            out.append((s, e))
        prev_end = max(prev_end, e)
    return out, added


def find_holes(
    audio: np.ndarray,
    words: list[tuple[float, float]],
    speech: list[tuple[float, float]],
    total_s: float,
    loud_db: float = -40.0,
    min_hole_s: float = 1.2,
    max_hole_s: float = 12.0,
    word_pad_s: float = 0.3,
) -> list[tuple[float, float]]:
    """Tìm những khoảng có tiếng (VAD hoặc audio to) mà bản nhận dạng chưa có chữ nào.

    Dùng cho lượt nghe lại: Whisper hay bỏ cả một cửa sổ khi đầu cửa sổ là nhạc/ồn."""
    R = 20  # ô 50 ms
    n = int(total_s * R) + 1
    cand = np.zeros(n, bool)
    for s, e in speech:
        cand[int(s * R):int(e * R)] = True
    win = SAMPLE_RATE // R
    m = len(audio) // win
    if m:
        rms = np.sqrt(np.mean(audio[: m * win].reshape(m, win) ** 2, axis=1)) + 1e-9
        loud = 20 * np.log10(rms) > loud_db
        # làm mượt 0.5s để không vụn
        k = np.ones(10) / 10
        loud = np.convolve(loud.astype(float), k, mode="same") > 0.5
        cand[: len(loud)] |= loud[: n]
    covered = np.zeros(n, bool)
    for s, e in words:
        covered[max(0, int((s - word_pad_s) * R)):int((e + word_pad_s) * R)] = True
    hole = cand & ~covered
    out, i = [], 0
    while i < n:
        if hole[i]:
            j = i
            while j < n and (hole[j] or (j + 10 < n and hole[j:j + 10].any())):  # nối khe < 0.5s
                j += 1
            s, e = i / R, min(j / R, total_s)
            while e - s >= min_hole_s:
                out.append((s, min(e, s + max_hole_s)))
                s += max_hole_s
            i = j
        else:
            i += 1
    return out
