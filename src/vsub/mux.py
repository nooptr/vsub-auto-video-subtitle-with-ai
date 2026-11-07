"""Gắn phụ đề vào video bằng ffmpeg: phụ đề mềm (bật/tắt được) hoặc in cứng lên hình."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ISO639_2 = {
    "vi": "vie", "en": "eng", "zh": "chi", "ja": "jpn", "ko": "kor", "fr": "fre",
    "de": "ger", "es": "spa", "th": "tha", "ru": "rus", "it": "ita", "pt": "por",
    "id": "ind", "ms": "may", "hi": "hin", "ar": "ara", "yue": "chi",
}

def make_style(position: str = "bottom", font_size: int = 18, margin: int = 26) -> str:
    """Kiểu chữ ASS cho phụ đề cứng. position: bottom | top."""
    # libass hiểu force_style của SRT theo kiểu SSA cũ: 2 = giữa-dưới, 6 = giữa-trên
    align = 6 if position == "top" else 2
    return (
        f"FontName=Arial,FontSize={font_size},PrimaryColour=&H00FFFFFF,"
        f"OutlineColour=&H00000000,BorderStyle=1,Outline=1.2,Shadow=0.6,"
        f"Alignment={align},MarginV={margin}"
    )


DEFAULT_STYLE = make_style()


def _probe_streams(path: str) -> list[dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    return json.loads(out).get("streams", [])


def _run(cmd: list[str], cwd: str | None = None) -> None:
    print("• " + " ".join(cmd[:3]) + " ...", file=sys.stderr, flush=True)
    proc = subprocess.run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi (mã {proc.returncode})")


def embed_soft(video: str, subs: str, out: str, language: str | None = None, title: str | None = None) -> None:
    n_subs = sum(1 for s in _probe_streams(video) if s.get("codec_type") == "subtitle")
    ext = os.path.splitext(out)[1].lower()
    codec = {".mp4": "mov_text", ".m4v": "mov_text", ".mov": "mov_text", ".webm": "webvtt"}.get(ext, "srt")
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-stats", "-y",
        "-i", video, "-i", subs,
        "-map", "0", "-map", "1:0", "-c", "copy", f"-c:s:{n_subs}", codec,
        f"-disposition:s:{n_subs}", "default",
    ]
    if language:
        cmd += [f"-metadata:s:s:{n_subs}", f"language={ISO639_2.get(language, language)}"]
    cmd += [f"-metadata:s:s:{n_subs}", f"title={title or 'vsub'}"]
    if ext in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    _run(cmd + [out])


def _has_encoder(name: str) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return f" {name} " in out


def burn_in(video: str, subs: str, out: str, style: str = DEFAULT_STYLE) -> None:
    video, out = os.path.abspath(video), os.path.abspath(out)
    v = next((s for s in _probe_streams(video) if s.get("codec_type") == "video"), {})
    src_bps = int(v.get("bit_rate") or 0)
    if _has_encoder("h264_videotoolbox"):  # encode phần cứng trên Mac
        bps = max(int(src_bps * 1.3), 3_000_000)
        venc = ["-c:v", "h264_videotoolbox", "-b:v", str(bps), "-allow_sw", "1"]
    else:
        venc = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
    with tempfile.TemporaryDirectory() as tmp:
        # chạy trong thư mục tạm để không phải escape đường dẫn trong filter
        ext = os.path.splitext(subs)[1].lower() or ".srt"
        shutil.copy(subs, os.path.join(tmp, "subs" + ext))
        vf = f"subtitles=subs{ext}:charenc=UTF-8:force_style='{style}'"
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error", "-stats", "-y", "-i", video,
            "-vf", vf, *venc, "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", out,
        ]
        _run(cmd, cwd=tmp)
