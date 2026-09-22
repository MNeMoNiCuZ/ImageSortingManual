"""Work out where a folder dropped onto the page actually lives.

A browser will not tell a page the real path of a dropped folder - it only
gives the folder's name and the names of the files inside it. Since the server
runs on the same machine, we can look for that folder ourselves. The search is
bounded so a stray drop can never grind the app to a halt.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

MAX_SECONDS = 2.5
MAX_DIRECTORIES = 40_000
MAX_DEPTH = 4
MAX_MATCHES = 8

SKIP = {
    "node_modules", "__pycache__", "$recycle.bin", "system volume information",
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", ".git", ".venv", "venv", "site-packages",
}


def search_roots(hints: list[str]) -> list[Path]:
    """Where to look, nearest guesses first."""
    roots: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser()
        except (OSError, RuntimeError):
            return
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)

    for hint in hints:
        if hint:
            add(Path(hint))
            add(Path(hint).parent)

    home = Path.home()
    add(home)
    for name in ("Desktop", "Downloads", "Documents", "Pictures"):
        add(home / name)

    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            add(Path(f"{letter}:\\"))
    else:
        add(Path("/"))
        add(Path("/media"))
        add(Path("/mnt"))
    return roots


def _matches(folder: Path, files: set[str]) -> bool:
    if not files:
        return True
    try:
        present = {entry.name.lower() for entry in os.scandir(folder) if entry.is_file()}
    except OSError:
        return False
    return bool(files & present)


def resolve(name: str, files: list[str], hints: list[str] | None = None) -> list[str]:
    """Absolute paths of folders called `name` that contain one of `files`."""
    name = (name or "").strip()
    if not name:
        return []
    wanted = {f.lower() for f in (files or []) if f}
    deadline = time.time() + MAX_SECONDS
    seen_dirs = 0
    found: list[str] = []
    visited: set[str] = set()

    for root in search_roots(hints or []):
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            if time.time() > deadline or seen_dirs > MAX_DIRECTORIES:
                return found
            folder, depth = stack.pop()
            key = str(folder).lower()
            if key in visited:
                continue
            visited.add(key)
            seen_dirs += 1

            if folder.name.lower() == name.lower() and _matches(folder, wanted):
                path = str(folder)
                if path not in found:
                    found.append(path)
                    if len(found) >= MAX_MATCHES:
                        return found
                continue                    # no need to look inside a match

            if depth >= MAX_DEPTH:
                continue
            try:
                for entry in os.scandir(folder):
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name.startswith(".") or entry.name.lower() in SKIP:
                        continue
                    stack.append((Path(entry.path), depth + 1))
            except OSError:
                continue
    return found


def resolve_files(names: list[str], hints: list[str] | None = None
                  ) -> tuple[list[str], list[str]]:
    """Find dropped image files by name. Returns (paths found, names missing).

    Files dropped together nearly always live in one folder, so we look for the
    folder that accounts for the most of them and take that as the answer.
    """
    wanted = {n.lower(): n for n in (names or []) if n}
    if not wanted:
        return [], []

    deadline = time.time() + MAX_SECONDS
    seen_dirs = 0
    visited: set[str] = set()
    found: dict[str, list[Path]] = {}

    for root_dir in search_roots(hints or []):
        stack: list[tuple[Path, int]] = [(root_dir, 0)]
        while stack:
            if time.time() > deadline or seen_dirs > MAX_DIRECTORIES:
                stack = []
                break
            folder, depth = stack.pop()
            key = str(folder).lower()
            if key in visited:
                continue
            visited.add(key)
            seen_dirs += 1

            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_file():
                        low = entry.name.lower()
                        if low in wanted:
                            found.setdefault(low, []).append(Path(entry.path))
                    elif (depth < MAX_DEPTH and not entry.name.startswith(".")
                          and entry.name.lower() not in SKIP):
                        stack.append((Path(entry.path), depth + 1))
                except OSError:
                    continue
        if len(found) == len(wanted):
            break

    if not found:
        return [], list(wanted.values())

    # Which folder holds the most of them?
    tally: dict[str, int] = {}
    for paths in found.values():
        for path in paths:
            tally[str(path.parent)] = tally.get(str(path.parent), 0) + 1
    best = max(tally, key=lambda folder: tally[folder])

    resolved: list[str] = []
    missing: list[str] = []
    for low, original in wanted.items():
        candidates = found.get(low, [])
        in_best = [p for p in candidates if str(p.parent) == best]
        if in_best:
            resolved.append(str(in_best[0]))
        elif len(candidates) == 1:
            resolved.append(str(candidates[0]))
        else:
            missing.append(original)
    return resolved, missing
