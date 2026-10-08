from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path

from .config import STATE_DIR
from .conflicts import conflict_path
from .models import FileInfo, ProjectConfig, SyncResult
from .scanner import evicted_original_name, scan_vault_detailed

LOGGER = logging.getLogger(__name__)

TOMBSTONE_TTL_DAYS = 30
DELETE_GUARD_MIN = 5
DELETE_GUARD_FRACTION = 0.2
MATERIALIZE_LIMIT = 200


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_path(project_name: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in project_name)
    return STATE_DIR / safe_name / "manifest.json"


def scan_cache_path(project_name: str) -> Path:
    return manifest_path(project_name).parent / "scan-cache.json"


def delete_limit(entry_count: int) -> int:
    return max(DELETE_GUARD_MIN, ceil(DELETE_GUARD_FRACTION * entry_count))


def load_manifest(project_name: str) -> dict:
    path = manifest_path(project_name)
    if not path.exists():
        return {"files": {}, "lastSyncTime": None, "lastOperation": None, "conflictCount": 0}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_manifest(project_name: str, manifest: dict) -> None:
    path = manifest_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def copy_file(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def delete_file(path: Path, root: Path, dry_run: bool) -> None:
    if dry_run:
        return
    path.unlink()
    parent = path.parent
    while parent != root and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def changed_since_manifest(info: FileInfo | None, entry: dict | None) -> bool:
    if info is None:
        return False
    if not entry:
        return True
    return info.hash != entry.get("hash")


def build_manifest_files(repo_files: dict[str, FileInfo], icloud_files: dict[str, FileInfo]) -> dict[str, dict]:
    now = utc_now()
    files: dict[str, dict] = {}
    for relative in sorted(set(repo_files) | set(icloud_files)):
        repo = repo_files.get(relative)
        icloud = icloud_files.get(relative)
        info = repo if repo and (not icloud or repo.hash == icloud.hash) else icloud or repo
        if info:
            files[relative] = {"hash": info.hash, "mtime": info.mtime, "lastSyncedAt": now}
    return files


def prune_tombstones(tombstones: dict[str, dict], files: dict[str, dict]) -> dict[str, dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_TTL_DAYS)
    kept: dict[str, dict] = {}
    for relative, stone in tombstones.items():
        if relative in files:
            continue
        try:
            deleted_at = datetime.fromisoformat(str(stone.get("deletedAt")))
        except (TypeError, ValueError):
            deleted_at = None
        if deleted_at and deleted_at < cutoff:
            continue
        kept[relative] = stone
    return kept


def compare_project(project: ProjectConfig) -> dict:
    repo_files, repo_evicted = scan_vault_detailed(project.repo_path)
    icloud_files, icloud_evicted = scan_vault_detailed(project.icloud_path)
    repo_dirs = collect_dirs(project.repo_path)
    icloud_dirs = collect_dirs(project.icloud_path)
    return {
        "project": project.name,
        "repoFileCount": len(repo_files),
        "icloudFileCount": len(icloud_files),
        "repoDirCount": len(repo_dirs),
        "icloudDirCount": len(icloud_dirs),
        "filesOnlyInRepo": sorted(set(repo_files) - set(icloud_files) - icloud_evicted),
        "filesOnlyInIcloud": sorted(set(icloud_files) - set(repo_files) - repo_evicted),
        "evictedInRepo": sorted(repo_evicted),
        "evictedInIcloud": sorted(icloud_evicted),
        "dirsOnlyInRepo": sorted(repo_dirs - icloud_dirs),
        "dirsOnlyInIcloud": sorted(icloud_dirs - repo_dirs),
        "commonDifferent": sorted(
            relative for relative in set(repo_files) & set(icloud_files) if repo_files[relative].hash != icloud_files[relative].hash
        ),
    }


def collect_dirs(root: Path) -> set[str]:
    from .scanner import should_ignore

    dirs: set[str] = set()
    if not root.exists() or not root.is_dir():
        return dirs
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if should_ignore(relative, path.is_dir()):
            continue
        if path.is_dir():
            dirs.add(relative)
    return dirs


class SyncEngine:
    def describe_project(self, project: ProjectConfig) -> dict:
        manifest = load_manifest(project.name)
        repo_exists = project.repo_path.exists() and project.repo_path.is_dir()
        icloud_exists = project.icloud_path.exists() and project.icloud_path.is_dir()
        repo_files, repo_evicted = self._scan_side(project, "repo") if repo_exists else ({}, set())
        icloud_files, icloud_evicted = self._scan_side(project, "icloud") if icloud_exists else ({}, set())
        status = self.project_status(project, repo_exists, icloud_exists, repo_files, icloud_files, manifest, repo_evicted | icloud_evicted)
        return {
            **project.to_dict(),
            "repoExists": repo_exists,
            "icloudExists": icloud_exists,
            "repoFileCount": len(repo_files),
            "icloudFileCount": len(icloud_files),
            "icloudEvictedCount": len(icloud_evicted),
            "lastSyncTime": manifest.get("lastSyncTime"),
            "status": status,
            "conflictCount": int(manifest.get("conflictCount", 0)),
        }

    def project_status(self, project: ProjectConfig, repo_exists: bool, icloud_exists: bool, repo_files: dict[str, FileInfo], icloud_files: dict[str, FileInfo], manifest: dict, evicted: set[str] | None = None) -> str:
        if not project.enabled:
            return "Disabled"
        if not repo_exists:
            return "Missing path"
        if int(manifest.get("conflictCount", 0)) > 0:
            return "Conflict"
        if not icloud_exists:
            return "Needs sync"
        evicted = evicted or set()
        for relative in set(repo_files) | set(icloud_files):
            if relative in evicted:
                continue
            repo = repo_files.get(relative)
            icloud = icloud_files.get(relative)
            if not repo or not icloud or repo.hash != icloud.hash:
                return "Needs sync"
        return "Synced"

    def sync(self, project: ProjectConfig, mode: str = "sync", dry_run: bool = False, force: bool = False) -> SyncResult:
        result = SyncResult(project=project.name, mode=mode, dryRun=dry_run)
        LOGGER.info("Starting %s for %s dry_run=%s force=%s", mode, project.name, dry_run, force)
        try:
            if not project.repo_path.exists() or not project.repo_path.is_dir():
                result.status = "Missing path"
                result.errors.append(f"Repo vault path does not exist: {project.repo_path}")
                LOGGER.error(result.errors[-1])
                return result
            if not project.icloud_path.exists():
                LOGGER.info("Creating iCloud vault path: %s", project.icloud_path)
                if not dry_run:
                    project.icloud_path.mkdir(parents=True, exist_ok=True)
            if not dry_run:
                self._materialize_evicted(project)
            if mode == "pull":
                self._copy_direction(project, "icloud", "repo", result, force=force)
            elif mode == "push":
                self._copy_direction(project, "repo", "icloud", result, force=force)
            elif mode == "sync":
                self._safe_sync(project, result, force=force)
            else:
                raise ValueError(f"Unknown sync mode: {mode}")
            result.lastSyncTime = utc_now()
            result.status = "Conflict" if result.conflicts else "Synced"
            if result.errors:
                result.status = "Error"
            if not dry_run and not result.errors:
                self._update_manifest(project, mode, result)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Sync failed for %s", project.name)
            result.status = "Error"
            result.errors.append(str(exc))
        LOGGER.info("Finished %s for %s status=%s copied=%s conflicts=%s errors=%s", mode, project.name, result.status, len(result.copied), len(result.conflicts), len(result.errors))
        return result

    def compare(self, project: ProjectConfig) -> dict:
        return compare_project(project)

    def prune_missing(self, project: ProjectConfig, side: str, paths: list[str], dry_run: bool = True) -> dict:
        if side not in {"repo", "icloud"}:
            raise ValueError("side must be repo or icloud")
        root = project.repo_path if side == "repo" else project.icloud_path
        deleted: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        for relative in paths:
            target = root / relative
            try:
                if not target.exists():
                    skipped.append(relative)
                    continue
                if target.is_dir():
                    skipped.append(f"{relative} is a directory")
                    continue
                deleted.append(relative)
                if not dry_run:
                    target.unlink()
            except OSError as exc:
                errors.append(f"{relative}: {exc}")
        if not dry_run:
            self._update_manifest(project, f"prune-{side}", SyncResult(project=project.name, mode=f"prune-{side}"))
        return {"project": project.name, "side": side, "dryRun": dry_run, "deleted": deleted, "skipped": skipped, "errors": errors}

    def _scan_side(self, project: ProjectConfig, side: str) -> tuple[dict[str, FileInfo], set[str]]:
        root = project.repo_path if side == "repo" else project.icloud_path
        cache = self._load_scan_cache(project.name)
        files, evicted = scan_vault_detailed(root, cache.get(side) or {})
        cache[side] = {relative: {"mtime": info.mtime, "size": info.size, "hash": info.hash} for relative, info in files.items()}
        self._save_scan_cache(project.name, cache)
        return files, evicted

    def _load_scan_cache(self, project_name: str) -> dict:
        path = scan_cache_path(project_name)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_scan_cache(self, project_name: str, cache: dict) -> None:
        path = scan_cache_path(project_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(cache, handle)
            tmp_path.replace(path)
        except OSError:
            LOGGER.debug("Could not persist scan cache for %s", project_name)

    def _materialize_evicted(self, project: ProjectConfig) -> None:
        """Ask iCloud to download evicted files so they stop looking deleted."""
        root = project.icloud_path.expanduser()
        if not root.exists() or not root.is_dir():
            return
        requested = 0
        for path in root.rglob("*.icloud"):
            if requested >= MATERIALIZE_LIMIT:
                LOGGER.warning("More than %s evicted files in %s; remaining downloads deferred to later runs", MATERIALIZE_LIMIT, root)
                break
            if not path.is_file():
                continue
            original = evicted_original_name(path.name)
            if original is None:
                continue
            requested += 1
            target = path.parent / original
            try:
                subprocess.run(["brctl", "download", str(target)], check=False, capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                LOGGER.debug("brctl download request failed for %s", target)
        if requested:
            LOGGER.info("Requested iCloud download of %s evicted files in %s", requested, root)

    def _apply_ops(self, ops: list[tuple], result: SyncResult) -> None:
        if result.dryRun:
            return
        for op in ops:
            if op[0] == "copy":
                _, src, dst = op
                LOGGER.info("Copying %s to %s", src, dst)
                copy_file(src, dst, False)
            else:
                _, path, root, relative = op
                LOGGER.info("Deleting %s", path)
                delete_file(path, root, False)

    def _deletes_allowed(self, ops: list[tuple], entries: dict, result: SyncResult, force: bool) -> bool:
        deletes = [op for op in ops if op[0] == "delete"]
        if not deletes or force:
            return True
        limit = delete_limit(len(entries))
        if len(deletes) <= limit:
            return True
        sample = ", ".join(op[3] for op in deletes[:10])
        result.copied.clear()
        result.conflicts.clear()
        result.skipped.clear()
        result.errors.append(
            f"Refusing to delete {len(deletes)} files in one pass (limit {limit}): {sample}"
            f"{', ...' if len(deletes) > 10 else ''}. "
            "Check with dry-run/compare; if the deletions are intended, re-run sync with force."
        )
        LOGGER.warning("Delete guard tripped for %s: %s planned deletions (limit %s)", result.project, len(deletes), limit)
        return False

    def _safe_sync(self, project: ProjectConfig, result: SyncResult, force: bool = False) -> None:
        manifest = load_manifest(project.name)
        entries = manifest.get("files", {})
        tombstones = manifest.get("tombstones", {})
        repo_files, repo_evicted = self._scan_side(project, "repo")
        icloud_files, icloud_evicted = self._scan_side(project, "icloud")
        evicted = repo_evicted | icloud_evicted
        if project.propagateDeletes and entries:
            if repo_files and not icloud_files:
                detail = f" ({len(icloud_evicted)} evicted to iCloud; download requested, will retry)" if icloud_evicted else ""
                result.errors.append("Refusing to propagate deletes: iCloud scan returned no files while repo has files" + detail)
                return
            if icloud_files and not repo_files:
                result.errors.append("Refusing to propagate deletes: repo scan returned no files while iCloud has files")
                return
        ops: list[tuple] = []
        for relative in sorted(set(repo_files) | set(icloud_files) | set(entries) | evicted):
            if relative in evicted:
                result.skipped.append(f"evicted:{relative}")
                continue
            repo = repo_files.get(relative)
            icloud = icloud_files.get(relative)
            entry = entries.get(relative)
            stone = tombstones.get(relative)
            if stone and (not repo or not icloud):
                survivor = repo or icloud
                if survivor is None or survivor.hash == stone.get("hash"):
                    result.skipped.append(f"deleted:{relative}")
                    continue
                # New content at a previously deleted path: treat as a fresh file.
            if repo and icloud and repo.hash == icloud.hash:
                continue
            if repo and not icloud:
                if entry and repo.hash == entry.get("hash"):
                    if project.propagateDeletes:
                        result.copied.append(f"delete repo:{relative}")
                        ops.append(("delete", repo.path, project.repo_path, relative))
                    else:
                        result.skipped.append(f"icloud-deleted:{relative}")
                    continue
                result.copied.append(f"repo:{relative} -> icloud:{relative}")
                ops.append(("copy", repo.path, project.icloud_path / relative))
                continue
            if icloud and not repo:
                if entry and icloud.hash == entry.get("hash"):
                    if project.propagateDeletes:
                        result.copied.append(f"delete icloud:{relative}")
                        ops.append(("delete", icloud.path, project.icloud_path, relative))
                    else:
                        result.skipped.append(f"repo-deleted:{relative}")
                    continue
                result.copied.append(f"icloud:{relative} -> repo:{relative}")
                ops.append(("copy", icloud.path, project.repo_path / relative))
                continue
            if not repo or not icloud:
                continue
            repo_changed = changed_since_manifest(repo, entry)
            icloud_changed = changed_since_manifest(icloud, entry)
            if repo_changed and icloud_changed:
                target = conflict_path(project.repo_path, relative)
                result.conflicts.append(f"{relative} -> {target.relative_to(project.repo_path).as_posix()}")
                ops.append(("copy", icloud.path, target))
            elif repo_changed:
                result.copied.append(f"repo:{relative} -> icloud:{relative}")
                ops.append(("copy", repo.path, project.icloud_path / relative))
            elif icloud_changed:
                result.copied.append(f"icloud:{relative} -> repo:{relative}")
                ops.append(("copy", icloud.path, project.repo_path / relative))
            else:
                result.skipped.append(relative)
        if not self._deletes_allowed(ops, entries, result, force):
            return
        self._apply_ops(ops, result)

    def _copy_direction(self, project: ProjectConfig, source_side: str, dest_side: str, result: SyncResult, force: bool = False) -> None:
        dest_root = project.repo_path if dest_side == "repo" else project.icloud_path
        manifest = load_manifest(project.name)
        entries = manifest.get("files", {})
        source_files, source_evicted = self._scan_side(project, source_side)
        dest_files, dest_evicted = self._scan_side(project, dest_side)
        evicted = source_evicted | dest_evicted
        ops: list[tuple] = []
        for relative in sorted(set(source_files) | set(dest_files) | evicted):
            if relative in evicted:
                result.skipped.append(f"evicted:{relative}")
                continue
            source = source_files.get(relative)
            dest = dest_files.get(relative)
            entry = entries.get(relative)
            if source and dest and source.hash == dest.hash:
                continue
            if source and not dest:
                result.copied.append(f"{source_side}:{relative} -> {dest_side}:{relative}")
                ops.append(("copy", source.path, dest_root / relative))
                continue
            if not source:
                if project.propagateDeletes and dest and entry and dest.hash == entry.get("hash"):
                    result.copied.append(f"delete {dest_side}:{relative}")
                    ops.append(("delete", dest.path, dest_root, relative))
                elif dest:
                    result.skipped.append(f"{source_side}-deleted:{relative}")
                continue
            source_changed = changed_since_manifest(source, entry)
            dest_changed = changed_since_manifest(dest, entry)
            if source_changed and dest_changed:
                target = conflict_path(dest_root, relative)
                result.conflicts.append(f"{relative} -> {target.relative_to(dest_root).as_posix()}")
                LOGGER.warning("Conflict detected for %s; writing conflict copy %s", relative, target)
                ops.append(("copy", source.path, target))
            elif source_changed and not dest_changed:
                result.copied.append(f"{source_side}:{relative} -> {dest_side}:{relative}")
                ops.append(("copy", source.path, dest_root / relative))
            else:
                result.skipped.append(relative)
        if not self._deletes_allowed(ops, entries, result, force):
            return
        self._apply_ops(ops, result)

    def _update_manifest(self, project: ProjectConfig, mode: str, result: SyncResult) -> None:
        repo_files, repo_evicted = self._scan_side(project, "repo")
        icloud_files, icloud_evicted = self._scan_side(project, "icloud")
        evicted = repo_evicted | icloud_evicted
        previous = load_manifest(project.name)
        now = utc_now()
        files = build_manifest_files(repo_files, icloud_files)
        tombstones = dict(previous.get("tombstones", {}))
        for relative, entry in previous.get("files", {}).items():
            if relative not in repo_files and relative not in icloud_files and relative not in evicted and relative not in tombstones:
                tombstones[relative] = {"deletedAt": now, "hash": entry.get("hash")}
        tombstones = prune_tombstones(tombstones, files)
        conflict_count = sum(1 for relative in set(repo_files) | set(icloud_files) if ".conflict-" in relative.rsplit("/", 1)[-1])
        save_manifest(project.name, {
            "lastSyncTime": result.lastSyncTime or now,
            "lastOperation": mode,
            "conflictCount": conflict_count,
            "files": files,
            "tombstones": tombstones,
            "updatedAt": time.time(),
        })
