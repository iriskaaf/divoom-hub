"""First-run device selection and guided connection using the real settings pages."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SubtitleLabel, isDarkTheme
from .widgets import ChoiceTile
from .assets import tile_icon


class SetupPage(QWidget):
    finished = Signal(int)
    def __init__(self, window, *, adding=False):
        super().__init__(window)
        self.host = window
        self.adding = adding
        self._existing_ditoo = bool(window.settings.ditoo_enabled)
        self._existing_tg = bool(window.settings.timesgate_enabled)
        self._device_snapshot = {name: getattr(window.settings,name) for name in ("ditoo_enabled","ditoo_address","ditoo_port","timesgate_enabled","tg_ip","tg_token","tg_mac","tg_hardware")}
        self._connections = []
        self._confirmed = {}
        for key, payload in getattr(window, "_last_events", {}).items():
            if key in ("ditoo", "tg") and payload[0]:
                self._confirmed[key] = self.connection_key(key)
        self.connect_events(self.connection_event)
        self.finished.connect(self.cleanup)
        self.setObjectName("setup")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)
        self.title = SubtitleLabel("Добро пожаловать в Divoom Hub")
        root.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        start = QWidget()
        layout = QVBoxLayout(start)
        message = BodyLabel("Выберите ваши устройства. Подключим их по шагам. Выбор можно изменить в настройках.")
        message.setWordWrap(True)
        if adding:
            self.title.setText("Добавить устройство")
            message.setText("Выберите новое устройство. Уже подключённые устройства останутся в программе.")
        layout.addWidget(message)
        self.ditoo = ChoiceTile("Ditoo Pro", "Bluetooth · обложки музыки", artwork=tile_icon("ditoo"))
        self.tg = ChoiceTile("Times Gate", "Wi-Fi · часы и подсветка", artwork=tile_icon("timesgate"))
        for tile in (self.ditoo, self.tg):
            tile.setFixedSize(240, 240)
            tile.clicked.connect(lambda tile=tile: tile.setChecked(not tile.isChecked()))
        s = window.settings
        self.ditoo.setChecked(s.ditoo_enabled if s.onboarding_completed else bool(s.ditoo_address))
        self.tg.setChecked(s.timesgate_enabled if s.onboarding_completed else bool(s.tg_ip))
        if adding:
            self.ditoo.setChecked(self._existing_ditoo)
            self.tg.setChecked(self._existing_tg)
            self.ditoo.setEnabled(not self._existing_ditoo)
            self.tg.setEnabled(not self._existing_tg)
        layout.addStretch()
        choices = QHBoxLayout()
        choices.addStretch()
        choices.addWidget(self.tg)
        choices.addWidget(self.ditoo)
        choices.addStretch()
        layout.addLayout(choices)
        layout.addStretch()
        self.stack.addWidget(start)
        buttons = QHBoxLayout()
        self.back = PushButton("Назад")
        self.back.clicked.connect(self.previous)
        buttons.addWidget(self.back)
        buttons.addStretch()
        self.cancel = PushButton("Отмена")
        self.cancel.setVisible(adding)
        self.cancel.clicked.connect(self.reject)
        buttons.addWidget(self.cancel)
        self.skip = PushButton("Пропустить")
        self.skip.clicked.connect(self.skip_devices)
        buttons.addWidget(self.skip)
        self.next = PrimaryPushButton("Продолжить")
        self.next.clicked.connect(self.advance)
        buttons.addWidget(self.next)
        root.addLayout(buttons)
        self.steps = []
        self.index = -1
        self.back.hide()
        for tile in (self.ditoo, self.tg):
            tile.clicked.connect(self.update_continue)
        self.update_continue()

    def connection_key(self, name):
        s = self.host.settings
        return (s.tg_ip, s.tg_token, s.tg_hardware) if name == "tg" else s.ditoo_address

    def connection_event(self, name, payload):
        if name not in ("ditoo", "tg"):
            return
        if payload[0]:
            self._confirmed[name] = self.connection_key(name)
        else:
            self._confirmed.pop(name, None)
        if hasattr(self, "next"):
            self.update_continue()

    def can_continue(self):
        if self.index < 0:
            if self.adding:
                return (self.ditoo.isChecked() and not self._existing_ditoo) or (self.tg.isChecked() and not self._existing_tg)
            return self.ditoo.isChecked() or self.tg.isChecked()
        step = self.steps[self.index]
        if step == "music":
            return True
        name = "tg" if step == "timesgate" else "ditoo"
        return name in self._confirmed and self._confirmed[name] == self.connection_key(name)

    def update_continue(self):
        self.next.setEnabled(self.can_continue())

    def skip_devices(self):
        self.ditoo.setChecked(False)
        self.tg.setChecked(False)
        self.advance()

    @staticmethod
    def plain_connection(editor, name):
        # Reuse the actual controls, without the expander/scroll-area decoration.
        group = getattr(editor, name)
        plain = QWidget(editor.view)
        layout = QVBoxLayout(plain)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for widget in list(group.widgets):
            layout.addWidget(widget)
        position = editor.layout_.indexOf(group)
        editor.layout_.removeWidget(group)
        group.hide()
        editor.layout_.insertWidget(position, plain)
        setattr(editor, name, plain)

    def previous(self):
        self.index -= 1
        self.show_step()

    def advance(self):
        if self.index >= 0 and not self.can_continue():
            return
        if self.index == -1:
            self.steps = (["ditoo"] if self.ditoo.isChecked() and not (self.adding and self._existing_ditoo) else []) + (["timesgate"] if self.tg.isChecked() and not (self.adding and self._existing_tg) else []) + ([] if self.adding else ["music"])
            s = self.host.settings
            s.ditoo_enabled = self.ditoo.isChecked() or (self.adding and self._existing_ditoo)
            s.timesgate_enabled = self.tg.isChecked() or (self.adding and self._existing_tg)
            s.save()
            if not s.ditoo_enabled:
                self.host.engine.disconnect_ditoo()
            self.host.update_device_navigation()
            self.host.tg.refresh()
        self.index += 1
        if self.index >= len(self.steps):
            self.host.settings.onboarding_completed = True
            self.host.settings.save()
            self.accept()
            return
        self.show_step()

    def show_step(self):
        self.back.setVisible(self.index >= 0)
        self.skip.setVisible(self.index < 0 and not self.adding)
        self.update_continue()
        if self.index < 0:
            self.stack.setCurrentIndex(0)
            self.title.setText("Добавить устройство" if self.adding else "Добро пожаловать в Divoom Hub")
            self.next.setText("Продолжить")
            return
        step = self.steps[self.index]
        key = "setup_" + step
        page = getattr(self, key, None)
        if page is None:
            page = QWidget()
            layout = QVBoxLayout(page)
            text = {
                "ditoo": "1. Включите Ditoo. 2. Спарьте DitooPro-Audio в параметрах Bluetooth Windows. 3. Отключите приложение Divoom на телефоне, обновите список ниже и нажмите «Подключить». Подключение можно изменить в настройках.",
                "timesgate": "1. Подключите Times Gate к Wi-Fi через приложение Divoom. 2. Компьютер должен быть в той же сети. 3. Нажмите «Найти» и введите LocalToken из настроек устройства в приложении Divoom. Подключение можно изменить в настройках.",
                "music": "Запустите Spotify на компьютере и включите трек. По умолчанию обложка берётся из медиасессии Windows: вход и ключи не нужны. Если музыка играет на телефоне, после настройки выберите Spotify Web API в «Настройки → Музыка».",
            }[step]
            label = BodyLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)
            if step == "ditoo":
                from .page_ditoo import DitooPage
                editor = DitooPage(self.host.settings, self.host.engine, page)
                editor.connection_open = True
                editor.device_group.show()
                self.plain_connection(editor, "device_group")
                for i in range(editor.layout_.count()):
                    widget = editor.layout_.itemAt(i).widget()
                    if widget and widget is not editor.device_group:
                        widget.hide()
                self.connect_events(editor.on_event)
                layout.addWidget(editor)
            elif step == "timesgate":
                from .page_timesgate import TimesGatePage
                editor = TimesGatePage(self.host.settings, self.host.tg, self.host.request_preview, page, connection_only=True)
                editor.connection_open = True
                editor.conn_group.show()
                self.plain_connection(editor, "conn_group")
                for i in range(editor.layout_.count()):
                    widget = editor.layout_.itemAt(i).widget()
                    if widget and widget is not editor.conn_group:
                        widget.hide()
                self.connect_events(editor.on_event)
                layout.addWidget(editor)
            else:
                label.setText("Выберите источник трека и обложки. Его можно изменить в настройках.")
                layout.addStretch()
                row = QHBoxLayout()
                row.addStretch()
                self.source_tiles = {}
                for source, title, detail in (("media", "Медиасессия Windows", "Музыка на этом компьютере · без входа"),
                                           ("api", "Spotify API", "Музыка на любом устройстве · нужен вход")):
                    tile = ChoiceTile(title, detail, artwork=tile_icon(source), artwork_height=72)
                    tile.setFixedSize(240, 240)
                    tile.setChecked(self.host.settings.track_source == source)
                    tile.clicked.connect(lambda source=source: self.choose_source(source))
                    row.addWidget(tile)
                    self.source_tiles[source] = tile
                row.addStretch()
                layout.addLayout(row)
                layout.addStretch()
            self.stack.addWidget(page)
            setattr(self, key, page)
        self.stack.setCurrentWidget(page)
        self.title.setText(f"Шаг {self.index + 1} из {len(self.steps)} · " + {"ditoo": "Ditoo Pro", "timesgate": "Times Gate", "music": "Музыка"}[step])
        self.next.setText("Продолжить")

    def connect_events(self, handler):
        self.host.bridge.event.connect(handler)
        self._connections.append(handler)

    def cleanup(self, _result):
        for handler in self._connections:
            self.host.bridge.event.disconnect(handler)
        self._connections.clear()

    def accept(self):
        self.finished.emit(1)

    def reject(self):
        if self.adding:
            s = self.host.settings
            tg_changed = any(getattr(s,name) != self._device_snapshot[name] for name in ("timesgate_enabled","tg_ip","tg_token","tg_hardware"))
            for name,value in self._device_snapshot.items():
                setattr(s,name,value)
            if not self._existing_ditoo:
                self.host.engine.disconnect_ditoo()
            s.save()
            if tg_changed:
                self.host.tg.reconnect()
            self.host.update_device_navigation()
        self.finished.emit(0)

    def choose_source(self, source):
        self.host.settings.track_source = source
        self.host.settings.save()
        self.host.engine.wake_spotify()
        for key, tile in self.source_tiles.items():
            tile.setChecked(key == source)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(32, 32, 32) if isDarkTheme() else QColor(249, 249, 249))
