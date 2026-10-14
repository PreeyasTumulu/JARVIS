"""Turn files into plain text for the model: text and code, PDF (pypdf), and Word .docx."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from jarvis.tools.base import ToolError

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_BINARY_HINTS = {".docx", ".xlsx", ".pptx", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".mp3", ".mp4"}


@dataclass(frozen=True)
class Document:
    text: str
    truncated: bool
    pages: int | None = None


def read_document(path: Path, *, max_chars: int, max_bytes: int) -> Document:
    if not path.is_file():
        raise ToolError(f"{path} does not exist or is not a file.")
    size = path.stat().st_size
    if size > max_bytes:
        raise ToolError(f"{path.name} is {size / 1e6:.0f} MB, too large to read.")
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _read_pdf(path, max_chars)
    if suffix == ".docx":
        return _clip(_read_docx(path), max_chars)
    if suffix in _BINARY_HINTS or _looks_binary(path):
        raise ToolError(f"I can't read {suffix or 'this'} files. I can open it instead.")
    return _clip(_read_text(path), max_chars)


def _clip(text: str, max_chars: int, pages: int | None = None) -> Document:
    text = text.strip()
    return Document(text[:max_chars], len(text) > max_chars, pages)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _read_pdf(path: Path, max_chars: int) -> Document:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ToolError(f"{path.name} is password protected.")
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
            total += len(text)
            if total > max_chars:
                break
    except PdfReadError as exc:
        raise ToolError(f"{path.name} could not be read as a PDF ({exc}).") from exc
    text = "\n\n".join(parts).strip()
    if not text:
        raise ToolError(f"{path.name} has no text layer (it may be a scanned image).")
    return _clip(text, max_chars, pages=len(reader.pages))


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ToolError(f"{path.name} could not be read as a Word document.") from exc
    paragraphs = [
        "".join(node.text or "" for node in para.iter(f"{_WORD_NS}t"))
        for para in root.iter(f"{_WORD_NS}p")
    ]
    return "\n".join(p for p in paragraphs if p.strip())


def _looks_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        head = handle.read(4096)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False  # UTF-16 text (PowerShell's default) is full of zero bytes
    return b"\x00" in head
