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

## The next release: v1.22.0 (prepared 2026-11-07)

`phase/32-chat-ui` holds Phases 19 to 32 (stacked on `main`, which has 0 to 18). CI is green on it. Before merging, do the hands-on items you want covered. These are every item still open, in one list:

| Phase | Item |
|---|---|
| 19.5 | Lock the PC while Jarvis runs: the microphone closes, and nothing private is said aloud |
| 20.5 | Clipboard history: "the second last thing I copied" with a real Ctrl+V |
| 17 | A real WhatsApp call ("call Amma") and "hang up", with someone who expects it |
| 24 | A real voice turn with streamed speech, and "stop" during it |
| 25 | `claude mcp add jarvis -- uv run --directory <repo> jarvis mcp serve`, then ask Claude Code for the weather |
| 27 | Spotify keys in `.env`; Docker Desktop running with a `[docker.projects]` entry; an `[ssh.profiles]` entry |
| 28 | "What's on my screen" on your real screen, by voice |
| 29 | Pair the phone in KDE Connect, then "find my phone", "send the clipboard to my phone", and a phone reminder; optionally an ntfy topic |
| 30 | `ui-demos`: "Use my microphone" with your own microphone; `/review-animations` on `chat.html` if you want that report |
| 32 | `jarvis serve --tray`, then `jarvis ui`: the real window, the mic button with voice on, and "open Jarvis" by voice |

Then:

```powershell
uv run pytest
uv run python scripts/check_personal.py
git checkout main
git pull
git merge --no-ff phase/32-chat-ui -m "Merge phases 19 to 32"
git push
```

Move the `[Unreleased]` section of CHANGELOG.md under `## [1.22.0] - <date>` and add its compare link, commit, and then:

```powershell
git tag -a v1.22.0 -m "Jarvis 1.22.0"
git push origin v1.22.0
```

Create the GitHub release from the tag, with that CHANGELOG section as the notes and `docs/demo.gif` at the top.

## Every release

- `uv run pytest`, `uv run pytest tests/e2e -m llm`, and `uv run python scripts/benchmark_tools.py` on a laptop with Ollama, so the scenarios and the benchmark reflect the real model.
- `.\install.ps1 -DryRun` on a clean checkout.
- `uv run python scripts/check_personal.py` and `scripts/check_dashes.py` pass (CI runs both).
- The version in `pyproject.toml`, `src/jarvis/__init__.py`, CHANGELOG.md, and the README status line agree.
