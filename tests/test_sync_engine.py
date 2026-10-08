from __future__ import annotations

from pathlib import Path

import pytest

from vaultboy_app.app import scanner as scanner_module
from vaultboy_app.app import sync_engine as sync_engine_module
from vaultboy_app.app.models import ProjectConfig
from vaultboy_app.app.sync_engine import SyncEngine, load_manifest


@pytest.fixture()
def vaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectConfig, Path, Path]:
    monkeypatch.setattr(sync_engine_module, "STATE_DIR", tmp_path / "state")
    repo = tmp_path / "repo"
    icloud = tmp_path / "icloud"
    repo.mkdir()
    icloud.mkdir()
    project = ProjectConfig(name="test", repoVaultPath=str(repo), icloudVaultPath=str(icloud))
    return project, repo, icloud


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def synced_pair(project: ProjectConfig, repo: Path, icloud: Path, names: list[str]) -> SyncEngine:
    engine = SyncEngine()
    for name in names:
        write(repo, name, f"content of {name}")
    result = engine.sync(project)
    assert result.errors == []
    for name in names:
        assert (icloud / name).exists()
    return engine


def test_delete_propagates_when_survivor_unchanged(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "gone.md"])
    (repo / "gone.md").unlink()
    result = engine.sync(project)
    assert result.errors == []
    assert "delete icloud:gone.md" in result.copied
    assert not (icloud / "gone.md").exists()
    assert (icloud / "keep.md").exists()


def test_modified_survivor_is_copied_back_not_deleted(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "note.md"])
    (repo / "note.md").unlink()
    write(icloud, "note.md", "edited on the phone")
    result = engine.sync(project)
    assert result.errors == []
    assert (repo / "note.md").read_text(encoding="utf-8") == "edited on the phone"
    assert (icloud / "note.md").exists()


def test_evicted_placeholder_is_not_treated_as_deletion(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "note.md"])
    # Simulate iCloud evicting note.md: real file replaced by a placeholder.
    (icloud / "note.md").unlink()
    write(icloud, ".note.md.icloud", "placeholder plist")
    result = engine.sync(project)
    assert result.errors == []
    assert "evicted:note.md" in result.skipped
    assert (repo / "note.md").exists(), "repo copy must survive eviction"
    assert not any(path.name.endswith(".icloud") for path in repo.rglob("*")), "placeholders must never be copied"
    manifest = load_manifest(project.name)
    assert "note.md" not in manifest.get("tombstones", {})


def test_recreated_file_after_tombstone_syncs_again(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "note.md"])
    (repo / "note.md").unlink()
    result = engine.sync(project)
    assert not (icloud / "note.md").exists()
    assert "note.md" in load_manifest(project.name).get("tombstones", {})

    write(repo, "note.md", "a brand new note at the old path")
    result = engine.sync(project)
    assert result.errors == []
    assert (icloud / "note.md").read_text(encoding="utf-8") == "a brand new note at the old path"
    assert "note.md" not in load_manifest(project.name).get("tombstones", {})


def test_unchanged_deleted_content_stays_tombstoned(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "note.md"])
    (repo / "note.md").unlink()
    engine.sync(project)
    # The same dead content reappearing (e.g. stale iCloud copy) stays deleted.
    write(icloud, "note.md", "content of note.md")
    result = engine.sync(project)
    assert "deleted:note.md" in result.skipped
    assert not (repo / "note.md").exists()


def test_mass_delete_guard_blocks_then_force_overrides(vaults):
    project, repo, icloud = vaults
    names = [f"note-{index}.md" for index in range(10)]
    engine = synced_pair(project, repo, icloud, names)
    for name in names[:8]:
        (repo / name).unlink()

    result = engine.sync(project)
    assert result.status == "Error"
    assert any("Refusing to delete 8 files" in error for error in result.errors)
    for name in names[:8]:
        assert (icloud / name).exists(), "guard must prevent the deletions"

    result = engine.sync(project, force=True)
    assert result.errors == []
    for name in names[:8]:
        assert not (icloud / name).exists()
    for name in names[8:]:
        assert (icloud / name).exists()


def test_conflict_creates_copy_and_count_resets_after_cleanup(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["note.md"])
    write(repo, "note.md", "edited on the mac")
    write(icloud, "note.md", "edited on the phone")
    result = engine.sync(project)
    assert result.status == "Conflict"
    conflict_copies = [path for path in repo.rglob("*") if ".conflict-" in path.name]
    assert len(conflict_copies) == 1
    assert load_manifest(project.name)["conflictCount"] >= 1

    for side in (repo, icloud):
        for path in side.rglob("*"):
            if ".conflict-" in path.name:
                path.unlink()
    result = engine.sync(project)
    assert result.errors == []
    assert load_manifest(project.name)["conflictCount"] == 0


def test_scan_cache_avoids_rehashing_unchanged_files(vaults, monkeypatch):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["a.md", "b.md"])

    calls = {"count": 0}
    real_hash = scanner_module.hash_file

    def counting_hash(path: Path) -> str:
        calls["count"] += 1
        return real_hash(path)

    monkeypatch.setattr(scanner_module, "hash_file", counting_hash)
    result = engine.sync(project)
    assert result.errors == []
    assert calls["count"] == 0, "unchanged files must reuse cached hashes"

    write(repo, "a.md", "changed")
    engine.sync(project)
    assert calls["count"] > 0


def test_pull_and_push_respect_eviction(vaults):
    project, repo, icloud = vaults
    engine = synced_pair(project, repo, icloud, ["keep.md", "note.md"])
    (icloud / "note.md").unlink()
    write(icloud, ".note.md.icloud", "placeholder")
    result = engine.sync(project, mode="pull")
    assert result.errors == []
    assert "evicted:note.md" in result.skipped
    assert (repo / "note.md").exists()
