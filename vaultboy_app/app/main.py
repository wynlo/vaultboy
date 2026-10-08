from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .config import LOG_PATH, default_icloud_path, delete_project, get_project, load_config, save_config, setup_logging, upsert_project
from .models import ProjectConfig
from .scheduler import Scheduler
from .sync_engine import SyncEngine, manifest_path
from .web import mount_web

setup_logging()
engine = SyncEngine()
scheduler = Scheduler(engine)
app = FastAPI(title="Vaultboy", version="0.1.0")

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_startup_config = load_config()
if _startup_config.host in _LOOPBACK_HOSTS:
    _allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        f"http://localhost:{_startup_config.port}",
        f"http://127.0.0.1:{_startup_config.port}",
        # Tauri desktop webview origins
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]
else:
    _allowed_origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_methods=["*"], allow_headers=["*"])


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Guard mutating endpoints with the optional apiToken from config.json."""
    token = load_config().apiToken
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@app.on_event("startup")
def on_startup() -> None:
    load_config()
    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    scheduler.stop()


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    config = load_config()
    return {"ok": True, "app": "Vaultboy", "intervalSeconds": config.intervalSeconds, "host": config.host, "port": config.port, "projectCount": len(config.projects), "logPath": str(LOG_PATH), "scheduler": scheduler.status()}


@app.get("/api/jobs")
def api_jobs() -> list[dict[str, Any]]:
    return scheduler.jobs()


@app.get("/api/projects")
def api_projects() -> list[dict[str, Any]]:
    config = load_config()
    return [engine.describe_project(project) for project in config.projects]


@app.post("/api/pick-folder", dependencies=[Depends(require_token)])
def api_pick_folder() -> dict[str, str | None]:
    try:
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose repo docs folder")'],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if result.returncode != 0:
        return {"path": None}
    return {"path": result.stdout.strip().rstrip("/")}


@app.get("/api/suggest-icloud-path")
def api_suggest_icloud_path(name: str = "", repoVaultPath: str = "") -> dict[str, str]:
    vault_name = name.strip() or repoVaultPath.rstrip("/").split("/")[-1].strip()
    if not vault_name:
        return {"path": ""}
    return {"path": str(default_icloud_path(vault_name))}


@app.post("/api/projects", dependencies=[Depends(require_token)])
def api_add_project(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    project = ProjectConfig.from_dict(payload)
    upsert_project(config, project)
    return engine.describe_project(project)


@app.put("/api/projects/{name}", dependencies=[Depends(require_token)])
def api_edit_project(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    if not get_project(config, name):
        raise HTTPException(status_code=404, detail="Project not found")
    project = ProjectConfig.from_dict(payload)
    upsert_project(config, project, original_name=name)
    return engine.describe_project(project)


@app.delete("/api/projects/{name}", dependencies=[Depends(require_token)])
def api_delete_project(name: str) -> dict[str, Any]:
    config = load_config()
    project = delete_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    state_dir = manifest_path(name).parent
    if state_dir.is_dir():
        shutil.rmtree(state_dir, ignore_errors=True)
    return {"project": project.name, "deleted": True}


@app.post("/api/projects/{name}/enable", dependencies=[Depends(require_token)])
def api_enable_project(name: str) -> dict[str, Any]:
    config = load_config()
    project = get_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.enabled = True
    save_config(config)
    return engine.describe_project(project)


@app.post("/api/projects/{name}/disable", dependencies=[Depends(require_token)])
def api_disable_project(name: str) -> dict[str, Any]:
    config = load_config()
    project = get_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.enabled = False
    save_config(config)
    return engine.describe_project(project)


def run_project_action(name: str, mode: str, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    config = load_config()
    project = get_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return scheduler.run_project(project, mode=mode, dry_run=dry_run, force=force)


@app.post("/api/projects/{name}/sync", dependencies=[Depends(require_token)])
def api_sync_project(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    force = bool((payload or {}).get("force", False))
    return run_project_action(name, "sync", force=force)


@app.post("/api/projects/{name}/pull", dependencies=[Depends(require_token)])
def api_pull_project(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    force = bool((payload or {}).get("force", False))
    return run_project_action(name, "pull", force=force)


@app.post("/api/projects/{name}/push", dependencies=[Depends(require_token)])
def api_push_project(name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    force = bool((payload or {}).get("force", False))
    return run_project_action(name, "push", force=force)


@app.post("/api/projects/{name}/dry-run", dependencies=[Depends(require_token)])
def api_dry_run_project(name: str) -> dict[str, Any]:
    return run_project_action(name, "sync", dry_run=True)


@app.get("/api/projects/{name}/compare")
def api_compare_project(name: str) -> dict[str, Any]:
    config = load_config()
    project = get_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return engine.compare(project)


@app.post("/api/projects/{name}/prune", dependencies=[Depends(require_token)])
def api_prune_project(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    project = get_project(config, name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    side = str(payload.get("side", ""))
    paths = payload.get("paths", [])
    dry_run = bool(payload.get("dryRun", True))
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise HTTPException(status_code=400, detail="paths must be a list of strings")
    try:
        return engine.prune_missing(project, side, paths, dry_run=dry_run)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/projects/{name}/logs")
def api_project_logs(name: str) -> dict[str, Any]:
    if not LOG_PATH.exists():
        return {"project": name, "logs": []}
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"project": name, "logs": [line for line in lines if name in line][-200:]}


@app.get("/api/projects/{name}/jobs")
def api_project_jobs(name: str) -> dict[str, Any]:
    return {"project": name, "jobs": scheduler.jobs(name)}


if os.environ.get("VAULTBOY_DEV") == "1":
    @app.get("/")
    def dev_root() -> RedirectResponse:
        return RedirectResponse("http://127.0.0.1:5173")
else:
    mount_web(app)


def run() -> None:
    config = load_config()
    # Pass the app object (not an import string) so frozen/PyInstaller builds work.
    uvicorn.run(app, host=config.host, port=config.port, reload=False)


if __name__ == "__main__":
    run()
