"""Tải video YouTube về .mp4 (H.264 + AAC, tối đa 1080p) bằng yt-dlp, rồi làm phụ đề như file thường.

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

_HOSTS = r"(?:(?:www|m|music)\.)?youtube\.com|youtu\.be"
_URL_RE = re.compile(
    rf"^(?:https?://)?(?:{_HOSTS})/"
    r"(?:watch\?(?:.*&)?v=|shorts/|live/|embed/|(?=[\w-]{11}(?:[?&#]|$)))"
    r"[\w-]{11}(?:[?&#].*)?$",
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


def default_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")


def update_hint() -> str:
    return f'uv pip install -U yt-dlp --python "{sys.executable}"'


def needs_login(msg: str) -> bool:
    """YouTube đòi đăng nhập (xác minh bot, giới hạn tuổi…): thử lại bằng cookie trình duyệt có thể qua."""
    low = msg.lower()
    return "not a bot" in low or "sign in to confirm" in low or "login_required" in low or "requires login" in low


COOKIE_HINT = ("Cách khắc phục: chọn trình duyệt bạn đã đăng nhập YouTube ở ô “Cookie” cạnh nút Tải video "
               "(dòng lệnh: --cookies-from-browser chrome, hoặc đặt biến VSUB_YT_COOKIES=chrome). "
               "App chỉ dùng cookie khi YouTube chặn.")


def explain_error(msg: str, tried_cookies: str | None = None) -> str:
    """Lỗi của yt-dlp -> câu tiếng Việt dễ hiểu."""
    low = msg.lower()
    if "private video" in low:
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
        why = "Link không phải link video YouTube."
    else:
        detail = re.sub(r"^ERROR:\s*", "", msg.strip()).splitlines()[0][:300] if msg.strip() else "lỗi không rõ"
        why = f"Không tải được: {detail}"
    if needs_login(msg):
        if tried_cookies:
            return (f"{why}\nĐã thử cookie của {browser_name(tried_cookies)} nhưng vẫn bị chặn: hãy mở YouTube "
                    f"trong {browser_name(tried_cookies)}, kiểm tra đã đăng nhập, xem thử một video rồi tải lại.")
        return f"{why}\n{COOKIE_HINT}"
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
        "format": FORMAT,
        "merge_output_format": "mp4",
        "outtmpl": {"default": os.path.join(out_dir, "%(title).150B.%(ext)s")},
        "windowsfilenames": True,
        "noplaylist": True,
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
    """Tải video về out_dir (mặc định ~/Downloads). Trả về đường dẫn file .mp4.
    Đã có file cùng tên thì dùng lại, không tải lại.
    cookies_from: trình duyệt (chrome, firefox…) để lấy cookie YouTube — chỉ dùng khi YouTube đòi
    đăng nhập / xác minh bot, lần đầu luôn tải không cookie."""
    import yt_dlp

    url = url.strip()
    if not is_youtube_url(url):
        raise DownloadError("Link không phải link video YouTube.")
    if not shutil.which("ffmpeg"):
        raise DownloadError("Cần FFmpeg để ghép hình và tiếng. Mở tab “Thư viện” để cài.")
    out_dir = out_dir or default_dir()
    os.makedirs(out_dir, exist_ok=True)
    say = status or (lambda _m: None)
    say("Đọc thông tin video YouTube…")

    def attempt(cookies: str | None) -> dict:
        opts = ydl_options(out_dir, status, progress, cancel)
        if cookies:
            opts["cookiesfrombrowser"] = (cookies,)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if cancel and cancel.is_set():
                raise Cancelled()
            if info.get("is_live"):
                raise DownloadError("Video đang phát trực tiếp — đợi phát xong rồi tải.")
            h = info.get("height")
            say(f"“{info.get('title')}” — {h}p" if h else f"“{info.get('title')}”")
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
            raise DownloadError(explain_error(str(e))) from None
        name = browser_name(cookies_from)
        say(f"YouTube đòi xác minh — thử lại bằng cookie YouTube của {name}"
            + (" (macOS có thể hỏi quyền Keychain, chọn Cho phép)…" if cookies_from in ("chrome", "brave", "edge")
               else "…"))
        try:
            info = attempt(cookies_from)
        except yt_dlp.utils.DownloadError as e2:
            if cancelled(e2):
                raise Cancelled() from None
            raise DownloadError(explain_error(str(e2), tried_cookies=cookies_from)) from None
        except (Cancelled, DownloadError):
            raise
        except Exception as e2:  # noqa: BLE001 — không đọc được cookie (chưa cài, từ chối Keychain…)
            raise DownloadError(f"Không đọc được cookie của {name}: {e2}\n"
                                f"Kiểm tra {name} đã cài và đã đăng nhập YouTube, hoặc chọn trình duyệt khác.") from None
    path = ((info.get("requested_downloads") or [{}])[0].get("filepath")
            or os.path.splitext(yt_dlp.YoutubeDL(ydl_options(out_dir)).prepare_filename(info))[0] + ".mp4")
    if not os.path.isfile(path):
        raise DownloadError(f"Tải xong nhưng không thấy file {path}")
    return path
