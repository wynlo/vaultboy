from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import STATE_DIR
from .conflicts import conflict_path
from .models import FileInfo, ProjectConfig, SyncResult
from .scanner import scan_vault

LOGGER = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_path(project_name: str) -> Path:
    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in project_name)
    return STATE_DIR / safe_name / "manifest.json"


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


def build_manifest_files(repo_files: dict[str, FileInfo], icloud_files: dict[str, FileInfo], previous: dict | None = None) -> dict[str, dict]:
    now = utc_now()
    files: dict[str, dict] = {}
    previous_files = (previous or {}).get("files", {})
    tombstones = (previous or {}).get("tombstones", {})
    for relative in sorted(set(repo_files) | set(icloud_files)):
        repo = repo_files.get(relative)
        icloud = icloud_files.get(relative)
        info = repo if repo and (not icloud or repo.hash == icloud.hash) else icloud or repo
        if info:
            files[relative] = {"hash": info.hash, "mtime": info.mtime, "lastSyncedAt": now}
    for relative, entry in previous_files.items():
        if relative not in files and relative not in tombstones:
            tombstones[relative] = {"deletedAt": now, "hash": entry.get("hash")}
    return files


def compare_project(project: ProjectConfig) -> dict:
    repo_files = scan_vault(project.repo_path)
    icloud_files = scan_vault(project.icloud_path)
    repo_dirs = collect_dirs(project.repo_path)
    icloud_dirs = collect_dirs(project.icloud_path)
    return {
        "project": project.name,
        "repoFileCount": len(repo_files),
        "icloudFileCount": len(icloud_files),
        "repoDirCount": len(repo_dirs),
        "icloudDirCount": len(icloud_dirs),
        "filesOnlyInRepo": sorted(set(repo_files) - set(icloud_files)),
        "filesOnlyInIcloud": sorted(set(icloud_files) - set(repo_files)),
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
        repo_files = scan_vault(project.repo_path) if repo_exists else {}
        icloud_files = scan_vault(project.icloud_path) if icloud_exists else {}
        status = self.project_status(project, repo_exists, icloud_exists, repo_files, icloud_files, manifest)
        return {
            **project.to_dict(),
            "repoExists": repo_exists,
            "icloudExists": icloud_exists,
            "repoFileCount": len(repo_files),
            "icloudFileCount": len(icloud_files),
            "lastSyncTime": manifest.get("lastSyncTime"),
            "status": status,
            "conflictCount": int(manifest.get("conflictCount", 0)),
        }

    def project_status(self, project: ProjectConfig, repo_exists: bool, icloud_exists: bool, repo_files: dict[str, FileInfo], icloud_files: dict[str, FileInfo], manifest: dict) -> str:
        if not project.enabled:
            return "Disabled"
        if not repo_exists:
            return "Missing path"
        if int(manifest.get("conflictCount", 0)) > 0:
            return "Conflict"
        if not icloud_exists:
            return "Needs sync"
        for relative in set(repo_files) | set(icloud_files):
            repo = repo_files.get(relative)
            icloud = icloud_files.get(relative)
            if not repo or not icloud or repo.hash != icloud.hash:
                return "Needs sync"
        return "Synced"

    def sync(self, project: ProjectConfig, mode: str = "sync", dry_run: bool = False) -> SyncResult:
        result = SyncResult(project=project.name, mode=mode, dryRun=dry_run)
        LOGGER.info("Starting %s for %s dry_run=%s", mode, project.name, dry_run)
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
            if not result.dryRun:
                scan_vault(project.repo_path)
                scan_vault(project.icloud_path)
            if mode == "pull":
                self._copy_direction(project, project.icloud_path, project.repo_path, "icloud", "repo", result)
            elif mode == "push":
                self._copy_direction(project, project.repo_path, project.icloud_path, "repo", "icloud", result)
            elif mode == "sync":
                self._safe_sync(project, result)
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

    def _safe_sync(self, project: ProjectConfig, result: SyncResult) -> None:
        manifest = load_manifest(project.name)
        entries = manifest.get("files", {})
        tombstones = manifest.get("tombstones", {})
        repo_files = scan_vault(project.repo_path)
        icloud_files = scan_vault(project.icloud_path)
        if project.propagateDeletes and entries:
            if repo_files and not icloud_files:
                result.errors.append("Refusing to propagate deletes: iCloud scan returned no files while repo has files")
                return
            if icloud_files and not repo_files:
                result.errors.append("Refusing to propagate deletes: repo scan returned no files while iCloud has files")
                return
        for relative in sorted(set(repo_files) | set(icloud_files) | set(entries)):
            repo = repo_files.get(relative)
            icloud = icloud_files.get(relative)
            entry = entries.get(relative)
            if relative in tombstones and (not repo or not icloud):
                result.skipped.append(f"deleted:{relative}")
                continue
            if repo and icloud and repo.hash == icloud.hash:
                continue
            if repo and not icloud:
                if entry and repo.hash == entry.get("hash"):
                    if project.propagateDeletes:
                        result.copied.append(f"delete repo:{relative}")
                        delete_file(repo.path, project.repo_path, result.dryRun)
                    else:
                        result.skipped.append(f"icloud-deleted:{relative}")
                    continue
                if relative in tombstones:
                    result.skipped.append(f"icloud-deleted:{relative}")
                    continue
                target = project.icloud_path / relative
                result.copied.append(f"repo:{relative} -> icloud:{relative}")
                copy_file(repo.path, target, result.dryRun)
                continue
            if icloud and not repo:
                if entry and icloud.hash == entry.get("hash"):
                    if project.propagateDeletes:
                        result.copied.append(f"delete icloud:{relative}")
                        delete_file(icloud.path, project.icloud_path, result.dryRun)
                    else:
                        result.skipped.append(f"repo-deleted:{relative}")
                    continue
                if relative in tombstones:
                    result.skipped.append(f"repo-deleted:{relative}")
                    continue
                target = project.repo_path / relative
                result.copied.append(f"icloud:{relative} -> repo:{relative}")
                copy_file(icloud.path, target, result.dryRun)
                continue
            if not repo or not icloud:
                continue
            repo_changed = changed_since_manifest(repo, entry)
            icloud_changed = changed_since_manifest(icloud, entry)
            if repo_changed and icloud_changed:
                target = conflict_path(project.repo_path, relative)
                result.conflicts.append(f"{relative} -> {target.relative_to(project.repo_path).as_posix()}")
                copy_file(icloud.path, target, result.dryRun)
            elif repo_changed:
                result.copied.append(f"repo:{relative} -> icloud:{relative}")
                copy_file(repo.path, project.icloud_path / relative, result.dryRun)
            elif icloud_changed:
                result.copied.append(f"icloud:{relative} -> repo:{relative}")
                copy_file(icloud.path, project.repo_path / relative, result.dryRun)
            else:
                result.skipped.append(relative)

    def _copy_direction(self, project: ProjectConfig, source_root: Path, dest_root: Path, source_label: str, dest_label: str, result: SyncResult) -> None:
        manifest = load_manifest(project.name)
        entries = manifest.get("files", {})
        source_files = scan_vault(source_root)
        dest_files = scan_vault(dest_root)
        for relative in sorted(set(source_files) | set(dest_files)):
            source = source_files.get(relative)
            dest = dest_files.get(relative)
            entry = entries.get(relative)
            if source and dest and source.hash == dest.hash:
                continue
            if source and not dest:
                target = dest_root / relative
                result.copied.append(f"{source_label}:{relative} -> {dest_label}:{relative}")
                LOGGER.info("Copying missing file %s to %s", source.path, target)
                copy_file(source.path, target, result.dryRun)
                continue
            if not source:
                if project.propagateDeletes and dest and entry and dest.hash == entry.get("hash"):
                    result.copied.append(f"delete {dest_label}:{relative}")
                    LOGGER.info("Deleting %s because it is missing from %s", dest.path, source_label)
                    delete_file(dest.path, dest_root, result.dryRun)
                elif dest:
                    result.skipped.append(f"{source_label}-deleted:{relative}")
                continue
            source_changed = changed_since_manifest(source, entry)
            dest_changed = changed_since_manifest(dest, entry)
            if source_changed and dest_changed:
                target = conflict_path(dest_root, relative)
                result.conflicts.append(f"{relative} -> {target.relative_to(dest_root).as_posix()}")
                LOGGER.warning("Conflict detected for %s; writing conflict copy %s", relative, target)
                copy_file(source.path, target, result.dryRun)
            elif source_changed and not dest_changed:
                target = dest_root / relative
                result.copied.append(f"{source_label}:{relative} -> {dest_label}:{relative}")
                LOGGER.info("Copying changed file %s to %s", source.path, target)
                copy_file(source.path, target, result.dryRun)
            else:
                result.skipped.append(relative)

    def _update_manifest(self, project: ProjectConfig, mode: str, result: SyncResult) -> None:
        repo_files = scan_vault(project.repo_path)
        icloud_files = scan_vault(project.icloud_path)
        previous = load_manifest(project.name)
        tombstones = previous.get("tombstones", {})
        now = utc_now()
        for relative, entry in previous.get("files", {}).items():
            if relative not in repo_files and relative not in icloud_files:
                tombstones[relative] = {"deletedAt": now, "hash": entry.get("hash")}
        previous["tombstones"] = tombstones
        save_manifest(project.name, {
            "lastSyncTime": result.lastSyncTime or utc_now(),
            "lastOperation": mode,
            "conflictCount": int(previous.get("conflictCount", 0)) + len(result.conflicts),
            "files": build_manifest_files(repo_files, icloud_files, previous),
            "tombstones": tombstones,
            "updatedAt": time.time(),
        })
