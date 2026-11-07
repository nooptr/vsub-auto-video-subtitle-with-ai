"""Bản mới: kiểm tra trên GitHub Releases, cập nhật tự động, hoặc hướng dẫn cập nhật thủ công.

Cách cập nhật tự động tuỳ cách app được cài:
- "mac-app": Vsub.app bản phát hành (launcher ghi install.json). Tải zip, thay app cũ (bản cũ để ở
  backup/), mở lại; lần mở đầu launcher tự cài thư viện của bản mới.
- "windows": thư mục giải nén từ zip (Vsub.cmd ghi install.json). Tải zip, chép đè, chạy lại Vsub.cmd.
- "git": chạy từ mã nguồn (git clone). git pull --ff-only rồi uv sync.
- "manual": không tự cập nhật được -> mở trang tải về.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from typing import Callable

from . import __version__
from .paths import IS_MAC, IS_WIN, data_dir

REPO = "viennv96/vsub-auto-video-subtitle-with-ai"
RELEASES_URL = f"https://github.com/{REPO}/releases"
LATEST_URL = f"{RELEASES_URL}/latest"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
SITE_URL = "https://viennv96.github.io/vsub-auto-video-subtitle-with-ai/"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAC_ASSET = "vsub-mac-universal.zip"
WIN_ASSET = "vsub-windows-amd64.zip"


class UpdateError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Release:
    version: str
    tag: str
    url: str
    notes: str = ""
    published: str = ""
    assets: dict[str, tuple[str, int]] = field(default_factory=dict)  # tên -> (url, cỡ byte)


def parse_version(v: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Phần không phải số (rc, beta…) bỏ qua."""
    nums = []
    for part in v.strip().lstrip("vV").split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        nums.append(int(m.group()))
    return tuple(nums) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"vsub/{__version__}", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — chỉ gọi github.com


def fetch_latest(timeout: float = 10) -> Release:
    try:
        with _get(API_LATEST, timeout) as r:
            d = json.load(r)
    except Exception as e:  # noqa: BLE001 — mạng, GitHub chưa có release…
        raise UpdateError(f"Không kiểm tra được bản mới ({e})") from e
    tag = str(d.get("tag_name") or "")
    if not tag:
        raise UpdateError("GitHub chưa có bản phát hành nào")
    assets = {a["name"]: (a["browser_download_url"], int(a.get("size") or 0))
              for a in d.get("assets") or [] if a.get("name") and a.get("browser_download_url")}
    return Release(tag.lstrip("vV"), tag, d.get("html_url") or LATEST_URL, d.get("body") or "",
                   (d.get("published_at") or "")[:10], assets)


