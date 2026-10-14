# Mockup Automator — hosted deployment (NESA Host #3, linux/arm64 + amd64).
#
# State lives in VOLUMES mounted by the systemd unit (they die with the
# container otherwise — the render-worker interval-task lesson):
#   /app/config     settings.yaml, credentials.json, token.json (0600),
#                   calibration/ — writable: drive.py refreshes token.json
#   /app/templates  blank templates synced from Drive
#   /app/output     rendered JPEGs + .thumbs/.previews (transient — Drive
#                   holds the real copies; host retention timer prunes)
#   /app/designs    only used for the "local" source
#   /app/.cache     drive sync manifest cache
#
# Single process, Flask built-in server `threaded=True`. Do NOT swap in
# multi-worker gunicorn: pipeline.JobRunner is an in-memory single-thread
# queue — more than one process means split job dicts and duplicate
# renders. (`gunicorn -w 1 --threads 8` is the only acceptable upgrade.)
FROM python:3.12-slim

WORKDIR /app
# Non-root user; chown WORKDIR or pip/user writes EACCES (the exact trap
# the render-worker Dockerfile hit on this box, 2026-10-12).
RUN useradd -m -u 1001 worker && chown worker:worker /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

USER worker
ENV HOST=0.0.0.0
EXPOSE 8765

# cli.py's serve subcommand hardcodes --port default 8765 (overriding PORT
# env) — fine, the container always publishes 8765.
CMD ["python", "-m", "app.cli", "serve"]
