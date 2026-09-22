"""FastAPI application serving the UI and the sorting API."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, thumbnails
from . import droppedfolder, nativedialog
from .config import (APPLY_MODES, CARD_LAYOUTS, FILE_ACTIONS, IMAGE_FITS,
                     SORT_ORDERS, THUMB_RATIOS)
from .filebrowser import create_folder, home, listing
from .session import Session

WEB_DIR = Path(__file__).parent / "web"

session = Session()


# -- request bodies -------------------------------------------------------
class FolderBody(BaseModel):
    path: str


class CategoryBody(BaseModel):
    name: str = ""
    folder: str = ""
    hotkey: str = ""
    color: str = ""


class CategoryTableBody(BaseModel):
    categories: list[dict[str, Any]]


class BulkBody(BaseModel):
    names: list[str]


class PresetBody(BaseModel):
    name: str
    replace: bool = True


class OrderBody(BaseModel):
    order: list[str]


class PathBody(BaseModel):
    path: str = ""


class NewFolderBody(BaseModel):
    parent: str
    name: str


class PickFolderBody(BaseModel):
    initial: str = ""
    title: str = "Select folder"


class DroppedFolderBody(BaseModel):
    name: str
    files: list[str] = []


class DroppedFilesBody(BaseModel):
    names: list[str]


class ImagesBody(BaseModel):
    paths: list[str]
    add: bool = False


class SettingsBody(BaseModel):
    """Every field is optional; only the ones sent are changed."""

    output_root: str | None = None
    recursive: bool | None = None
    sort_order: str | None = None
    move_sidecars: bool | None = None
    sidecar_extensions: list[str] | None = None
    file_action: str | None = None
    apply_mode: str | None = None
    create_folders_upfront: bool | None = None
    skip_hotkey: str | None = None
    show_filmstrip: bool | None = None
    filmstrip_size: int | None = None
    dock_height: int | None = None
    full_height_strip: bool | None = None
    show_card_thumbnails: bool | None = None
    card_thumb_size: int | None = None
    thumb_ratio: str | None = None
    card_layout: str | None = None
    show_card_counts: bool | None = None
    image_fit: str | None = None
    autosave: bool | None = None
    remember_last_project: bool | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Image Sorting Tool", version=__version__)

    def ok() -> JSONResponse:
        return JSONResponse(session.state())

    def fail(exc: Exception, code: int = 400) -> JSONResponse:
        return JSONResponse({**session.state(), "error": str(exc)}, status_code=code)

    # -- state ------------------------------------------------------------
    @app.get("/api/state")
    def get_state() -> JSONResponse:
        return ok()

    @app.post("/api/folder")
    def set_folder(body: FolderBody) -> JSONResponse:
        try:
            session.set_folder(body.path)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/folder/add")
    def add_folder(body: FolderBody) -> JSONResponse:
        """Add a folder's images to what is already loaded."""
        try:
            session.add_folder(body.path)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/rescan")
    def rescan() -> JSONResponse:
        try:
            session.reload_images()
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/settings")
    def settings(body: SettingsBody) -> JSONResponse:
        try:
            session.update_settings(body.model_dump(exclude_none=True))
        except Exception as exc:
            return fail(exc)
        return ok()

    # -- images -----------------------------------------------------------
    @app.get("/api/image/{index}")
    def image(index: int) -> Response:
        images = session.queue.images
        if not 0 <= index < len(images):
            raise HTTPException(404, "No such image.")
        path = images[index]
        if not path.exists():
            raise HTTPException(410, "That file is no longer on disk.")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/api/thumb/{index}")
    def thumb(index: int, size: int = Query(240, ge=32, le=1024)) -> Response:
        images = session.queue.images
        if not 0 <= index < len(images):
            raise HTTPException(404, "No such image.")
        try:
            data = thumbnails.render(images[index], size)
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        return Response(data, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/categories/{category_id}/previews")
    def category_previews(category_id: str, limit: int = Query(12, ge=1, le=64)) -> JSONResponse:
        previews = session.category_previews(category_id, limit)
        waiting = {str(i.path) for i in session.queue.staged_items
                   if i.category_id == category_id}
        by_path = {str(item.path): i for i, item in enumerate(session.queue.items)}
        return JSONResponse({"previews": [
            {"n": n, "name": p.name, "waiting": str(p) in waiting,
             "index": by_path.get(str(p), -1)}
            for n, p in enumerate(previews)
        ]})

    @app.get("/api/categories/{category_id}/preview/{n}")
    def category_preview(category_id: str, n: int,
                         size: int = Query(160, ge=32, le=512)) -> Response:
        previews = session.category_previews(category_id, n + 1)
        if n >= len(previews):
            raise HTTPException(404, "No preview there.")
        try:
            data = thumbnails.render(previews[n], size)
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc
        # The URL carries a version, so the browser may keep these.
        return Response(data, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=120"})

    @app.get("/api/categories/{category_id}/thumb")
    def category_thumb(category_id: str, size: int = Query(160, ge=32, le=512)) -> Response:
        return category_preview(category_id, 0, size)

    # -- actions ----------------------------------------------------------
    @app.post("/api/sort/{category_id}")
    def sort(category_id: str, index: int = Query(-1)) -> JSONResponse:
        """Sort the current image, or the one at `index` (drag and drop)."""
        try:
            if index >= 0:
                session.select(index)
            session.sort_current(category_id)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/skip")
    def skip(index: int = Query(-1)) -> JSONResponse:
        """Skip the current image, or the one at `index` (drag and drop)."""
        try:
            if index >= 0:
                session.select(index)
        except Exception as exc:
            return fail(exc)
        session.skip()
        return ok()

    @app.post("/api/skipped/restore/{index}")
    def restore_skipped(index: int) -> JSONResponse:
        try:
            session.restore_skipped(index)
        except Exception as exc:
            return fail(exc, 404)
        return ok()

    @app.post("/api/skipped/review")
    def review_skipped() -> JSONResponse:
        session.review_skipped()
        return ok()

    @app.post("/api/select/{index}")
    def select(index: int) -> JSONResponse:
        """Look at another image without changing where the queue is."""
        try:
            session.select(None if index < 0 else index)
        except Exception as exc:
            return fail(exc, 404)
        return ok()

    @app.post("/api/apply")
    def apply_staged() -> JSONResponse:
        try:
            session.apply_staged()
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/staged/discard")
    def discard_staged() -> JSONResponse:
        session.discard_staged()
        return ok()

    @app.post("/api/undo")
    def undo() -> JSONResponse:
        try:
            session.undo()
        except Exception as exc:
            return fail(exc)
        return ok()

    # -- categories -------------------------------------------------------
    @app.post("/api/categories")
    def add_category(body: CategoryBody) -> JSONResponse:
        if not body.name.strip() or not body.folder.strip():
            return fail(ValueError("A category needs a name and a folder."))
        try:
            session.add_category(body.name, body.folder, body.hotkey, body.color)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.put("/api/categories/{category_id}")
    def edit_category(category_id: str, body: CategoryBody) -> JSONResponse:
        try:
            session.update_category(
                category_id,
                name=body.name,
                folder=body.folder,
                hotkey=body.hotkey,
                color=body.color,
            )
        except KeyError:
            return fail(ValueError("Unknown category."), 404)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.delete("/api/categories/{category_id}")
    def remove_category(category_id: str) -> JSONResponse:
        try:
            session.delete_category(category_id)
        except KeyError:
            return fail(ValueError("Unknown category."), 404)
        return ok()

    @app.put("/api/categories")
    def save_category_table(body: CategoryTableBody) -> JSONResponse:
        try:
            session.replace_categories(body.categories)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/categories/bulk")
    def bulk_categories(body: BulkBody) -> JSONResponse:
        try:
            session.add_categories_bulk(body.names)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/categories/order")
    def order_categories(body: OrderBody) -> JSONResponse:
        by_id = {c.id: c for c in session.project.categories}
        reordered = [by_id[i] for i in body.order if i in by_id]
        reordered += [c for c in session.project.categories if c.id not in set(body.order)]
        session.project.categories = reordered
        return ok()

    @app.post("/api/categories/{category_id}/clear")
    def clear_category(category_id: str) -> JSONResponse:
        try:
            session.clear_category(category_id)
        except KeyError:
            return fail(ValueError("Unknown category."), 404)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/categories/create-folders")
    def make_folders() -> JSONResponse:
        try:
            session.create_category_folders()
        except Exception as exc:
            return fail(exc)
        return ok()

    # -- presets ----------------------------------------------------------
    @app.post("/api/presets/save")
    def preset_save(body: PresetBody) -> JSONResponse:
        try:
            session.save_preset(body.name)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/presets/load")
    def preset_load(body: PresetBody) -> JSONResponse:
        try:
            session.load_preset(body.name, body.replace)
        except KeyError:
            return fail(ValueError(f"No preset called '{body.name}'."), 404)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/presets/delete")
    def preset_delete(body: PresetBody) -> JSONResponse:
        try:
            session.delete_preset(body.name)
        except KeyError:
            return fail(ValueError(f"No preset called '{body.name}'."), 404)
        return ok()

    # -- carrying on from last time ----------------------------------------
    @app.post("/api/resume")
    def resume() -> JSONResponse:
        try:
            session.resume()
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/resume/dismiss")
    def dismiss_resume() -> JSONResponse:
        session.dismiss_resume()
        return ok()

    # -- project files ----------------------------------------------------
    @app.post("/api/project/load")
    def project_load(body: PathBody) -> JSONResponse:
        try:
            session.load_project_file(body.path)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/project/save")
    def project_save(body: PathBody) -> JSONResponse:
        try:
            session.save_project_file(body.path or None)
        except Exception as exc:
            return fail(exc)
        return ok()

    # -- folder browser ---------------------------------------------------
    @app.get("/api/browse")
    def browse(path: str = "") -> JSONResponse:
        return JSONResponse(listing(path or home()))

    @app.post("/api/browse/new")
    def browse_new(body: NewFolderBody) -> JSONResponse:
        try:
            created = create_folder(body.parent, body.name)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(listing(created))

    @app.get("/api/browse/files")
    def browse_files(path: str = "", suffix: str = ".json") -> JSONResponse:
        data = listing(path or home())
        folder = Path(data["path"])
        files = []
        try:
            files = [
                {"name": p.name, "path": str(p)}
                for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
                if p.is_file() and p.suffix.lower() == suffix.lower()
            ]
        except OSError:
            pass
        data["files"] = files
        return JSONResponse(data)

    # -- native dialogs and dropped folders --------------------------------
    @app.post("/api/pick-folder")
    def pick_folder(body: PickFolderBody) -> JSONResponse:
        if not nativedialog.available():
            return JSONResponse({"supported": False, "path": ""})
        try:
            chosen = nativedialog.pick_folder(body.initial, body.title)
        except Exception as exc:
            return JSONResponse({"supported": False, "path": "", "error": str(exc)})
        return JSONResponse({"supported": True, "path": chosen or ""})

    @app.post("/api/resolve-folder")
    def resolve_folder(body: DroppedFolderBody) -> JSONResponse:
        """A browser only gives us the name of a dropped folder; find it."""
        hints = [session.project.source_folder, session.config.output_root]
        matches = droppedfolder.resolve(body.name, body.files, hints)
        return JSONResponse({"matches": matches})

    @app.post("/api/resolve-files")
    def resolve_files(body: DroppedFilesBody) -> JSONResponse:
        """Same problem as a dropped folder: only the file names reach us."""
        hints = [session.project.source_folder, session.config.output_root]
        paths, missing = droppedfolder.resolve_files(body.names[:60], hints)
        return JSONResponse({"paths": paths, "missing": missing})

    @app.post("/api/images")
    def set_images(body: ImagesBody) -> JSONResponse:
        try:
            if body.add:
                session.add_images(body.paths)
            else:
                session.set_images(body.paths)
        except Exception as exc:
            return fail(exc)
        return ok()

    @app.post("/api/input/clear")
    def clear_input() -> JSONResponse:
        session.clear_input()
        return ok()

    @app.get("/api/env")
    def env() -> JSONResponse:
        return JSONResponse({
            "version": __version__,
            "platform": sys.platform,
            "home": home(),
            "config_file": str(session.config.file),
            "sort_orders": list(SORT_ORDERS),
            "image_fits": list(IMAGE_FITS),
            "file_actions": list(FILE_ACTIONS),
            "apply_modes": list(APPLY_MODES),
            "thumb_ratios": list(THUMB_RATIOS),
            "card_layouts": list(CARD_LAYOUTS),
            "native_dialogs": nativedialog.available(),
        })

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
