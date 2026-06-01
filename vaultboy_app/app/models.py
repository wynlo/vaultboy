from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectConfig:
    name: str
    repoVaultPath: str
    icloudVaultPath: str
    enabled: bool = True
    propagateDeletes: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectConfig":
        return cls(
            name=str(data.get("name", "")).strip(),
            repoVaultPath=str(data.get("repoVaultPath", "")).strip(),
            icloudVaultPath=str(data.get("icloudVaultPath", "")).strip(),
            enabled=bool(data.get("enabled", True)),
            propagateDeletes=bool(data.get("propagateDeletes", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "repoVaultPath": self.repoVaultPath,
            "icloudVaultPath": self.icloudVaultPath,
            "enabled": self.enabled,
            "propagateDeletes": self.propagateDeletes,
        }

    @property
    def repo_path(self) -> Path:
        return Path(self.repoVaultPath).expanduser()

    @property
    def icloud_path(self) -> Path:
        return Path(self.icloudVaultPath).expanduser()


@dataclass
class AppConfig:
    intervalSeconds: int = 300
    host: str = "0.0.0.0"
    port: int = 4567
    projects: list[ProjectConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            intervalSeconds=int(data.get("intervalSeconds", 300)),
            host=str(data.get("host", "0.0.0.0")),
            port=int(data.get("port", 4567)),
            projects=[ProjectConfig.from_dict(item) for item in data.get("projects", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "intervalSeconds": self.intervalSeconds,
            "host": self.host,
            "port": self.port,
            "projects": [project.to_dict() for project in self.projects],
        }


@dataclass
class FileInfo:
    relative_path: str
    path: Path
    hash: str
    mtime: float
    size: int


@dataclass
class SyncResult:
    project: str
    mode: str
    dryRun: bool = False
    status: str = "Synced"
    copied: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    lastSyncTime: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "mode": self.mode,
            "dryRun": self.dryRun,
            "status": self.status,
            "copied": self.copied,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "skipped": self.skipped,
            "lastSyncTime": self.lastSyncTime,
        }
