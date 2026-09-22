# Trimage

Manually sort large image folders by hand, fast.

Point it at a folder, define your categories, and it shows you the images one at a time.
Press a category's hotkey and the image is moved or copied into that category's folder,
together with any sidecar files sharing its name (`.txt`, `.caption`, `.json`, ...), and
the next image comes up. Built for triaging datasets, culling renders and splitting
captioned image sets.

It runs as a desktop window, in your browser, or as a server you host.

![image](https://github.com/MNeMoNiCuZ/Trimage/assets/60541708/2a834a38-05ba-493c-b885-9f72905bae04)

| | command |
|---|---|
| Native desktop window | `py main.py` |
| In your browser | `py main.py --web` |
| Hosted / headless server | `py main.py --server --host 0.0.0.0` |
| Open a saved project | `py main.py myproject.json` |

## Install

```
git clone https://github.com/MNeMoNiCuZ/Trimage
cd Trimage
py -m pip install -r requirements.txt
py main.py
```

Python 3.11+.

On Windows, `venv_create.bat` creates a `venv` and installs `requirements.txt` into it.
`build.bat` uses that `venv` when it exists.

## Usage

1. Load images: **Image folder...**, or drop a folder or images onto the window.
2. Set an **output root**, paste your category names into *Quick add*, one per line, then
   **Save categories**.
3. Press a category hotkey, or click a card.

## Hotkeys

| Key | Action |
|---|---|
| your category hotkeys | move the current image into that category |
| `Ctrl`+`X` | skip |
| `Ctrl`+`Z` / `←` / `Backspace` | undo |
| `Ctrl`+`S` | save project |
| `Ctrl`+`O` | choose image folder |
| `Ctrl`+`E` | edit categories |
| `Ctrl`+`Enter` | apply pending changes |
| `?` | shortcut list |
| `Esc` | close a dialog |

## Building an executable

```
py build.py              # src/dist/Trimage/
py build.py --onefile    # single .exe
build.bat                # --onefile, then copies the .exe to the project root
```
