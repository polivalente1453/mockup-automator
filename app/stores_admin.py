"""Add stores from the web UI.

A store is two Drive folders — blank templates under "Bos Mockuplar" and
finished mockups under "Mockups" — plus an entry in config/settings.yaml.
The UI discovers template folders that exist in Drive but aren't configured
yet; adding one creates/finds the matching output folder and appends a
store block to settings.yaml. The server re-reads settings on every
request, so a new store is usable immediately with no restart.

settings.yaml is hand-edited and commented, so the new store is appended
as TEXT (never a yaml.dump of the whole file, which would strip every
comment). The result is validated by round-tripping through load_settings
on a temp file before atomically replacing the real one — a bad append can
never leave the config broken.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .config import CONFIG_PATH, Settings, load_settings


class StoreAdminError(Exception):
    pass


CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")


def suggest_code(name: str, existing: List[str]) -> str:
    """Store code from the name's initials: "Ahmet Doormat Store" -> ADS.

    Falls back to the first letters of the name, and de-dupes against
    existing codes with a numeric suffix (ADS, ADS2, ADS3...).
    """
    words = re.findall(r"[A-Za-z0-9]+", name)
    code = "".join(w[0] for w in words).upper()[:4]
    if len(code) < 2:
        code = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:3]
    if len(code) < 2:
        code = (code + "ST")[:2]
    taken = {c.upper() for c in existing}
    if code not in taken:
        return code
    n = 2
    while f"{code}{n}" in taken:
        n += 1
    return f"{code}{n}"


def store_yaml_block(code: str, name: str, templates_folder_id: str,
                     output_folder_id: str) -> str:
    """The text appended to settings.yaml — same shape as the hand-written stores."""
    return (
        f"  - code: {code}\n"
        f"    name: {name}\n"
        f"    templates_folder_id: {templates_folder_id}   # Bos Mockuplar/{name}\n"
        f"    output_folder_id: {output_folder_id}      # Mockups/{name}\n"
        f"    count: 10\n"
        f"    order: shuffle\n"
        f"    always_first: []\n"
    )


def append_store(code: str, name: str, templates_folder_id: str,
                 output_folder_id: str, config_path: Optional[Path] = None) -> None:
    """Append the store to settings.yaml, validate, then atomically replace.

    Assumes `stores:` is the LAST top-level key in the file (it is, and the
    round-trip validation catches it if that ever changes: the appended
    store would not come back from load_settings and we refuse the write).
    """
    path = Path(config_path or CONFIG_PATH)
    text = path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + store_yaml_block(code, name, templates_folder_id, output_folder_id)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".yaml")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        validated = load_settings(tmp)  # raises ConfigError on anything wrong
        got = [s for s in validated.stores if s.code == code]
        if not got or got[0].templates_folder_id != templates_folder_id:
            raise StoreAdminError(
                "settings.yaml no longer ends with the stores list — add the store by hand.")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ── Drive discovery ──────────────────────────────────────────────────────────

def _folder_meta(dc, file_id: str) -> dict:
    return dc.svc.files().get(
        fileId=file_id, fields="id,name,parents,mimeType", supportsAllDrives=True,
    ).execute()


def drive_parents(settings: Settings, dc) -> Tuple[str, str]:
    """Derive the "Bos Mockuplar" and "Mockups" parent folder ids from the
    first configured store — zero extra config, and both always exist."""
    for s in settings.stores:
        if s.templates_folder_id and s.output_folder_id:
            tpl = _folder_meta(dc, s.templates_folder_id)
            out = _folder_meta(dc, s.output_folder_id)
            if tpl.get("parents") and out.get("parents"):
                return tpl["parents"][0], out["parents"][0]
    raise StoreAdminError("No existing store with Drive folders to anchor discovery.")


def discover_stores(settings: Settings, dc) -> dict:
    """Folders under Bos Mockuplar that aren't configured as a store yet."""
    bos_id, _ = drive_parents(settings, dc)
    configured = {s.templates_folder_id for s in settings.stores}
    folders = [
        {"id": f["id"], "name": f["name"].strip()}
        for f in dc.list_folders(bos_id)
        if f["id"] not in configured
    ]
    folders.sort(key=lambda f: f["name"].lower())
    return {"folders": folders}


def add_store(settings: Settings, dc, templates_folder_id: str,
              name: Optional[str] = None, code: Optional[str] = None,
              config_path: Optional[Path] = None) -> dict:
    """Wire a Bos Mockuplar folder up as a store. Returns the new store dict."""
    if any(s.templates_folder_id == templates_folder_id for s in settings.stores):
        raise StoreAdminError("That folder is already configured as a store.")

    meta = _folder_meta(dc, templates_folder_id)
    bos_id, mockups_id = drive_parents(settings, dc)
    if bos_id not in (meta.get("parents") or []):
        # Only folders inside Bos Mockuplar become stores — never an
        # arbitrary Drive folder id.
        raise StoreAdminError(
            'That folder is not inside "Bos Mockuplar" — create the store folder there.')

    name = (name or meta["name"]).strip()
    if not name:
        raise StoreAdminError("The store needs a name.")
    existing_codes = [s.code for s in settings.stores]
    if code:
        code = code.strip().upper()
        if not CODE_RE.match(code):
            raise StoreAdminError("Store code must be 2-8 letters/digits.")
        if code in {c.upper() for c in existing_codes}:
            raise StoreAdminError(f"Store code {code} is already taken.")
    else:
        code = suggest_code(name, existing_codes)

    output_folder_id = dc.ensure_folder(mockups_id, name)
    append_store(code, name, templates_folder_id, output_folder_id, config_path)
    return {
        "code": code,
        "name": name,
        "templates_folder_id": templates_folder_id,
        "output_folder_id": output_folder_id,
    }
