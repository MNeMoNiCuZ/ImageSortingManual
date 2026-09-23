"""Tests for the scanner, the move/undo engine, settings and the HTTP API."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from trimage.config import AppConfig
from trimage.models import DEFAULT_CATEGORIES, Category, suggest_hotkeys
from trimage.scanner import (count_images, duplicate_stems, newest_image,
                                 scan_folder, sidecar_files)
from trimage.session import Session
from trimage.sorter import PENDING, SKIPPED, SORTED, SortQueue, unique_destination


DEFAULT_NAMES = [c["name"] for c in DEFAULT_CATEGORIES]


def make_image(path: Path, size=(24, 16)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 40, 200)).save(path)
    return path


@pytest.fixture
def library(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    make_image(source / "cat.png")
    (source / "cat.txt").write_text("a cat", encoding="utf-8")
    (source / "cat.caption").write_text("caption", encoding="utf-8")
    make_image(source / "cat2.png")           # must NOT be treated as a cat sidecar
    (source / "cat2.txt").write_text("other", encoding="utf-8")
    make_image(source / "nested" / "dog.jpg")
    return source


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    """A config that writes to the temp dir, never the real config.json."""
    fresh = AppConfig(apply_mode="immediate")
    fresh._file = tmp_path / "config.json"
    return fresh


@pytest.fixture
def session(library: Path, config: AppConfig) -> Session:
    instance = Session(config)
    # Start from nothing: the default categories have their own tests, and
    # every other test here sets up the categories it needs.
    instance.project.categories = []
    instance.set_folder(str(library))
    return instance


# -- scanner --------------------------------------------------------------
def test_scan_is_recursive(library: Path):
    assert len(scan_folder(library, recursive=True)) == 3


def test_scan_non_recursive(library: Path):
    assert len(scan_folder(library, recursive=False)) == 2


def test_scan_order_by_size(tmp_path: Path):
    make_image(tmp_path / "small.png", (8, 8))
    make_image(tmp_path / "big.png", (400, 400))
    assert scan_folder(tmp_path, order="largest")[0].name == "big.png"
    assert scan_folder(tmp_path, order="smallest")[0].name == "small.png"


def test_sidecars_match_stem_exactly(library: Path):
    names = {p.name for p in sidecar_files(library / "cat.png")}
    assert names == {"cat.txt", "cat.caption"}


def test_sidecars_can_be_filtered_by_extension(library: Path):
    names = {p.name for p in sidecar_files(library / "cat.png", ["txt"])}
    assert names == {"cat.txt"}


def test_duplicate_stems(tmp_path: Path):
    make_image(tmp_path / "a" / "x.png")
    make_image(tmp_path / "b" / "x.png")
    assert "x" in duplicate_stems(scan_folder(tmp_path))


def test_count_and_newest(library: Path):
    assert count_images(library) == 2          # nested/dog.jpg is not counted
    assert newest_image(library) is not None


# -- sorter ---------------------------------------------------------------
def test_sort_moves_image_and_sidecars(library: Path, tmp_path: Path):
    destination = tmp_path / "keep"
    queue = SortQueue()
    queue.load(library)
    record = queue.sort_current("id", "Keep", destination)

    assert len(record.moves) == 3
    assert (destination / "cat.png").exists()
    assert (destination / "cat.txt").exists()
    assert not (library / "cat.png").exists()
    assert (library / "cat2.png").exists()
    assert queue.items[0].status == SORTED
    assert queue.index == 1


def test_copy_leaves_the_original(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", tmp_path / "keep", copy=True)
    assert (library / "cat.png").exists()
    assert (tmp_path / "keep" / "cat.png").exists()


def test_undo_of_a_copy_removes_the_copy(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", tmp_path / "keep", copy=True)
    queue.undo()
    assert (library / "cat.png").exists()
    assert not (tmp_path / "keep" / "cat.png").exists()


def test_undo_restores_everything(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", tmp_path / "keep")
    queue.undo()

    assert (library / "cat.png").exists()
    assert (library / "cat.txt").exists()
    assert (library / "cat.caption").exists()
    assert queue.index == 0
    assert queue.items[0].status == PENDING
    assert not queue.can_undo()


def test_collision_gets_a_new_name(library: Path, tmp_path: Path):
    destination = tmp_path / "keep"
    destination.mkdir()
    make_image(destination / "cat.png")

    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", destination)
    assert (destination / "cat (2).png").exists()


def test_unique_destination(tmp_path: Path):
    target = tmp_path / "f.txt"
    assert unique_destination(target) == target
    target.write_text("x", encoding="utf-8")
    assert unique_destination(target).name == "f (2).txt"


def test_skip_marks_and_advances(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.skip()
    assert queue.items[0].status == SKIPPED
    assert queue.index == 1
    assert queue.count(SKIPPED) == 1
    assert queue.remaining == 2


def test_review_skipped_requeues_them(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.skip()
    queue.skip()
    assert queue.index == 2
    assert queue.review_skipped() == 2
    assert queue.index == 0
    assert queue.count(SKIPPED) == 0
    assert queue.remaining == 3


def test_undo_takes_back_a_skip(library: Path):
    queue = SortQueue()
    queue.load(library)
    first = queue.current.name

    queue.skip()
    assert queue.count(SKIPPED) == 1
    assert queue.can_undo() is True

    record = queue.undo()
    assert record.kind == "skip"
    assert queue.count(SKIPPED) == 0
    assert queue.index == 0
    assert queue.current.name == first


def test_undo_walks_back_through_both_kinds(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", tmp_path / "keep")
    queue.skip()
    queue.sort_current("id", "Keep", tmp_path / "keep")
    assert (queue.count(SORTED), queue.count(SKIPPED)) == (2, 1)

    assert queue.undo().kind == "sort"
    assert queue.undo().kind == "skip"
    assert queue.undo().kind == "sort"
    assert queue.can_undo() is False
    assert queue.count(PENDING) == 3
    assert (library / "cat.png").exists()


def test_undoing_a_skipped_look_ahead(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.select(2)
    queue.skip()
    assert queue.index == 0                 # the queue never moved
    queue.undo()
    assert queue.count(SKIPPED) == 0
    assert queue.index == 0
    assert queue.selection == 2             # back to looking at it


def test_restore_one_skipped_image(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.skip()
    queue.skip()
    assert queue.count(SKIPPED) == 2

    assert queue.restore_skipped(0) is True
    assert queue.items[0].status == PENDING
    assert queue.count(SKIPPED) == 1
    # It left the history with it, so Undo does not re-skip it.
    assert len(queue.history) == 1
    assert queue.undo().kind == "skip"
    assert queue.count(SKIPPED) == 0


def test_restore_rejects_what_is_not_skipped(library: Path):
    queue = SortQueue()
    queue.load(library)
    assert queue.restore_skipped(0) is False
    assert queue.restore_skipped(99) is False


def test_review_skipped_clears_their_history(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.skip()
    queue.skip()
    queue.review_skipped()
    assert queue.can_undo() is False        # nothing left to take back


def test_session_restore_skipped(session: Session):
    session.skip()
    session.skip()
    session.restore_skipped(1)
    state = session.state()
    assert state["skipped"] == 1
    assert state["selection"] == 1
    assert state["current"]["name"] == "cat2.png"


def test_api_restore_skipped(client):
    client.post("/api/skip")
    client.post("/api/skip")
    state = client.post("/api/skipped/restore/0").json()
    assert state["skipped"] == 1
    assert client.post("/api/skipped/restore/0").status_code == 404


def test_api_undo_a_skip(client):
    state = client.post("/api/skip").json()
    assert state["skipped"] == 1 and state["can_undo"] is True
    state = client.post("/api/undo").json()
    assert state["skipped"] == 0
    assert state["pending"] == 3


def test_skipped_previews_carry_their_queue_index(client):
    from trimage.session import SKIPPED_ID

    client.post("/api/skip")
    data = client.get(f"/api/categories/{SKIPPED_ID}/previews").json()["previews"]
    assert data[0]["index"] == 0


def test_skipped_images_newest_first(library: Path):
    queue = SortQueue()
    queue.load(library)
    first = queue.current.name
    queue.skip()
    second = queue.current.name
    queue.skip()
    assert [p.name for p in queue.skipped_images()] == [second, first]


def test_skipped_previews(session: Session):
    from trimage.session import SKIPPED_ID

    assert session.category_previews(SKIPPED_ID) == []
    session.skip()
    session.skip()
    previews = session.category_previews(SKIPPED_ID)
    assert [p.name for p in previews] == ["cat2.png", "cat.png"]
    assert len(session.category_previews(SKIPPED_ID, 1)) == 1


def test_api_skipped_previews(client):
    from trimage.session import SKIPPED_ID

    client.post("/api/skip")
    data = client.get(f"/api/categories/{SKIPPED_ID}/previews").json()["previews"]
    assert [p["name"] for p in data] == ["cat.png"]
    assert client.get(f"/api/categories/{SKIPPED_ID}/preview/0").status_code == 200


def test_api_skip_a_named_image(client):
    state = client.post("/api/skip?index=2").json()
    assert state["skipped"] == 1
    assert state["index"] == 0                  # the queue did not move
    assert state["current"]["name"] == "cat.png"


def test_done_only_when_nothing_is_pending(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.skip()
    queue.sort_current("id", "Keep", tmp_path / "keep")
    queue.sort_current("id", "Keep", tmp_path / "keep")
    assert queue.done is False          # one image is still sitting in Skipped
    queue.review_skipped()
    queue.sort_current("id", "Keep", tmp_path / "keep")
    assert queue.done is True


def test_sidecars_can_be_left_behind(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.sort_current("id", "Keep", tmp_path / "keep", move_sidecars=False)
    assert (library / "cat.txt").exists()


def test_selecting_ahead_does_not_move_the_queue(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    assert queue.select(2) is True
    assert queue.index == 0          # the queue stays where it was
    assert queue.target == 2
    assert queue.current.name == "dog.jpg"

    queue.sort_current("id", "Keep", tmp_path / "keep")
    assert (tmp_path / "keep" / "dog.jpg").exists()
    assert queue.index == 0          # still on the first image
    assert queue.selection is None   # the look-ahead is done with
    assert queue.current.name == "cat.png"


def test_selecting_the_current_image_clears_the_selection(library: Path):
    queue = SortQueue()
    queue.load(library)
    queue.select(2)
    queue.select(0)
    assert queue.selection is None


def test_undo_of_a_look_ahead_leaves_the_queue_alone(library: Path, tmp_path: Path):
    queue = SortQueue()
    queue.load(library)
    queue.select(2)
    queue.sort_current("id", "Keep", tmp_path / "keep")
    queue.undo()
    assert queue.index == 0
    assert queue.selection == 2
    assert (library / "nested" / "dog.jpg").exists()


def test_clear_category_puts_moved_files_back(session: Session, tmp_path: Path):
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.sort_current(category.id)
    assert (tmp_path / "keep" / "cat.png").exists()

    moved, cancelled, extra = session.clear_category(category.id)
    assert (moved, cancelled, extra) == (2, 0, 0)
    assert (Path(session.project.source_folder) / "cat.png").exists()
    assert (Path(session.project.source_folder) / "cat.txt").exists()
    state = session.state()
    assert state["pending"] == 3
    assert state["categories"][0]["count"] == 0


def test_clear_category_cancels_waiting_decisions(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)

    moved, cancelled, extra = session.clear_category(category.id)
    assert (moved, cancelled, extra) == (0, 1, 0)
    assert session.state()["staged"] == 0
    assert session.state()["pending"] == 3


def test_clear_also_recovers_files_it_did_not_put_there(session: Session, tmp_path: Path):
    """Clearing empties the folder, whatever put the images there."""
    destination = tmp_path / "keep"
    make_image(destination / "stranger.png")
    (destination / "stranger.txt").write_text("caption", encoding="utf-8")
    category = session.add_category("Keep", str(destination))
    session.sort_current(category.id)

    put_back, cancelled, extra = session.clear_category(category.id)
    assert (put_back, cancelled, extra) == (1, 0, 1)
    source = Path(session.project.source_folder)
    assert (source / "stranger.png").exists()
    assert (source / "stranger.txt").exists()
    assert list(destination.glob("*.png")) == []

    state = session.state()
    assert state["categories"][0]["count"] == 0
    assert state["total"] == 4              # the stranger joined the queue
    assert state["pending"] == 4


def test_clear_only_touches_its_own_category(session: Session, tmp_path: Path):
    keep = session.add_category("Keep", str(tmp_path / "keep"))
    bin_ = session.add_category("Bin", str(tmp_path / "bin"))
    session.sort_current(keep.id)
    session.sort_current(bin_.id)

    session.clear_category(keep.id)
    assert not (tmp_path / "keep" / "cat.png").exists()
    assert (tmp_path / "bin" / "cat2.png").exists()


# -- config ---------------------------------------------------------------
def test_config_round_trip(tmp_path: Path):
    target = tmp_path / "config.json"
    original = AppConfig(output_root=str(tmp_path), sort_order="newest",
                         filmstrip_size=999, image_fit="nonsense")
    original.normalise().save(target)

    loaded = AppConfig.load(target)
    assert loaded.output_root == str(tmp_path)
    assert loaded.sort_order == "newest"
    assert loaded.filmstrip_size == 500        # clamped
    assert loaded.image_fit == "contain"       # rejected value falls back


def test_corrupt_config_does_not_explode(tmp_path: Path):
    target = tmp_path / "config.json"
    target.write_text("{not json", encoding="utf-8")
    assert AppConfig.load(target).recursive is True


def test_settings_are_written_to_the_config_file(session: Session, tmp_path: Path):
    session.update_settings({"file_action": "copy", "sort_order": "newest"})
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["file_action"] == "copy"
    assert stored["sort_order"] == "newest"


def test_legacy_copy_flag_is_understood(tmp_path: Path):
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"copy_instead_of_move": True}), encoding="utf-8")
    config = AppConfig.load(target)
    assert config.file_action == "copy"
    assert config.copying is True


def test_bad_action_values_fall_back(tmp_path: Path):
    config = AppConfig(file_action="teleport", apply_mode="whenever").normalise()
    assert config.file_action == "move"
    assert config.apply_mode == "deferred"


def test_manual_apply_is_default(session: Session, tmp_path: Path):
    session.config = AppConfig.from_dict({})
    session.config._file = tmp_path / "manual-config.json"
    category = session.add_category("Keep", str(tmp_path / "keep"))
    original = session.queue.current
    session.sort_current(category.id)
    assert original.exists()
    assert not (tmp_path / "keep").exists()
    category_state = session.category_state(category)
    assert category_state["staged_here"] == 1
    assert category_state["clearable_on_disk"] == 0
    assert session.clear_category(category.id) == (0, 1, 0)
    assert original.exists()
    assert session.queue.current == original


@pytest.mark.parametrize("action", ["move", "copy"])
def test_clear_output_restores_applied_and_pending_images(session, library, tmp_path, action):
    session.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg"),
                        str(library / "cat2.png")])
    session.config.file_action = action
    first = session.add_category("Keep", str(tmp_path / "keep"))
    second = session.add_category("Maybe", str(tmp_path / "maybe"))
    session.sort_current(first.id)
    session.sort_current(second.id)
    session.config.apply_mode = "deferred"
    session.sort_current(second.id)
    session.clear_output()
    assert (library / "cat.png").exists()
    assert (library / "cat.txt").exists()
    assert (library / "nested" / "dog.jpg").exists()
    assert (library / "cat2.png").exists()
    assert not list((tmp_path / "keep").iterdir())
    assert not list((tmp_path / "maybe").iterdir())
    assert session.state()["pending"] == 3
    assert session.state()["staged"] == 0
    assert len(session.project.categories) == 2


def test_api_clear_output_cancels_pending_placements(client, tmp_path):
    client.post("/api/settings", json={"apply_mode": "deferred"})
    state = client.post("/api/categories", json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category = state["categories"][0]
    client.post(f"/api/sort/{category['id']}")
    response = client.post("/api/output/clear")
    assert response.status_code == 200
    assert response.json()["staged"] == 0
    assert response.json()["pending"] == 3
    assert not (tmp_path / "keep").exists()


def test_explicit_immediate_apply_is_preserved():
    assert AppConfig.from_dict({"apply_mode": "immediate"}).apply_mode == "immediate"


# -- categories and relative folders --------------------------------------
def test_relative_folder_resolves_against_output_root(tmp_path: Path):
    category = Category("Keep", "keep")
    assert category.resolve("") is None
    assert category.resolve(str(tmp_path)) == tmp_path / "keep"


def test_absolute_folder_ignores_output_root(tmp_path: Path):
    category = Category("Keep", str(tmp_path / "elsewhere"))
    assert category.resolve("/somewhere") == tmp_path / "elsewhere"


def test_relative_category_needs_a_root(session: Session):
    session.add_category("Keep", "keep")
    with pytest.raises(ValueError, match="output root"):
        session.sort_current(session.project.categories[0].id)


def test_relative_category_sorts_into_the_root(session: Session, tmp_path: Path):
    session.update_settings({"output_root": str(tmp_path / "out")})
    category = session.add_category("Keep", "keep")
    session.sort_current(category.id)
    assert (tmp_path / "out" / "keep" / "cat.png").exists()


def test_suggest_hotkeys_avoids_collisions():
    assert suggest_hotkeys(["keep", "kill"], set()) == ["K", "I"]
    assert suggest_hotkeys(["keep"], {"K"}) == ["E"]


def test_bulk_add(session: Session, tmp_path: Path):
    session.update_settings({"output_root": str(tmp_path / "out")})
    session.add_categories_bulk(["keep", "maybe", "discard"])
    assert [c.name for c in session.project.categories] == ["keep", "maybe", "discard"]
    assert [c.folder for c in session.project.categories] == ["keep", "maybe", "discard"]
    assert len({c.hotkey for c in session.project.categories}) == 3


def test_replace_categories_rejects_duplicate_hotkeys(session: Session):
    with pytest.raises(ValueError, match="used by both"):
        session.replace_categories([
            {"name": "A", "folder": "a", "hotkey": "K"},
            {"name": "B", "folder": "b", "hotkey": "k"},
        ])


def test_create_category_folders(session: Session, tmp_path: Path):
    session.update_settings({"output_root": str(tmp_path / "out")})
    session.add_categories_bulk(["keep", "discard"])
    assert session.create_category_folders() == 2
    assert (tmp_path / "out" / "keep").is_dir()


# -- autosave and carrying on ---------------------------------------------
def test_categories_are_saved_as_you_go(session: Session, tmp_path: Path):
    session.add_category("Keep", "keep", "K")
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    saved = stored["last_session"]
    assert [c["name"] for c in saved["categories"]] == ["Keep"]
    assert saved["categories"][0]["hotkey"] == "K"
    assert saved["source_folder"] == session.project.source_folder
    assert saved["saved_at"]


def test_autosave_can_be_turned_off(session: Session, tmp_path: Path):
    session.update_settings({"autosave": False})
    session.add_category("Keep", "keep", "K")
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["last_session"] == {}


def test_a_dropped_set_is_remembered_and_offered_back(library: Path, tmp_path: Path,
                                                      config: AppConfig):
    chosen = [str(library / "cat.png"), str(library / "nested" / "dog.jpg")]
    first = Session(config)
    first.set_images(chosen)
    first.add_category("Keep", str(tmp_path / "keep"), "K")

    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["last_session"]
    assert sorted(saved["images"]) == sorted(chosen)
    assert saved["source_folder"] == ""          # they span two folders

    second = Session(AppConfig.load(tmp_path / "config.json"))
    assert second.state()["resume"]["images"] == 2
    second.resume()
    assert second.state()["total"] == 2
    assert second.state()["project"]["folders"] == 2
    assert [c.name for c in second.project.categories] == DEFAULT_NAMES + ["Keep"]


def test_resuming_a_dropped_set_that_is_gone(library: Path, tmp_path: Path,
                                             config: AppConfig):
    first = Session(config)
    first.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg")])
    (library / "cat.png").unlink()
    (library / "nested" / "dog.jpg").unlink()

    second = Session(AppConfig.load(tmp_path / "config.json"))
    second.resume()
    assert second.state()["total"] == 0
    assert any("no longer where they were" in w for w in second.state()["warnings"])


def test_resuming_a_partly_gone_dropped_set(library: Path, tmp_path: Path,
                                            config: AppConfig):
    first = Session(config)
    first.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg")])
    (library / "nested" / "dog.jpg").unlink()

    second = Session(AppConfig.load(tmp_path / "config.json"))
    second.resume()
    assert second.state()["total"] == 1
    assert any("1 of last time's images are gone" in w for w in second.state()["warnings"])


def test_a_single_folder_drop_resumes_as_that_folder(library: Path, tmp_path: Path,
                                                     config: AppConfig):
    """One folder behaves like opening it, so a moved file is no great loss."""
    first = Session(config)
    first.set_images([str(library / "cat.png")])
    (library / "cat.png").unlink()

    second = Session(AppConfig.load(tmp_path / "config.json"))
    second.resume()
    assert second.state()["total"] == 2          # the rest of the folder


def test_a_fresh_session_is_offered_last_time(library: Path, tmp_path: Path,
                                              config: AppConfig):
    first = Session(config)
    first.set_folder(str(library))
    first.add_category("Keep", str(tmp_path / "keep"), "K")

    second = Session(AppConfig.load(tmp_path / "config.json"))
    offer = second.state()["resume"]
    assert offer["available"] is True
    assert offer["categories"] == len(DEFAULT_NAMES) + 1
    assert offer["source_folder"] == str(library)

    second.resume()
    assert [c.name for c in second.project.categories] == DEFAULT_NAMES + ["Keep"]
    assert second.project.categories[-1].hotkey == "K"
    assert second.state()["total"] == 3
    assert second.state()["resume"]["available"] is False


def test_the_offer_is_hidden_once_you_start_working(library: Path, tmp_path: Path,
                                                    config: AppConfig):
    Session(config).add_category("Keep", "keep", "K")

    second = Session(AppConfig.load(tmp_path / "config.json"))
    assert second.state()["resume"]["available"] is True
    second.set_folder(str(library))
    assert second.state()["resume"]["available"] is False


def test_dismissing_the_offer(library: Path, tmp_path: Path, config: AppConfig):
    Session(config).add_category("Keep", "keep", "K")
    second = Session(AppConfig.load(tmp_path / "config.json"))
    second.dismiss_resume()
    assert second.state()["resume"]["available"] is False
    assert [c.name for c in second.project.categories] == DEFAULT_NAMES


def test_resuming_a_folder_that_is_gone(tmp_path: Path, config: AppConfig):
    config.last_session = {
        "source_folder": str(tmp_path / "vanished"),
        "categories": [{"name": "Keep", "folder": "keep"}],
        "saved_at": "whenever",
    }
    session = Session(config)
    session.resume()
    assert [c.name for c in session.project.categories] == ["Keep"]
    assert session.state()["total"] == 0
    assert any("gone" in w for w in session.state()["warnings"])


def test_nothing_to_resume(config: AppConfig):
    session = Session(config)
    assert session.state()["resume"]["available"] is False
    with pytest.raises(ValueError):
        session.resume()


def test_api_resume(client, library: Path, tmp_path: Path, config: AppConfig):
    client.post("/api/categories", json={"name": "Keep", "folder": str(tmp_path / "keep")})

    from trimage import server
    server.session = Session(AppConfig.load(tmp_path / "config.json"))

    state = client.get("/api/state").json()
    assert state["resume"]["available"] is True
    assert state["resume"]["categories"] == 1

    state = client.post("/api/resume").json()
    assert [c["name"] for c in state["categories"]] == ["Keep"]
    assert state["resume"]["available"] is False

    server.session = Session(AppConfig.load(tmp_path / "config.json"))
    state = client.post("/api/resume/dismiss").json()
    assert state["resume"]["available"] is False
    assert [c["name"] for c in state["categories"]] == DEFAULT_NAMES


# -- presets --------------------------------------------------------------
def test_presets_save_load_delete(session: Session, tmp_path: Path):
    session.add_category("Keep", "keep", "K")
    session.add_category("Bin", "bin", "B")
    session.save_preset("my set")

    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in stored["presets"]["my set"]] == ["Keep", "Bin"]

    session.project.categories = []
    session.load_preset("my set")
    assert [c.name for c in session.project.categories] == ["Keep", "Bin"]

    session.load_preset("my set", replace=False)
    assert len(session.project.categories) == 4

    session.delete_preset("my set")
    assert session.config.presets == {}
    with pytest.raises(KeyError):
        session.load_preset("my set")


def test_empty_preset_is_rejected(session: Session):
    with pytest.raises(ValueError):
        session.save_preset("nothing")


# -- session --------------------------------------------------------------
def test_session_round_trip(session: Session, tmp_path: Path):
    category = session.add_category("Keep", str(tmp_path / "keep"), "K")

    state = session.state()
    assert state["total"] == 3
    assert state["current"]["name"] == "cat.png"
    assert sorted(state["current"]["sidecars"]) == ["caption", "txt"]

    session.sort_current(category.id)
    state = session.state()
    assert state["sorted"] == 1
    assert state["can_undo"] is True
    assert state["categories"][0]["count"] == 1
    assert state["categories"][0]["sorted_here"] == 1

    session.undo()
    assert session.state()["sorted"] == 0
    assert (session.project.source_folder and Path(session.project.source_folder) / "cat.png").exists()


def test_skipped_count_in_state(session: Session):
    session.skip()
    state = session.state()
    assert state["skipped"] == 1
    assert state["pending"] == 2
    session.review_skipped()
    assert session.state()["skipped"] == 0


def test_project_save_and_load(session: Session, tmp_path: Path, config: AppConfig):
    session.add_category("Keep", str(tmp_path / "keep"), "K")
    saved = session.save_project_file(str(tmp_path / "proj.json"))

    fresh = Session(config)
    fresh.load_project_file(str(saved))
    assert fresh.project.source_folder == session.project.source_folder
    assert fresh.project.categories[0].hotkey == "K"
    assert fresh.state()["total"] == 3


def test_legacy_project_format(tmp_path: Path, library: Path, config: AppConfig):
    legacy = tmp_path / "old.json"
    legacy.write_text(json.dumps({
        "chosen_folder": str(library),
        "categories": [{"name": "A", "path": str(tmp_path / "a"), "hotkey": "a"}],
    }), encoding="utf-8")

    session = Session(config)
    session.load_project_file(str(legacy))
    assert session.project.categories[0].name == "A"
    assert session.project.categories[0].folder == str(tmp_path / "a")
    assert session.state()["total"] == 3


# -- API ------------------------------------------------------------------
@pytest.fixture
def client(library: Path, config: AppConfig):
    from fastapi.testclient import TestClient

    from trimage import server

    server.session = Session(config)
    server.session.project.categories = []
    with TestClient(server.create_app()) as test_client:
        test_client.post("/api/folder", json={"path": str(library)})
        yield test_client


def test_api_flow(client, tmp_path: Path):
    state = client.get("/api/state").json()
    assert state["total"] == 3

    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep"),
                              "hotkey": "K"}).json()
    category_id = state["categories"][0]["id"]

    assert client.get(f"/api/image/{state['index']}").status_code == 200
    assert client.get(f"/api/thumb/{state['index']}").headers["content-type"] == "image/jpeg"

    state = client.post(f"/api/sort/{category_id}").json()
    assert state["sorted"] == 1
    assert state["categories"][0]["count"] == 1
    assert (tmp_path / "keep" / "cat.png").exists()

    assert client.get(f"/api/categories/{category_id}/thumb").status_code == 200

    state = client.post("/api/undo").json()
    assert state["sorted"] == 0
    assert state["can_undo"] is False


def test_api_skip_and_review(client):
    state = client.post("/api/skip").json()
    assert state["skipped"] == 1
    state = client.post("/api/skipped/review").json()
    assert state["skipped"] == 0
    assert state["index"] == 0


def test_api_category_table(client, tmp_path: Path):
    state = client.put("/api/categories", json={"categories": [
        {"name": "Keep", "folder": "keep", "hotkey": "K", "color": "#ffffff"},
        {"name": "Bin", "folder": "bin", "hotkey": "B", "color": "#000000"},
    ]}).json()
    assert [c["name"] for c in state["categories"]] == ["Keep", "Bin"]
    assert state["categories"][0]["relative"] is True
    assert state["categories"][0]["problem"]       # no output root yet

    state = client.post("/api/settings", json={"output_root": str(tmp_path / "out")}).json()
    assert state["categories"][0]["problem"] == ""
    assert state["categories"][0]["resolved"] == str(tmp_path / "out" / "keep")


def test_api_bulk_and_presets(client, tmp_path: Path):
    client.post("/api/settings", json={"output_root": str(tmp_path / "out")})
    state = client.post("/api/categories/bulk", json={"names": ["keep", "bin"]}).json()
    assert len(state["categories"]) == 2

    state = client.post("/api/presets/save", json={"name": "set one"}).json()
    assert state["presets"] == ["set one"]

    client.delete(f"/api/categories/{state['categories'][0]['id']}")
    state = client.post("/api/presets/load", json={"name": "set one"}).json()
    assert len(state["categories"]) == 2

    state = client.post("/api/presets/delete", json={"name": "set one"}).json()
    assert state["presets"] == []
    assert client.post("/api/presets/load", json={"name": "set one"}).status_code == 404


def test_api_settings_persist(client, tmp_path: Path):
    state = client.post("/api/settings", json={"file_action": "copy"}).json()
    assert state["config"]["file_action"] == "copy"
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["file_action"] == "copy"


# -- deferred apply -------------------------------------------------------
def test_deferred_sorting_touches_nothing_until_applied(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))

    session.sort_current(category.id)
    session.sort_current(category.id)

    state = session.state()
    assert state["staged"] == 2
    assert state["sorted"] == 2
    assert state["categories"][0]["staged_here"] == 2
    assert state["categories"][0]["in_folder"] == 0     # nothing on disk yet
    assert state["categories"][0]["count"] == 2         # but two are spoken for
    assert not (tmp_path / "keep").exists()
    assert (Path(session.project.source_folder) / "cat.png").exists()

    done, problems = session.apply_staged()
    assert (done, problems) == (2, [])
    assert (tmp_path / "keep" / "cat.png").exists()
    assert (tmp_path / "keep" / "cat.txt").exists()      # sidecars come too
    assert session.state()["staged"] == 0
    assert session.state()["categories"][0]["in_folder"] == 2
    assert session.state()["categories"][0]["count"] == 2


def test_deferred_copy_leaves_the_originals(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred", "file_action": "copy"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.apply_staged()
    assert (tmp_path / "keep" / "cat.png").exists()
    assert (Path(session.project.source_folder) / "cat.png").exists()


def test_discarding_staged_requeues_the_images(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.sort_current(category.id)

    assert session.discard_staged() == 2
    state = session.state()
    assert state["staged"] == 0
    assert state["sorted"] == 0
    assert state["pending"] == 3
    assert not (tmp_path / "keep").exists()


def test_undo_of_a_staged_decision_moves_no_files(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.undo()
    assert session.state()["staged"] == 0
    assert session.state()["pending"] == 3
    assert not (tmp_path / "keep").exists()


def test_undo_after_apply_still_reverses_the_move(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.apply_staged()
    assert (tmp_path / "keep" / "cat.png").exists()

    session.undo()
    assert not (tmp_path / "keep" / "cat.png").exists()
    assert (Path(session.project.source_folder) / "cat.png").exists()


def test_apply_reports_a_broken_category(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.project.categories.clear()          # the category disappears
    done, problems = session.apply_staged()
    assert done == 0
    assert problems and "gone" in problems[0]


def test_category_previews_show_waiting_then_folder(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.sort_current(category.id)

    previews = session.category_previews(category.id)
    assert [p.name for p in previews] == ["cat2.png", "cat.png"]   # newest decision first

    session.apply_staged()
    previews = session.category_previews(category.id)
    assert {p.name for p in previews} == {"cat.png", "cat2.png"}
    assert all(p.parent == tmp_path / "keep" for p in previews)


def test_api_select_and_drop_sort(client, tmp_path: Path):
    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category_id = state["categories"][0]["id"]

    state = client.post("/api/select/2").json()
    assert state["index"] == 0 and state["selection"] == 2 and state["target"] == 2
    assert state["current"]["name"] == "dog.jpg"

    # dropping image 1 on a card sorts that one, not the selected or current one
    state = client.post(f"/api/sort/{category_id}?index=1").json()
    assert (tmp_path / "keep" / "cat2.png").exists()
    assert state["index"] == 0
    assert state["current"]["name"] == "cat.png"

    assert client.post("/api/select/99").status_code == 404


def test_api_clear_category(client, tmp_path: Path):
    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category_id = state["categories"][0]["id"]
    client.post(f"/api/sort/{category_id}")
    assert (tmp_path / "keep" / "cat.png").exists()

    state = client.post(f"/api/categories/{category_id}/clear").json()
    assert not (tmp_path / "keep" / "cat.png").exists()
    assert state["pending"] == 3
    assert state["categories"][0]["clearable"] == 0
    assert client.post("/api/categories/nope/clear").status_code == 404


def test_api_resolve_dropped_folder(client, library: Path):
    data = client.post("/api/resolve-folder",
                       json={"name": library.name, "files": ["cat.png"]}).json()
    assert str(library) in data["matches"]

    empty = client.post("/api/resolve-folder",
                        json={"name": "definitely-not-a-real-folder-xyz", "files": []}).json()
    assert empty["matches"] == []


def test_resolve_dropped_files(library: Path):
    from trimage.droppedfolder import resolve_files

    paths, missing = resolve_files(["cat.png", "cat2.png"], [str(library)])
    assert sorted(Path(p).name for p in paths) == ["cat.png", "cat2.png"]
    assert all(Path(p).parent == library for p in paths)
    assert missing == []

    paths, missing = resolve_files(["cat.png", "nope-xyz.png"], [str(library)])
    assert [Path(p).name for p in paths] == ["cat.png"]
    assert missing == ["nope-xyz.png"]


def test_set_images_takes_a_hand_picked_list(session: Session, library: Path):
    chosen = [str(library / "cat.png"), str(library / "cat2.png")]
    assert session.set_images(chosen) == 2

    state = session.state()
    assert state["total"] == 2
    assert state["current"]["name"] == "cat.png"
    assert state["project"]["source_folder"] == str(library)


def test_set_images_from_several_folders_keeps_them_apart(session: Session, library: Path):
    session.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg")])
    state = session.state()
    assert state["total"] == 2
    # No single folder is invented for them.
    assert state["project"]["source_folder"] == ""
    assert state["project"]["folders"] == 2
    assert "2 folder" in state["project"]["source_label"]
    assert any("own folder" in w for w in state["warnings"])


def test_each_image_goes_back_to_its_own_folder(session: Session, library: Path,
                                                tmp_path: Path):
    session.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg")])
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    session.sort_current(category.id)
    assert (tmp_path / "keep" / "cat.png").exists()
    assert (tmp_path / "keep" / "dog.jpg").exists()

    session.clear_category(category.id)
    assert (library / "cat.png").exists()
    assert (library / "nested" / "dog.jpg").exists()      # not flattened
    assert session.state()["pending"] == 2


def test_clear_leaves_strangers_alone_when_there_is_no_one_source(
        session: Session, library: Path, tmp_path: Path):
    destination = tmp_path / "keep"
    make_image(destination / "stranger.png")
    session.set_images([str(library / "cat.png"), str(library / "nested" / "dog.jpg")])
    category = session.add_category("Keep", str(destination))
    session.sort_current(category.id)

    put_back, cancelled, extra = session.clear_category(category.id)
    assert (put_back, cancelled, extra) == (1, 0, 0)
    assert (destination / "stranger.png").exists()        # nowhere sensible to put it
    assert any("left alone" in w for w in session.state()["warnings"])


def test_a_dropped_set_survives_a_settings_change(session: Session, library: Path):
    session.set_images([str(library / "cat.png"), str(library / "cat2.png")])
    session.update_settings({"sort_order": "newest"})
    assert session.state()["total"] == 2          # not rescanned into a folder listing


def test_single_folder_drop_behaves_like_opening_that_folder(session: Session,
                                                             library: Path):
    session.set_images([str(library / "cat.png"), str(library / "cat2.png")])
    state = session.state()
    assert state["project"]["source_folder"] == str(library)
    assert state["project"]["folders"] == 1


def test_set_images_rejects_ghosts(session: Session, tmp_path: Path):
    with pytest.raises(ValueError):
        session.set_images([str(tmp_path / "not-here.png")])


def test_dropped_images_can_then_be_sorted(session: Session, library: Path, tmp_path: Path):
    session.set_images([str(library / "cat.png")])
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    assert (tmp_path / "keep" / "cat.png").exists()
    assert (tmp_path / "keep" / "cat.txt").exists()


def test_adding_images_keeps_what_is_there(session: Session, library: Path,
                                           tmp_path: Path):
    extra = tmp_path / "extra"
    make_image(extra / "new1.png")
    make_image(extra / "new2.png")

    assert session.state()["total"] == 3          # the folder scan
    added = session.add_images([str(extra / "new1.png"), str(extra / "new2.png")])
    assert added == 2

    state = session.state()
    assert state["total"] == 5
    assert state["pending"] == 5
    assert [i["name"] for i in state["upcoming"]][:1] == ["cat.png"]   # cursor unmoved
    assert "new1.png" in [p.name for p in session.queue.images]


def test_adding_images_does_not_disturb_progress(session: Session, library: Path,
                                                 tmp_path: Path):
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)
    current = session.state()["current"]["name"]

    make_image(tmp_path / "extra" / "new1.png")
    session.add_images([str(tmp_path / "extra" / "new1.png")])

    state = session.state()
    assert state["sorted"] == 1
    assert state["current"]["name"] == current    # still on the same image
    assert state["total"] == 4


def test_adding_the_same_image_twice_does_nothing(session: Session, library: Path):
    assert session.add_images([str(library / "cat.png")]) == 0
    assert session.state()["total"] == 3


def test_adding_after_finishing_moves_on_to_the_new_ones(session: Session,
                                                         library: Path, tmp_path: Path):
    category = session.add_category("Keep", str(tmp_path / "keep"))
    for _ in range(3):
        session.sort_current(category.id)
    assert session.state()["done"] is True

    make_image(tmp_path / "extra" / "new1.png")
    session.add_images([str(tmp_path / "extra" / "new1.png")])
    state = session.state()
    assert state["done"] is False
    assert state["current"]["name"] == "new1.png"


def test_adding_a_folder(session: Session, tmp_path: Path):
    extra = tmp_path / "extra"
    make_image(extra / "new1.png")
    make_image(extra / "new2.png")
    assert session.add_folder(str(extra)) == 2
    assert session.state()["total"] == 5


def test_adding_a_folder_with_no_images(session: Session, tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        session.add_folder(str(empty))


def test_added_images_survive_a_rescan(session: Session, tmp_path: Path):
    make_image(tmp_path / "extra" / "new1.png")
    session.add_images([str(tmp_path / "extra" / "new1.png")])
    session.reload_images()
    assert session.state()["total"] == 4


def test_clear_input_keeps_the_categories(session: Session, tmp_path: Path):
    category = session.add_category("Keep", str(tmp_path / "keep"), "K")
    session.sort_current(category.id)

    assert session.clear_input() == 3
    state = session.state()
    assert state["total"] == 0
    assert state["project"]["source_folder"] == ""
    assert [c["name"] for c in state["categories"]] == ["Keep"]
    assert state["categories"][0]["hotkey"] == "K"
    assert (tmp_path / "keep" / "cat.png").exists()     # already-moved files stay put


def test_clear_input_drops_waiting_decisions(session: Session, tmp_path: Path):
    session.update_settings({"apply_mode": "deferred"})
    category = session.add_category("Keep", str(tmp_path / "keep"))
    session.sort_current(category.id)

    session.clear_input()
    assert session.state()["staged"] == 0
    assert not (tmp_path / "keep").exists()             # nothing was written


def test_clear_input_then_load_again(session: Session, library: Path):
    session.clear_input()
    session.set_folder(str(library))
    assert session.state()["total"] == 3


def test_a_new_session_starts_with_keep_maybe_discard(config: AppConfig):
    fresh = Session(config)
    assert [(c.name, c.folder, c.hotkey) for c in fresh.project.categories] == [
        ("Keep", "Keep", "A"), ("Maybe", "Maybe", "S"), ("Discard", "Discard", "D")
    ]
    assert len({c.color for c in fresh.project.categories}) == 3
    assert fresh.state()["resume"]["available"] is False    # defaults are not "setup"


def test_the_default_categories_sort_like_any_other(config: AppConfig, library: Path,
                                                    tmp_path: Path):
    fresh = Session(config)
    fresh.config.output_root = str(tmp_path / "out")
    fresh.set_folder(str(library))
    keep = fresh.project.categories[0]

    fresh.sort_current(keep.id)
    assert (tmp_path / "out" / "Keep" / "cat.png").exists()


def test_clear_input_forgets_the_saved_session(session: Session, library: Path):
    """The cleared images must not come back as the next run's resume offer."""
    assert session.config.last_session

    session.clear_input()

    assert session.config.last_session == {}
    assert not session.resume_offer()["available"]


