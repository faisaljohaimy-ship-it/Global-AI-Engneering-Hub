#!/usr/bin/env bash
# Install the reviewed priority tools outside the repository and run their functional tests.
#
#   activation/activate.sh [pydantic-ai] [inspect-ai] [promptfoo] [playwright-mcp] [chrome-devtools-mcp] [all]
#
# Python tools come from hash-checked locks, npm tools from package-lock.json with install
# scripts disabled. No provider key is read, no paid service is called, no browser is
# downloaded: the MCP servers are pointed at the browser named by BROWSER.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="${GAIE_TOOLS:-$HOME/.gaie-tools}/activation"
BROWSER="${BROWSER:-/opt/pw-browsers/chromium}"
OUT="${ACTIVATION_OUT:-$TOOLS/out}"
mkdir -p "$TOOLS" "$OUT"
failed=0

python_tool() {  # name
  local home="$TOOLS/$1" lock="$HERE/locks/$1/requirements.lock"
  [ -x "$home/venv/bin/python" ] && return 0
  mkdir -p "$home"
  if command -v uv > /dev/null; then
    uv venv -q --python 3.13 "$home/venv" 2> /dev/null || uv venv -q "$home/venv"
    uv pip install -q --python "$home/venv/bin/python" --require-hashes -r "$lock"
  else
    python3 -m venv "$home/venv" && "$home/venv/bin/pip" install -q --require-hashes -r "$lock"
  fi
}

npm_tool() {  # name
  local home="$TOOLS/$1"
  [ -d "$home/node_modules" ] && return 0
  mkdir -p "$home"
  cp "$HERE/locks/$1/package.json" "$HERE/locks/$1/package-lock.json" "$home/"
  (cd "$home" && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 PUPPETEER_SKIP_DOWNLOAD=1 npm ci --ignore-scripts --no-audit --no-fund > /dev/null)
}

offline() {  # run a command with no network where the kernel allows it
  if unshare -n true 2> /dev/null; then unshare -n "$@"; else "$@"; fi
}

run() {
  case "$1" in
    pydantic-ai)
      python_tool pydantic-ai \
        && PYDANTIC_AI_NO_BANNER=1 offline "$TOOLS/pydantic-ai/venv/bin/python" -I "$HERE/tests/pydantic_ai_typed_tool.py" > "$OUT/pydantic-ai.json"
      ;;
    inspect-ai)
      python_tool inspect-ai \
        && "$TOOLS/inspect-ai/venv/bin/python" -I "$HERE/tests/inspect_ai_mock_eval.py" > "$OUT/inspect-ai.json"
      ;;
    promptfoo)
      npm_tool promptfoo || return 1
      (cd "$HERE/tests/promptfoo" \
        && PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 PROMPTFOO_CONFIG_DIR="$OUT/promptfoo-home" \
          node "$TOOLS/promptfoo/node_modules/promptfoo/dist/src/main.js" eval -c promptfooconfig.yaml \
          --no-cache --no-write --no-progress-bar -o "$OUT/promptfoo.json" > "$OUT/promptfoo.log" 2>&1)
      # One assertion in the config fails on purpose, so the expected exit status is 100.
      [ "$?" -eq 100 ] && python3 "$HERE/tests/promptfoo/check.py" "$OUT/promptfoo.json"
      ;;
    playwright-mcp | chrome-devtools-mcp)
      npm_tool "$1" \
        && python3 "$HERE/tests/mcp_browser_probe.py" "$1" "$TOOLS" "$BROWSER" "$OUT/$1" > "$OUT/$1.json"
      ;;
    all)
      for each in pydantic-ai inspect-ai promptfoo playwright-mcp chrome-devtools-mcp; do run "$each"; done
      return 0
      ;;
    *)
      echo "unknown tool: $1" >&2
      return 2
      ;;
  esac
  local status=$?
  if [ "$status" -eq 0 ]; then echo "passed  $1"; else echo "FAILED  $1 (see $OUT)"; failed=1; fi
}

if [ "$#" -eq 0 ]; then set -- all; fi
for tool in "$@"; do run "$tool"; done
exit "$failed"
