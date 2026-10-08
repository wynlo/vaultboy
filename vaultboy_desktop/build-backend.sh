#!/usr/bin/env bash
# Build the Python backend into a single-file sidecar binary for Tauri.
# Output: vaultboy_desktop/src-tauri/binaries/vaultboy-backend-<target-triple>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/vaultboy_desktop"
VENV="$ROOT/.venv"
TRIPLE="$(rustc --print host-tuple 2>/dev/null || rustc -vV | sed -n 's/^host: //p')"

if [[ -z "$TRIPLE" ]]; then
  echo "error: could not determine Rust host triple (is rustc installed?)" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "error: $VENV not found; run ./vaultboy once to create it" >&2
  exit 1
fi

"$VENV/bin/pip" show pyinstaller >/dev/null 2>&1 || "$VENV/bin/pip" install pyinstaller

mkdir -p "$DESKTOP/src-tauri/binaries"
"$VENV/bin/pyinstaller" \
  --onefile \
  --noconfirm \
  --clean \
  --name vaultboy-backend \
  --distpath "$DESKTOP/dist" \
  --workpath "$DESKTOP/build" \
  --specpath "$DESKTOP" \
  --paths "$ROOT" \
  --add-data "$ROOT/vaultboy_app/web:vaultboy_app/web" \
  "$DESKTOP/backend_entry.py"

cp "$DESKTOP/dist/vaultboy-backend" "$DESKTOP/src-tauri/binaries/vaultboy-backend-$TRIPLE"
echo "Built sidecar: src-tauri/binaries/vaultboy-backend-$TRIPLE"
