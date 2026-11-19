"""Exercise real widgets without starting device workers or touching user data."""
import time

import pytest
from PySide6.QtWidgets import QApplication

from core.player import Engine
from core.settings import Settings
from core.spotify import SpotifyAuth
from gui.main_window import MainWindow
from gui.onboarding import SetupPage
from timesgate.engine import TimesGateEngine


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(Settings, "save", lambda *args: None)
    monkeypatch.setattr(SpotifyAuth, "has_saved_login", staticmethod(lambda: False))
    from bluetooth.connection import DitooConnection
    monkeypatch.setattr(DitooConnection, "scan", staticmethod(lambda **kwargs: []))
    monkeypatch.setattr("gui.page_timesgate.whole_faces", lambda: {})
    settings = Settings()
    w = MainWindow(settings, Engine(settings), TimesGateEngine(settings))
    yield w, app
    w.tray.hide()
    w.hide()
    import logging
    logging.getLogger().removeHandler(w._log_handler)
    w.deleteLater()
    app.processEvents()


def test_setup_steps_and_hidden_devices(window):
    w, app = window
    wizard = SetupPage(w)
    wizard.ditoo.setChecked(True)
    wizard.tg.setChecked(True)
    wizard.advance()
    assert wizard.steps == ["ditoo", "timesgate", "music"]
    wizard.advance()
    assert wizard.index == 0
    assert not wizard.next.isEnabled()
    w.bridge.event.emit("ditoo", (True, "Connected"))
    wizard.advance()
    w.bridge.event.emit("tg", (False, "Testing"))
    w.bridge.event.emit("tg_ip", "192.168.1.20")
    app.processEvents()
    wizard.advance()
    assert wizard.index == 1
    w.bridge.event.emit("tg", (True, "Connected"))
    wizard.advance()
    wizard.advance()
    assert w.settings.onboarding_completed
    wizard = SetupPage(w)
    wizard.ditoo.setChecked(False)
    wizard.tg.setChecked(False)
    wizard.advance()
    assert wizard.steps == ["music"]
    assert w.navigationInterface.widget("ditoo").isHidden()
    assert not w.tray.theme_action.isVisible()
    wizard.reject()


