"""Destination setup must be valid before sorting changes any files."""
from pathlib import Path

import pytest
from PIL import Image

from trimage.config import AppConfig
from trimage.session import Session


@pytest.fixture
def session(tmp_path):
    config = AppConfig()
    config._file = tmp_path / "config.json"
    instance = Session(config)
    source = tmp_path / "input"
    source.mkdir()
    Image.new("RGB", (8, 8)).save(source / "image.png")
    instance.set_folder(str(source))
    return instance


def test_missing_output_blocks_sorting_without_moving_images(session):
    original = session.queue.current
    assert not session.state()["setup"]["ready"]
    with pytest.raises(ValueError, match="output root"):
        session.sort_current(session.project.categories[0].id)
    assert original.exists()
    assert session.queue.current == original


def test_output_setup_becomes_ready_and_can_be_invalidated(session, tmp_path):
    session.config.output_root = str(tmp_path / "output")
    assert session.state()["setup"]["ready"]
    assert not (tmp_path / "output").exists()
    session.config.output_root = ""
    assert not session.state()["setup"]["ready"]


def test_file_cannot_be_used_as_output_folder(session, tmp_path):
    target = tmp_path / "output"
    target.write_text("not a directory", encoding="utf-8")
    session.config.output_root = str(target)
    assert not session.state()["setup"]["ready"]
    with pytest.raises(ValueError, match="not writable"):
        session.sort_current(session.project.categories[0].id)


def test_absolute_category_folders_do_not_need_shared_root(session, tmp_path):
    for category in session.project.categories:
        category.folder = str(tmp_path / category.name)
    assert session.state()["setup"]["ready"]
    session.project.categories[-1].folder = ""
    assert not session.state()["setup"]["ready"]


def test_invalid_setup_blocks_deferred_apply(session, tmp_path):
    session.config.output_root = str(tmp_path / "output")
    session.config.apply_mode = "deferred"
    original = session.queue.current
    session.sort_current(session.project.categories[0].id)
    session.config.output_root = ""
    done, errors = session.apply_staged()
    assert done == 0 and errors
    assert original.exists()
    assert len(session.queue.staged_items) == 1
