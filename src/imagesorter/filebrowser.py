"""A tiny server-side folder browser.

The desktop build can open a native dialog, but the browser build cannot, so the
UI needs a folder picker it can drive over HTTP. Both use this.
"""
from __future__ import annotations

import string
import sys
from pathlib import Path
from typing import Any

from .scanner import IMAGE_EXTENSIONS


def drives() -> list[str]:
    """Drive roots on Windows, `/` elsewhere."""
    if sys.platform != "win32":
        return ["/"]
    return [f"{letter}:\\" for letter in string.ascii_uppercase
            if Path(f"{letter}:\\").exists()]


def home() -> str:
    return str(Path.home())


def listing(path: str | None = None) -> dict[str, Any]:
    """Sub-folders of `path`, plus a rough count of images directly inside it."""
    target = Path(path).expanduser() if path else Path.home()
    if not target.is_dir():
        target = Path.home()
    target = target.resolve()

    folders: list[dict[str, Any]] = []
    images = 0
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.is_dir():
                    if not entry.name.startswith("."):
                        folders.append({"name": entry.name, "path": str(entry)})
                elif entry.suffix.lower() in IMAGE_EXTENSIONS:
                    images += 1
            except OSError:
                continue
    except PermissionError:
        return {
            "path": str(target),
            "parent": str(target.parent) if target.parent != target else "",
            "folders": [],
            "images": 0,
            "drives": drives(),
            "error": "Permission denied.",
        }

    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else "",
        "folders": folders,
        "images": images,
        "drives": drives(),
        "error": "",
    }


def create_folder(parent: str, name: str) -> str:
    folder = Path(parent).expanduser() / name.strip()
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder.resolve())