def test_new_input_gets_a_new_revision(session: Session, library: Path, tmp_path: Path):
    """Counts repeat, so the cards key their cached thumbnails on this instead."""
    session.skip()
    first = session.state()
    session.clear_input()

    other = tmp_path / "other"
    make_image(other / "one.png")
    make_image(other / "two.png")
    make_image(other / "three.png")
    session.set_folder(str(other))
    session.skip()
    second = session.state()

    assert second["skipped"] == first["skipped"]        # the same numbers...
    assert second["total"] == first["total"]
    assert second["revision"] != first["revision"]      # ...but a different input


def test_api_add_images_and_clear_input(client, library: Path, tmp_path: Path):
    extra = tmp_path / "extra"
    make_image(extra / "new1.png")

    state = client.post("/api/images",
                        json={"paths": [str(extra / "new1.png")], "add": True}).json()
    assert state["total"] == 4

    state = client.post("/api/folder/add", json={"path": str(extra)}).json()
    assert state["total"] == 4                          # already there, nothing added

    state = client.post("/api/input/clear").json()
    assert state["total"] == 0
    assert state["project"]["source_folder"] == ""


def test_api_dropped_images(client, library: Path):
    found = client.post("/api/resolve-files",
                        json={"names": ["cat.png", "cat2.png"]}).json()
    assert len(found["paths"]) == 2

    state = client.post("/api/images", json={"paths": found["paths"]}).json()
    assert state["total"] == 2
    assert client.post("/api/images", json={"paths": []}).status_code == 400


