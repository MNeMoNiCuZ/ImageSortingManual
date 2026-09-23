"""Application state: settings, the loaded project and the live sorting queue."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from . import thumbnails
from .config import AppConfig
from .models import Category, Project, suggest_hotkeys
from .project import load_project, save_project
from .scanner import (count_images, duplicate_stems, is_image, scan_folder,
                      sidecar_files, sort_paths)
from .sorter import PENDING, SKIPPED, SORTED, SortQueue

UPCOMING_COUNT = 14

# The Skipped card is not a real category, but it behaves like one for
# previews and for dropping images onto it.
SKIPPED_ID = "skipped"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


class FolderStats:
    """Image counts per destination folder, refreshed when the folder changes."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, int]] = {}

    def count(self, folder: Path | None) -> int:
        if folder is None or not folder.is_dir():
            return 0
        key = str(folder)
        try:
            stamp = folder.stat().st_mtime
        except OSError:
            return 0
        cached = self._cache.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
        total = count_images(folder)
        self._cache[key] = (stamp, total)
        return total

    def invalidate(self) -> None:
        self._cache.clear()


class Session:
    """One sorting session. The server owns exactly one of these."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config if config is not None else AppConfig.load()
        self.project = Project.with_defaults()
        self.queue = SortQueue()
        self.project_path: Path | None = None
        self.warnings: list[str] = []
        self.folders = FolderStats()
        self.image_list: list[Path] = []     # set when images were dropped in
        self.resume_dismissed = False
        self.status: str = "Pick an image folder to begin."

    # -- settings ---------------------------------------------------------
    def save_config(self) -> None:
        self.config.normalise().save()

    def update_settings(self, changes: dict[str, Any]) -> None:
        rescan_keys = {"recursive", "sort_order"}
        needs_rescan = any(
            key in changes and changes[key] != getattr(self.config, key, None)
            for key in rescan_keys
        )
        skip_hotkey = str(changes.get("skip_hotkey") or "").strip()
        if skip_hotkey:
            clash = next((c for c in self.project.categories
                          if c.hotkey and c.hotkey.upper() == skip_hotkey.upper()), None)
            if clash is not None:
                raise ValueError(
                    f"Hotkey {skip_hotkey} is already used by '{clash.name}'."
                )
        for key, value in changes.items():
            if value is not None and hasattr(self.config, key):
                setattr(self.config, key, value)
        if changes.get("autosave") is False:
            # Turning it off should forget what it already kept, or the app
            # would still offer it back on the next start.
            self.config.last_session = {}
        self.config.normalise()
        self.save_config()
        self.folders.invalidate()
        if needs_rescan and self.project.source_folder:
            self.reload_images()
        else:
            self.status = "Settings saved."

    # -- autosave -----------------------------------------------------------
    def autosave(self) -> None:
        """Keep a copy of the current setup so the next run can offer it back."""
        if not self.config.autosave:
            return
        if self.untouched:
            return
        self.config.last_session = {
            "source_folder": self.project.source_folder,
            "images": [str(p) for p in self.image_list],
            "categories": [c.to_dict() for c in self.project.categories],
            "project": str(self.project_path) if self.project_path else "",
            "saved_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        self.save_config()

    @property
    def untouched(self) -> bool:
        """Nothing has been set up in this run yet."""
        return (self.project.is_pristine and not self.project.source_folder
                and not self.image_list)

    def resume_offer(self) -> dict[str, Any]:
        saved = self.config.last_session or {}
        available = bool(
            self.config.autosave and not self.resume_dismissed and self.untouched
            and (saved.get("categories") or saved.get("source_folder")
                 or saved.get("images"))
        )
        return {
            "available": available,
            "categories": len(saved.get("categories") or []),
            "source_folder": saved.get("source_folder", ""),
            "images": len(saved.get("images") or []),
            "project": saved.get("project", ""),
            "saved_at": saved.get("saved_at", ""),
        }

    def resume(self) -> None:
        saved = self.config.last_session or {}
        if not saved:
            raise ValueError("There is nothing saved to carry on from.")
        self.project = Project.from_dict(saved)
        self.project_path = Path(saved["project"]) if saved.get("project") else None
        self.resume_dismissed = True
        self.image_list = []

        dropped = [p for p in (saved.get("images") or []) if Path(p).is_file()]
        if dropped:
            self.set_images(dropped)
            lost = len(saved["images"]) - len(dropped)
            if lost:
                self.warnings.append(f"{lost} of last time's images are gone.")
        elif self.project.source_folder and Path(self.project.source_folder).is_dir():
            self.reload_images()
        else:
            self.queue.clear()
            if self.project.source_folder:
                self.warnings.append(
                    f"Last time's image folder is gone: {self.project.source_folder}"
                )
            elif saved.get("images"):
                self.warnings.append("Last time's images are no longer where they were.")
        count = len(self.project.categories)
        self.status = f"Carried on from last time with {count} categor{'y' if count == 1 else 'ies'}."

    def dismiss_resume(self) -> None:
        self.resume_dismissed = True
        self.status = "Starting fresh."

    # -- folder / project -------------------------------------------------
    def set_folder(self, folder: str) -> None:
        path = Path(folder).expanduser()
        if not path.is_dir():
            raise NotADirectoryError(f"{folder} is not a folder.")
        self.project.source_folder = str(path)
        self.image_list = []
        self.resume_dismissed = True
        self.reload_images()
        self.autosave()

    def set_images(self, paths: list[str]) -> int:
        """Sort a hand-picked set of images, wherever they live.

        They keep their own folders: nothing is collapsed to a single source,
        and every image goes back to where it came from if it is undone or its
        category is cleared.
        """
        images = [Path(p) for p in paths]
        images = [p for p in images if p.is_file() and is_image(p)]
        if not images:
            raise ValueError("None of those are images that are still here.")

        self.image_list = images
        # One folder behaves exactly like opening that folder; several do not
        # get flattened into one.
        self._recalculate_source()
        self.resume_dismissed = True
        count = self._apply_image_list()
        self.autosave()
        return count

    def _apply_image_list(self) -> int:
        alive = [p for p in self.image_list if p.is_file()]
        lost = len(self.image_list) - len(alive)
        self.image_list = alive
        count = self.queue.load_paths(sort_paths(alive, self.config.sort_order))
        self._describe_input(extra=[f"{lost} of the dropped image(s) are no longer there."]
                             if lost else [])
        thumbnails.clear()
        self.folders.invalidate()
        folders = len({p.parent for p in alive})
        self.status = f"Loaded {count} dropped image(s) from {folders} folder(s)."
        return count

    def _describe_input(self, extra: list[str] | None = None) -> None:
        """Recalculate the warnings that describe the current set of images."""
        self.warnings = list(extra or [])
        images = self.queue.images
        duplicates = duplicate_stems(images)
        if duplicates:
            self.warnings.append(
                f"{len(duplicates)} of these share a name with another one; "
                "the second one to land in a category folder gets renamed."
            )
        if self.image_list:
            folders = len({p.parent for p in self.image_list})
            if folders > 1:
                self.warnings.append(
                    f"These {len(images)} images come from {folders} folders. Each one "
                    "goes back to its own folder if you undo it or clear its category."
                )

    def _recalculate_source(self) -> None:
        parents = {p.parent for p in self.image_list}
        self.project.source_folder = str(next(iter(parents))) if len(parents) == 1 else ""

    def add_images(self, paths: list[str]) -> int:
        """Add images to what is already being sorted, rather than replacing it."""
        if not self.queue.items:
            return self.set_images(paths)

        incoming = [Path(p) for p in paths]
        incoming = [p for p in incoming if p.is_file() and is_image(p)]
        if not incoming:
            raise ValueError("None of those are images that are still here.")

        known = {str(p) for p in self.queue.images}
        fresh = [p for p in incoming if str(p) not in known]
        if not fresh:
            self.status = "Those images are already in the list."
            return 0

        # Adding to a folder scan turns it into an explicit list, so that a
        # later rescan keeps what was added.
        if not self.image_list:
            self.image_list = list(self.queue.images)
        ordered = sort_paths(fresh, self.config.sort_order)
        self.image_list.extend(ordered)

        added = self.queue.append_paths(ordered)
        self._recalculate_source()
        self._describe_input()
        self.folders.invalidate()
        self.resume_dismissed = True
        self.status = f"Added {added} image(s); {self.queue.remaining} left to sort."
        self.autosave()
        return added

    def add_folder(self, folder: str) -> int:
        """Add every image in a folder to what is already loaded."""
        path = Path(folder).expanduser()
        if not path.is_dir():
            raise NotADirectoryError(f"{folder} is not a folder.")
        if not self.queue.items:
            self.set_folder(folder)
            return len(self.queue.items)
        found = scan_folder(path, self.config.recursive, self.config.sort_order)
        if not found:
            raise ValueError(f"There are no images in {path.name}.")
        return self.add_images([str(p) for p in found])

    def clear_input(self) -> int:
        """Throw away the images, keep the categories and the settings."""
        had = len(self.queue.items)
        self.queue.clear()
        self.image_list = []
        self.project.source_folder = ""
        self.warnings = []
        thumbnails.clear()
        self.folders.invalidate()
        self.status = ("Cleared the input. Your categories are still here."
                       if had else "There was nothing loaded.")
        if self.untouched:
            # Nothing is left to remember, and `autosave` will not overwrite a
            # saved session with an empty one - so drop it here, or the images
            # that were just cleared come back as next run's resume offer.
            self.config.last_session = {}
            self.save_config()
        self.autosave()
        return had

    def reload_images(self) -> None:
        if self.image_list:
            self._apply_image_list()     # a dropped set is not a folder to rescan
            return
        self.warnings = []
        if not self.project.source_folder:
            self.queue.clear()
            return
        count = self.queue.load(
            self.project.source_folder, self.config.recursive, self.config.sort_order
        )
        duplicates = duplicate_stems(self.queue.images)
        if duplicates:
            sample = ", ".join(sorted(duplicates)[:5])
            tail = "..." if len(duplicates) > 5 else ""
            self.warnings.append(
                f"{len(duplicates)} file name(s) appear in more than one folder "
                f"({sample}{tail}). They will be renamed if they land in the "
                "same category folder."
            )
        thumbnails.clear()
        self.folders.invalidate()
        self.status = f"Loaded {count} image(s)." if count else "No images found in that folder."

    def load_project_file(self, path: str) -> None:
        self.project = load_project(path)
        self.image_list = []
        self.project_path = Path(path)
        if self.config.remember_last_project:
            self.config.last_project = str(self.project_path)
            self.save_config()
        if self.project.source_folder and Path(self.project.source_folder).is_dir():
            self.reload_images()
        else:
            self.queue.clear()
            if self.project.source_folder:
                self.warnings.append(
                    f"The project's image folder is missing: {self.project.source_folder}"
                )
        self.resume_dismissed = True
        self.status = f"Loaded project {self.project_path.name}."
        self.autosave()

    def save_project_file(self, path: str | None = None) -> Path:
        target = Path(path) if path else self.project_path
        if target is None:
            raise ValueError("No project path given.")
        self.project_path = save_project(self.project, target)
        if self.config.remember_last_project:
            self.config.last_project = str(self.project_path)
            self.save_config()
        self.status = f"Saved project to {self.project_path.name}."
        self.autosave()
        return self.project_path

    # -- categories -------------------------------------------------------
    def sorting_setup(self) -> dict[str, Any]:
        """Validate destinations before exposing sorting controls."""
        if not self.project.categories:
            return {"ready": False, "error": "Set up categories before sorting."}
        try:
            for category in self.project.categories:
                folder = self._destination(category)
                if not folder.is_absolute():
                    raise ValueError("Choose an absolute output folder before sorting.")
                ancestor = folder
                while not ancestor.exists() and ancestor != ancestor.parent:
                    ancestor = ancestor.parent
                if not ancestor.is_dir() or not os.access(ancestor, os.W_OK):
                    raise ValueError(f"Output folder is not writable: {folder}")
        except (ValueError, OSError) as exc:
            return {"ready": False, "error": str(exc)}
        return {"ready": True, "error": ""}

    def require_sorting_setup(self) -> None:
        setup = self.sorting_setup()
        if not setup["ready"]:
            raise ValueError(setup["error"])

    def _destination(self, category: Category) -> Path:
        folder = category.resolve(self.config.output_root)
        if folder is None:
            raise ValueError(
                f"Category '{category.name}' has a relative folder "
                f"('{category.folder}') but no output root is set. "
                "Set one in Settings, or give it a full path."
            )
        return folder

    def add_category(self, name: str, folder: str, hotkey: str = "",
                     color: str = "") -> Category:
        category = Category(
            name=name.strip() or "Unnamed",
            folder=folder.strip(),
            hotkey=hotkey.strip(),
            color=color or self.project.next_color(),
        )
        self.project.categories.append(category)
        self.status = f"Added category '{category.name}'."
        self.autosave()
        return category

    def update_category(self, category_id: str, **fields: Any) -> Category:
        category = self.project.find(category_id)
        if category is None:
            raise KeyError(category_id)
        if "name" in fields:
            category.name = str(fields["name"]).strip() or category.name
        if "folder" in fields and fields["folder"] is not None:
            category.folder = str(fields["folder"]).strip()
        if "hotkey" in fields:
            category.hotkey = str(fields["hotkey"] or "").strip()
        if "color" in fields and fields["color"]:
            category.color = str(fields["color"])
        self.status = f"Updated category '{category.name}'."
        self.autosave()
        return category

    def delete_category(self, category_id: str) -> None:
        category = self.project.find(category_id)
        if category is None:
            raise KeyError(category_id)
        self.project.categories.remove(category)
        self.status = f"Removed category '{category.name}'."
        self.autosave()

    def replace_categories(self, rows: list[dict[str, Any]]) -> None:
        """Save the whole category table in one go."""
        categories: list[Category] = []
        seen_hotkeys: dict[str, str] = {}
        for row in rows:
            if not str(row.get("name", "")).strip():
                continue
            category = Category.from_dict(row)
            if category.hotkey:
                key = category.hotkey.upper()
                if key == (self.config.skip_hotkey or "").upper():
                    raise ValueError(
                        f"Hotkey {category.hotkey} is already used by Skip."
                    )
                if key in seen_hotkeys:
                    raise ValueError(
                        f"Hotkey {category.hotkey} is used by both "
                        f"'{seen_hotkeys[key]}' and '{category.name}'."
                    )
                seen_hotkeys[key] = category.name
            categories.append(category)
        self.project.categories = categories
        self.folders.invalidate()
        self.status = f"Saved {len(categories)} categor{'y' if len(categories) == 1 else 'ies'}."
        self.autosave()

    def add_categories_bulk(self, names: list[str]) -> list[Category]:
        """Create one category per name, folder = name, auto hotkey and colour."""
        clean = [n.strip() for n in names if n.strip()]
        taken = {c.hotkey for c in self.project.categories if c.hotkey}
        hotkeys = suggest_hotkeys(clean, taken)
        created = []
        for name, hotkey in zip(clean, hotkeys):
            created.append(self.add_category(name, name, hotkey))
        self.status = f"Added {len(created)} categories."
        self.autosave()
        return created

    def create_category_folders(self) -> int:
        made = 0
        for category in self.project.categories:
            try:
                folder = self._destination(category)
            except ValueError:
                continue
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                made += 1
        self.folders.invalidate()
        self.status = f"Created {made} folder(s)."
        return made

    # -- presets ----------------------------------------------------------
    def save_preset(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("A preset needs a name.")
        if not self.project.categories:
            raise ValueError("There are no categories to save.")
        self.config.presets[name] = [c.to_dict() for c in self.project.categories]
        self.save_config()
        self.status = f"Saved preset '{name}'."

    def load_preset(self, name: str, replace: bool = True) -> None:
        rows = self.config.presets.get(name)
        if rows is None:
            raise KeyError(name)
        categories = [Category.from_dict(row) for row in rows]
        if replace:
            self.project.categories = categories
        else:
            self.project.categories.extend(categories)
        self.folders.invalidate()
        self.status = f"Loaded preset '{name}'."
        self.autosave()

    def delete_preset(self, name: str) -> None:
        if name not in self.config.presets:
            raise KeyError(name)
        del self.config.presets[name]
        self.save_config()
        self.status = f"Deleted preset '{name}'."

    # -- actions ----------------------------------------------------------
    def sort_current(self, category_id: str) -> None:
        self.require_sorting_setup()
        category = self.project.find(category_id)
        if category is None:
            raise KeyError(category_id)
        # Resolve the destination even in deferred mode, so a broken category
        # is reported when you press the key, not an hour later on Apply.
        destination = self._destination(category)

        if self.config.deferred:
            record = self.queue.assign_current(category.id, category.name)
            verb = "Will copy" if self.config.copying else "Will move"
            self.status = (f"{verb} {record.image_source.name} to {category.name} "
                           f"({len(self.queue.staged_items)} change(s) waiting).")
            return

        record = self.queue.sort_current(
            category.id, category.name, destination,
            move_sidecars=self.config.move_sidecars,
            sidecar_extensions=self.config.sidecar_extensions,
            copy=self.config.copying,
        )
        extra = len(record.moves) - 1
        suffix = f" + {extra} sidecar file(s)" if extra else ""
        verb = "Copied" if self.config.copying else "Moved"
        self.folders.invalidate()
        self.status = f"{verb} {record.image_source.name}{suffix} to {category.name}."

    def apply_staged(self) -> tuple[int, list[str]]:
        if any(self.project.find(item.category_id) is None for item in self.queue.staged_items):
            return 0, ["A staged image points at a category that is gone."]
        setup = self.sorting_setup()
        if not setup["ready"]:
            return 0, [setup["error"]]

        def destination_for(category_id: str) -> Path:
            category = self.project.find(category_id)
            if category is None:
                raise ValueError("A staged image points at a category that is gone.")
            return self._destination(category)

        done, problems = self.queue.apply_staged(
            destination_for,
            move_sidecars=self.config.move_sidecars,
            sidecar_extensions=self.config.sidecar_extensions,
            copy=self.config.copying,
        )
        self.folders.invalidate()
        verb = "Copied" if self.config.copying else "Moved"
        self.status = f"{verb} {done} image(s)."
        self.warnings = problems
        if problems:
            self.status += f" {len(problems)} failed."
        return done, problems

    def discard_staged(self) -> int:
        count = self.queue.discard_staged()
        self.status = (f"Discarded {count} staged change(s)." if count
                       else "Nothing was waiting.")
        return count

    def select(self, index: int | None) -> None:
        if not self.queue.select(index):
            raise ValueError("No such image.")
        item = self.queue.current_item
        self.status = (f"Looking at {item.path.name}." if item and self.queue.selection is not None
                       else "Back to the queue.")

    def clear_category(self, category_id: str) -> tuple[int, int, int]:
        """Send a category's images back to the source folder."""
        category = self.project.find(category_id)
        if category is None:
            raise KeyError(category_id)
        try:
            folder = self._destination(category)
        except ValueError:
            folder = None
        source = Path(self.project.source_folder) if self.project.source_folder else None

        put_back, cancelled, extra = self.queue.clear_category(
            category_id, folder, source, self.config.sidecar_extensions)
        self.folders.invalidate()

        parts = []
        if put_back:
            parts.append(f"put {put_back} image(s) back where they came from")
        if extra:
            parts.append(f"moved {extra} other image(s) to the source folder")
        if cancelled:
            parts.append(f"cancelled {cancelled} waiting decision(s)")
        if source is None and folder is not None and count_images(folder):
            self.warnings = [
                f"{count_images(folder)} image(s) that this session did not put in "
                f"{category.name} were left alone: these images came from several "
                "folders, so there is no one place to send them."
            ]
        self.status = (f"Cleared {category.name}: {', '.join(parts)}." if parts
                       else f"{category.name} was already empty.")
        return put_back, cancelled, extra

    def clear_output(self) -> None:
        """Clear every category using the same restoration rules as a single clear."""
        warnings = []
        try:
            for category in self.project.categories:
                self.warnings = []
                self.clear_category(category.id)
                warnings.extend(self.warnings)
        finally:
            self.folders.invalidate()
            self.warnings = list(dict.fromkeys(warnings + self.warnings))
        self.status = "Output cleared."

    def skip(self) -> None:
        self.status = "Skipped." if self.queue.skip() else "Nothing left to skip."

    def review_skipped(self) -> None:
        count = self.queue.review_skipped()
        self.status = (f"Re-queued {count} skipped image(s)." if count
                       else "Nothing has been skipped.")

    def undo(self) -> None:
        record = self.queue.undo()
        self.folders.invalidate()
        self.status = (f"Un-skipped {record.image_source.name}." if record.kind == "skip"
                       else f"Undid {record.image_source.name} → {record.category_name}.")

    def restore_skipped(self, index: int) -> None:
        if not self.queue.restore_skipped(index):
            raise ValueError("That image is not in the skipped group.")
        item = self.queue.items[index]
        self.status = f"{item.path.name} is back in the queue."

    # -- state ------------------------------------------------------------
    def category_state(self, category: Category) -> dict[str, Any]:
        try:
            destination = self._destination(category)
            problem = ""
        except ValueError as exc:
            destination = None
            problem = str(exc)
        return {
            **category.to_dict(),
            "resolved": str(destination) if destination else "",
            "relative": bool(category.folder) and not category.is_absolute,
            "exists": bool(destination and destination.is_dir()),
            "in_folder": self.folders.count(destination),
            "count": self.folders.count(destination) + self.queue.staged_for(category.id),
            "staged_here": self.queue.staged_for(category.id),
            "sorted_here": sum(1 for item in self.queue.items
                               if item.category_id == category.id),
            "clearable": (self.folders.count(destination)
                          + self.queue.staged_for(category.id)),
            "clearable_on_disk": self.folders.count(destination),
            "problem": problem,
        }

    def category_previews(self, category_id: str, limit: int = 12) -> list[Path]:
        """Images to show on a category's card: what is waiting first, then
        what is already in the folder, newest first."""
        if category_id == SKIPPED_ID:
            return self.queue.skipped_images()[:max(0, limit)]
        category = self.project.find(category_id)
        if category is None or limit <= 0:
            return []

        waiting = [item.path for item in reversed(self.queue.staged_items)
                   if item.category_id == category_id]

        in_folder: list[Path] = []
        try:
            destination = self._destination(category)
            if destination.is_dir():
                in_folder = sorted(
                    (p for p in destination.iterdir() if p.is_file() and is_image(p)),
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
        except (ValueError, OSError):
            pass

        previews: list[Path] = []
        seen: set[str] = set()
        for path in waiting + in_folder:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            previews.append(path)
            if len(previews) >= limit:
                break
        return previews

    def category_preview(self, category_id: str) -> Path | None:
        previews = self.category_previews(category_id, 1)
        return previews[0] if previews else None

    def source_label(self) -> str:
        """What to show where the source folder normally goes."""
        if self.project.source_folder:
            return self.project.source_folder
        if self.image_list:
            folders = len({p.parent for p in self.image_list})
            return (f"{len(self.image_list)} dropped image(s) "
                    f"from {folders} folder{'s' if folders != 1 else ''}")
        return ""

    def current_info(self) -> dict[str, Any] | None:
        image = self.queue.current
        if image is None:
            return None
        info: dict[str, Any] = {
            "index": self.queue.target,
            "name": image.name,
            "path": str(image),
            "folder": str(image.parent),
            "sidecars": [p.suffix.lstrip(".") or p.name
                         for p in sidecar_files(image, self.config.sidecar_extensions)],
        }
        try:
            info["size"] = human_size(image.stat().st_size)
        except OSError:
            info["size"] = "?"
        try:
            info["width"], info["height"] = thumbnails.dimensions(image)
        except Exception:
            info["width"] = info["height"] = 0
        return info

    def state(self) -> dict[str, Any]:
        total = len(self.queue.items)
        pending = self.queue.count(PENDING)
        return {
            "config": self.config.to_dict(),
            "setup": self.sorting_setup(),
            "project": {
                "source_folder": self.project.source_folder,
                "source_label": self.source_label(),
                "dropped": bool(self.image_list),
                "folders": len({p.parent for p in self.image_list}) if self.image_list else 0,
                "path": str(self.project_path) if self.project_path else "",
            },
            "categories": [self.category_state(c) for c in self.project.categories],
            "presets": sorted(self.config.presets),
            "resume": self.resume_offer(),
            "total": total,
            "revision": self.queue.revision,
            "index": self.queue.index,
            "selection": self.queue.selection,
            "target": self.queue.target,
            "position": self.queue.index + 1 if self.queue.current else 0,
            "pending": pending,
            "skipped": self.queue.count(SKIPPED),
            "sorted": self.queue.count(SORTED),
            "staged": len(self.queue.staged_items),
            "can_undo": self.queue.can_undo(),
            "done": self.queue.done,
            "current": self.current_info(),
            "upcoming": [
                {"index": index, "name": path.name}
                for index, path in self.queue.upcoming(UPCOMING_COUNT)
            ],
            "warnings": self.warnings,
            "status": self.status,
        }
