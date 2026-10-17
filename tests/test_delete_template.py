"""Deleting a blank template: Drive trash first (source of truth), then local cleanup."""
import json
from pathlib import Path

import pytest

import app.sources as sources
import app.templates as templates
from app.config import Settings, Store
from app.sources import delete_template


class FakeDrive:
    def __init__(self, files, fail_trash=False):
        self.files = files
        self.fail_trash = fail_trash
        self.trashed = []

    def list_images(self, parent_id):
        return self.files

    def trash(self, file_id):
        if self.fail_trash:
            raise RuntimeError("Drive says no")
        self.trashed.append(file_id)


def make_settings(tmp_path, store) -> Settings:
    return Settings(
        width=4200, height=2800, quality=92, dpi=300,
        output_dir=tmp_path / "output", templates_dir=tmp_path / "templates",
        designs_dir=tmp_path / "designs", cache_dir=tmp_path / "cache",
        credentials_file=tmp_path / "credentials.json",
        designs_folder_id="", design_pick="newest", stores=[store],
    )


def seed(tmp_path, monkeypatch, store, name="Blank3.png"):
    s = make_settings(tmp_path, store)
    d = s.store_templates_dir(store.code)
    d.mkdir(parents=True)
    (d / name).write_bytes(b"png")
    (d / ".manifest.json").write_text(json.dumps({name: "stamp", "Other.png": "x"}))
    monkeypatch.setattr(templates, "CALIBRATION_DIR", tmp_path / "calibration")
    cal = templates.calibration_file(store.code, name)
    cal.parent.mkdir(parents=True)
    cal.write_text("{}")
    return s, d, cal


def test_local_only_store_deletes_everything_locally(tmp_path, monkeypatch):
    store = Store(code="HSH", name="x")  # no templates_folder_id
    s, d, cal = seed(tmp_path, monkeypatch, store)
    out = delete_template(s, store, "Blank3.png", lambda m: None)
    assert out == {"deleted": "Blank3.png", "trashed_on_drive": 0}
    assert not (d / "Blank3.png").exists()
    assert not cal.exists()
    assert json.loads((d / ".manifest.json").read_text()) == {"Other.png": "x"}


def test_drive_store_trashes_every_stem_match(tmp_path, monkeypatch):
    store = Store(code="HSH", name="x", templates_folder_id="tpl-folder")
    s, d, _ = seed(tmp_path, monkeypatch, store)
    fake = FakeDrive([
        {"id": "a", "name": "Blank3.jpg"},       # same stem, other extension
        {"id": "b", "name": "Blank3.png "},      # trailing space (Drive reality)
        {"id": "c", "name": "Blank30.png"},      # different stem — must survive
    ])
    monkeypatch.setattr(sources, "drive_client", lambda _s: fake)
    out = delete_template(s, store, "Blank3.png", lambda m: None)
    assert fake.trashed == ["a", "b"]
    assert out["trashed_on_drive"] == 2
    assert not (d / "Blank3.png").exists()


def test_drive_failure_leaves_local_untouched(tmp_path, monkeypatch):
    store = Store(code="HSH", name="x", templates_folder_id="tpl-folder")
    s, d, cal = seed(tmp_path, monkeypatch, store)
    fake = FakeDrive([{"id": "a", "name": "Blank3.png"}], fail_trash=True)
    monkeypatch.setattr(sources, "drive_client", lambda _s: fake)
    with pytest.raises(RuntimeError):
        delete_template(s, store, "Blank3.png", lambda m: None)
    assert (d / "Blank3.png").exists()
    assert cal.exists()


def test_gone_from_drive_still_deletes_locally(tmp_path, monkeypatch):
    store = Store(code="HSH", name="x", templates_folder_id="tpl-folder")
    s, d, _ = seed(tmp_path, monkeypatch, store)
    fake = FakeDrive([])
    monkeypatch.setattr(sources, "drive_client", lambda _s: fake)
    out = delete_template(s, store, "Blank3.png", lambda m: None)
    assert out["trashed_on_drive"] == 0
    assert not (d / "Blank3.png").exists()


def test_unknown_and_traversal_names_404(tmp_path, monkeypatch):
    store = Store(code="HSH", name="x")
    s, _, _ = seed(tmp_path, monkeypatch, store)
    for bad in ("Nope.png", "../Blank3.png", "sub/Blank3.png"):
        with pytest.raises(FileNotFoundError):
            delete_template(s, store, bad, lambda m: None)


def test_route_deletes_and_404s(tmp_path, monkeypatch):
    import app.server as server
    store = Store(code="HSH", name="x")
    s, d, _ = seed(tmp_path, monkeypatch, store)
    monkeypatch.setattr(server, "load_settings", lambda: s)
    server.app.config["TESTING"] = True
    c = server.app.test_client()
    assert c.post("/api/templates/NOPE/Blank3.png/delete").status_code == 404
    assert c.post("/api/templates/HSH/Nope.png/delete").status_code == 404
    r = c.post("/api/templates/HSH/Blank3.png/delete")
    assert r.status_code == 200
    assert r.get_json()["deleted"] == "Blank3.png"
    assert not (d / "Blank3.png").exists()
