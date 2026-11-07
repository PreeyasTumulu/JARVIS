"""Copy ui-demos/_kit.js into every demo page, between its kit markers.

Each demo stays one HTML file you can double-click (ADR-100); the kit lives once in
`ui-demos/_kit.js` so the seven states, the scripted run, and the controls stay the same
everywhere. tests/unit/test_ui_demos.py fails when a page's copy is out of date.

    uv run python scripts/build_ui_demos.py
"""

from __future__ import annotations

import re
from pathlib import Path

DEMOS = Path(__file__).resolve().parents[1] / "ui-demos"
BEGIN, END = "// kit:begin", "// kit:end"
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


def kit() -> str:
    return (DEMOS / "_kit.js").read_text(encoding="utf-8").strip()


def pages() -> list[Path]:
    return sorted(p for p in DEMOS.glob("*.html") if p.name != "index.html")


def with_kit(html: str, code: str) -> str:
    block = f"{BEGIN}\n{code}\n{END}"
    if not _BLOCK.search(html):
        raise ValueError("no kit markers")
    return _BLOCK.sub(lambda _: block, html, count=1)


def main() -> None:
    code = kit()
    for page in pages():
        html = page.read_text(encoding="utf-8")
        updated = with_kit(html, code)
        if updated != html:
            page.write_bytes(updated.encode("utf-8"))
            print(f"updated {page.name}")


if __name__ == "__main__":
    main()
