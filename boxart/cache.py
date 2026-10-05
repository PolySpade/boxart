"""A local library of original-quality artwork, shared by every device BoxArt exports to."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from .fileops import move_no_replace
from .library import Game, decode
from .systems import PlaylistIdentity

_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "TIFF": ".tif"}


def default_root() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(data_home, "boxart", "artwork")


class ArtworkLibrary:
    """Covers stored as <root>/<system>/<name>.<ext>, plus <system>/by-code/<CODE>.<ext> for DS.

    Files are the bytes as downloaded or imported, never resized, so each export
    profile can render them at its own size. Writes are atomic; readers on other
    threads only ever see complete files.
    """

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else default_root()
        self._lock = threading.Lock()

    def _keys(self, game: Game, names: list[str | None]) -> list[Path]:
        folder = self.root / game.system.value
        keys = []
        if game.code:
            keys.append(folder / "by-code" / game.code)
        for name in names:
            if name:
                key = folder / PlaylistIdentity.safe_name(name).lstrip(".")
                if key.name and key not in keys:
                    keys.append(key)
        return keys

    @staticmethod
    def _find(key: Path) -> Path | None:
        for ext in _EXTENSIONS.values():
            path = key.with_name(key.name + ext)
            if path.is_file():
                return path
        return None

    def get(self, game: Game) -> bytes | None:
        """Exact code or name match only, mirroring the online providers."""
        for key in self._keys(game, [game.lookup_name, game.path.stem]):
            if (path := self._find(key)) is not None:
                try:
                    data = path.read_bytes()
                    decode(data)
                    return data
                except Exception:
                    continue  # Unreadable or corrupt entries fall through to the next key.
        return None

    def put(self, game: Game, data: bytes, names: list[str | None], replace: bool = False) -> bool:
        """Store artwork under the game's code and each name. Returns True if anything was written.

        Downloads never replace an existing entry; an explicit import does (replace=True).
        """
        try:
            ext = _EXTENSIONS.get(decode(data).format or "", ".png")
        except Exception:
            return False
        written = False
        with self._lock:
            for key in self._keys(game, names):
                existing = self._find(key)
                if existing is not None and not replace:
                    continue
                key.parent.mkdir(parents=True, exist_ok=True)
                temporary = key.parent / f".boxart-{uuid.uuid4()}.tmp"
                try:
                    temporary.write_bytes(data)
                    if existing is not None:
                        existing.unlink(missing_ok=True)
                    try:
                        move_no_replace(temporary, key.with_name(key.name + ext))
                        written = True
                    except FileExistsError:
                        pass
                finally:
                    temporary.unlink(missing_ok=True)
        return written

    def stats(self) -> tuple[int, int]:
        """(number of covers by name, total bytes) for display."""
        count = size = 0
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.is_file() and not path.name.startswith("."):
                    size += path.stat().st_size
                    count += path.parent.name != "by-code"
        return count, size
