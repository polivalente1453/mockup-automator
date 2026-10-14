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
from .templates import IMAGE_EXTS, natural_key, normalize_template

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

    def fetch_design(self, sku: str, choice: Optional[str], log: Log) -> Path:
        files = self._images(sku)
        f = next((x for x in files if x["id"] == choice), files[0])
        if len(files) > 1 and not choice:
            log(f"{sku}: {len(files)} designs in folder, using '{f['name']}' ({self.s.design_pick})")
        dest = self.s.cache_dir / "designs" / sku / f"{f['id']}{Path(f['name']).suffix.lower()}"
        if not dest.exists():
            log(f"{sku}: downloading {f['name']}")
            self.client.download(f["id"], dest)
        return dest

    def publish(self, sku: str, store: Store, files: List[Path], log: Log) -> None:
        if not store.output_folder_id:
            log(f"{store.code}: no output_folder_id set, keeping files local only")
            return
        folder = self.client.ensure_folder(store.output_folder_id, sku)
        for p in files:
            self.client.upload(p, folder)
        log(f"{sku}/{store.code}: uploaded {len(files)} files to Drive")


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
