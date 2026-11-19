"""Main window (Windows 11 Fluent style), tray icon and single-instance handling."""

from __future__ import annotations

from collections import deque
import json
import logging
import threading
import winreg

from PySide6.QtCore import QEvent, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import (FluentIcon, FluentWindow, NavigationItemPosition, Theme, isDarkTheme,
                            qconfig, setCustomStyleSheet, setTheme, setThemeColor)

from core import autostart
from core.player import Engine
from core.settings import APP_DIR, Settings, settings_for_gui_launch
from core.version import APP_NAME
from core.profile import PROFILE_NAME, TEST_MODE
from timesgate.engine import TimesGateEngine

from .page_home import HomePage, LogPage
from .tray import Tray, app_icon
from .widgets import Bridge, QtLogHandler

log = logging.getLogger(__name__)
INSTANCE_KEY = PROFILE_NAME + "-single-instance"
MAX_MESSAGE = 4096
THEMES = {"auto": Theme.AUTO, "dark": Theme.DARK, "light": Theme.LIGHT}


def system_accent(dark: bool) -> str:
    """Windows accent colour, in the lighter shade Windows itself uses on dark UI."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as key:
            palette = winreg.QueryValueEx(key, "AccentPalette")[0]
        i = 1 if dark else 4  # palette: light3, light2, light1, accent, dark1, dark2, ...
        r, g, b = palette[i * 4: i * 4 + 3]
        return f"#{r:02X}{g:02X}{b:02X}"
    except OSError:
        return "#60CDFF" if dark else "#005FB8"


class LazyPage(QWidget):
    """A navigation destination whose controls are created on first visit."""

    def __init__(self, name, factory, parent):
        super().__init__(parent)
        self.setObjectName(name)
        self._factory = factory
        self.page = None
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.page is None:
            self.page = self._factory(self)
            self.page.layout_.addStretch(1)
            self.layout_.addWidget(self.page)


class MainWindow(FluentWindow):
    def __init__(self, settings: Settings, engine: Engine, tg: TimesGateEngine):
        super().__init__()
        self.settings, self.engine, self.tg = settings, engine, tg
        self.quitting = False
        self.tray_hint_shown = False
        self.apply_theme(settings.ui_theme)
        # Native Mica can retain a stale backing surface after tray restore.
        # Use the Fluent palette with the normal Qt backing store.
        self.setMicaEffectEnabled(False)
        self._sync_window_chrome()
        qconfig.themeChangedFinished.connect(self._sync_window_chrome)
        self.setWindowTitle(APP_NAME + (" · TEST" if TEST_MODE else ""))
        self.setWindowIcon(app_icon())
        self.resize(1040, 760)
        self.setMinimumWidth(820)

        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        engine.add_listener(self.bridge.event.emit)
        tg.add_listener(self.bridge.event.emit)
        self._log_handler = QtLogHandler(self.bridge)
        logging.getLogger().addHandler(self._log_handler)
        self._recent_logs = deque(maxlen=1000)
        self.bridge.log_line.connect(self._append_log)
        self._last_events = {}

        # Times Gate previews render in a worker thread (a theme switch can take
        # a few hundred ms); requests are coalesced and refreshed every 20 s.
        self._preview_busy = False
        self._preview_again = False
        self.preview_timer = QTimer(self, singleShot=True, interval=120)
        self.preview_timer.timeout.connect(self._render_preview)
        self.minute_timer = QTimer(self, interval=20_000)
        self.minute_timer.timeout.connect(self.request_preview)
        self.home = HomePage(settings, tg, self)
        self.home.layout_.addStretch(1)
        self.ditoo = LazyPage("ditoo", self._make_ditoo, self)
        self.timesgate = LazyPage("timesgate", self._make_timesgate, self)
        self.log_page = LazyPage("log", self._make_log, self)
        self.faq = LazyPage("faq", self._make_faq, self)
        self.settings_page = LazyPage("settings", self._make_settings, self)
        self.pages = [self.home, self.ditoo, self.timesgate, self.log_page, self.faq, self.settings_page]

        nav = self.navigationInterface
        self.addSubInterface(self.home, FluentIcon.HOME, "Главная")
        nav.addSeparator()
        self.addSubInterface(self.ditoo, FluentIcon.BLUETOOTH, "Ditoo Pro")
        self.addSubInterface(self.timesgate, FluentIcon.DATE_TIME, "Times Gate")

        self.addSubInterface(self.faq, FluentIcon.INFO, "О программе", NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "Настройки", NavigationItemPosition.BOTTOM)
        self.stackedWidget.addWidget(self.log_page)
        nav.setReturnButtonVisible(False)
        nav.setExpandWidth(230)
        nav.setMinimumExpandWidth(1000)
        self.stackedWidget.currentChanged.connect(lambda _: self.request_preview())
        if self.width() >= 1000:
            nav.expand(useAni=False)
        self.update_device_navigation()
        self.home.ditoo_card.clicked.connect(lambda: self.switchTo(self.ditoo))
        self.home.tg_card.clicked.connect(lambda: self.switchTo(self.timesgate))

        self.tray = Tray(self, on_show=self.show_window,
                         on_toggle_integration=self.set_tracking,
                         on_reconnect=engine.reconnect_ditoo, on_theme=lambda step: tg.switch_theme(step),
                         on_device_face=lambda: tg.set_mode("device"),
                         on_exit=self.quit_app)
        self.tray.set_paused(not settings.show_artwork)
        self.tray.set_devices(settings.ditoo_enabled, settings.timesgate_enabled)
        self.tray.show()
        self.request_preview()

    def update_device_navigation(self):
        for route, enabled in (("ditoo", self.settings.ditoo_enabled),
                               ("timesgate", self.settings.timesgate_enabled)):
            self.navigationInterface.widget(route).setVisible(enabled)
        self.home.update_visibility()
        if self.settings_page.page is not None:
            self.settings_page.page.update_visibility()
        current = self.stackedWidget.currentWidget()
        if ((current is self.ditoo and not self.settings.ditoo_enabled)
                or (current is self.timesgate and not self.settings.timesgate_enabled)):
            self.switchTo(self.home)
        if hasattr(self, "tray"):
            self.tray.set_devices(self.settings.ditoo_enabled, self.settings.timesgate_enabled)

    def open_setup(self, adding=False):
        from .onboarding import SetupPage
        if getattr(self, "_setup_page", None) is not None:
            self._setup_page.raise_()
            return
        self._setup_return = self.stackedWidget.currentWidget()
        self._setup_page = SetupPage(self, adding=adding)
        self.request_preview()  # suspend previews while the wizard covers the dashboard
        self._setup_page.finished.connect(self._finish_setup)
        self.navigationInterface.hide()
        self.navigationInterface.setMenuButtonVisible(False)
        self.navigationInterface.setEnabled(False)
        self.stackedWidget.setEnabled(False)
        self._position_setup()
        self._setup_page.show()
        self._setup_page.raise_()
        self._setup_page.setFocus()

    def _finish_setup(self, _result):
        page = self._setup_page
        self._setup_page = None
        self.navigationInterface.show()
        self.navigationInterface.setMenuButtonVisible(True)
        self.navigationInterface.setEnabled(True)
        self.stackedWidget.setEnabled(True)
        page.hide()
        self.switchTo(self._setup_return if page.adding else self.home)
        page.deleteLater()
        # Home may already be current, so no currentChanged signal is emitted.
        self.request_preview()

    def _position_setup(self):
        page = getattr(self, "_setup_page", None)
        if page is not None:
            page.setGeometry(0, self.titleBar.height(), self.width(), self.height()-self.titleBar.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_setup()

    def open_internal_page(self, page, *, delete=False):
        previous = self.stackedWidget.currentWidget()
        page.setProperty("isStackedTransparent",False)
        if self.stackedWidget.indexOf(page) < 0:
            self.stackedWidget.addWidget(page)
        closed = False
        def left(_index):
            nonlocal closed
            if not closed and self.stackedWidget.currentWidget() is not page:
                closed = True
                self.stackedWidget.currentChanged.disconnect(left)
                if delete:
                    QTimer.singleShot(0, lambda: self._dispose_connection(page))
        self.stackedWidget.currentChanged.connect(left)
        self.switchTo(page)
        return lambda: self.switchTo(previous)

    def open_connection(self, device):
        from qfluentwidgets import PushButton
        from .widgets import Page
        from .onboarding import SetupPage
        previous = self.stackedWidget.currentWidget()
        connection = Page("connection_" + device, "Подключение · " + ("Ditoo Pro" if device == "ditoo" else "Times Gate"), parent=self)
        back = PushButton(FluentIcon.LEFT_ARROW, "Назад")
        connection.layout_.insertWidget(0, back)
        if device == "timesgate":
            from .page_timesgate import TimesGatePage
            editor = TimesGatePage(self.settings, self.tg, self.request_preview, connection, connection_only=True)
            attribute = "conn_group"
        else:
            from .page_ditoo import DitooPage
            editor = DitooPage(self.settings, self.engine, connection)
            attribute = "device_group"
        editor.connection_open = True
        editor.hide()
        SetupPage.plain_connection(editor, attribute)
        group = getattr(editor, attribute)
        connection.add(group)
        group.show()
        self.bridge.event.connect(editor.on_event)
        if device == "timesgate":
            editor.on_event("tg", self.tg.status)
        elif "ditoo" in self._last_events:
            editor.on_event("ditoo", self._last_events["ditoo"])
        self.stackedWidget.addWidget(connection)
        closed = False
        def left(_index):
            nonlocal closed
            if not closed and self.stackedWidget.currentWidget() is not connection:
                closed = True
                self.bridge.event.disconnect(editor.on_event)
                self.stackedWidget.currentChanged.disconnect(left)
                QTimer.singleShot(0, lambda: self._dispose_connection(connection))
        self.stackedWidget.currentChanged.connect(left)
        self.switchTo(connection)
        back.clicked.connect(lambda: self.switchTo(previous))
        connection._editor = editor

    def _dispose_connection(self, page):
        self.stackedWidget.removeWidget(page)
        page.deleteLater()

    def open_log(self):
        if self.log_page.page is None:
            self.log_page.page = self._make_log(self.log_page)
            self.log_page.layout_.addWidget(self.log_page.page)
        self.stackedWidget.setCurrentWidget(self.log_page)

    def _restore_events(self, page, *names):
        for name in names:
            if name in self._last_events:
                page.on_event(name, self._last_events[name])
        return page

    def _make_ditoo(self, parent):
        from .page_ditoo import DitooPage
        return self._restore_events(DitooPage(self.settings, self.engine, parent), "ditoo")

    def _make_timesgate(self, parent):
        from .page_timesgate import TimesGatePage
        page = TimesGatePage(self.settings, self.tg, self.request_preview, parent)
        return self._restore_events(page, "tg", "tg_preview")

    def _make_log(self, parent):
        page = LogPage(parent)
        page.view_.setPlainText("\n".join(self._recent_logs))
        return page

    def _make_faq(self, parent):
        from .page_faq import FaqPage
        return FaqPage(parent)

    def _make_settings(self, parent):
        from .page_settings import SettingsPage
        return self._restore_events(SettingsPage(self.settings, self.engine, self.change_theme, parent),
                                    "spotify", "ditoo", "tg")

    def _append_log(self, line: str) -> None:
        self._recent_logs.append(line)
        if self.log_page.page is not None:
            self.log_page.page.append(line)

    def set_tracking(self, value: bool) -> None:
        self.settings.show_artwork = value
        self.settings.save()
        self.engine.wake_spotify()
        self.tray.set_paused(not value)
        page = self.settings_page.page
        if page is not None:
            previous = page.show_artwork.blockSignals(True)
            page.show_artwork.setChecked(value)
            page.show_artwork.blockSignals(previous)

    # ---- Times Gate preview ------------------------------------------------

    def _preview_visible(self) -> bool:
        if getattr(self, "_setup_page", None) is not None:
            return False
        if not (self.isVisible() and not self.isMinimized()
                and self.settings.tg_ip and self.settings.tg_token):
            return False
        return (self.stackedWidget.currentWidget() in (self.home, self.timesgate)
                and self.settings.tg_mode in ("clock", "gifs_clock"))

    def request_preview(self) -> None:
        if not self._preview_visible():
            self.preview_timer.stop()
            self.minute_timer.stop()
            return
        if not self.minute_timer.isActive():
            self.minute_timer.start()
        self.preview_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync_window_chrome()
        QTimer.singleShot(0, self._sync_window_chrome)
        QTimer.singleShot(0, self.request_preview)
        if hasattr(self, "home"):
            self.request_preview()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.preview_timer.stop()
        self.minute_timer.stop()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange):
            self._sync_window_chrome()
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "home"):
            self.request_preview()

    def _render_preview(self) -> None:
        if not self._preview_visible():
            return
        if self._preview_busy:
            self._preview_again = True
            return
        self._preview_busy = True

        def run() -> None:
            try:
                images = self.tg.preview()
                self.bridge.event.emit("tg_preview", (images, self.tg.current_theme()["name"]))
            except Exception:
                log.exception("Times Gate preview failed")
            finally:
                self.bridge.event.emit("tg_preview_done", None)
        threading.Thread(target=run, name="tg-preview", daemon=True).start()

    # ---- theme -----------------------------------------------------------

    def _sync_window_chrome(self):
        if not hasattr(self, "titleBar") or self.isMicaEffectEnabled():
            return
        dark = isDarkTheme()
        # A theme transition can leave the parent's old light background behind
        # the transparent title bar. Commit the current palette without hover.
        self.backgroundColorAni.stop()
        self.setBackgroundColor(self._normalBackgroundColor())
        if getattr(self, "_chrome_dark", None) is not dark:
            self._chrome_dark = dark
            setCustomStyleSheet(self.titleBar,
                                "FluentTitleBar { background-color: #F0F4F9; }",
                                "FluentTitleBar { background-color: #202020; }")
            self.titleBar.titleLabel.setTextColor("#1A1A1A", "#FFFFFF")
            for button in (self.titleBar.minBtn, self.titleBar.maxBtn, self.titleBar.closeBtn):
                button.setNormalColor("#FFFFFF" if dark else "#1A1A1A")
        self.titleBar.update()
        self.update()

    def apply_theme(self, name: str) -> None:
        setTheme(THEMES.get(name, Theme.AUTO))
        setThemeColor(system_accent(isDarkTheme()))
        self._sync_window_chrome()

    def change_theme(self, name: str) -> None:
        self.settings.ui_theme = name
        self.settings.save()
        self.apply_theme(name)

    # ---- events ----------------------------------------------------------

    def on_event(self, name: str, payload) -> None:
        if name == "shutdown_done":
            QApplication.quit()
            return
        if self.quitting:
            return
        if name in ("ditoo", "spotify", "tg", "tg_preview"):
            self._last_events[name] = payload
        for destination in self.pages:
            page = destination.page if isinstance(destination, LazyPage) else destination
            handler = getattr(page, "on_event", None)
            if handler:
                handler(name, payload)
        if name == "tg_preview_done":
            self._preview_busy = False
            if self._preview_again:
                self._preview_again = False
                self.request_preview()
            return
        if name == "track":
            self.tg.refresh()  # the centre screen may switch between cover and colon
        if name in ("track", "tg_theme", "tg_mode", "tg_screens", "tg"):
            self.request_preview()
        if name == "ditoo":
            self.tray.set_ditoo(*payload)
        elif name == "spotify":
            self.tray.set_spotify(str(payload))
        elif name in ("tg", "tg_theme"):
            connected, text = self.tg.status
            self.tray.set_tg(connected, text, self.tg.current_theme()["name"])

    def run_command(self, command: dict) -> None:
        """Commands from a second launch (see app.py)."""
        theme = command.get("tg_theme")
        if theme in ("next", "prev"):
            self.tg.switch_theme(+1 if theme == "next" else -1)
        elif isinstance(theme, str) and theme:
            self.tg.switch_theme(name=theme)
        if command.get("tg_mode") in ("clock", "gifs_clock", "device", "off"):
            self.tg.set_mode(command["tg_mode"])

    # ---- window / tray ---------------------------------------------------

    def show_window(self) -> None:
        if self.quitting:
            return
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.layout().activate()
        self.stackedWidget.updateGeometry()
        self.update()
        QTimer.singleShot(0, self._refresh_restored_window)
        self.raise_()
        self.activateWindow()

    def _refresh_restored_window(self):
        if self.isVisible() and not self.quitting:
            self.layout().activate()
            self.stackedWidget.update()
            self.repaint()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.tray_hint_shown:
            self.tray_hint_shown = True
            self.tray.showMessage(APP_NAME, "Программа работает в трее. "
                                  "Выход — правый клик по иконке.", app_icon(), 3000)

    def quit_app(self) -> None:
        if self.quitting:
            return
        self.quitting = True
        self.hide()
        self.tray.hide()
        self.preview_timer.stop()
        self.minute_timer.stop()
        logging.getLogger().removeHandler(self._log_handler)
        def shutdown():
            try:
                self.engine.stop()
                if self.tg.stop():
                    self.tg.release_to_device()
            except Exception:
                log.exception("Shutdown failed")
            finally:
                self.bridge.event.emit("shutdown_done", None)
        threading.Thread(target=shutdown, name="shutdown", daemon=True).start()


# ---- single instance ----------------------------------------------------------

def send_to_running_instance(message: dict) -> bool:
    """True if another instance is running and received the message."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    data = json.dumps(message).encode("utf-8") + b"\n"
    if len(data) > MAX_MESSAGE or sock.write(data) != len(data):
        sock.abort()
        return False
    if sock.bytesToWrite() and not sock.waitForBytesWritten(500):
        sock.abort()
        return False
    sock.disconnectFromServer()
    return True


