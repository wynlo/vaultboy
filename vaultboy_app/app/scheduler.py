from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .config import load_config
from .models import ProjectConfig
from .sync_engine import SyncEngine

LOGGER = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, engine: SyncEngine) -> None:
        self.engine = engine
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._locks: dict[str, threading.Lock] = {}
        self._jobs: deque[dict[str, Any]] = deque(maxlen=200)
        self._jobs_lock = threading.Lock()
        self._next_run_at: float | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="vaultboy-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def lock_for(self, project_name: str) -> threading.Lock:
        if project_name not in self._locks:
            self._locks[project_name] = threading.Lock()
        return self._locks[project_name]

    def run_project(self, project: ProjectConfig, mode: str = "sync", dry_run: bool = False, trigger: str = "manual", force: bool = False) -> dict:
        started_at = time.time()
        job = {
            "id": f"{project.name}-{int(started_at * 1000)}",
            "project": project.name,
            "mode": mode,
            "dryRun": dry_run,
            "force": force,
            "trigger": trigger,
            "startedAt": datetime.fromtimestamp(started_at, timezone.utc).isoformat(),
            "finishedAt": None,
            "durationMs": None,
            "status": "Running",
            "copiedCount": 0,
            "conflictCount": 0,
            "errorCount": 0,
            "skippedCount": 0,
            "evictedCount": 0,
            "copied": [],
            "conflicts": [],
            "errors": [],
            "skipped": [],
        }
        self._record_job(job)
        lock = self.lock_for(project.name)
        if not lock.acquire(blocking=False):
            LOGGER.info("Skipping %s for %s; sync already running", mode, project.name)
            skipped = {"project": project.name, "mode": mode, "status": "Skipped", "errors": ["Sync already running"]}
            self._finish_job(job, skipped, started_at)
            return skipped
        try:
            result = self.engine.sync(project, mode=mode, dry_run=dry_run, force=force).to_dict()
            self._finish_job(job, result, started_at)
            return result
        finally:
            lock.release()

    def jobs(self, project_name: str | None = None) -> list[dict[str, Any]]:
        with self._jobs_lock:
            jobs = list(self._jobs)
        if project_name:
            jobs = [job for job in jobs if job.get("project") == project_name]
        return list(reversed(jobs))

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "nextRunAt": datetime.fromtimestamp(self._next_run_at, timezone.utc).isoformat() if self._next_run_at else None,
            "trackedJobs": len(self._jobs),
        }

    def _record_job(self, job: dict[str, Any]) -> None:
        with self._jobs_lock:
            self._jobs.append(job)

    def _finish_job(self, job: dict[str, Any], result: dict[str, Any], started_at: float) -> None:
        finished_at = time.time()
        skipped = result.get("skipped", [])
        job.update({
            "finishedAt": datetime.fromtimestamp(finished_at, timezone.utc).isoformat(),
            "durationMs": int((finished_at - started_at) * 1000),
            "status": result.get("status", "Unknown"),
            "copied": result.get("copied", []),
            "conflicts": result.get("conflicts", []),
            "errors": result.get("errors", []),
            "skipped": skipped[:50],
        })
        job["copiedCount"] = len(job["copied"])
        job["conflictCount"] = len(job["conflicts"])
        job["errorCount"] = len(job["errors"])
        job["skippedCount"] = len(skipped)
        job["evictedCount"] = sum(1 for item in skipped if isinstance(item, str) and item.startswith("evicted:"))

    def _run(self) -> None:
        while not self._stop.is_set():
            config = load_config()
            interval = max(30, int(config.intervalSeconds or 300))
            self._next_run_at = time.time() + interval
            for project in config.projects:
                if self._stop.is_set():
                    break
                if not project.enabled:
                    continue
                LOGGER.info("Auto-sync attempt for %s", project.name)
                self.run_project(project, mode="sync", dry_run=False, trigger="auto")
            self._stop.wait(interval)
