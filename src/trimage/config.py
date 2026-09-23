"""Application settings and category presets, stored in `config.json`.

The file lives next to the executable (frozen build) or in the repository root
(running from source), so it is easy to find, edit by hand, or .gitignore.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_NAME = "config.json"

SORT_ORDERS = ("name", "newest", "oldest", "largest", "smallest", "random")
IMAGE_FITS = ("contain", "cover", "actual")
FILE_ACTIONS = ("move", "copy")
THUMB_RATIOS = {"vertical": 9 / 16, "horizontal": 16 / 9, "square": 1.0}
APPLY_MODES = ("immediate", "deferred")
CARD_LAYOUTS = ("grid", "rows", "columns")


def app_root() -> Path:
    """Where `config.json` lives."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def config_path() -> Path:
    return app_root() / CONFIG_NAME


@dataclass
class AppConfig:
    """Everything that is a preference rather than part of a project."""

    # where relative category folders are created
    output_root: str = ""
    # scanning
    recursive: bool = True
    sort_order: str = "name"
    # sorting behaviour
    file_action: str = "move"        # move | copy
    apply_mode: str = "deferred"     # immediate | deferred (apply on demand)
    move_sidecars: bool = True
    sidecar_extensions: list[str] = field(default_factory=list)  # empty = every extension
    create_folders_upfront: bool = False
    # the key that skips the current image; blank means no keyboard skip
    skip_hotkey: str = "Ctrl+X"
    # view
    show_filmstrip: bool = True
    filmstrip_size: int = 150       # dragged, not set in the settings dialog
    dock_height: int = 210          # ditto
    full_height_strip: bool = True
    show_card_thumbnails: bool = True
    card_thumb_size: int = 56
    thumb_ratio: str = "vertical"   # vertical | horizontal | square
    card_layout: str = "grid"       # grid | rows | columns
    show_card_counts: bool = True
    image_fit: str = "contain"
    # startup
    autosave: bool = True
    remember_last_project: bool = True
    last_project: str = ""
    # the setup as it was when the app was last used, offered on the next start
    last_session: dict[str, Any] = field(default_factory=dict)
    # saved category sets, name -> list of category dicts
    presets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Where this config came from / goes back to. Not a stored field.
        self._file: Path | None = None

    @property
    def file(self) -> Path:
        return self._file or config_path()

    # -- validation ------------------------------------------------------
    def normalise(self) -> "AppConfig":
        if self.sort_order not in SORT_ORDERS:
            self.sort_order = "name"
        if self.image_fit not in IMAGE_FITS:
            self.image_fit = "contain"
        if self.file_action not in FILE_ACTIONS:
            self.file_action = "move"
        if self.apply_mode not in APPLY_MODES:
            self.apply_mode = "deferred"
        if self.thumb_ratio not in THUMB_RATIOS:
            self.thumb_ratio = "vertical"
        if self.card_layout not in CARD_LAYOUTS:
            self.card_layout = "grid"
        self.filmstrip_size = max(80, min(500, int(self.filmstrip_size)))
        self.dock_height = max(132, min(700, int(self.dock_height)))
        self.card_thumb_size = max(32, min(140, int(self.card_thumb_size)))
        self.skip_hotkey = str(self.skip_hotkey or "").strip()
        self.sidecar_extensions = [
            ext.strip().lstrip(".").lower()
            for ext in self.sidecar_extensions if str(ext).strip()
        ]
        return self

    # -- persistence -----------------------------------------------------
    @property
    def aspect(self) -> float:
        """Thumbnail width / height."""
        return THUMB_RATIOS[self.thumb_ratio]

    @property
    def copying(self) -> bool:
        return self.file_action == "copy"

    @property
    def deferred(self) -> bool:
        return self.apply_mode == "deferred"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {f for f in cls.__dataclass_fields__}
        values = {k: v for k, v in data.items() if k in known}
        # Config written before move/copy became a named choice.
        if "file_action" not in values and data.get("copy_instead_of_move"):
            values["file_action"] = "copy"
        return cls(**values).normalise()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        target = Path(path) if path else config_path()
        if not target.is_file():
            fresh = cls()
            fresh._file = target
            return fresh
        try:
            loaded = cls.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError):
            # A corrupt config must never stop the app from starting.
            loaded = cls()
        loaded._file = target
        return loaded

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self.file
        self._file = target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return target

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
