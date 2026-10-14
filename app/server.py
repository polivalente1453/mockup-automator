"""Local web UI: http://127.0.0.1:8765"""
from __future__ import annotations

import hmac
import os
from dataclasses import asdict

from flask import Flask, abort, jsonify, request, send_from_directory

from .config import ROOT, load_settings
from .pipeline import Job, JobRunner
from .render import render
from .sources import make_source
from .templates import Calibration, get_template, list_templates, save_calibration
from .drive import TOKEN_FILE

app = Flask(__name__, static_folder=None)
runner = JobRunner(load_settings)

# Optional bearer-token gate for hosted deployments (NESA admin proxy).
# When MOCKUP_API_TOKEN is set, EVERY route requires
# `Authorization: Bearer <token>` — the UI itself is served through the
# authenticated reverse proxy, so nothing needs to stay public. When the
# env var is unset (local per-machine use on 127.0.0.1) behavior is
# unchanged: no auth, same as before.
API_TOKEN = os.environ.get("MOCKUP_API_TOKEN", "")


@app.before_request
def _require_token():
    if not API_TOKEN:
        return None
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {API_TOKEN}"):
        return jsonify({"error": "unauthorized"}), 401
    return None


def err(msg, code=400):
    return jsonify({"error": str(msg)}), code


@app.get("/")
def index():
    return send_from_directory(ROOT / "web", "index.html")


@app.get("/web/<path:name>")
def web(name):
    return send_from_directory(ROOT / "web", name)


@app.get("/api/config")
def config():
    s = load_settings()
    return jsonify({
        "output": {"width": s.width, "height": s.height},
        "drive": {"credentials": s.credentials_file.exists(), "signed_in": TOKEN_FILE.exists()},
        "stores": [{**asdict(st), "templates": [t.to_dict() for t in list_templates(s, st.code)]}
                   for st in s.stores],
    })


@app.get("/api/skus")
def skus():
    s = load_settings()
    try:
        return jsonify({"skus": make_source(s, request.args.get("source", "local")).list_skus()})
    except Exception as e:
        return err(e)


@app.get("/api/designs/<sku>")
def designs(sku):
    s = load_settings()
    try:
        return jsonify({"options": make_source(s, request.args.get("source", "local")).design_options(sku)})
    except Exception as e:
        return err(e)


@app.post("/api/jobs")
def create_job():
    s = load_settings()
    body = request.get_json(force=True)
    kind = body.get("kind", "render")
    stores = body.get("stores") or [st.code for st in s.stores]
    for c in stores:
        s.store(c)
    if kind == "render" and not body.get("skus"):
        return err("Pick at least one SKU")
    job = Job(kind=kind, skus=[str(x).strip() for x in body.get("skus", [])], stores=stores,
              source=body.get("source", "local"), upload=bool(body.get("upload", True)),
              design_choice=body.get("design_choice") or {})
    runner.submit(job)
    return jsonify(job.to_dict())


@app.get("/api/jobs/<job_id>")
def job(job_id):
    j = runner.get(job_id)
    return jsonify(j.to_dict()) if j else err("no such job", 404)


@app.get("/files/output/<path:p>")
def output_file(p):
    return send_from_directory(load_settings().output_dir, p)


@app.get("/files/template/<store>/<name>")
def template_file(store, name):
    s = load_settings()
    return send_from_directory(s.store_templates_dir(store), name)


@app.put("/api/templates/<store>/<name>")
def save_template(store, name):
    s = load_settings()
    try:
        t = get_template(s, store, name)
    except FileNotFoundError as e:
        return err(e, 404)
    body = request.get_json(force=True)
    corners = body.get("corners")
    if not (isinstance(corners, list) and len(corners) == 4):
        return err("Need exactly 4 corners")
    cal = Calibration(
        mode=body.get("mode", t.calibration.mode),
        corners=[[float(x), float(y)] for x, y in corners],
        shading=float(body.get("shading", t.calibration.shading)),
        texture=float(body.get("texture", t.calibration.texture)),
    )
    save_calibration(store, name, cal)
    return jsonify(get_template(s, store, name).to_dict())


@app.post("/api/templates/<store>/<name>/preview")
def preview(store, name):
    from PIL import Image
    s = load_settings()
    body = request.get_json(force=True)
    try:
        t = get_template(s, store, name)
        src = make_source(s, body.get("source", "local"))
        sku = body.get("sku") or (src.list_skus() or [None])[0]
        if not sku:
            return err("No designs available to preview with")
        with Image.open(src.fetch_design(sku, None, print)) as im:
            img = render(t, im.convert("RGBA"), (s.width // 3, s.height // 3))
    except Exception as e:
        return err(e)
    out = s.output_dir / ".previews" / store / f"{name}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=85)
    return jsonify({"url": f"/files/output/.previews/{store}/{name}.jpg", "sku": sku})


def main(host=None, port=None):
    import logging
    import flask.cli
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    flask.cli.show_server_banner = lambda *a, **k: None  # local tool: hide the "development server" banner
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = int(port or os.environ.get("PORT", 8765))
    print(f"Mockup Automator running at http://{host}:{port}"
          + (" (bearer auth ON)" if API_TOKEN else ""))
    app.run(host=host, port=port, threaded=True)
