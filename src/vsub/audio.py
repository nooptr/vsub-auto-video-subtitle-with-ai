"""Tách audio từ video bằng ffmpeg."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 16000


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError(
            "Không tìm thấy ffmpeg/ffprobe. Mở tab “Thư viện” trong app (hoặc chạy: vsub doctor --install ffmpeg)"
        )


def probe_duration(path: str) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path,
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def load_audio(path: str, audio_track: int = 0) -> np.ndarray:
    """Đọc audio của video thành mảng float32 mono 16 kHz (định dạng Whisper cần).

    Có lọc nhẹ highpass/lowpass để giảm tiếng ồn tần số thấp và cao, giúp
    Whisper nghe thoại rõ hơn khi phim có nhạc nền.

    `aresample=async=1:first_pts=0`: nhiều file bị mất vài gói audio (ví dụ hụt 8 giây giữa phim).
    Không có bộ lọc này ffmpeg nối liền phần còn lại, mọi câu phía sau bị sớm dần (có tập lệch 50 giây).
    Bộ lọc chèn khoảng lặng vào chỗ hụt, nên giây thứ N của mảng audio đúng là giây thứ N của video.
    """
    require_ffmpeg()
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", path,
        "-map", f"0:a:{audio_track}", "-vn",
        "-af", "aresample=async=1:first_pts=0,highpass=f=80,lowpass=f=8000",
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg không đọc được audio: {proc.stderr.decode(errors='replace')}"
        )
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()
