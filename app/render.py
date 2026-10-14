"""Puts a design onto a blank template. Pure local image processing (Pillow + numpy)."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

from .templates import Template

Point = Sequence[float]


def perspective_coeffs(dst: Sequence[Point], src: Sequence[Point]) -> list:
    """Coefficients for Image.transform(PERSPECTIVE): maps output points (dst) back to input points (src)."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def _grow(corners: Sequence[Point], amount: float) -> list:
    c = np.array(corners, float)
    center = c.mean(axis=0)
    return (center + (c - center) * (1 + amount)).tolist()


def warp(design: Image.Image, corners: Sequence[Point], size: Tuple[int, int]) -> Image.Image:
    """Warp an RGBA design so its 4 corners land on `corners` (TL, TR, BR, BL) on a canvas of `size`."""
    c = np.array(corners, float)
    target_w = max(np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[3]))
    target_h = max(np.linalg.norm(c[3] - c[0]), np.linalg.norm(c[2] - c[1]))
    # Pre-shrink with a good filter so the bicubic warp doesn't alias.
    r = min(1.0, 1.25 * max(target_w / design.width, target_h / design.height))
    if r < 1:
        design = design.resize((max(1, round(design.width * r)), max(1, round(design.height * r))),
                               Image.Resampling.LANCZOS)
    w, h = design.size
    coeffs = perspective_coeffs(corners, [(0, 0), (w, 0), (w, h), (0, h)])
    # Premultiplied alpha ("RGBa") avoids dark fringes around transparent edges.
    return design.convert("RGBa").transform(size, Image.Transform.PERSPECTIVE, coeffs,
                                            Image.Resampling.BICUBIC).convert("RGBA")


def _render_window(tpl: Image.Image, design: Image.Image, t: Template) -> Image.Image:
    cal = t.calibration
    base = Image.new("RGBA", design.size, tuple(cal.base_color) + (255,))
    base.alpha_composite(design)
    layer = warp(base, _grow(cal.corners, cal.bleed), tpl.size)
    canvas = Image.new("RGBA", tpl.size, (255, 255, 255, 255))
    canvas.alpha_composite(layer)
    canvas.alpha_composite(tpl.convert("RGBA"))
    return canvas.convert("RGB")


def _render_corners(tpl: Image.Image, design: Image.Image, t: Template) -> Image.Image:
    cal = t.calibration
    bg = tpl.convert("RGB")
    layer = warp(design, cal.corners, bg.size)
    c = np.array(cal.corners)
    x0, y0 = np.floor(c.min(axis=0)).astype(int).clip(0)
    x1, y1 = np.ceil(c.max(axis=0)).astype(int)
    x1, y1 = min(x1, bg.width), min(y1, bg.height)
    box = (x0, y0, x1, y1)

    bgf = np.asarray(bg.crop(box), np.float32) / 255
    lf = np.asarray(layer.crop(box), np.float32) / 255
    alpha = lf[..., 3:4]
    lum = 0.299 * bgf[..., 0] + 0.587 * bgf[..., 1] + 0.114 * bgf[..., 2]
    inside = alpha[..., 0] > 0.5
    mean = float(lum[inside].mean()) if inside.any() else 0.5
    shade = 1 + cal.shading * (lum / max(mean, 1e-3) - 1)
    texture = (lum - mean) * cal.texture
    printed = np.clip(lf[..., :3] * shade[..., None] + texture[..., None], 0, 1)
    out = bgf * (1 - alpha) + printed * alpha
    bg.paste(Image.fromarray((out * 255 + 0.5).astype(np.uint8)), box[:2])
    return bg


def render(template: Template, design: Image.Image, size: Tuple[int, int]) -> Image.Image:
    if template.status != "ready":
        raise ValueError(f"Template {template.key} needs its 4 mat corners set (Templates tab)")
    design = design.convert("RGBA")
    with Image.open(template.path) as tpl:
        tpl.load()
        if template.calibration.mode == "window":
            img = _render_window(tpl, design, template)
        else:
            img = _render_corners(tpl, design, template)
    if img.size != tuple(size):
        img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
    return img


def save_jpeg(img: Image.Image, path: Path, quality: int, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.jpg")
    img.save(tmp, "JPEG", quality=quality, dpi=(dpi, dpi), optimize=True, progressive=True, subsampling=0)
    tmp.replace(path)


def save_thumb(img: Image.Image, path: Path, width: int = 640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = img.copy()
    t.thumbnail((width, width))
    t.save(path, "JPEG", quality=80)
