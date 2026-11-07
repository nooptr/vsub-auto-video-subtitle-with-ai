import numpy as np

from vsub.backends import ChunkResult, TranscribeOptions
from vsub.models import Segment, Word
from vsub import pipeline


class FakeBackend:
    name, model = "fake", "fake"

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, opts: TranscribeOptions):
        self.calls.append(opts.language)
        self.prompts = getattr(self, "prompts", []) + [opts.initial_prompt]
        dur = len(audio) / 16000
        # chunk đầu tiên giả vờ nhận nhầm ngôn ngữ
        lang = opts.language or ("en" if len(self.calls) == 1 else "vi")
        w = [Word(0.1, 0.5, " Xin"), Word(0.5, 0.9, " chào.")]
        return ChunkResult(lang, [Segment(0.1, 0.9, " Xin chào.", w)])


def test_offsets_and_language_vote(monkeypatch):
    regions = [(1.0, 9.0), (20.0, 35.0), (50.0, 75.0), (90.0, 100.0)]
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: regions)
    audio = np.zeros(16000 * 120, dtype=np.float32)
    be = FakeBackend()
    t = pipeline.transcribe_video("x.mp4", be, TranscribeOptions(), progress=None, audio=audio)
    assert t.language == "vi"
    # chunk 1 bị nhận là "en" phải được chạy lại với language="vi"
    assert be.calls.count("vi") >= 1
    starts = [s.start for s in t.segments]
    assert starts == sorted(starts)
    assert abs(t.segments[0].start - (1.0 - 0.15 + 0.1)) < 1e-6
    assert all(w.start >= 0.8 for s in t.segments for w in s.words)
    cues = pipeline.make_cues(t)
    assert len(cues) >= 4 and [c.start for c in cues] == sorted(c.start for c in cues)


def test_transcript_roundtrip(tmp_path):
    t = pipeline.Transcript("v.mp4", "fake", "m", "transcribe", "vi", 10.0, [(0, 5)],
                            [Segment(0, 1, " a", [Word(0, 1, " a", 0.9)])])
    p = tmp_path / "t.json"
    t.save(str(p))
    t2 = pipeline.Transcript.load(str(p))
    assert t2.segments[0].words[0].probability == 0.9 and t2.chunks == [(0, 5)]


def test_punctuation_prompt_for_japanese(monkeypatch):
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(1.0, 9.0), (20.0, 30.0)])
    be = FakeBackend()
    pipeline.transcribe_video("x.mp4", be, TranscribeOptions(language="ja"), progress=None,
                              audio=np.zeros(16000 * 40, dtype=np.float32), status=None)
    assert all(p and "。" in p for p in be.prompts)
    be2 = FakeBackend()
    pipeline.transcribe_video("x.mp4", be2, TranscribeOptions(language="vi"), progress=None,
                              audio=np.zeros(16000 * 40, dtype=np.float32), status=None)
    assert all(p is None for p in be2.prompts)


def test_script_language():
    from vsub.pipeline import script_language
    assert script_language("明明まさか異性化男性が女性に女性なら男性になる異性化体質といえます" * 2) == "ja"
    assert script_language("아키라! 아키라! 괜찮아? 무슨 일이야 정말 이상하다 어떻게 된 거야") == "ko"
    assert script_language("你好，最近怎么样？我们一起去吃饭吧，然后再去看电影好不好") == "zh"
    assert script_language("Xin chào các bạn") is None


class KoreanFirstBackend(FakeBackend):
    """Giả lập Whisper đoán nhầm tiếng Hàn ở đoạn mở đầu, và chữ ra vẫn là tiếng Nhật."""

    def transcribe(self, audio, opts):
        self.calls.append(opts.language)
        dur = len(audio) / 16000
        lang = opts.language or ("ko" if len(self.calls) <= 2 else "ja")
        text = "今日はいい天気ですね。散歩に行きましょうか。" if lang == "ja" else "아키라! 아키라! 괜찮아? 무슨 일이야 정말"
        w = [Word(0.1, dur - 0.1, text)]
        return ChunkResult(lang, [Segment(0.1, dur - 0.1, text, w)])


def test_language_vote_skips_intro_and_uses_script(monkeypatch):
    regions = [(5.0, 15.0), (20.0, 30.0)] + [(130.0 + i * 60, 140.0 + i * 60) for i in range(12)]
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: regions)
    be = KoreanFirstBackend()
    t = pipeline.transcribe_video("x.mp4", be, TranscribeOptions(), progress=None,
                                  audio=np.zeros(16000 * 900, dtype=np.float32), status=None)
    assert t.language == "ja"


class AlwaysKorean(FakeBackend):
    def transcribe(self, audio, opts):
        self.calls.append(opts.language)
        dur = len(audio) / 16000
        text = "今日はいい天気ですね。散歩に行きましょうか。"  # Whisper trả "ko" nhưng chữ là tiếng Nhật
        return ChunkResult(opts.language or "ko", [Segment(0.1, dur - 0.1, text, [Word(0.1, dur - 0.1, text)])])


def test_relock_when_script_disagrees(monkeypatch):
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(10.0 + i * 30, 35.0 + i * 30) for i in range(10)])
    be = AlwaysKorean()
    msgs = []
    t = pipeline.transcribe_video("x.mp4", be, TranscribeOptions(), progress=None,
                                  audio=np.zeros(16000 * 400, dtype=np.float32), status=msgs.append)
    assert t.language == "ja"
    assert "ja" in be.calls  # đã chạy lại với tiếng Nhật


