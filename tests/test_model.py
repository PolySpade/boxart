from pathlib import Path

import pytest

from boxart.library import Game
from boxart.model import LibraryModel
from conftest import MemoryStore, live, make_rom, png


@pytest.fixture
def model():
    m = LibraryModel(store=MemoryStore())
    m.games = [Game(Path(f"/tmp/Game {i}.nds"), None) for i in range(6)]
    return m


def test_shift_range_and_command_toggle(model):
    ids = [g.id for g in model.games]
    model.select(ids[1]); model.select(ids[4], shift=True)
    assert model.selected_ids == set(ids[1:5])
    model.select(ids[2], shift=True)
    assert model.selected_ids == set(ids[1:3])
    model.select(ids[5], command=True); model.select(ids[1], command=True)
    assert model.selected_ids == {ids[2], ids[5]}
    model.select(ids[3]); model.select(ids[0], shift=True)
    assert model.selected_ids == set(ids[0:4])


def test_hidden_selections_pruned(model):
    ids = [g.id for g in model.games]
    model.select(ids[0]); model.select(ids[5], shift=True)
    model.query = "Game 2"; model.prune_selection()
    assert model.selected_ids == {ids[2]}
    model.query = "Game 4"; model.prune_selection()
    assert model.selected_ids == set()
    model.select(ids[4], shift=True)
    assert model.selected_ids == {ids[4]}


def test_selected_export_uses_snapshot_and_excludes_other_ready_covers(tmp_path):
    m = LibraryModel(store=MemoryStore())
    for i in range(3):
        game = Game(make_rom(tmp_path, f"Game {i}.nds"), None)
        game.artwork, game.status = png(16, 16), "Ready"
        m.games.append(game)
    m.select(m.games[0].id); m.select(m.games[1].id, shift=True); m.get_for_selected()
    m.select(m.games[2].id)
    assert m.wait(5)
    assert m.saved == 2
    assert m.games[2].status == "Ready"
    assert not (tmp_path / "Imgs/Game 2.png").exists()


def test_collisions_block_the_whole_batch(tmp_path):
    from boxart.library import Profile
    m = LibraryModel(store=MemoryStore())
    m.profile, m.destination = Profile.CUSTOM, tmp_path / "out"
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        game = Game(make_rom(tmp_path / folder, "Game.nds"), None)
        game.artwork, game.status = png(16, 16), "Ready"
        m.games.append(game)
    m.save()
    assert m.error and not m.busy
    assert not (tmp_path / "out").exists()


def test_settings_are_persisted():
    store = MemoryStore()
    m = LibraryModel(store=store)
    m.set_normalize_filenames(True)
    assert LibraryModel(store=store).normalize_filenames


@live
def test_download_and_save_all_end_to_end(tmp_path):
    rom = make_rom(tmp_path, "Oddly named game.nds", code="B6ZE")
    header = rom.read_bytes()
    m = LibraryModel(store=MemoryStore())
    m.games = [Game(rom, "B6ZE")]
    m.download_and_save_all()
    assert m.wait(45)
    assert m.saved == 1
    assert (tmp_path / "Imgs/Oddly named game.png").exists()
    assert rom.read_bytes() == header
