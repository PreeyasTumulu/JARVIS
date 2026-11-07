"""Write the agent graph's Mermaid diagram into docs/ARCHITECTURE.md (section 4.1).

Run after changing core/graph.py: uv run python scripts/architecture_graph.py
tests/unit/test_architecture_doc.py fails while the document and the code disagree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE.md"
BLOCK = re.compile(r"(<!-- graph:begin -->\n```mermaid\n)(.*?)(\n```\n<!-- graph:end -->)", re.S)


def graph_mermaid() -> str:
    from jarvis.core.graph import AgentGraph

    return AgentGraph(None).mermaid().strip()  # type: ignore[arg-type]


def documented(text: str) -> str | None:
    found = BLOCK.search(text)
    return found.group(2).strip() if found else None


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    if documented(text) is None:
        print("docs/ARCHITECTURE.md has no graph:begin and graph:end markers", file=sys.stderr)
        return 1
    updated = BLOCK.sub(lambda m: m.group(1) + graph_mermaid() + m.group(3), text)
    DOC.write_bytes(updated.encode("utf-8"))
    print("Updated the graph in docs/ARCHITECTURE.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
