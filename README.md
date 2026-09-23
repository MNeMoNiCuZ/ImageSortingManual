# Trimage
The purpose of this tool is to help you quickly sort through files / datasets where an image may have multiple additional files sharing the same name (such as .txt, .json, .caption etc.).

The tool shows you an image, and you press a configured button or hotkey to copy or move the image and all the supplementary files into a target output folder.

Built for triaging datasets, culling renders and splitting captioned image sets.

It runs as a desktop window, in your browser, or as a server you host.

<img width="2557" height="1380" alt="Screenshot" src="https://github.com/user-attachments/assets/3a8140bf-0f0d-4d4b-829a-dadc0215b32e" />


## Commands
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
| `+` / `-` | zoom in / out |
| `0` | reset zoom |
| Scroll wheel | zoom in/out centered on cursor |
| Middle-click drag | pan when zoomed in |
| `?` | shortcut list |
| `Esc` | close a dialog |

## Building an executable

```
py build.py              # src/dist/Trimage/
py build.py --onefile    # single .exe
build.bat                # --onefile, then copies the .exe to the project root
```
