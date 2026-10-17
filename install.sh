#!/usr/bin/env bash
# Install the bigbrain skill into an agent skills directory.
#
# From a checkout:
#   ./install.sh                 -> ${CODEX_HOME:-$HOME/.codex}/skills/bigbrain
#   ./install.sh --claude        -> also install into ~/.claude/skills/bigbrain
#   ./install.sh --copy          -> copy instead of symlink
#   ./install.sh --uninstall     -> remove the skill (keeps the experience store)
#   ./install.sh --uninstall --purge  -> also remove ~/.bigbrain experience data
#   ./install.sh --dir PATH      -> any custom destination
#   ./install.sh --no-setup      -> skip the "Configure now?" prompt
#
# With no checkout (the curl|bash one-liner):
#   curl -fsSL https://raw.githubusercontent.com/kangchainx/bigbrain-skill/main/install.sh \
#     | BIGBRAIN_SRC=https://github.com/kangchainx/bigbrain-skill/archive/refs/heads/main.tar.gz bash
#
# The installer never touches an AGENTS.md, and never writes to any agent
# instruction or configuration file.  It places the skill, and nothing else.
# On an interactive terminal it offers to run the setup wizard, which writes
# only ~/.bigbrain/config.json.
#
# Local only: nothing is pushed or published.  The tarball download is the one
# network fetch, and it only happens when there is no local checkout.

set -euo pipefail

CLAUDE=0
MODE="symlink"
DEST=""
UNINSTALL=0
PURGE=0
SETUP=1
# When the script arrives on stdin (curl | bash) there is no BASH_SOURCE at all,
# which under `set -u` is an unbound variable rather than an empty one.
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
fi

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --claude)    CLAUDE=1; shift ;;
    --codex|--agents|--codex-legacy) shift ;;
    --dir)       DEST="${2:-}"; shift 2 ;;
    --copy)      MODE="copy"; shift ;;
    --symlink)   MODE="symlink"; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge)     PURGE=1; shift ;;
    --no-setup)  SETUP=0; shift ;;
    -h|--help)   usage 0 ;;
    *) echo "install.sh: unknown option $1" >&2; usage 1 ;;
  esac
done

# --------------------------------------------------------------------------
# Destinations
# --------------------------------------------------------------------------

PRIMARY_ROOT="${CODEX_HOME:-$HOME/.codex}"
PRIMARY_DIR="$PRIMARY_ROOT/skills"
AGENTS_DIR="$HOME/.agents/skills"
CLAUDE_DIR="$HOME/.claude/skills"

# --------------------------------------------------------------------------
# Uninstall
# --------------------------------------------------------------------------

if [ "$UNINSTALL" -eq 1 ]; then
  removed=0
  for dir in "$PRIMARY_DIR" "$AGENTS_DIR" "$CLAUDE_DIR"; do
    target="$dir/bigbrain"
    if [ -e "$target" ] || [ -L "$target" ]; then
      rm -rf "$target"
      echo "install.sh: removed $target"
      removed=$((removed + 1))
    fi
  done
  if [ -n "$DEST" ] && [ -e "$DEST/bigbrain" ]; then
    rm -rf "$DEST/bigbrain"
    echo "install.sh: removed $DEST/bigbrain"
    removed=$((removed + 1))
  fi
  [ "$removed" -eq 0 ] && echo "install.sh: nothing to remove"

  # The experience store is the user's own accumulated lessons, so it survives
  # an uninstall unless --purge is explicit.  It is never inside the repo.
  if [ "$PURGE" -eq 1 ]; then
    store="${BIGBRAIN_HOME:-$HOME/.bigbrain}"
    if [ -e "$store" ]; then
      rm -rf "$store"
      echo "install.sh: purged experience store $store"
    fi
  else
    store="${BIGBRAIN_HOME:-$HOME/.bigbrain}"
    [ -e "$store" ] && echo "install.sh: kept experience store $store (use --purge to remove)"
  fi
  exit 0
fi

# --------------------------------------------------------------------------
# Source: local checkout, or download the tarball
# --------------------------------------------------------------------------

SOURCE=""
TMPDIR_DL=""

cleanup() {
  [ -n "$TMPDIR_DL" ] && [ -d "$TMPDIR_DL" ] && rm -rf "$TMPDIR_DL"
  return 0
}
trap cleanup EXIT

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/SKILL.md" ]; then
  SOURCE="$SCRIPT_DIR"
