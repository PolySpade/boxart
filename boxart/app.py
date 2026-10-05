"""The Qt user interface."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer, QUrl, QUrlQuery, QItemSelection, QItemSelectionModel
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from . import __version__
from .dialogs import choose_directory, choose_files, configure_platform_theme
from .library import Game, Profile
from .model import FILTERS, WORKER_CHOICES, LibraryModel
from .systems import GameSystem

APP_ID = "io.github.polyspade.BoxArt"
ICON_PATH = Path(__file__).with_name("data") / f"{APP_ID}.svg"
TEAL = QColor("#1aa6a6")
GREEN = QColor("#34a853")
FILTER_TITLES = {"All games": "All", "Needs artwork": "Missing", "Ready to save": "Unsaved", "Saved": "Saved"}
FILTER_ICONS = {"All games": "view-grid", "Needs artwork": "image-missing", "Ready to save": "document-save", "Saved": "emblem-ok-symbolic"}


def icon(name: str, fallback: QStyle.StandardPixmap | None = None) -> QIcon:
    if fallback is None:
        return QIcon.fromTheme(name)
    return QIcon.fromTheme(name, QApplication.style().standardIcon(fallback))


def status_color(status: str, palette) -> QColor:
    if status == "Saved":
        return GREEN
    if status == "Ready":
        return TEAL
    return palette.placeholderText().color()


def show_in_file_manager(path: Path):
    """Highlight a file in the desktop's file manager, or open its folder."""
    bus = QDBusConnection.sessionBus()
    if bus.isConnected():
        manager = QDBusInterface("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1", bus)
        if manager.isValid():
            reply = manager.call("ShowItems", [QUrl.fromLocalFile(str(path)).toString()], "")
            if not reply.errorName():
                return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def search_online(game: Game):
    url = QUrl("https://www.google.com/search")
    query = QUrlQuery()
    query.addQueryItem("tbm", "isch")
    query.addQueryItem("q", f"{game.title} {game.system.value} box art")
    url.setQuery(query)
    QDesktopServices.openUrl(url)


