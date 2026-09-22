"""Discovery of images and their sidecar files."""
from __future__ import annotations

import random
from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".tif", ".tiff", ".avif", ".jfif",
}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _sort_key(order: str):
    def by_name(path: Path):
        return (str(path.parent).lower(), path.name.lower())

    def stat_or(path: Path, attribute: str, fallback: float = 0.0) -> float:
        try:
            return float(getattr(path.stat(), attribute))
        except OSError:
            return fallback

    return {
        "name": (by_name, False),
        "newest": (lambda p: stat_or(p, "st_mtime"), True),
        "oldest": (lambda p: stat_or(p, "st_mtime"), False),
        "largest": (lambda p: stat_or(p, "st_size"), True),
        "smallest": (lambda p: stat_or(p, "st_size"), False),
    }.get(order, (by_name, False))


def scan_folder(folder: str | Path, recursive: bool = True,
                order: str = "name") -> list[Path]:
    """Return every image below `folder`, in the requested order."""
    root = Path(folder)
    if not root.is_dir():
        return []
    walker = root.rglob("*") if recursive else root.glob("*")
    images = [p for p in walker if p.is_file() and is_image(p)]
    if order == "random":
        random.shuffle(images)
        return images
    key, reverse = _sort_key(order)
    return sorted(images, key=key, reverse=reverse)


def sort_paths(paths: list[Path], order: str = "name") -> list[Path]:
    """Put an explicit list of images in the configured order."""
    if order == "random":
        shuffled = list(paths)
        random.shuffle(shuffled)
        return shuffled
    key, reverse = _sort_key(order)
    return sorted(paths, key=key, reverse=reverse)


def sidecar_files(image: str | Path,
                  extensions: list[str] | None = None) -> list[Path]:
    """Files next to `image` with the exact same stem (.txt, .caption, ...).

    The stem is matched exactly, so `cat.png` never picks up `cat2.txt`.
    Pass `extensions` to restrict which ones travel with the image.
    """
    image = Path(image)
    folder = image.parent
    if not folder.is_dir():
        return []
    wanted = {e.strip().lstrip(".").lower() for e in extensions or [] if str(e).strip()}
    found = [
        p for p in folder.iterdir()
        if p.is_file() and p != image and p.stem == image.stem
    ]
    if wanted:
        found = [p for p in found if p.suffix.lstrip(".").lower() in wanted]
    return sorted(found)


def duplicate_stems(images: list[Path]) -> dict[str, list[Path]]:
    """Stems that occur in more than one folder - moving them can collide."""
    seen: dict[str, list[Path]] = {}
    for image in images:
        seen.setdefault(image.stem.lower(), []).append(image)
    return {stem: paths for stem, paths in seen.items() if len(paths) > 1}


def count_images(folder: str | Path) -> int:
    """How many images sit directly in `folder`."""
    path = Path(folder)
    if not path.is_dir():
        return 0
    try:
        return sum(1 for p in path.iterdir() if p.is_file() and is_image(p))
    except OSError:
        return 0


def newest_image(folder: str | Path) -> Path | None:
    """The most recently added image directly in `folder`."""
    path = Path(folder)
    if not path.is_dir():
        return None
    try:
        images = [p for p in path.iterdir() if p.is_file() and is_image(p)]
    except OSError:
        return None
    if not images:
        return None
    return max(images, key=lambda p: p.stat().st_mtime)
