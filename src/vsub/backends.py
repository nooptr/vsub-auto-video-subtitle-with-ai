"""Backend nhận dạng giọng nói.

- MLXBackend: mlx-whisper, chạy trên GPU của Mac chip M (nhanh nhất trên M1 Max).
- FasterWhisperBackend: faster-whisper (CTranslate2), chạy CPU/CUDA — dùng khi
  không có MLX (Linux, Windows, Mac Intel).
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .models import Segment, Word

# Tên ngắn -> repo trên Hugging Face
MLX_MODELS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}


# Whisper viết tiếng Nhật/Trung thường thiếu dấu câu -> không biết chỗ hết câu.
# Đưa một câu mồi CÓ dấu câu làm initial_prompt khiến model chép lại có 。、？！.
# Không dùng nhãn kiểu "字幕：" hay dấu "！": model bắt chước thành "：", "１" chèn vào lời thoại.
PUNCT_PROMPTS = {
    "ja": "はい、そうです。それで、どうしますか？",
    "zh": "好的，我知道了。那你呢？",
    "yue": "好呀，我知道喇。咁你呢？",
}


# Các "alignment head" dùng để căn timestamp từng từ, chép từ openai-whisper (MIT,
# whisper/__init__.py, _ALIGNMENT_HEADS). mlx_whisper.load_model KHÔNG cài các head này mà dùng
# mặc định "mọi head ở nửa sau decoder" -> với large-v3-turbo (4 tầng) timestamp từng từ lệch nhiều
# giây: chữ đúng nhưng phụ đề hiện sai chỗ.
ALIGNMENT_HEADS = {
    "tiny": b"ABzY8bu8Lr0{>%RKn9Fp%m@SkK7Kt=7ytkO",
    "base": b"ABzY8KQ!870{>%RzyTQH3`Q^yNP!>##QT-<FaQ7m",
    "small": b"ABzY8DmU6=0{>%Rpa?J`kvJ6qF(V^F86#Xh7JUGMK}P<N0000",
    "medium": b"ABzY8B0Jh+0{>%R7}kK1fFL7w6%<-Pf*t^=N)Qr&0RR9",
    "large-v1": b"ABzY8r9j$a0{>%R7#4sLmoOs{s)o3~84-RPdcFk!JR<kSfC2yj",
    "large-v2": b"ABzY8zd+h!0{>%R7=D0pU<_bnWW*tkYAhobTNnu$jnkEkXqp)j;w1Tzk)UH3X%SZd&fFZ2fC2yj",
    "large-v3": b"ABzY8gWO1E0{>%R7(9S+Kn!D~%ngiGaR?*L!iJG9p-nab0JQ=-{D1-g00",
    "large-v3-turbo": b"ABzY8j^C+e0{>%RARaKHP%t(lGR*)0g!tONPyhe`",
}


def alignment_key(model: str) -> str | None:
    """'large-v3-turbo', 'turbo', 'mlx-community/whisper-large-v3-mlx'... -> khoá trong ALIGNMENT_HEADS."""
    import re

    name = model.lower().rsplit("/", 1)[-1]
    if name in ("turbo", "large-v3-turbo") or "turbo" in name:
        return "large-v3-turbo"
    m = re.search(r"(tiny|base|small|medium|large-v3|large-v2|large-v1)(?!\.en)", name)
    return m.group(1) if m else None


@dataclass
class TranscribeOptions:
    language: str | None = None  # None = tự nhận diện
    task: str = "transcribe"  # hoặc "translate" (chỉ dịch sang tiếng Anh)
    initial_prompt: str | None = None


@dataclass
class ChunkResult:
    language: str | None
    segments: list[Segment]


class Backend(Protocol):
    name: str
    model: str

    def transcribe(self, audio: np.ndarray, opts: TranscribeOptions) -> ChunkResult: ...


def _words_from(raw_words) -> list[Word]:
    out = []
    for w in raw_words or []:
        get = w.get if isinstance(w, dict) else lambda k, o=w: getattr(o, k)
        out.append(
            Word(
                start=float(get("start")),
                end=float(get("end")),
                text=str(get("word")),
                probability=float(get("probability")),
            )
        )
    return out


class MLXBackend:
    name = "mlx"

    def __init__(self, model: str):
        import mlx_whisper  # noqa: F401  (báo lỗi sớm nếu chưa cài)

        self.model = model
        self.repo = MLX_MODELS.get(model, model)
        self._aligned = False

    def _ensure_alignment_heads(self) -> None:
        """Nạp model trước (cùng kiểu dữ liệu mlx_whisper.transcribe dùng) rồi cài alignment heads."""
        if self._aligned:
            return
        self._aligned = True
        key = alignment_key(self.model) or alignment_key(self.repo)
        if not key:
            return
        try:
            import mlx.core as mx
            from mlx_whisper.transcribe import ModelHolder

            ModelHolder.get_model(self.repo, mx.float16).set_alignment_heads(ALIGNMENT_HEADS[key])
        except Exception as e:  # noqa: BLE001 — không cài được thì dùng mặc định
            print(f"! Không cài được alignment heads ({e})", file=sys.stderr)

    def transcribe(self, audio: np.ndarray, opts: TranscribeOptions) -> ChunkResult:
        import mlx_whisper

        self._ensure_alignment_heads()
        res = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.repo,
            language=opts.language,
            task=opts.task,
            initial_prompt=opts.initial_prompt,
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            verbose=None,
        )
        segs = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s["text"],
                words=_words_from(s.get("words")),
                avg_logprob=float(s.get("avg_logprob", 0.0)),
                no_speech_prob=float(s.get("no_speech_prob", 0.0)),
                compression_ratio=float(s.get("compression_ratio", 1.0)),
            )
            for s in res.get("segments", [])
        ]
        return ChunkResult(language=res.get("language"), segments=segs)


class FasterWhisperBackend:
    name = "faster-whisper"

    def __init__(self, model: str, device: str = "auto", compute_type: str = "auto"):
        from faster_whisper import WhisperModel

        self.model = model
        self._m = WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, opts: TranscribeOptions) -> ChunkResult:
        seg_iter, info = self._m.transcribe(
            audio,
            language=opts.language,
            task=opts.task,
            initial_prompt=opts.initial_prompt,
            beam_size=5,
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            vad_filter=False,  # đã cắt VAD ở ngoài
        )
        segs = [
            Segment(
                start=float(s.start),
                end=float(s.end),
                text=s.text,
                words=_words_from(s.words),
                avg_logprob=float(s.avg_logprob),
                no_speech_prob=float(s.no_speech_prob),
                compression_ratio=float(s.compression_ratio),
            )
            for s in seg_iter
        ]
        return ChunkResult(language=info.language, segments=segs)


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def make_backend(name: str, model: str) -> Backend:
    if name == "auto":
        name = "mlx" if is_apple_silicon() else "faster-whisper"
    if name == "mlx":
        try:
            return MLXBackend(model)
        except ImportError as e:
            raise RuntimeError(
                "Chưa cài mlx-whisper. Chạy: uv pip install mlx-whisper"
            ) from e
    if name in ("faster-whisper", "fw"):
        return FasterWhisperBackend(model)
    raise ValueError(f"Backend không hợp lệ: {name}")
