"""Thin Google Drive v3 client. Uses the free Drive API with each team member's own Google login.

First use opens a browser to sign in; the token is stored per machine in config/token.json.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional

from .config import ROOT

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER = "application/vnd.google-apps.folder"
TOKEN_FILE = ROOT / "config" / "token.json"
FIELDS = "files(id,name,mimeType,size,modifiedTime,md5Checksum)"


class DriveNotConfigured(Exception):
    pass


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(self, credentials_file: Path):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_file.exists():
                    raise DriveNotConfigured(
                        f"Missing {credentials_file.relative_to(ROOT)}. See README > Google Drive setup.")
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_FILE.write_text(creds.to_json())
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def _list(self, q: str) -> List[dict]:
        files, token = [], None
        while True:
            r = self.svc.files().list(
                q=q, fields=f"nextPageToken,{FIELDS}", pageSize=1000, pageToken=token,
                supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            files.extend(r.get("files", []))
            token = r.get("nextPageToken")
            if not token:
                return files

    def list_folders(self, parent_id: str) -> List[dict]:
        return self._list(f"'{parent_id}' in parents and mimeType = '{FOLDER}' and trashed = false")

    def list_images(self, parent_id: str) -> List[dict]:
        return self._list(f"'{parent_id}' in parents and mimeType contains 'image/' and trashed = false")

    def find_child(self, parent_id: str, name: str, folder: bool) -> Optional[dict]:
        kind = "=" if folder else "!="
        hits = self._list(f"'{parent_id}' in parents and name = '{_q(name)}' "
                          f"and mimeType {kind} '{FOLDER}' and trashed = false")
        return hits[0] if hits else None

    def ensure_folder(self, parent_id: str, name: str) -> str:
        hit = self.find_child(parent_id, name, folder=True)
        if hit:
            return hit["id"]
        meta = {"name": name, "mimeType": FOLDER, "parents": [parent_id]}
        return self.svc.files().create(body=meta, fields="id", supportsAllDrives=True).execute()["id"]

    def download(self, file_id: str, dest: Path) -> None:
        from googleapiclient.http import MediaIoBaseDownload

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with io.FileIO(str(tmp), "wb") as fh:
            dl = MediaIoBaseDownload(fh, self.svc.files().get_media(fileId=file_id, supportsAllDrives=True),
                                     chunksize=32 * 1024 * 1024)
            done = False
            while not done:
                _, done = dl.next_chunk()
        tmp.replace(dest)

    def trash(self, file_id: str) -> None:
        """Move a file to the Drive trash (recoverable there for ~30 days, unlike a hard delete)."""
        self.svc.files().update(fileId=file_id, body={"trashed": True}, fields="id",
                                supportsAllDrives=True).execute()

    def upload(self, path: Path, parent_id: str, name: Optional[str] = None) -> str:
        """Upload, replacing a file with the same name in that folder (so re-runs don't duplicate)."""
        from googleapiclient.http import MediaFileUpload

        name = name or path.name
        media = MediaFileUpload(str(path), mimetype="image/jpeg", resumable=True)
        existing = self.find_child(parent_id, name, folder=False)
        if existing:
            return self.svc.files().update(fileId=existing["id"], media_body=media, fields="id",
                                           supportsAllDrives=True).execute()["id"]
        meta = {"name": name, "parents": [parent_id]}
        return self.svc.files().create(body=meta, media_body=media, fields="id",
                                       supportsAllDrives=True).execute()["id"]
