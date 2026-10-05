import io
from pathlib import Path

from PIL import Image

from boxart.cache import ArtworkLibrary, default_root
from boxart.library import ExportSettings, Game, Profile
from boxart.model import LibraryModel
from conftest import MemoryStore, make_rom, png
from test_parallel import FakeService


class OfflineService:
    """Fails every request, proving a lookup was served from the library."""
    calls = 0

    def normalized_name(self, game, cancel=None):
        return None

    def artwork(self, game, cancel=None):
        OfflineService.calls += 1
        raise OSError("offline")


def jpeg(size=(300, 270)):
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "JPEG")
    return out.getvalue()


def test_match_by_ds_code_across_different_filenames(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    library.put(Game(Path("/card1/Roms/NDS/Mario Kart DS (USA).nds"), "AMCE"), jpeg(), ["Mario Kart DS (USA)"])
    renamed = Game(Path("/card2/nds/mkds_scene_rip.nds"), "AMCE")
    assert library.get(renamed) == jpeg()
    assert (tmp_path / "lib/Nintendo - Nintendo DS/by-code/AMCE.jpg").is_file()


def test_match_by_name_and_keep_original_bytes(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    original = png(1024, 900)
    library.put(Game(Path("/a/GBA/Metroid.gba"), None), original, ["Metroid - Zero Mission (USA)", "Metroid"])
    assert library.get(Game(Path("/b/Roms/GBA/Metroid.gba"), None)) == original
    labelled = Game(Path("/c/GBA/mzm.gba"), None, lookup_name="Metroid - Zero Mission (USA)")
    assert library.get(labelled) == original
    assert library.get(Game(Path("/c/GBA/Other.gba"), None)) is None
    assert library.get(Game(Path("/c/NDS/Metroid.nds"), None)) is None  # Systems never mix.


def test_downloads_never_replace_but_imports_do(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    game = Game(Path("/a/GBA/Game.gba"), None)
    assert library.put(game, png(10, 10), ["Game"])
    assert not library.put(game, png(20, 20), ["Game"])
    assert Image.open(io.BytesIO(library.get(game))).size == (10, 10)
    assert library.put(game, jpeg(), ["Game"], replace=True)
    assert library.get(game) == jpeg()
    assert sorted(p.name for p in (tmp_path / "lib/Nintendo - Game Boy Advance").iterdir()) == ["Game.jpg"]


def test_unsafe_names_stay_inside_the_library(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    library.put(Game(Path("/a/GBA/x.gba"), None), png(4, 4), ["../../escape", "Metroid: Zero/Mission"])
    files = [p.relative_to(tmp_path / "lib") for p in (tmp_path / "lib").rglob("*.png")]
    assert {str(f) for f in files} == {"Nintendo - Game Boy Advance/_.._escape.png", "Nintendo - Game Boy Advance/Metroid_ Zero_Mission.png"}
    assert not (tmp_path / "escape.png").exists()


def test_corrupt_entries_and_bad_data_are_ignored(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    game = Game(Path("/a/GBA/Game.gba"), None)
    assert not library.put(game, b"not an image", ["Game"])
    folder = tmp_path / "lib/Nintendo - Game Boy Advance"
    folder.mkdir(parents=True)
    (folder / "Game.png").write_bytes(b"truncated")
    assert library.get(game) is None


def test_second_device_is_served_from_the_library(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    first = tmp_path / "anbernic/Roms/NDS"; first.mkdir(parents=True)
    m = LibraryModel(store=MemoryStore(), service=FakeService(delay=0), artwork_library=library)
    m.games = [Game(make_rom(first, f"Game {i}.nds", code=f"AB{i}E"), f"AB{i}E") for i in range(3)]
    m.download_and_save_all()
    assert m.wait(10) and m.saved == 3

    second = tmp_path / "dsi"; second.mkdir()
    OfflineService.calls = 0
    m2 = LibraryModel(store=MemoryStore(), service=OfflineService(), artwork_library=library)
    m2.profile, m2.destination = Profile.TWILIGHT, tmp_path / "dsi-sd"
    m2.games = [Game(make_rom(second, f"renamed {i}.nds", code=f"AB{i}E"), f"AB{i}E") for i in range(3)]
    m2.download_and_save_all()
    assert m2.wait(10)
    assert OfflineService.calls == 0
    assert m2.saved == 3
    assert {g.source for g in m2.games} == {"Local artwork library"}
    out = tmp_path / "dsi-sd/_nds/TWiLightMenu/boxart/renamed 0.nds.png"
    assert Image.open(out).size[0] <= 128  # Re-rendered for this device's profile.


def test_imports_are_remembered(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    m = LibraryModel(store=MemoryStore(), artwork_library=library)
    rom = make_rom(tmp_path, "Homebrew.nds", code="XXXX")
    m.games = [Game(rom, None)]
    image = tmp_path / "cover.png"; image.write_bytes(png(64, 64))
    m.import_image(image, m.games[0].id)
    assert library.get(Game(Path("/elsewhere/NDS/Homebrew.nds"), None)) == png(64, 64)


def test_library_can_be_turned_off(tmp_path):
    library = ArtworkLibrary(tmp_path / "lib")
    store = MemoryStore()
    m = LibraryModel(store=store, service=FakeService(delay=0), artwork_library=library)
    m.set_use_library(False)
    m.games = [Game(make_rom(tmp_path, "Game.nds"), None)]
    m.download()
    assert m.wait(10) and m.ready == 1
    assert not (tmp_path / "lib").exists()
    assert not LibraryModel(store=store, artwork_library=library).use_library


def test_tests_use_a_temporary_library():
    assert "boxart-tests-" in str(default_root())
