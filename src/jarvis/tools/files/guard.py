"""The folder allowlist and file rules every file tool goes through.

Paths are resolved first (following symlinks and junctions), so "..", links, and odd casing
cannot escape the allowed folders. Secret-looking files are blocked even inside them.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path

from jarvis.config import FilesSettings
from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Risk, ToolError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PathCheck:
    path: Path
    risk: Risk
    reason: str | None = None


class FileGuard:
    def __init__(self, cfg: FilesSettings, roots: list[Path] | None = None) -> None:
        self._cfg = cfg
        self.roots = roots if roots is not None else resolve_roots(cfg.allowed_folders)
        self._blocked = [pattern.casefold() for pattern in cfg.blocked_patterns]
        self._blocked_ext = {ext.casefold() for ext in cfg.blocked_extensions}
        self._confirm_ext = {ext.casefold() for ext in cfg.confirm_extensions}

    def resolve(self, raw: str) -> Path:
        path = Path(raw.strip().strip('"')).expanduser()
        if not path.is_absolute():
            raise ToolError(f"'{raw}' is not a full path. Use find_file to look the file up first.")
        return path.resolve(strict=False)

    def inside(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.roots)

    def is_secret(self, path: Path) -> bool:
        name = path.name.casefold()
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self._blocked)

    def check(self, raw: str, *, opening: bool = False) -> PathCheck:
        path = self.resolve(raw)
        if not self.inside(path):
            folders = ", ".join(str(root) for root in self.roots) or "none configured"
            return PathCheck(
                path, Risk.BLOCKED, f"{path} is outside the allowed folders ({folders})"
            )
        if self.is_secret(path):
            return PathCheck(
                path, Risk.BLOCKED, f"{path.name} looks like a secret or credential file"
            )
        suffix = path.suffix.casefold()
        if opening and suffix in self._blocked_ext:
            return PathCheck(path, Risk.BLOCKED, f"opening {suffix} files is not allowed")
        if opening and suffix in self._confirm_ext:
            return PathCheck(path, Risk.CONFIRM, f"opening a {suffix} file runs a program")
        return PathCheck(path, Risk.SAFE)

    def allows(self, path: Path) -> bool:
        return self.inside(path) and not self.is_secret(path)


def resolve_roots(specs: list[str]) -> list[Path]:
    roots: list[Path] = []
    for spec in specs:
        try:
            root = expand_folder(spec).resolve(strict=False)
        except (KeyError, OSError) as exc:
            log.warning("Skipping allowed folder %s: %s", spec, exc)
            continue
        if root.is_dir():
            roots.append(root)
        else:
            log.warning("Allowed folder %s does not exist", root)
    return roots
