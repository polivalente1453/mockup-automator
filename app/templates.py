"""Blank mockup templates: templates/<STORE CODE>/<name>.png plus calibration in config/calibration/.

A template places the design in one of two ways:
  window  - the PNG has a transparent "hole" where the mat is. The design goes UNDER the template,
            so the template's own shadows/texture sit on top. Corners are auto-detected.
  corners - an opaque photo of a blank mat. Someone clicks the 4 mat corners once in the web UI;
            the design is warped onto them and the mat's texture/lighting is multiplied in.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image

from .config import CALIBRATION_DIR, Settings

Image.MAX_IMAGE_PIXELS = None  # Drive templates are very large PNGs
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


@dataclass
class Calibration:
    mode: str = "window"           # window | corners
    corners: Optional[list] = None  # [[x,y] TL, TR, BR, BL] in template pixels
    shading: float = 0.85           # corners mode: how much mat lighting shows through the design
    texture: float = 0.35           # corners mode: how much fibre texture shows through dark ink
    bleed: float = 0.006            # window mode: grow the quad slightly so no gap shows at the edges
    base_color: tuple = (176, 140, 92)  # window mode: colour under transparent parts of a design (coir)


@dataclass
class Template:
    store: str
    name: str
    path: Path
    calibration: Calibration
    status: str  # ready | needs_corners

    @property
    def key(self) -> str:
        return f"{self.store}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "store": self.store, "name": self.name, "status": self.status,
            "mode": self.calibration.mode, "corners": self.calibration.corners,
            "shading": self.calibration.shading, "texture": self.calibration.texture,
        }


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def calibration_file(store: str, name: str) -> Path:
    return CALIBRATION_DIR / store / f"{name}.json"


def _cache_file(settings: Settings, path: Path) -> Path:
    st = path.stat()
    return settings.cache_dir / "detect" / path.parent.name / f"{path.name}.{int(st.st_mtime)}.{st.st_size}.json"


def order_corners(corners: Optional[list]) -> Optional[list]:
    """Put 4 clicked corners in TL, TR, BR, BL order, whatever order they were clicked in."""
    if not corners or len(corners) != 4:
        return corners
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    pts = sorted(corners, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # clockwise on screen
    start = min(range(4), key=lambda i: pts[i][0] + pts[i][1])
    return [list(p) for p in pts[start:] + pts[:start]]


def save_calibration(store: str, name: str, cal: Calibration) -> None:
    cal.corners = order_corners(cal.corners)
    f = calibration_file(store, name)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(asdict(cal), indent=2))


def detect_window(img: Image.Image) -> Optional[list]:
    """Find the 4 corners of a transparent hole in an RGBA template, or None if there isn't one."""
    if img.mode != "RGBA":
        return None
    scale = 4
    small = img.getchannel("A").reduce(scale)
    a = np.asarray(small)
    hole = a < 128
    if hole.sum() < 0.005 * hole.size:
        return None
    ys, xs = np.nonzero(hole)
    s, d = xs + ys, xs - ys
    tl = (xs[s.argmin()], ys[s.argmin()])
    br = (xs[s.argmax()], ys[s.argmax()])
    tr = (xs[d.argmax()], ys[d.argmax()])
    bl = (xs[d.argmin()], ys[d.argmin()])
    return [[int(x * scale), int(y * scale)] for x, y in (tl, tr, br, bl)]


def load_template(settings: Settings, store: str, path: Path) -> Template:
    name = path.name
    cal_f = calibration_file(store, name)
    if cal_f.exists():
        data = json.loads(cal_f.read_text())
        cal = Calibration(**{**asdict(Calibration()), **data})
        cal.base_color = tuple(cal.base_color)
        cal.corners = order_corners(cal.corners)
    else:
        cache = _cache_file(settings, path)
        if cache.exists():
            corners = json.loads(cache.read_text())["corners"]
        else:
            with Image.open(path) as im:
                corners = detect_window(im)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"corners": corners}))
        cal = Calibration(mode="window", corners=corners) if corners else Calibration(mode="corners")
    status = "ready" if cal.corners and len(cal.corners) == 4 else "needs_corners"
    return Template(store=store, name=name, path=path, calibration=cal, status=status)


def list_templates(settings: Settings, store: str) -> List[Template]:
    d = settings.store_templates_dir(store)
    if not d.exists():
        return []
    files = sorted((p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")),
                   key=lambda p: natural_key(p.name))
    return [load_template(settings, store, p) for p in files]


def get_template(settings: Settings, store: str, name: str) -> Template:
    path = settings.store_templates_dir(store) / name
    if not path.exists() or path.parent != settings.store_templates_dir(store):
        raise FileNotFoundError(f"Template not found: {store}/{name}")
    return load_template(settings, store, path)


def normalize_template(src: Path, dest: Path, width: int, height: int) -> None:
    """Scale a (huge) template down so it covers width x height, keeping alpha. Run once on sync."""
    with Image.open(src) as im:
        im.draft("RGB", (width, height))  # speeds up JPEG decoding
        mode = "RGBA" if ("A" in im.getbands() or "transparency" in im.info) else "RGB"
        im = im.convert(mode)
        r = max(width / im.width, height / im.height)
        if r < 1:
            im = im.resize((round(im.width * r), round(im.height * r)), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp.png")
        im.save(tmp, "PNG", compress_level=3)
        tmp.replace(dest.with_suffix(".png"))
