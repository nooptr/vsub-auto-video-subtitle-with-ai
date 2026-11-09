"""Thư mục lưu kết quả (--out-dir / "Thư mục lưu" trong giao diện)."""
import os

from vsub import cli, dub
from vsub.paths import output_stem


def test_output_stem_next_to_video_by_default(tmp_path):
    assert output_stem(str(tmp_path / "phim.mp4")) == str(tmp_path / "phim")


def test_output_stem_in_out_dir_creates_folder(tmp_path):
    out = tmp_path / "ket qua" / "con"
    assert output_stem("/videos/Tập 1.mkv", str(out)) == str(out / "Tập 1")
    assert out.is_dir()


def test_output_stem_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert output_stem("/v/a.mp4", "~/PhuDe") == str(tmp_path / "PhuDe" / "a")


def test_dub_paths_follow_out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dub, "_probe_has_video", lambda _v: True)
    out = str(tmp_path / "out")
    assert dub.output_path("/v/phim.mp4", out) == os.path.join(out, "phim.thuyetminh.mp4")
    assert dub.output_path("/v/phim.mp4") == "/v/phim.thuyetminh.mp4"
    assert dub.reference_path("/v/phim.mp4", out) == os.path.join(out, "phim.giong-mau.wav")


def test_cli_parses_out_dir_for_every_command():
    p = cli.build_parser()
    for argv in (["run", "a.mp4"], ["translate", "a.srt", "--to", "vi"], ["embed", "a.mp4", "a.srt"], ["dub", "a.mp4"]):
        assert p.parse_args([*argv, "-O", "/tmp/x"]).out_dir == "/tmp/x"
        assert p.parse_args(argv).out_dir is None


def test_cli_dub_finds_vi_srt_in_out_dir_then_next_to_video(tmp_path):
    video = tmp_path / "phim.mp4"
    out = tmp_path / "out"
    out.mkdir()
    assert cli._vi_subs(str(video), str(out)) == str(out / "phim.vi.srt")  # chưa có đâu: chỗ mới
    (tmp_path / "phim.vi.srt").write_text("x")
    assert cli._vi_subs(str(video), str(out)) == str(tmp_path / "phim.vi.srt")
    (out / "phim.vi.srt").write_text("x")
    assert cli._vi_subs(str(video), str(out)) == str(out / "phim.vi.srt")


def test_gui_paths_follow_out_dir(tmp_path):
    from vsub.gui import srt_path, vi_srt_path

    video = str(tmp_path / "phim.mp4")
    out = str(tmp_path / "out")
    assert srt_path(video) == str(tmp_path / "phim.srt")
    assert srt_path(video, out) == os.path.join(out, "phim.srt")
    (tmp_path / "phim.vi.srt").write_text("x")
    assert vi_srt_path(video, out) == str(tmp_path / "phim.vi.srt")