class DetectsKoreanTextThenJapanese(FakeBackend):
    """Lúc đoán ngôn ngữ chỉ nghe được tiếng hét (Hangul), lúc chạy thật thì chữ là tiếng Nhật."""

    def transcribe(self, audio, opts):
        self.calls.append(opts.language)
        dur = len(audio) / 16000
        if opts.language is None:
            text, lang = "아키라! 아키라! 괜찮아? 무슨 일이야 정말 이상하다", "ko"
        else:
            text, lang = "今日はいい天気ですね。散歩に行きましょうか。", opts.language
        return ChunkResult(lang, [Segment(0.1, dur - 0.1, text, [Word(0.1, dur - 0.1, text)])])


def test_relock_after_early_check(monkeypatch):
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(10.0 + i * 30, 35.0 + i * 30) for i in range(12)])
    be = DetectsKoreanTextThenJapanese()
    msgs = []
    t = pipeline.transcribe_video("x.mp4", be, TranscribeOptions(), progress=None,
                                  audio=np.zeros(16000 * 400, dtype=np.float32), status=msgs.append)
    assert t.language == "ja"
    assert any("chạy lại với ja" in m for m in msgs)


def test_explicit_language_only_warns(monkeypatch):
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(10.0, 35.0), (40.0, 65.0)])
    msgs = []
    t = pipeline.transcribe_video("x.mp4", AlwaysKorean(), TranscribeOptions(language="ko"), progress=None,
                                  audio=np.zeros(16000 * 80, dtype=np.float32), status=msgs.append)
    assert t.language == "ko" and any("Cảnh báo" in m for m in msgs)



class LoopThenOk(FakeBackend):
    """Chunk dài thì lặp vòng, chunk ngắn (sau khi chia đôi) thì ra chữ thật."""

    def transcribe(self, audio, opts):
        self.calls.append(opts.language)
        dur = len(audio) / 16000
        if dur > 12:
            txt = "あ、" * 60
            return ChunkResult("ja", [Segment(0.1, dur - 0.1, txt, [Word(0.1, dur - 0.1, txt)], compression_ratio=20)])
        txt = "本当にありがとう。"
        return ChunkResult("ja", [Segment(0.2, dur - 0.2, txt, [Word(0.2 + i * (dur - 0.4) / 9, 0.2 + (i + 1) * (dur - 0.4) / 9, ch) for i, ch in enumerate(txt)])])


def test_loop_chunk_is_split_and_retried(monkeypatch):
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(10.0, 30.0)])
    t = pipeline.transcribe_video("x.mp4", LoopThenOk(), TranscribeOptions(language="ja"), progress=None,
                                  audio=np.zeros(16000 * 40, dtype=np.float32), status=None)
    assert t.segments and all("あ、あ、" not in s.text for s in t.segments)
    assert sum("ありがとう" in s.text for s in t.segments) >= 2


def test_plan_chunks_keeps_music_separate():
    from vsub.pipeline import plan_chunks
    ch = plan_chunks([(0.0, 5.0), (40.0, 45.0)], [(5.0, 40.0)], 60.0)
    spans = [(round(c.start, 2), round(c.end, 2)) for c in ch]
    assert spans[0][0] == 0.0 and all(c.end - c.start <= 12.5 for c in ch[1:-1])
    assert all(a.end <= b.start + 1e-9 for a, b in zip(ch, ch[1:]))


def test_holes_pass_recovers_missing_speech(monkeypatch):
    # VAD thấy thoại 10-30s nhưng lượt đầu Whisper chỉ ra chữ ở 10-12s
    monkeypatch.setattr(pipeline, "speech_regions", lambda a: [(10.0, 30.0)])

    class FirstPassSkips(FakeBackend):
        def transcribe(self, audio, opts):
            self.calls.append(opts.language)
            dur = len(audio) / 16000
            txt = "今日は。" if dur > 15 else f"続き{len(self.calls)}です。"
            end = 2.0 if dur > 15 else dur - 0.2
            return ChunkResult("ja", [Segment(0.1, end, txt, [Word(0.1, end, txt)])])

    msgs = []
    t = pipeline.transcribe_video("x.mp4", FirstPassSkips(), TranscribeOptions(language="ja"), progress=None,
                                  audio=np.zeros(16000 * 40, dtype=np.float32), status=msgs.append)
    assert any("Nghe lại" in m for m in msgs)
    assert max(s.end for s in t.segments) > 25


def test_alignment_heads_table():
    import base64, gzip
    from vsub.backends import ALIGNMENT_HEADS, alignment_key
    dims = {"large-v3-turbo": (4, 20), "large-v3": (32, 20), "medium": (24, 16), "small": (12, 12)}
    for k, (L, h) in dims.items():
        assert np.frombuffer(gzip.decompress(base64.b85decode(ALIGNMENT_HEADS[k])), dtype=bool).size == L * h
    assert alignment_key("large-v3-turbo") == "large-v3-turbo"
    assert alignment_key("mlx-community/whisper-large-v3-turbo") == "large-v3-turbo"
    assert alignment_key("mlx-community/whisper-large-v3-mlx") == "large-v3"
    assert alignment_key("mlx-community/whisper-medium-mlx") == "medium"
