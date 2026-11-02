# Releasing

How the built phases become a release. Nothing here runs by itself: each step happens after the hands-on review.

## The branches

Phases 4 to 16 are stacked: each `phase/<n>-<name>` branch starts from the one before it, so the last one (`phase/16-release-polish`) contains all of them. Phases 0 to 3 are on `main`, tagged `v0.0.1` to `v0.3.0`.

## After the review

1. Fix what the review finds on the last branch (`phase/16-release-polish`), with CI green.
2. Merge it into `main` in one go. Because the branches are stacked, this brings every phase:

   ```powershell
   git checkout main
   git pull
   git merge --no-ff phase/16-release-polish -m "Merge phases 4 to 16"
   git push
   ```

3. Tag the release on `main` (the version in `pyproject.toml` and `src/jarvis/__init__.py`), and move the `[Unreleased]` notes in CHANGELOG.md under it first:

   ```powershell
   git tag -a v1.6.0 -m "Jarvis 1.6.0"
   git push origin v1.6.0
   ```

4. On GitHub, create a release from the tag with that version's CHANGELOG.md section as its notes.

Older versions (0.4.0 to 1.5.0) stay as entries in the changelog; tagging them afterwards is optional, on the last commit of each phase branch.

## Every release

- `uv run pytest`, `uv run pytest tests/e2e -m llm`, and `uv run python scripts/benchmark_tools.py` on a laptop with Ollama, so the scenarios and the benchmark reflect the real model.
- `.\install.ps1 -DryRun` on a clean checkout.
- The version in `pyproject.toml`, `src/jarvis/__init__.py`, CHANGELOG.md, and the README status line agree.
