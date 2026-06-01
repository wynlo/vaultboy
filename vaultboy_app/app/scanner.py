from __future__ import annotations

import hashlib
from pathlib import Path

from .models import FileInfo


IGNORED_DIRS = {".git", "node_modules", "build", "dist", ".next", "target", ".venv", "__pycache__"}
IGNORED_FILES = {".DS_Store"}
IGNORED_EXACT = {".obsidian/workspace.json", ".obsidian/workspace-mobile.json"}
IGNORED_PREFIXES = {".obsidian/cache/"}


def should_ignore(relative_path: str, is_dir: bool = False) -> bool:
    parts = Path(relative_path).parts
    if parts and parts[0] == ".obsidian":
        return True
    if any(part in IGNORED_DIRS for part in parts):
        return True
    if parts and parts[-1] in IGNORED_FILES:
        return True
    normalized = relative_path.replace("\\", "/")
    if normalized in IGNORED_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return True
    if len(parts) >= 4 and parts[0] == ".obsidian" and parts[1] == "plugins" and parts[-1] == "data.json":
        return True
    return False


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_vault(root: Path) -> dict[str, FileInfo]:
    root = root.expanduser()
    if not root.exists() or not root.is_dir():
        return {}
    files: dict[str, FileInfo] = {}
    try:
        paths = list(root.rglob("*"))
    except OSError as exc:
        raise PermissionError(f"Unable to scan vault path {root}: {exc}") from exc
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if should_ignore(relative, path.is_dir()):
            continue
        if not path.is_file():
            continue
        stat = path.stat()
        files[relative] = FileInfo(relative, path, hash_file(path), stat.st_mtime, stat.st_size)
    return files
