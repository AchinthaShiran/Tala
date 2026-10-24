"""The product name lives in one module; nothing else may hard-code it."""

from __future__ import annotations

import re
from pathlib import Path

from assistant.domain import branding

SRC = Path(__file__).resolve().parent.parent / "src" / "assistant"


def test_derived_names_follow_the_constants():
    assert f"{branding.ENV_PREFIX}_HOME" == branding.HOME_ENV
    assert f"{branding.ENV_PREFIX}__" == branding.SETTINGS_ENV_PREFIX
    assert branding.cmd("packs", "trust") == f"{branding.COMMAND} packs trust"


def test_source_code_does_not_hard_code_the_product_identity():
    identity = [
        branding.APP_NAME,
        branding.APP_SLUG,
        branding.COMMAND,
        branding.ENV_PREFIX,
        branding.PROJECT_DIR,
    ]
    pattern = re.compile("|".join(re.escape(x) for x in identity if x), re.IGNORECASE)
    offenders = []
    for file in SRC.rglob("*.py"):
        if file.name == "branding.py":
            continue
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{file.relative_to(SRC)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_the_cli_uses_the_configured_command_and_name(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from assistant.cli import app as cli_app

    monkeypatch.setenv(branding.HOME_ENV, str(tmp_path))
    result = CliRunner().invoke(cli_app.app, ["--help"])
    assert branding.TAGLINE.split(":")[0] in result.output
