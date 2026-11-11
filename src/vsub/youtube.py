"""Tải video YouTube / X (Twitter) về .mp4 (H.264 + AAC, tối đa 1080p) bằng yt-dlp, rồi làm phụ đề như file thường.

H.264 mở được ở mọi nơi (QuickTime, TV, điện thoại). YouTube chỉ có H.264 tới 1080p, bản cao hơn là
VP9/AV1, nên giới hạn 1080p. Video không có H.264 thì lấy bản tốt nhất <= 1080p, vẫn đóng gói .mp4.
JavaScript (giải mã link của YouTube) chạy bằng deno cài kèm qua pip (yt-dlp[deno]).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from typing import Callable

# hình H.264 + tiếng AAC -> bản H.264 có sẵn tiếng -> hình bất kỳ + tiếng -> bản bất kỳ; luôn <= 1080p
FORMAT = "/".join([
    "bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]",
    "b[vcodec^=avc1][height<=1080][acodec^=mp4a]",
    "bv*[height<=1080]+ba",
    "b[height<=1080]",
])
# X: các bản mp4 "http-*" đã có sẵn tiếng (H.264 + AAC) nhưng không ghi codec -> lấy nguyên một file,
# không ghép thêm tiếng (sẽ thành 2 rãnh tiếng). Chỉ bản HLS tách hình / tiếng mới cần ghép.
FORMAT_X = "/".join([
    "b[height<=1080][ext=mp4]",
    "b[height<=1080]",
    "bv*[height<=1080]+ba",
    "b",
])

_HOSTS = r"(?:(?:www|m|music)\.)?youtube\.com|youtu\.be"
_URL_RE = re.compile(
    rf"^(?:https?://)?(?:{_HOSTS})/"
    r"(?:watch\?(?:.*&)?v=|shorts/|live/|embed/|(?=[\w-]{11}(?:[?&#]|$)))"
    r"[\w-]{11}(?:[?&#].*)?$",
    re.I,
)

_X_RE = re.compile(
    r"^(?:https?://)?(?:(?:www|mobile)\.)?(?:x|twitter)\.com/"
    r"(?:\w{1,15}|i|i/web)/status/\d+(?:/(?:video|photo)/\d+)?/?(?:[?#].*)?$",
    re.I,
)

ProgressFn = Callable[[int, int, "float | None", "float | None", str], None]

# Trình duyệt để lấy cookie YouTube khi YouTube đòi đăng nhập / xác minh "không phải bot"
BROWSERS = [
    ("Không dùng", None),
    ("Chrome", "chrome"),
    ("Firefox", "firefox"),
    ("Brave", "brave"),
    ("Safari", "safari"),
    ("Edge", "edge"),
]


def browser_name(key: str | None) -> str:
    return next((n for n, k in BROWSERS if k == key), key or "")


class Cancelled(Exception):
    pass


class DownloadError(RuntimeError):
    pass


def is_youtube_url(text: str) -> bool:
    """Link tới MỘT video YouTube (watch, youtu.be, shorts, live, embed). Kênh / playlist không tính."""
    return bool(_URL_RE.match((text or "").strip()))


def is_twitter_url(text: str) -> bool:
    """Link tới MỘT bài đăng trên X / Twitter (x.com/…/status/…, twitter.com/…/status/…)."""
    return bool(_X_RE.match((text or "").strip()))


def is_video_url(text: str) -> bool:
    """Link tải được: video YouTube hoặc bài đăng X (Twitter)."""
    return is_youtube_url(text) or is_twitter_url(text)


def site_name(url: str) -> str:
    return "X" if is_twitter_url(url) else "YouTube"


def default_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")


def update_hint() -> str:
    return f'uv pip install -U yt-dlp --python "{sys.executable}"'


def needs_login(msg: str) -> bool:
    """Trang đòi đăng nhập (YouTube xác minh bot / giới hạn tuổi, X nội dung nhạy cảm / tài khoản khoá…):
    thử lại bằng cookie trình duyệt có thể qua."""
    low = msg.lower()
    return any(k in low for k in ("not a bot", "sign in to confirm", "login_required", "requires login",
                                  "requires authentication", "protected tweet"))


def cookie_hint(site: str = "YouTube") -> str:
    return (f"Cách khắc phục: chọn trình duyệt bạn đã đăng nhập {site} ở ô “Cookie” cạnh nút Tải video "
            "(dòng lệnh: --cookies-from-browser chrome, hoặc đặt biến VSUB_YT_COOKIES=chrome). "
            f"App chỉ dùng cookie khi {site} chặn.")


COOKIE_HINT = cookie_hint()


def explain_error(msg: str, tried_cookies: str | None = None, site: str = "YouTube") -> str:
    """Lỗi của yt-dlp -> câu tiếng Việt dễ hiểu."""
    low = msg.lower()
    if "nsfw tweet" in low:
        why = "Bài đăng có nội dung nhạy cảm, X bắt đăng nhập mới cho xem."
    elif "protected tweet" in low:
        why = "Tài khoản X này để riêng tư, chỉ người theo dõi mới xem được."
    elif "no video could be found" in low or "is not a video" in low:
        why = "Bài đăng này không có video."
    elif "tweet is unavailable" in low or "tweet unavailable" in low:
        why = "Bài đăng không còn xem được (đã bị xoá, bị ẩn, hoặc link sai)."
    elif "private video" in low:
        why = "Video riêng tư, chỉ người được chia sẻ mới xem được."
    elif "confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        why = "Video giới hạn tuổi, YouTube bắt đăng nhập mới cho tải."
    elif "not a bot" in low:
        why = "YouTube nghi là máy tải tự động (thường do IP này tải nhiều) và đòi đăng nhập."
    elif "members-only" in low or "join this channel" in low:
        why = "Video chỉ dành cho hội viên của kênh."
    elif "live event will begin" in low or "premieres in" in low:
        why = "Buổi phát trực tiếp / công chiếu chưa bắt đầu."
    elif ("video unavailable" in low or "video is unavailable" in low or "has been removed" in low or "not available in your country" in low):
        why = "Video không còn xem được (đã bị xoá, bị chặn ở khu vực này, hoặc link sai)."
    elif "unsupported url" in low or "is not a valid url" in low or "incomplete youtube id" in low:
        why = f"Link không phải link video {site}."
    else:
        detail = re.sub(r"^ERROR:\s*", "", msg.strip()).splitlines()[0][:300] if msg.strip() else "lỗi không rõ"
        why = f"Không tải được: {detail}"
    if needs_login(msg):
        if tried_cookies:
            return (f"{why}\nĐã thử cookie của {browser_name(tried_cookies)} nhưng vẫn bị chặn: hãy mở {site} "
                    f"trong {browser_name(tried_cookies)}, kiểm tra đã đăng nhập, xem thử một video rồi tải lại.")
        return f"{why}\n{cookie_hint(site)}"
    return f"{why}\nNếu video vẫn xem được trên trình duyệt, thử cập nhật yt-dlp:\n  {update_hint()}"


def _js_runtimes() -> dict:
    try:
        import deno

        return {"deno": {"path": deno.find_deno_bin()}}
    except Exception:  # noqa: BLE001 — không có gói deno: dùng deno / node có sẵn trên máy nếu có
        return {name: {} for name in ("deno", "node") if shutil.which(name)} or {"deno": {}}


class _Logger:
    """yt-dlp mặc định in ra stdout -> chuyển cảnh báo sang status, bỏ phần còn lại (lỗi được raise)."""

    def __init__(self, status: Callable[[str], None] | None):
        self.status = status

    def debug(self, msg: str) -> None:
        pass

    info = debug

    def warning(self, msg: str) -> None:
        low = msg.lower()
        if self.status and "javascript runtime" not in low and "no title found in player" not in low:
            self.status("! " + msg.strip()[:300])

    def error(self, msg: str) -> None:
        pass


def ydl_options(
    out_dir: str,
    status: Callable[[str], None] | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    site: str = "YouTube",
) -> dict:
    def on_progress(d: dict) -> None:
        if cancel and cancel.is_set():
            raise Cancelled()
        if progress and d.get("status") == "downloading":
            vcodec = (d.get("info_dict") or {}).get("vcodec")
            part = "tiếng" if vcodec == "none" else "hình"
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            progress(int(d.get("downloaded_bytes") or 0), int(total), d.get("speed"), d.get("eta"), part)

    def on_post(d: dict) -> None:
        if status and d.get("status") == "started" and d.get("postprocessor") == "Merger":
            status("Ghép hình và tiếng thành .mp4…")

    opts = {
        "format": FORMAT_X if site == "X" else FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": {"default": os.path.join(out_dir, "%(title).150B.%(ext)s")},
        "windowsfilenames": True,
        "noplaylist": True,
        "playlist_items": "1",  # tweet có nhiều video -> chỉ video đầu (link …/video/N thì yt-dlp chọn video N)
        "quiet": True,
        "noprogress": True,
        "no_warnings": False,
        "logger": _Logger(status),
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_post],
        "js_runtimes": _js_runtimes(),
    }
    ff = shutil.which("ffmpeg")
    if ff:
        opts["ffmpeg_location"] = ff
    return opts


def download(
    url: str,
    out_dir: str | None = None,
    status: Callable[[str], None] | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    cookies_from: str | None = None,
) -> str:
    """Tải video YouTube / X về out_dir (mặc định ~/Downloads). Trả về đường dẫn file .mp4.
    Đã có file cùng tên thì dùng lại, không tải lại.
    cookies_from: trình duyệt (chrome, firefox…) để lấy cookie — chỉ dùng khi trang đòi
    đăng nhập / xác minh bot, lần đầu luôn tải không cookie."""
    import yt_dlp

    url = url.strip()
    if not is_video_url(url):
        raise DownloadError("Link không phải link video YouTube hay bài đăng X (Twitter).")
    site = site_name(url)
    if not shutil.which("ffmpeg"):
        raise DownloadError("Cần FFmpeg để ghép hình và tiếng. Mở tab “Thư viện” để cài.")
    out_dir = out_dir or default_dir()
    os.makedirs(out_dir, exist_ok=True)
    say = status or (lambda _m: None)
    say(f"Đọc thông tin video {site}…")

    def attempt(cookies: str | None) -> dict:
        opts = ydl_options(out_dir, status, progress, cancel, site=site)
        if cookies:
            opts["cookiesfrombrowser"] = (cookies,)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if cancel and cancel.is_set():
                raise Cancelled()
            if info.get("_type") == "playlist" and not info.get("entries"):
                raise DownloadError("Bài đăng này không có video.")
            if info.get("is_live"):
                raise DownloadError("Video đang phát trực tiếp — đợi phát xong rồi tải.")
            first = (info.get("entries") or [info])[0] or {}
            h = first.get("height")
            say(f"{site}: “{first.get('title')}” — {h}p" if h else f"{site}: “{first.get('title')}”")
            return ydl.process_ie_result(info, download=True)

    def cancelled(e: Exception) -> bool:
        ei = getattr(e, "exc_info", None)
        return bool(ei) and isinstance(ei[1], Cancelled)

    try:
        info = attempt(None)
    except yt_dlp.utils.DownloadError as e:
        if cancelled(e):
            raise Cancelled() from None
        if not (cookies_from and needs_login(str(e))):
            raise DownloadError(explain_error(str(e), site=site)) from None
        name = browser_name(cookies_from)
        say(f"{site} đòi xác minh — thử lại bằng cookie {site} của {name}"
            + (" (macOS có thể hỏi quyền Keychain, chọn Cho phép)…" if cookies_from in ("chrome", "brave", "edge")
               else "…"))
        try:
            info = attempt(cookies_from)
        except yt_dlp.utils.DownloadError as e2:
            if cancelled(e2):
                raise Cancelled() from None
            raise DownloadError(explain_error(str(e2), tried_cookies=cookies_from, site=site)) from None
        except (Cancelled, DownloadError):
            raise
        except Exception as e2:  # noqa: BLE001 — không đọc được cookie (chưa cài, từ chối Keychain…)
            raise DownloadError(f"Không đọc được cookie của {name}: {e2}\n"
                                f"Kiểm tra {name} đã cài và đã đăng nhập {site}, hoặc chọn trình duyệt khác.") from None
    if info.get("_type") == "playlist" or info.get("entries"):
        info = next((e for e in info.get("entries") or [] if e), None) or {}
    path = ((info.get("requested_downloads") or [{}])[0].get("filepath")
            or os.path.splitext(yt_dlp.YoutubeDL(ydl_options(out_dir, site=site)).prepare_filename(info))[0] + ".mp4")
    if not os.path.isfile(path):
        raise DownloadError(f"Tải xong nhưng không thấy file {path}")
    return path
