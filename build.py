"""Build a standalone executable with PyInstaller.

    py -m pip install -r requirements.txt
    py build.py            one-folder build (fast to start)
    py build.py --onefile  single .exe

Build artifacts land in src/build and src/dist.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
WEB = SRC / "imagesorter" / "web"
ASSETS = SRC / "assets"
ICON = ASSETS / "image_sorting_tool.ico"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onefile", action="store_true")
    parser.add_argument("--console", action="store_true", help="keep a console window")
    args = parser.parse_args()

    if shutil.which("pyinstaller") is None:
        print("pyinstaller not found - pip install -r requirements.txt", file=sys.stderr)
        return 1

    separator = ";" if sys.platform == "win32" else ":"
    command = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--name", "ImageSortingTool",
        "--paths", str(SRC),
        "--add-data", f"{WEB}{separator}imagesorter/web",
        "--add-data", f"{ASSETS}{separator}assets",
        "--icon", str(ICON),
        "--collect-submodules", "uvicorn",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.loops.asyncio",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--distpath", str(SRC / "dist"),
        "--workpath", str(SRC / "build"),
        "--specpath", str(SRC),
        "--onefile" if args.onefile else "--onedir",
        "--console" if args.console else "--noconsole",
        str(ROOT / "main.py"),
    ]
    print(" ".join(command))
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
