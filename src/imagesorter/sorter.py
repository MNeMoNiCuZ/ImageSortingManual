"""The sorting queue: move an image plus its sidecars, and undo it again."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .scanner import is_image, scan_folder, sidecar_files

PENDING = "pending"
SORTED = "sorted"
SKIPPED = "skipped"


def unique_destination(destination: Path) -> Path:
    """`dir/name.ext` -> `dir/name (2).ext` if something is already there."""
    if not destination.exists():
        return destination
    stem, suffix, parent = destination.stem, destination.suffix, destination.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


@dataclass
class Item:
    """One image in the queue and what has happened to it."""

    path: Path
    status: str = PENDING
    category_id: str = ""
    applied: bool = True          # False while a decision is staged on disk
    record: "MoveRecord | None" = None


@dataclass
class MoveRecord:
    """One thing you did, with enough information to take it back.

    `kind` is "sort" for filing an image into a category and "skip" for
    passing over it. Both go in the same history, so Undo always takes back
    the last thing you did, whatever it was.
    """

    image_source: Path
    category_id: str
    category_name: str
    queue_index: int
    kind: str = "sort"
    copied: bool = False
    staged: bool = False          # decided, but nothing has been moved yet
    at_cursor: bool = True        # False when a look-ahead image was sorted
    previous_status: str = PENDING
    moves: list[tuple[Path, Path]] = field(default_factory=list)


class SortQueue:
    """Holds the images to sort, the cursor into them, and the undo history."""

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.index: int = 0
        self.selection: int | None = None   # a look-ahead pick, see `target`
        self.history: list[MoveRecord] = []

    # -- loading ---------------------------------------------------------
    def load(self, folder: str | Path, recursive: bool = True,
             order: str = "name") -> int:
        self.items = [Item(path) for path in scan_folder(folder, recursive, order)]
        self.index = 0
        self.selection = None
        self.history.clear()
        return len(self.items)

    def load_paths(self, paths: list[str | Path]) -> int:
        """Queue up an explicit list of images, in the order given."""
        self.items = [Item(Path(p)) for p in paths]
        self.index = 0
        self.selection = None
        self.history.clear()
        return len(self.items)

    def append_paths(self, paths: list[str | Path]) -> int:
        """Add more images to the end of the queue, leaving the rest alone."""
        before = len(self.items)
        for path in paths:
            self.items.append(Item(Path(path)))
        if self.current_item is None or self.current_item.status != PENDING:
            # The queue had run out; carry on with the new ones.
            self.index = self._next_pending(min(self.index, before))
            self.selection = None
        return len(self.items) - before

    def clear(self) -> None:
        self.items = []
        self.index = 0
        self.selection = None
        self.history.clear()

    @property
    def images(self) -> list[Path]:
        return [item.path for item in self.items]

    # -- cursor ----------------------------------------------------------
    @property
    def target(self) -> int:
        """The image the buttons and hotkeys act on: the picked one, else the
        one the queue is on."""
        if self.selection is not None and 0 <= self.selection < len(self.items):
            return self.selection
        return self.index

    def select(self, index: int | None) -> bool:
        """Look at another image without disturbing the queue."""
        if index is None or index == self.index:
            self.selection = None
            return True
        if not 0 <= index < len(self.items):
            return False
        self.selection = index
        return True

    @property
    def current(self) -> Path | None:
        item = self.current_item
        return item.path if item else None

    @property
    def current_item(self) -> Item | None:
        index = self.target
        if 0 <= index < len(self.items):
            return self.items[index]
        return None

    def count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def remaining(self) -> int:
        return self.count(PENDING)

    @property
    def staged_items(self) -> list["Item"]:
        """Decisions that have been made but not yet carried out on disk."""
        return [i for i in self.items if i.status == SORTED and not i.applied]

    def staged_for(self, category_id: str) -> int:
        return sum(1 for i in self.staged_items if i.category_id == category_id)

    @property
    def done(self) -> bool:
        """Every image has been sorted. Skipped ones still need a decision."""
        return bool(self.items) and self.remaining == 0 and self.count(SKIPPED) == 0

    def _next_pending(self, start: int) -> int:
        for i in range(max(0, start), len(self.items)):
            if self.items[i].status == PENDING:
                return i
        return len(self.items)

    def _after_action(self, acted_index: int) -> None:
        """Move on only when the queue itself was the thing acted on."""
        if acted_index == self.index:
            self._advance()
        self.selection = None

    def _advance(self) -> None:
        following = self._next_pending(self.index + 1)
        # Wrap around so undone or re-queued images earlier in the list are
        # not stranded behind the cursor.
        self.index = following if following < len(self.items) else self._next_pending(0)

    def upcoming(self, count: int) -> list[tuple[int, Path]]:
        """The current image and the pending ones after it, for the filmstrip."""
        result: list[tuple[int, Path]] = []
        for i in range(self.index, len(self.items)):
            if self.items[i].status == PENDING or i == self.index:
                result.append((i, self.items[i].path))
            if len(result) >= count:
                break
        return result

    def skip(self) -> bool:
        acted = self.target
        item = self.current_item
        if item is None or item.status != PENDING:
            return False
        record = MoveRecord(item.path, "", "Skipped", acted, kind="skip",
                            at_cursor=acted == self.index, previous_status=PENDING)
        item.status = SKIPPED
        item.record = record
        self.history.append(record)
        self._after_action(acted)
        return True

    def _forget_skip(self, item: Item) -> None:
        """A skip that has been taken back another way leaves the history."""
        if item.record is not None and item.record.kind == "skip":
            try:
                self.history.remove(item.record)
            except ValueError:
                pass
            item.record = None

    def restore_skipped(self, index: int) -> bool:
        """Put one skipped image back in the queue and look at it."""
        if not 0 <= index < len(self.items):
            return False
        item = self.items[index]
        if item.status != SKIPPED:
            return False
        item.status = PENDING
        self._forget_skip(item)
        self.selection = None if index == self.index else index
        return True

    def skipped_images(self) -> list[Path]:
        """The skipped images, most recently skipped first."""
        return [item.path for item in reversed(self.items) if item.status == SKIPPED]

    def review_skipped(self) -> int:
        """Put every skipped image back in the queue and jump to the first."""
        first = -1
        count = 0
        for i, item in enumerate(self.items):
            if item.status == SKIPPED:
                item.status = PENDING
                self._forget_skip(item)
                count += 1
                if first < 0:
                    first = i
        if first >= 0:
            self.index = first
            self.selection = None
        return count

    def goto(self, index: int) -> bool:
        if 0 <= index < len(self.items):
            self.index = index
            self.selection = None
            return True
        return False

    # -- sorting ---------------------------------------------------------
    def sort_current(self, category_id: str, category_name: str,
                     destination: str | Path, move_sidecars: bool = True,
                     sidecar_extensions: list[str] | None = None,
                     copy: bool = False) -> MoveRecord:
        acted = self.target
        item = self.current_item
        if item is None:
            raise RuntimeError("There is no image to sort.")
        image = item.path
        if not image.exists():
            raise FileNotFoundError(f"{image.name} is no longer on disk.")

        target_dir = Path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)

        sources = [image]
        if move_sidecars:
            sources.extend(sidecar_files(image, sidecar_extensions))

        record = MoveRecord(image, category_id, category_name, acted,
                            copied=copy, at_cursor=acted == self.index,
                            previous_status=item.status)
        try:
            for source in sources:
                target = unique_destination(target_dir / source.name)
                if copy:
                    shutil.copy2(str(source), str(target))
                else:
                    shutil.move(str(source), str(target))
                record.moves.append((source, target))
        except Exception:
            self._revert(record)
            raise

        if not copy:
            item.path = record.moves[0][1]
        item.status = SORTED
        item.category_id = category_id
        item.applied = True
        item.record = record
        self.history.append(record)
        self._after_action(acted)
        return record

    def assign_current(self, category_id: str, category_name: str) -> MoveRecord:
        """Record a decision without touching the files (deferred mode)."""
        acted = self.target
        item = self.current_item
        if item is None:
            raise RuntimeError("There is no image to sort.")
        record = MoveRecord(item.path, category_id, category_name, acted,
                            staged=True, at_cursor=acted == self.index,
                            previous_status=item.status)
        item.status = SORTED
        item.category_id = category_id
        item.applied = False
        item.record = record
        self.history.append(record)
        self._after_action(acted)
        return record

    def apply_staged(self, destination_for, move_sidecars: bool = True,
                     sidecar_extensions: list[str] | None = None,
                     copy: bool = False) -> tuple[int, list[str]]:
        """Carry out every staged decision. Returns (done, problems)."""
        done = 0
        problems: list[str] = []
        for item in self.staged_items:
            record = item.record
            try:
                target_dir = Path(destination_for(item.category_id))
            except Exception as exc:
                problems.append(str(exc))
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            sources = [item.path]
            if move_sidecars:
                sources.extend(sidecar_files(item.path, sidecar_extensions))

            moves: list[tuple[Path, Path]] = []
            try:
                for source in sources:
                    if not source.exists():
                        continue
                    target = unique_destination(target_dir / source.name)
                    if copy:
                        shutil.copy2(str(source), str(target))
                    else:
                        shutil.move(str(source), str(target))
                    moves.append((source, target))
            except Exception as exc:
                for source, target in reversed(moves):
                    if target.exists():
                        if copy:
                            target.unlink()
                        else:
                            shutil.move(str(target), str(source))
                problems.append(f"{item.path.name}: {exc}")
                continue

            if record is not None:
                record.moves = moves
                record.copied = copy
                record.staged = False
            if moves and not copy:
                item.path = moves[0][1]
            item.applied = True
            done += 1
        return done, problems

    def clear_category(self, category_id: str, folder: Path | None = None,
                       source: Path | None = None,
                       sidecar_extensions: list[str] | None = None
                       ) -> tuple[int, int, int]:
        """Empty a category: everything in it goes back to the source folder.

        Images this session put there return to exactly where they came from;
        anything else in the folder is moved to `source` and queued up. Returns
        (put back, decisions cancelled, extra files recovered).
        """
        put_back = cancelled = 0
        for record in [r for r in self.history
                       if r.kind == "sort" and r.category_id == category_id]:
            item = self.items[record.queue_index]
            if record.moves:
                self._revert(record)
                put_back += 1
            else:
                cancelled += 1
            item.path = record.image_source
            item.status = PENDING
            item.category_id = ""
            item.applied = True
            item.record = None
            self.history.remove(record)

        extra = 0
        if folder is not None and source is not None and folder.is_dir():
            known = {str(i.path) for i in self.items}
            try:
                leftovers = [p for p in sorted(folder.iterdir())
                             if p.is_file() and is_image(p) and str(p) not in known]
            except OSError:
                leftovers = []
            source.mkdir(parents=True, exist_ok=True)
            for image in leftovers:
                companions = sidecar_files(image, sidecar_extensions)
                try:
                    target = unique_destination(source / image.name)
                    shutil.move(str(image), str(target))
                except OSError:
                    continue
                for companion in companions:
                    try:
                        shutil.move(str(companion),
                                    str(unique_destination(source / companion.name)))
                    except OSError:
                        pass
                self.items.append(Item(target))
                extra += 1

        if put_back or cancelled or extra:
            self.index = min(self.index, self._next_pending(0))
            self.selection = None
        return put_back, cancelled, extra

    def sorted_here(self, category_id: str) -> tuple[int, int]:
        """(already on disk, still waiting) for one category, this session."""
        sorts = [r for r in self.history if r.kind == "sort" and r.category_id == category_id]
        on_disk = sum(1 for r in sorts if r.moves)
        waiting = sum(1 for r in sorts if not r.moves)
        return on_disk, waiting

    def discard_staged(self) -> int:
        """Throw the staged decisions away and put those images back in the queue."""
        staged = self.staged_items
        for item in staged:
            if item.record is not None:
                try:
                    self.history.remove(item.record)
                except ValueError:
                    pass
            item.status = item.record.previous_status if item.record else PENDING
            if item.status == SORTED:
                item.status = PENDING
            item.category_id = ""
            item.applied = True
            item.record = None
        if staged:
            self.index = self._next_pending(0)
        return len(staged)

    # -- undo ------------------------------------------------------------
    def can_undo(self) -> bool:
        return bool(self.history)

    def undo(self) -> MoveRecord:
        """Take back the last action, whether it was a sort or a skip."""
        if not self.history:
            raise RuntimeError("Nothing to undo.")
        record = self.history.pop()
        item = self.items[record.queue_index]

        if record.kind != "skip":
            self._revert(record)
            item.path = record.image_source
            item.category_id = ""
            item.applied = True
        item.status = PENDING
        item.record = None

        if record.at_cursor:
            self.index = record.queue_index
            self.selection = None
        else:
            self.selection = record.queue_index
        return record

    @staticmethod
    def _revert(record: MoveRecord) -> None:
        for source, target in reversed(record.moves):
            if not target.exists():
                continue
            if record.copied:
                target.unlink()
            else:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        record.moves.clear()
