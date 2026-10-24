#!/bin/sh
# One-line installer for macOS and Linux:
#   curl -fsSL https://raw.githubusercontent.com/AchinthaShiran/Tala/main/install.sh | sh
#
# Installs the app in its own isolated environment (uv or pipx), then starts the setup wizard.
# Rebranding: change the variables below (they mirror src/assistant/domain/branding.py).
APP_NAME="Tala"
COMMAND="tala"
ENV_PREFIX="TALA"
DEFAULT_PACKAGE="tala-ai"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

set -eu

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
env_value() { eval "printf '%s' \"\${$1:-}\""; }  # read an environment variable by name

# <PREFIX>_SOURCE overrides what to install (a PyPI name, a git URL or a local path).
SOURCE="$(env_value "${ENV_PREFIX}_SOURCE")"
SOURCE="${SOURCE:-$DEFAULT_PACKAGE}"
SKIP_SETUP="$(env_value "${ENV_PREFIX}_NO_SETUP")"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c "import sys; sys.exit(sys.version_info < ($MIN_PYTHON_MAJOR, $MIN_PYTHON_MINOR))" 2>/dev/null; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

say "Installing $APP_NAME ..."

if command -v uv >/dev/null 2>&1; then
  say "Using uv."
  uv tool install --force "$SOURCE"
  uv tool update-shell >/dev/null 2>&1 || true
elif command -v pipx >/dev/null 2>&1; then
  say "Using pipx."
  pipx install --force "$SOURCE"
  pipx ensurepath >/dev/null 2>&1 || true
else
  PYTHON="$(find_python)" || die "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR or newer is required. Install it from https://www.python.org/downloads/ and run this again."
  say "Installing pipx with $PYTHON ..."
  "$PYTHON" -m pip install --user --quiet pipx ||
    die "Could not install pipx (your system Python may be externally managed). Install pipx or uv with your package manager, then run this again."
  "$PYTHON" -m pipx ensurepath >/dev/null 2>&1 || true
  "$PYTHON" -m pipx install --force "$SOURCE"
fi

if ! command -v "$COMMAND" >/dev/null 2>&1; then
  say ""
  say "$APP_NAME is installed, but '$COMMAND' is not on your PATH yet."
  say "Open a new terminal (or add ~/.local/bin to PATH), then run: $COMMAND setup"
  exit 0
fi

say ""
if [ -n "$SKIP_SETUP" ]; then
  say "Installed. Run '$COMMAND setup' to configure it."
elif [ -r /dev/tty ]; then
  "$COMMAND" setup </dev/tty
else
  say "Installed. Run '$COMMAND setup' to configure it."
fi