else
  # curl | bash: there is no checkout on disk, so fetch one.
  URL="${BIGBRAIN_SRC:-}"
  if [ -z "$URL" ]; then
    echo "install.sh: no local SKILL.md and BIGBRAIN_SRC is not set." >&2
    echo "install.sh: set BIGBRAIN_SRC to a tarball URL, or run this from the skill directory." >&2
    exit 1
  fi
  command -v tar >/dev/null 2>&1 || { echo "install.sh: tar is required" >&2; exit 1; }
  TMPDIR_DL="$(mktemp -d "${TMPDIR:-/tmp}/bigbrain-install.XXXXXX")"
  echo "install.sh: fetching $URL"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$TMPDIR_DL/bigbrain.tar.gz"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMPDIR_DL/bigbrain.tar.gz" "$URL"
  else
    echo "install.sh: neither curl nor wget is available" >&2
    exit 1
  fi
  mkdir -p "$TMPDIR_DL/src"
  tar -xzf "$TMPDIR_DL/bigbrain.tar.gz" -C "$TMPDIR_DL/src"
  # The archive may or may not have a top-level directory.
  if [ -f "$TMPDIR_DL/src/SKILL.md" ]; then
    SOURCE="$TMPDIR_DL/src"
  else
    found="$(find "$TMPDIR_DL/src" -maxdepth 2 -name SKILL.md -print -quit 2>/dev/null || true)"
    [ -n "$found" ] || { echo "install.sh: no SKILL.md in the archive" >&2; exit 1; }
    SOURCE="$(dirname "$found")"
  fi

  # A symlink into a temp directory would dangle the moment this script exits
  # and the trap removes it, so a downloaded install must copy.  Only an
  # explicit --symlink overrides that, and it is almost never what you want.
  if [ "$MODE" = "symlink" ] && [ "${FORCE_SYMLINK:-0}" != "1" ]; then
    MODE="copy"
    echo "install.sh: downloading, so installing a copy (pass --symlink to override)"
  fi
fi

# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------

install_into() {
  dest_root="$1"
  target="$dest_root/bigbrain"
  mkdir -p "$dest_root"

  if [ -L "$target" ] && [ "$(readlink "$target" 2>/dev/null || true)" = "$SOURCE" ]; then
    echo "install.sh: already linked at $target"
    return 0
  fi
  if [ -e "$target" ] || [ -L "$target" ]; then
    rm -rf "$target"
  fi

  if [ "$MODE" = "copy" ]; then
    mkdir -p "$target"
    # Everything except tests, repo-only docs/CI, session state and the
    # user-level store.  The exclusions are deliberate: tests, docs/
    # and .github/ are for the checkout, .bigbrain holds
    # this workspace's session transcripts, and experience/ is the user's own.
    ( cd "$SOURCE" && tar -cf - \
        --exclude='./tests' \
        --exclude='./docs' \
        --exclude='./.github' \
        --exclude='./.bigbrain' \
        --exclude='./experience' \
        --exclude='./.git' \
        --exclude='./__pycache__' \
        --exclude='*.pyc' \
        . ) | ( cd "$target" && tar -xf - )
    echo "install.sh: copied to $target"
  else
    ln -s "$SOURCE" "$target"
    echo "install.sh: linked $target -> $SOURCE"
  fi
}

# Codex discovers both personal skill directories; install only once.
install_into "${DEST:-$PRIMARY_DIR}"

if [ "$CLAUDE" -eq 1 ] && [ "$PRIMARY_DIR" != "$CLAUDE_DIR" ]; then
  install_into "$CLAUDE_DIR"
fi

# The installed copy, for the commands printed below.
if [ -n "$DEST" ]; then
  SKILL_PATH="$DEST/bigbrain"
else
  SKILL_PATH="$PRIMARY_DIR/bigbrain"
fi
SETUP_CMD="python3 $SKILL_PATH/scripts/bigbrain_cli.py setup --web"
CHECK_CMD="python3 $SKILL_PATH/scripts/check_config.py"

echo
echo "Installed."

# Offer the setup wizard, but only to a person: a piped or scripted install
# (curl | bash, CI) must never block on a prompt.
configured=0
if [ "$SETUP" -eq 1 ] && [ -t 0 ] && [ -t 1 ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "install.sh: python3 not found; skipping setup."
  else
    printf 'Configure now? [Y/n] '
    answer=""
    read -r answer || answer="n"
    case "$answer" in
      ""|y|Y|yes|YES|Yes)
        if python3 "$SKILL_PATH/scripts/bigbrain_cli.py" setup; then
          configured=1
        else
          echo "install.sh: setup did not complete; run it again any time (below)."
        fi
        ;;
    esac
  fi
fi

echo
if [ "$configured" -eq 1 ]; then
  echo "Configured. Check it any time with:"
  echo "  $CHECK_CMD"
else
  echo "Next: configure the advisor endpoint in the Codex in-app browser:"
  echo "  $SETUP_CMD"
  echo "Open the printed setup_url in Codex and keep the process running until setup completes."
  echo "(or export BIGBRAIN_BASE_URL and BIGBRAIN_API_KEY), then:"
  echo "  $CHECK_CMD   # must print OK before use"
fi
echo
echo "Nothing was written to AGENTS.md or to any agent configuration file."