def run_gui(settings: Settings, minimized: bool = False, command: dict | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)  # closing the window only hides it
    app.setWindowIcon(app_icon())
    message = {"command": command} if command else {"show": True}
    if send_to_running_instance(message):
        log.info("Already running: message passed to the running copy")
        return 0
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(APP_DIR / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(500):
        # The first instance may be between acquiring the lock and listening.
        if send_to_running_instance(message):
            return 0
        log.error("Divoom Hub is already starting or running")
        return 1
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(INSTANCE_KEY):
        log.error("Could not open instance socket: %s", server.errorString())
        return 1

    settings = settings_for_gui_launch(settings)
    autostart.refresh()
    engine = Engine(settings)
    tg = TimesGateEngine(settings, cover_provider=engine.now_playing_cover)
    window = MainWindow(settings, engine, tg)

    def receive(sock: QLocalSocket) -> None:
        # QLocalSocket is a stream: readyRead can deliver half a JSON message.
        # Accept old senders without a newline when they disconnect.
        pending = bytearray()
        handled = False

        def read(final=False) -> None:
            nonlocal handled
            pending.extend(bytes(sock.read(MAX_MESSAGE + 1)))
            if handled or len(pending) > MAX_MESSAGE:
                sock.abort()
                return
            if b"\n" not in pending and not final:
                return
            handled = True
            try:
                msg = json.loads(bytes(pending).split(b"\n", 1)[0])
                if not isinstance(msg, dict):
                    return
                if isinstance(msg.get("command"), dict):
                    window.run_command(msg["command"])
                elif msg.get("show") is True:
                    window.show_window()
            except (ValueError, TypeError):
                log.debug("Ignored invalid local command")

        def disconnected() -> None:
            if not handled:
                read(final=True)
            sock.deleteLater()

        sock.readyRead.connect(read)
        sock.disconnected.connect(disconnected)
        read()
        if sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            disconnected()
        else:
            QTimer.singleShot(2000, sock, sock.abort)

    def on_connection() -> None:
        while server.hasPendingConnections():
            receive(server.nextPendingConnection())
    server.newConnection.connect(on_connection)

    if not minimized and not command or not settings.onboarding_completed:
        window.show()
    if not settings.onboarding_completed:
        QTimer.singleShot(0, window.open_setup)
    engine.start()
    tg.start()
    if command:
        window.run_command(command)
    log.info("Started%s", " minimized to tray" if minimized or command else "")
    return app.exec()
