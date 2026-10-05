"""Game systems, Libretro naming and RetroArch playlist matching."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath

from .errors import ArtError


class GameSystem(Enum):
    NDS = "Nintendo - Nintendo DS"
    GBA = "Nintendo - Game Boy Advance"
    GB = "Nintendo - Game Boy"
    GBC = "Nintendo - Game Boy Color"
    FDS = "Nintendo - Family Computer Disk System"
    NES = "Nintendo - Nintendo Entertainment System"
    SNES = "Nintendo - Super Nintendo Entertainment System"
    N64 = "Nintendo - Nintendo 64"
    PS = "Sony - PlayStation"
    PSP = "Sony - PlayStation Portable"
    GENESIS = "Sega - Mega Drive - Genesis"
    SMS = "Sega - Master System - Mark III"
    GG = "Sega - Game Gear"
    DREAMCAST = "Sega - Dreamcast"
    SATURN = "Sega - Saturn"
    SEGACD = "Sega - Mega-CD - Sega CD"
    SEGA32X = "Sega - 32X"
    NGPC = "SNK - Neo Geo Pocket Color"
    WSC = "Bandai - WonderSwan Color"
    PCE = "NEC - PC Engine - TurboGrafx 16"
    ATARI = "Atari - 2600"
    LYNX = "Atari - Lynx"
    NGP = "SNK - Neo Geo Pocket"
    WS = "Bandai - WonderSwan"

    @property
    def repository(self) -> str:
        return self.value.replace(" ", "_")

    @property
    def short_name(self) -> str:
        return " · ".join(self.value.split(" - ")[1:])

    @classmethod
    def infer(cls, path: PurePath | str) -> GameSystem | None:
        path = PurePath(path)
        ext = path.suffix[1:].lower()
        if ext in _EXTENSIONS:
            return _EXTENSIONS[ext]
        if ext not in _CONTAINERS:
            return None
        for part in reversed(path.parent.parts):
            if part.upper() in _FOLDERS:
                return _FOLDERS[part.upper()]
            for system in cls:
                if system.value.casefold() == part.casefold():
                    return system
        return None


S = GameSystem
_EXTENSIONS = {"nds": S.NDS, "dsi": S.NDS, "gba": S.GBA, "gb": S.GB, "gbc": S.GBC, "nes": S.NES, "fds": S.FDS, "sfc": S.SNES, "smc": S.SNES, "z64": S.N64, "n64": S.N64, "v64": S.N64, "gen": S.GENESIS, "md": S.GENESIS, "sms": S.SMS, "gg": S.GG, "pce": S.PCE, "a26": S.ATARI, "lnx": S.LYNX, "ngp": S.NGP, "ngc": S.NGPC, "ws": S.WS, "wsc": S.WSC, "32x": S.SEGA32X}
_CONTAINERS = {"zip", "7z", "chd", "cue", "pbp", "iso", "cso", "m3u", "bin", "gdi"}
_FOLDERS = {"NDS": S.NDS, "GBA": S.GBA, "GB": S.GB, "GBC": S.GBC, "FC": S.NES, "FDS": S.FDS, "SFC": S.SNES, "SNES": S.SNES, "N64": S.N64, "PS": S.PS, "PS1": S.PS, "PSX": S.PS, "PSP": S.PSP, "MD": S.GENESIS, "SMS": S.SMS, "GG": S.GG, "DREAMCAST": S.DREAMCAST, "SATURN": S.SATURN, "MDCD": S.SEGACD, "SEGA32X": S.SEGA32X, "PCE": S.PCE, "A2600": S.ATARI, "LYNX": S.LYNX, "NGP": S.NGP, "WS": S.WS}
del S

_UNSAFE = re.compile(r'[&*/:`<>?\\|"]')


@dataclass(frozen=True)
class PlaylistIdentity:
    label: str
    database: str

    @staticmethod
    def safe_name(text: str) -> str:
        return _UNSAFE.sub("_", text)


def _strip_extension(text: str) -> str:
    # Keeps any directory parts so that unsafe database names are still rejected.
    head, sep, tail = text.rpartition("/")
    if "." in tail[1:]:
        tail = tail.rsplit(".", 1)[0]
    return head + sep + tail


def match_playlist(data: bytes | str, playlist_name: str, games) -> dict[str, PlaylistIdentity]:
    """Map game ids to RetroArch playlist labels, matching by unique ROM filename."""
    try:
        items = json.loads(data)["items"]
        entries = [(str(i["path"]), str(i["label"]), i.get("db_name")) for i in items]
    except (ValueError, KeyError, TypeError) as error:
        raise ArtError("Not a JSON RetroArch playlist. Legacy six-line playlists are not supported.") from error
    result: dict[str, PlaylistIdentity] = {}
    for path, label, db_name in entries:
        name = path.replace("\\", "/").split("#")[0].rsplit("/", 1)[-1]
        matches = [g for g in games if g.path.name == name]
        if len(matches) != 1:
            continue
        game = matches[0]
        database = _strip_extension(db_name if db_name else playlist_name)
        identity = PlaylistIdentity(label, database)
        if not label or not database or database in (".", "..") or "/" in database or "\\" in database:
            raise ArtError("Playlist contains an invalid thumbnail name.")
        previous = result.get(game.id)
        if previous is not None and previous != identity:
            raise ArtError(f"Playlist contains conflicting entries for {name}.")
        result[game.id] = identity
    return result
