"""Add-store-from-the-UI logic: code suggestion, comment-preserving YAML
append with round-trip validation, Drive discovery, and the add_store gate
that only accepts folders inside "Bos Mockuplar"."""
from pathlib import Path

import pytest

from app.config import ConfigError, load_settings
from app.stores_admin import (
    StoreAdminError, add_store, append_store, discover_stores, suggest_code,
)

SETTINGS = """\
# comment that must survive
output:
  width: 4200
  height: 2800

paths:
  output_dir: output

drive:
  credentials_file: config/credentials.json
  designs_folder_id: DESIGNS

stores:
  - code: HSH
    name: Happy Step Home
    templates_folder_id: TPL_HSH   # keep me
    output_folder_id: OUT_HSH
    count: 10
    order: shuffle
    always_first: []
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text(SETTINGS)
    return p


# ── suggest_code ─────────────────────────────────────────────────────────────

def test_code_from_initials():
    assert suggest_code("Ahmet Doormat Store", ["HSH"]) == "ADS"
    assert suggest_code("Eagle Mehmet Store", []) == "EMS"


def test_code_dedupes_against_existing():
    assert suggest_code("Ahmet Doormat Store", ["ADS"]) == "ADS2"
    assert suggest_code("Ahmet Doormat Store", ["ADS", "ADS2"]) == "ADS3"


def test_code_short_name_fallback():
    assert suggest_code("Zo", []) == "ZO"
    assert len(suggest_code("X", [])) >= 2


# ── append_store ─────────────────────────────────────────────────────────────

def test_append_keeps_comments_and_loads(cfg):
    append_store("EDS", "Esra Doormat Store", "TPL_EDS", "OUT_EDS", cfg)
    text = cfg.read_text()
    assert "# comment that must survive" in text
    assert "# keep me" in text
    s = load_settings(cfg)
    assert [st.code for st in s.stores] == ["HSH", "EDS"]
    new = s.store("EDS")
    assert new.templates_folder_id == "TPL_EDS"
    assert new.output_folder_id == "OUT_EDS"
    assert new.count == 10 and new.order == "shuffle"


def test_append_duplicate_code_refused_and_file_untouched(cfg):
    before = cfg.read_text()
    with pytest.raises(ConfigError):
        append_store("HSH", "Clone", "TPL_X", "OUT_X", cfg)
    assert cfg.read_text() == before


def test_append_refused_when_stores_not_last(tmp_path):
    p = tmp_path / "settings.yaml"
    # `stores:` is NOT the last top-level key — the appended block would
    # attach to the wrong list, which the round-trip check must catch.
    p.write_text(SETTINGS + "\nextra_key:\n  - code: X\n    name: X\n")
    before = p.read_text()
    with pytest.raises((StoreAdminError, ConfigError)):
        append_store("EDS", "Esra", "TPL_EDS", "OUT_EDS", p)
    assert p.read_text() == before


# ── Drive-facing paths, with a fake client ───────────────────────────────────

class FakeFiles:
    def __init__(self, meta):
        self.meta = meta

    def get(self, fileId, **kw):
        class R:
            def __init__(self, v): self.v = v
            def execute(self): return self.v
        return R(self.meta[fileId])


class FakeDrive:
    """Only what stores_admin touches: svc.files().get, list_folders, ensure_folder."""

    def __init__(self, meta, children, ensured="OUT_NEW"):
        self._files = FakeFiles(meta)
        self.children = children
        self.ensured = ensured
        self.ensure_calls = []

    @property
    def svc(self):
        class S:
            def __init__(s, f): s.f = f
            def files(s): return s.f
        return S(self._files)

    def list_folders(self, parent_id):
        return self.children.get(parent_id, [])

    def ensure_folder(self, parent_id, name):
        self.ensure_calls.append((parent_id, name))
        return self.ensured


META = {
    "TPL_HSH": {"id": "TPL_HSH", "name": "Happy Step Home", "parents": ["BOS"]},
    "OUT_HSH": {"id": "OUT_HSH", "name": "Happy Step Home", "parents": ["MOCKUPS"]},
    "TPL_NEW": {"id": "TPL_NEW", "name": "Esra Doormat Store ", "parents": ["BOS"]},
    "TPL_ROGUE": {"id": "TPL_ROGUE", "name": "Rogue", "parents": ["ELSEWHERE"]},
}


def fake_drive():
    return FakeDrive(META, {"BOS": [
        {"id": "TPL_HSH", "name": "Happy Step Home"},
        {"id": "TPL_NEW", "name": "Esra Doormat Store "},
    ]})


def test_discover_filters_configured(cfg):
    s = load_settings(cfg)
    got = discover_stores(s, fake_drive())
    assert got == {"folders": [{"id": "TPL_NEW", "name": "Esra Doormat Store"}]}


def test_add_store_full_flow(cfg):
    s = load_settings(cfg)
    dc = fake_drive()
    st = add_store(s, dc, "TPL_NEW", config_path=cfg)
    # name trimmed, code from initials, output folder ensured under Mockups
    assert st == {"code": "EDS", "name": "Esra Doormat Store",
                  "templates_folder_id": "TPL_NEW", "output_folder_id": "OUT_NEW"}
    assert dc.ensure_calls == [("MOCKUPS", "Esra Doormat Store")]
    reloaded = load_settings(cfg)
    assert [x.code for x in reloaded.stores] == ["HSH", "EDS"]


def test_add_store_rejects_folder_outside_bos(cfg):
    s = load_settings(cfg)
    with pytest.raises(StoreAdminError, match="Bos Mockuplar"):
        add_store(s, fake_drive(), "TPL_ROGUE", config_path=cfg)


def test_add_store_rejects_already_configured(cfg):
    s = load_settings(cfg)
    with pytest.raises(StoreAdminError, match="already configured"):
        add_store(s, fake_drive(), "TPL_HSH", config_path=cfg)


def test_add_store_rejects_bad_code(cfg):
    s = load_settings(cfg)
    with pytest.raises(StoreAdminError, match="2-8"):
        add_store(s, fake_drive(), "TPL_NEW", code="x", config_path=cfg)
    with pytest.raises(StoreAdminError, match="taken"):
        add_store(s, fake_drive(), "TPL_NEW", code="hsh", config_path=cfg)
