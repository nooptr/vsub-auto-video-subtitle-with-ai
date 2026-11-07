import io
import json
import os
import zipfile

import pytest

from vsub import update


def test_parse_and_compare_versions():
    assert update.parse_version("v0.10.2") == (0, 10, 2)
    assert update.parse_version("1.2.3-rc1") == (1, 2, 3)
    assert update.is_newer("0.10.0", "0.9.9")
    assert update.is_newer("v1.0.0", "0.99")
    assert not update.is_newer("0.1.0", "0.1.0")
    assert not update.is_newer("0.1.0", "0.2.0")


def test_fetch_latest_parses_github_api(monkeypatch):
    payload = {"tag_name": "v1.2.0", "html_url": "https://github.com/x/y/releases/tag/v1.2.0",
               "body": "- mới", "published_at": "2026-11-07T10:00:00Z",
               "assets": [{"name": update.MAC_ASSET, "browser_download_url": "https://dl/mac.zip", "size": 123},
                          {"name": update.WIN_ASSET, "browser_download_url": "https://dl/win.zip", "size": 456}]}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(update, "_get", lambda url, timeout: Resp(json.dumps(payload).encode()))
    rel = update.fetch_latest()
    assert rel.version == "1.2.0" and rel.tag == "v1.2.0" and rel.published == "2026-11-07"
    assert update.asset_for(rel, "mac-app") == ("https://dl/mac.zip", 123)
    assert update.asset_for(rel, "windows") == ("https://dl/win.zip", 456)
    assert update.asset_for(rel, "git") is None


def test_fetch_latest_error_is_friendly(monkeypatch):
    def boom(url, timeout):
        raise OSError("no network")

    monkeypatch.setattr(update, "_get", boom)
    with pytest.raises(update.UpdateError, match="Không kiểm tra được"):
        update.fetch_latest()


def _install(tmp_path, monkeypatch, kind, path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "install.json").write_text(json.dumps({"kind": kind, "path": str(path), "version": "0.1.0"}),
                                       encoding="utf-8-sig")
    monkeypatch.setenv("VSUB_HOME", str(home))
    return home


def test_update_mode_from_install_json(tmp_path, monkeypatch):
    app = tmp_path / "Vsub.app"
    app.mkdir()
    _install(tmp_path, monkeypatch, "mac-app", app)
    monkeypatch.setattr(update, "IS_MAC", True)
    monkeypatch.setattr(update, "IS_WIN", False)
    assert update.update_mode() == ("mac-app", str(app))
    # bản cài đã bị xoá -> không dùng nữa
    monkeypatch.setattr(update, "PROJECT_DIR", str(tmp_path / "khong-co"))
    app.rmdir()
    assert update.update_mode() == ("manual", "")


def test_windows_update_replaces_app_folder(tmp_path, monkeypatch):
    inst = tmp_path / "vsub"
    (inst / "app" / "src").mkdir(parents=True)
    (inst / "app" / "src" / "cu.py").write_text("old")
    (inst / "Vsub.cmd").write_text("old")
    home = _install(tmp_path, monkeypatch, "windows", inst)
    monkeypatch.setattr(update, "IS_MAC", False)
    monkeypatch.setattr(update, "IS_WIN", True)

    z = tmp_path / "vsub-windows-amd64.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("vsub/Vsub.cmd", "new")
        f.writestr("vsub/app/VERSION", "9.9.9")
        f.writestr("vsub/app/src/moi.py", "new")
    rel = update.Release("9.9.9", "v9.9.9", "u", assets={update.WIN_ASSET: (z.as_uri(), z.stat().st_size)})
    assert update.apply_update(rel) == "windows"
    assert (inst / "Vsub.cmd").read_text() == "new"
    assert (inst / "app" / "VERSION").read_text() == "9.9.9"
    assert (inst / "app" / "src" / "moi.py").exists()
    assert not (inst / "app" / "src" / "cu.py").exists()          # mã nguồn cũ không sót lại
    assert (home / "backup" / "app" / "src" / "cu.py").exists()   # nhưng vẫn giữ bản sao lưu


def test_update_without_asset_or_manual_mode_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("VSUB_HOME", str(tmp_path / "none"))
    monkeypatch.setattr(update, "PROJECT_DIR", str(tmp_path))
    rel = update.Release("9.9.9", "v9.9.9", "u")
    with pytest.raises(update.UpdateError):
        update.apply_update(rel)


def test_cached_check():
    assert update.cached_check({}) == (True, None)
    import time

    should, latest = update.cached_check({"update_checked_at": time.time(), "update_latest": "1.0.0"})
    assert not should and latest == "1.0.0"
