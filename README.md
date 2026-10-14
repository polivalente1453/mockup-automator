# Mockup Automator

Generates Etsy doormat mockups (4200 × 2800 JPEG) for every store from one design per SKU.
Runs 100% locally on each team machine: rendering is Pillow/numpy, Drive access is the free Google Drive API.
No AI, no Claude/Codex tokens.

```
Doormat Designs/<SKU>/design.png          (input, Google Drive)
        │
        ▼   for each store: pick N of that store's blank templates (stable per SKU, varied across SKUs)
Bos Mockuplar/<Store>/1.png, 2.png …      (blank templates, synced once to templates/<CODE>/)
        │
        ▼   render 4200×2800, quality 92, 300 dpi
output/<SKU>/<CODE>/<SKU>_<CODE>_01.jpg   (local copy)
        │
        ▼   upload (creates the SKU folder, replaces same-name files on re-run)
Mockups/<Store>/<SKU>/<SKU>_<CODE>_01.jpg (Google Drive)
```

Stores are configured in `config/settings.yaml` (currently **HSH** Happy Step Home and **SNS** Signature Nesa Studio).
Adding store 3, 4, 5 = add a block there with its template folder and output folder IDs.

## Install & start (Mac or Windows)

Needs **Python 3.9+** ([python.org](https://www.python.org/downloads/); on Windows tick *"Add python.exe to PATH"*).
Put the project folder anywhere, then:

| | Mac | Windows |
|---|---|---|
| Start (double-click) | `start.command` | `start.bat` |
| Start (terminal) | `./start.sh` | `start.bat` |
| Add the `mockup` command | `./start.sh install` | `start.bat install` |
| Create mockups (terminal, asks SKUs/stores) | `./create-mockups.sh` | — |

The first start installs everything into `.venv/` inside the project folder (about a minute) and opens
http://127.0.0.1:8765. Running it again while it's already open just brings the page back up.

After `install`, type `mockup` in **any** terminal / Command Prompt, from any folder:

```bash
mockup                      # start the web UI
mockup render 334 335       # render from the command line
mockup sync                 # download blank templates from Drive
mockup setup                # reinstall dependencies
```

If you move the project folder, run `install` again from the new location.
Port 8765 busy? `PORT=9000 ./start.sh` (Mac) / `set PORT=9000 && start.bat` (Windows).

Without Drive credentials, the first start creates demo templates and two demo designs (`designs/DEMO-101.png`, `DEMO-102.png`)
so you can try everything with the **Local folder** source.

## Google Drive setup (once for the team, ~10 min)

1. https://console.cloud.google.com → create project "Mockup Automator".
2. *APIs & Services → Library* → enable **Google Drive API**.
3. *OAuth consent screen* → External, app name "Mockup Automator", add every team member's Google account under **Test users**.
4. *Credentials → Create credentials → OAuth client ID → Desktop app* → download JSON.
5. Save it as `config/credentials.json` on each team machine (same file for everyone).
6. Run `mockup login` (or `./start.sh login` / `start.bat login`) — each person signs in with their own Google account once
   (token saved to `config/token.json`). Then `mockup sync` to download the blank templates.

Each person's account needs edit access to the `Doormat Designs`, `Bos Mockuplar` and `Mockups` folders.

## Daily use

**Web UI** — Generate tab: pick source (Drive), filter/paste SKUs (`334, 335, 336`), tick stores, *Generate mockups*.
Thumbnails appear as they finish; click one to open the full 4200×2800 file.

**CLI**

```bash
mockup skus                          # list SKUs in Doormat Designs
mockup render 334 335                # all stores, upload to Drive
mockup render 334 --store HSH --no-upload
mockup sync                          # re-download templates after adding/changing them in Drive
```

## Templates

Blank templates live in Drive (`Bos Mockuplar/<Store>/`). `sync` downloads them once, scales them to output
size and keeps a manifest, so later syncs only fetch new/changed files (and remove deleted ones).

Two placement modes, chosen automatically per template:

| Mode | Template looks like | Setup needed |
|---|---|---|
| **window** | PNG with a transparent (or semi-transparent) hole where the mat is. Design is placed *under* the template, so the template's shadows/texture stay on top. | None — corners auto-detected |
| **corners** | Opaque photo of a blank mat | Templates tab → click the 4 mat corners once → Save. The mat's lighting and coir texture are blended into the design. |

Calibrations are saved in `config/calibration/<CODE>/<template>.json` — commit/share them so every machine renders identically.

## Combinations

Per store in `settings.yaml`:

- `count` — mockups per SKU (default 10, matching `_01 … _10`).
- `order: shuffle` — each SKU gets its own selection and order of that store's templates, so listings don't all share
  the same hero image. Deterministic: re-running a SKU reproduces the same set (safe to overwrite).
  `order: fixed` uses template order 1, 2, 3…
- `always_first: ["1.png"]` — pin specific templates to image #1, #2…

Stores never share templates (each reads its own folder), so each store's mockups are unique.

## Layout

```
launcher.py        cross-platform launcher: setup, start, `install` the mockup command
start.sh / start.command / start.bat   thin wrappers around launcher.py
app/config.py      settings.yaml loader
app/templates.py   template library, window auto-detect, calibration, sync downscaling
app/render.py      perspective warp + compositing, JPEG export
app/planner.py     which templates each store uses per SKU
app/drive.py       Google Drive v3 client (list, download, ensure folder, upload/replace)
app/sources.py     Drive vs local design sources, template sync
app/pipeline.py    batch jobs (one worker thread)
app/server.py      Flask web UI/API on 127.0.0.1:8765
web/index.html     UI
tests/             pytest -q tests
```

## Open questions / next steps

- Some SKU folders contain several PNGs (e.g. 334). Currently the newest image is used (`drive.design_pick`);
  confirm the rule, or add a naming convention like `<SKU>_design.png`.
- Verify the real HSH/SNS templates: are they "window" PNGs (transparent mat) or opaque photos needing corners?
- Parallel rendering across CPU cores for big batches (~0.4 s/image now, excluding upload).
- Optional: write a CSV of generated files per batch for Etsy listing upload.
