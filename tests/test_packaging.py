"""Publishing readiness: metadata, licence files, version source, CI and workflow consistency."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

from assistant import __version__

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
PROJECT = PYPROJECT["project"]
REPO_URL = "https://github.com/AchinthaShiran/Tala"


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_core_metadata():
    assert PROJECT["name"] == "tala-ai"
    assert PROJECT["requires-python"] == ">=3.11"
    assert PROJECT["readme"] == "README.md" and PROJECT["description"]
    assert PROJECT["authors"] and PROJECT["authors"][0]["name"]
    assert "tala" in PROJECT["scripts"] and PROJECT["scripts"]["tala"].startswith("assistant.")
    assert len(PROJECT["keywords"]) >= 5


def test_project_urls_point_at_the_repository():
    urls = PROJECT["urls"]
    assert {"Homepage", "Source", "Issues", "Changelog"} <= set(urls)
    assert all(url.startswith(REPO_URL) for url in urls.values()), urls


def test_license_is_apache_2_and_files_are_present():
    assert PROJECT["license"] == "Apache-2.0"
    assert set(PROJECT["license-files"]) == {"LICENSE", "NOTICE"}
    licence = text("LICENSE")
    assert "Apache License" in licence and "Version 2.0, January 2004" in licence
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in licence
    notice = text("NOTICE")
    assert "Copyright" in notice and "Achintha Bandara" in notice
    assert "Apache License, Version 2.0" in notice


def test_no_deprecated_license_classifier_alongside_an_spdx_expression():
    assert not [c for c in PROJECT["classifiers"] if c.startswith("License ::")]


def test_version_has_a_single_source():
    assert "version" not in PROJECT and PROJECT["dynamic"] == ["version"]
    assert PYPROJECT["tool"]["hatch"]["version"]["path"] == "src/assistant/__init__.py"
    assert re.fullmatch(r"\d+\.\d+\.\d+([abrc.\-+\w]*)?", __version__)


def test_classifiers_cover_exactly_the_python_versions_ci_tests():
    ci = yaml.safe_load(text(".github/workflows/ci.yml"))
    tested = [str(v) for v in ci["jobs"]["test"]["strategy"]["matrix"]["python"]]
    declared = [
        c.rsplit(" ", 1)[1]
        for c in PROJECT["classifiers"]
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    ]
    assert sorted(tested) == sorted(declared)
    floor = PROJECT["requires-python"].removeprefix(">=")
    assert min(tested, key=lambda v: tuple(map(int, v.split(".")))) == floor


def test_every_workflow_is_valid_yaml_with_jobs():
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        assert data["jobs"], workflow.name


def test_release_workflow_uses_trusted_publishing_not_stored_tokens():
    raw = text(".github/workflows/release.yml")
    data = yaml.safe_load(raw)
    jobs = data["jobs"]
    assert jobs["publish-pypi"]["permissions"]["id-token"] == "write"
    assert jobs["publish-pypi"]["environment"] == "pypi"
    assert jobs["publish-testpypi"]["environment"] == "testpypi"
    assert "password:" not in raw and "PYPI_API_TOKEN" not in raw
    assert data[True]["push"]["tags"] == ["v*"]  # YAML parses the key `on` as True
    # Publishing only ever follows the quality gates.
    assert "build" in jobs["publish-pypi"]["needs"] and "build" in jobs["publish-testpypi"]["needs"]


def test_release_refuses_tags_that_are_not_on_main():
    steps = yaml.safe_load(text(".github/workflows/release.yml"))["jobs"]["build"]["steps"]
    guard = next(s for s in steps if s.get("name") == "Tag must be on main")
    assert "merge-base --is-ancestor" in guard["run"] and "origin/main" in guard["run"]
    assert steps[0]["with"]["fetch-depth"] == 0


def test_installers_install_the_published_package_name():
    assert f'DEFAULT_PACKAGE="{PROJECT["name"]}"' in text("install.sh")
    assert f'$DefaultPackage = "{PROJECT["name"]}"' in text("install.ps1")


def test_docs_have_no_placeholder_urls_and_use_the_real_repository():
    for rel in ("README.md", "docs/setup.md", "docs/publishing.md", "install.sh", "install.ps1"):
        assert "<URL-of" not in text(rel), rel
    assert "raw.githubusercontent.com/AchinthaShiran/Tala/main/install.sh" in text("README.md")
    assert "pipx install tala-ai" in text("README.md")
    assert "Apache License, Version 2.0" in text("README.md")


def test_source_archive_excludes_planning_notes_and_ci_config():
    sdist = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/src" in sdist and "/LICENSE" in sdist and "/NOTICE" in sdist
    assert not [p for p in sdist if p.startswith(("/.10x", "/.github"))]
