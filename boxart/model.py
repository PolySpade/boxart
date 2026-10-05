"""Application state and background jobs, independent of the widgets."""
from __future__ import annotations

import getpass
import glob
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal

from . import library, normalization
from .artwork import ArtworkService, Cancelled
from .cache import ArtworkLibrary
from .errors import ArtError
from .library import ExportSettings, Game, Profile
from .systems import GameSystem, match_playlist

FILTERS = ["All games", "Needs artwork", "Ready to save", "Saved"]
WORKER_CHOICES = [1, 2, 4, 6, 8, 12, 16]
DEFAULT_WORKERS = 6


def default_folder() -> str:
    user = getpass.getuser()
    for pattern in (f"/run/media/{user}/*/Roms/NDS", f"/media/{user}/*/Roms/NDS", "/mnt/*/Roms/NDS"):
        if found := sorted(glob.glob(pattern)):
            return found[0]
    return f"/run/media/{user}/DS/Roms/NDS"


class LibraryModel(QObject):
    changed = Signal()
    status_changed = Signal()
    error_raised = Signal(str)

    def __init__(self, store: QSettings | None = None, service: ArtworkService | None = None, artwork_library: ArtworkLibrary | None = None):
        super().__init__()
        self.store = store if store is not None else QSettings("BoxArt", "BoxArt")
        self.folder = str(self.store.value("romFolder", "") or default_folder())
        self.normalize_filenames = self.store.value("normalizeFilenames", False) in (True, "true")
        try:
            self.workers = max(1, min(16, int(self.store.value("downloadWorkers", DEFAULT_WORKERS))))
        except (TypeError, ValueError):
            self.workers = DEFAULT_WORKERS
        self.games: list[Game] = []
        self.selection: str | None = None
        self.selected_ids: set[str] = set()
        self._anchor: str | None = None
        self.query = ""
        self.filter = "All games"
        self.system_filter: GameSystem | None = None
        self.profile = Profile.ANBERNIC
        self.size = 512
        self.jpeg = False
        self.identities = {}
        self.destination: Path | None = None
        self.busy = False
        self.progress = 0.0
        self.message = "Connect your SD card to get started."
        self.error: str | None = None
        self.service = service or ArtworkService()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self.artwork_library = artwork_library or ArtworkLibrary()
        self.use_library = self.store.value("useArtworkLibrary", True) in (True, "true")

    # Selection

    def select(self, id: str, shift: bool = False, command: bool = False):
        ids = [g.id for g in self.visible]
        if id not in ids:
            return
        end = ids.index(id)
        if shift and self._anchor in ids:
            start = ids.index(self._anchor)
            span = set(ids[min(start, end):max(start, end) + 1])
            self.selected_ids = self.selected_ids | span if command else span
        elif command:
            self.selected_ids ^= {id}
            self._anchor = id
        else:
            self.selected_ids = {id}
            self._anchor = id
        self.selection = id if id in self.selected_ids else next((i for i in ids if i in self.selected_ids), None)
        self.changed.emit()

    def set_list_selection(self, ids: set[str], current: str | None = None):
        self.selected_ids = set(ids)
        if current in ids:
            self.selection = current
        elif self.selection not in ids:
            self.selection = next((g.id for g in self.visible if g.id in ids), None)
        self._anchor = self.selection

    def prune_selection(self):
        self.selected_ids &= {g.id for g in self.visible}
        if self.selection not in self.selected_ids:
            self.selection = next((g.id for g in self.visible if g.id in self.selected_ids), None)
        if self._anchor is not None and self._anchor not in self.selected_ids:
            self._anchor = self.selection

    # Derived state

    @property
    def settings(self) -> ExportSettings:
        destination = self.destination
        if destination is None and self.profile is Profile.RETROARCH:
            destination = ExportSettings.suggested_retroarch_directory(Path(self.folder))
        return ExportSettings(self.profile, dict(self.identities), destination, self.size, self.jpeg)

    @property
    def matching_games(self) -> list[Game]:
        query = self.query.casefold()
        return [g for g in self.games if (self.system_filter is None or g.system is self.system_filter)
                and (not query or query in g.title.casefold() or (g.code is not None and query in g.code.casefold()))]

    @staticmethod
    def matches_artwork_filter(game: Game, filter: str) -> bool:
        if filter == "Ready to save":
            return game.status == "Ready"
        if filter == "Saved":
            return game.saved_path is not None
        if filter == "Needs artwork":
            return game.saved_path is None and game.status != "Ready"
        return True

    @property
    def visible(self) -> list[Game]:
        return [g for g in self.matching_games if self.matches_artwork_filter(g, self.filter)]

    def filter_count(self, filter: str) -> int:
        return sum(self.matches_artwork_filter(g, filter) for g in self.matching_games)

    @property
    def ready(self) -> int:
        return sum(g.status == "Ready" for g in self.games)

    @property
    def saved(self) -> int:
        return sum(g.saved_path is not None for g in self.games)

    @property
    def selected(self) -> Game | None:
        return next((g for g in self.games if g.id == self.selection), None)

    def game(self, id: str) -> Game | None:
        return next((g for g in self.games if g.id == id), None)

    # Settings

    def set_folder(self, folder: str):
        self.folder = folder
        self.store.setValue("romFolder", folder)
        self.scan()

    def set_normalize_filenames(self, value: bool):
        self.normalize_filenames = value
        self.store.setValue("normalizeFilenames", value)

    def set_workers(self, value: int):
        self.workers = max(1, min(16, int(value)))
        self.store.setValue("downloadWorkers", self.workers)

    def set_use_library(self, value: bool):
        self.use_library = value
        self.store.setValue("useArtworkLibrary", value)

    def _remember(self, game: Game, data: bytes, names, replace: bool = False):
        # The library is a convenience; never let it fail a download or import.
        try:
            self.artwork_library.put(game, data, names, replace=replace)
        except OSError:
            pass

    def set_destination(self, path: Path | None):
        self.destination = path
        self.refresh_existing()

    def _fail(self, text: str):
        self.error = text
        self.error_raised.emit(text)

    def _status(self, message: str | None = None, progress: float | None = None):
        if message is not None:
            self.message = message
        if progress is not None:
            self.progress = progress
        self.status_changed.emit()

    # Jobs

    def _start(self, target, *args):
        self.busy = True
        self.progress = 0.0
        self._cancel = threading.Event()
        cancel = self._cancel

        def run():
            try:
                target(cancel, *args)
            except Exception as error:  # Never leave the app stuck busy.
                self._fail(str(error))
            finally:
                self.busy = False
                self.status_changed.emit()
                self.changed.emit()

        self._thread = threading.Thread(target=run, daemon=True)
        self.status_changed.emit()
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the current job finishes. Used by tests and on quit."""
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.busy

    def stop(self):
        self._cancel.set()

    def scan(self):
        if self.busy:
            return
        self.message = "Reading ROM headers…"
        self._start(self._scan_job, Path(self.folder))

    def _scan_job(self, cancel, root: Path):
        try:
            scanned = library.scan(root)
        except (ArtError, OSError) as error:
            self._fail(str(error))
            self._status("Scan failed.")
            return
        self.games = scanned
        self.identities = {}
        self.selected_ids = set()
        self.selection = self._anchor = None
        self.refresh_existing(notify=False)
        self._status(f"{len(self.games)} games found. {self.saved} already have artwork.")

    def refresh_existing(self, notify: bool = True):
        settings = self.settings
        for game in self.games:
            game.saved_path = None
            try:
                path = library.existing(game.path, settings)
            except ArtError:
                path = None
            if path is not None:
                game.saved_path = path
                try:
                    game.artwork = path.read_bytes()
                except OSError:
                    game.artwork = None
                game.status = "Saved"
                game.source = "Existing artwork"
            else:
                game.status = "Missing" if game.artwork is None else "Ready"
        if notify:
            self.changed.emit()

    def download(self, selected_only: bool = False, save_after: bool = False, ids: set[str] | None = None):
        if self.busy:
            return
        targets = [g for g in self.games if g.saved_path is None and g.status != "Ready"
                   and (not selected_only or g.id == self.selection) and (ids is None or g.id in ids)]
        if not targets:
            return
        self._start(self._download_job, targets, save_after, None if ids is None else set(ids), self.normalize_filenames)

    def _lookup(self, game: Game, cancel: threading.Event, normalize: bool):
        """Network-only half of a download; runs on a pool thread and never touches files."""
        with self._state_lock:
            if cancel.is_set():
                raise Cancelled()
            game.status = "Searching"
        self.changed.emit()
        lookup = Game(game.path, game.code, game.title, game.lookup_name)
        canonical = None
        if normalize:
            if game.id in self.identities or self.profile is Profile.RETROARCH:
                raise ArtError("Disable filename normalization for RetroArch or imported playlists; their paths must remain unchanged.")
            canonical = self.service.normalized_name(lookup, cancel)
            lookup.lookup_name = canonical or lookup.lookup_name
        if self.use_library and (data := self.artwork_library.get(lookup)) is not None:
            return canonical, (data, "Local artwork library"), True
        return canonical, self.service.artwork(lookup, cancel), False

    def _download_job(self, cancel, targets, save_after, batch_ids, normalize):
        workers = max(1, min(self.workers, len(targets)))
        pool = ThreadPoolExecutor(workers, thread_name_prefix="boxart-download")
        futures = {pool.submit(self._lookup, game, cancel, normalize): game for game in targets}
        done = 0
        self._status(f"Finding artwork · 0 of {len(targets)}" + (f" · {workers} at a time" if workers > 1 else ""))
        try:
            # Results are applied here, one at a time, so renames and selection updates stay serial.
            for future in as_completed(futures):
                game = futures[future]
                try:
                    canonical, result, cached = future.result()
                    if cancel.is_set():
                        raise Cancelled()
                    if result is not None:
                        data, source = result
                        original_stem = game.path.stem
                        if canonical is not None:
                            self._rename(game, canonical, batch_ids, cancel)
                        if self.use_library and not cached:
                            self._remember(game, data, [game.lookup_name, original_stem, game.path.stem])
                        game.artwork, game.source, game.status = data, source, "Ready"
                    else:
                        game.status, game.source = "Not found", "Try importing an image."
                except Cancelled:
                    break
                except Exception as error:
                    if cancel.is_set():
                        break
                    game.status, game.source = "Error", str(error)
                done += 1
                self._status(f"Finding artwork · {done} of {len(targets)} · {game.title}", done / len(targets))
                self.changed.emit()
        finally:
            # Don't wait on in-flight requests after Stop; their results are discarded.
            pool.shutdown(wait=not cancel.is_set(), cancel_futures=True)
            with self._state_lock:
                for game in targets:
                    if game.status == "Searching":
                        game.status = "Missing"
        if cancel.is_set():
            self._status("Stopped. Downloaded artwork is ready to save.")
        else:
            self._status(f"Search complete. {self.ready} covers ready to save.")
            if save_after:
                pending = self._pending_saves(batch_ids)
                if pending:
                    self._save_job(cancel, pending, self.settings)

    def _rename(self, game: Game, canonical: str, batch_ids, cancel):
        settings = self.settings
        old_id = game.id
        if library.existing(game.path, settings) is not None:
            raise ArtError("Renaming skipped because this ROM already has artwork.")
        target = game.path.with_name(canonical + game.path.suffix)
        if target != game.path and library.existing(target, settings) is not None:
            raise ArtError("Renaming skipped because the new name already has artwork.")
        if cancel.is_set():
            raise Cancelled()
        renamed = normalization.rename(game.path, canonical)
        game.path, game.title, game.lookup_name = renamed, Game.clean(canonical), canonical
        new_id = str(renamed)
        if old_id in self.selected_ids:
            self.selected_ids = (self.selected_ids - {old_id}) | {new_id}
        if self.selection == old_id:
            self.selection = new_id
        if self._anchor == old_id:
            self._anchor = new_id
        if batch_ids is not None and old_id in batch_ids:
            batch_ids.discard(old_id)
            batch_ids.add(new_id)

    def download_and_save_all(self):
        self._download_and_save(None)

    def get_for_selected(self):
        if self.selected_ids:
            self._download_and_save(set(self.selected_ids))

    def _download_and_save(self, ids):
        if self.busy:
            return
        targets = [g for g in self.games if g.saved_path is None and (ids is None or g.id in ids)]
        if not targets:
            self._status("Selected games already have artwork.")
            return
        try:
            for game in targets:
                self.settings.output(game.path)
        except ArtError as error:
            self._fail(str(error))
            return
        if any(g.status != "Ready" for g in targets):
            self.download(save_after=True, ids=ids)
        else:
            self.save(ids)

    def _pending_saves(self, ids) -> list[Game] | None:
        settings = self.settings
        pending = [g for g in self.games if g.status == "Ready" and (ids is None or g.id in ids)]
        if not pending:
            return None
        # Detect collisions before writing any artwork into a shared destination.
        try:
            paths = [str(settings.output(g.path)).casefold() for g in pending]
        except ArtError as error:
            self._fail(str(error))
            return None
        if len(set(paths)) != len(paths):
            self._fail("Multiple ROMs would export to the same filename. Use per-ROM Imgs folders or separate the exports.")
            return None
        return pending

    def save(self, ids: set[str] | None = None):
        if self.busy:
            return
        if pending := self._pending_saves(ids):
            self._start(self._save_job, pending, self.settings)

    def _save_job(self, cancel, pending, settings):
        count = 0
        for offset, game in enumerate(pending):
            if cancel.is_set():
                break
            if game.artwork is None:
                continue
            try:
                game.saved_path = library.save(game.artwork, game.path, settings)
                game.status = "Saved"
                count += 1
            except (ArtError, OSError) as error:
                game.status, game.source = "Save failed", str(error)
            self._status(progress=(offset + 1) / len(pending))
            self.changed.emit()
        failed = sum(g.status == "Save failed" for g in self.games)
        self._status(f"Saved {count} covers. {failed} failed.")

    def import_playlists(self, paths: list[Path]):
        try:
            matches = dict(self.identities)
            for path in paths:
                matches.update(match_playlist(Path(path).read_bytes(), Path(path).name, self.games))
        except (ArtError, OSError) as error:
            self._fail(str(error))
            return
        self.identities = matches
        for game in self.games:
            identity = matches.get(game.id)
            game.lookup_name = identity.label if identity else None
        self.refresh_existing()
        self._status(f"Matched playlist labels to {len(matches)} games. Ambiguous or absent filenames were skipped.")

    def import_image(self, path: Path, id: str | None = None):
        if self.busy:
            return
        game = self.game(id or self.selection or "")
        if game is None or game.saved_path is not None:
            return
        try:
            data = Path(path).read_bytes()
            library.render(data, self.settings)
        except (ArtError, OSError) as error:
            self._fail(str(error))
            return
        game.artwork, game.source, game.status = data, f"Imported · {Path(path).name}", "Ready"
        if self.use_library:
            self._remember(game, data, [game.lookup_name, game.path.stem], replace=True)
        self.changed.emit()
