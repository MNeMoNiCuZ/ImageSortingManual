"""Reading and writing .json project files."""
from __future__ import annotations

import json
from pathlib import Path

from .models import Project


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Project.from_dict(data)


def save_project(project: Project, path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
    return target
