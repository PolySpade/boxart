import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from boxart.artwork import ArtworkService, Cancelled
from boxart.library import Game
from boxart.model import LibraryModel
from conftest import MemoryStore, make_rom, png


class FakeService:
    """Answers lookups after a delay and records how many ran at once."""
    def __init__(self, delay=0.05, missing=(), canonical=None):
        self.delay, self.missing, self.canonical = delay, set(missing), canonical or {}
        self.active = self.peak = 0
        self.lock = threading.Lock()

    def normalized_name(self, game, cancel=None):
        return self.canonical.get(game.path.stem)

    def artwork(self, game, cancel=None):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            deadline = time.monotonic() + self.delay
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                time.sleep(0.005)
            name = game.lookup_name or game.path.stem
            return None if name in self.missing else (png(8, 8), f"Fake · {name}")
        finally:
            with self.lock:
                self.active -= 1


def library(tmp_path, count, service, workers=6):
    m = LibraryModel(store=MemoryStore(), service=service)
    m.set_workers(workers)
    m.games = [Game(make_rom(tmp_path, f"Game {i}.nds"), None) for i in range(count)]
    return m


def test_downloads_run_concurrently_and_apply_every_result(tmp_path):
    service = FakeService(missing={"Game 3"})
    m = library(tmp_path, 12, service, workers=4)
    started = time.monotonic()
    m.download()
    assert m.wait(10)
    assert service.peak == 4
    assert time.monotonic() - started < 12 * service.delay  # Faster than one at a time.
    statuses = {g.path.stem: g.status for g in m.games}
    assert statuses.pop("Game 3") == "Not found"
    assert set(statuses.values()) == {"Ready"}
    assert m.progress == 1.0


def test_single_worker_is_sequential(tmp_path):
    service = FakeService(delay=0.01)
    m = library(tmp_path, 4, service, workers=1)
    m.download()
    assert m.wait(10)
    assert service.peak == 1 and m.ready == 4


def test_stop_returns_promptly_and_leaves_nothing_searching(tmp_path):
    service = FakeService(delay=0.5)
    m = library(tmp_path, 20, service, workers=4)
    m.download()
    time.sleep(0.1)
    m.stop()
    assert m.wait(2)
    assert not any(g.status == "Searching" for g in m.games)
    assert m.ready < 20
    assert m.message.startswith("Stopped")


def test_download_and_save_all_in_parallel(tmp_path):
    m = library(tmp_path, 8, FakeService(delay=0.01))
    m.download_and_save_all()
    assert m.wait(10)
    assert m.saved == 8
    assert len(list((tmp_path / "Imgs").iterdir())) == 8


def test_parallel_lookups_with_renames_keep_selection_in_sync(tmp_path):
    service = FakeService(canonical={f"Game {i}": f"Title {i} (USA)" for i in range(6)})
    m = library(tmp_path, 6, service)
    m.set_normalize_filenames(True)
    m.select(m.games[0].id); m.select(m.games[5].id, shift=True)
    m.get_for_selected()
    assert m.wait(10)
    assert sorted(p.name for p in tmp_path.glob("*.nds")) == [f"Title {i} (USA).nds" for i in range(6)]
    assert m.selected_ids == {g.id for g in m.games}
    assert m.saved == 6


def test_name_index_is_fetched_once_across_threads(monkeypatch):
    service = ArtworkService()
    calls = []

    def fake_get(url, cancel):
        calls.append(url)
        time.sleep(0.05)
        return 200, json.dumps({"tree": [{"path": "Named_Boxarts/Game (USA).png", "type": "blob"}]}).encode()

    monkeypatch.setattr(service, "_get", fake_get)
    games = [Game(Path(f"/Roms/GBA/Game_USA_{i}.gba"), None) for i in range(8)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(service.normalized_name, games))
    assert len(calls) == 1


def test_worker_setting_is_persisted_and_clamped():
    store = MemoryStore()
    LibraryModel(store=store).set_workers(64)
    assert LibraryModel(store=store).workers == 16
    store.setValue("downloadWorkers", "junk")
    assert LibraryModel(store=store).workers == 6
