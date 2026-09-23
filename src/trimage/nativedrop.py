"""Receive original disk paths from the desktop window's file drop event."""
from __future__ import annotations

import json
from pathlib import Path

from .scanner import is_image


def register_window(window) -> None:
    """Connect pywebview's native file paths to the existing image loader."""
    from webview.dom import DOMEventHandler

    def on_drop(event):
        items = []
        for file in event.get("dataTransfer", {}).get("files", []):
            raw_path = file.get("pywebviewFullPath")
            if not raw_path:
                continue
            path = Path(raw_path)
            if path.is_dir():
                items.append({"path": str(path), "directory": True})
            elif is_image(path):
                items.append({"path": str(path), "directory": False})
        if items:
            window.run_js(f"handleNativeDrop({json.dumps(items)});")

    def on_loaded():
        window.dom.body.on("drop", DOMEventHandler(on_drop, prevent_default=True))
        window.run_js("window.trimageNativeDrop = true;")

    window.events.loaded += on_loaded
