"""Đường dẫn và vài thao tác hệ thống khác nhau giữa macOS / Windows / Linux."""

from __future__ import annotations

import os
import sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")


def _local_appdata() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def data_dir() -> str:
    """Nơi app cài thêm đồ (venv, VieNeu, ffmpeg trên Windows, thông tin bản cài). VSUB_HOME để đổi."""
    if os.environ.get("VSUB_HOME"):
        return os.environ["VSUB_HOME"]
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/vsub")
    if IS_WIN:
        return os.path.join(_local_appdata(), "vsub")
    return os.path.expanduser("~/.local/share/vsub")


def cache_dir() -> str:
    if IS_MAC:
        return os.path.expanduser("~/Library/Caches/vsub")
    if IS_WIN:
        return os.path.join(_local_appdata(), "vsub", "Cache")
    return os.path.expanduser("~/.cache/vsub")


def log_path() -> str:
    if IS_MAC:
        return os.path.expanduser("~/Library/Logs/vsub.log")
    return os.path.join(cache_dir(), "vsub.log")


def venv_python(venv: str, gui: bool = False) -> str:
    if IS_WIN:
        return os.path.join(venv, "Scripts", "pythonw.exe" if gui else "python.exe")
    return os.path.join(venv, "bin", "python")


def extra_paths() -> list[str]:
    """Thư mục hay chứa ffmpeg / uv / claude mà app mở từ Finder / Start Menu không thấy trong PATH."""
    home = os.path.expanduser("~")
    if IS_WIN:
        return [os.path.join(data_dir(), "ffmpeg", "bin"), os.path.join(home, ".local", "bin"),
                os.path.join(_local_appdata(), "Microsoft", "WinGet", "Links")]
    return ["/opt/homebrew/bin", "/usr/local/bin", os.path.join(home, ".local", "bin")]


def fix_path() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join([p for p in extra_paths() if p not in parts] + parts)


def pid_alive(pid: int) -> bool:
    """Tiến trình còn chạy không. Trên Windows KHÔNG dùng os.kill(pid, 0): nó tắt luôn tiến trình đó."""
    if pid <= 0:
        return False
    if IS_WIN:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def utf8_stdio() -> None:
    """Windows: console / pipe mặc định cp1252 -> in tiếng Việt, ✔ bị lỗi. Ép UTF-8."""
    if not IS_WIN:
        return
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def reveal(path: str) -> None:
    """Mở thư mục chứa file và chọn file đó."""
    import subprocess

    if IS_MAC:
        subprocess.run(["open", "-R", path])
    elif IS_WIN:
        subprocess.run(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)])


def output_stem(path: str, out_dir: str | None = None) -> str:
    """Tên file xuất ra (chưa có đuôi) cho `path`: cạnh file gốc, hoặc trong out_dir nếu có (tự tạo thư mục)."""
    stem = os.path.splitext(path)[0]
    if not out_dir:
        return stem
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, os.path.basename(stem))
