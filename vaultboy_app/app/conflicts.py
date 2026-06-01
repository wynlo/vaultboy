from __future__ import annotations

from datetime import datetime
from pathlib import Path


def conflict_path(destination: Path, relative_path: str) -> Path:
    original = destination / relative_path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if original.suffix:
        stem = original.name[: -len(original.suffix)]
        filename = f"{stem}.conflict-{stamp}{original.suffix}"
    else:
        filename = f"{original.name}.conflict-{stamp}.md"
    return original.with_name(filename)
