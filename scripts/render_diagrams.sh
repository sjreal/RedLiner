#!/usr/bin/env bash
# Render the Mermaid sources in docs/diagrams to SVG and PNG.
# Requires Node.js/npx and a local Chrome or Chromium.
set -euo pipefail

cd "$(dirname "$0")/.."
DIAGRAM_DIR="docs/diagrams"
CONFIG="${TMPDIR:-/tmp}/redliner-mermaid-puppeteer.json"
CHROME="${PUPPETEER_EXECUTABLE_PATH:-}"

if [[ -z "$CHROME" ]]; then
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "$(command -v google-chrome || true)" \
    "$(command -v chromium || true)" \
    "$(command -v chromium-browser || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      CHROME="$candidate"
      break
    fi
  done
fi

if [[ -z "$CHROME" ]]; then
  echo "Chrome/Chromium not found. Set PUPPETEER_EXECUTABLE_PATH." >&2
  exit 1
fi

printf '{"executablePath": "%s", "args": ["--no-sandbox", "--disable-setuid-sandbox"]}\n' \
  "$CHROME" > "$CONFIG"

for name in architecture runtime aws-deployment; do
  echo "Rendering $name"
  npx -y @mermaid-js/mermaid-cli \
    -p "$CONFIG" \
    -i "$DIAGRAM_DIR/$name.mmd" \
    -o "$DIAGRAM_DIR/$name.svg" \
    -b transparent \
    --size 1800
  npx -y @mermaid-js/mermaid-cli \
    -p "$CONFIG" \
    -i "$DIAGRAM_DIR/$name.mmd" \
    -o "$DIAGRAM_DIR/$name.png" \
    -b white \
    --size 1800 \
    -s 2
done

echo "Rendered diagrams in $DIAGRAM_DIR"
