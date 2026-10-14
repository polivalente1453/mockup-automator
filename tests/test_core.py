import numpy as np
from PIL import Image

from app.config import Store
from app.planner import plan_store
from app.render import perspective_coeffs, warp
from app.templates import Calibration, Template, detect_window


def _tpl(name, ready=True):
    cal = Calibration(corners=[[0, 0], [1, 0], [1, 1], [0, 1]] if ready else None)
    return Template("HSH", name, None, cal, "ready" if ready else "needs_corners")


def test_plan_is_stable_and_varies_by_sku():
    store = Store(code="HSH", name="x", count=5)
    tpls = [_tpl(f"{i}.png") for i in range(1, 13)]
    a1, _ = plan_store(store, "334", tpls)
    a2, _ = plan_store(store, "334", tpls)
    b, _ = plan_store(store, "335", tpls)
    assert [t.name for t in a1] == [t.name for t in a2]
    assert [t.name for t in a1] != [t.name for t in b]
    assert len(a1) == 5 and len({t.name for t in a1}) == 5


def test_plan_pins_and_skips_uncalibrated():
    store = Store(code="HSH", name="x", count=3, always_first=["1.png"])
    tpls = [_tpl("1.png"), _tpl("2.png", ready=False), _tpl("3.png"), _tpl("4.png")]
    chosen, warnings = plan_store(store, "334", tpls)
    assert chosen[0].name == "1.png"
    assert "2.png" not in [t.name for t in chosen]
    assert any("uncalibrated" in w for w in warnings)


def test_perspective_maps_corners():
    dst = [(100, 50), (400, 60), (420, 300), (80, 290)]
    src = [(0, 0), (10, 0), (10, 5), (0, 5)]
    a, b, c, d, e, f, g, h = perspective_coeffs(dst, src)
    for (x, y), (u, v) in zip(dst, src):
        den = g * x + h * y + 1
        assert abs((a * x + b * y + c) / den - u) < 1e-6
        assert abs((d * x + e * y + f) / den - v) < 1e-6


def test_detect_window_finds_hole():
    img = Image.new("RGBA", (800, 600), (200, 200, 200, 255))
    hole = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    img.paste(hole, (200, 300))
    corners = detect_window(img)
    assert corners is not None
    assert abs(corners[0][0] - 200) <= 8 and abs(corners[0][1] - 300) <= 8
    assert abs(corners[2][0] - 500) <= 8 and abs(corners[2][1] - 500) <= 8


def test_warp_fills_quad():
    design = Image.new("RGBA", (100, 60), (255, 0, 0, 255))
    out = np.asarray(warp(design, [(50, 50), (150, 50), (150, 110), (50, 110)], (200, 200)))
    assert out[80, 100, 3] == 255 and out[80, 100, 0] == 255
    assert out[10, 10, 3] == 0


def test_has_transparency_prefers_cutout_designs(tmp_path):
    from app.sources import has_transparency
    cutout = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    opaque_rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    photo = Image.new("RGB", (10, 10), (255, 0, 0))
    for name, im in (("c.png", cutout), ("o.png", opaque_rgba), ("p.png", photo)):
        im.save(tmp_path / name)
    assert has_transparency(tmp_path / "c.png")
    assert not has_transparency(tmp_path / "o.png")
    assert not has_transparency(tmp_path / "p.png")


def test_order_corners_fixes_click_order():
    from app.templates import order_corners
    want = [[100, 100], [400, 110], [420, 300], [90, 290]]
    for clicked in (want, [want[0], want[3], want[2], want[1]], [want[2], want[0], want[3], want[1]]):
        assert order_corners(clicked) == want


def test_fit_design_trims_border():
    from app.render import fit_design
    design = Image.new("RGBA", (2000, 2000), (0, 0, 0, 0))
    design.paste((255, 0, 0, 255), (100, 700, 1900, 1300))  # 1800x600 artwork in a square file
    out = fit_design(design, margin=0.02)
    assert abs(out.width / out.height - 3) < 0.01
    bbox = out.getchannel("A").getbbox()
    assert (bbox[2] - bbox[0]) / out.width > 0.95 and (bbox[3] - bbox[1]) / out.height > 0.95
