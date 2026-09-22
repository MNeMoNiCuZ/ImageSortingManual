"""In-memory thumbnail cache backed by Pillow."""
from __future__ import annotations

import io
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps

_CACHE: "OrderedDict[tuple[str, float, int], bytes]" = OrderedDict()
_CACHE_LIMIT = 400


def render(path: str | Path, size: int = 256) -> bytes:
    """Return a JPEG thumbnail of `path`, at most `size` px on the long edge."""
    path = Path(path)
    key = (str(path), path.stat().st_mtime, size)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((size, size), Image.LANCZOS)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)

    data = buffer.getvalue()
    _CACHE[key] = data
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return data


def dimensions(path: str | Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def clear() -> None:
    _CACHE.clear()
