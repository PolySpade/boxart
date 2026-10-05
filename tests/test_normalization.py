from pathlib import Path

import pytest

from boxart import normalization
from boxart.artwork import ArtworkService
from boxart.errors import ArtError
from boxart.library import Game
from conftest import live


@live
def test_live_psp_index_and_cover():
    service = ArtworkService()
    game = Game(Path("/PSP/Ridge_Racer_2_EUR_PSP-pSyPSP.cso"), None)
    name = service.normalized_name(game)
    assert name == "Ridge Racer 2 (Europe) (En,Fr,De,Es,It)"
    game.lookup_name = name
    assert service.artwork(game) is not None


def test_scene_names_and_regions():
    names = ["Ridge Racer 2 (Europe) (En,Fr,De,Es,It)", "Ridge Racer 2 (Europe, Australia) (En,Fr,De,Es,It)", "Ridge Racer (Europe)"]
    assert normalization.match("Ridge_Racer_2_EUR_PSP-pSyPSP", names) == names[0]
    assert normalization.match("Loco_Roco_USA_PSP-pSyPSP", ["LocoRoco (USA) (En,Ja)"]) == "LocoRoco (USA) (En,Ja)"
    assert normalization.match("BURNOUT DOMINATOR - ULUS10236", ["Burnout Dominator (USA)"]) == "Burnout Dominator (USA)"
    assert normalization.match("BurnOut_USA_MULTi5_PROPER_READNFO_PSP-MUPSP", ["Burnout Legends (USA)", "Burnout Dominator (USA)"]) is None
    assert normalization.match("Game_USA_PSP-team", ["Game (USA) (v1)", "Game (USA) (v2)"]) is None


def test_rename_preserves_contents_and_rejects_collisions_and_references(tmp_path):
    rom = tmp_path / "old.cso"
    data = bytes([1, 2, 3, 4])
    rom.write_bytes(data)
    renamed = normalization.rename(rom, "Game (USA)")
    assert renamed.name == "Game (USA).cso"
    assert renamed.read_bytes() == data
    assert not rom.exists()
    assert (tmp_path / ".boxart-renames.jsonl").exists()
    rom.write_bytes(data)
    with pytest.raises(ArtError):
        normalization.rename(rom, "Game (USA)")
    with pytest.raises(ArtError):
        normalization.rename(rom, "game (usa)")
    with pytest.raises(ArtError):
        normalization.rename(rom, "../unsafe")
    (tmp_path / "games.m3u").write_bytes(b"")
    with pytest.raises(ArtError):
        normalization.rename(rom, "Other")
    assert rom.read_bytes() == data
