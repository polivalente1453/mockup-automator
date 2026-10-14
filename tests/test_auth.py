"""Bearer-token gate on the Flask API (hosted deployments set MOCKUP_API_TOKEN)."""
import importlib

import app.server as server


def client_with_token(monkeypatch, token):
    monkeypatch.setenv("MOCKUP_API_TOKEN", token)
    importlib.reload(server)  # module-level API_TOKEN is read at import
    server.app.config["TESTING"] = True
    return server.app.test_client()


def teardown_module(module):
    # Re-import with a clean env so other test modules see the open server.
    import os
    os.environ.pop("MOCKUP_API_TOKEN", None)
    importlib.reload(server)


def test_rejects_without_token(monkeypatch):
    c = client_with_token(monkeypatch, "sekrit")
    assert c.get("/api/config").status_code == 401
    assert c.get("/").status_code == 401
    assert c.post("/api/jobs", json={}).status_code == 401


def test_rejects_wrong_token(monkeypatch):
    c = client_with_token(monkeypatch, "sekrit")
    r = c.get("/api/config", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_accepts_correct_token(monkeypatch):
    c = client_with_token(monkeypatch, "sekrit")
    r = c.get("/api/config", headers={"Authorization": "Bearer sekrit"})
    assert r.status_code == 200
    assert "stores" in r.get_json()


def test_open_when_env_unset(monkeypatch):
    monkeypatch.delenv("MOCKUP_API_TOKEN", raising=False)
    importlib.reload(server)
    server.app.config["TESTING"] = True
    c = server.app.test_client()
    assert c.get("/api/config").status_code == 200
