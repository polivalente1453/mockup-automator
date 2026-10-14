"""Runs a batch: for each SKU, for each store, render N mockups, save locally, optionally upload."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from .config import Settings
from .planner import plan_store
from .render import render, save_jpeg, save_thumb
from .sources import make_source, sync_templates
from .templates import list_templates


@dataclass
class Job:
    kind: str                      # render | sync
    skus: List[str] = field(default_factory=list)
    stores: List[str] = field(default_factory=list)
    source: str = "local"
    upload: bool = True
    design_choice: Dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "queued"         # queued | running | done | failed
    done: int = 0
    total: int = 0
    log: List[str] = field(default_factory=list)
    outputs: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started: float = 0.0
    finished: float = 0.0

    def write(self, msg: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        print(msg, flush=True)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "id", "kind", "skus", "stores", "source", "status", "done", "total",
            "log", "outputs", "errors", "started", "finished")}


def output_name(sku: str, code: str, i: int) -> str:
    return f"{sku}_{code}_{i:02d}.jpg"


def run_render(job: Job, s: Settings) -> None:
    source = make_source(s, job.source)
    stores = [s.store(c) for c in job.stores]
    plans = {}
    for st in stores:
        tpls = list_templates(s, st.code)
        plans[st.code] = tpls
    job.total = len(job.skus) * sum(min(st.count, len([t for t in plans[st.code] if t.status == "ready"]))
                                    for st in stores)
    for sku in job.skus:
        try:
            design_path = source.fetch_design(sku, job.design_choice.get(sku), job.write)
            with Image.open(design_path) as im:
                design = im.convert("RGBA")
        except Exception as e:  # keep going with the other SKUs
            job.errors.append(f"{sku}: {e}")
            job.write(f"ERROR {sku}: {e}")
            continue
        for st in stores:
            try:
                chosen, warnings = plan_store(st, sku, plans[st.code])
                for w in warnings:
                    job.write(w)
                out_dir = s.output_dir / sku / st.code
                files = []
                for i, t in enumerate(chosen, 1):
                    img = render(t, design, (s.width, s.height))
                    name = output_name(sku, st.code, i)
                    path = out_dir / name
                    save_jpeg(img, path, s.quality, s.dpi)
                    save_thumb(img, s.output_dir / ".thumbs" / sku / st.code / name)
                    files.append(path)
                    job.outputs.append({"sku": sku, "store": st.code, "file": name, "template": t.name,
                                        "path": f"{sku}/{st.code}/{name}"})
                    job.done += 1
                job.write(f"{sku}/{st.code}: rendered {len(files)} mockups")
                if job.upload and files:
                    source.publish(sku, st, files, job.write)
            except Exception as e:
                job.errors.append(f"{sku}/{st.code}: {e}")
                job.write(f"ERROR {sku}/{st.code}: {e}")


def run_sync(job: Job, s: Settings) -> None:
    job.total = len(job.stores)
    for code in job.stores:
        try:
            sync_templates(s, s.store(code), job.write)
        except Exception as e:
            job.errors.append(f"{code}: {e}")
            job.write(f"ERROR {code}: {e}")
        job.done += 1


class JobRunner:
    """One worker thread: jobs run one at a time (the Drive client is not thread-safe)."""

    def __init__(self, settings_loader):
        self.load = settings_loader
        self.jobs: Dict[str, Job] = {}
        self.queue: List[Job] = []
        self.cv = threading.Condition()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, job: Job) -> Job:
        with self.cv:
            self.jobs[job.id] = job
            self.queue.append(job)
            self.cv.notify()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def _worker(self) -> None:
        while True:
            with self.cv:
                while not self.queue:
                    self.cv.wait()
                job = self.queue.pop(0)
            job.status, job.started = "running", time.time()
            try:
                s = self.load()
                (run_sync if job.kind == "sync" else run_render)(job, s)
                job.status = "failed" if job.errors and not job.outputs and job.kind == "render" else "done"
            except Exception as e:
                job.errors.append(str(e))
                job.write(f"ERROR: {e}")
                traceback.print_exc()
                job.status = "failed"
            job.finished = time.time()
            job.write(f"Finished in {job.finished - job.started:.0f}s")
