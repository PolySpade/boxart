"""Downloading artwork from Libretro thumbnails and GameTDB."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, normalization
from .errors import ArtError
from .library import Game, decode
from .systems import PlaylistIdentity

USER_AGENT = f"BoxArt-Linux/{__version__}"
TIMEOUT = 15
_REGIONS = {"J": "JA", "K": "KO", "D": "DE", "F": "FR", "I": "IT", "S": "ES", "E": "US"}


class Cancelled(Exception):
    pass


class ArtworkService:
    def __init__(self):
        self._names: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._repo_locks: dict[str, threading.Lock] = {}

    def _get(self, url: str, cancel: threading.Event | None) -> tuple[int, bytes]:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status, response.read(20_000_001)
        except urllib.error.HTTPError as error:
            return error.code, b""
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ArtError(f"Network error: {reason}") from error
        finally:
            if cancel is not None and cancel.is_set():
                raise Cancelled()

    def _fetch(self, url: str, cancel, follow_link: bool = True) -> bytes | None:
        status, data = self._get(url, cancel)
        if status == 404:
            return None
        if status != 200:
            raise ArtError(f"Artwork server returned HTTP {status}. Try again later.")
        if len(data) >= 20_000_000:
            return None
        try:
            decode(data)
        except ArtError:
            # Libretro stores shared covers (e.g. other discs) as git symlinks, which
            # raw.githubusercontent.com serves as a file containing the target name.
            target = data.decode("utf-8", "replace").strip()
            if follow_link and "raw.githubusercontent.com" in url and len(data) < 512 and target.endswith(".png") and "\n" not in target and not target.startswith("/"):
                return self._fetch(urllib.parse.urljoin(url, urllib.parse.quote(target)), cancel, follow_link=False)
            return None
        return data

    def normalized_name(self, game: Game, cancel: threading.Event | None = None) -> str | None:
        repo = game.system.repository
        with self._lock:
            repo_lock = self._repo_locks.setdefault(repo, threading.Lock())
        # One download of each system's index, however many threads need it at once.
        with repo_lock:
            names = self._names.get(repo)
            if names is None:
                url = f"https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/master?recursive=1"
                status, data = self._get(url, cancel)
                if status != 200:
                    raise ArtError("Artwork name index unavailable. Try again later.")
                tree = json.loads(data)
                if tree.get("truncated"):
                    raise ArtError("Artwork name index is incomplete; no automatic rename was made.")
                names = [e["path"][14:-4] for e in tree["tree"] if e["type"] == "blob" and e["path"].startswith("Named_Boxarts/") and e["path"].endswith(".png")]
                self._names[repo] = names
        original = game.path.stem
        if original in names:
            return original
        return normalization.match(original, names)

    def artwork(self, game: Game, cancel: threading.Event | None = None) -> tuple[bytes, str] | None:
        last_error = None
        # Exact filename only: do not silently assign a similarly named sequel or region.
        name = PlaylistIdentity.safe_name(game.lookup_name or game.path.stem)
        url = f"https://raw.githubusercontent.com/libretro-thumbnails/{game.system.repository}/master/Named_Boxarts/{urllib.parse.quote(name + '.png')}"
        try:
            if (data := self._fetch(url, cancel)) is not None:
                return data, "Libretro · exact filename"
        except ArtError as error:
            last_error = error
        if game.code:
            regions = []
            for value in (_REGIONS.get(game.code[-1], "EN"), "US", "EN", "JA"):
                if value not in regions:
                    regions.append(value)
            for kind, ext in (("coverM", "jpg"), ("coverS", "png")):
                for region in regions:
                    try:
                        if (data := self._fetch(f"https://art.gametdb.com/ds/{kind}/{region}/{game.code}.{ext}", cancel)) is not None:
                            return data, f"GameTDB · {game.code} · {region} · {kind}"
                    except ArtError as error:
                        last_error = error
                        break
        if last_error is not None:
            raise last_error
        return None
