"""docs/ARCHITECTURE.md shows the graph the code builds, not an older drawing of it."""

from __future__ import annotations

import importlib.util

from tests.conftest import REPO


def test_the_documented_graph_is_the_real_one() -> None:
    spec = importlib.util.spec_from_file_location(
        "architecture_graph", REPO / "scripts" / "architecture_graph.py"
    )
    assert spec is not None
    assert spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    documented = script.documented(script.DOC.read_text(encoding="utf-8"))
    assert documented is not None, "the graph markers are missing from docs/ARCHITECTURE.md"
    assert documented == script.graph_mermaid(), (
        "docs/ARCHITECTURE.md is out of date: uv run python scripts/architecture_graph.py"
    )
