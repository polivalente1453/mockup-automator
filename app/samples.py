"""Generates demo templates and designs so the tool can be tried without Google Drive.

HSH demo templates use "window" mode (transparent mat hole, auto-detected).
SNS demo templates use "corners" mode (opaque blank-mat photo + saved calibration).
`python -m app.cli sync` later replaces the demo templates with the real ones from Drive.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Settings
from .templates import Calibration, save_calibration

W, H = 4200, 2800
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/ariblk.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


def _noise(rng, h, w, scale, sigma):
    n = rng.normal(0, 1, (max(1, h // scale), max(1, w // scale))).astype(np.float32)
    img = Image.fromarray(((n * 40) + 128).clip(0, 255).astype(np.uint8)).resize((w, h), Image.Resampling.BICUBIC)
    return (np.asarray(img, np.float32) - 128) / 40 * sigma


def _coir(rng, h, w):
    base = np.array([176, 140, 92], np.float32)
    fine = _noise(rng, h, w, 2, 22) + _noise(rng, h, w, 6, 10)
    rows = (np.sin(np.arange(h) / 3.0) * 6)[:, None]
    return (base[None, None] + (fine + rows)[..., None]).clip(0, 255)


def _scene(seed, wall, door, floor, quad):
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    horizon = int(H * 0.6)
    img[:horizon] = np.array(wall, np.float32) + _noise(rng, horizon, W, 8, 4)[..., None]
    fl = np.array(floor, np.float32) + _noise(rng, H - horizon, W, 4, 10)[..., None]
    for y in range(0, H - horizon, 140):
        fl[y:y + 6] *= 0.85
    img[horizon:] = fl
    im = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    dx0, dx1 = int(W * 0.34), int(W * 0.66)
    d.rectangle([dx0 - 60, int(H * 0.02) - 60, dx1 + 60, horizon], fill=tuple(int(c * 0.8) for c in wall))
    d.rectangle([dx0, int(H * 0.02), dx1, horizon], fill=door)
    dark = tuple(int(c * 0.8) for c in door)
    for (y0, y1) in ((0.08, 0.30), (0.34, 0.56)):
        d.rectangle([dx0 + 120, int(H * y0), (dx0 + dx1) // 2 - 40, int(H * y1)], outline=dark, width=18)
        d.rectangle([(dx0 + dx1) // 2 + 40, int(H * y0), dx1 - 120, int(H * y1)], outline=dark, width=18)
    d.ellipse([dx1 - 260, int(H * 0.33), dx1 - 180, int(H * 0.36)], fill=(200, 170, 90))
    # soft shadow under the mat
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).polygon([(x + 25, y + 40) for x, y in quad], fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(40))
    im = Image.composite(Image.new("RGB", (W, H), (20, 15, 10)), im, sh)
    return im, rng


def _mat_mask(quad):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in quad], fill=255)
    return m


SCENES = [
    (1, (232, 228, 220), (38, 52, 74), (120, 112, 104), [(1250, 1900), (2950, 1900), (3200, 2560), (1000, 2560)]),
    (2, (214, 222, 212), (150, 40, 38), (96, 84, 72), [(1300, 1950), (2900, 1950), (3080, 2600), (1120, 2600)]),
    (3, (240, 236, 226), (30, 30, 30), (160, 150, 136), [(1150, 1880), (3050, 1880), (3350, 2620), (850, 2620)]),
    (4, (205, 196, 182), (70, 96, 72), (110, 100, 90), [(1400, 1980), (2800, 1980), (2950, 2560), (1250, 2560)]),
]


def make_samples(s: Settings) -> None:
    hsh, sns = s.stores[0].code, s.stores[min(1, len(s.stores) - 1)].code
    for i, (seed, wall, door, floor, quad) in enumerate(SCENES, 1):
        im, rng = _scene(seed, wall, door, floor, quad)
        mask = _mat_mask(quad)
        name = f"demo-{i}.png"

        # window template: mat area semi-transparent with fibre texture on top of the design
        texture = _coir(rng, H, W)
        lum = (texture.mean(axis=2) - texture.mean()) / 60
        shade = Image.fromarray(np.full((H, W, 3), 0, np.uint8))
        alpha_hole = (40 + np.abs(lum) * 50).clip(0, 110).astype(np.uint8)
        win = im.convert("RGBA")
        hole = Image.merge("RGBA", (*shade.split(), Image.fromarray(alpha_hole)))
        win.paste(hole, (0, 0), mask)
        out = s.store_templates_dir(hsh) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        win.save(out, compress_level=3)

        # corners template: opaque photo of a blank coir mat
        mat = Image.fromarray(_coir(rng, H, W).astype(np.uint8))
        photo = im.copy()
        photo.paste(mat, (0, 0), mask)
        out = s.store_templates_dir(sns) / name
        out.parent.mkdir(parents=True, exist_ok=True)
        photo.save(out, compress_level=3)
        save_calibration(sns, name, Calibration(mode="corners", corners=[list(p) for p in quad]))
        print(f"templates: {hsh}/{name}, {sns}/{name}")

    s.designs_dir.mkdir(parents=True, exist_ok=True)
    dw, dh = 3000, 1800
    # transparent black-ink design (typical coir print)
    d1 = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
    g = ImageDraw.Draw(d1)
    g.rectangle([60, 60, dw - 60, dh - 60], outline=(15, 15, 15, 255), width=40)
    g.text((dw // 2, dh // 2 - 80), "WELCOME", font=_font(420), fill=(15, 15, 15, 255), anchor="mm")
    g.text((dw // 2, dh // 2 + 330), "home sweet home", font=_font(170), fill=(15, 15, 15, 255), anchor="mm")
    d1.save(s.designs_dir / "DEMO-101.png")
    # full-colour opaque design
    d2 = Image.new("RGBA", (dw, dh), (34, 76, 60, 255))
    g = ImageDraw.Draw(d2)
    for x in range(-dh, dw, 220):
        g.line([(x, dh), (x + dh, 0)], fill=(48, 98, 78, 255), width=70)
    g.rounded_rectangle([180, 420, dw - 180, dh - 420], radius=80, fill=(238, 226, 200, 255))
    g.text((dw // 2, dh // 2), "HELLO THERE", font=_font(300), fill=(34, 76, 60, 255), anchor="mm")
    d2.save(s.designs_dir / "DEMO-102.png")
    print(f"designs: {s.designs_dir}/DEMO-101.png, DEMO-102.png")
