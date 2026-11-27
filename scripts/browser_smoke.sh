#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
browser=${BROWSER_BIN:-chromium}
port=${MOTION_LAB_PORT:-8765}
output=$(mktemp)
server_log=$(mktemp)
profile_dir=$(mktemp -d)

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then kill "$server_pid" 2>/dev/null || true; fi
  rm -f "$output" "$server_log"
  rm -rf "$profile_dir"
}
trap cleanup EXIT

python3 -m http.server "$port" --bind 127.0.0.1 --directory "$repo_root" >"$server_log" 2>&1 &
server_pid=$!

for _ in {1..30}; do
  if curl --fail --silent "http://127.0.0.1:${port}/motion-lab/index.html" >/dev/null; then break; fi
  sleep 0.1
done

XDG_CACHE_HOME="$profile_dir/cache" XDG_CONFIG_HOME="$profile_dir/config" \
timeout 20s "$browser" --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --single-process --no-zygote \
  --disable-background-networking --disable-breakpad --disable-component-update \
  --disable-crash-reporter --disable-default-apps --disable-domain-reliability \
  --disable-extensions --disable-sync --no-first-run --no-default-browser-check \
  --user-data-dir="$profile_dir" \
  --virtual-time-budget=4000 --dump-dom \
  "http://127.0.0.1:${port}/motion-lab/index.html" >"$output"

grep -q 'data-lab-ready="true"' "$output"
grep -q '<strong id="indexedCount">142</strong>' "$output"
grep -q '<strong id="implementedCount">11</strong>' "$output"
grep -q '<strong id="testedCount">11</strong>' "$output"
grep -q '<strong id="usedCount">11</strong>' "$output"
printf 'Motion Lab browser load verified: indexed=142 implemented=11 tested=11 used=11\n'
