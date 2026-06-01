from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles


WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def mount_web(app) -> None:
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
