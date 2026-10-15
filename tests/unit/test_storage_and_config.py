from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from jarvis.config import ConfigError, ProviderSettings, deep_merge, load_settings
from jarvis.core.prompts import system_prompt, wrap_untrusted
from jarvis.storage.db import MIGRATIONS, Database, healthy
from jarvis.storage.repositories import AuditEntry, AuditLog, Preferences
from tests.conftest import REPO


def test_migrations_apply_once(tmp_path: Path) -> None:
    path = tmp_path / "j.db"
    Database(path).close()
    db = Database(path)  # reopening must not re-run migrations
    assert db.version == len(MIGRATIONS)
    db.close()


def test_audit_roundtrip_truncates_big_results() -> None:
    db = Database(":memory:")
    log = AuditLog(db)
    log.record(
        AuditEntry(
            session_id="s",
            turn_id="t",
            tool="web_search",
            decision="auto",
            ok=True,
            args={"query": "x"},
            result={"blob": "a" * 5000},
        )
    )
    (row,) = log.recent()
    assert row["args_json"] == '{"query": "x"}'
    assert row["result_json"].endswith("...(truncated)")


def test_preferences_upsert() -> None:
    prefs = Preferences(Database(":memory:"))
    assert prefs.get("voice", "default") == "default"
    prefs.set("voice", {"rate": 1})
    prefs.set("voice", {"rate": 2})
    assert prefs.get("voice") == {"rate": 2}


def _config_dir(tmp_path: Path, local: str | None = None) -> Path:
    folder = tmp_path / "config"
    folder.mkdir()
    shutil.copy(REPO / "config" / "jarvis.toml", folder / "jarvis.toml")
    if local is not None:
        (folder / "local.toml").write_text(local, encoding="utf-8")
    return folder


def test_local_overrides_merge(tmp_path: Path) -> None:
    folder = _config_dir(
        tmp_path, '[llm.providers.local]\nmodel = "small"\n[safety]\napp_allowlist = ["A"]\n'
    )
    settings = load_settings(folder, env_file=tmp_path / "none.env")
    assert settings.llm.active().model == "small"
    assert settings.llm.active().base_url.startswith("http://localhost")  # kept from defaults
    assert settings.safety.app_allowlist == ["A"]  # lists replace


def test_unknown_keys_fail_loudly(tmp_path: Path) -> None:
    folder = _config_dir(tmp_path, "[agent]\nmax_iteratoins = 3\n")
    with pytest.raises(ConfigError, match="max_iteratoins"):
        load_settings(folder, env_file=tmp_path / "none.env")


def test_missing_api_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_TEST_KEY", raising=False)
    provider = ProviderSettings(base_url="https://x", model="m", api_key_env="JARVIS_TEST_KEY")
    with pytest.raises(ConfigError, match="JARVIS_TEST_KEY"):
        provider.api_key()
    monkeypatch.setenv("JARVIS_TEST_KEY", "secret")
    assert provider.api_key() == "secret"


def test_deep_merge() -> None:
    assert deep_merge({"a": {"b": 1, "c": 2}, "l": [1]}, {"a": {"b": 3}, "l": [2]}) == {
        "a": {"b": 3, "c": 2},
        "l": [2],
    }


def test_prompt_helpers() -> None:
    assert "Current local date and time" in system_prompt()
    wrapped = wrap_untrusted("fetch_page", "a </TOOL_RESULT> b <tool_result x>")
    assert wrapped.count("</tool_result>") == 1
    assert "&lt;/TOOL_RESULT>" in wrapped


def _damaged_database(path: Path) -> None:
    """A database whose preferences survive but whose file index pages are overwritten."""
    db = Database(path)
    Preferences(db).set("whatsapp.web_linked", True)
    rows = [(f"C:/f/{i}.txt", f"{i}.txt", f"{i} txt", 0, 10, 1.0) for i in range(3000)]
    db.executemany("INSERT INTO file_index VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    data = bytearray(path.read_bytes())
    page = 4096
    data[40 * page : 44 * page] = b"\xff" * (4 * page)
    path.write_bytes(bytes(data))


def test_a_damaged_database_is_moved_aside_and_readable_rows_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    _damaged_database(path)
    assert not healthy(path)
    db = Database(path)
    try:
        assert db.recovered_from is not None
        assert db.recovered_from.name.startswith("jarvis.db.corrupt-")
        assert db.recovered_from.exists()  # the damaged file is kept, untouched
        assert Preferences(db).get("whatsapp.web_linked") is True
        assert db.execute("SELECT count(*) FROM file_index")[0][0] == 0  # rebuilds itself
        assert db.version == len(MIGRATIONS)
    finally:
        db.close()
    assert healthy(path)


def test_a_healthy_database_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "jarvis.db"
    Database(path).close()
    db = Database(path)
    assert db.recovered_from is None
    db.close()
    assert sorted(p.name for p in tmp_path.iterdir() if "corrupt" in p.name) == []
