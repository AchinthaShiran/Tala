"""Single source of truth for everything that carries the product name.

To rename the product, change the constants below, then:
  1. rename the console script in ``pyproject.toml`` (``[project.scripts]``) and the project name;
  2. search-replace the old name in the Markdown docs (they cannot read these constants).
Nothing else in the code base hard-codes the name, the command, the environment variables or the
folder names (``tests/test_branding.py`` enforces that).
"""

from __future__ import annotations

APP_NAME = "Tala"  # display name shown in banners and help
APP_SLUG = "tala"  # config/data folder name
COMMAND = "tala"  # CLI command typed by the user
ENV_PREFIX = "TALA"  # environment variables: TALA_HOME, TALA__SECTION__KEY
PROJECT_DIR = ".tala"  # per-project folder (holds packs/)
TAGLINE = "Local PC assistant: chat in natural language, extend it with YAML packs."

HOME_ENV = f"{ENV_PREFIX}_HOME"  # relocates config and data
SETTINGS_ENV_PREFIX = f"{ENV_PREFIX}__"  # prefix for settings overrides


def cmd(*args: str) -> str:
    """A command line as the user would type it, for hints and error messages."""
    return " ".join((COMMAND, *args))
