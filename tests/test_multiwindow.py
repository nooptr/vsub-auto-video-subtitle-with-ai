import json
import multiprocessing as mp
import os

from vsub.series import Profile


def _learn(path, i):
    p = Profile.load(path)
    p.bucket("vi")["glossary"][f"名{i}"] = f"Ten{i}"
    p.save()


def test_two_windows_keep_both_learnings(tmp_path):
    path = str(tmp_path / "ho-so.json")
    Profile(path).save()
    a, b = Profile.load(path), Profile.load(path)   # hai cửa sổ cùng mở hồ sơ
    a.bucket("vi")["glossary"]["田中"] = "Tanaka"
    a.source_lang = "ja"
    a.save()
    b.bucket("vi")["glossary"]["佐藤"] = "Sato"
    b.save()                                         # trước đây: đè mất "田中" của cửa sổ a
    g = Profile.load(path).learned["vi"]["glossary"]
    assert g == {"田中": "Tanaka", "佐藤": "Sato"}
    assert Profile.load(path).source_lang == "ja"


def test_reload_pulls_other_window(tmp_path):
    path = str(tmp_path / "ho-so.json")
    Profile(path).save()
    a, b = Profile.load(path), Profile.load(path)
    a.bucket("vi")["glossary"]["田中"] = "Tanaka"
    a.save()
    b.reload()
    assert b.bucket("vi")["glossary"]["田中"] == "Tanaka"


def test_concurrent_processes(tmp_path):
    path = str(tmp_path / "ho-so.json")
    Profile(path).save()
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_learn, args=(path, i)) for i in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    g = json.load(open(path))["learned"]["vi"]["glossary"]
    assert len(g) == 6


def test_claim_video(tmp_path, monkeypatch):
    from vsub import gui
    monkeypatch.setattr(gui, "_cache_dir", lambda: str(tmp_path))
    v = str(tmp_path / "ep1.mp4")
    lock = gui.claim_video(v)
    assert lock and os.path.exists(lock)
    # cửa sổ khác (pid khác còn sống) đang giữ -> không lấy được
    open(lock, "w").write(str(os.getppid()))
    assert gui.claim_video(v) is None
    # khoá bỏ lại của tiến trình đã chết -> lấy lại được
    open(lock, "w").write("999999")
    lock2 = gui.claim_video(v)
    assert lock2 == lock
    gui.release_video(lock2)
    assert not os.path.exists(lock)
