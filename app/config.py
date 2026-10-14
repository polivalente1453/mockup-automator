"""Loads config/settings.yaml into typed objects."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("MOCKUP_CONFIG", str(ROOT / "config" / "settings.yaml")))
CALIBRATION_DIR = ROOT / "config" / "calibration"


class ConfigError(Exception):
    pass


@dataclass
class Store:
    code: str
    name: str
    count: int = 10
    order: str = "shuffle"
    always_first: List[str] = field(default_factory=list)
    templates_folder_id: str = ""
    output_folder_id: str = ""


@dataclass
class Settings:
    width: int
    height: int
    quality: int
    dpi: int
    output_dir: Path
    templates_dir: Path
    designs_dir: Path
    cache_dir: Path
    credentials_file: Path
    designs_folder_id: str
    design_pick: str
    stores: List[Store]

    def store(self, code: str) -> Store:
        for s in self.stores:
            if s.code == code:
                return s
        raise ConfigError(f"Unknown store code: {code}")

    def store_templates_dir(self, code: str) -> Path:
        return self.templates_dir / code


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load_settings(path: Optional[Path] = None) -> Settings:
    path = path or CONFIG_PATH
    raw = yaml.safe_load(Path(path).read_text()) or {}
    out = raw.get("output", {})
    paths = raw.get("paths", {})
    drive = raw.get("drive", {})

    stores = []
    seen = set()
    for s in raw.get("stores", []):
        code = str(s.get("code", "")).strip()
        if not code:
            raise ConfigError("Every store needs a 'code' (e.g. HSH)")
        if code in seen:
            raise ConfigError(f"Duplicate store code: {code}")
        seen.add(code)
        order = s.get("order", "shuffle")
        if order not in ("shuffle", "fixed"):
            raise ConfigError(f"{code}: order must be 'shuffle' or 'fixed'")
        stores.append(Store(
            code=code,
            name=str(s.get("name", code)).strip(),
            count=int(s.get("count", 10)),
            order=order,
            always_first=list(s.get("always_first") or []),
            templates_folder_id=str(s.get("templates_folder_id") or ""),
            output_folder_id=str(s.get("output_folder_id") or ""),
        ))
    if not stores:
        raise ConfigError("No stores configured in settings.yaml")

    pick = drive.get("design_pick", "newest")
    if pick not in ("newest", "largest"):
        raise ConfigError("drive.design_pick must be 'newest' or 'largest'")

    return Settings(
        width=int(out.get("width", 4200)),
        height=int(out.get("height", 2800)),
        quality=int(out.get("quality", 92)),
        dpi=int(out.get("dpi", 300)),
        output_dir=_path(paths.get("output_dir", "output")),
        templates_dir=_path(paths.get("templates_dir", "templates")),
        designs_dir=_path(paths.get("designs_dir", "designs")),
        cache_dir=_path(paths.get("cache_dir", ".cache")),
        credentials_file=_path(drive.get("credentials_file", "config/credentials.json")),
        designs_folder_id=str(drive.get("designs_folder_id") or ""),
        design_pick=pick,
        stores=stores,
    )
