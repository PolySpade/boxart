from pathlib import Path

import pytest

from boxart.artwork import ArtworkService
from boxart.errors import ArtError
from boxart.library import ExportSettings, Game, Profile
from boxart.systems import GameSystem, match_playlist
from conftest import live


@pytest.mark.parametrize("folder, expected", [
    ("/run/media/me/ExampleCard/Roms/NDS", "/run/media/me/ExampleCard/RetroArch/thumbnails"),
    ("/tmp/ExampleLibrary/Roms", "/tmp/ExampleLibrary/RetroArch/thumbnails"),
    ("/run/media/me/ExampleCard/NDS", "/run/media/me/ExampleCard/RetroArch/thumbnails"),
    ("/media/me/ExampleCard/games/NDS", "/media/me/ExampleCard/RetroArch/thumbnails"),
    ("/mnt/sd/NDS", "/mnt/sd/RetroArch/thumbnails"),
    ("/home/me/games/NDS", "/home/me/games/RetroArch/thumbnails"),
])
def test_suggested_retroarch_directory_follows_rom_root(folder, expected):
    assert ExportSettings.suggested_retroarch_directory(Path(folder)) == Path(expected)


def test_suggested_retroarch_directory_reuses_existing(tmp_path):
    (tmp_path / ".config/retroarch/thumbnails").mkdir(parents=True)
    assert ExportSettings.suggested_retroarch_directory(tmp_path / "Roms/GBA") == tmp_path / ".config/retroarch/thumbnails"


def test_system_detection():
    assert GameSystem.infer("/Roms/GBA/Game.gba") is GameSystem.GBA
    assert GameSystem.infer("/Roms/PS/Game.chd") is GameSystem.PS
    assert GameSystem.infer("/Roms/PSP/Game.iso") is GameSystem.PSP
    assert GameSystem.infer("/Roms/SFC/Game.zip") is GameSystem.SNES
    assert GameSystem.infer("/Roms/Sony - PlayStation/Game.chd") is GameSystem.PS
    assert GameSystem.infer("/Roms/Unknown/Game.chd") is None


def test_playlist_labels_and_device_paths():
    game = Game(Path("/run/media/me/DS/Roms/GBA/Metroid.gba"), None)
    data = '{"items":[{"path":"/mnt/sdcard/Roms/GBA/Metroid.gba","label":"Metroid: Zero Mission (USA)","db_name":"Nintendo - Game Boy Advance.lpl"}]}'
    matches = match_playlist(data, "Favorites.lpl", [game])
    settings = ExportSettings(Profile.RETROARCH, matches, Path("/tmp/thumbnails"))
    assert settings.output(game.path) == Path("/tmp/thumbnails/Nintendo - Game Boy Advance/Named_Boxarts/Metroid_ Zero Mission (USA).png")


def test_windows_paths_and_missing_db_name():
    game = Game(Path("/a/Game.gba"), None)
    data = r'{"items":[{"path":"C:\\Roms\\Game.gba#inner.gba","label":"Game","db_name":""}]}'
    identity = match_playlist(data, "Nintendo - Game Boy Advance.lpl", [game])[game.id]
    assert identity.database == "Nintendo - Game Boy Advance"


def test_ambiguous_playlist_mapping_skipped():
    games = [Game(Path(p), None) for p in ("/a/Game.gba", "/b/Game.gba")]
    data = '{"items":[{"path":"/device/Game.gba","label":"Game","db_name":"Nintendo - Game Boy Advance.lpl"}]}'
    assert match_playlist(data, "GBA.lpl", games) == {}


def test_playlist_cannot_escape_destination():
    game = Game(Path("/a/Game.gba"), None)
    data = '{"items":[{"path":"/device/Game.gba","label":"Game","db_name":"../../escape.lpl"}]}'
    with pytest.raises(ArtError):
        match_playlist(data, "GBA.lpl", [game])


def test_legacy_playlist_rejected():
    with pytest.raises(ArtError):
        match_playlist("/roms/Game.gba\nGame\nDETECT\nDETECT\nDETECT\nGBA.lpl\n", "GBA.lpl", [])


@live
@pytest.mark.parametrize("path", ["/Roms/GBA/Metroid - Zero Mission (USA).gba", "/Roms/PS/Final Fantasy VII (USA) (Disc 1).chd"])
def test_live_gba_and_ps_providers(path):
    assert ArtworkService().artwork(Game(Path(path), None)) is not None