def test_device_and_source_artwork_stays_clickable_and_fits_cards(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from gui.assets import tile_icon
    w, app = window
    w.move(-5000, -5000)
    w.show()
    wizard = SetupPage(w)
    wizard.setGeometry(0, 48, w.width(), w.height()-48)
    wizard.show()
    app.processEvents()
    for tile in (wizard.ditoo, wizard.tg):
        assert not tile.artwork.icon.pixmap(160, 96).isNull()
        assert tile.artwork.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    before = wizard.tg.isChecked()
    point = wizard.tg.artwork.geometry().center()
    QTest.mouseClick(wizard.tg, Qt.MouseButton.LeftButton, pos=point)
    assert wizard.tg.isChecked() != before
    wizard.skip_devices()
    app.processEvents()
    for key, tile in wizard.source_tiles.items():
        assert not tile.artwork.icon.pixmap(72, 72).isNull()
        QTest.mouseClick(tile, Qt.MouseButton.LeftButton, pos=tile.artwork.geometry().center())
        assert w.settings.track_source == key
        assert tile.label.height() >= tile.label.heightForWidth(tile.label.width())
    music_page = wizard.stack.currentWidget()
    wizard.previous()
    wizard.advance()
    assert wizard.stack.currentWidget() is music_page
    wizard.reject()
    wizard.hide()
    w.settings.ditoo_enabled = w.settings.timesgate_enabled = True
    w.switchTo(w.settings_page)
    QTest.qWait(350)
    page = w.settings_page.page
    for name in ("ditoo", "tg"):
        for online in (True, False):
            page.on_event(name, (online, "status"))
            app.processEvents()
            tile = page.connection_tiles["ditoo" if name == "ditoo" else "timesgate"]
            assert not tile.artwork.icon.isNull()
            assert tile.rect().contains(tile.detail.geometry())
            assert tile.artwork.geometry().bottom() < tile.label.geometry().top()
            assert tile.label.geometry().bottom() < tile.detail.geometry().top()
    assert tile_icon("api").cacheKey() == tile_icon("api").cacheKey()


def test_all_pages_construct_and_developer_visibility(window):
    w, app = window
    for page in (w.ditoo, w.timesgate, w.settings_page, w.faq):
        # Materialize hidden destinations too, as a minimized launch would not.
        page.page = page._factory(page)
        page.layout_.addWidget(page.page)
    assert w.stackedWidget.currentWidget() is w.home
    settings = w.settings_page.page
    assert settings.logs_card.isHidden()
    settings.commit_developer(True)
    assert not settings.logs_card.isHidden()
    assert not w.timesgate.page.hardware_card.isHidden()
    w.open_log()
    from PySide6.QtTest import QTest
    QTest.qWait(400)
    assert w.stackedWidget.currentWidget() is w.log_page
    app.processEvents()


def test_quit_returns_without_waiting_for_workers(window, monkeypatch):
    w, app = window
    import threading
    stopped = threading.Event()
    def slow_stop():
        time.sleep(0.2)
        stopped.set()
    monkeypatch.setattr(w.engine, "stop", slow_stop)
    monkeypatch.setattr(w.tg, "stop", lambda: True)
    monkeypatch.setattr(w.tg, "release_to_device", lambda: None)
    start = time.perf_counter()
    w.quit_app()
    assert time.perf_counter() - start < 0.15
    assert w.isHidden()
    assert not w.tray.isVisible()
    assert stopped.wait(1)
    # Deliver shutdown_done before deleting its receiver.
    time.sleep(0.02)
    app.processEvents()


def test_setup_is_inside_main_window(window):
    w, app = window
    from PySide6.QtTest import QTest
    w.open_setup()
    QTest.qWait(400)
    page = w._setup_page
    assert not page.isWindow()
    assert page.window() is w
    assert page.width() == w.width()
    assert not w.stackedWidget.isEnabled()
    assert not w.navigationInterface.isEnabled()
    assert w.navigationInterface.isHidden()
    assert w.navigationInterface.panel.menuButton.isHidden()
    page.advance()  # no devices selected: music step
    page.advance()
    QTest.qWait(450)
    assert w._setup_page is None
    assert w.stackedWidget.currentWidget() is w.home
    assert w.navigationInterface.isEnabled()


def test_setup_controls_are_plain_and_sources_square(window):
    w, app = window
    wizard = SetupPage(w)
    assert wizard.next.text() == "Продолжить"
    assert not wizard.skip.isHidden()
    wizard.tg.setChecked(True)
    wizard.advance()
    app.processEvents()
    group = wizard.setup_timesgate.findChild(__import__('gui.page_timesgate', fromlist=['TimesGatePage']).TimesGatePage).conn_group
    assert not hasattr(group, "card")
    assert group.layout().count() == 3
    assert wizard.skip.isHidden()
    wizard.advance()
    assert wizard.index == 0
    w.bridge.event.emit("tg", (True,"Connected"))
    wizard.advance()
    for tile in wizard.source_tiles.values():
        assert tile.width() == tile.height() == 240
    wizard.choose_source("api")
    assert w.settings.track_source == "api"
    assert wizard.source_tiles["api"].isChecked()
    assert not wizard.source_tiles["media"].isChecked()
    wizard.reject()


def test_everyday_groups_are_open_and_cards_have_one_layout_owner(window):
    from gui.widgets import FoldGroup, StableGroup
    w, app = window
    page = w._make_timesgate(w.timesgate)
    for group in (page.screens_group, page.music_group, page.lights_group):
        assert isinstance(group, StableGroup) and not isinstance(group, FoldGroup)
    assert isinstance(page.more_group, FoldGroup)
    assert not hasattr(page, "deck_group")
    assert page.card_screen_br.parentWidget() is page.screens_group.body
    for card in (page.card_cover, page.card_follow_cover, page.card_follow):
        assert card.parentWidget() is page.music_group.body
        assert page.music_group.cardLayout.indexOf(card) >= 0
        assert page.screens_group.cardLayout.indexOf(card) == -1
        assert page.lights_group.cardLayout.indexOf(card) == -1


def test_disclosure_repeated_toggle_has_stable_final_geometry(window):
    from gui.widgets import FoldGroup, card
    from qfluentwidgets import FluentIcon
    from PySide6.QtTest import QTest
    w, app = window
    group = FoldGroup("Rare settings", w)
    group.addSettingCard(card(FluentIcon.INFO, "One setting"))
    group.setExpand(True)
    group.setExpand(False)
    group.setExpand(True)
    QTest.qWait(200)
    assert group.reveal.maximumHeight() == group._content_height()
    group.setExpand(False)
    QTest.qWait(200)
    assert group.reveal.maximumHeight() == 0
    assert group.cardLayout.count() == 1


def test_title_bar_uses_current_theme_without_pointer_events(window):
    from qfluentwidgets import Theme, setTheme
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    w, app = window
    w.move(-5000, -5000)
    for theme, expected in ((Theme.DARK, "#202020"), (Theme.LIGHT, "#f0f4f9"), (Theme.DARK, "#202020")):
        setTheme(theme)
        w.show_window()
        QTest.qWait(250)
        image = w.titleBar.grab().toImage()
        pixel = image.pixelColor(image.width()//2, image.height()-3)
        assert pixel == QColor(expected)
        assert not w.backgroundColorAni.state().value
        w.hide()


def test_connecting_in_setup_never_constructs_or_shows_the_gallery(window):
    from gui.page_timesgate import TimesGatePage
    from gui.theme_gallery import ThemeGallery
    w, app = window
    wizard = SetupPage(w)
    wizard.tg.setChecked(True)
    wizard.advance()
    editor = wizard.setup_timesgate.findChild(TimesGatePage)
    assert editor.connection_only
    assert not editor.findChildren(ThemeGallery)
    editor.ip.setText("127.0.0.1")
    editor.token.setText("1")
    editor.connect_device()
    editor.on_event("tg", (False, "Connecting"))
    editor.on_event("tg_theme", "Swiss Brutal")
    editor.on_event("tg_mode", "clock")
    editor.on_event("tg_preview", None)
    editor.update_visibility()
    app.processEvents()
    assert wizard.index == 0
    assert not wizard.next.isEnabled()
    assert not editor.findChildren(ThemeGallery)
    assert all(editor.layout_.itemAt(i).widget().isHidden()
               for i in range(editor.layout_.count())
               if editor.layout_.itemAt(i).widget() is not None
               and editor.layout_.itemAt(i).widget() is not editor.conn_group)
    wizard.reject()


def test_lighting_controls_and_music_order_match_daily_flow(window):
    w, app = window
    page = w._make_timesgate(w.timesgate)
    assert page.card_zone.parentWidget() is page.light_more_group.body
    assert page.card_keys.parentWidget() is page.light_more_group.body
    assert page.card_light_br.parentWidget() is page.lights_group.body
    assert page.card_screen_br.parentWidget() is page.screens_group.body
    settings = w._make_settings(w.settings_page)
    ordered = [settings.music_group.cardLayout.itemAt(i).widget()
               for i in range(settings.music_group.cardLayout.count())]
    assert ordered[:5] == [settings.tracking_card, settings.status_card,
                           settings.music_separator, settings.source_card,
                           settings.only_spotify_card]
    assert settings.add_device_tile.width() == 160
    assert page.light_more_group.chevron.parentWidget() is page.light_more_group.header


def test_compact_gallery_uses_compact_cards(window):
    from gui.theme_gallery import ThemeCard
    w, app = window
    card = ThemeCard(0, w)
    card.set_compact(True)
    assert card.width() == 148
    card.set_compact(False)
    assert card.width() == 236


def test_home_preview_starts_without_visiting_timesgate(window, monkeypatch):
    from PIL import Image
    from PySide6.QtTest import QTest
    w, app = window
    w.settings.tg_ip, w.settings.tg_token = "127.0.0.1", "1"
    calls = []
    def preview():
        calls.append(True)
        return [Image.new("RGB", (128,128), "red") for _ in range(5)]
    monkeypatch.setattr(w.tg, "preview", preview)
    w.move(-5000,-5000)
    w.show()
    for _ in range(150):
        QTest.qWait(20)
        if calls and not w.home.tiles[0].pixmap().isNull():
            break
    assert calls
    assert not w.home.tiles[0].pixmap().isNull()
    assert w.timesgate.page is None
    w.open_setup()
    assert not w.minute_timer.isActive()
    calls.clear()
    for tile in w.home.tiles:
        tile.clear()
    w._setup_page.reject()
    assert w.stackedWidget.currentWidget() is w.home
    for _ in range(150):
        QTest.qWait(20)
        if calls and not w.home.tiles[0].pixmap().isNull():
            break
    assert calls
    assert not w.home.tiles[0].pixmap().isNull()
    assert w.timesgate.page is None


def test_gate_connection_prefills_only_in_test_build(window, monkeypatch):
    import gui.page_timesgate as module
    w, app = window
    monkeypatch.setenv("DIVOOM_TEST_GATE_IP", "192.0.2.10")
    monkeypatch.setenv("DIVOOM_TEST_GATE_TOKEN", "123456")
    monkeypatch.setattr(module, "TEST_MODE", True)
    page = module.TimesGatePage(w.settings, w.tg, w.request_preview, w, connection_only=True)
    assert page.ip.text() == "192.0.2.10"
    assert page.token.text() == "123456"
    assert w.settings.tg_ip == ""  # prefilling does not connect or persist before user action
    monkeypatch.setattr(module, "TEST_MODE", False)
    normal = module.TimesGatePage(w.settings, w.tg, w.request_preview, w, connection_only=True)
    assert normal.ip.text() == normal.token.text() == ""


def test_cover_follow_persists_across_theme_selection(window):
    w, app = window
    page = w._make_timesgate(w.timesgate)
    page.commit_face_follow_cover(True)
    for index in range(5):
        page.select_theme(index)
        assert w.settings.tg_face_follow_cover
        assert page.follow_switch.isChecked()
    page.commit_face_follow_cover(False)
    page.select_theme(0)
    assert not page.follow_switch.isChecked()


def test_slider_ignores_mouse_wheel(window):
    from gui.widgets import slider
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    w, app = window
    box, control = slider(0,100,50)
    box.setParent(w)
    event = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(), QPoint(0,120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    app.sendEvent(control,event)
    assert control.value() == 50
    assert not event.isAccepted()


def test_disclosure_keeps_scrolled_header_in_place(window):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    w, app = window
    w.settings.tg_ip, w.settings.tg_token = "127.0.0.1", "1"
    w.move(-5000,-5000)
    w.show()
    w.switchTo(w.timesgate)
    QTest.qWait(450)
    page = w.timesgate.page
    group = page.more_group
    page.ensureWidgetVisible(group.header, 0, 20)
    QTest.qWait(50)
    before = group.header.mapTo(page.viewport(), QPoint()).y()
    group.setExpand(True)
    positions = []
    for _ in range(12):
        QTest.qWait(20)
        positions.append(group.header.mapTo(page.viewport(), QPoint()).y())
    assert max(abs(y-before) for y in positions) <= 3
    assert group.reveal.height() > 0



def test_gallery_cards_do_not_shift_during_disclosure(window):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    w, app = window
    w.settings.tg_ip, w.settings.tg_token = "127.0.0.1", "1"
    w.move(-5000,-5000)
    w.show()
    w.switchTo(w.timesgate)
    QTest.qWait(500)
    page = w.timesgate.page
    group = page.more_group
    page.ensureWidgetVisible(group.header,0,20)
    QTest.qWait(50)
    card = page.gallery.cards[0]
    original = card.geometry()
    position = card.mapTo(page.viewport(),QPoint())
    for expanded in (True,False):
        group.setExpand(expanded)
        for _ in range(12):
            QTest.qWait(20)
            assert card.geometry() == original
            assert abs(card.mapTo(page.viewport(),QPoint()).y()-position.y()) <= 3



def test_add_device_preserves_existing_and_cancel_rolls_back(window):
    w,app = window
    w.settings.ditoo_enabled = False
    w.settings.timesgate_enabled = True
    w.settings.tg_ip,w.settings.tg_token = "127.0.0.1","1"
    w.settings.onboarding_completed = True
    wizard = SetupPage(w,adding=True)
    assert not wizard.tg.isEnabled()
    assert wizard.tg.isChecked()
    assert wizard.cancel.isVisibleTo(wizard)
    wizard.ditoo.setChecked(True)
    wizard.advance()
    assert wizard.steps == ["ditoo"]
    assert w.settings.timesgate_enabled
    assert w.settings.tg_ip == "127.0.0.1"
    w.settings.ditoo_address = "new-device"
    wizard.reject()
    assert not w.settings.ditoo_enabled
    assert not w.settings.ditoo_address
    assert w.settings.timesgate_enabled and w.settings.tg_token == "1"


def test_connection_opens_inside_main_window_and_leaving_cleans_up(window):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog
    w,app = window
    w.move(-5000,-5000)
    w.show()
    original_count = w.stackedWidget.count()
    w.open_connection("timesgate")
    QTest.qWait(400)
    page = w.stackedWidget.currentWidget()
    assert page.objectName() == "connection_timesgate"
    assert page.window() is w and not isinstance(page,QDialog)
    assert page._editor.connection_only
    w.switchTo(w.home)
    QTest.qWait(450)
    assert w.stackedWidget.count() == original_count


def test_reordering_preserves_active_theme_and_persists(window, monkeypatch):
    w,app = window
    page = w._make_timesgate(w.timesgate)
    active = page.current()
    before = list(page.themes())
    saves = []
    monkeypatch.setattr(w.settings,"save",lambda:saves.append(True))
    page.reorder_themes(0,3)
    expected = list(before)
    expected.insert(3,expected.pop(0))
    assert page.themes() == expected
    assert page.current() is active
    assert saves


def test_faq_grids_do_not_move_or_stretch_during_disclosure(window):
    from gui.widgets import FoldGroup
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    w,app = window
    w.move(-5000,-5000)
    w.show()
    w.switchTo(w.faq)
    QTest.qWait(450)
    page = w.faq.page
    group = page.findChildren(FoldGroup)[0]
    page.ensureWidgetVisible(group.header,0,20)
    QTest.qWait(50)
    cards = [tile for _,tiles in page.grid_boxes for tile in tiles]
    geometry = [tile.geometry() for tile in cards]
    positions = [tile.mapTo(page.viewport(),QPoint()).y() for tile in cards]
    for expanded in (True,False):
        group.setExpand(expanded)
        for _ in range(12):
            QTest.qWait(20)
            assert [tile.geometry() for tile in cards] == geometry
            assert all(abs(tile.mapTo(page.viewport(),QPoint()).y()-y)<=3 for tile,y in zip(cards,positions))



def test_editor_and_color_picker_stay_inside_main_window(window):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QColorDialog
    from PySide6.QtGui import QColor
    w,app = window
    w.settings.tg_ip,w.settings.tg_token = "127.0.0.1","1"
    w.settings.tg_face_follow_cover = True
    w.move(-5000,-5000)
    w.show()
    w.switchTo(w.timesgate)
    QTest.qWait(350)
    page = w.timesgate.page
    page.open_editor(1)
    QTest.qWait(350)
    assert w.stackedWidget.currentWidget() is page.editor_page
    assert not page.editor_page.isWindow()
    assert len(page._pickers) == 13
    picker,_ = page._pickers[0]
    picker.open_picker()
    QTest.qWait(350)
    color_page = w.stackedWidget.currentWidget()
    chooser = color_page.findChild(QColorDialog)
    assert chooser.window() is w and not chooser.isWindow()
    assert chooser.isVisibleTo(color_page)
    chooser.setCurrentColor(QColor("#123456"))
    chooser.accept()
    QTest.qWait(350)
    assert w.stackedWidget.currentWidget() is page.editor_page
    assert page.current()["t0"] == "#123456"


def test_file_chooser_is_embedded_and_preserves_overwrite_confirmation(window, tmp_path):
    from gui.widgets import choose_file
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtTest import QTest
    w,app = window
    w.move(-5000,-5000)
    w.show()
    path = tmp_path/"existing.zip"
    path.write_bytes(b"original")
    picked = []
    choose_file(w,"Export","Packs (*.zip)",picked.append,save=True,suggested=str(path))
    QTest.qWait(350)
    page = w.stackedWidget.currentWidget()
    chooser = page.findChild(QFileDialog)
    assert not chooser.isWindow() and chooser.window() is w
    chooser.accept()
    assert picked == []
    assert path.read_bytes() == b"original"
    assert any(button.text() == "Заменить" for button in page.findChildren(__import__("qfluentwidgets").PushButton))
    w.switchTo(w.home)
    QTest.qWait(350)


def test_idle_light_color_is_editable_while_following_cover(window):
    w,app = window
    w.settings.tg_light_follow_cover = True
    page = w._make_timesgate(w.timesgate)
    assert page.light_color_picker.isEnabled()
    assert "не играет" in page.card_color.contentLabel.text()
    assert page.view.testAttribute(__import__("PySide6.QtCore",fromlist=["Qt"]).Qt.WidgetAttribute.WA_OpaquePaintEvent)



def test_faq_card_pixels_do_not_duplicate_during_disclosure(window):
    from gui.widgets import FoldGroup
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint,QRect
    w,app = window
    w.move(-5000,-5000)
    w.show()
    w.switchTo(w.faq)
    QTest.qWait(450)
    page = w.faq.page
    group = page.findChildren(FoldGroup)[0]
    page.ensureWidgetVisible(group.header,0,20)
    QTest.qWait(80)
    tiles = [tile for _,items in page.grid_boxes for tile in items]
    areas = [QRect(tile.mapTo(page.viewport(),QPoint()),tile.size()).intersected(page.viewport().rect()) for tile in tiles]
    areas = [area for area in areas if area.height()>20 and area.width()>20]
    assert areas
    before = page.viewport().grab().toImage()
    for expanded in (True,False):
        group.setExpand(expanded)
        for _ in range(12):
            QTest.qWait(20)
            current = page.viewport().grab().toImage()
            assert all(current.copy(area) == before.copy(area) for area in areas)
