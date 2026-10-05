import io
from dataclasses import replace

import pytest
from PIL import Image

from boxart import library
from boxart.artwork import ArtworkService
from boxart.errors import ArtError
from boxart.library import ExportSettings, Game, Profile
from conftest import live, make_rom, png


def test_scan_reads_headers_and_ignores_hidden_files(tmp_path):
    file = make_rom(tmp_path)
    make_rom(tmp_path, "._Mario.nds")
    make_rom(tmp_path, "Notes.txt")
    (tmp_path / ".hidden").mkdir()
    make_rom(tmp_path / ".hidden", "Other.nds")
    (tmp_path / "Link.nds").symlink_to(file)
    games = library.scan(tmp_path)
    assert [(g.path, g.code) for g in games] == [(file, "ASME")]


def test_scan_skips_bin_tracks_beside_descriptors_and_sorts_naturally(tmp_path):
    ps = tmp_path / "PS"
    ps.mkdir()
    for name in ("Game 10.cue", "Game 10 (Track 1).bin", "Game 9.chd"):
        (ps / name).write_bytes(b"x")
    assert [g.path.name for g in library.scan(tmp_path)] == ["Game 9.chd", "Game 10.cue"]


def test_missing_folder(tmp_path):
    with pytest.raises(ArtError):
        library.scan(tmp_path / "absent")


@live
def test_live_provider(tmp_path):
    file = make_rom(tmp_path, code="B6ZE")
    result = ArtworkService().artwork(Game(file, "B6ZE"))
    assert result is not None
    library.save(result[0], file, ExportSettings())


def test_invalid_header_falls_back(tmp_path):
    file = tmp_path / "Homebrew.nds"
    file.write_bytes(bytes([0, 1]))
    assert library.game_code(file) is None


def test_profile_naming_preserves_exact_stem(tmp_path):
    file = make_rom(tmp_path, " Mario.nds")
    settings = ExportSettings()
    assert settings.output(file).name == " Mario.png"
    assert settings.output(file).parent.name == "Imgs"
    settings.profile = Profile.TWILIGHT
    with pytest.raises(ArtError):
        settings.output(file)
    settings.destination = tmp_path
    assert settings.output(file).name == " Mario.nds.png"


def test_resize_and_never_overwrite(tmp_path):
    file = make_rom(tmp_path)
    original = file.read_bytes()
    output = library.save(png(), file, ExportSettings())
    data = output.read_bytes()
    assert Image.open(io.BytesIO(data)).size == (512, 460)
    with pytest.raises(ArtError):
        library.save(png(), file, ExportSettings())
    assert output.read_bytes() == data
    assert file.read_bytes() == original
    assert [p.name for p in output.parent.iterdir()] == ["Mario (USA).png"]


def test_downscales_and_flattens_transparency(tmp_path):
    settings = ExportSettings(max_size=128)
    image = Image.open(io.BytesIO(library.render(png(1024, 512), settings)))
    assert image.size == (128, 64)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    jpeg = library.render(png(), replace(settings, profile=Profile.CUSTOM, jpeg=True))
    assert Image.open(io.BytesIO(jpeg)).format == "JPEG"


def test_jpeg_existing_and_twilight_dimensions(tmp_path):
    file = make_rom(tmp_path)
    settings = ExportSettings()
    target = settings.output(file).with_suffix(".jpg")
    target.parent.mkdir(parents=True)
    target.write_bytes(png())
    assert library.existing(file, settings) == target
    with pytest.raises(ArtError):
        library.save(png(), file, settings)
    settings.profile, settings.destination = Profile.TWILIGHT, tmp_path
    width, height = Image.open(io.BytesIO(library.render(png(), settings))).size
    assert width <= 128 and height <= 115


def test_invalid_image_and_missing_card(tmp_path):
    file = make_rom(tmp_path)
    with pytest.raises(ArtError):
        library.save(b"bad", file, ExportSettings())
    assert not (tmp_path / "Imgs").exists()
    file.unlink()
    with pytest.raises(ArtError):
        library.save(png(), file, ExportSettings())