def test_api_pick_folder_reports_support(client):
    data = client.post("/api/pick-folder", json={}).json()
    assert "supported" in data and "path" in data


def test_api_previews(client, tmp_path: Path):
    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category_id = state["categories"][0]["id"]
    assert client.get(f"/api/categories/{category_id}/previews").json()["previews"] == []

    client.post(f"/api/sort/{category_id}")
    data = client.get(f"/api/categories/{category_id}/previews").json()["previews"]
    assert [p["name"] for p in data] == ["cat.png"]
    assert data[0]["waiting"] is False
    assert client.get(f"/api/categories/{category_id}/preview/0").status_code == 200
    assert client.get(f"/api/categories/{category_id}/preview/5").status_code == 404


def test_api_previews_include_waiting(client, tmp_path: Path):
    client.post("/api/settings", json={"apply_mode": "deferred"})
    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category_id = state["categories"][0]["id"]
    client.post(f"/api/sort/{category_id}")

    data = client.get(f"/api/categories/{category_id}/previews").json()["previews"]
    assert [p["name"] for p in data] == ["cat.png"]
    assert data[0]["waiting"] is True
    assert client.get(f"/api/categories/{category_id}/preview/0").status_code == 200


def test_api_apply_and_discard(client, tmp_path: Path):
    client.post("/api/settings", json={"apply_mode": "deferred"})
    state = client.post("/api/categories",
                        json={"name": "Keep", "folder": str(tmp_path / "keep")}).json()
    category_id = state["categories"][0]["id"]

    state = client.post(f"/api/sort/{category_id}").json()
    assert state["staged"] == 1
    assert not (tmp_path / "keep").exists()

    state = client.post("/api/apply").json()
    assert state["staged"] == 0
    assert (tmp_path / "keep" / "cat.png").exists()

    client.post(f"/api/sort/{category_id}")
    state = client.post("/api/staged/discard").json()
    assert state["staged"] == 0
    assert state["pending"] == 2


def test_api_rejects_bad_folder(client):
    response = client.post("/api/folder", json={"path": "Z:/definitely/not/here"})
    assert response.status_code == 400
    assert response.json()["error"]


def test_api_browse(client, tmp_path: Path):
    data = client.get("/api/browse", params={"path": str(tmp_path)}).json()
    assert data["path"] == str(tmp_path.resolve())
    assert any(folder["name"] == "source" for folder in data["folders"])


def test_api_env_exposes_choices(client):
    data = client.get("/api/env").json()
    assert "random" in data["sort_orders"]
    assert "contain" in data["image_fits"]
    assert "square" in data["thumb_ratios"]
    assert data["card_layouts"] == ["grid", "rows", "columns"]
    assert "native_dialogs" in data
    assert data["config_file"]
