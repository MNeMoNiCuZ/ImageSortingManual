<<<<<<< HEAD
# Trimage
=======
# Image Sorting Tool
The purpose of this tool is to help you quickly sort through files / datasets where an image may have multiple additional files sharing the same name (such as .txt, .json, .caption etc.).
>>>>>>> 65b7398098ecfa8da8af8e9d44ff06b07de2c216

The tool shows you an image, and you press a configured button or hotkey to copy or move the image and all the supplementary files into a target output folder.

Built for triaging datasets, culling renders and splitting captioned image sets.

It runs as a desktop window, in your browser, or as a server you host.

<<<<<<< HEAD
![image](https://github.com/MNeMoNiCuZ/Trimage/assets/60541708/2a834a38-05ba-493c-b885-9f72905bae04)
=======

>>>>>>> 65b7398098ecfa8da8af8e9d44ff06b07de2c216

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
