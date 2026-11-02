# Releasing

How the built phases become a release. Nothing here runs by itself: each step happens after the hands-on review.

## The branches

Each `phase/<n>-<name>` branch starts from the one before it, so the last one contains all of them. Phases 0 to 18 are merged to `main` as one merge commit (`Merge phases 4 to 18`). Only Phases 0 to 3 are tagged, `v0.0.1` to `v0.3.0`. Later phases start from `main`, stacked the same way.

## After the review

1. Fix what the review finds on the last phase branch, with CI green.
2. Merge it into `main` in one go. Because the branches are stacked, this brings every phase:

   ```powershell
   git checkout main
   git pull
   git merge --no-ff phase/<n>-<name> -m "Merge phases <first> to <n>"
   git push
   ```

3. Tag the release on `main` (the version in `pyproject.toml` and `src/jarvis/__init__.py`), and move the `[Unreleased]` notes in CHANGELOG.md under it first:

   ```powershell
   git tag -a v<version> -m "Jarvis <version>"
   git push origin v<version>
   ```

4. On GitHub, create a release from the tag with that version's CHANGELOG.md section as its notes.

Older versions (0.4.0 to 1.7.0) stay as entries in the changelog; tagging them afterwards is optional, on the last commit of each phase branch.

## Every release

- `uv run pytest`, `uv run pytest tests/e2e -m llm`, and `uv run python scripts/benchmark_tools.py` on a laptop with Ollama, so the scenarios and the benchmark reflect the real model.
- `.\install.ps1 -DryRun` on a clean checkout.
- The version in `pyproject.toml`, `src/jarvis/__init__.py`, CHANGELOG.md, and the README status line agree.
