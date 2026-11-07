from vsub.filters import clean_segments, is_hallucination
from vsub.formats import parse_srt, to_srt, to_vtt
from vsub.models import Cue, Segment
from vsub.vad import group_regions


def test_srt_roundtrip():
    cues = [Cue(1.5, 3.25, ["Xin chào", "các bạn"]), Cue(3661.0, 3662.999, ["Hết"])]
    s = to_srt(cues)
    assert "00:00:01,500 --> 00:00:03,250" in s
    assert "01:01:01,000 --> 01:01:02,999" in s
    back = parse_srt(s)
    assert [c.lines for c in back] == [c.lines for c in cues]
    assert abs(back[1].end - 3662.999) < 1e-6


def test_vtt_header():
    v = to_vtt([Cue(0, 1, ["a"])])
    assert v.startswith("WEBVTT") and "00:00:00.000 --> 00:00:01.000" in v


def test_hallucinations_dropped():
    assert is_hallucination(Segment(0, 1, " Hãy subscribe cho kênh Ghiền Mì Gõ để không bỏ lỡ"))
    assert is_hallucination(Segment(0, 1, " ..."))
    assert is_hallucination(Segment(0, 1, " ha ha", compression_ratio=3.0))
    # thoại thật "Cảm ơn các bạn đã xem" khi model tự tin thì giữ lại
    assert not is_hallucination(Segment(0, 1, " Cảm ơn các bạn đã xem", avg_logprob=-0.2))
    assert is_hallucination(Segment(0, 1, " Cảm ơn các bạn đã xem", avg_logprob=-0.9))


def test_repeat_collapse():
    segs = [Segment(i, i + 1, " Đi thôi.") for i in range(6)]
    assert len(clean_segments(segs)) == 2


def test_same_line_far_apart_is_kept():
    segs = [Segment(i * 60, i * 60 + 1, " Đi thôi.") for i in range(4)]
    assert len(clean_segments(segs)) == 4


def test_group_regions():
    regions = [(0.0, 2.0), (2.5, 5.0), (10.0, 12.0), (12.2, 40.0)]
    chunks = group_regions(regions, max_chunk_s=28, max_gap_s=1.5, total_s=60)
    assert [(round(c.start, 2), round(c.end, 2)) for c in chunks] == [
        (0.0, 5.15), (9.85, 12.15), (12.15, 40.15)]
    for a, b in zip(chunks, chunks[1:]):
        assert a.end <= b.start


def test_fill_loud_gaps():
    import numpy as np
    from vsub.vad import fill_loud_gaps
    sr = 16000
    audio = np.zeros(sr * 30, dtype=np.float32)
    audio[sr * 10: sr * 15] = 0.1 * np.sin(np.arange(sr * 5) / 5)  # khoảng 10-15s: to nhưng VAD bỏ
    regions = [(2.0, 9.0), (16.0, 20.0)]
    out, added = fill_loud_gaps(regions, audio, 30.0)
    assert added == [(9.0, 16.0)]                      # khoảng to được bù
    assert (0.0, 2.0) not in out and (20.0, 30.0) not in out  # khoảng im lặng thì không


def test_strict_filter_in_uncertain_zone():
    zone = [(10.0, 20.0)]
    weak = Segment(11, 13, " có thể là bịa", avg_logprob=-0.9)
    sure = Segment(14, 16, " câu thật", avg_logprob=-0.3, no_speech_prob=0.1)
    outside = Segment(30, 32, " ngoài vùng", avg_logprob=-0.9)
    kept = clean_segments([weak, sure, outside], uncertain=zone)
    assert [s.text for s in kept] == [" câu thật", " ngoài vùng"]



def test_repair_prompt_echo_keeps_real_speech():
    from vsub.filters import repair
    from vsub.models import Word
    words = [Word(0, 0.2, "字幕"), Word(0.2, 0.3, "："), Word(0.3, 1.0, "あきら"), Word(1.0, 1.5, "には"), Word(1.5, 2.0, "楽しく１")]
    seg = Segment(0, 2, "字幕：あきらには楽しく１でも", words)
    fixed = repair(seg)
    assert fixed.text == "あきらには楽しく。でも"
    assert fixed.start == 0.3 and fixed.words[0].text == "あきら"
    kept = clean_segments([seg])
    assert kept and "字幕" not in kept[0].text
