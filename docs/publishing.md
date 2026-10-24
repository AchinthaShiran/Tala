# Publishing a release (maintainers)

The package is published to PyPI as **`tala-ai`**; users get the `tala` command.
Source: <https://github.com/AchinthaShiran/Tala>. Licence: Apache-2.0 (see `LICENSE` and `NOTICE`).

Uploads to PyPI are permanent: a version number can never be re-used. Rehearse on TestPyPI first.

## One-time setup

1. **Accounts.** Create accounts on <https://pypi.org> and <https://test.pypi.org>, and enable 2FA on both.
2. **GitHub environments.** In the repository settings, create two environments: `pypi` and `testpypi`.
   Optionally require your approval on `pypi` so a release cannot go out by accident.
3. **Trusted Publishing** (no API tokens). On each site open *Your projects, Publishing, Add a new pending
   publisher* and enter:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `tala-ai` |
   | Owner | `AchinthaShiran` |
   | Repository name | `Tala` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` (on TestPyPI: `testpypi`) |

4. **Public repository.** The installer links, the PyPI project links and the GitHub release downloads all
   require the repository to be **public** (Settings, then General, then Danger zone, then Change
   visibility). Do this before the first release. The installer URLs use the `main` branch.

## Releasing

1. Update `CHANGELOG.md` and bump `__version__` in `src/assistant/__init__.py` (the only place; the
   package version is read from it). Use semantic versioning.
2. Merge to `main` (pull request) and wait for CI (Windows, Linux, macOS; Python 3.11 to 3.14) to pass.
   Tags must point at a commit on `main`; the release workflow refuses anything else.
3. **Rehearse (recommended):** Actions, *release*, *Run workflow*. It builds and uploads to TestPyPI. Then,
   in a clean virtual environment:

   ```sh
   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple tala-ai
   tala --help && tala setup --check
   ```

4. **Release:** `git tag v3.0.0 && git push --tags`. The workflow re-runs the quality gates, checks that the
   tag equals the package version, builds, publishes to PyPI, and creates a GitHub release with the
   archives and the two installer scripts attached.

## Without CI (manual)

```sh
python -m pip install build twine
python -m build
twine check dist/*
twine upload --repository testpypi dist/*     # rehearsal
twine upload dist/*                           # real; needs a PyPI API token
```

## If a release is bad

You cannot delete or replace it. *Yank* it on PyPI (installers then skip it unless pinned) and publish the
next version (for example 3.0.1).

## What users run

```sh
pipx install tala-ai        # or: uv tool install tala-ai
pipx upgrade tala-ai        # later updates
```

or the one-line installers from the README. They need Python 3.11 or newer (any of 3.11 to 3.14 is
tested) and Ollama.
