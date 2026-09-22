"""End-to-end UI check: drives the real app in Chrome via Playwright.

Not part of the pytest suite - it needs a browser and a running server.

    py -m pip install playwright
    py src/tests/ui_check.py --serve

`--serve` starts a throwaway server on its own port with a temporary config,
which is what you normally want. To drive a server you started yourself:

    py main.py --server --port 8421 --folder <the folder it prints>
    py src/tests/ui_check.py --url http://127.0.0.1:8421/

The server must have a FRESH session: leftover categories break the
duplicate-hotkey assertions.
"""
import argparse
import json
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="")
parser.add_argument("--serve", action="store_true",
                    help="start a private server instead of using --url")
parser.add_argument("--work", default=str(Path(__file__).parent / "_uicheck"))
parser.add_argument("--headed", action="store_true")
args = parser.parse_args()

SP = Path(args.work)
OUT = SP / "shots"
OUT.mkdir(parents=True, exist_ok=True)

errors = []
results = []


def open_settings(page):
    """Settings moved into the menu at the top right."""
    page.click("#btn-menu")
    page.wait_for_selector("#context-menu:not([hidden])")
    page.locator("#context-menu button", has_text="Settings").click()
    page.wait_for_selector("#modal-settings:not([hidden])")


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    line = ("PASS " if condition else "FAIL ") + name + (f"  {detail}" if detail else "")
    # Windows consoles are often cp1252; never let a glyph kill the run.
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, "replace").decode(encoding, "replace"))


def build_demo_images():
    """Recreate the demo set the assertions below expect."""
    demo = SP / "demo"
    if demo.exists():
        shutil.rmtree(demo)
    source = demo / "in"
    source.mkdir(parents=True)
    for i in range(6):
        image = Image.new("RGB", (640, 420), ((i * 37) % 255, (i * 71) % 255, 180))
        ImageDraw.Draw(image).text((30, 30), f"IMAGE {i}", fill="white")
        image.save(source / f"pic{i:02d}.png")
        (source / f"pic{i:02d}.txt").write_text(f"caption {i}", encoding="utf-8")
    return source


def start_server(source_folder):
    """Run the app in-process on a free port, with a throwaway config."""
    import uvicorn

    from trimage.config import AppConfig
    from trimage import server as server_module

    config = AppConfig()
    config._file = SP / "config.json"
    if config._file.exists():
        config._file.unlink()
    server_module.session = server_module.Session(config)
    server_module.session.set_folder(str(source_folder))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    app = server_module.create_app()

    globals()["_server_module"] = server_module
    globals()["_config_file"] = config._file

    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=uv.run, daemon=True).start()

    deadline = time.time() + 20
    while time.time() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.1)
    return f"http://127.0.0.1:{port}/"


def restart_app():
    """Stand in for quitting and starting the app again: a brand new session
    reading the config back off disk."""
    from trimage.config import AppConfig as _Config
    module = globals()["_server_module"]
    module.session = module.Session(_Config.load(globals()["_config_file"]))


source_folder = build_demo_images()
if args.serve or not args.url:
    URL = start_server(source_folder)
    print(f"serving {source_folder} at {URL}\n")
else:
    URL = args.url
    print(f"point the server at: {source_folder}\n")

