from vsub.hardsub import HardsubInfo, _band, caption_boxes


def box(cx, y0, y1, w, W=960, H=540):
    x0, x1 = (cx - w / 2) * W, (cx + w / 2) * W
    return [[x0, y0 * H], [x1, y0 * H], [x1, y1 * H], [x0, y1 * H]]


def test_caption_boxes_keeps_centered_short_boxes():
    boxes = [box(0.5, 0.92, 0.98, 0.5), box(0.2, 0.92, 0.98, 0.2), box(0.5, 0.3, 0.7, 0.3)]
    out = caption_boxes(boxes, 540)
    assert len(out) == 1 and abs(out[0][0] - 0.92) < 1e-6


def test_band_needs_consistent_position():
    steady = [[(0.92, 0.98)] for _ in range(8)] + [[] for _ in range(2)]
    ratio, band = _band(steady, 0.62, 1.0)
    assert ratio == 0.8 and band == (0.92, 0.98)
    scattered = [[(0.64 + i * 0.035, 0.67 + i * 0.035)] for i in range(10)]
    ratio, _ = _band(scattered, 0.62, 1.0)
    assert ratio < 0.35


def test_suggest_position():
    assert HardsubInfo(20, 0.9, 0.0).suggest_position() == "top"
    assert HardsubInfo(20, 0.1, 0.0).suggest_position() == "bottom"
    assert HardsubInfo(20, 0.0, 0.8).suggest_position() == "bottom"
