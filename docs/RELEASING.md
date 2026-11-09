# Releasing

How the built phases become a release. Nothing here runs by itself: each step happens after the hands-on review.

## The branches

Each `phase/<n>-<name>` branch starts from the one before it, so the last one contains all of them. Phases 0 to 18 are merged to `main` as one merge commit (`Merge phases 4 to 18`), and Phases 19 to 32 as a second (`Merge phases 19 to 32`, 2026-11-07). Only Phases 0 to 3 are tagged, `v0.0.1` to `v0.3.0`. Later phases start from `main`, stacked the same way.

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

## The next release: v1.22.0 (merged 2026-11-07, not tagged)

`main` holds Phases 0 to 32, with CI green. Before tagging, do the hands-on items you want covered. These are every item still open, in one list:

| Phase | Item |
|---|---|
| 19.5 | A reminder that falls due while the PC is locked: only "something is waiting" while locked, the reminder after unlock (the microphone closing while locked passed on 2026-11-09, H.4) |
| 20.5 | Clipboard history: "the second last thing I copied" with a real Ctrl+V (deferred by the user on 2026-11-09; needs `[clipboard] history = true` in local.toml) |
| 29 | "Send the clipboard to my phone" (deferred with 20.5); optionally an ntfy topic, then a phone reminder arrives there too (ADR-104) |
| 17 | A real WhatsApp call ("call Amma") and "hang up", with someone who expects it |
| 25 | `claude mcp add jarvis -- uv run --directory <repo> jarvis mcp serve`, then ask Claude Code for the weather |
| 27 | Spotify keys in `.env`; Docker Desktop running with a `[docker.projects]` entry; an `[ssh.profiles]` entry |
| 28 | "What's on my screen" on your real screen, by voice |
| 34 | `claude auth login` first (the CLI's sign-in had expired), then "tell Claude in jarvis to ..." with a yes to the edit by voice, "open Claude for jarvis", and "... so I can watch"; "run the jarvis code in Docker" with your own runner |
| 30 | `ui-demos`: "Use my microphone" with your own microphone; `/review-animations` on `chat.html` if you want that report |

Passed on 2026-11-09 (docs/HANDTESTS.md, H.1 to H.6): the mic button with voice on and "open Jarvis" by voice (32), "stop" during a spoken reply (24), the microphone closing while locked (19.5), pairing the phone, "find my phone", and a phone reminder (29). The phone reminder fix (ADR-104) is on `phase/33-hands-on-fixes`.

The merge is done. Then:

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
