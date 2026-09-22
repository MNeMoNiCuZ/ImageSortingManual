"""Native folder picker for the desktop build.

Only the pywebview window can put a dialog on screen safely: it belongs to the
app, and it is the window the user is actually looking at. Anything else - a Tk
dialog spawned from a background server thread, say - pops up unasked and
blocks the request, so we do not do it. Without a window the caller falls back
to the in-app folder browser.
"""
from __future__ import annotations

from pathlib import Path

_window = None          # set by the desktop launcher


def register_window(window) -> None:
    """Remember the pywebview window so dialogs can be parented to it."""
    global _window
    _window = window


def available() -> bool:
    return _window is not None


def pick_folder(initial: str = "", title: str = "Select folder") -> str | None:
    """Open the window's folder dialog. None means the user cancelled."""
    if _window is None:
        raise RuntimeError("No native dialog is available here.")

    import webview

    start = str(Path(initial).expanduser()) if initial else ""
    # FileDialog.FOLDER on pywebview 5+, FOLDER_DIALOG on older releases.
    folder_dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER",
                            getattr(webview, "FOLDER_DIALOG", 20))
    result = _window.create_file_dialog(folder_dialog, directory=start)
    if not result:
        return None
    return str(Path(result[0]))
