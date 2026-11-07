"""Thuyết minh: VieNeu-TTS đọc phụ đề tiếng Việt đè lên phim, âm gốc được giảm xuống khi có lời đọc.

Các bước:
1. VieNeu đọc từng câu (chạy bằng Python của môi trường đã cài VieNeu, xem vieneu_worker.py).
   Câu đã đọc được lưu cache theo (giọng, nội dung): sửa một câu thì chỉ đọc lại câu đó.
2. Cắt khoảng lặng đầu/cuối, xếp câu theo giờ phụ đề. Câu dài hơn chỗ trống thì đọc nhanh lên
   (tối đa 1,35 lần; đang trễ so với phụ đề thì tới 1,6 lần để đuổi kịp).
3. Kiểm tra âm trước khi trộn: đo mức thoại gốc để đặt mức giọng đọc, đo nền ở từng câu
   (nhạc, tiếng động, lời gốc) để chọn mức giảm: cảnh ồn giảm nhiều, cảnh yên giảm ít.
4. Trộn: âm gốc giảm/tăng mượt quanh mỗi câu (không giật), các câu sát nhau giữ mức giảm luôn
   cho khỏi "bập bềnh". Đo lại bản trộn: giọng đọc cao hơn nền bao nhiêu dB, đỉnh có bị vỡ không.
5. Xuất video mới: track 1 = thuyết minh (mặc định), track 2 = âm gốc; hình chép nguyên.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .models import Cue

SR = 48_000
DEFAULT_VOICE = "Trúc Ly"
# Giọng có sẵn của VieNeu-TTS v3 Turbo (3.8.x); giọng lạ vẫn dùng được nếu VieNeu có.
VOICES = [
    ("Trúc Ly — nữ, Bắc, tự nhiên", "Trúc Ly"),
    ("Ngọc Huyền — nữ, Bắc, tự nhiên", "Ngọc Huyền"),
    ("Mai Anh — nữ, Bắc, tin tức", "Mai Anh"),
    ("Ngọc Linh — nữ, Bắc, kể chuyện", "Ngọc Linh"),
    ("Đoan Trang — nữ, Bắc, tự nhiên", "Đoan Trang"),
    ("Thùy Dung — nữ, Nam, tin tức", "Thùy Dung"),
    ("Thục Đoan — nữ, Nam, kể chuyện", "Thục Đoan"),
    ("Ngọc Trân — nữ, Trung, tự nhiên", "Ngọc Trân"),
    ("Thiện Minh — nam, Bắc, kể chuyện", "Thiện Minh"),
    ("Hải Đăng — nam, Bắc, tự nhiên", "Hải Đăng"),
    ("Thanh Bình — nam, Bắc, kể chuyện", "Thanh Bình"),
    ("Minh Đức — nam, Bắc, tin tức", "Minh Đức"),
    ("Quốc Tuấn — nam, Bắc, tự nhiên", "Quốc Tuấn"),
    ("Thái Sơn — nam, Nam, kể chuyện", "Thái Sơn"),
    ("Quang Sơn — nam, Trung, tự nhiên", "Quang Sơn"),
]
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vieneu_worker.py")
CACHE_VERSION = "1"


class DubError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ tìm VieNeu

def _python_from_shebang(script: str) -> str | None:
    try:
        with open(script, "rb") as f:
            first = f.readline().decode(errors="replace").strip()
    except OSError:
        return None
    if first.startswith("#!"):
        exe = first[2:].strip().split()[0]
        return exe if os.path.basename(exe).startswith("python") else None
    return None


def _has_vieneu(python: str) -> bool:
    try:
        r = subprocess.run(
            [python, "-I", "-c", "import importlib.util,sys; sys.exit(importlib.util.find_spec('vieneu') is None)"],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_found: dict[str, str | None] = {}


def find_vieneu_python(refresh: bool = False) -> str | None:
    """Python của môi trường đã cài VieNeu: VSUB_VIENEU_PYTHON, venv app tự cài (deps.vieneu_home),
    ~/video-tools/vnenv, venv có lệnh vieneu-web/vieneu-stream, hoặc chính Python đang chạy."""
    from .deps import vieneu_home
    from .paths import IS_WIN, venv_python

    if "py" in _found and not refresh:
        return _found["py"]
    home = os.path.expanduser("~")
    cands = [os.environ.get("VSUB_VIENEU_PYTHON"), venv_python(os.path.join(vieneu_home(), "venv")),
             f"{home}/video-tools/vnenv/bin/python"]
    scripts = [shutil.which(n) for n in ("vieneu-web", "vieneu-stream")]
    sub = "Scripts" if IS_WIN else "bin"
    for depth in ("*", "*/*", "*/*/*"):
        scripts += sorted(glob.glob(os.path.join(home, depth, sub, "vieneu-web*")))
    for s in filter(None, scripts):
        if IS_WIN:  # venv Windows: python.exe nằm cạnh vieneu-web.exe
            cands.append(os.path.join(os.path.dirname(s), "python.exe"))
        else:
            cands.append(_python_from_shebang(s))
    cands.append(sys.executable)
    seen = set()
    for c in cands:
        if not c or c in seen or not os.path.isfile(c):
            continue
        seen.add(c)
        if _has_vieneu(c):
            _found["py"] = c
            return c
    _found["py"] = None
    return None


# ------------------------------------------------------------------ chữ đọc

_TAGS = re.compile(r"\[[^\]]*\]|♪+|\{[^}]*\}|<[^>]+>")


def tts_text(cue: Cue) -> str:
    """Chữ để đọc: bỏ tag âm thanh [..], nốt nhạc, tag định dạng; nối các dòng của cue."""
    t = _TAGS.sub(" ", " ".join(cue.lines))
    t = re.sub(r"^\s*[-–—]\s*", "", t)            # gạch đầu dòng hội thoại
    t = re.sub(r"\s+[-–—]\s+", ", ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if re.search(r"\w", t) else ""


def cache_dir() -> str:
    from .paths import cache_dir as base

    return os.path.join(base(), "tts")


def cache_path(voice: str, text: str, root: str | None = None) -> str:
    h = hashlib.sha1(f"{CACHE_VERSION}|{voice}|{text}".encode()).hexdigest()[:20]
    return os.path.join(root or cache_dir(), h[:2], h + ".wav")


# ------------------------------------------------------------------ VieNeu

def synthesize(
    texts: list[str],
    voice: str = DEFAULT_VOICE,
    python: str | None = None,
    root: str | None = None,
    progress: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[str | None]:
    """Đọc các câu chưa có trong cache. Trả về đường dẫn WAV cho từng câu (None = câu trống / lỗi)."""
    say = status or (lambda _m: None)
    paths = [cache_path(voice, t, root) if t else None for t in texts]
    todo: dict[str, str] = {}
    for t, p in zip(texts, paths):
        if p and not os.path.exists(p):
            todo.setdefault(p, t)
    done_before = len({p for p in paths if p}) - len(todo)
    if not todo:
        say(f"Đã có sẵn giọng đọc của cả {done_before} câu (cache)")
        return paths
    python = python or find_vieneu_python()
    if not python:
        raise DubError("Không tìm thấy VieNeu-TTS. Mở tab “Thư viện” để cài, hoặc đặt biến "
                       "VSUB_VIENEU_PYTHON = Python của môi trường đã cài vieneu.")
    for p in todo:
        os.makedirs(os.path.dirname(p), exist_ok=True)
    items = [{"text": t, "out": p} for p, t in todo.items()]
    say(f"VieNeu ({voice}) đang đọc {len(items)} câu"
        + (f", {done_before} câu đã có trong cache" if done_before else "") + "…")
    errors: list[str] = []
    with tempfile.TemporaryFile("w+") as err, tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen([python, "-I", WORKER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=err, text=True, encoding="utf-8", cwd=tmp)
        try:
            proc.stdin.write(json.dumps({"voice": voice, "items": items}, ensure_ascii=False))
            proc.stdin.close()
            n = 0
            for line in proc.stdout:
                if cancel and cancel.is_set():
                    raise Cancelled()
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "fatal" in msg:
                    raise DubError("VieNeu lỗi: " + msg["fatal"])
                if "i" in msg:
                    n += 1
                    if not msg.get("ok"):
                        errors.append(f"“{items[msg['i']]['text'][:40]}”: {msg.get('error')}")
                    if progress:
                        progress(n, len(items))
            proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        if proc.returncode:
            err.seek(0)
            tail = err.read()[-600:].strip()
            raise DubError(f"VieNeu dừng bất thường (mã {proc.returncode}): {tail}")
    if errors:
        say(f"! {len(errors)} câu VieNeu không đọc được, bỏ qua: " + "; ".join(errors[:3]))
    return [p if p and os.path.exists(p) else None for p in paths]


# ------------------------------------------------------------------ xử lý âm thanh

def read_wav(path: str) -> np.ndarray:
    """WAV PCM16 -> float32 mono 48 kHz."""
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = w.readframes(n)
    a = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != SR and len(a):
        x = np.arange(int(len(a) * SR / sr)) * (sr / SR)
        a = np.interp(x, np.arange(len(a)), a).astype(np.float32)
    return a


def frame_db(a: np.ndarray, sr: int, win: float = 0.05) -> np.ndarray:
    n = max(1, int(win * sr))
    m = len(a) // n
    if m == 0:
        return np.full(1, -120.0)
    f = a[: m * n].reshape(m, n)
    return 20 * np.log10(np.sqrt(np.mean(f * f, axis=1)) + 1e-9)


def power_mean_db(db: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(10 ** (db / 10)) + 1e-12))


def active_db(a: np.ndarray, sr: int = SR, rel: float = 20.0) -> float | None:
    """Mức (dBFS RMS) của phần có tiếng: bỏ các khung thấp hơn khung to nhất quá `rel` dB."""
    db = frame_db(a, sr)
    top = float(db.max())
    if top < -70:
        return None
    return power_mean_db(db[db > top - rel])


def trim_silence(a: np.ndarray, sr: int = SR, rel: float = 40.0, floor: float = -55.0,
                 pad: float = 0.03) -> np.ndarray:
    db = frame_db(a, sr, 0.01)
    thr = max(float(db.max()) - rel, floor)
    on = np.flatnonzero(db > thr)
    if not len(on):
        return a[:0]
    n = int(0.01 * sr)
    s = max(0, on[0] * n - int(pad * sr))
    e = min(len(a), (on[-1] + 1) * n + int(pad * sr))
    return a[s:e]


def stretch(a: np.ndarray, tempo: float, sr: int = SR) -> np.ndarray:
    """Đọc nhanh lên `tempo` lần, giữ cao độ (ffmpeg atempo)."""
    if abs(tempo - 1.0) < 0.01 or not len(a):
        return a
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         "-af", f"atempo={tempo:.4f}", "-f", "f32le", "-"],
        input=a.astype(np.float32).tobytes(), capture_output=True,
    )
    if r.returncode or not r.stdout:
        raise DubError("ffmpeg atempo lỗi: " + r.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(r.stdout, np.float32).copy()


# ------------------------------------------------------------------ xếp lịch đọc

@dataclass
class Placement:
    idx: int      # câu thứ mấy trong danh sách phụ đề
    start: float  # giây bắt đầu đọc
    tempo: float  # hệ số đọc nhanh
    dur: float    # độ dài sau khi đọc nhanh

    @property
    def end(self) -> float:
        return self.start + self.dur


def plan_placements(slots: list[tuple[float, float]], durs: list[float], max_tempo: float = 1.35,
                    catchup_tempo: float = 1.6, gap: float = 0.12, tail: float = 2.0) -> list[Placement]:
    """Mỗi câu đọc từ lúc phụ đề hiện. Câu dài hơn chỗ trống (tới câu sau) thì đọc nhanh lên;
    vẫn không vừa thì lấn sang, câu sau lùi lại một chút và được đọc nhanh hơn để đuổi kịp."""
    out: list[Placement] = []
    prev_end = -1e9
    n = len(slots)
    for i, ((s, e), d) in enumerate(zip(slots, durs)):
        if d <= 0:
            continue
        start = max(s, prev_end + gap)
        nxt = next((slots[j][0] for j in range(i + 1, n) if durs[j] > 0), max(e, s + d) + tail)
        avail = max(nxt - gap - start, 0.25)
        cap = catchup_tempo if start - s > 1.0 else max_tempo
        tempo = min(max(d / avail, 1.0), cap)
        if tempo < 1.03:
            tempo = 1.0
        out.append(Placement(i, start, round(tempo, 4), d / tempo))
        prev_end = start + d / tempo
    return out


# ------------------------------------------------------------------ kiểm tra âm, mức giảm

@dataclass
class LevelPlan:
    dialog_db: float                  # mức thoại gốc (dBFS RMS)
    voice_db: float                   # mức đặt cho giọng thuyết minh
    bg_db: list[float]                # nền (âm gốc) trong lúc đọc từng câu
    ducks: list[float]                # dB giảm âm gốc cho từng câu (số âm)
    fixed: bool = False

    def describe(self) -> str:
        d = np.array(self.ducks) if self.ducks else np.zeros(1)
        b = np.array(self.bg_db) if self.bg_db else np.zeros(1)
        how = "cố định" if self.fixed else "tự động theo nền từng câu"
        return (f"Kiểm tra âm: thoại gốc ≈ {self.dialog_db:.0f} dB, nền lúc đọc {b.min():.0f}…{b.max():.0f} dB"
                f" → giọng đọc đặt ở {self.voice_db:.0f} dB, âm gốc giảm {-d.max():.0f}–{-d.min():.0f} dB"
                f" (trung bình {-d.mean():.0f} dB, {how})")


def analyze_levels(audio: np.ndarray, sr: int, cue_windows: list[tuple[float, float]],
                   placements: list[Placement], duck_db: float | None = None, margin: float = 10.0,
                   min_duck: float = 6.0, max_duck: float = 24.0) -> LevelPlan:
    """Đo âm gốc trước khi trộn.

    - Mức thoại gốc: trung vị mức "phần có tiếng" trong các khoảng có phụ đề. Giọng đọc đặt cao hơn
      1 dB (trong khoảng −24…−16 dB) để độ to tổng thể gần như phim gốc.
    - Nền trong lúc đọc từng câu: phân vị 90 của các khung 100 ms (bắt được đoạn nhạc/hét to).
      Mức giảm = vừa đủ để nền thấp hơn giọng đọc `margin` dB, trong khoảng `min_duck`…`max_duck`.
    `duck_db` (số dương) = giảm cố định cho mọi câu, bỏ qua phần tự động."""
    db = frame_db(audio, sr, 0.1)
    rate = 10.0

    def frames(s: float, e: float) -> np.ndarray:
        a, b = int(s * rate), max(int(e * rate), int(s * rate) + 1)
        return db[max(0, a):max(0, min(b, len(db)))]

    levels = []
    for s, e in cue_windows:
        f = frames(s, e)
        if len(f) and f.max() > -60:
            levels.append(power_mean_db(f[f > f.max() - 20]))
    dialog = float(np.median(levels)) if levels else -24.0
    voice = float(np.clip(dialog + 1.0, -24.0, -16.0))
    bgs, ducks = [], []
    for p in placements:
        f = frames(p.start, p.end)
        bg = float(np.percentile(f, 90)) if len(f) else -90.0
        bgs.append(bg)
        if duck_db is not None:
            ducks.append(-abs(duck_db))
        else:
            ducks.append(float(np.clip(voice - margin - bg, -max_duck, -min_duck)))
    return LevelPlan(dialog, voice, bgs, ducks, fixed=duck_db is not None)


def duck_curve(placements: list[Placement], ducks: list[float], attack: float = 0.15,
               release: float = 0.4, hold_gap: float = 0.8) -> tuple[np.ndarray, np.ndarray]:
    """Đường mức giảm (giây, dB) nối thẳng giữa các điểm; ngoài các điểm là 0 dB.

    Âm gốc giảm dần trong `attack` giây trước khi đọc, giữ trong lúc đọc, tăng lại trong `release`.
    Hai câu cách nhau dưới `hold_gap` giây thì giữ mức giảm luôn (nối thẳng mức của hai câu)."""
    xs: list[float] = []
    ys: list[float] = []
    groups: list[list[tuple[float, float, float]]] = []
    for p, d in zip(placements, ducks):
        if p.dur <= 0:
            continue
        if groups and p.start - groups[-1][-1][1] < hold_gap:
            groups[-1].append((p.start, p.end, d))
        else:
            groups.append([(p.start, p.end, d)])
    eps = 1e-4
    for g in groups:
        pts = [(g[0][0] - attack, 0.0)]
        for s, e, d in g:
            pts += [(s, d), (e, d)]
        pts.append((g[-1][1] + release, 0.0))
        for x, y in pts:
            if xs and x <= xs[-1]:
                x = xs[-1] + eps
            xs.append(x)
            ys.append(y)
    return np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64)


def soft_limit(x: np.ndarray, thr: float = 0.89, ceil: float = 0.98) -> tuple[np.ndarray, int]:
    """Nén mềm phần vượt −1 dBFS, không bao giờ quá `ceil` (để mã hoá AAC không vỡ tiếng).
    Trả về (tín hiệu, số mẫu phải nén)."""
    over = np.abs(x) > thr
    n = int(over.sum())
    if n:
        k = ceil - thr
        y = x.copy()
        y[over] = np.sign(x[over]) * (thr + k * np.tanh((np.abs(x[over]) - thr) / k))
        return y, n
    return x, 0


# ------------------------------------------------------------------ trộn và xuất

@dataclass
class DubResult:
    out: str
    lines: int
    plan: LevelPlan
    margin_db: float          # giọng đọc cao hơn nền (đo trên bản trộn), trung bình
    margin_min_db: float
    peak_db: float
    limited: int              # số mẫu phải nén mềm
    sped_up: int              # số câu phải đọc nhanh
    late: float               # câu trễ nhất so với phụ đề (giây)
    elapsed: float
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"Kiểm tra bản trộn: giọng đọc cao hơn nền trung bình {self.margin_db:.0f} dB "
                f"(thấp nhất {self.margin_min_db:.0f} dB), đỉnh {self.peak_db:.1f} dB"
                + (f", nén mềm {self.limited} mẫu" if self.limited else "")
                + (f"; {self.sped_up} câu đọc nhanh hơn" if self.sped_up else "")
                + (f", câu trễ nhất {self.late:.1f}s" if self.late > 0.3 else ""))


def output_path(video: str) -> str:
    stem, ext = os.path.splitext(video)
    ext = ext.lower()
    if _probe_has_video(video):
        ext = ext if ext in (".mp4", ".m4v", ".mov", ".mkv") else ".mkv"
    else:
        ext = ".m4a"
    return f"{stem}.thuyetminh{ext}"


def _probe(video: str) -> list[dict]:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", video],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(r.stdout).get("streams", [])
    except ValueError:
        return []


def _probe_has_video(video: str) -> bool:
    return any(s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
               for s in _probe(video))


def _write_narration(path: str, clips, total: int) -> None:
    """Ghi track giọng đọc (mono PCM16) theo thứ tự thời gian; các câu không chồng lên nhau."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        pos = 0
        zero = np.zeros(SR * 10, np.int16)
        for at, a in clips:
            if at >= total:
                break
            while pos < at:
                k = min(at - pos, len(zero))
                w.writeframes(zero[:k].tobytes())
                pos += k
            a = a[: max(0, total - pos)]
            w.writeframes(np.clip(a * 32767, -32768, 32767).astype(np.int16).tobytes())
            pos += len(a)
        while pos < total:
            k = min(total - pos, len(zero))
            w.writeframes(zero[:k].tobytes())
            pos += k


