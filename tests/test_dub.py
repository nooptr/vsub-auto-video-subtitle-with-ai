import json
import shutil
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from vsub import dub
from vsub.models import Cue

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")


def test_tts_text_strips_tags_and_dashes():
    assert dub.tts_text(Cue(0, 1, ["[tiếng cười] Chào anh!", "♪ la la ♪"])) == "Chào anh! la la"
    assert dub.tts_text(Cue(0, 1, ["- Đi đâu đấy?", "- Về nhà."])) == "Đi đâu đấy?, Về nhà."
    assert dub.tts_text(Cue(0, 1, ["{\\an8}♪♪"])) == ""


def test_plan_fits_lines_into_slots():
    slots = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (10.0, 11.0)]
    p = dub.plan_placements(slots, [1.5, 3.0, 1.0, 3.0])
    assert [x.idx for x in p] == [0, 1, 2, 3]
    assert p[0].start == 0.0 and p[0].tempo == 1.0          # vừa chỗ -> đọc tốc độ thường
    assert p[1].start == pytest.approx(2.0)
    assert p[1].tempo == pytest.approx(1.35)                 # dài hơn chỗ trống tới câu sau -> nhanh tối đa
    assert 4.0 < p[2].start < 4.5                            # lấn một chút, câu sau lùi lại
    assert p[3].start == 10.0 and p[3].tempo == 1.0          # câu sau khoảng lặng: lấn sang lặng, không cần nhanh
    for a, b in zip(p, p[1:]):                               # không bao giờ chồng lên nhau
        assert b.start >= a.end


def test_plan_catches_up_when_late():
    # câu đầu quá dài -> câu 2 bị lùi > 1s -> được đọc nhanh tới 1.6 lần để đuổi kịp
    p = dub.plan_placements([(0.0, 1.0), (1.0, 2.0), (3.0, 4.0)], [4.0, 2.0, 1.0])
    assert p[1].start - 1.0 > 1.0
    assert p[1].tempo > 1.35
    assert all(b.start >= a.end for a, b in zip(p, p[1:]))


def test_plan_skips_empty_lines():
    p = dub.plan_placements([(0, 1), (1, 2), (2, 3)], [1.0, 0.0, 1.0])
    assert [x.idx for x in p] == [0, 2]


