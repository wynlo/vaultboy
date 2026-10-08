from __future__ import annotations

import hashlib
from pathlib import Path

from .models import FileInfo


IGNORED_DIRS = {".git", "node_modules", "build", "dist", ".next", "target", ".venv", "__pycache__"}
IGNORED_FILES = {".DS_Store"}
IGNORED_EXACT = {".obsidian/workspace.json", ".obsidian/workspace-mobile.json"}
IGNORED_PREFIXES = {".obsidian/cache/"}
ICLOUD_PLACEHOLDER_SUFFIX = ".icloud"


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


def evicted_original_name(name: str) -> str | None:
    """Map an iCloud placeholder filename like `.Note.md.icloud` to `Note.md`.

    macOS "Optimize Mac Storage" replaces evicted file contents with these
    placeholders; the real file is still in iCloud, just not on disk.
    """
    if name.startswith(".") and name.endswith(ICLOUD_PLACEHOLDER_SUFFIX) and len(name) > len(ICLOUD_PLACEHOLDER_SUFFIX) + 1:
        return name[1 : -len(ICLOUD_PLACEHOLDER_SUFFIX)]
    return None


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_vault_detailed(root: Path, cache: dict[str, dict] | None = None) -> tuple[dict[str, FileInfo], set[str]]:
    """Scan a vault, returning (files, evicted).

    `evicted` holds relative paths of files whose contents are evicted to
    iCloud (represented on disk only by a `.name.icloud` placeholder); they are
    never included in `files`. `cache` maps relative path -> {mtime, size,
    hash}; a file whose mtime and size match its cache entry reuses the cached
    hash instead of re-reading the content.
    """
    root = root.expanduser()
    files: dict[str, FileInfo] = {}
    evicted: set[str] = set()
    if not root.exists() or not root.is_dir():
        return files, evicted
    cache = cache or {}
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
        original = evicted_original_name(path.name)
        if original is not None:
            real_relative = (path.parent / original).relative_to(root).as_posix()
            if not should_ignore(real_relative):
                evicted.add(real_relative)
            continue
        stat = path.stat()
        entry = cache.get(relative)
        if entry and entry.get("mtime") == stat.st_mtime and entry.get("size") == stat.st_size and entry.get("hash"):
            file_hash = entry["hash"]
        else:
            file_hash = hash_file(path)
        files[relative] = FileInfo(relative, path, file_hash, stat.st_mtime, stat.st_size)
    # A placeholder can coexist briefly with the materialized file; trust the real file.
    evicted -= set(files)
    return files, evicted


def scan_vault(root: Path) -> dict[str, FileInfo]:
    files, _ = scan_vault_detailed(root)
    return files