def _audio_codec(video: str, track: int) -> str:
    aud = [s for s in _probe(video) if s.get("codec_type") == "audio"]
    return aud[track].get("codec_name", "") if track < len(aud) else ""


def _mix(video: str, out: str, narration: str, curve: tuple[np.ndarray, np.ndarray], total: int,
         placements: list[Placement], track: int,
         progress: Callable[[int, int], None] | None, cancel: threading.Event | None) -> dict:
    """Giải mã âm gốc -> giảm theo đường mức -> cộng giọng đọc -> nén mềm -> mã hoá AAC, ghép với hình."""
    xs, ys = curve
    has_video = _probe_has_video(video)
    ext = os.path.splitext(out)[1].lower()
    mp4ish = ext in (".mp4", ".m4v", ".mov", ".m4a")
    orig_copy = not mp4ish or _audio_codec(video, track) in ("aac", "mp3", "ac3", "eac3", "alac")
    dec_cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", video, "-map", f"0:a:{track}", "-vn",
               "-af", "aresample=async=1:first_pts=0", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    enc_cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2",
               "-i", "pipe:0", "-i", video]
    if has_video:
        enc_cmd += ["-map", "1:v:0", "-c:v", "copy"]
    enc_cmd += ["-map", "0:a", "-map", f"1:a:{track}", "-c:a:0", "aac", "-b:a:0", "192k",
                "-c:a:1", "copy" if orig_copy else "aac", *([] if orig_copy else ["-b:a:1", "192k"]),
                "-metadata:s:a:0", "language=vie", "-disposition:a:0", "default", "-disposition:a:1", "0"]
    for i, name in enumerate(("Thuyết minh (VieNeu)", "Âm gốc")):  # MP4 hiện tên track bằng handler_name
        enc_cmd += [f"-metadata:s:a:{i}", f"title={name}", f"-metadata:s:a:{i}", f"handler_name={name}"]
    if mp4ish:
        enc_cmd += ["-movflags", "+faststart"]
    tmp_out = out + ".part" + ext
    enc_cmd.append(tmp_out)

    starts = np.array([int(p.start * SR) for p in placements])
    ends = np.array([int(p.end * SR) for p in placements])
    e_bg = np.zeros(len(placements))
    e_vo = np.zeros(len(placements))
    peak, limited = 0.0, 0
    block = SR * 5
    with tempfile.TemporaryFile() as derr, tempfile.TemporaryFile() as eerr:
        dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=derr)
        enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=eerr)
        try:
            with wave.open(narration, "rb") as nar:
                pos = 0
                while True:
                    if cancel and cancel.is_set():
                        raise Cancelled()
                    raw = dec.stdout.read(block * 8)
                    if not raw:
                        break
                    o = np.frombuffer(raw[: len(raw) // 8 * 8], np.float32).reshape(-1, 2)
                    n = len(o)
                    t = (pos + np.arange(n)) / SR
                    g = 10 ** (np.interp(t, xs, ys, left=0.0, right=0.0) / 20) if len(xs) else np.ones(n)
                    bg = o * g[:, None]
                    v = np.frombuffer(nar.readframes(n), np.int16).astype(np.float32) / 32768.0
                    if len(v) < n:
                        v = np.pad(v, (0, n - len(v)))
                    mix, k = soft_limit(bg + v[:, None])
                    limited += k
                    peak = max(peak, float(np.abs(mix).max()) if n else 0.0)
                    # đo lại: năng lượng nền (đã giảm) và giọng đọc trong từng câu
                    for j in np.flatnonzero((starts < pos + n) & (ends > pos)):
                        a, b = max(starts[j], pos) - pos, min(ends[j], pos + n) - pos
                        e_bg[j] += float(np.sum(bg[a:b].mean(axis=1) ** 2))
                        e_vo[j] += float(np.sum(v[a:b] ** 2))
                    enc.stdin.write(mix.astype(np.float32).tobytes())
                    pos += n
                    if progress:
                        progress(min(pos, total), total)
            enc.stdin.close()
            dec.wait()
            enc.wait()
        except BrokenPipeError:  # ffmpeg mã hoá chết giữa chừng -> báo lỗi của nó bên dưới
            dec.kill()
            dec.wait()
            enc.wait()
        except BaseException:
            for p in (dec, enc):
                p.kill()
                p.wait()
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            raise
        if enc.returncode or dec.returncode:
            eerr.seek(0)
            derr.seek(0)
            msg = (eerr.read() or derr.read()).decode(errors="replace")[-500:]
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            raise DubError(f"ffmpeg lỗi khi trộn/xuất: {msg}")
    os.replace(tmp_out, out)
    ok = e_vo > 0
    margins = 10 * np.log10((e_vo[ok] + 1e-12) / (e_bg[ok] + 1e-12)) if ok.any() else np.zeros(1)
    return {"margin": float(np.mean(np.minimum(margins, 40))), "margin_min": float(np.min(margins)),
            "peak_db": 20 * np.log10(peak + 1e-9), "limited": limited}


def voiceover(
    video: str,
    cues: list[Cue],
    out: str | None = None,
    voice: str = DEFAULT_VOICE,
    duck_db: float | None = None,
    audio_track: int = 0,
    python: str | None = None,
    status: Callable[[str], None] | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    cancel: threading.Event | None = None,
    tts_root: str | None = None,
) -> DubResult:
    """Làm bản thuyết minh cho `video` từ phụ đề tiếng Việt `cues`."""
    from .audio import load_audio

    say = status or (lambda _m: None)
    prog = progress or (lambda *_a: None)
    t0 = time.time()
    out = out or output_path(video)
    cues = sorted(cues, key=lambda c: c.start)
    texts = [tts_text(c) for c in cues]
    if not any(texts):
        raise DubError("Phụ đề không có câu nào để đọc")

    wavs = synthesize(texts, voice, python, tts_root, progress=lambda i, n: prog("tts", i, n),
                      status=say, cancel=cancel)

    say("Kiểm tra âm gốc và giọng đọc…")

    def clip(i: int) -> np.ndarray | None:
        a = trim_silence(read_wav(wavs[i])) if wavs[i] else None
        return a if a is not None and len(a) > SR // 20 else None

    durs, clip_db = [], []
    for i in range(len(wavs)):  # chỉ giữ độ dài và mức to, không giữ cả câu trong RAM
        a = clip(i)
        durs.append(len(a) / SR if a is not None else 0.0)
        clip_db.append(active_db(a) if a is not None else None)
    places = plan_placements([(c.start, c.end) for c in cues], durs)
    if not places:
        raise DubError("VieNeu không đọc được câu nào")
    if cancel and cancel.is_set():
        raise Cancelled()

    audio16 = load_audio(video, audio_track)
    plan = analyze_levels(audio16, 16000, [(c.start, c.end) for c in cues], places, duck_db)
    say(plan.describe())
    total = int(max(len(audio16) / 16000, places[-1].end) * SR)
    del audio16

    say(f"Trộn giọng đọc vào phim ({len(places)} câu)…")
    with tempfile.TemporaryDirectory() as tmp:
        narration = os.path.join(tmp, "narration.wav")

        def ready():
            for k, p in enumerate(places):
                if cancel and cancel.is_set():
                    raise Cancelled()
                a = stretch(clip(p.idx), p.tempo)
                gain = 10 ** ((plan.voice_db - (clip_db[p.idx] or plan.voice_db)) / 20)
                peak = float(np.abs(a).max()) * gain if len(a) else 0.0
                if peak > 0.89:  # không để một câu tự vỡ tiếng
                    gain *= 0.89 / peak
                prog("prep", k + 1, len(places))
                yield int(p.start * SR), (a * gain).astype(np.float32)

        _write_narration(narration, ready(), total)
        stats = _mix(video, out, narration, duck_curve(places, plan.ducks), total, places, audio_track,
                     lambda i, n: prog("mix", i, n), cancel)
    late = max((p.start - cues[p.idx].start for p in places), default=0.0)
    res = DubResult(out, len(places), plan, stats["margin"], stats["margin_min"], stats["peak_db"],
                    stats["limited"], sum(1 for p in places if p.tempo > 1.0), late, time.time() - t0)
    if res.margin_min_db < 3:
        res.warnings.append("có câu giọng đọc gần bằng nền (cảnh nhạc rất to) — thử giảm âm gốc cố định 18–20 dB")
    return res
