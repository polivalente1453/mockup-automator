"""Where designs come from and where finished mockups go.

LocalSource: designs/<SKU>.png -> output/ only (no Google account needed; good for testing).
DriveSource: Doormat Designs/<SKU>/ -> output/ -> Mockups/<Store>/<SKU>/ on Drive.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import Settings, Store
from .templates import IMAGE_EXTS, calibration_file, natural_key, normalize_template

Log = Callable[[str], None]

_drive_lock = threading.Lock()
_drive_client = None


def drive_client(settings: Settings):
    global _drive_client
    with _drive_lock:
        if _drive_client is None:
            from .drive import DriveClient
            _drive_client = DriveClient(settings.credentials_file)
        return _drive_client


class LocalSource:
    name = "local"

    def __init__(self, settings: Settings):
        self.s = settings

    def list_skus(self) -> List[str]:
        d = self.s.designs_dir
        if not d.exists():
            return []
        return sorted({p.stem for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS}, key=natural_key)

    def design_options(self, sku: str) -> List[dict]:
        return [{"id": p.name, "name": p.name} for p in self._files(sku)]

    def _files(self, sku: str) -> List[Path]:
        return [p for p in sorted(self.s.designs_dir.glob(f"{sku}.*")) if p.suffix.lower() in IMAGE_EXTS]

    def fetch_design(self, sku: str, choice: Optional[str], log: Log) -> Path:
        files = self._files(sku)
        if not files:
            raise FileNotFoundError(f"No design for {sku} in {self.s.designs_dir}")
        for f in files:
            if choice and f.name == choice:
                return f
        return files[0]

    def publish(self, sku: str, store: Store, files: List[Path], log: Log) -> None:
        pass


class DriveSource:
    name = "drive"

    def __init__(self, settings: Settings):
        self.s = settings
        self.client = drive_client(settings)
        self._folders: Dict[str, str] = {}

    def _sku_folders(self) -> Dict[str, str]:
        if not self._folders:
            if not self.s.designs_folder_id:
                raise ValueError("drive.designs_folder_id is not set in settings.yaml")
            self._folders = {f["name"].strip(): f["id"] for f in self.client.list_folders(self.s.designs_folder_id)}
        return self._folders

    def list_skus(self) -> List[str]:
        self._folders = {}
        return sorted(self._sku_folders(), key=natural_key, reverse=True)

    def _images(self, sku: str) -> List[dict]:
        folder = self._sku_folders().get(sku)
        if not folder:
            raise FileNotFoundError(f"No folder '{sku}' in Doormat Designs")
        files = self.client.list_images(folder)
        if not files:
            raise FileNotFoundError(f"Folder {sku} has no images")
        key = (lambda f: int(f.get("size", 0))) if self.s.design_pick == "largest" else (lambda f: f["modifiedTime"])
        return sorted(files, key=key, reverse=True)

    def design_options(self, sku: str) -> List[dict]:
        return [{"id": f["id"], "name": f["name"]} for f in self._images(sku)]

    def _download(self, sku: str, f: dict, log: Log) -> Path:
        dest = self.s.cache_dir / "designs" / sku / f"{f['id']}{Path(f['name']).suffix.lower()}"
        if not dest.exists():
            log(f"{sku}: downloading {f['name']}")
            self.client.download(f["id"], dest)
        return dest

    def fetch_design(self, sku: str, choice: Optional[str], log: Log) -> Path:
        files = self._images(sku)
        picked = next((x for x in files if x["id"] == choice), None)
        if picked or len(files) == 1:
            return self._download(sku, picked or files[0], log)
        # Folders often hold finished mockup photos next to the design. The printable design is the
        # one with a transparent background, so prefer that; otherwise fall back to design_pick order.
        for f in files:
            path = self._download(sku, f, log)
            if has_transparency(path):
                log(f"{sku}: {len(files)} images in folder, using '{f['name']}' (transparent background)")
                return path
        log(f"{sku}: {len(files)} images in folder, none transparent, using '{files[0]['name']}' ({self.s.design_pick})")
        return self._download(sku, files[0], log)

    def publish(self, sku: str, store: Store, files: List[Path], log: Log) -> None:
        if not store.output_folder_id:
            log(f"{store.code}: no output_folder_id set, keeping files local only")
            return
        folder = self.client.ensure_folder(store.output_folder_id, sku)
        for p in files:
            self.client.upload(p, folder)
        log(f"{sku}/{store.code}: uploaded {len(files)} files to Drive")


def has_transparency(path: Path) -> bool:
    """True if the image has a real see-through area (not just an all-opaque alpha channel)."""
    from PIL import Image
    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
            return im.convert("RGBA").getchannel("A").getextrema()[0] < 128
    return False


def make_source(settings: Settings, name: str):
    if name == "drive":
        return DriveSource(settings)
    if name == "local":
        return LocalSource(settings)
    raise ValueError(f"Unknown source: {name}")


def sync_templates(settings: Settings, store: Store, log: Log) -> int:
    """Mirror Bos Mockuplar/<store> into templates/<CODE>/, downscaled to output size. Returns files changed."""
    if not store.templates_folder_id:
        raise ValueError(f"{store.code}: templates_folder_id not set")
    client = drive_client(settings)
    dest_dir = settings.store_templates_dir(store.code)
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest_f = dest_dir / ".manifest.json"
    manifest = json.loads(manifest_f.read_text()) if manifest_f.exists() else {}

    remote = client.list_images(store.templates_folder_id)
    wanted = set()
    changed = 0
    for f in remote:
        local_name = Path(f["name"]).stem + ".png"
        wanted.add(local_name)
        stamp = f.get("md5Checksum") or f["modifiedTime"]
        if manifest.get(local_name) == stamp and (dest_dir / local_name).exists():
            continue
        size_mb = int(f.get("size", 0)) / 1e6
        log(f"{store.code}: downloading template {f['name']} ({size_mb:.0f} MB)")
        raw = settings.cache_dir / "raw-templates" / store.code / f["name"]
        client.download(f["id"], raw)
        normalize_template(raw, dest_dir / local_name, settings.width, settings.height)
        raw.unlink()
        manifest[local_name] = stamp
        manifest_f.write_text(json.dumps(manifest, indent=1))
        changed += 1
    for p in dest_dir.glob("*.png"):
        if p.name not in wanted:
            log(f"{store.code}: removing {p.name} (no longer on Drive)")
            p.unlink()
            manifest.pop(p.name, None)
            changed += 1
    manifest_f.write_text(json.dumps(manifest, indent=1))
    log(f"{store.code}: {len(remote)} templates on Drive, {changed} updated")
    return changed


def delete_template(settings: Settings, store: Store, name: str, log: Log) -> dict:
    """Remove a blank template everywhere it lives.

    Drive (Bos Mockuplar) is the source of truth — sync_templates mirrors it, so a
    local-only delete would come straight back on the next sync. Order matters:
    trash the Drive original(s) FIRST; if that fails, nothing local is touched, so
    the user sees the error instead of a template that quietly resurrects.
    The local name is normalized to <stem>.png, so every Drive image sharing the
    stem (any extension, trailing spaces tolerated) is trashed — same collapsing
    rule the sync uses. Drive trash keeps the file recoverable for ~30 days.
    """
    dest_dir = settings.store_templates_dir(store.code)
    local = dest_dir / name
    if local.parent != dest_dir or not local.exists():
        raise FileNotFoundError(f"Template not found: {store.code}/{name}")
    stem = Path(name).stem
    trashed = 0
    if store.templates_folder_id:
        client = drive_client(settings)
        for f in client.list_images(store.templates_folder_id):
            if Path(f["name"].strip()).stem == stem:
                client.trash(f["id"])
                trashed += 1
                log(f"{store.code}: moved {f['name']} to the Drive trash")
        if not trashed:
            log(f"{store.code}: {stem} not found in Drive (already removed there)")
    local.unlink()
    cal = calibration_file(store.code, name)
    if cal.exists():
        cal.unlink()
    manifest_f = dest_dir / ".manifest.json"
    if manifest_f.exists():
        manifest = json.loads(manifest_f.read_text())
        if manifest.pop(name, None) is not None:
            manifest_f.write_text(json.dumps(manifest, indent=1))
    log(f"{store.code}: deleted template {name}")
    return {"deleted": name, "trashed_on_drive": trashed}
