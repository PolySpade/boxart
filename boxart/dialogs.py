"""File dialogs that use the desktop's native picker and surface removable drives."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QStorageInfo, QUrl
from PySide6.QtWidgets import QFileDialog, QWidget

_MOUNT_ROOTS = ("/run/media/", "/media/", "/mnt/")


def configure_platform_theme():
    """Route file dialogs through xdg-desktop-portal when Qt has no desktop integration.

    PySide6 wheels bundle their own Qt, which cannot load the system's KDE (or other)
    platform theme, so dialogs would fall back to Qt's generic picker. The portal
    shows the desktop's own dialog instead: KDE's on Plasma, GTK's on GNOME. Must run
    before QApplication is created; an explicit QT_QPA_PLATFORMTHEME is respected.
    """
    if os.environ.get("QT_QPA_PLATFORMTHEME") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return
    themes = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath), "platformthemes")
    plugins = [p.name for p in themes.glob("*.so")] if themes.is_dir() else []
    if any("KDEPlasma" in name for name in plugins):
        return  # System Qt with plasma-integration already gives KDE dialogs.
    if any("xdgdesktopportal" in name for name in plugins):
        os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"


def removable_volumes() -> list[Path]:
    """Mounted SD cards, USB drives and other user-mounted volumes."""
    volumes = []
    for volume in QStorageInfo.mountedVolumes():
        root = volume.rootPath()
        if volume.isValid() and volume.isReady() and root.startswith(_MOUNT_ROOTS):
            volumes.append(Path(root))
    return sorted(volumes)


def start_directory(path: str | os.PathLike | None) -> str:
    """The nearest existing folder to start in, preferring a removable volume over '/'."""
    if path:
        candidate = Path(path)
        while not candidate.is_dir() and candidate != candidate.parent:
            candidate = candidate.parent
        if candidate.is_dir() and candidate != Path("/"):
            return str(candidate)
    volumes = removable_volumes()
    return str(volumes[0] if volumes else Path.home())


def _dialog(parent: QWidget, title: str, start, mode: QFileDialog.FileMode, filters: str | None = None) -> QFileDialog:
    dialog = QFileDialog(parent, title, start_directory(start))
    dialog.setFileMode(mode)
    if mode == QFileDialog.FileMode.Directory:
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
    if filters:
        dialog.setNameFilters(filters.split(";;"))
    # Only used when no native dialog is available: list drives beside the usual places.
    places = [Path.home(), *removable_volumes()]
    dialog.setSidebarUrls([QUrl.fromLocalFile(str(p)) for p in places])
    return dialog


def choose_directory(parent: QWidget, title: str, start=None) -> Path | None:
    dialog = _dialog(parent, title, start, QFileDialog.FileMode.Directory)
    if dialog.exec() and dialog.selectedFiles():
        return Path(dialog.selectedFiles()[0])
    return None


def choose_files(parent: QWidget, title: str, start=None, filters: str | None = None, multiple: bool = False) -> list[Path]:
    mode = QFileDialog.FileMode.ExistingFiles if multiple else QFileDialog.FileMode.ExistingFile
    dialog = _dialog(parent, title, start, mode, filters)
    if dialog.exec():
        return [Path(f) for f in dialog.selectedFiles()]
    return []