class Covers:
    """Decoded artwork, keyed by game and invalidated when its bytes change."""
    def __init__(self):
        self._cache: dict[str, tuple[bytes, QPixmap]] = {}

    def get(self, game: Game) -> QPixmap | None:
        if game.artwork is None:
            return None
        cached = self._cache.get(game.id)
        if cached is None or cached[0] is not game.artwork:
            pixmap = QPixmap()
            pixmap.loadFromData(game.artwork)
            if not pixmap.isNull() and max(pixmap.width(), pixmap.height()) > 480:
                pixmap = pixmap.scaled(480, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cached = self._cache[game.id] = (game.artwork, pixmap)
        return None if cached[1].isNull() else cached[1]


def paint_cover(painter: QPainter, rect: QRect, pixmap: QPixmap | None, palette, large: bool):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    background = QColor(palette.text().color())
    background.setAlphaF(0.07)
    path = QPainterPath()
    path.addRoundedRect(rect, 8, 8)
    painter.fillPath(path, background)
    if pixmap is not None:
        inner = rect.adjusted(*(8, 8, -8, -8) if large else (2, 2, -2, -2))
        scaled = pixmap.scaled(inner.size() * painter.device().devicePixelRatioF(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(painter.device().devicePixelRatioF())
        size = scaled.deviceIndependentSize().toSize()
        painter.drawPixmap(inner.x() + (inner.width() - size.width()) // 2, inner.y() + (inner.height() - size.height()) // 2, scaled)
    else:
        placeholder = icon("image-x-generic", QStyle.SP_FileIcon)
        side = 48 if large else 20
        placeholder.paint(painter, QRect(rect.center().x() - side // 2, rect.center().y() - side // 2, side, side), Qt.AlignCenter, QIcon.Disabled)
    painter.restore()


class GameListModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1

    def __init__(self, library: LibraryModel):
        super().__init__()
        self.library = library
        self.games: list[Game] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.games)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        game = self.games[index.row()]
        if role == Qt.DisplayRole:
            return game.title
        if role == Qt.ToolTipRole:
            return f"{game.path.name}\n{game.status}" + (f" · {game.source}" if game.source else "")
        if role == self.IdRole:
            return game.id
        return None

    def refresh(self) -> bool:
        """Re-read the visible games; returns True when the rows changed."""
        visible = self.library.visible
        if [g.id for g in visible] == [g.id for g in self.games]:
            self.games = visible
            if self.games:
                self.dataChanged.emit(self.index(0), self.index(len(self.games) - 1))
            return False
        self.beginResetModel()
        self.games = visible
        self.endResetModel()
        return True


class CoverDelegate(QStyledItemDelegate):
    def __init__(self, covers: Covers, parent=None):
        super().__init__(parent)
        self.covers = covers
        self.grid = True

    def sizeHint(self, option, index):
        return QSize(176, 236) if self.grid else QSize(200, 58)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        game: Game = index.model().games[index.row()]
        palette = option.palette
        selected = bool(option.state & QStyle.State_Selected)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if self.grid:
            card = rect.adjusted(4, 4, -4, -4)
            if selected:
                fill = QColor(TEAL)
                fill.setAlphaF(0.14)
                border = QColor(TEAL)
                border.setAlphaF(0.6)
                path = QPainterPath()
                path.addRoundedRect(card, 12, 12)
                painter.fillPath(path, fill)
                painter.setPen(border)
                painter.drawPath(path)
            cover = QRect(card.x() + (card.width() - 148) // 2, card.y() + 10, 148, 154)
            paint_cover(painter, cover, self.covers.get(game), palette, True)
            text = QRect(card.x() + 10, cover.bottom() + 9, card.width() - 20, 36)
            font = QFont(option.font)
            font.setWeight(QFont.Medium)
            painter.setFont(font)
            painter.setPen(palette.text().color())
            painter.drawText(text, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._elide_two_lines(painter, game.title, text.width()))
            dot_y = text.bottom() + 12
            painter.setPen(Qt.NoPen)
            painter.setBrush(status_color(game.status, palette))
            painter.drawEllipse(text.x(), dot_y - 3, 6, 6)
            small = QFont(option.font)
            small.setPointSizeF(option.font.pointSizeF() * 0.85)
            painter.setFont(small)
            painter.setPen(palette.placeholderText().color())
            painter.drawText(QRect(text.x() + 11, dot_y - 9, text.width() - 11, 18), Qt.AlignLeft | Qt.AlignVCenter, game.status)
        else:
            if selected:
                painter.fillRect(rect, palette.highlight())
            text_color = palette.highlightedText().color() if selected else palette.text().color()
            secondary = text_color if selected else palette.placeholderText().color()
            cover = QRect(rect.x() + 10, rect.y() + 7, 44, 44)
            paint_cover(painter, cover, self.covers.get(game), palette, False)
            font = QFont(option.font)
            font.setWeight(QFont.Medium)
            status_width = 110
            body = QRect(cover.right() + 12, rect.y() + 8, rect.width() - cover.width() - 40 - status_width, 20)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(body, Qt.AlignLeft | Qt.AlignVCenter, painter.fontMetrics().elidedText(game.title, Qt.ElideRight, body.width()))
            mono = QFont("monospace")
            mono.setStyleHint(QFont.Monospace)
            mono.setPointSizeF(option.font.pointSizeF() * 0.8)
            painter.setFont(mono)
            painter.setPen(secondary)
            detail = game.system.value + (f" · {game.code}" if game.code else "")
            painter.drawText(body.translated(0, 21), Qt.AlignLeft | Qt.AlignVCenter, painter.fontMetrics().elidedText(detail, Qt.ElideRight, body.width()))
            painter.setFont(font)
            painter.setPen(text_color if selected else status_color(game.status, palette))
            painter.drawText(QRect(rect.right() - status_width - 12, rect.y(), status_width, rect.height()), Qt.AlignRight | Qt.AlignVCenter, game.status)
        painter.restore()

    @staticmethod
    def _elide_two_lines(painter, text, width):
        metrics = painter.fontMetrics()
        if metrics.horizontalAdvance(text) <= width * 2 - 10:
            return text
        return metrics.elidedText(text, Qt.ElideRight, width * 2 - 10)


class SettingsDialog(QDialog):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window_ = window
        self.model = window.model
        self.setWindowTitle("Artwork settings")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)
        heading = QLabel("Artwork settings")
        heading.setFont(window.scaled_font(1.5, QFont.Bold))
        layout.addWidget(heading)

        self.form = QWidget()
        form = QFormLayout(self.form)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.normalize = QCheckBox("Normalize filenames when processing")
        self.normalize.setChecked(self.model.normalize_filenames)
        self.normalize.toggled.connect(self.model.set_normalize_filenames)
        form.addRow(self.normalize)
        form.addRow(self.caption("Renames ROMs to uniquely matched artwork titles, keeping their extensions. Off by default. Skips ambiguous matches, existing artwork and playlist-based libraries. Saves a rename log beside the ROMs."))
        self.workers = QComboBox()
        for count in WORKER_CHOICES:
            self.workers.addItem("1 (one at a time)" if count == 1 else str(count), count)
        self.workers.setCurrentIndex(max(0, self.workers.findData(self.model.workers)))
        self.workers.currentIndexChanged.connect(lambda: self.model.set_workers(self.workers.currentData()))
        self.workers.setToolTip("How many games to look up and download at the same time. Lower this if downloads fail or your connection is slow.")
        form.addRow("Parallel downloads", self.workers)
        self.profile = QComboBox()
        for profile in Profile:
            self.profile.addItem(profile.value, profile)
        self.profile.setCurrentIndex(list(Profile).index(self.model.profile))
        self.profile.currentIndexChanged.connect(self.profile_changed)
        form.addRow("Export profile", self.profile)
        self.detail = self.caption("")
        form.addRow(self.detail)
        self.size = QComboBox()
        for size in (128, 256, 512, 1024):
            self.size.addItem(f"{size} px", size)
        self.size.setCurrentIndex(max(0, self.size.findData(self.model.size)))
        self.size.currentIndexChanged.connect(self.size_changed)
        self.size_label = QLabel("Maximum edge")
        form.addRow(self.size_label, self.size)
        self.format = QComboBox()
        self.format.addItems(["PNG", "JPEG"])
        self.format.setCurrentIndex(int(self.model.jpeg))
        self.format.currentIndexChanged.connect(self.format_changed)
        self.format_label = QLabel("Format")
        form.addRow(self.format_label, self.format)
        self.choose = QPushButton("Choose destination…")
        self.choose.clicked.connect(self.choose_destination)
        form.addRow(self.choose)
        self.destination = self.caption("")
        self.destination.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(self.destination)
        self.retroarch_note = self.caption("Created automatically when saving. Set RetroArch’s Settings → Directory → Thumbnails to this folder on your device. You can choose another location above.")
        form.addRow(self.retroarch_note)
        self.playlists = QPushButton("Import .lpl playlists…")
        self.playlists.clicked.connect(self.import_playlists)
        form.addRow(self.playlists)
        self.playlist_count = self.caption("")
        form.addRow(self.playlist_count)
        layout.addWidget(self.form)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        sources = QLabel('Sources: GameTDB for DS game codes; Libretro for all systems. Existing artwork is preserved.<br>'
                         '<a href="https://www.gametdb.com">GameTDB</a> · <a href="https://github.com/libretro-thumbnails/libretro-thumbnails">Libretro</a>')
        sources.setWordWrap(True)
        sources.setOpenExternalLinks(True)
        layout.addWidget(sources)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).setText("Done")
        layout.addWidget(buttons)
        self.update_state()

    @staticmethod
    def caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setForegroundRole(label.foregroundRole())
        font = label.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        label.setFont(font)
        label.setStyleSheet("color: palette(placeholder-text);")
        return label

    def update_state(self):
        profile = self.model.profile
        self.form.setEnabled(not self.model.busy)
        self.detail.setText(profile.detail)
        for widget in (self.size_label, self.size):
            widget.setVisible(profile is not Profile.TWILIGHT)
        for widget in (self.format_label, self.format):
            widget.setVisible(profile is Profile.CUSTOM)
        for widget in (self.choose, self.destination):
            widget.setVisible(profile is not Profile.ANBERNIC)
        destination = self.model.settings.destination
        self.destination.setText(str(destination) if destination else "No destination selected")
        for widget in (self.retroarch_note, self.playlists, self.playlist_count):
            widget.setVisible(profile is Profile.RETROARCH)
        self.playlists.setEnabled(bool(self.model.games))
        self.playlist_count.setText(f"{len(self.model.identities)} playlist labels matched")
        self.adjustSize()

    def profile_changed(self):
        self.model.profile = self.profile.currentData()
        self.model.refresh_existing()
        self.update_state()

    def size_changed(self):
        self.model.size = self.size.currentData()
        self.window_.schedule_refresh()

    def format_changed(self):
        self.model.jpeg = self.format.currentIndex() == 1
        self.model.refresh_existing()

    def choose_destination(self):
        start = str(self.model.settings.destination or self.model.folder)
        folder = choose_directory(self, "Choose the artwork destination (SD root for TWiLight Menu++)", start)
        if folder:
            self.model.set_destination(folder)
            self.update_state()

    def import_playlists(self):
        files = choose_files(self, "Choose RetroArch JSON .lpl playlists", self.model.folder, "RetroArch playlists (*.lpl);;All files (*)", multiple=True)
        if files:
            self.model.import_playlists(files)
            self.update_state()


class Inspector(QScrollArea):
    def __init__(self, window: MainWindow):
        super().__init__()
        self.window_ = window
        self.model = window.model
        self.setWidgetResizable(True)
        self.setFixedWidth(290)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.stack = QStackedWidget()
        self.setWidget(self.stack)

        empty = QLabel("<b>Select a game</b><br>Preview its artwork and export location.")
        empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        empty.setContentsMargins(20, 70, 20, 20)
        empty.setWordWrap(True)
        self.stack.addWidget(empty)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(self.section("ARTWORK PREVIEW"))
        self.cover = QLabel()
        self.cover.setFixedSize(232, 216)
        layout.addWidget(self.cover)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setFont(window.scaled_font(1.2, QFont.Bold))
        layout.addWidget(self.title)
        self.source = SettingsDialog.caption("")
        self.source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.source)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        self.fields = {}
        for name in ("ROM FILE", "OUTPUT", "IMAGE"):
            layout.addWidget(self.section(name))
            value = QLabel()
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(value)
            self.fields[name] = value
        self.find = QPushButton("Find artwork for this game")
        self.find.clicked.connect(lambda: self.model.download(selected_only=True))
        self.import_ = QPushButton("Import image…")
        self.import_.clicked.connect(lambda: window.import_image(None))
        self.show_files = QPushButton("Show in Files")
        self.show_files.clicked.connect(self.show_saved)
        for button in (self.find, self.import_, self.show_files):
            layout.addWidget(button)
        layout.addStretch()
        self.stack.addWidget(page)

    @staticmethod
    def section(text):
        label = QLabel(text)
        font = label.font()
        font.setPointSizeF(font.pointSizeF() * 0.8)
        font.setWeight(QFont.DemiBold)
        label.setFont(font)
        label.setStyleSheet("color: palette(placeholder-text);")
        return label

    def show_saved(self):
        if (game := self.model.selected) and game.saved_path:
            show_in_file_manager(game.saved_path)

    def refresh(self):
        game = self.model.selected
        self.stack.setCurrentIndex(0 if game is None else 1)
        if game is None:
            return
        pixmap = QPixmap(self.cover.size() * self.devicePixelRatioF())
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        paint_cover(painter, QRect(0, 0, 232, 216), self.window_.covers.get(game), self.palette(), True)
        painter.end()
        self.cover.setPixmap(pixmap)
        self.title.setText(game.title)
        self.source.setText(game.source or "Find artwork to preview the matching cover before saving it to your card.")
        settings = self.model.settings
        self.fields["ROM FILE"].setText(game.path.name)
        try:
            output = str(settings.output(game.path))
        except Exception:
            output = "Choose a destination"
        self.fields["OUTPUT"].setText(output)
        if settings.profile is Profile.TWILIGHT:
            image = "PNG · fits within 128 × 115"
        else:
            image = f"{'JPEG' if settings.jpeg and settings.profile is Profile.CUSTOM else 'PNG'} · up to {settings.max_size} px · preserves proportions"
        self.fields["IMAGE"].setText(image)
        unsaved = game.saved_path is None
        self.find.setVisible(unsaved)
        self.import_.setVisible(unsaved)
        self.show_files.setVisible(not unsaved)
        self.find.setEnabled(not self.model.busy and game.status != "Ready")
        self.import_.setEnabled(not self.model.busy)


class MainWindow(QMainWindow):
    def __init__(self, model: LibraryModel):
        super().__init__()
        self.model = model
        self.covers = Covers()
        self.settings_dialog: SettingsDialog | None = None
        self._syncing = False
        self.setWindowTitle("BoxArt")
        self.setMinimumSize(1020, 680)
        self.resize(1240, 800)
        self._refresh_timer = QTimer(self, singleShot=True, interval=30, timeout=self.refresh)

        self.build_toolbar()
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_sidebar())
        splitter.addWidget(self.build_detail())
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1000])
        self.setCentralWidget(splitter)
        self.build_actions()

        model.changed.connect(self.schedule_refresh)
        model.status_changed.connect(self.schedule_refresh)
        model.error_raised.connect(self.show_error)
        self.refresh()

    def scaled_font(self, factor: float, weight=QFont.Normal) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(font.pointSizeF() * factor)
        font.setWeight(weight)
        return font

    # Construction

    def build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search games")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self.query_changed)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(self.search)
        toolbar.addSeparator()
        group = QButtonGroup(self)
        self.grid_button = QToolButton(checkable=True, checked=True, toolTip="Grid")
        self.grid_button.setIcon(icon("view-grid", QStyle.SP_FileDialogContentsView))
        self.list_button = QToolButton(checkable=True, toolTip="List")
        self.list_button.setIcon(icon("view-list-details", QStyle.SP_FileDialogDetailedView))
        for button in (self.grid_button, self.list_button):
            group.addButton(button)
            toolbar.addWidget(button)
        self.grid_button.toggled.connect(self.set_grid)
        self.inspector_button = QToolButton(checkable=True, toolTip="Show artwork details")
        self.inspector_button.setIcon(icon("sidebar-show-right", QStyle.SP_FileDialogInfoView))
        self.inspector_button.toggled.connect(lambda on: self.inspector.setVisible(on))
        toolbar.addWidget(self.inspector_button)
        settings = QToolButton(toolTip="Artwork settings (Ctrl+,)")
        settings.setIcon(icon("configure", QStyle.SP_FileDialogListView))
        settings.clicked.connect(self.open_settings)
        toolbar.addWidget(settings)

    def build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(200)
        sidebar.setMaximumWidth(300)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        brand = QLabel()
        brand.setText(f'<img src="{ICON_PATH}" width="28" height="28" style="vertical-align: middle"> &nbsp;<b>BoxArt</b>')
        brand.setFont(self.scaled_font(1.4))
        brand.setContentsMargins(18, 16, 18, 12)
        layout.addWidget(brand)
        self.systems = QListWidget()
        self.systems.setFrameShape(QFrame.NoFrame)
        self.systems.setSpacing(1)
        self.systems.itemClicked.connect(self.system_clicked)
        layout.addWidget(self.systems, 1)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 14, 18, 18)
        title = QLabel("ROM library")
        title.setFont(self.scaled_font(1.0, QFont.Medium))
        self.folder_label = SettingsDialog.caption("")
        self.folder_label.setWordWrap(False)
        self.choose_button = QPushButton("Choose folder…")
        self.choose_button.clicked.connect(self.choose_folder)
        for widget in (title, self.folder_label, self.choose_button):
            footer_layout.addWidget(widget)
        layout.addWidget(footer)
        return sidebar

    def build_detail(self) -> QWidget:
        detail = QWidget()
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 14)
        header_layout.setSpacing(12)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.heading = QLabel()
        self.heading.setFont(self.scaled_font(2.0, QFont.Bold))
        self.subheading = SettingsDialog.caption("")
        titles.addWidget(self.heading)
        titles.addWidget(self.subheading)
        top.addLayout(titles, 1)
        self.rescan_button = QToolButton(toolTip="Rescan library (Ctrl+R)")
        self.rescan_button.setIcon(icon("view-refresh", QStyle.SP_BrowserReload))
        self.rescan_button.clicked.connect(self.model.scan)
        top.addWidget(self.rescan_button)
        self.all_button = QPushButton("Download && save all")
        self.all_button.setToolTip("Find and save all missing covers across the entire scanned library")
        self.all_button.setStyleSheet(f"QPushButton {{ background: {TEAL.name()}; color: white; border: none; border-radius: 6px; padding: 7px 16px; font-weight: 600; }}"
                                      f"QPushButton:hover {{ background: {TEAL.darker(110).name()}; }} QPushButton:disabled {{ background: palette(mid); color: palette(light); }}")
        self.all_button.clicked.connect(self.model.download_and_save_all)
        top.addWidget(self.all_button)
        header_layout.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.filter_buttons = {}
        filters = QButtonGroup(self)
        for name in FILTERS:
            button = QToolButton(checkable=True)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setIcon(icon(FILTER_ICONS[name]))
            button.setAutoRaise(True)
            button.setToolTip("Downloaded or imported covers that have not been saved. Unsaved previews are lost when the app closes."
                              if name == "Ready to save" else f"Show {name.lower()} in the current system and search")
            button.setStyleSheet(f"QToolButton {{ padding: 5px 10px; border-radius: 8px; border: 1px solid transparent; }}"
                                 f"QToolButton:checked {{ background: rgba({TEAL.red()},{TEAL.green()},{TEAL.blue()},0.14); border-color: rgba({TEAL.red()},{TEAL.green()},{TEAL.blue()},0.5); font-weight: 600; }}")
            button.clicked.connect(lambda _=False, n=name: self.filter_changed(n))
            filters.addButton(button)
            row.addWidget(button)
            self.filter_buttons[name] = button
        self.filter_buttons["All games"].setChecked(True)
        row.addStretch()
        self.selected_button = QPushButton()
        self.selected_button.setToolTip("Download and save artwork only for the selected games")
        self.selected_button.clicked.connect(self.model.get_for_selected)
        row.addWidget(self.selected_button)
        self.more_button = QToolButton(toolTip="More")
        self.more_button.setIcon(icon("overflow-menu", QStyle.SP_TitleBarUnshadeButton))
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more_button)
        menu.addAction("Download previews only", lambda: self.model.download())
        self.save_ready_action = menu.addAction("Save ready covers", lambda: self.model.save())
        self.more_button.setMenu(menu)
        row.addWidget(self.more_button)
        header_layout.addLayout(row)

        self.banner = QWidget()
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(0, 0, 0, 0)
        banner_icon = QLabel()
        banner_icon.setPixmap(icon("document-save", QStyle.SP_DialogSaveButton).pixmap(18, 18))
        banner_layout.addWidget(banner_icon)
        banner_layout.addWidget(SettingsDialog.caption("Covers in memory, not yet saved to your artwork folder."), 1)
        self.save_visible_button = QPushButton("Save these covers")
        self.save_visible_button.clicked.connect(lambda: self.model.save({g.id for g in self.model.visible}))
        banner_layout.addWidget(self.save_visible_button)
        header_layout.addWidget(self.banner)
        layout.addWidget(header)
        layout.addWidget(self.hline())

        body = QHBoxLayout()
        body.setSpacing(0)
        self.center = QStackedWidget()
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.center.addWidget(self.empty)
        self.list_model = GameListModel(self.model)
        self.delegate = CoverDelegate(self.covers, self)
        self.view = QListView()
        self.view.setModel(self.list_model)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.view.selectionModel().selectionChanged.connect(self.view_selection_changed)
        self.view.doubleClicked.connect(lambda: self.inspector_button.setChecked(True))
        self.center.addWidget(self.view)
        body.addWidget(self.center, 1)
        self.inspector = Inspector(self)
        self.inspector.setVisible(False)
        body.addWidget(self.inspector)
        layout.addLayout(body, 1)
        layout.addWidget(self.hline())

        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 8, 14, 8)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(110)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.message = SettingsDialog.caption("")
        self.message.setWordWrap(False)
        self.message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.model.stop)
        self.count_label = SettingsDialog.caption("")
        bottom.addWidget(self.progress)
        bottom.addWidget(self.message, 1)
        bottom.addWidget(self.stop_button)
        bottom.addWidget(self.count_label)
        layout.addLayout(bottom)
        self.set_grid(True)
        return detail

    @staticmethod
    def hline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def build_actions(self):
        for text, shortcut, slot in (("Open ROM Folder…", QKeySequence.Open, self.choose_folder),
                                     ("Scan Library", QKeySequence("Ctrl+R"), self.model.scan),
                                     ("Settings…", QKeySequence("Ctrl+,"), self.open_settings),
                                     ("Search", QKeySequence.Find, lambda: self.search.setFocus()),
                                     ("Quit", QKeySequence.Quit, self.close)):
            action = QAction(text, self, shortcut=shortcut)
            action.triggered.connect(slot)
            self.addAction(action)

    # Events

    def schedule_refresh(self):
        self._refresh_timer.start()

    def show_error(self, text: str):
        QMessageBox.warning(self, "BoxArt", text)
        self.model.error = None

    def set_grid(self, grid: bool):
        self.delegate.grid = grid
        if grid:
            self.view.setViewMode(QListView.IconMode)
            self.view.setFlow(QListView.LeftToRight)
            self.view.setGridSize(QSize(180, 240))
            self.view.setSpacing(0)
            self.view.setContentsMargins(18, 18, 18, 18)
        else:
            self.view.setViewMode(QListView.ListMode)
            self.view.setFlow(QListView.TopToBottom)
            self.view.setGridSize(QSize())
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setWrapping(grid)
        self.view.setUniformItemSizes(True)
        self.view.doItemsLayout()

    def query_changed(self, text: str):
        self.model.query = text
        self.model.prune_selection()
        self.refresh()

    def filter_changed(self, name: str):
        self.model.filter = name
        self.model.prune_selection()
        self.refresh()

    def system_clicked(self, item: QListWidgetItem):
        self.model.system_filter = item.data(Qt.UserRole)
        self.model.prune_selection()
        self.refresh()

    def view_selection_changed(self, *_):
        if self._syncing:
            return
        ids = {index.data(GameListModel.IdRole) for index in self.view.selectionModel().selectedIndexes()}
        current = self.view.currentIndex()
        self.model.set_list_selection(ids, current.data(GameListModel.IdRole) if current.isValid() else None)
        self.schedule_refresh()

    def sync_view_selection(self):
        self._syncing = True
        try:
            selection = QItemSelection()
            for row, game in enumerate(self.list_model.games):
                if game.id in self.model.selected_ids:
                    index = self.list_model.index(row)
                    selection.select(index, index)
            self.view.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)
        finally:
            self._syncing = False

    def choose_folder(self):
        if self.model.busy:
            return
        folder = choose_directory(self, "Choose your Roms folder or an individual system folder", self.model.folder)
        if folder:
            self.model.set_folder(str(folder))

    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.update_state()
        self.settings_dialog.show()
        self.settings_dialog.raise_()

    def import_image(self, id: str | None):
        files = choose_files(self, "Import cover image", Path.home() / "Pictures", "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp *.bmp *.gif)")
        if files:
            self.model.import_image(files[0], id)

    def context_menu(self, position):
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        game = self.list_model.games[index.row()]
        if game.id not in self.model.selected_ids:
            self.view.selectionModel().select(index, QItemSelectionModel.ClearAndSelect)
            self.view.setCurrentIndex(index)
        busy = self.model.busy
        menu = QMenu(self)
        menu.addAction(icon("folder-open", QStyle.SP_DirOpenIcon), "Show in Files", lambda: show_in_file_manager(game.saved_path or game.path))
        if game.saved_path is not None:
            menu.addAction(icon("document-open", QStyle.SP_FileIcon), "Show ROM in Files", lambda: show_in_file_manager(game.path))
        menu.addAction(icon("documentinfo", QStyle.SP_FileDialogInfoView), "Show Info", lambda: self.show_info(game.id))
        menu.addSeparator()
        menu.addAction(icon("edit-find", QStyle.SP_FileDialogContentsView), "Find Image", lambda: self.model.download(ids={game.id})).setEnabled(
            not busy and game.saved_path is None and game.status != "Ready")
        menu.addAction(icon("internet-web-browser", QStyle.SP_DriveNetIcon), "Search Images Online…", lambda: search_online(game))
        menu.addAction(icon("document-import", QStyle.SP_DialogOpenButton), "Import Image…", lambda: self.import_image(game.id)).setEnabled(
            not busy and game.saved_path is None)
        menu.addAction(icon("document-save", QStyle.SP_DialogSaveButton), "Save Image", lambda: self.model.save({game.id})).setEnabled(
            not busy and game.status == "Ready")
        menu.exec(self.view.viewport().mapToGlobal(position))

    def show_info(self, id: str):
        self.model.select(id)
        self.sync_view_selection()
        self.inspector_button.setChecked(True)

    def closeEvent(self, event):
        self.model.stop()
        self.model.wait(3)
        super().closeEvent(event)

    # Rendering

    def refresh(self):
        model = self.model
        busy = model.busy

        system = model.system_filter
        self.systems.blockSignals(True)
        self.systems.clear()
        all_item = QListWidgetItem(icon("view-grid", QStyle.SP_DirIcon), f"All games  ({len(model.games)})")
        all_item.setData(Qt.UserRole, None)
        self.systems.addItem(all_item)
        counts = {}
        for game in model.games:
            counts[game.system] = counts.get(game.system, 0) + 1
        if counts:
            header = QListWidgetItem("SYSTEMS")
            header.setFlags(Qt.NoItemFlags)
            header.setFont(Inspector.section("").font())
            self.systems.addItem(header)
        for candidate in GameSystem:
            if candidate in counts:
                item = QListWidgetItem(icon("input-gaming", QStyle.SP_ComputerIcon), f"{candidate.short_name}  ({counts[candidate]})")
                item.setData(Qt.UserRole, candidate)
                item.setToolTip(candidate.value)
                self.systems.addItem(item)
        for row in range(self.systems.count()):
            item = self.systems.item(row)
            if item.flags() & Qt.ItemIsSelectable and item.data(Qt.UserRole) == system:
                item.setSelected(True)
        self.systems.blockSignals(False)
        self.folder_label.setText(self.folder_label.fontMetrics().elidedText(model.folder, Qt.ElideMiddle, 250))
        self.folder_label.setToolTip(model.folder)
        self.choose_button.setEnabled(not busy)

        visible_count = len(model.visible)
        self.heading.setText(system.short_name if system else "All games")
        self.subheading.setText(f"{visible_count} games · {model.profile.value}")
        self.rescan_button.setEnabled(not busy)
        self.all_button.setEnabled(not busy and bool(model.games))
        for name, button in self.filter_buttons.items():
            button.setText(f"{FILTER_TITLES[name]}  {model.filter_count(name):,}")
        self.selected_button.setVisible(bool(model.selected_ids))
        self.selected_button.setText(f"Get for selected ({len(model.selected_ids)})")
        self.selected_button.setEnabled(not busy)
        self.more_button.setEnabled(not busy)
        self.save_ready_action.setText(f"Save {model.ready} ready covers")
        self.save_ready_action.setEnabled(model.ready > 0)
        self.banner.setVisible(model.filter == "Ready to save")
        self.save_visible_button.setEnabled(not busy and visible_count > 0)

        if self.list_model.refresh():
            self.sync_view_selection()
        elif {g.id for g in self.list_model.games if g.id in model.selected_ids} != {i.data(GameListModel.IdRole) for i in self.view.selectionModel().selectedIndexes()}:
            self.sync_view_selection()
        if not model.games:
            self.empty.setText("<h2>Bring your games to life</h2><p>Choose your Roms folder to scan DS, GBA, PlayStation and more.</p>")
        else:
            self.empty.setText("<h2>No games here</h2><p>Try another filter or search.</p>")
        self.center.setCurrentIndex(1 if visible_count else 0)
        self.view.viewport().update()
        self.inspector.refresh()
        if self.settings_dialog is not None and self.settings_dialog.isVisible():
            self.settings_dialog.form.setEnabled(not busy)

        self.progress.setVisible(busy)
        self.progress.setValue(int(model.progress * 1000))
        self.message.setText(model.message)
        self.stop_button.setVisible(busy)
        self.count_label.setText(f"{model.saved} / {len(model.games)} saved")


def desktop_entry_installed() -> bool:
    """Whether the .desktop file is installed; the portal rejects unknown app IDs."""
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return any(Path(d, "applications", f"{APP_ID}.desktop").is_file() for d in [data_home, *data_dirs] if d)


def main(argv: list[str] | None = None) -> int:
    configure_platform_theme()
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("BoxArt")
    app.setApplicationDisplayName("BoxArt")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("BoxArt")
    if desktop_entry_installed():
        app.setDesktopFileName(APP_ID)
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(ICON_PATH))))
    window = MainWindow(LibraryModel())
    window.show()
    window.model.scan()
    return app.exec()
