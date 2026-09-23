"""Desktop drops must preserve the paths supplied by the operating system."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trimage.nativedrop import register_window


class LoadedEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def registered_window():
    pytest.importorskip("webview.dom")
    window = SimpleNamespace(
        events=SimpleNamespace(loaded=LoadedEvent()),
        dom=SimpleNamespace(body=Mock()),
        run_js=Mock(),
    )
    register_window(window)
    window.events.loaded.handlers[0]()
    event, handler = window.dom.body.on.call_args.args
    assert event == "drop"
    assert handler.prevent_default
    window.run_js.assert_called_once_with("window.trimageNativeDrop = true;")
    window.run_js.reset_mock()
    return window, handler.callback


def test_native_drop_preserves_deep_and_duplicate_paths(tmp_path):
    window, on_drop = registered_window()
    deep = tmp_path.joinpath(*["nested"] * 8, "images with spaces")
    deep.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    files = [deep / "same.png", other / "same.png"]
    for path in files:
        path.touch()
    on_drop({"dataTransfer": {"files": [
        {"name": path.name, "pywebviewFullPath": str(path)} for path in files
    ] + [{"name": deep.name, "pywebviewFullPath": str(deep)}]}})
    script = window.run_js.call_args.args[0]
    payload = json.loads(script.removeprefix("handleNativeDrop(").removesuffix(");"))
    assert payload == [
        {"path": str(files[0]), "directory": False},
        {"path": str(files[1]), "directory": False},
        {"path": str(deep), "directory": True},
    ]


def test_native_drop_does_not_guess_paths_or_load_sidecars(tmp_path):
    window, on_drop = registered_window()
    on_drop({"dataTransfer": {"files": [
        {"name": "photo.png"},
        {"name": "photo.txt", "pywebviewFullPath": str(tmp_path / "photo.txt")},
    ]}})
    on_drop({"dataTransfer": {"files": []}})
    window.run_js.assert_not_called()