def install_info() -> dict | None:
    try:
        with open(os.path.join(data_dir(), "install.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def update_mode() -> tuple[str, str]:
    """(cách cập nhật, đường dẫn bản cài)."""
    info = install_info() or {}
    path = str(info.get("path") or "")
    if info.get("kind") == "mac-app" and IS_MAC and os.path.isdir(path):
        return "mac-app", path
    if info.get("kind") == "windows" and IS_WIN and os.path.isdir(path):
        return "windows", path
    if os.path.isdir(os.path.join(PROJECT_DIR, ".git")):
        return "git", PROJECT_DIR
    return "manual", ""


def asset_for(release: Release, mode: str) -> tuple[str, int] | None:
    name = {"mac-app": MAC_ASSET, "windows": WIN_ASSET}.get(mode)
    return release.assets.get(name) if name else None


def describe_mode(mode: str) -> str:
    return {
        "mac-app": "tải bản mới, thay Vsub.app cũ rồi mở lại",
        "windows": "tải bản mới, chép đè thư mục cài rồi mở lại",
        "git": "git pull mã nguồn mới rồi cài lại thư viện (uv sync)",
        "manual": "mở trang tải về để bạn tự tải",
    }[mode]


# ------------------------------------------------------------------ cập nhật

def _download(url: str, dest: str, progress: Callable[[int, int], None] | None,
              cancel: threading.Event | None) -> None:
    with _get(url, 30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel and cancel.is_set():
                raise Cancelled()
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def _run(cmd: list[str], say: Callable[[str], None], cwd: str | None = None) -> None:
    say("$ " + " ".join(cmd))
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    for line in p.stdout:
        line = line.rstrip()
        if line:
            say("  " + line[-160:])
    if p.wait():
        raise UpdateError(f"Lệnh lỗi (mã {p.returncode}): {' '.join(cmd[:3])}…")


def apply_update(
    release: Release,
    status: Callable[[str], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> str:
    """Cài bản mới. Trả về cách cập nhật đã dùng (để biết mở lại app thế nào)."""
    say = status or (lambda _m: None)
    mode, path = update_mode()
    if mode == "manual":
        raise UpdateError("Bản cài này không tự cập nhật được — hãy tải bản mới ở trang phát hành")
    if mode == "git":
        from .deps import find_uv

        _run(["git", "-C", path, "pull", "--ff-only"], say)
        uv = find_uv()
        if not uv:
            raise UpdateError("Đã lấy mã nguồn mới nhưng không thấy uv để cài thư viện — chạy: bash setup.command")
        _run([uv, "sync", "--project", path], say)
        return mode

    asset = asset_for(release, mode)
    if not asset:
        raise UpdateError(f"Bản {release.tag} chưa có file cho máy này — hãy tải thủ công")
    url, size = asset
    tmp = tempfile.mkdtemp(prefix="vsub-update-")
    try:
        zpath = os.path.join(tmp, os.path.basename(url))
        say(f"Tải {os.path.basename(url)}" + (f" ({size / 1e6:.1f} MB)" if size else "") + "…")
        _download(url, zpath, progress, cancel)
        out = os.path.join(tmp, "x")
        say("Giải nén…")
        if IS_MAC:  # ditto giữ quyền chạy, symlink, thuộc tính của bundle
            _run(["ditto", "-x", "-k", zpath, out], say)
        else:
            with zipfile.ZipFile(zpath) as z:
                z.extractall(out)
        if cancel and cancel.is_set():
            raise Cancelled()
        backup = os.path.join(data_dir(), "backup")
        os.makedirs(backup, exist_ok=True)
        if mode == "mac-app":
            new = os.path.join(out, "Vsub.app")
            if not os.path.isfile(os.path.join(new, "Contents", "Info.plist")):
                raise UpdateError("File tải về không có Vsub.app")
            old_copy = os.path.join(backup, "Vsub.app")
            shutil.rmtree(old_copy, ignore_errors=True)
            say(f"Thay {path} (bản cũ để ở {old_copy})…")
            shutil.move(path, old_copy)
            try:
                shutil.move(new, path)
            except Exception:
                shutil.move(old_copy, path)  # trả lại bản cũ
                raise
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", path], capture_output=True)
        else:  # windows: zip có một thư mục gốc "vsub/"
            entries = [os.path.join(out, n) for n in os.listdir(out)]
            src = entries[0] if len(entries) == 1 and os.path.isdir(entries[0]) else out
            if not os.path.isfile(os.path.join(src, "Vsub.cmd")):
                raise UpdateError("File tải về không có Vsub.cmd")
            say(f"Chép bản mới vào {path}…")
            app_dir = os.path.join(path, "app")
            if os.path.isdir(app_dir):  # bỏ mã nguồn cũ để không sót file thừa
                shutil.rmtree(os.path.join(backup, "app"), ignore_errors=True)
                shutil.move(app_dir, os.path.join(backup, "app"))
            shutil.copytree(src, path, dirs_exist_ok=True)
        return mode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def relaunch(mode: str) -> None:
    """Mở lại app sau khi cập nhật (cửa sổ hiện tại tự đóng sau đó)."""
    _, path = update_mode()
    if mode == "mac-app" and path:
        subprocess.Popen(["open", "-n", path])
    elif mode == "windows" and path:
        subprocess.Popen(["cmd", "/c", "start", "", os.path.join(path, "Vsub.cmd")],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        app = os.environ.get("VSUB_APP")
        if IS_MAC and app and os.path.isdir(app):
            subprocess.Popen(["open", "-n", "-a", app])
        else:
            from .gui import open_new_window

            open_new_window()


# ------------------------------------------------------------------ nhớ lần kiểm tra

def cached_check(settings: dict, max_age_h: float = 6.0) -> tuple[bool, str | None]:
    """(có nên hỏi GitHub không, bản mới nhất đã biết)."""
    last = float(settings.get("update_checked_at") or 0)
    return time.time() - last > max_age_h * 3600, settings.get("update_latest")