KEEP = SP / "demo" / "keep"
TRASH = SP / "demo" / "trash"
ROOT = SP / "demo" / "out"


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=not args.headed)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)

    page.goto(URL)
    page.wait_for_function("document.getElementById('info-name').textContent !== '—'",
                           timeout=10000)
    page.wait_for_timeout(500)

    # -- initial render -----------------------------------------------
    check("main image visible", page.locator("#main-image").is_visible())
    check("filename shown", page.locator("#info-name").inner_text() == "pic00.png",
          page.locator("#info-name").inner_text())
    check("sidecar chip", page.locator(".chip").first.inner_text().lower() == "txt")
    check("filmstrip thumbs", page.locator(".thumb").count() == 6,
          str(page.locator(".thumb").count()))
    check("progress", page.locator("#info-progress").inner_text() == "1 / 6",
          page.locator("#info-progress").inner_text())
    check("counts show left/sorted", "left" in page.locator("#info-counts").inner_text(),
          page.locator("#info-counts").inner_text())
    page.screenshot(path=str(OUT / "01-loaded.png"))

    # -- the menu icon actually fills its button ------------------------
    box = page.evaluate("""() => {
        const b = document.getElementById('btn-menu').getBoundingClientRect();
        const s = document.querySelector('#btn-menu svg').getBoundingClientRect();
        return {button: b.height, icon: s.height};
    }""")
    check("the menu icon fills its button", box["icon"] >= box["button"] * 0.7,
          f"icon {box['icon']:.0f}px in a {box['button']:.0f}px button")

    # -- controls live in the top row of the app ------------------------
    layout = page.evaluate("""() => {
        const ctrl = document.getElementById('dock-controls');
        const box = ctrl.getBoundingClientRect();
        const bar = document.querySelector('.topbar').getBoundingClientRect();
        const viewer = document.getElementById('viewer').getBoundingClientRect();
        const tops = [...ctrl.querySelectorAll('.btn')]
            .filter(b => b.offsetParent !== null)          // skip hidden buttons
            .map(b => Math.round(b.getBoundingClientRect().top));
        return {inTopbar: ctrl.closest('.topbar') !== null,
                top: box.top, bottom: box.bottom,
                barTop: bar.top, barBottom: bar.bottom,
                viewerTop: viewer.top, rows: new Set(tops).size};
    }""")
    check("controls sit on one row", layout["rows"] == 1, f"{layout['rows']} row(s)")
    check("controls are in the top bar", layout["inTopbar"]
          and layout["top"] >= layout["barTop"] - 1
          and layout["bottom"] <= layout["barBottom"] + 1)
    check("nothing but the header is above the image",
          layout["bottom"] <= layout["viewerTop"] + 1,
          f"buttons end at {layout['bottom']:.0f}, image starts at {layout['viewerTop']:.0f}")

    check("the bottom section is categories only", page.evaluate("""() => {
        const bottom = document.getElementById('bottom');
        return bottom.querySelectorAll('.btn').length === 0
            || [...bottom.querySelectorAll('.btn')].every(b => b.closest('#categories'));
    }"""))

    # -- the category table ---------------------------------------------
    page.click("#btn-manage")
    page.wait_for_selector("#modal-categories:not([hidden])")
    check("table opens with one blank row", page.locator("#cat-rows tr").count() == 1)

    # bulk add three categories at once
    page.fill("#bulk-names", "Keep\nMaybe\nDiscard")
    page.fill("#table-root", str(ROOT))
    page.dispatch_event("#table-root", "change")
    page.wait_for_timeout(400)
    page.click("#bulk-add")
    page.wait_for_timeout(600)
    check("bulk add created 3 rows", page.locator("#cat-rows tr").count() == 3,
          str(page.locator("#cat-rows tr").count()))
    names = page.locator("#cat-rows tr input[type=text]").all_inner_texts()
    values = page.evaluate("""() => [...document.querySelectorAll('#cat-rows tr')]
        .map(tr => tr.querySelectorAll('input[type=text]')[0].value)""")
    check("bulk names landed", values == ["Keep", "Maybe", "Discard"], str(values))
    folders = page.evaluate("""() => [...document.querySelectorAll('#cat-rows tr')]
        .map(tr => tr.querySelectorAll('input[type=text]')[1].value)""")
    check("folders are plain names, not full paths", folders == ["Keep", "Maybe", "Discard"],
          str(folders))
    hotkeys = page.evaluate("""() => [...document.querySelectorAll('#cat-rows tr')]
        .map(tr => tr.querySelector('.hotkey-input').value)""")
    check("hotkeys auto-assigned and unique", len(set(hotkeys)) == 3 and all(hotkeys),
          str(hotkeys))
    page.screenshot(path=str(OUT / "02-table.png"))

    # set an explicit hotkey on the first row
    page.locator("#cat-rows tr").first.locator(".hotkey-input").click()
    page.keyboard.press("K")
    check("row hotkey captured",
          page.locator("#cat-rows tr").first.locator(".hotkey-input").input_value() == "K",
          page.locator("#cat-rows tr").first.locator(".hotkey-input").input_value())

    # a function key on the second row
    page.locator("#cat-rows tr").nth(1).locator(".hotkey-input").click()
    page.keyboard.press("F4")
    check("F-key captured in the table",
          page.locator("#cat-rows tr").nth(1).locator(".hotkey-input").input_value() == "F4")

    # save as a preset, then save the table
    page.click("#preset-save")
    page.wait_for_selector("#modal-prompt:not([hidden])")
    page.fill("#prompt-input", "my set")
    page.click("#prompt-ok")
    page.wait_for_timeout(600)
    check("preset appears in the list",
          "my set" in page.locator("#preset-select").inner_text(),
          page.locator("#preset-select").inner_text())

    page.click("#cat-table-save")
    page.wait_for_timeout(500)
    check("three cards rendered", page.locator(".card:not(.skipped)").count() == 3,
          str(page.locator(".card:not(.skipped)").count()))
    check("card shows a hotkey badge",
          page.locator(".card").first.locator(".hk").inner_text() == "K")
    check("card shows a single count",
          page.locator(".card").first.locator(".card-count").count() == 1
          and page.locator(".card").first.locator(".card-count").inner_text() == "0",
          page.locator(".card").first.locator(".card-count").inner_text())

    fill = page.evaluate("""() => {
        const wrap = document.getElementById('categories').getBoundingClientRect();
        const cards = [...document.querySelectorAll('.card')].map(c => c.getBoundingClientRect());
        const left = Math.min(...cards.map(c => c.left));
        const right = Math.max(...cards.map(c => c.right));
        const top = Math.min(...cards.map(c => c.top));
        const bottom = Math.max(...cards.map(c => c.bottom));
        const rows = new Set(cards.map(c => Math.round(c.top))).size;
        return {wrapW: wrap.width, wrapH: wrap.height, spanW: right - left,
                spanH: bottom - top, rows};
    }""")
    check("3 cards fill the width", fill["spanW"] > fill["wrapW"] * 0.97,
          f"{fill['spanW']:.0f} of {fill['wrapW']:.0f}")
    check("3 cards fill the height on one row",
          fill["rows"] == 1 and fill["spanH"] > fill["wrapH"] * 0.97,
          f"{fill['rows']} row(s), {fill['spanH']:.0f} of {fill['wrapH']:.0f}")
    page.screenshot(path=str(OUT / "03-cards.png"))

    # -- sorting via hotkey, into a relative folder ---------------------
    page.click("body")
    page.keyboard.press("k")
    page.wait_for_timeout(800)
    check("relative folder resolved under the output root",
          (ROOT / "Keep" / "pic00.png").exists())
    check("sidecar came along", (ROOT / "Keep" / "pic00.txt").exists())
    check("advanced to pic01", page.locator("#info-name").inner_text() == "pic01.png",
          page.locator("#info-name").inner_text())
    check("card count went up",
          page.locator(".card").first.locator(".card-count").inner_text() == "1",
          page.locator(".card").first.locator(".card-count").inner_text())
    page.wait_for_timeout(600)
    check("card shows the actual image",
          page.locator(".card").first.locator(".card-previews img").count() == 1,
          str(page.locator(".card").first.locator(".card-previews img").count()))

    page.keyboard.press("F4")
    page.wait_for_timeout(700)
    check("F4 sorted into Maybe", (ROOT / "Maybe" / "pic01.png").exists())

    # -- skip, the Skipped group, and revisiting ------------------------
    page.keyboard.press("Space")
    page.keyboard.press("Space")
    page.wait_for_timeout(700)
    check("skipped card appears", page.locator(".card.skipped").count() == 1)
    page.wait_for_timeout(600)
    check("the skipped card shows thumbnails too",
          page.locator(".card.skipped .card-previews img").count() == 2,
          str(page.locator(".card.skipped .card-previews img").count()))
    check("skipped card counts two",
          page.locator(".card.skipped .card-count").inner_text() == "2",
          page.locator(".card.skipped .card-count").inner_text())
    check("counts mention skipped", "skipped" in page.locator("#info-counts").inner_text(),
          page.locator("#info-counts").inner_text())
    check("moved past the skipped ones",
          page.locator("#info-name").inner_text() == "pic04.png",
          page.locator("#info-name").inner_text())
    page.screenshot(path=str(OUT / "04-skipped.png"))

    page.click(".card.skipped")
    page.wait_for_timeout(700)
    check("revisiting jumps back to the first skipped image",
          page.locator("#info-name").inner_text() == "pic02.png",
          page.locator("#info-name").inner_text())
    check("skipped card is gone", page.locator(".card.skipped").count() == 0)
    check("nothing was undone - pic00 is still sorted", (ROOT / "Keep" / "pic00.png").exists())

    # -- undo -----------------------------------------------------------
    page.keyboard.press("Control+z")
    page.wait_for_timeout(800)
    check("undo restored pic01", (SP / "demo" / "in" / "pic01.png").exists())
    check("undo restored the sidecar", (SP / "demo" / "in" / "pic01.txt").exists())

    # -- undo takes back a skip, just like a move ---------------------------
    before = page.locator("#info-name").inner_text()
    page.keyboard.press("Space")                       # skip: marks and moves on
    page.wait_for_timeout(400)
    check("skip moved on", page.locator("#info-name").inner_text() != before)
    check("undo is offered for a skip", not page.locator("#btn-undo").is_disabled())
    page.keyboard.press("Control+z")
    page.wait_for_timeout(500)
    check("undo un-skips it without touching files",
          page.locator("#info-name").inner_text() == before
          and (SP / "demo" / "in" / before).exists(), before)
    check("and it left the skipped group",
          page.locator(".card.skipped").count() == 0)
    check("there is no Prev button any more",
          page.locator("#btn-back").count() == 0)

    # dragging an image onto Skipped skips it
    target_name = page.evaluate("() => state.upcoming[1].name")
    page.locator(".thumb").nth(1).hover()
    page.mouse.down()
    page.mouse.move(400, 400, steps=4)           # get the drag going
    page.evaluate("async () => render(await (await fetch('/api/state')).json())")
    page.mouse.up()
    page.wait_for_timeout(400)
    page.keyboard.press("Space")                 # make a Skipped card exist
    page.wait_for_timeout(500)
    if page.locator(".card.skipped").count():
        skip_card = page.locator(".card.skipped").bounding_box()
        before_skipped = page.evaluate("() => state.skipped")
        page.locator(".thumb").nth(1).hover()
        page.mouse.down()
        page.mouse.move(skip_card["x"] + skip_card["width"] / 2,
                        skip_card["y"] + skip_card["height"] / 2, steps=10)
        page.mouse.up()
        page.wait_for_timeout(700)
        check("dragging an image onto Skipped skips it",
              page.evaluate("() => state.skipped") == before_skipped + 1,
              f"{before_skipped} -> {page.evaluate('() => state.skipped')}")
        # one image can come back on its own, by clicking its thumbnail
        page.wait_for_timeout(600)
        skipped_now = page.evaluate("() => state.skipped")
        if page.locator(".card.skipped .card-previews img").count():
            page.locator(".card.skipped .card-previews img").first.click()
            page.wait_for_timeout(700)
            check("clicking a skipped thumbnail brings that one back",
                  page.evaluate("() => state.skipped") == skipped_now - 1,
                  f"{skipped_now} -> {page.evaluate('() => state.skipped')}")
        if page.locator(".card.skipped").count():
            page.click(".card.skipped")          # the rest go back together
            page.wait_for_timeout(600)
        check("the skipped group is empty again",
              page.evaluate("() => state.skipped") == 0)

    # -- settings ---------------------------------------------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    check("settings shows the config file path",
          page.locator("#set-config-path").inner_text().endswith("config.json"),
          page.locator("#set-config-path").inner_text())
    check("settings knows the output root",
          page.input_value("#set-output-root") == str(ROOT),
          page.input_value("#set-output-root"))
    page.screenshot(path=str(OUT / "05-settings.png"))

    page.uncheck("#set-card-thumbs")
    page.wait_for_timeout(500)
    stored = json.loads((SP / "config.json").read_text(encoding="utf-8"))
    check("setting written to config.json", stored["show_card_thumbnails"] is False)
    check("preset stored in config.json", "my set" in stored.get("presets", {}))
    page.check("#set-card-thumbs")
    page.wait_for_timeout(400)

    page.select_option("#set-sort-order", "newest")
    page.wait_for_timeout(600)
    check("sort order persisted",
          json.loads((SP / "config.json").read_text(encoding="utf-8"))["sort_order"] == "newest")
    page.select_option("#set-sort-order", "name")
    page.wait_for_timeout(600)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # -- presets round trip ----------------------------------------------
    page.click("#btn-manage")
    page.wait_for_selector("#modal-categories:not([hidden])")
    page.locator("#cat-rows tr").last.locator(".row-del").click()
    page.click("#cat-table-save")
    page.wait_for_timeout(500)
    check("a category was removed", page.locator(".card:not(.skipped)").count() == 2,
          str(page.locator(".card:not(.skipped)").count()))

    page.click("#btn-manage")
    page.wait_for_selector("#modal-categories:not([hidden])")
    page.select_option("#preset-select", "my set")
    page.click("#preset-load")
    page.wait_for_timeout(600)
    check("preset restored all three", page.locator("#cat-rows tr").count() == 3,
          str(page.locator("#cat-rows tr").count()))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # -- resize ------------------------------------------------------------
    page.set_viewport_size({"width": 900, "height": 620})
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "06-small.png"))
    check("image still fits after resize", page.evaluate(
        "()=>{const i=document.getElementById('main-image');"
        "const v=document.getElementById('viewer');"
        "return i.getBoundingClientRect().height <= v.getBoundingClientRect().height+1;}"))
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(300)

    # -- folder browser -----------------------------------------------------
    # Served in a browser there is no window to hang a native dialog on, so the
    # in-app folder browser is what opens.
    check("no native dialog is offered to a browser client",
          page.evaluate("() => env.native_dialogs") is False)
    page.click("#btn-folder")
    page.wait_for_selector("#modal-browse:not([hidden])")
    page.wait_for_function("document.getElementById('browse-path').value !== ''", timeout=5000)
    check("browser shows drives", page.locator("#browse-drives button").count() > 0)
    check("browser starts at the current folder",
          page.input_value("#browse-path").endswith("in"), page.input_value("#browse-path"))

    picker = page.evaluate("""() => {
        const modal = document.getElementById('modal-browse').getBoundingClientRect();
        const input = document.getElementById('browse-path').getBoundingClientRect();
        const list = document.getElementById('browse-list').getBoundingClientRect();
        return {modalW: modal.width, inputW: input.width, inputH: input.height, listH: list.height};
    }""")
    check("path input is not a thin strip", picker["inputH"] >= 38,
          f"{picker['inputH']:.0f}px tall")
    check("path input spans the dialog",
          picker["inputW"] > picker["modalW"] * 0.6,
          f"{picker['inputW']:.0f}px of {picker['modalW']:.0f}px")
    check("folder list is roomy", picker["listH"] >= 340, f"{picker['listH']:.0f}px tall")
    page.screenshot(path=str(OUT / "08-browser.png"))

    page.click("#browse-up")
    page.wait_for_timeout(500)
    check("browser lists folders after going up", page.locator("#browse-list li").count() > 0,
          str(page.locator("#browse-list li").count()))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # -- move vs copy, and deferred apply -----------------------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    check("move/copy is a visible choice",
          page.locator("#set-file-action option").count() == 2)
    check("apply timing is a visible choice",
          page.locator("#set-apply-mode option").count() == 2)
    page.select_option("#set-file-action", "copy")
    page.wait_for_timeout(500)
    page.select_option("#set-apply-mode", "deferred")
    page.wait_for_timeout(600)
    stored = json.loads((SP / "config.json").read_text(encoding="utf-8"))
    check("move/copy persisted", stored["file_action"] == "copy", stored["file_action"])
    check("apply mode persisted", stored["apply_mode"] == "deferred", stored["apply_mode"])
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    check("apply button hidden with nothing waiting",
          page.locator("#btn-apply").is_hidden())

    before_files = sorted(p.name for p in (ROOT / "Keep").glob("*")) if (ROOT / "Keep").is_dir() else []
    current = page.locator("#info-name").inner_text()
    page.click("body")
    page.keyboard.press("k")
    page.wait_for_timeout(700)
    check("deferred pick moved nothing yet",
          (SP / "demo" / "in" / current).exists(), current)
    check("apply button appeared", page.locator("#btn-apply").is_visible())
    check("apply button is just 'Apply'",
          page.locator("#btn-apply").inner_text().strip().endswith("Apply"),
          page.locator("#btn-apply").inner_text())
    check("cancel button is just 'Cancel'",
          page.locator("#btn-discard").inner_text().strip().endswith("Cancel"),
          page.locator("#btn-discard").inner_text())
    apply_tip = page.locator("#btn-apply").get_attribute("title") or ""
    cancel_tip = page.locator("#btn-discard").get_attribute("title") or ""
    check("apply tooltip carries the count and the consequence",
          "1 image" in apply_tip and "Copy" in apply_tip, apply_tip)
    check("cancel tooltip carries the count and the consequence",
          "1 waiting" in cancel_tip and "No files are moved" in cancel_tip, cancel_tip)
    check("count folds the waiting image in, as one number",
          page.locator(".card").first.locator(".card-count").inner_text() == "2 (1 waiting)",
          page.locator(".card").first.locator(".card-count").inner_text())
    page.wait_for_timeout(500)
    check("waiting image is previewed on the card",
          page.locator(".card").first.locator(".card-previews img.waiting").count() == 1,
          str(page.locator(".card").first.locator(".card-previews img.waiting").count()))
    check("control bar explains the pending state",
          "waiting" in page.locator("#control-note").inner_text(),
          page.locator("#control-note").inner_text())
    check("counts mention waiting", "waiting" in page.locator("#info-counts").inner_text(),
          page.locator("#info-counts").inner_text())
    page.screenshot(path=str(OUT / "09-staged.png"))

    page.click("#btn-apply")
    page.wait_for_timeout(900)
    check("apply copied the file", (ROOT / "Keep" / current).exists(), current)
    check("copy left the original in place", (SP / "demo" / "in" / current).exists())
    check("apply button hidden again", page.locator("#btn-apply").is_hidden())
    check("waiting wording cleared",
          "waiting" not in page.locator(".card").first.locator(".card-count").inner_text(),
          page.locator(".card").first.locator(".card-count").inner_text())

    # discard instead of applying
    nxt = page.locator("#info-name").inner_text()
    page.keyboard.press("k")
    page.wait_for_timeout(600)
    check("second pick staged again", page.locator("#btn-apply").is_visible())
    page.once("dialog", lambda d: d.accept())
    page.click("#btn-discard")
    page.wait_for_timeout(700)
    check("discard cleared the queue", page.locator("#btn-apply").is_hidden())
    check("discard copied nothing", not (ROOT / "Keep" / nxt).exists(), nxt)
    check("discarded image is back in the queue",
          page.locator("#info-name").inner_text() == nxt,
          page.locator("#info-name").inner_text())

    # -- many cards wrap into a sensible grid --------------------------------
    page.click("#btn-manage")
    page.wait_for_selector("#modal-categories:not([hidden])")
    page.fill("#bulk-names", "\n".join(f"cat{i:02d}" for i in range(12)))
    page.click("#bulk-add")
    page.wait_for_timeout(1400)
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)

    grid = page.evaluate("""() => {
        const wrap = document.getElementById('categories').getBoundingClientRect();
        const cards = [...document.querySelectorAll('.card')].map(c => c.getBoundingClientRect());
        const rows = new Set(cards.map(c => Math.round(c.top))).size;
        const cols = new Set(cards.map(c => Math.round(c.left))).size;
        const right = Math.max(...cards.map(c => c.right));
        const left = Math.min(...cards.map(c => c.left));
        return {n: cards.length, rows, cols, wrapW: wrap.width, spanW: right - left};
    }""")
    check("many cards wrap into rows and columns",
          grid["rows"] > 1 and grid["cols"] > 1,
          f"{grid['rows']}x{grid['cols']} for {grid['n']} cards")
    check("wrapped cards still fill the width", grid["spanW"] > grid["wrapW"] * 0.97,
          f"{grid['spanW']:.0f} of {grid['wrapW']:.0f}")
    page.screenshot(path=str(OUT / "10-many-cards.png"))

    # -- drag the dock taller and the strip wider ----------------------------
    dock_before = page.evaluate(
        "() => document.getElementById('bottom').getBoundingClientRect().height")
    handle = page.locator("#resize-dock").bounding_box()
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] - 90, steps=8)
    page.mouse.up()
    page.wait_for_timeout(800)
    dock_after = page.evaluate(
        "() => document.getElementById('bottom').getBoundingClientRect().height")
    check("dragging made the category area taller", dock_after > dock_before + 60,
          f"{dock_before:.0f} -> {dock_after:.0f}")
    check("dock height was remembered",
          abs(json.loads((SP / "config.json").read_text(encoding="utf-8"))["dock_height"]
              - dock_after) < 3)

    strip_before = page.evaluate(
        "() => document.getElementById('filmstrip').getBoundingClientRect().width")
    handle = page.locator("#resize-strip").bounding_box()
    page.mouse.move(handle["x"] + handle["width"] / 2, handle["y"] + handle["height"] / 2)
    page.mouse.down()
    page.mouse.move(handle["x"] + 80, handle["y"] + handle["height"] / 2, steps=8)
    page.mouse.up()
    page.wait_for_timeout(800)
    strip_after = page.evaluate(
        "() => document.getElementById('filmstrip').getBoundingClientRect().width")
    check("dragging made the strip wider", strip_after > strip_before + 50,
          f"{strip_before:.0f} -> {strip_after:.0f}")
    check("strip width was remembered",
          abs(json.loads((SP / "config.json").read_text(encoding="utf-8"))["filmstrip_size"]
              - strip_after) < 3)

    # -- clicking a card must not flash a scrollbar --------------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    page.select_option("#set-apply-mode", "immediate")
    page.wait_for_timeout(600)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    scroll = page.evaluate("""() => {
        const wrap = document.getElementById('categories');
        const card = document.querySelector('.card');
        const before = {v: wrap.scrollHeight > wrap.clientHeight,
                        h: wrap.scrollWidth > wrap.clientWidth};
        card.classList.add('flash');
        const down = new MouseEvent('mousedown', {bubbles: true});
        card.dispatchEvent(down);
        const during = {v: wrap.scrollHeight > wrap.clientHeight,
                        h: wrap.scrollWidth > wrap.clientWidth,
                        overflowX: getComputedStyle(wrap).overflowX};
        card.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        card.classList.remove('flash');
        return {before, during};
    }""")
    check("pressing a card does not add a vertical scrollbar",
          scroll["during"]["v"] == scroll["before"]["v"],
          f"{scroll['before']['v']} -> {scroll['during']['v']}")
    check("the card area never scrolls sideways",
          not scroll["during"]["h"] and scroll["during"]["overflowX"] == "hidden",
          scroll["during"]["overflowX"])

    # -- the strip can run the full height of the window ---------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    check("full-height strip is on by default", page.is_checked("#set-full-strip"))

    tall = page.evaluate("""() => {
        const strip = document.getElementById('filmstrip').getBoundingClientRect();
        const bottom = document.getElementById('bottom').getBoundingClientRect();
        return {stripBottom: strip.bottom, bottomBottom: bottom.bottom};
    }""")
    check("strip reaches past the category area",
          tall["stripBottom"] >= tall["bottomBottom"] - 1,
          f"strip ends at {tall['stripBottom']:.0f}, categories at {tall['bottomBottom']:.0f}")

    page.uncheck("#set-full-strip")
    page.wait_for_timeout(600)
    short = page.evaluate("""() => {
        const strip = document.getElementById('filmstrip').getBoundingClientRect();
        const bottom = document.getElementById('bottom').getBoundingClientRect();
        return {stripBottom: strip.bottom, bottomTop: bottom.top};
    }""")
    check("turning it off stops the strip above the categories",
          short["stripBottom"] <= short["bottomTop"] + 1,
          f"strip ends at {short['stripBottom']:.0f}, categories start at {short['bottomTop']:.0f}")
    check("full-height strip setting persisted",
          json.loads((SP / "config.json").read_text(encoding="utf-8"))["full_height_strip"] is False)
    page.check("#set-full-strip")
    page.wait_for_timeout(600)

    # -- thumbnail shape ------------------------------------------------------
    check("three thumbnail shapes offered",
          page.locator("#set-thumb-ratio option").count() == 3)
    check("vertical is the default",
          page.input_value("#set-thumb-ratio") == "vertical",
          page.input_value("#set-thumb-ratio"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    def strip_shape():
        return page.evaluate("""() => {
            const i = document.querySelector('.thumb img').getBoundingClientRect();
            return i.width / i.height;
        }""")

    def tile_shape():
        return page.evaluate("""() => {
            const i = document.querySelector('.card-previews img');
            if (!i) return null;
            const r = i.getBoundingClientRect();
            return r.width / r.height;
        }""")

    check("strip thumbnails are tall by default", abs(strip_shape() - 9 / 16) < 0.06,
          f"{strip_shape():.2f} (want {9/16:.2f})")
    shape = tile_shape()
    check("card previews are tall by default", shape is not None and abs(shape - 9 / 16) < 0.12,
          f"{shape}")

    for ratio, want in (("horizontal", 16 / 9), ("square", 1.0)):
        open_settings(page)
        page.wait_for_selector("#modal-settings:not([hidden])")
        page.select_option("#set-thumb-ratio", ratio)
        page.wait_for_timeout(700)
        page.keyboard.press("Escape")
        page.wait_for_timeout(700)
        check(f"{ratio} thumbnails in the strip", abs(strip_shape() - want) < 0.12,
              f"{strip_shape():.2f} (want {want:.2f})")
        got = tile_shape()
        check(f"{ratio} previews on the cards", got is not None and abs(got - want) < 0.2,
              f"{got}")
    page.screenshot(path=str(OUT / "12-shapes.png"))

    # -- one top bar ----------------------------------------------------------
    header = page.evaluate("""() => {
        const bar = document.querySelector('.topbar');
        const tops = new Set([...bar.querySelectorAll('.btn')]
            .filter(b => b.offsetParent !== null)
            .map(b => Math.round(b.getBoundingClientRect().top)));
        const ctrl = document.getElementById('dock-controls').getBoundingClientRect();
        const left = document.querySelector('.topbar-left').getBoundingClientRect();
        const right = document.querySelector('.topbar-right').getBoundingClientRect();
        const folder = document.getElementById('btn-folder').getBoundingClientRect();
        const menu = document.getElementById('btn-menu').getBoundingClientRect();
        const widths = [...bar.querySelectorAll('.btn')]
            .filter(b => b.offsetParent !== null)
            .map(b => ({id: b.id, w: b.getBoundingClientRect().width,
                        scroll: b.scrollWidth}));
        return {rows: tops.size, height: bar.getBoundingClientRect().height,
                overflows: bar.scrollWidth > bar.clientWidth + 1,
                hasBrand: !!bar.querySelector('.brand'),
                ctrl: [ctrl.left, ctrl.right], leftRight: left.right,
                rightLeft: right.left, folderWidth: folder.width,
                menuWidth: menu.width, menuRight: menu.right,
                barRight: bar.getBoundingClientRect().right,
                widths};
    }""")
    check("the header is a single row", header["rows"] == 1 and header["height"] < 70,
          f"{header['rows']} row(s), {header['height']:.0f}px tall")
    check("the tool name is gone from the header", not header["hasBrand"])
    check("nothing in the header overflows", not header["overflows"])

    offset = ((header["ctrl"][0] + header["ctrl"][1]) / 2) - (1440 / 2)
    check("the Prev/Skip row is centred in the window", abs(offset) < 12,
          f"{offset:.0f}px off centre")
    check("Categories is on the left", header["leftRight"] <= header["ctrl"][0] + 1,
          f"left group ends {header['leftRight']:.0f}, controls start {header['ctrl'][0]:.0f}")
    check("the path and the menu are on the right",
          header["rightLeft"] >= header["ctrl"][1] - 1,
          f"right group starts {header['rightLeft']:.0f}, controls end {header['ctrl'][1]:.0f}")
    check("the path button is the big one", header["folderWidth"] >= 260,
          f"{header['folderWidth']:.0f}px")
    check("the menu button is a normal size", header["menuWidth"] >= 34,
          f"{header['menuWidth']:.0f}px")
    check("no header button is squeezed below its content",
          all(w["w"] >= w["scroll"] - 1 or w["id"] == "btn-folder" for w in header["widths"]),
          str([w for w in header["widths"] if w["w"] < w["scroll"] - 1]))

    # the menu holds what used to be loose in the bar
    page.click("#btn-menu")
    page.wait_for_selector("#context-menu:not([hidden])")
    entries = page.locator("#context-menu button").all_inner_texts()
    check("the menu has Settings, shortcuts, Save and Load",
          any("Settings" in e for e in entries) and any("shortcut" in e for e in entries)
          and any("Save" in e for e in entries) and any("Load" in e for e in entries),
          str(entries))
    menu_box = page.locator("#context-menu").bounding_box()
    check("the menu opens at the top right",
          menu_box["y"] < 120 and menu_box["x"] > 1440 / 2,
          f"at {menu_box['x']:.0f},{menu_box['y']:.0f}")
    check("the menu offers Clear input", any("Clear input" in e for e in entries),
          str(entries))
    page.screenshot(path=str(OUT / "17-menu.png"))

    # pressing the button again closes it
    page.click("#btn-menu")
    page.wait_for_timeout(250)
    check("pressing the hamburger again closes the menu",
          page.locator("#context-menu").is_hidden())
    page.click("#btn-menu")
    page.wait_for_timeout(250)
    check("and again reopens it", page.locator("#context-menu").is_visible())
    page.click("#btn-menu")
    page.wait_for_timeout(250)
    page.click("#viewer", position={"x": 20, "y": 20})
    page.wait_for_timeout(300)
    # -- clicking a thumbnail selects, it does not act -------------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    page.select_option("#set-apply-mode", "immediate")
    page.wait_for_timeout(500)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    state_before = page.evaluate("() => ({index: state.index, pending: state.pending, "
                                 "skipped: state.skipped, sorted: state.sorted})")
    names = page.evaluate("() => state.upcoming.map(u => u.name)")
    page.locator(".thumb").nth(2).click()
    page.wait_for_timeout(600)
    after = page.evaluate("() => ({index: state.index, selection: state.selection, "
                          "target: state.target, pending: state.pending, "
                          "skipped: state.skipped, sorted: state.sorted})")
    check("clicking a thumbnail shows that image",
          page.locator("#info-name").inner_text() == names[2],
          f"{page.locator('#info-name').inner_text()} (wanted {names[2]})")
    check("clicking a thumbnail leaves the queue where it was",
          after["index"] == state_before["index"], f"{state_before['index']} -> {after['index']}")
    check("clicking a thumbnail decides nothing",
          after["pending"] == state_before["pending"]
          and after["skipped"] == state_before["skipped"]
          and after["sorted"] == state_before["sorted"],
          str(after))
    check("the queue position is still marked in the strip",
          page.locator(".thumb.cursor-at").count() == 1)

    # acting on a look-ahead returns to the queue afterwards
    page.locator(".card").first.click()
    page.wait_for_timeout(800)
    check("sorting a looked-at image files that one",
          (ROOT / "Keep" / names[2]).exists(), names[2])
    check("and the queue carries on where it was",
          page.locator("#info-name").inner_text() == names[0],
          page.locator("#info-name").inner_text())

    # -- drag a thumbnail onto a card -----------------------------------------
    names = page.evaluate("() => state.upcoming.map(u => u.name)")
    dragged = names[1]
    source = page.locator(".thumb").nth(1)
    target = page.locator(".card").nth(1)          # "Maybe"
    source.hover()
    page.mouse.down()
    box = target.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
    check("a ghost follows the pointer while dragging",
          page.locator(".drag-ghost").count() == 1)
    check("the card under the pointer lights up",
          page.locator(".card.drop-target").count() == 1)
    page.mouse.up()
    page.wait_for_timeout(900)
    check("dragging a thumbnail onto a card sorts that image",
          (ROOT / "Maybe" / dragged).exists(), dragged)
    check("its sidecar went too",
          (ROOT / "Maybe" / dragged.replace(".png", ".txt")).exists())
    check("the ghost is gone afterwards", page.locator(".drag-ghost").count() == 0)
    check("nothing is left marked as dragging",
          page.locator(".dragging").count() == 0)

    # dragging the big image works the same way, and a cancelled drag cleans up
    main_box = page.locator("#main-image").bounding_box()
    page.mouse.move(main_box["x"] + main_box["width"] / 2, main_box["y"] + main_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(main_box["x"] + main_box["width"] / 2 - 120,
                    main_box["y"] + main_box["height"] / 2 + 60, steps=8)
    check("the main image can be dragged", page.locator(".drag-ghost").count() == 1)
    opacity_during = page.evaluate(
        "() => getComputedStyle(document.getElementById('main-image')).opacity")
    page.keyboard.press("Escape")          # cancel it
    page.mouse.up()
    page.wait_for_timeout(500)
    check("a cancelled drag leaves the image alone",
          page.evaluate("() => getComputedStyle(document.getElementById('main-image')).opacity") == "1"
          and page.locator(".drag-ghost").count() == 0,
          f"during {opacity_during}, after "
          + page.evaluate("() => getComputedStyle(document.getElementById('main-image')).opacity"))

    main_name = page.locator("#info-name").inner_text()
    main_box = page.locator("#main-image").bounding_box()
    target = page.locator(".card").nth(2)
    page.mouse.move(main_box["x"] + main_box["width"] / 2, main_box["y"] + main_box["height"] / 2)
    page.mouse.down()
    box = target.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
    page.mouse.up()
    page.wait_for_timeout(900)
    check("dragging the main image onto a card files it",
          (ROOT / "Discard" / main_name).exists(), main_name)

    # -- right-click menu and Clear -------------------------------------------
    keep_before = len(list((ROOT / "Keep").glob("*.png")))
    check("Keep has files to clear", keep_before > 0, str(keep_before))
    page.locator(".card").first.click(button="right")
    page.wait_for_selector("#context-menu:not([hidden])")
    labels = page.locator("#context-menu button").all_inner_texts()
    check("context menu offers Edit and Clear",
          any(l.startswith("Edit") for l in labels) and any(l.startswith("Clear") for l in labels),
          str(labels))
    clearable = page.evaluate("() => state.categories[0].clearable")
    check("Clear says how many it would take back",
          any(f"({clearable})" in l for l in labels) and clearable == keep_before,
          f"{labels} (folder has {keep_before}, clearable {clearable})")
    page.screenshot(path=str(OUT / "13-context-menu.png"))

    page.once("dialog", lambda d: d.accept())
    page.locator("#context-menu button", has_text="Clear").click()
    page.wait_for_timeout(1000)
    check("Clear emptied the folder back to the source",
          len(list((ROOT / "Keep").glob("*.png"))) == 0
          and (SP / "demo" / "in" / names[0]).exists(),
          str(sorted(f.name for f in (ROOT / "Keep").glob("*"))))
    check("cleared images are queued again",
          page.evaluate("() => state.categories[0].count") == 0)

    # -- cards leave no empty space -------------------------------------------
    def coverage():
        # Each row must span the full usable width (gaps between cards are
        # fine; a short last row is not) and the rows must fill the height.
        return page.evaluate("""() => {
            const wrap = document.getElementById('categories');
            const inner = wrap.clientWidth;
            const left = wrap.getBoundingClientRect().left;
            const cards = [...document.querySelectorAll('.card')].map(c => c.getBoundingClientRect());
            const rows = {};
            cards.forEach(c => {
                const key = Math.round(c.top);
                rows[key] = rows[key] || {left: Infinity, right: -Infinity};
                rows[key].left = Math.min(rows[key].left, c.left);
                rows[key].right = Math.max(rows[key].right, c.right);
            });
            const shortfalls = Object.values(rows).map(r => inner - (r.right - r.left));
            const bottom = Math.max(...cards.map(c => c.bottom));
            const top = Math.min(...cards.map(c => c.top));
            return {worstRowGap: Math.max(...shortfalls), rows: Object.keys(rows).length,
                    heightUsed: (bottom - top) / wrap.clientHeight, n: cards.length};
        }""")

    for count, label in ((3, "three"), (5, "five"), (7, "seven")):
        page.click("#btn-manage")
        page.wait_for_selector("#modal-categories:not([hidden])")
        rows_now = page.locator("#cat-rows tr").count()
        while page.locator("#cat-rows tr").count() > count:
            page.locator("#cat-rows tr").last.locator(".row-del").click()
        while page.locator("#cat-rows tr").count() < count:
            page.click("#cat-add-row")
            last = page.locator("#cat-rows tr").last
            index = page.locator("#cat-rows tr").count()
            last.locator("input[type=text]").first.fill(f"extra{index}")
            last.locator("input[type=text]").nth(1).fill(f"extra{index}")
        page.click("#cat-table-save")
        page.wait_for_timeout(800)
        cover = coverage()
        check(f"{label} cards leave no gap on any row", cover["worstRowGap"] < 14,
              f"worst gap {cover['worstRowGap']:.0f}px over {cover['rows']} row(s)")
        check(f"{label} cards fill the height", cover["heightUsed"] > 0.96,
              f"{cover['heightUsed'] * 100:.0f}%")
    page.screenshot(path=str(OUT / "14-no-gaps.png"))

    # -- the card layout setting ----------------------------------------------
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    check("three card layouts offered", page.locator("#set-card-layout option").count() == 3)
    check("grid is the default", page.input_value("#set-card-layout") == "grid")
    page.select_option("#set-card-layout", "rows")
    page.wait_for_timeout(700)
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    stacked = page.evaluate("""() => new Set([...document.querySelectorAll('.card')]
        .map(c => Math.round(c.getBoundingClientRect().top))).size""")
    check("'one per row' stacks them vertically",
          stacked == page.locator(".card").count(),
          f"{stacked} rows for {page.locator('.card').count()} cards")

    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    page.select_option("#set-card-layout", "columns")
    page.wait_for_timeout(700)
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)
    one_row = page.evaluate("""() => new Set([...document.querySelectorAll('.card')]
        .map(c => Math.round(c.getBoundingClientRect().top))).size""")
    check("'all on one row' puts them side by side", one_row == 1, f"{one_row} row(s)")
    open_settings(page)
    page.wait_for_selector("#modal-settings:not([hidden])")
    page.select_option("#set-card-layout", "grid")
    page.wait_for_timeout(600)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    # -- the category table buttons moved -------------------------------------
    page.click("#btn-manage")
    page.wait_for_selector("#modal-categories:not([hidden])")
    places = page.evaluate("""() => {
        const table = document.querySelector('.table-wrap').getBoundingClientRect();
        const addRow = document.getElementById('cat-add-row').getBoundingClientRect();
        const bulkBox = document.querySelector('.bulk').getBoundingClientRect();
        const add = document.getElementById('bulk-add').getBoundingClientRect();
        const text = document.getElementById('bulk-names').getBoundingClientRect();
        return {addRowTop: addRow.top, tableBottom: table.bottom, bulkTop: bulkBox.top,
                addBottom: add.bottom, bulkBottom: bulkBox.bottom, textBottom: text.bottom};
    }""")
    check("'+ Row' sits under the table",
          places["addRowTop"] >= places["tableBottom"] - 1
          and places["addRowTop"] <= places["bulkTop"] + 1,
          f"row button at {places['addRowTop']:.0f}, table ends {places['tableBottom']:.0f}")
    check("'Add these' sits on the bottom line of the quick-add box",
          abs(places["addBottom"] - places["textBottom"]) < 6,
          f"button ends {places['addBottom']:.0f}, box ends {places['textBottom']:.0f}")
    page.screenshot(path=str(OUT / "15-table.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # -- the drop zone ---------------------------------------------------------
    drop = page.evaluate("""() => {
        const zone = document.getElementById('dropzone');
        const dt = new DataTransfer();
        const enter = new DragEvent('dragenter', {bubbles: true, dataTransfer: dt});
        // A real folder drag carries a file item; fake one.
        Object.defineProperty(dt, 'items', {value: [{kind: 'file'}]});
        document.dispatchEvent(enter);
        const shown = !document.getElementById('drop-overlay').hidden;
        document.dispatchEvent(new DragEvent('dragleave', {bubbles: true, dataTransfer: dt}));
        return {exists: !!zone, shown, hiddenAfter: document.getElementById('drop-overlay').hidden};
    }""")
    check("there is a drop area for a folder", drop["exists"])
    check("dragging a folder over the window shows the drop overlay", drop["shown"])
    check("leaving hides it again", drop["hiddenAfter"])

    # -- dropping a handful of images rather than a folder --------------------
    picked = sorted(f.name for f in (SP / "demo" / "in").glob("*.png"))[:2]
    if len(picked) >= 2:
        loaded = page.evaluate("""async (names) => {
            const found = await fetch('/api/resolve-files', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({names})}).then(r => r.json());
            if (!found.paths.length) return {total: -1, missing: found.missing};
            const state = await fetch('/api/images', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({paths: found.paths})}).then(r => r.json());
            return {total: state.total, first: state.current && state.current.name,
                    missing: found.missing};
        }""", picked)
        check("a handful of dropped images becomes the queue",
              loaded["total"] == len(picked), str(loaded))
        check("and the first of them is showing", loaded["first"] in picked,
              str(loaded.get("first")))
        check("the header says where they came from",
              page.locator("#folder-label").inner_text().endswith("in"),
              page.locator("#folder-label").inner_text())

        # images from two different folders keep their own folders
        spread = page.evaluate("""async (paths) => {
            const state = await fetch('/api/images', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({paths})}).then(r => r.json());
            return {total: state.total, folder: state.project.source_folder,
                    folders: state.project.folders, label: state.project.source_label,
                    warnings: state.warnings};
        }""", [str(SP / "demo" / "in" / picked[0]),
               str(ROOT / "Maybe" / sorted(f.name for f in (ROOT / "Maybe").glob("*.png"))[0])])
        check("images from two folders load together", spread["total"] == 2, str(spread))
        check("no single folder is invented for them",
              spread["folder"] == "" and spread["folders"] == 2, str(spread))
        check("the header says how many folders", "2 folder" in spread["label"],
              spread["label"])
        check("and it says each goes back to its own folder",
              any("own folder" in w for w in spread["warnings"]), str(spread["warnings"]))

        # dropping more while sorting adds to the list instead of replacing it
        page.evaluate("async () => render(await (await fetch('/api/state')).json())")
        page.wait_for_timeout(500)
        before_total = page.evaluate("() => state.total")
        before_first = page.locator("#info-name").inner_text()
        grown = page.evaluate("""async (paths) => {
            const state = await fetch('/api/images', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({paths, add: true})}).then(r => r.json());
            return state.total;
        }""", [str(SP / "demo" / "in" / f.name)
               for f in sorted((SP / "demo" / "in").glob("*.png"))[2:4]])
        page.evaluate("async () => render(await (await fetch('/api/state')).json())")
        page.wait_for_timeout(600)
        check("dropping more images adds to the list", grown > before_total,
              f"{before_total} -> {grown}")
        check("the strip shows them too",
              page.locator(".thumb").count() == grown,
              f"{page.locator('.thumb').count()} thumbs for {grown} images")
        check("and the current image did not change",
              page.locator("#info-name").inner_text() == before_first,
              page.locator("#info-name").inner_text())

        page.reload()
        page.wait_for_timeout(900)

    # -- the header stays on one row at any width -----------------------------
    # Make the two extra buttons visible so the header is under real pressure.
    page.evaluate("""() => {
        document.getElementById('btn-apply').hidden = false;
        document.getElementById('btn-discard').hidden = false;
        fitHeader();
    }""")
    for width, label in ((1440, "wide"), (1100, "medium"), (860, "narrow"),
                         (720, "vertical screen"), (560, "very narrow"),
                         (420, "phone width")):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(400)
        shape = page.evaluate("""() => {
            const bar = document.querySelector('.topbar');
            const box = bar.getBoundingClientRect();
            const buttons = [...bar.querySelectorAll('.btn')].filter(b => b.offsetParent !== null);
            const rects = buttons.map(b => b.getBoundingClientRect());
            const tops = new Set(rects.map(r => Math.round(r.top)));
            const outside = buttons.filter((b, i) =>
                rects[i].right > box.right + 1 || rects[i].left < box.left - 1).map(b => b.id);
            let overlap = false;
            for (let i = 0; i < rects.length; i++) {
                for (let j = i + 1; j < rects.length; j++) {
                    if (rects[i].right > rects[j].left + 1 && rects[j].right > rects[i].left + 1
                        && rects[i].bottom > rects[j].top + 1 && rects[j].bottom > rects[i].top + 1) {
                        overlap = true;
                    }
                }
            }
            return {rows: tops.size, height: box.height, outside, overlap,
                    classes: bar.className, buttons: buttons.length};
        }""")
        check(f"header is one row at {width}px ({label})",
              shape["rows"] == 1 and shape["height"] < 62,
              f"{shape['rows']} row(s), {shape['height']:.0f}px, {shape['classes']}")
        check(f"every header button still fits at {width}px",
              not shape["outside"] and not shape["overlap"],
              f"outside={shape['outside']} overlap={shape['overlap']}")
        if width <= 720:
            page.screenshot(path=str(OUT / f"18-header-{width}.png"),
                            clip={"x": 0, "y": 0, "width": width, "height": 60})
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(400)
    page.evaluate("() => { render(state); }")
    page.wait_for_timeout(300)

    # -- the setup is saved and offered back ----------------------------------
    # Back to the plain folder first: the dropped-set case is covered above.
    page.evaluate("""(path) => fetch('/api/folder', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})})""", str(SP / "demo" / "in"))
    page.wait_for_timeout(700)
    saved = json.loads((SP / "config.json").read_text(encoding="utf-8")).get("last_session", {})
    check("the categories were saved without being asked",
          len(saved.get("categories", [])) > 0,
          f"{len(saved.get('categories', []))} saved")
    check("their hotkeys were saved too",
          any(c.get("hotkey") for c in saved.get("categories", [])))
    check("the image folder was saved", saved.get("source_folder", "").endswith("in"),
          saved.get("source_folder", ""))

    # a brand new session must offer it back
    restart_app()
    page.reload()
    page.wait_for_selector("#modal-resume:not([hidden])", timeout=8000)
    summary = page.locator("#resume-summary").inner_text()
    check("a fresh start offers last time's setup",
          "categor" in summary, summary.replace("\n", " "))
    page.screenshot(path=str(OUT / "16-resume.png"))

    page.click("#resume-yes")
    page.wait_for_timeout(1200)
    check("using it brings the categories back",
          page.locator(".card:not(.skipped)").count() == len(saved["categories"]),
          f"{page.locator('.card:not(.skipped)').count()} cards")
    check("and the hotkeys with them",
          page.locator(".card .hk:not(.none)").count() > 0)
    check("and the image folder",
          page.evaluate("() => state.project.source_folder").endswith("in"))

    # starting fresh instead
    restart_app()
    page.reload()
    page.wait_for_selector("#modal-resume:not([hidden])", timeout=8000)
    page.click("#resume-no")
    page.wait_for_timeout(700)
    check("starting fresh leaves it empty",
          page.locator(".card").count() == 0
          and page.evaluate("() => state.project.source_folder") == "")
    check("and does not ask again in the same run",
          page.evaluate("() => state.resume.available") is False)

    # -- Clear input ----------------------------------------------------------
    page.evaluate("""(path) => fetch('/api/folder', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path})})""", str(SP / "demo" / "in"))
    page.wait_for_timeout(700)
    page.evaluate("async () => render(await (await fetch('/api/state')).json())")
    page.wait_for_timeout(400)
    categories_before = page.locator(".card:not(.skipped)").count()
    check("there is something loaded to clear",
          page.evaluate("() => state.total") > 0)

    page.click("#btn-menu")
    page.wait_for_selector("#context-menu:not([hidden])")
    page.once("dialog", lambda d: (
        check("Clear input warns about what is loaded", "image(s) are loaded" in d.message,
              d.message.replace("\n", " ")),
        d.accept()))
    page.locator("#context-menu button", has_text="Clear input").click()
    page.wait_for_timeout(800)

    check("Clear input empties the image list",
          page.evaluate("() => state.total") == 0
          and page.locator(".thumb").count() == 0)
    check("and keeps the categories",
          page.locator(".card:not(.skipped)").count() == categories_before,
          f"{page.locator('.card:not(.skipped)').count()} of {categories_before}")
    check("and forgets the folder",
          page.evaluate("() => state.project.source_folder") == "")
    page.screenshot(path=str(OUT / "19-cleared.png"))

    page.click("#btn-menu")
    page.wait_for_selector("#context-menu:not([hidden])")
    disabled = page.locator("#context-menu button", has_text="Clear input").is_disabled()
    check("Clear input is greyed out with nothing loaded", disabled)
    page.click("#btn-menu")
    page.wait_for_timeout(250)

    page.screenshot(path=str(OUT / "07-final.png"))
    browser.close()

print("\nconsole/page errors:", errors or "none")
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} UI checks passed")
sys.exit(1 if failed or errors else 0)
