"""System tray icon: the program keeps running when the window is closed."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget
from qfluentwidgets import Action, FluentIcon, SystemTrayMenu

from core.version import APP_NAME


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "resources" / name


def app_icon() -> QIcon:
    return QIcon(str(resource("icon.ico")))


class Tray(QSystemTrayIcon):
    def __init__(self, parent: QWidget, *, on_show: Callable[[], None],
                 on_toggle_integration: Callable[[bool], None], on_reconnect: Callable[[], None],
                 on_theme: Callable[[int], None], on_device_face: Callable[[], None],
                 on_exit: Callable[[], None]):
        super().__init__(app_icon(), parent)
        menu = SystemTrayMenu(parent=parent)
        self.ditoo_action = Action(FluentIcon.BLUETOOTH, "Ditoo: —")
        self.spotify_action = Action(FluentIcon.MUSIC, "Музыка: —")
        self.tg_action = Action(FluentIcon.DATE_TIME, "Times Gate: —")
        for a in (self.ditoo_action, self.spotify_action, self.tg_action):
            a.setEnabled(False)
        menu.addActions([self.ditoo_action, self.spotify_action, self.tg_action])
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.HOME, "Показать", triggered=on_show))
        self.pause_action = Action(FluentIcon.PAUSE, "Пауза интеграции", checkable=True)
        self.pause_action.toggled.connect(lambda paused: on_toggle_integration(not paused))
        menu.addAction(self.pause_action)
        self.reconnect_action = Action(FluentIcon.SYNC, "Переподключить Ditoo", triggered=on_reconnect)
        menu.addAction(self.reconnect_action)
        self.theme_action = Action(FluentIcon.RIGHT_ARROW, "Следующий циферблат", triggered=lambda: on_theme(+1))
        menu.addAction(self.theme_action)
        self.face_action = Action(FluentIcon.POWER_BUTTON, "Встроенный циферблат Times Gate", triggered=on_device_face)
        menu.addAction(self.face_action)
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.CLOSE, "Выход", triggered=on_exit))
        self.setContextMenu(menu)
        self.activated.connect(lambda reason: on_show() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self._lines = {"ditoo": "", "spotify": "", "tg": ""}
        self._update_tooltip()

    def set_devices(self, ditoo: bool, tg: bool):
        for action in (self.ditoo_action, self.reconnect_action):
            action.setVisible(ditoo)
        for action in (self.tg_action, self.theme_action, self.face_action):
            action.setVisible(tg)

    def _set(self, key: str, action: Action, text: str) -> None:
        action.setText(text)
        self._lines[key] = text
        self._update_tooltip()

    def set_ditoo(self, connected: bool, text: str) -> None:
        self._set("ditoo", self.ditoo_action, "Ditoo: " + ("подключён" if connected else text))

    def set_spotify(self, text: str) -> None:
        self._set("spotify", self.spotify_action, f"Музыка: {text}")

    def set_tg(self, connected: bool, text: str, theme: str = "") -> None:
        state = f"тема «{theme}»" if connected and theme else text
        self._set("tg", self.tg_action, f"Times Gate: {state}")

    def set_paused(self, paused: bool) -> None:
        self.pause_action.blockSignals(True)
        self.pause_action.setChecked(paused)
        self.pause_action.blockSignals(False)

    def _update_tooltip(self) -> None:
        lines = [APP_NAME, *[v for v in self._lines.values() if v]]
        self.setToolTip("\n".join(lines)[:127])
