#!/usr/bin/env bash
# Install the reviewed, pinned tools this skill uses into a private folder outside any
# repository, and put short launchers for them in one bin folder.
#
#   scripts/bootstrap.sh [headroom] [serena] [repomix] [context-mode] [all]
#
# With no argument it installs Headroom only. Nothing is installed globally, no account
# or credential is touched, no proxy or server is started, and nothing is fetched at a
# floating version: Python tools come from hash-checked lock files, npm tools from
# package-lock.json with install scripts disabled, Node from a checksum written below.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${GAIE_TOOLS:-$HOME/.gaie-tools}"
NODE24_VERSION="v24.22.3"
NODE24_SHA256="4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb"  # linux-x64 tar.xz

mkdir -p "$TOOLS/bin"
chmod 700 "$TOOLS"

launcher() {  # name, command line
  printf '#!/usr/bin/env bash\nexec %s "$@"\n' "$2" > "$TOOLS/bin/$1"
  chmod 755 "$TOOLS/bin/$1"
}

python_tool() {  # name
  local name="$1" lock="$HERE/locks/$1.lock" home="$TOOLS/$1" want
  want="$(sha256sum "$lock" | cut -d' ' -f1)"
  if [ -x "$home/venv/bin/python" ] && [ "$(cat "$home/.lock-sha256" 2>/dev/null)" = "$want" ]; then
    echo "$name: already installed from this lock"
    return
  fi
  mkdir -p "$home"
  rm -rf "$home/venv"
  if command -v uv > /dev/null; then
    uv venv -q --python 3.13 "$home/venv" 2> /dev/null || uv venv -q "$home/venv"
    uv pip install -q --python "$home/venv/bin/python" --require-hashes -r "$lock"
  else
    python3 -m venv "$home/venv"
    "$home/venv/bin/pip" install -q --require-hashes -r "$lock"
  fi
  echo "$want" > "$home/.lock-sha256"
  echo "$name: installed"
}

node24() {
  local home="$TOOLS/node24" file="node-$NODE24_VERSION-linux-x64.tar.xz"
  [ -x "$home/bin/node" ] && return
  if [ "$(uname -sm)" != "Linux x86_64" ]; then
    echo "node24: only Linux x86_64 is scripted here; install Node $NODE24_VERSION yourself and put it at $home" >&2
    return 1
  fi
  mkdir -p "$home"
  (cd "$home" \
    && curl -fsS -O "https://nodejs.org/dist/$NODE24_VERSION/$file" \
    && echo "$NODE24_SHA256  $file" | sha256sum -c - > /dev/null \
    && tar -xJf "$file" --strip-components=1 \
    && rm -f "$file")
  echo "node24: installed $NODE24_VERSION"
}

npm_tool() {  # name, extra PATH entry or empty
  local name="$1" home="$TOOLS/$1"
  mkdir -p "$home"
  cp "$HERE/locks/$name/package.json" "$HERE/locks/$name/package-lock.json" "$home/"
  (cd "$home" && PATH="${2:+$2:}$PATH" npm ci --ignore-scripts --no-audit --no-fund > /dev/null)
  echo "$name: installed"
}

install() {
  case "$1" in
    headroom)
      python_tool headroom
      launcher hr "python3 '$HERE/scripts/hr.py'"
      launcher ast-grep "'$TOOLS/headroom/venv/bin/ast-grep'"
      ;;
    serena)
      python_tool serena
      SERENA_HOME="$TOOLS/serena/home" SERENA_USAGE_REPORTING=false \
        "$TOOLS/serena/venv/bin/serena" download-ls-dependencies python typescript > /dev/null 2>&1 \
        || echo "serena: language servers will be fetched on first use" >&2
      launcher sym "python3 '$HERE/scripts/sym.py'"
      ;;
    repomix)
      npm_tool repomix ""
      launcher repomix "'$TOOLS/repomix/node_modules/.bin/repomix'"
      ;;
    context-mode)
      node24
      npm_tool context-mode "$TOOLS/node24/bin"
      launcher context-mode-server "'$TOOLS/node24/bin/node' '$TOOLS/context-mode/node_modules/context-mode/server.mjs' --agent claude-code"
      ;;
    all)
      for each in headroom serena repomix context-mode; do install "$each"; done
      ;;
    *)
      echo "unknown tool: $1 (choose headroom, serena, repomix, context-mode or all)" >&2
      exit 2
      ;;
  esac
}

if [ "$#" -eq 0 ]; then set -- headroom; fi
for tool in "$@"; do install "$tool"; done
echo "launchers are in $TOOLS/bin; add it to PATH for this shell: export PATH=\"$TOOLS/bin:\$PATH\""
