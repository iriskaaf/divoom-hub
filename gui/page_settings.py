"""Settings: where the track comes from, startup, appearance, data folder."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from qfluentwidgets import FluentIcon, LineEdit, PrimaryPushButton, PushButton, InfoBar

from core import autostart
from core.player import TRACK_SOURCES, Engine
from core.settings import APP_DIR, Settings
from core.profile import TEST_MODE
from core.spotify import REDIRECT_URI

from .widgets import ChoiceTile, StableGroup, Page, card, combo, show, switch
from .assets import tile_icon


class SettingsPage(Page):
    def __init__(self, settings: Settings, engine: Engine, on_theme, parent=None):
        super().__init__("settings", "Настройки", "", parent)
        self.settings, self.engine = settings, engine

        # ---- music source ------------------------------------------------------------
        self.music_group = g = self.group("Музыка")
        self.source_combo = combo(TRACK_SOURCES, settings.track_source, self.commit_source, 270)
        for index, source in enumerate(TRACK_SOURCES):
            self.source_combo.setItemIcon(index, tile_icon(source))
        self.source_card = card(FluentIcon.MUSIC, "Откуда брать трек и обложку",
                              "Web API нужен, только если музыка играет на телефоне",
                              self.source_combo)
        g.addSettingCard(self.source_card)
        self.status_card = card(FluentIcon.INFO, "Состояние", "—")
        g.addSettingCard(self.status_card)
        self.only_spotify_card = card(FluentIcon.FILTER, "Только Spotify",
                                      "Выключено — подойдёт любой плеер: браузер, Яндекс Музыка и т. д.",
                                      switch(settings.media_only_spotify, self.commit_only_spotify))
        g.addSettingCard(self.only_spotify_card)
        uri = LineEdit()
        uri.setText(REDIRECT_URI)
        uri.setReadOnly(True)
        uri.setMinimumWidth(260)
        copy = PushButton(FluentIcon.COPY, "Копировать")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(REDIRECT_URI))
        self.uri_card = card(FluentIcon.LINK, "Redirect URI",
                             "Вставьте в приложение на developer.spotify.com", uri, copy)
        g.addSettingCard(self.uri_card)
        self.client_id = LineEdit()
        self.client_id.setText(settings.spotify_client_id)
        self.client_id.setPlaceholderText("Client ID из developer.spotify.com")
        self.client_id.setMinimumWidth(320)
        self.client_id.editingFinished.connect(self.commit_client_id)
        self.client_card = card(FluentIcon.FINGERPRINT, "Client ID", "Client Secret не нужен", self.client_id)
        g.addSettingCard(self.client_card)
        self.login_btn = PrimaryPushButton("Войти в Spotify")
        self.login_btn.clicked.connect(self.toggle_login)
        self.account_card = card(FluentIcon.PEOPLE, "Аккаунт", "—", self.login_btn)
        g.addSettingCard(self.account_card)
        self.show_artwork = switch(settings.show_artwork, self.commit_show_artwork)
        self.tracking_card = card(FluentIcon.ALBUM, "Следить за музыкой",
                              "Обложка на Ditoo и цвет обложки для Times Gate", self.show_artwork)
        g.addSettingCard(self.tracking_card)
        from PySide6.QtWidgets import QFrame
        self.music_separator = QFrame()
        self.music_separator.setFixedHeight(1)
        self.music_separator.setStyleSheet("background: rgba(128,128,128,70);")
        for widget in (self.tracking_card, self.status_card, self.source_card, self.only_spotify_card, self.uri_card, self.client_card, self.account_card):
            g.cardLayout.removeWidget(widget)
        for widget in (self.tracking_card, self.status_card, self.music_separator, self.source_card, self.only_spotify_card, self.uri_card, self.client_card, self.account_card):
            g.cardLayout.addWidget(widget)

        # ---- startup ---------------------------------------------------------------
        g = self.group("Запуск", collapsible=False)
        self.autostart = switch(autostart.is_enabled(), self.commit_autostart)
        self.autostart.setEnabled(not TEST_MODE)
        g.addSettingCard(card(FluentIcon.POWER_BUTTON, "Запускать вместе с Windows",
                              ("В тестовой версии отключено: автозапуск основной программы не меняется" if TEST_MODE else
                               "Стартует свёрнутой в трей. «Закрыть» тоже сворачивает в трей, выход — правый клик по иконке"), self.autostart))

        # ---- appearance / data ---------------------------------------------------------
        g = self.group("Внешний вид", collapsible=False)
        g.addSettingCard(card(FluentIcon.CONSTRACT, "Тема оформления", "",
                              combo({"auto": "Как в Windows", "dark": "Тёмная", "light": "Светлая"},
                                    settings.ui_theme, on_theme, 180)))
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        self.devices_group = StableGroup("Устройства", self.view)
        self.layout_.insertWidget(2, self.devices_group)
        self.connection_tiles = {}
        devices = QWidget()
        row = QHBoxLayout(devices)
        row.setContentsMargins(0, 0, 0, 0)
        for key, title in (("ditoo", "Ditoo Pro"), ("timesgate", "Times Gate")):
            tile = ChoiceTile(title, "Не подключено · настроить", artwork=tile_icon(key), artwork_height=60)
            tile.setFixedSize(160, 160)
            tile.layout().setContentsMargins(12, 12, 12, 12)
            tile.setChecked(True)
            tile.outline_color = QColor("#C42B1C")
            tile.clicked.connect(lambda key=key: self.window().open_connection(key))
            row.addWidget(tile)
            self.connection_tiles[key] = tile
        self.add_device_tile = ChoiceTile("+", "Добавить устройство")
        self.add_device_tile.setFixedSize(160, 160)
        self.add_device_tile.clicked.connect(lambda: self.window().open_setup(adding=True))
        row.addWidget(self.add_device_tile)
        row.addStretch()
        self.devices_group.addSettingCard(devices)
        g = self.group("Для разработчиков", collapsible=False)
        g.addSettingCard(card(FluentIcon.DEVELOPER_TOOLS, "Режим разработчика",
                              "Журнал, ручные тесты Ditoo и ревизия Times Gate",
                              switch(settings.developer_mode, self.commit_developer)))
        logs = PushButton(FluentIcon.HISTORY, "Открыть журнал")
        logs.clicked.connect(lambda: self.window().open_log())
        self.logs_card = card(FluentIcon.HISTORY, "Журнал событий", "Для диагностики подключения", logs)
        g.addSettingCard(self.logs_card)
        self.data_group = g = self.group("Данные", collapsible=False)
        open_btn = PushButton(FluentIcon.FOLDER, "Открыть")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR))))
        self.data_card = card(FluentIcon.FOLDER, "Папка программы",
                              "Настройки, кэш обложек, паки Times Gate и логи", open_btn)
        g.addSettingCard(self.data_card)
        self.on_login(engine.logged_in)

    # ---- music source ------------------------------------------------------------

    def update_visibility(self) -> None:
        self.source_card.iconLabel.setIcon(tile_icon(self.settings.track_source))
        show(self.connection_tiles["ditoo"], self.settings.ditoo_enabled)
        show(self.connection_tiles["timesgate"], self.settings.timesgate_enabled)
        show(self.logs_card, self.settings.developer_mode)
        show(self.data_group, self.settings.developer_mode)
        api = self.settings.track_source == "api"
        logged_in = self.engine.logged_in
        show(self.only_spotify_card, not api)
        show(self.account_card, api)
        # app registration is needed only to sign in
        show(self.uri_card, api and not logged_in)
        show(self.client_card, api and not logged_in)
        self.layout_.invalidate()
        self.view.updateGeometry()

    def commit_developer(self, value: bool):
        self.settings.developer_mode = value
        self.settings.save()
        self.update_visibility()
        for destination in (self.window().ditoo, self.window().timesgate):
            if destination.page is not None:
                destination.page.update_visibility()

    def commit_source(self, value: str) -> None:
        self.settings.track_source = value
        self.settings.save()
        self.status_card.setContent("…")
        self.engine.wake_spotify()
        self.update_visibility()

    def commit_only_spotify(self, value: bool) -> None:
        self.settings.media_only_spotify = value
        self.settings.save()
        self.engine.wake_spotify()

    def commit_client_id(self) -> None:
        value = self.client_id.text().strip()
        if value != self.settings.spotify_client_id:
            self.settings.spotify_client_id = value
            self.settings.save()
            self.engine.wake_spotify()

    def toggle_login(self) -> None:
        if self.engine.logged_in:
            self.engine.spotify_logout()
            return
        self.commit_client_id()
        if not self.settings.spotify_client_id:
            self.account_card.setContent("Сначала введите Client ID")
            return
        self.engine.spotify_login()

    def commit_show_artwork(self, value: bool) -> None:
        self.window().set_tracking(value)

    def commit_autostart(self, value: bool) -> None:
        try:
            autostart.set_enabled(value)
        except OSError as error:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(autostart.is_enabled())
            self.autostart.blockSignals(False)
            InfoBar.error("Автозапуск не изменён", str(error), parent=self.window(), duration=5000)

    def on_login(self, logged_in: bool) -> None:
        self.login_btn.setText("Выйти" if logged_in else "Войти в Spotify")
        self.account_card.setContent("Вход выполнен" if logged_in else "Не выполнен вход")
        self.update_visibility()

    def on_event(self, name: str, payload) -> None:
        if name in ("ditoo", "tg"):
            tile = self.connection_tiles["ditoo" if name == "ditoo" else "timesgate"]
            tile.detail.setText("Подключено · настроить" if payload[0] else "Не подключено · настроить")
            tile.outline_color = QColor("#6CCB5F" if payload[0] else "#C42B1C")
            tile.update()
        elif name == "login":
            self.on_login(bool(payload))
        elif name == "spotify":
            self.status_card.setContent(str(payload))
