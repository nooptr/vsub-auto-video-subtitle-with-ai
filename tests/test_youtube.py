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


@pytest.mark.parametrize("raw, expect", [
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser", True),
    ("ERROR: [youtube] x: Sign in to confirm your age.", True),
    ("ERROR: [youtube] x: This video requires login (LOGIN_REQUIRED)", True),
    ("ERROR: [youtube] x: Video unavailable", False),
    ("ERROR: [youtube] x: Private video", False),
])
def test_needs_login(raw, expect):
    assert youtube.needs_login(raw) is expect


def test_bot_error_suggests_browser_cookies():
    msg = youtube.explain_error("ERROR: Sign in to confirm you’re not a bot")
    assert "cookie" in msg.lower() and "--cookies-from-browser" in msg


class _FakeYDL:
    """Giả yt_dlp.YoutubeDL: lần không có cookie bị chặn, có cookie thì tải được."""
    calls: list = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        _FakeYDL.calls.append(self.opts.get("cookiesfrombrowser"))
        if not self.opts.get("cookiesfrombrowser"):
            import yt_dlp
            raise yt_dlp.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm you’re not a bot")
        return {"title": "Phim", "height": 1080}

    def process_ie_result(self, info, download=True):
        out = self.opts["outtmpl"]["default"].replace("%(title).150B.%(ext)s", "Phim.mp4")
        open(out, "wb").close()
        return {**info, "requested_downloads": [{"filepath": out}]}


def test_download_retries_with_browser_cookies_when_blocked(tmp_path, monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(youtube.shutil, "which", lambda name: "/usr/bin/" + name)
    _FakeYDL.calls = []
    said = []
    path = youtube.download("https://youtu.be/aqz-KE-bpKQ", str(tmp_path), status=said.append,
                            cookies_from="chrome")
    assert path == str(tmp_path / "Phim.mp4")
    assert _FakeYDL.calls == [None, ("chrome",)]
    assert any("Chrome" in m for m in said)


def test_download_without_cookies_explains_how_to_fix(tmp_path, monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(youtube.shutil, "which", lambda name: "/usr/bin/" + name)
    _FakeYDL.calls = []
    with pytest.raises(youtube.DownloadError, match="cookie"):
        youtube.download("https://youtu.be/aqz-KE-bpKQ", str(tmp_path))
    assert _FakeYDL.calls == [None]
