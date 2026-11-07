import shutil
import subprocess

import numpy as np
import pytest

from vsub.audio import SAMPLE_RATE, load_audio

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="cần ffmpeg")


def test_audio_gap_is_filled_with_silence(tmp_path):
    """File mất gói audio giữa chừng: phần sau chỗ hụt phải giữ đúng giờ của video,
    không bị ffmpeg nối liền vào (lỗi làm phụ đề ep.3 sớm dần tới 50 giây)."""
    f = tmp_path / "gap.mp4"
    # 3 giây tiếng bíp, sau giây thứ 1 bị hụt 2 giây -> file dài 5 giây
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000",
         "-af", "asetpts='if(gte(T,1),PTS+2/TB,PTS)'", "-c:a", "aac", str(f)],
        check=True,
    )
    a = load_audio(str(f))
    assert abs(len(a) / SAMPLE_RATE - 5.0) < 0.1

    def rms(s, e):
        return float(np.sqrt(np.mean(a[int(s * SAMPLE_RATE):int(e * SAMPLE_RATE)] ** 2)))

    assert rms(0.2, 0.8) > 0.05      # tiếng trước chỗ hụt
    assert rms(1.2, 2.8) < 1e-3      # chỗ hụt là im lặng
    assert rms(3.2, 4.8) > 0.05      # tiếng sau chỗ hụt nằm đúng giây 3-5
