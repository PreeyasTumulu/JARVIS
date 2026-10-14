"""File guard, index and search, readers, and the file tools, inside a temporary folder."""

from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.config import FilesSettings
from jarvis.storage.db import Database
from jarvis.tools.base import Risk, ToolError
from jarvis.tools.files import selection
from jarvis.tools.files.guard import FileGuard
from jarvis.tools.files.index import EverythingSearch, FileIndex, query_words
from jarvis.tools.files.readers import read_document
from tests.conftest import FakeChannel, FakeDesktop, MakeApp, reply

CFG = FilesSettings(
    blocked_patterns=[".env", "*.pem", "*secret*"],
    blocked_extensions=[".reg"],
    confirm_extensions=[".exe", ".bat"],
    skip_dirs=["node_modules", ".git"],
)


def make_tree(root: Path) -> None:
    files = {
        "Resume_Preeyas_2026.pdf": b"%PDF",
        "notes/meeting notes.txt": b"agenda",
        "Projects/jarvis/README.md": b"# Jarvis",
        "Projects/jarvis/node_modules/pkg/resume.js": b"skip me",
        ".git/config": b"skip",
        "Old/resume_2019.docx": b"old",
        "setup.exe": b"MZ",
        "tweak.reg": b"REGEDIT4",
        "api_secret.txt": b"k",
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    old = time.time() - 400 * 86400
    os.utime(root / "Old/resume_2019.docx", (old, old))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = (tmp_path / "allowed").resolve()
    folder.mkdir()
    make_tree(folder)
    return folder


def test_guard_rules(root: Path, tmp_path: Path) -> None:
    guard = FileGuard(CFG, roots=[root])
    assert guard.check(str(root / "notes/meeting notes.txt")).risk is Risk.SAFE
    assert guard.check(str(root / ".." / "elsewhere.txt")).risk is Risk.BLOCKED  # ".." escape
    assert guard.check("C:/Windows/win.ini").risk is Risk.BLOCKED
    assert guard.check(str(root / "api_secret.txt")).risk is Risk.BLOCKED
    assert guard.check(str(root / "setup.exe"), opening=True).risk is Risk.CONFIRM
    assert guard.check(str(root / "setup.exe")).risk is Risk.SAFE  # reading is fine
    assert guard.check(str(root / "tweak.reg"), opening=True).risk is Risk.BLOCKED
    with pytest.raises(ToolError, match="not a full path"):
        guard.check("notes.txt")


async def test_index_search_ranks_and_skips_junk(root: Path) -> None:
    index = FileIndex(Database(":memory:"), FileGuard(CFG, roots=[root]), CFG)
    hits = await index.search("my resume")
    names = [hit.name for hit in hits]
    assert names[0] == "Resume_Preeyas_2026.pdf"  # newer file wins
    assert "resume_2019.docx" in names
    assert "resume.js" not in names  # node_modules is skipped
    folders = await index.search("projects", kind="folder")
    assert folders[0].is_dir
    assert folders[0].name == "Projects"
    assert (await index.search("meting notes"))[0].name == "meeting notes.txt"  # typo


async def test_index_finds_by_exact_name_and_rebuilds_when_stale(root: Path) -> None:
    db = Database(":memory:")
    index = FileIndex(db, FileGuard(CFG, roots=[root]), CFG)
    assert await index.find_by_name("readme.md") == [str(root / "Projects/jarvis/README.md")]
    (root / "new plan.txt").write_text("x", encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(hours=CFG.index_max_age_hours + 1)).isoformat()
    db.execute("UPDATE index_meta SET built_at = ? WHERE name = 'files'", (old,))
    await index.ensure_ready()  # stale: rebuild in the background
    assert index._rebuild_task is not None
    await index._rebuild_task
    assert (await index.search("new plan"))[0].name == "new plan.txt"


async def test_everything_results_are_filtered_by_the_guard(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_resume.pdf"
    outside.write_bytes(b"x")

    class FakeEverything(EverythingSearch):
        def search(self, words: list[str], limit: int = 300) -> list[Path]:
            return [outside, root / "Resume_Preeyas_2026.pdf", root / "api_secret.txt"]

    index = FileIndex(
        Database(":memory:"), FileGuard(CFG, roots=[root]), CFG, FakeEverything(Path("es"))
    )
    names = [hit.name for hit in await index.search("resume")]
    assert names == ["Resume_Preeyas_2026.pdf"]
    assert index.backend == "everything"


def test_query_words_drop_filler() -> None:
    assert query_words("open my latest resume file") == ["resume"]
    assert query_words("the file") == ["the", "file"]


def test_readers(tmp_path: Path) -> None:
    text = tmp_path / "a.txt"
    text.write_text("hello world " * 100, encoding="utf-16")
    doc = read_document(text, max_chars=50, max_bytes=10_000)
    assert doc.text.startswith("hello world")
    assert doc.truncated

    docx = tmp_path / "cv.docx"
    body = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Preeyas</w:t></w:r></w:p><w:p><w:r><w:t>Engineer</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", body)
    assert read_document(docx, max_chars=100, max_bytes=10_000).text == "Preeyas\nEngineer"

    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolError, match="can't read"):
        read_document(binary, max_chars=100, max_bytes=10_000)
    with pytest.raises(ToolError, match="too large"):
        read_document(text, max_chars=100, max_bytes=10)


def test_pdf_without_text_layer(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "scan.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(ToolError, match="no text layer"):
        read_document(path, max_chars=100, max_bytes=100_000)


async def test_find_then_open_through_the_agent(make_app: MakeApp, desktop: FakeDesktop) -> None:
    h = make_app()
    make_tree(h.files_root)
    target = str(h.files_root / "Resume_Preeyas_2026.pdf")
    h.llm._script = [
        reply("", ("find_file", {"query": "resume"})),
        reply("", ("open_file", {"path": target})),
        reply("Opened your resume."),
    ]
    await h.app.agent.run_turn("open my resume")
    found = json.loads(h.audit()[0]["result_json"])
    assert found[0]["path"] == target
    assert desktop.opened_files == [target]


async def test_invented_paths_are_recovered_or_explained(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    h = make_app()
    make_tree(h.files_root)
    h.llm._script = [
        reply("", ("read_file", {"path": "/path/to/my/jarvis/readme.md"})),
        reply("", ("open_file", {"path": "resume"})),
        reply("Here you go."),
    ]
    await h.app.agent.run_turn("read the jarvis readme, then open my resume")
    first, second = h.audit()
    assert json.loads(first["args_json"])["path"].endswith("README.md")  # clear winner: used
    assert first["ok"] == 1
    assert second["ok"] == 0  # two resumes are close: the model gets real paths to choose from
    assert "Closest matches" in second["error"]
    assert "Resume_Preeyas_2026.pdf" in second["error"]


async def test_risky_files_are_blocked_or_confirmed(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    h = make_app(channel=FakeChannel(confirm=False))
    make_tree(h.files_root)
    h.llm._script = [
        reply(
            "",
            ("read_file", {"path": str(h.files_root / "api_secret.txt")}),
            ("open_file", {"path": str(h.files_root / "setup.exe")}),
            ("read_file", {"path": "C:/Windows/win.ini"}),
        ),
        reply("Some of that was not allowed."),
    ]
    await h.app.agent.run_turn("do risky things")
    decisions = [row["decision"] for row in h.audit()]
    assert decisions == ["blocked", "denied", "blocked"]
    assert desktop.opened_files == []


async def test_get_selected_file_from_explorer(
    make_app: MakeApp, desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_app()
    make_tree(h.files_root)
    desktop.add("Windows Terminal", "WindowsTerminal")
    explorer = desktop.add("Downloads", "explorer", "CabinetWClass")
    chosen = str(h.files_root / "notes" / "meeting notes.txt")
    monkeypatch.setattr(
        selection, "explorer_windows", lambda: {explorer.hwnd: (str(h.files_root), [chosen])}
    )
    h.llm._script = [reply("", ("get_selected_file", {})), reply("It's your meeting notes.")]
    await h.app.agent.run_turn("what is this file")
    data = json.loads(h.audit()[0]["result_json"])
    assert data["source"] == "explorer"
    assert data["files"] == [{"path": chosen, "allowed": True}]


async def test_get_selected_file_from_vscode_title(
    make_app: MakeApp, desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_app()
    make_tree(h.files_root)
    desktop.add("\u25cf README.md - jarvis - Visual Studio Code", "Code")
    monkeypatch.setattr(selection, "explorer_windows", dict)
    h.llm._script = [reply("", ("get_selected_file", {})), reply("ok")]
    await h.app.agent.run_turn("open this file")
    data = json.loads(h.audit()[0]["result_json"])
    assert data["source"] == "vscode"
    assert data["files"][0]["path"].endswith("README.md")


async def test_get_selected_file_with_nothing_open(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selection, "explorer_windows", dict)
    h = make_app([reply("", ("get_selected_file", {})), reply("Which file?")])
    await h.app.agent.run_turn("read this file")
    assert "Ask the user" in h.audit()[0]["error"]


async def test_missing_paths_outside_the_allowlist_are_blocked_not_searched(
    make_app: MakeApp,
) -> None:
    h = make_app()
    make_tree(h.files_root)
    missing = "C:/Definitely/Not/Here/Resume_Preeyas_2026.pdf"  # name exists inside, path does not
    h.llm._script = [reply("", ("read_file", {"path": missing})), reply("Not allowed.")]
    await h.app.agent.run_turn("read that file")
    (row,) = h.audit()
    assert row["decision"] == "blocked"
