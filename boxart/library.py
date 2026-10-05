"""Scanning ROM libraries, export naming, and writing artwork."""
from __future__ import annotations

import io
import os
import re
import stat
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PIL import Image

from .errors import ArtError
from .fileops import move_no_replace
from .systems import GameSystem, PlaylistIdentity


class Profile(Enum):
    ANBERNIC = "Anbernic · Imgs / NNDDSS"
    RETROARCH = "RetroArch"
    TWILIGHT = "TWiLight Menu++"
    CUSTOM = "Custom folder"

    @property
    def detail(self) -> str:
        return {
            Profile.ANBERNIC: "Imgs beside each ROM • filename without .nds • PNG. Community-reported layout; 512 px was tested on RG DS Plus; size is configurable.",
            Profile.RETROARCH: "Choose RetroArch’s thumbnails directory. Uses system/Named_Boxarts/label.png. Import .lpl playlists to match their exact labels; otherwise uses standard system names and ROM stems.",
            Profile.TWILIGHT: "Select the SD card root as destination. Uses _nds/TWiLightMenu/boxart and the full ROM filename. PNG fitted within 128 × 115.",
            Profile.CUSTOM: "Choose a destination, size and format. Images use the ROM filename without its extension.",
        }[self]


def _mount_root(parts: tuple[str, ...]) -> Path | None:
    """The removable volume containing a path, for the common Linux mount layouts."""
    if len(parts) > 4 and parts[1:3] == ("run", "media"):
        return Path(*parts[:5])
    if len(parts) > 3 and parts[1] == "media":
        return Path(*parts[:4])
    if len(parts) > 2 and parts[1] in ("mnt", "Volumes"):
        return Path(*parts[:3])
    return None


@dataclass
class ExportSettings:
    profile: Profile = Profile.ANBERNIC
    identities: dict[str, PlaylistIdentity] = field(default_factory=dict)
    destination: Path | None = None
    max_size: int = 512
    jpeg: bool = False

    @staticmethod
    def suggested_retroarch_directory(rom_folder: Path) -> Path:
        parts = Path(os.path.normpath(rom_folder)).parts
        index = next((i for i, p in enumerate(parts) if p.casefold() == "roms"), None)
        if index is not None:
            root = Path(*parts[:index]) if index else Path("/")
        else:
            root = _mount_root(parts) or Path(*parts).parent
        for suffix in ("RetroArch/thumbnails", "retroarch/thumbnails", ".config/retroarch/thumbnails"):
            if (root / suffix).is_dir():
                return root / suffix
        return root / "RetroArch/thumbnails"

    def output(self, rom: Path) -> Path:
        if self.profile is Profile.ANBERNIC:
            folder = rom.parent / "Imgs"
        elif self.profile is Profile.RETROARCH:
            if self.destination is None:
                raise ArtError("Choose RetroArch’s thumbnails directory.")
            identity = self.identities.get(str(rom))
            system = identity.database if identity else (s.value if (s := GameSystem.infer(rom)) else None)
            if system is None:
                raise ArtError("Cannot determine this ROM’s system.")
            name = PlaylistIdentity.safe_name(identity.label if identity else rom.stem)
            return self.destination / system / "Named_Boxarts" / (name + ".png")
        elif self.profile is Profile.TWILIGHT:
            if self.destination is None:
                raise ArtError("Choose the SD card root for TWiLight Menu++.")
            folder = self.destination / "_nds/TWiLightMenu/boxart"
        else:
            if self.destination is None:
                raise ArtError("Choose an artwork destination.")
            folder = self.destination
        name = rom.name if self.profile is Profile.TWILIGHT else rom.stem
        return folder / (name + (".jpg" if self.profile is Profile.CUSTOM and self.jpeg else ".png"))


_TAGS = re.compile(r"\([^)]*\)|\[[^]]*\]")


@dataclass
class Game:
    path: Path
    code: str | None
    title: str = ""
    lookup_name: str | None = None
    artwork: bytes | None = None
    source: str = ""
    status: str = "Missing"
    saved_path: Path | None = None

    def __post_init__(self):
        self.path = Path(self.path)
        if not self.title:
            self.title = self.clean(self.path.stem)

    @property
    def id(self) -> str:
        return str(self.path)

    @property
    def system(self) -> GameSystem:
        return GameSystem.infer(self.path) or GameSystem.NDS

    @staticmethod
    def clean(name: str) -> str:
        return _TAGS.sub("", name).replace("_", " ").strip()


def _natural_key(text: str):
    return [(0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk) for chunk in re.split(r"(\d+)", text.casefold()) if chunk]


def game_code(path: Path) -> str | None:
    with open(path, "rb") as file:
        file.seek(12)
        data = file.read(4)
    if len(data) == 4 and all(65 <= b <= 90 or 48 <= b <= 57 for b in data):
        return data.decode("ascii")
    return None


def scan(root: Path) -> list[Game]:
    root = Path(root)
    if not root.is_dir():
        raise ArtError("ROM folder is unavailable. Connect your card or choose another folder.")
    games = []

    def fail(error):
        raise error

    for folder, dirs, files in os.walk(root, onerror=fail):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        has_descriptor = any(f.lower().endswith((".cue", ".gdi")) for f in files)
        for name in files:
            if name.startswith("."):
                continue
            path = Path(folder, name)
            if GameSystem.infer(path) is None:
                continue
            if has_descriptor and path.suffix.lower() == ".bin":
                continue
            if not stat.S_ISREG(os.lstat(path).st_mode):
                continue
            code = game_code(path) if path.suffix.lower() in (".nds", ".dsi") else None
            games.append(Game(path, code))
    return sorted(games, key=lambda g: _natural_key(g.title))


def existing(rom: Path, settings: ExportSettings) -> Path | None:
    target = settings.output(rom)
    alternatives = [target]
    if settings.profile is Profile.ANBERNIC:
        alternatives += [target.with_suffix(".jpg"), target.with_suffix(".jpeg")]
    return next((p for p in alternatives if p.exists()), None)


def decode(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        if image.width > 10000 or image.height > 10000:
            raise ArtError("The source is not a supported image.")
        image.load()
        return image
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise ArtError("The source is not a supported image.") from error


def render(data: bytes, settings: ExportSettings) -> bytes:
    image = decode(data)
    twilight = settings.profile is Profile.TWILIGHT
    width_limit = 128 if twilight else max(32, min(settings.max_size, 2048))
    height_limit = 115 if twilight else width_limit
    scale = min(1.0, width_limit / image.width, height_limit / image.height)
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    # Flatten any transparency onto white, as the handheld frontends expect opaque covers.
    rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    if flat.size != size:
        flat = flat.resize(size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if settings.profile is Profile.CUSTOM and settings.jpeg:
        flat.save(out, "JPEG", quality=92)
    else:
        flat.save(out, "PNG", optimize=True)
    return out.getvalue()


def save(data: bytes, rom: Path, settings: ExportSettings) -> Path:
    if not rom.exists():
        raise ArtError("ROM unavailable. Reconnect the SD card and scan again.")
    if existing(rom, settings) is not None:
        raise ArtError("Artwork already exists; preserved the existing file.")
    output = settings.output(rom)
    rendered = render(data, settings)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / f".boxart-{uuid.uuid4()}.tmp"
    try:
        with open(temporary, "xb") as file:
            file.write(rendered)
            file.flush()
            os.fsync(file.fileno())
        try:
            move_no_replace(temporary, output)
        except FileExistsError as error:
            raise ArtError("Artwork already exists; preserved the existing file.") from error
    finally:
        temporary.unlink(missing_ok=True)
    return output
