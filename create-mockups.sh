#!/bin/sh
# Mac/Linux: create mockups from the terminal without opening the web UI.
#   ./create-mockups.sh                 ask for SKUs, stores and upload
#   ./create-mockups.sh 334 335         render these SKUs for all stores and upload to Drive
# Extra options go to `render` (e.g. --store HSH --no-upload --source local).
cd "$(dirname "$0")"

if [ $# -gt 0 ]; then
  exec ./start.sh render "$@"
fi

printf "SKUs (e.g. 334 335 336): "
read -r SKUS
SKUS=$(printf "%s" "$SKUS" | tr ',' ' ')
[ -n "$SKUS" ] || { echo "No SKUs given."; exit 1; }

printf "Stores (e.g. HSH SNS, Enter = all): "
read -r STORES
STORE_ARGS=""
for st in $(printf "%s" "$STORES" | tr ',' ' '); do
  STORE_ARGS="$STORE_ARGS --store $st"
done

printf "Design source: [d]rive or [l]ocal designs/ folder (Enter = drive): "
read -r SRC
case "$SRC" in l*|L*) SOURCE=local ;; *) SOURCE=drive ;; esac

printf "Upload results to Google Drive? [Y/n]: "
read -r UP
case "$UP" in n*|N*) UPLOAD="--no-upload" ;; *) UPLOAD="" ;; esac

# shellcheck disable=SC2086  # word splitting is intended for the lists above
exec ./start.sh render $SKUS $STORE_ARGS --source "$SOURCE" $UPLOAD
