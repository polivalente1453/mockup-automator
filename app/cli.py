"""Command line: python -m app.cli --help"""
from __future__ import annotations

import argparse
import sys
import time

from .config import load_settings
from .pipeline import Job, run_render, run_sync


def main(argv=None):
    p = argparse.ArgumentParser(prog="mockup")
    sub = p.add_subparsers(dest="cmd", required=True)

    sv = sub.add_parser("serve", help="start the web UI")
    sv.add_argument("--port", type=int, default=8765)
    sub.add_parser("login", help="sign in to Google Drive (opens browser once)")
    sub.add_parser("samples", help="create demo templates + designs to try offline")

    sy = sub.add_parser("sync", help="download blank templates from Drive")
    sy.add_argument("--store", action="append", help="store code (default: all)")

    ls = sub.add_parser("skus", help="list SKUs")
    ls.add_argument("--source", default="drive", choices=["drive", "local"])

    r = sub.add_parser("render", help="render mockups")
    r.add_argument("skus", nargs="+")
    r.add_argument("--store", action="append", help="store code (default: all)")
    r.add_argument("--source", default="drive", choices=["drive", "local"])
    r.add_argument("--no-upload", action="store_true")

    a = p.parse_args(argv)
    s = load_settings()
    stores = (getattr(a, "store", None) or [st.code for st in s.stores])

    if a.cmd == "serve":
        from .server import main as serve
        serve(port=a.port)
    elif a.cmd == "login":
        from .sources import drive_client
        drive_client(s)
        print("Signed in to Google Drive.")
    elif a.cmd == "samples":
        from .samples import make_samples
        make_samples(s)
    elif a.cmd == "skus":
        from .sources import make_source
        print("\n".join(make_source(s, a.source).list_skus()))
    elif a.cmd in ("sync", "render"):
        job = Job(kind=a.cmd, stores=stores, skus=getattr(a, "skus", []) or [],
                  source=getattr(a, "source", "drive"), upload=not getattr(a, "no_upload", False))
        t = time.time()
        (run_sync if a.cmd == "sync" else run_render)(job, s)
        print(f"Done in {time.time() - t:.0f}s: {job.done} items, {len(job.errors)} errors")
        sys.exit(1 if job.errors else 0)


if __name__ == "__main__":
    main()
