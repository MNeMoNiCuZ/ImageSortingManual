"""Trimage.

    py main.py                  native desktop window (falls back to browser)
    py main.py --web            serve and open the default browser
    py main.py --server         serve only, no window (host it anywhere)
    py main.py project.json     start with a project loaded
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

from trimage import __version__, nativedialog, nativedrop
from trimage.server import app, session

APP_ID = "Trimage.Trimage"
ROOT = Path(getattr(sys, "_MEIPASS", SRC))
ICON_PATH = ROOT / "assets" / "trimage.ico"


def configure_windows_identity() -> None:
    """Give Windows a stable identity for taskbar grouping and icon display."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def free_port(host: str, preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def serve(host: str, port: int, blocking: bool = True) -> threading.Thread | None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    if blocking:
        server.run()
        return None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def wait_until_up(host: str, port: int, timeout: float = 15.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def run_desktop(host: str, port: int) -> bool:
    """Open the UI in a native window. Returns False if pywebview is missing."""
    try:
        import webview
    except ImportError:
        return False

    serve(host, port, blocking=False)
    wait_until_up(host, port)
    window = webview.create_window(
        "Trimage",
        f"http://127.0.0.1:{port}/",
        width=1440,
        height=900,
        min_size=(900, 600),
        background_color="#12141a",
    )
    nativedialog.register_window(window)
    nativedrop.register_window(window)
    webview.start(icon=str(ICON_PATH))
    return True


def main(argv: list[str] | None = None) -> int:
    configure_windows_identity()
    parser = argparse.ArgumentParser(description="Trimage")
    parser.add_argument("project", nargs="?", help="a .json project file to open")
    parser.add_argument("--web", action="store_true", help="open in the default browser")
    parser.add_argument("--server", action="store_true", help="serve only, open nothing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--folder", help="image folder to load on start")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.project or args.folder:
        # An explicit project or folder means "use this", not "what about
        # last time?".
        session.resume_dismissed = True
    if args.project:
        try:
            session.load_project_file(args.project)
        except Exception as exc:
            print(f"Could not load project {args.project}: {exc}", file=sys.stderr)
    if args.folder:
        try:
            session.set_folder(args.folder)
        except Exception as exc:
            print(f"Could not load folder {args.folder}: {exc}", file=sys.stderr)

    port = free_port(args.host, args.port)
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{port}/"

    if args.server:
        print(f"Trimage serving on {url}")
        serve(args.host, port)
        return 0

    if args.web:
        serve(args.host, port, blocking=False)
        wait_until_up(args.host, port)
        print(f"Trimage running at {url}")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0

    if run_desktop(args.host, port):
        return 0

    print("pywebview is not installed - falling back to the browser.")
    return main(["--web", "--host", args.host, "--port", str(port)])


if __name__ == "__main__":
    raise SystemExit(main())
