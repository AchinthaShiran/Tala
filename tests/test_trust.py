from __future__ import annotations

from pathlib import Path

from assistant.bootstrap import pack_roots, untrusted_project_packs
from assistant.config import AppPaths, Settings, TrustStore
from assistant.domain.branding import PROJECT_DIR


def project_with_pack(root: Path) -> Path:
    packs = root / PROJECT_DIR / "packs"
    packs.mkdir(parents=True)
    (packs / "x.yaml").write_text("pack: x\ntools: []\n", encoding="utf-8")
    return root


def labels(paths: AppPaths, project: Path) -> list[str]:
    return [r.label for r in pack_roots(paths, Settings(), project)]


def test_project_packs_are_ignored_until_trusted(tmp_path: Path):
    paths = AppPaths(tmp_path / "c", tmp_path / "d")
    project = project_with_pack(tmp_path / "repo")

    assert "project" not in labels(paths, project)
    assert untrusted_project_packs(paths, project) == project / PROJECT_DIR / "packs"

    TrustStore(paths.trusted_projects).trust(project)
    assert "project" in labels(paths, project)
    assert untrusted_project_packs(paths, project) is None


def test_revoke_and_listing(tmp_path: Path):
    store = TrustStore(tmp_path / "t.json")
    store.trust(tmp_path)
    assert store.is_trusted(tmp_path) and store.all() == [str(tmp_path.resolve())]
    assert store.revoke(tmp_path) and not store.is_trusted(tmp_path)
    assert not store.revoke(tmp_path)


def test_corrupt_trust_file_means_nothing_is_trusted(tmp_path: Path):
    path = tmp_path / "t.json"
    path.write_text("{not json", encoding="utf-8")
    assert not TrustStore(path).is_trusted(tmp_path)


def test_directory_without_project_packs_has_no_warning(tmp_path: Path):
    assert untrusted_project_packs(AppPaths(tmp_path / "c", tmp_path / "d"), tmp_path) is None
