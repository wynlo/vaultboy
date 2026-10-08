from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import AppConfig, ProjectConfig


APP_DIR = Path.home() / ".vaultboy"
CONFIG_PATH = APP_DIR / "config.json"
STATE_DIR = APP_DIR / "state"
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "vaultboy.log"


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def default_icloud_path(vault_name: str) -> Path:
    return Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / vault_name


def load_config() -> AppConfig:
    ensure_app_dirs()
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return AppConfig.from_dict(data)


def save_config(config: AppConfig) -> None:
    ensure_app_dirs()
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(config.to_dict(), handle, indent=2)
        handle.write("\n")
    tmp_path.replace(CONFIG_PATH)


def get_project(config: AppConfig, name: str) -> ProjectConfig | None:
    for project in config.projects:
        if project.name == name:
            return project
    return None


def delete_project(config: AppConfig, name: str) -> ProjectConfig | None:
    project = get_project(config, name)
    if not project:
        return None
    config.projects = [item for item in config.projects if item.name != name]
    save_config(config)
    return project


def upsert_project(config: AppConfig, project: ProjectConfig, original_name: str | None = None) -> AppConfig:
    if not project.name:
        raise ValueError("Project name is required")
    if not project.repoVaultPath:
        raise ValueError("Repo docs path is required")
    if not project.icloudVaultPath:
        raise ValueError("iCloud vault path is required")

    target_name = original_name or project.name
    replaced = False
    new_projects: list[ProjectConfig] = []
    for existing in config.projects:
        if existing.name == target_name:
            new_projects.append(project)
            replaced = True
        elif existing.name == project.name and target_name != project.name:
            raise ValueError(f"Project already exists: {project.name}")
        else:
            new_projects.append(existing)
    if not replaced:
        if get_project(config, project.name):
            raise ValueError(f"Project already exists: {project.name}")
        new_projects.append(project)
    config.projects = new_projects
    save_config(config)
    return config


def setup_logging() -> None:
    ensure_app_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
