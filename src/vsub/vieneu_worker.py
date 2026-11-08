"""Đọc nhiều câu bằng VieNeu-TTS, chạy bằng Python của môi trường đã cài VieNeu.

Script đứng riêng, không import vsub (VieNeu thường nằm trong venv khác, Python khác).
dub.py gọi: <python có vieneu> -I vieneu_worker.py, rồi đưa vào stdin:
  {"voice": "Trúc Ly", "ref_audio": null, "items": [{"text": "...", "out": "/đường/dẫn.wav"}, ...]}
  (ref_audio = file giọng mẫu để clone; khi có thì bỏ qua voice)
stdout mỗi dòng một JSON: {"ready": true, "voices": [...]}, {"i": 0, "ok": true, "dur": 1.2},
{"i": 1, "ok": false, "error": "..."}, cuối cùng {"done": true}. Lỗi nạp model: {"fatal": "..."}.
"""

import json
import os
import sys
import time
from pathlib import Path

_proto = sys.stdout


def send(**msg) -> None:
    _proto.write(json.dumps(msg, ensure_ascii=False) + "\n")
    _proto.flush()


def use_local_models() -> None:
    """onnxruntime >= 1.31 từ chối file .data rời khi kho Hugging Face lưu file dạng symlink
    -> đọc model từ thư mục models (cạnh venv, hoặc VSUB_VIENEU_MODELS) gồm file thật.
    Thiếu file nào thì tải thẳng vào đó (local_dir: file thật, không symlink)."""
    base = Path(os.environ.get("VSUB_VIENEU_MODELS") or Path(sys.prefix).parent / "models")
    local = {"pnnbao-ump/VieNeu-TTS-v3-Turbo": base / "vieneu-v3-turbo",
             "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX": base / "moss-codec"}
    try:
        from vieneu._v3_turbo_engine import onnx_runtime_lite as orl
    except ImportError:
        return
    orig = orl.OnnxV3LiteEngine._fetch

    def fetch(repo, files, subfolder):
        root = local.get(repo)
        if root is None:
            return orig(repo, files, subfolder)
        d = root / (subfolder or "")
        missing = [f for f in files if not (d / f).exists()]
        if missing:
            from huggingface_hub import hf_hub_download

            print(f"Tải {len(missing)} file model {repo} vào {root}…", file=sys.stderr, flush=True)
            for f in missing:
                try:
                    hf_hub_download(repo, f, subfolder=subfolder or None, local_dir=str(root))
                except Exception:
                    if not f.endswith(".json"):  # file .json phụ có thể không có trong kho
                        raise
        return d

    orl.OnnxV3LiteEngine._fetch = staticmethod(fetch)


def plausible(dur: float, text: str) -> bool:
    """Bắt lỗi model: đọc lố ("nói thêm" lặp vòng) hoặc gần như không ra tiếng."""
    expect = max(len(text) / 15.0, 0.4)  # tiếng Việt ~15 ký tự/giây
    return 0.3 * expect <= dur <= 3.0 * expect + 1.5


def main() -> None:
    global _proto
    # Thư viện nào in ra stdout cũng không được làm hỏng giao thức: giữ stdout thật cho JSON,
    # còn fd 1 trỏ sang stderr.
    _proto = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    job = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))  # Windows: stdin mặc định cp1252
    try:
        import numpy as np
        import soundfile as sf
        from vieneu import Vieneu

        use_local_models()
        tts = Vieneu()
        voices = [v for _, v in tts.list_preset_voices()]
        voice = job.get("voice") or None
        ref = job.get("ref_audio") or None
        if ref:  # clone: học giọng mẫu một lần (lọc nhiễu + cắt lặng), các câu sau dùng lại
            if not os.path.isfile(ref):
                send(fatal=f"Không thấy file giọng mẫu: {ref}")
                sys.exit(1)
            tts.encode_reference(ref)
        elif voice and tts.resolve_voice_name(voice) is None:
            send(fatal=f"VieNeu không có giọng “{voice}”. Các giọng có: {', '.join(voices)}")
            sys.exit(1)
    except Exception as e:  # noqa: BLE001
        send(fatal=f"{type(e).__name__}: {e}")
        sys.exit(1)
    send(ready=True, voices=voices, sample_rate=tts.sample_rate)
    for i, it in enumerate(job.get("items", [])):
        text, out = it["text"], it["out"]
        t0 = time.time()
        try:
            wav = None
            for attempt in range(3):
                temp = 0.8 if attempt == 0 else 0.6
                w = tts.infer(text, ref_audio=ref, temperature=temp) if ref else \
                    tts.infer(text, voice=voice, temperature=temp)
                w = np.asarray(w, dtype=np.float32)
                dur = len(w) / tts.sample_rate
                wav = w if wav is None or plausible(dur, text) else wav
                if plausible(dur, text):
                    break
            tmp = out + ".part.wav"
            sf.write(tmp, wav, tts.sample_rate, subtype="PCM_16")
            os.replace(tmp, out)  # file dở dang (bị dừng giữa chừng) không bao giờ thành cache
            send(i=i, ok=True, dur=round(len(wav) / tts.sample_rate, 3), secs=round(time.time() - t0, 2))
        except Exception as e:  # noqa: BLE001
            send(i=i, ok=False, error=f"{type(e).__name__}: {e}")
    send(done=True)


if __name__ == "__main__":
    main()
