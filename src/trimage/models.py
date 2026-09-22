"""Data model for projects and categories."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Palette used to auto-assign a colour to new categories.
CATEGORY_COLORS = [
    "#4f8ef7", "#f7794f", "#3fb98a", "#c264e0",
    "#e4b23c", "#3fb6c9", "#e0648f", "#8a7ef0",
]


# What a fresh start begins with: keep / maybe / discard on the home row.
DEFAULT_CATEGORIES = [
    {"name": "Keep", "folder": "Keep", "hotkey": "A", "color": "#3fb98a"},
    {"name": "Maybe", "folder": "Maybe", "hotkey": "S", "color": "#e4a13c"},
    {"name": "Discard", "folder": "Discard", "hotkey": "D", "color": "#e05a77"},
]


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Category:
    """A sorting destination: a name, a target folder and an optional hotkey.

    `folder` may be an absolute path, or a plain name that is resolved against
    the configured output root - so a project can be moved between machines.
    """

    name: str
    folder: str = ""
    hotkey: str = ""
    color: str = CATEGORY_COLORS[0]
    id: str = field(default_factory=_new_id)

    @property
    def is_absolute(self) -> bool:
        return bool(self.folder) and Path(self.folder).is_absolute()

    def resolve(self, output_root: str = "") -> Path | None:
        """The real destination folder, or None if it cannot be worked out."""
        if not self.folder:
            return None
        folder = Path(self.folder).expanduser()
        if folder.is_absolute():
            return folder
        if not output_root:
            return None
        return Path(output_root).expanduser() / folder

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Category":
        # "path" is the key used by v1 projects and by earlier v2 builds.
        folder = data.get("folder") or data.get("path") or ""
        return cls(
            name=data.get("name", "Unnamed"),
            folder=folder,
            hotkey=data.get("hotkey") or "",
            color=data.get("color") or CATEGORY_COLORS[0],
            id=data.get("id") or _new_id(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Project:
    """The part of the setup that belongs to a job, saved as a .json file."""

    source_folder: str = ""
    categories: list[Category] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        # Accept the legacy v1 format ("chosen_folder", categories with "path").
        folder = data.get("source_folder") or data.get("chosen_folder") or ""
        raw = data.get("categories") or []
        categories = [Category.from_dict(c) for c in raw]
        for i, category in enumerate(categories):
            if "color" not in raw[i]:
                category.color = CATEGORY_COLORS[i % len(CATEGORY_COLORS)]
        return cls(source_folder=folder, categories=categories)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_folder": self.source_folder,
            "categories": [c.to_dict() for c in self.categories],
        }

    @property
    def is_pristine(self) -> bool:
        """True while nothing has been set up: the starting three, or none."""
        if not self.categories:
            return True
        return [
            (c.name, c.folder, c.hotkey, c.color) for c in self.categories
        ] == [
            (d["name"], d["folder"], d["hotkey"], d["color"]) for d in DEFAULT_CATEGORIES
        ]

    @classmethod
    def with_defaults(cls) -> "Project":
        """A new project starts with Keep / Maybe / Discard, ready to use."""
        return cls(categories=[Category.from_dict(c) for c in DEFAULT_CATEGORIES])

    def next_color(self) -> str:
        return CATEGORY_COLORS[len(self.categories) % len(CATEGORY_COLORS)]

    def find(self, category_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == category_id), None)


def suggest_hotkeys(names: list[str], taken: set[str]) -> list[str]:
    """Pick an unused single-key hotkey per name, preferring its first letter."""
    used = {t.upper() for t in taken if t}
    result: list[str] = []
    for name in names:
        candidates = [c.upper() for c in name if c.isalnum()]
        candidates += list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        choice = next((c for c in candidates if c not in used), "")
        if choice:
            used.add(choice)
        result.append(choice)
    return result
