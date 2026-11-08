import threading

import pytest

from vsub import youtube


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "https://youtube.com/watch?v=aqz-KE-bpKQ&t=30s",
    "http://m.youtube.com/watch?feature=share&v=aqz-KE-bpKQ",
    "https://music.youtube.com/watch?v=aqz-KE-bpKQ&list=RDxyz",
    "https://youtu.be/aqz-KE-bpKQ",
    "https://youtu.be/aqz-KE-bpKQ?si=abc",
    "https://www.youtube.com/shorts/aqz-KE-bpKQ",
    "https://www.youtube.com/live/aqz-KE-bpKQ",
    "https://www.youtube.com/embed/aqz-KE-bpKQ",
    "  www.youtube.com/watch?v=aqz-KE-bpKQ  ",
    "youtu.be/aqz-KE-bpKQ",
])
def test_recognizes_youtube_video_links(url):
    assert youtube.is_youtube_url(url)


@pytest.mark.parametrize("text", [
    "", "phim.mp4", "/Users/a/Downloads/youtube.com.mp4", "https://vimeo.com/123",
    "https://www.youtube.com/", "https://www.youtube.com/@kenh", "https://www.youtube.com/playlist?list=PL1",
    "https://notyoutube.com/watch?v=aqz-KE-bpKQ", "https://youtube.com.evil.io/watch?v=aqz-KE-bpKQ",
])
def test_rejects_other_text(text):
    assert not youtube.is_youtube_url(text)


def test_options_prefer_h264_up_to_1080p_and_mp4(tmp_path):
    opts = youtube.ydl_options(str(tmp_path))
    first = opts["format"].split("/")[0]
    assert "vcodec^=avc1" in first and "height<=1080" in first and "acodec^=mp4a" in first
    assert all("height<=1080" in f for f in opts["format"].split("/"))  # không bao giờ quá 1080p
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert opts["outtmpl"]["default"].startswith(str(tmp_path))
    assert "%(title)" in opts["outtmpl"]["default"]


def test_progress_hook_reports_and_cancels(tmp_path):
    seen = []
    cancel = threading.Event()
    opts = youtube.ydl_options(str(tmp_path), progress=lambda *a: seen.append(a), cancel=cancel)
    hook = opts["progress_hooks"][0]
    hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200, "speed": 10.0, "eta": 15,
          "info_dict": {"vcodec": "avc1.64002A"}})
    hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes_estimate": 20, "speed": None, "eta": None,
          "info_dict": {"vcodec": "none"}})
    assert seen == [(50, 200, 10.0, 15, "hình"), (5, 20, None, None, "tiếng")]
    cancel.set()
    with pytest.raises(youtube.Cancelled):
        hook({"status": "downloading", "downloaded_bytes": 6, "info_dict": {}})


@pytest.mark.parametrize("raw, expect", [
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "riêng tư"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate", "giới hạn tuổi"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot", "nghi là máy"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed", "không còn xem được"),
    ("ERROR: [youtube] xxxxxxxxxxx: This video is unavailable", "không còn xem được"),
    ("ERROR: [youtube] x: Join this channel to get access to members-only content", "hội viên"),
    ("ERROR: something new and strange", "yt-dlp"),
])
def test_explains_errors_in_vietnamese(raw, expect):
    assert expect in youtube.explain_error(raw)