def _tone(db, secs, sr=16000, f=440.0):
    t = np.arange(int(secs * sr)) / sr
    return (10 ** (db / 20) * np.sqrt(2) * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_analyze_levels_ducks_loud_background_more():
    sr = 16000
    audio = np.concatenate([_tone(-22, 10), _tone(-40, 10), _tone(-12, 10)])  # thoại / yên / nhạc to
    cues = [(1, 9)]
    places = [dub.Placement(0, 2, 1, 6), dub.Placement(1, 12, 1, 6), dub.Placement(2, 22, 1, 6)]
    plan = dub.analyze_levels(audio, sr, cues, places)
    assert plan.dialog_db == pytest.approx(-22, abs=1)
    assert plan.voice_db == pytest.approx(-21, abs=1)
    quiet, speech, loud = plan.ducks[1], plan.ducks[0], plan.ducks[2]
    assert quiet == pytest.approx(-6)                  # nền yên -> giảm tối thiểu
    assert loud < speech < quiet                       # nền càng to giảm càng nhiều
    assert loud == pytest.approx(-21 - 10 + 12, abs=1)  # vừa đủ để nền thấp hơn giọng 10 dB
    fixed = dub.analyze_levels(audio, sr, cues, places, duck_db=15)
    assert fixed.ducks == [-15, -15, -15]
    assert "giảm" in plan.describe()


def test_duck_curve_ramps_and_holds_between_close_lines():
    places = [dub.Placement(0, 1.0, 1, 1.0), dub.Placement(1, 2.3, 1, 1.0), dub.Placement(2, 6.0, 1, 1.0)]
    xs, ys = dub.duck_curve(places, [-10, -14, -8])
    at = lambda t: float(np.interp(t, xs, ys, left=0, right=0))  # noqa: E731
    assert at(0.5) == 0 and at(1.5) == -10
    assert at(2.15) == pytest.approx(-12)   # khe 0.3s giữa hai câu: giữ mức giảm, nối thẳng
    assert at(2.8) == -14
    assert -14 < at(3.5) < 0                # nhả dần sau câu
    assert at(4.5) == 0 and at(6.5) == -8 and at(7.6) == 0
    assert np.all(np.diff(xs) > 0)


def test_soft_limit_keeps_peaks_under_0dbfs():
    x = np.array([0.1, 0.95, -1.5, 3.0], np.float32)
    y, n = dub.soft_limit(x)
    assert n == 3 and np.all(np.abs(y) < 1.0) and y[0] == pytest.approx(0.1)


def test_trim_silence():
    a = np.concatenate([np.zeros(4800), _tone(-20, 1, sr=48000), np.zeros(9600)]).astype(np.float32)
    t = dub.trim_silence(a)
    assert 0.95 < len(t) / 48000 < 1.1


FAKE_WORKER = textwrap.dedent('''
    import json, math, struct, sys, wave
    job = json.load(sys.stdin)
    print(json.dumps({"ready": True, "voices": ["Giả"]}), flush=True)
    for i, it in enumerate(job["items"]):
        n = int(48000 * (0.4 + 0.05 * len(it["text"])))
        with wave.open(it["out"], "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 1000 * k / 48000)))
                                   for k in range(n)))
        print(json.dumps({"i": i, "ok": True, "dur": n / 48000}), flush=True)
    print(json.dumps({"done": True}), flush=True)
''')


@needs_ffmpeg
def test_voiceover_end_to_end(tmp_path, monkeypatch):
    video = tmp_path / "phim.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8:sample_rate=48000",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER)
    monkeypatch.setattr(dub, "WORKER", str(worker))
    cues = [Cue(1.0, 2.5, ["Xin chào"]), Cue(5.0, 6.5, ["[nhạc] Tạm biệt"])]
    steps = []
    r = dub.voiceover(str(video), cues, python=sys.executable, tts_root=str(tmp_path / "tts"),
                      progress=lambda s, i, n: steps.append(s))
    assert r.out == str(tmp_path / "phim.thuyetminh.mp4") and r.lines == 2
    assert {"tts", "prep", "mix"} <= set(steps)
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", r.out],
                                        capture_output=True, text=True).stdout)["streams"]
    assert [s["codec_type"] for s in streams] == ["video", "audio", "audio"]
    assert streams[1]["disposition"]["default"] == 1 and streams[2]["disposition"]["default"] == 0

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", r.out, "-map", "0:a:0", "-ac", "1", "-ar", "48000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    mix = np.frombuffer(raw, np.float32)
    assert abs(len(mix) / 48000 - 8.0) < 0.2

    def band_db(s, e, f):  # mức của tần số f trong đoạn [s, e]
        x = mix[int(s * 48000):int(e * 48000)]
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        k = int(round(f * len(x) / 48000))
        return 20 * np.log10(spec[k - 3:k + 4].max() + 1e-9)

    # âm gốc (440 Hz) bị giảm khi có lời đọc (1000 Hz), và trở lại khi hết lời
    assert band_db(1.3, 1.8, 440) < band_db(3.3, 4.3, 440) - 5
    assert band_db(1.3, 1.8, 1000) > band_db(3.3, 4.3, 1000) + 20

    # chạy lại: đã có cache -> không gọi VieNeu nữa
    r2 = dub.voiceover(str(video), cues, python="/không/có/python", tts_root=str(tmp_path / "tts"))
    assert r2.lines == 2


def test_synthesize_reports_fatal(tmp_path, monkeypatch):
    worker = tmp_path / "w.py"
    worker.write_text('import json,sys; json.load(sys.stdin); print(json.dumps({"fatal": "không có giọng X"}))')
    monkeypatch.setattr(dub, "WORKER", str(worker))
    with pytest.raises(dub.DubError, match="không có giọng X"):
        dub.synthesize(["chào"], "X", python=sys.executable, root=str(tmp_path / "tts"))
