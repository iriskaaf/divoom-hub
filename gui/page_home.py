from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget, FluentIcon, IconWidget, PlainTextEdit,
                            PushButton, StrongBodyLabel, SubtitleLabel)

from core.models import TrackInfo
from core.settings import APP_DIR, Settings
from core.version import APP_NAME
from timesgate.engine import TimesGateEngine

from .widgets import Page, PixelPreview, ThemeSwitcher, show


def status_text(connected: bool, text: str) -> str:
    return ("● " if connected else "○ ") + text


class StatusCard(CardWidget):
    """Clickable dashboard card: icon + title + status line, content below."""

    def __init__(self, icon, title: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 16, 20, 18)
        self.root.setSpacing(12)
        head = QHBoxLayout()
        ic = IconWidget(icon)
        ic.setFixedSize(18, 18)
        head.addWidget(ic)
        head.addSpacing(8)
        head.addWidget(StrongBodyLabel(title))
        head.addStretch()
        self.status = CaptionLabel("—")
        head.addWidget(self.status)
        self.root.addLayout(head)


class HomePage(Page):
    def __init__(self, settings: Settings, tg: TimesGateEngine, parent=None):
        super().__init__("home", APP_NAME, "Ваши устройства и текущая музыка.", parent)
        self.settings, self.tg = settings, tg

        # now playing / Ditoo
        self.ditoo_card = StatusCard(FluentIcon.MUSIC, "Сейчас играет")
        body = QHBoxLayout()
        body.setSpacing(18)
        self.cover = PixelPreview(144)
        body.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.track = SubtitleLabel("Ничего не играет")
        self.artist = BodyLabel("")
        self.album = CaptionLabel("")
        self.album.setTextColor("#707070", "#9a9a9a")
        self.spotify_state = CaptionLabel("")
        for w in (self.track, self.artist, self.album):
            w.setWordWrap(True)
            w.setTextFormat(Qt.TextFormat.PlainText)
            text.addWidget(w)
        text.addStretch()
        text.addWidget(self.spotify_state)
        body.addLayout(text, 1)
        self.ditoo_card.root.addLayout(body)
        self.ditoo_card.setMinimumHeight(224)
        self.add(self.ditoo_card)
        self.layout_.addSpacing(8)

        # Times Gate
        self.tg_card = StatusCard(FluentIcon.DATE_TIME, "Times Gate")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.tiles = [PixelPreview(76) for _ in range(5)]
        for t in self.tiles:
            row.addWidget(t)
        row.addStretch()
        self.tg_card.root.addLayout(row)
        themes = QHBoxLayout()
        themes.addWidget(BodyLabel("Тема:"))
        self.switcher = ThemeSwitcher(lambda step: tg.switch_theme(step))
        self.switcher.set_name(tg.current_theme()["name"])
        themes.addWidget(self.switcher)
        themes.addStretch()
        self.tg_card.root.addLayout(themes)
        self.add(self.tg_card)
        self.empty = StatusCard(FluentIcon.CONNECT, "Добавьте ваше устройство")
        self.empty.status.setText("Первый запуск")
        message = BodyLabel("Выберите Ditoo Pro или Times Gate и пройдите подключение по шагам.")
        message.setWordWrap(True)
        self.empty.root.addWidget(message)
        setup = PushButton(FluentIcon.ADD, "Выбрать устройства")
        setup.clicked.connect(lambda: self.window().open_setup())
        self.empty.root.addWidget(setup)
        self.add(self.empty)
        self.update_visibility()

    def update_visibility(self) -> None:
        show(self.empty, not self.settings.ditoo_enabled and not self.settings.timesgate_enabled)
        show(self.switcher, self.settings.tg_mode in ("clock", "gifs_clock"))
        show(self.ditoo_card, self.settings.ditoo_enabled)
        show(self.tg_card, bool(self.settings.timesgate_enabled and self.settings.tg_ip and self.settings.tg_token))

    def on_event(self, name: str, payload) -> None:
        if name == "ditoo":
            self.ditoo_card.status.setText("Ditoo " + status_text(*payload))
        elif name == "spotify":
            self.spotify_state.setText(f"Музыка: {payload}")
        elif name == "display":
            self.cover.set_image(payload)
        elif name == "track":
            self.show_track(payload)
        elif name == "tg":
            self.tg_card.status.setText(status_text(*payload))
            self.update_visibility()
        elif name == "tg_mode":
            self.update_visibility()
        elif name == "tg_preview":
            images, theme = payload
            for tile, img in zip(self.tiles, images):
                tile.set_image(img)
            self.switcher.set_name(theme)

    def show_track(self, track: TrackInfo | None) -> None:
        if track is None:
            self.cover.set_image(None)
            self.track.setText("Ничего не играет")
            self.artist.setText("")
            self.album.setText("")
            return
        icon = "▶  " if track.is_playing else "⏸  "
        self.track.setText(icon + track.track_name)
        self.artist.setText(track.artist_name)
        self.album.setText(track.album_name)


class LogPage(Page):
    def __init__(self, parent=None):
        super().__init__("log", "Журнал", "Последние события. Полный журнал — в папке логов.", parent)
        self.view_ = PlainTextEdit()
        self.view_.setReadOnly(True)
        self.view_.setMinimumHeight(460)
        self.view_.document().setMaximumBlockCount(1000)
        self.add(self.view_)
        open_btn = PushButton(FluentIcon.FOLDER, "Открыть папку логов")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR / "logs"))))
        self.add(open_btn)

    def append(self, line: str) -> None:
        self.view_.appendPlainText(line)
