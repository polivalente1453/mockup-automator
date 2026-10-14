"""Chooses which templates each store uses for a SKU.

- Stable: the same SKU always gets the same combination (re-runs overwrite cleanly).
- Varied: different SKUs get different combinations/hero images (shuffle mode).
- Unique per store: every store draws only from its own template folder.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from .config import Store
from .templates import Template


def plan_store(store: Store, sku: str, templates: List[Template]) -> Tuple[List[Template], List[str]]:
    warnings = []
    ready = [t for t in templates if t.status == "ready"]
    skipped = [t.name for t in templates if t.status != "ready"]
    if skipped:
        warnings.append(f"{store.code}: skipping uncalibrated templates {', '.join(skipped)}")
    if not ready:
        raise ValueError(f"{store.code}: no ready templates. Sync templates from Drive or calibrate them.")

    by_name = {t.name: t for t in ready}
    pinned = []
    for name in store.always_first:
        if name in by_name:
            pinned.append(by_name.pop(name))
        else:
            warnings.append(f"{store.code}: always_first template '{name}' not found or not ready")
    rest = list(by_name.values())
    if store.order == "shuffle":
        random.Random(f"{store.code}:{sku}").shuffle(rest)

    chosen = (pinned + rest)[: store.count]
    if len(chosen) < store.count:
        warnings.append(f"{store.code}: only {len(chosen)} ready templates, wanted {store.count}")
    return chosen, warnings
