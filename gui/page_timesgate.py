"""Times Gate page.

Only what matters for the current setup is shown:
  * not configured            -> just the connection block;
  * mode decides the rest     -> faces + editor for clock modes, side pictures only for
                                 "pictures + clock", the built-in face for "device",
                                 lights / brightness in every mode;
  * the editor hides colours that the light replaces ("Цвет из подсветки");
  * lights unfold step by step (managed -> on -> colour effect -> follows the cover).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (Action, BodyLabel, CaptionLabel, ComboBox,
                            FlowLayout, FluentIcon, InfoBar, InfoBarPosition,
                            LineEdit, PasswordLineEdit, PushButton, RoundMenu,
                            SettingCardGroup, SimpleCardWidget, StrongBodyLabel, SubtitleLabel)

from core.settings import APP_DIR, Settings
from core.profile import TEST_MODE
from timesgate import digits, packs
from timesgate.client import BUILTIN_FACES, LIGHT_ZONES, TimesGateError, discover, effects_for_zone, whole_faces
from timesgate.engine import MODES, TimesGateEngine

from .theme_gallery import ThemeGallery
from .widgets import InlineColorPicker, choose_file, TitleStatusDot, Page, PixelPreview, ThemeSwitcher, card, combo, show, slider, switch

log = logging.getLogger(__name__)
MEDIA_DIR = APP_DIR / "timesgate"
MEDIA_FILTER = "Картинки и GIF (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
PACK_FILTER = "Пак часов (*.zip)"
CLOCK_MODES = ("clock", "gifs_clock")


class MediaSlot(QWidget):
    """A picture slot: click to choose a file, right-click to clear.
    `on_pick(source or None)` stores the file and returns the stored path."""

    def __init__(self, caption: str, path: str, on_pick, parent=None):
        super().__init__(parent)
        self.on_pick, self.path = on_pick, path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.tile = PixelPreview(72)
        self.tile.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tile.setToolTip("Клик — выбрать картинку или GIF, правый клик — убрать")
        label = CaptionLabel(caption)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(label)
        self.tile.mousePressEvent = self._clicked
        self.set_path(path)

    def set_path(self, path: str) -> None:
        self.path = path
        if path and Path(path).exists():
            try:
                self.tile.set_image(digits.load_media(path, (72, 72))[0][0])
                return
            except OSError:
                pass
        self.tile.set_image(None)
        self.tile.setText("+")

    def _clicked(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            menu = RoundMenu(parent=self)
            menu.addAction(Action(FluentIcon.FOLDER, "Выбрать...", triggered=self._pick))
            menu.addAction(Action(FluentIcon.DELETE, "Убрать", triggered=lambda: self.set_path(self.on_pick(None))))
            menu.exec(self.tile.mapToGlobal(QPoint(0, self.tile.height())))
        else:
            self._pick()

    def _pick(self) -> None:
        choose_file(self, "Картинка или GIF", MEDIA_FILTER,
                    lambda src: self.set_path(self.on_pick(src)))



def slot_grid(slots: list[MediaSlot]) -> SimpleCardWidget:
    box = SimpleCardWidget()
    flow = FlowLayout(box)  # wraps to the next row in a narrow window
    flow.setContentsMargins(16, 14, 16, 14)
    flow.setHorizontalSpacing(14)
    flow.setVerticalSpacing(12)
    for s in slots:
        flow.addWidget(s)
    return box


class TimesGatePage(Page):
    _faces_ready = Signal(object)

    def __init__(self, settings: Settings, tg: TimesGateEngine, request_preview, parent=None, *, connection_only=False):
        super().__init__("timesgate", "Times Gate",
                         "",
                         parent)
        title = self.layout_.itemAt(0).widget()
        self.layout_.removeWidget(title)
        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(title)
        self.connection_dot = TitleStatusDot(title)
        self.connection_dot.setToolTip("Не подключено")
        title_layout.addWidget(self.connection_dot)
        title_layout.addStretch()
        self.layout_.insertWidget(0, title_row)
        self.connection_only = connection_only
        self.settings, self.tg = settings, tg
        self.request_preview = request_preview  # rendered off the GUI thread by the window
        s = settings

        # ---- preview ---------------------------------------------------------
        self.head = QWidget()
        hl = QVBoxLayout(self.head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        top = QHBoxLayout()
        self.switcher = ThemeSwitcher(lambda step: self.select_theme((self.current_index() + step)
                                                                     % len(self.themes())), 220)
        self.device_btn = PushButton(FluentIcon.POWER_BUTTON, "Встроенный циферблат")
        self.device_btn.clicked.connect(self.toggle_device_face)
        self.tg_status = CaptionLabel("")
        top.addWidget(self.switcher)
        top.addStretch()
        self.tg_status.hide()
        top.addSpacing(12)
        self.device_btn.hide()
        # Status lives next to the page title; built-in mode is selected under Screens.
        self.tiles_box = QWidget()
        row = QHBoxLayout(self.tiles_box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.tiles = [PixelPreview(104) for _ in range(5)]
        for t in self.tiles:
            row.addWidget(t)
        row.addStretch()
        hl.addWidget(self.tiles_box)
        self.device_note = CaptionLabel("Экранами управляет сам Times Gate — встроенный циферблат. "
                                        "Программа их не трогает.")
        self.device_note.setTextColor("#707070", "#9a9a9a")
        hl.addWidget(self.device_note)
        self.add(self.head)

        # ---- connection -------------------------------------------------------
        self.conn_group = g = self.group("Подключение")
        self.ip = LineEdit()
        self.ip.setPlaceholderText("192.168.1.50")
        self.ip.setText(s.tg_ip or (os.environ.get("DIVOOM_TEST_GATE_IP", "") if TEST_MODE else ""))
        self.ip.setFixedWidth(170)
        self.ip.editingFinished.connect(self.commit_connection)
        self.find_btn = PushButton(FluentIcon.SEARCH, "Найти")
        self.find_btn.clicked.connect(self.find_devices)
        g.addSettingCard(card(FluentIcon.WIFI, "IP-адрес",
                              "«Найти» ищет устройства Divoom в вашей сети", self.ip, self.find_btn))
        self.token = PasswordLineEdit()
        self.token.setPlaceholderText("число из приложения Divoom")
        self.token.setText(s.tg_token or (os.environ.get("DIVOOM_TEST_GATE_TOKEN", "") if TEST_MODE else ""))
        self.token.setFixedWidth(220)
        self.token.editingFinished.connect(self.commit_connection)
        g.addSettingCard(card(FluentIcon.FINGERPRINT, "LocalToken",
                              "Приложение Divoom → Times Gate → настройки устройства", self.token))
        self.connect_btn = reconnect = PushButton("Подключить")
        reconnect.clicked.connect(self.connect_device)
        self.status_card = card(FluentIcon.CONNECT, "Состояние", "—", reconnect)
        g.addSettingCard(self.status_card)

        if connection_only:
            self.connection_open = True
            for i in range(self.layout_.count()):
                widget = self.layout_.itemAt(i).widget()
                if widget and widget is not self.conn_group:
                    widget.hide()
            return  # do not construct a gallery or start its background workers

        # ---- screens -------------------------------------------------------------
        self.screens_group = g = self.group("Экраны")
        self.mode_combo = combo(MODES, s.tg_mode, self.set_mode, 330)
        g.addSettingCard(card(FluentIcon.LAYOUT, "Режим", "", self.mode_combo))
        self.card_24h = card(FluentIcon.DATE_TIME, "24-часовой формат", "",
                             switch(s.tg_24h, lambda v: self.save("tg_24h", v)))
        self.card_blink = card(FluentIcon.STOP_WATCH, "Мигающее двоеточие", "",
                               switch(s.tg_blink_colon, lambda v: self.save("tg_blink_colon", v)))
        self.card_cover = card(FluentIcon.ALBUM, "Обложка Spotify вместо двоеточия",
                               "Пока играет музыка, в центре обложка трека",
                               switch(s.tg_center_cover, lambda v: self.save("tg_center_cover", v)))
        for c in (self.card_24h, self.card_blink, self.card_cover):
            g.addSettingCard(c)

        # ---- built-in face (mode "device") --------------------------------------------------
        self.face_group = g = self.group("Встроенный циферблат")
        self.face_combo = ComboBox()
        self.face_combo.setMinimumWidth(260)
        self.fill_faces(BUILTIN_FACES)
        self.face_combo.currentIndexChanged.connect(self.commit_face)
        g.addSettingCard(card(FluentIcon.POWER_BUTTON, "Циферблат Times Gate",
                              "Идёт на самом устройстве, компьютер не нужен", self.face_combo))
        self._faces_ready.connect(self.fill_faces)
        def load_faces():
            faces = whole_faces()
            try:
                self._faces_ready.emit(faces)
            except RuntimeError:
                pass  # the setup dialog may have closed while discovery was running
        threading.Thread(target=load_faces, daemon=True).start()

        # ---- faces gallery + editor (clock modes) -------------------------------------------
        self.faces_box = SimpleCardWidget()
        fl = QVBoxLayout(self.faces_box)
        fl.setContentsMargins(16, 12, 16, 12)
        self.layout_.removeWidget(self.head)
        fl.addWidget(self.head)
        fl.setSpacing(12)
        bar = QHBoxLayout()
        title = SubtitleLabel("Циферблаты")
        new_btn = PushButton(FluentIcon.ADD, "Новый пак")
        new_btn.setToolTip("Свой набор картинок для цифр 0–9 и «:»")
        new_btn.clicked.connect(self.new_pack)
        import_btn = PushButton(FluentIcon.FOLDER, "Импорт пака")
        import_btn.clicked.connect(self.import_pack)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(import_btn)
        bar.addWidget(new_btn)
        fl.addSpacing(10)
        fl.addLayout(bar)
        self.gallery = ThemeGallery()
        self.gallery.selected.connect(self.select_theme)
        self.gallery.moved.connect(self.reorder_themes)
        self.gallery.edit.connect(self.open_editor)
        self.gallery.duplicate.connect(self.duplicate_theme)
        self.gallery.export.connect(self.export_pack)
        self.gallery.delete.connect(self.delete_theme)
        fl.addWidget(self.gallery)

        self.editor = g = SettingCardGroup("Выбранный циферблат", self.faces_box)
        fl.addSpacing(10)
        fl.addWidget(g)
        self.theme_name = LineEdit()
        self.theme_name.setFixedWidth(220)
        self.theme_name.editingFinished.connect(self.rename_theme)
        g.addSettingCard(card(FluentIcon.EDIT, "Название", "", self.theme_name))
        self.style_combo = combo(digits.STYLES, "", lambda v: self.edit_theme("style", v), 220)
        g.addSettingCard(card(FluentIcon.FONT, "Стиль", "", self.style_combo))
        self.follow_switch = switch(s.tg_face_follow_cover, self.commit_face_follow_cover)
        self.card_follow = card(FluentIcon.ALBUM, "Циферблат под цвет обложки",
                                "Цвет из обложки; без музыки — выбранные цвета циферблата",
                                self.follow_switch)

        self.colors_box = SimpleCardWidget()
        self.colors_flow = FlowLayout(self.colors_box)
        self.colors_flow.setContentsMargins(16, 12, 16, 12)
        self.colors_flow.setHorizontalSpacing(18)
        self.colors_flow.setVerticalSpacing(10)
        fl.addWidget(self.colors_box)
        self._colors_key = None
        self.pack_label = StrongBodyLabel("Картинки пака")
        fl.addWidget(self.pack_label)
        self.char_slots = {ch: MediaSlot(ch, "", lambda src, c=ch: self.set_pack_char(c, src))
                           for ch in digits.CHARS}
        self.pack_box = slot_grid(list(self.char_slots.values()))
        fl.addWidget(self.pack_box)
        self.add(self.faces_box)

        # ---- side pictures (mode "gifs_clock") ----------------------------------------------
        self.side_box = QWidget()
        sl = QVBoxLayout(self.side_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        side_title = SubtitleLabel("Картинки по бокам")
        sl.addSpacing(10)
        sl.addWidget(side_title)
        names = ["Экран 1", "Экран 2", "Экран 4", "Экран 5"]
        side = (list(s.tg_side_media) + [""] * 4)[:4]
        self.side_slots = [MediaSlot(names[i], side[i], lambda src, i=i: self.set_side(i, src))
                           for i in range(4)]
        sl.addWidget(slot_grid(self.side_slots))
        self.add(self.side_box)

        # ---- lights -------------------------------------------------------------
        self.lights_group = g = self.group("Подсветка")
        self.card_light_on = card(FluentIcon.POWER_BUTTON, "Подсветка включена", "",
                                  switch(s.tg_light_on, lambda v: self.save_light("tg_light_on", v)))
        self.zone_combo = combo(LIGHT_ZONES, s.tg_light_zone, self.commit_zone, 200)
        self.card_zone = card(FluentIcon.LAYOUT, "Зона", "У задней подсветки свой набор эффектов",
                              self.zone_combo)
        self.effect_combo = ComboBox()
        self.effect_combo.setMinimumWidth(240)
        self.effect_combo.currentIndexChanged.connect(self.commit_effect)
        self.card_effect = card(FluentIcon.HIGHTLIGHT, "Эффект", "★ — эффект принимает цвет", self.effect_combo)
        self.light_color_picker = light_color = InlineColorPicker(QColor(s.tg_light_color), "Цвет подсветки")
        light_color.colorChanged.connect(lambda c: self.save_light("tg_light_color", c.name().upper()))
        self.card_color = card(FluentIcon.PALETTE, "Цвет", "", light_color)
        self.card_follow_cover = card(FluentIcon.ALBUM, "Подсветка под цвет обложки",
                                      "Пока играет Spotify, цвет берётся с обложки",
                                      switch(s.tg_light_follow_cover,
                                             lambda v: self.save_light("tg_light_follow_cover", v)))
        self.card_cycle = card(FluentIcon.SYNC, "Перебор цветов", "Менять цвет после каждого цикла эффекта",
                               switch(s.tg_light_cycle, lambda v: self.save_light("tg_light_cycle", v)))
        box, light_br = slider(0, 100, s.tg_light_brightness)
        light_br.sliderReleased.connect(lambda: self.save_light("tg_light_brightness", light_br.value()))
        self.card_light_br = card(FluentIcon.BRIGHTNESS, "Яркость подсветки", "", box)
        self.card_keys = card(FluentIcon.HIGHTLIGHT, "Подсветка кнопок", "",
                              switch(s.tg_key_light, lambda v: self.save_light("tg_key_light", v)))
        for c in (self.card_light_on, self.card_effect, self.card_color,
                  self.card_follow_cover, self.card_light_br):
            g.addSettingCard(c)

        box, self.screen_br = slider(0, 100, s.tg_brightness)
        self.screen_br.sliderReleased.connect(self.commit_screen_brightness)
        self.card_screen_br = card(FluentIcon.BRIGHTNESS, "Яркость экранов", "", box)
        self.screens_group.addSettingCard(self.card_screen_br)
        self.light_more_group = self.group("Дополнительные параметры подсветки", collapsible=True)
        for widget in (self.card_zone, self.card_keys, self.card_cycle):
            self.light_more_group.addSettingCard(widget)

        # ---- advanced (collapsed) -------------------------------------------------------
        self.more_group = g = self.group("Дополнительно", collapsible=True)
        self.card_on_exit = card(FluentIcon.CLOSE, "Встроенный циферблат при выходе",
                                 "Чтобы после выхода из программы часы не застыли",
                                 switch(s.tg_device_face_on_exit,
                                        lambda v: self.save_plain("tg_device_face_on_exit", v)))
        g.addSettingCard(self.card_on_exit)
        self.hardware_card = card(FluentIcon.DEVELOPER_TOOLS, "Ревизия железа", "Почти у всех 400",
                              combo({400: "400 (порт 80)", 402: "402 (порт 9000)"}, s.tg_hardware,
                                    self.commit_hardware, 160))
        g.addSettingCard(self.hardware_card)
        # Set up once, the connection is rarely needed again: it goes down, just above
        # "Дополнительно". Until it is set up it is the only thing on the page anyway.
        self.layout_.removeWidget(self.conn_group)
        self.layout_.insertWidget(self.layout_.indexOf(self.more_group), self.conn_group)

        # Connection is edited from Settings; these widgets are reused there.
        self.conn_group.hide()
        self.switcher.hide()
        # Preview and gallery form one visual block.
        self.layout_.removeWidget(self.faces_box)
        self.layout_.insertWidget(self.layout_.indexOf(self.screens_group), self.faces_box)
        self.music_group = self.group("Музыка")
        for widget in (self.card_cover, self.card_follow_cover, self.card_follow):
            self.music_group.addSettingCard(widget)
        self.layout_.removeWidget(self.music_group)
        self.layout_.insertWidget(self.layout_.indexOf(self.lights_group), self.music_group)
        # Pencil-only editor, separate from the device's everyday settings.
        self.editor_page = Page("face_editor", "Редактор циферблата", parent=self)
        for widget in (self.editor, self.colors_box, self.pack_label, self.pack_box):
            fl.removeWidget(widget)
            self.editor_page.add(widget)
        self.palette_note = CaptionLabel("Ручная палитра используется, когда музыка не играет.")
        self.palette_note.setWordWrap(True)
        self.editor_page.layout_.insertWidget(3,self.palette_note)
        close = PushButton("Готово")
        close.clicked.connect(lambda: self.window().switchTo(self.window().timesgate))
        self.editor_page.add(close)
        self.editor_page.hide()
        setup = PushButton(FluentIcon.CONNECT, "Настроить подключение")
        setup.clicked.connect(lambda: self.window().open_connection("timesgate"))
        self.setup_hint = card(FluentIcon.WIFI, "Times Gate ещё не настроен",
                               "Подключите устройство, чтобы выбрать циферблат и настроить подсветку", setup)
        self.add(self.setup_hint)
        self.reload_gallery()
        self.fill_effects()
        self.update_visibility()

    # ---- what is shown ---------------------------------------------------------

    def update_visibility(self) -> None:
        if self.connection_only:
            return
        s = self.settings
        show(self.hardware_card, s.developer_mode)
        configured = bool(s.tg_ip and s.tg_token)
        show(self.setup_hint, not configured)
        mode = s.tg_mode
        clock = mode in CLOCK_MODES
        show(self.head, configured)
        for w in (self.screens_group, self.lights_group, self.light_more_group, self.more_group):
            show(w, configured)
        show(self.faces_box, configured and clock)
        show(self.side_box, configured and mode == "gifs_clock")
        show(self.face_group, configured and mode == "device")
        self.switcher.hide()
        self.conn_group.setVisible(getattr(self, "connection_open", False))
        show(self.music_group, configured)
        self.gallery.compact = mode == "gifs_clock"
        show(self.tiles_box, mode != "device")  # the device draws its own face, not ours
        show(self.device_note, mode == "device")
        show(self.card_on_exit, mode not in ("device", "off"))
        self.device_btn.setText("Свои часы" if mode == "device" else "Встроенный циферблат")
        self.device_btn.setToolTip("Вернуть циферблаты программы" if mode == "device"
                                   else "Отдать экраны самому Times Gate: часы идут и без компьютера")
        show(self.card_24h, clock)
        show(self.card_blink, clock)
        show(self.card_cover, mode == "clock")
        # lights unfold step by step
        managed, on = True, s.tg_light_on
        takes_color = any(eid == s.tg_light_effect and colored
                          for eid, _, colored in effects_for_zone(s.tg_light_zone))
        show(self.card_light_on, managed)
        for c in (self.card_zone, self.card_effect, self.card_light_br, self.card_keys):
            show(c, managed and on)
        for c in (self.card_color, self.card_cycle):
            show(c, managed and on and takes_color)
        show(self.card_cycle, managed and on and takes_color and not s.tg_light_follow_cover)
        self.light_color_picker.setEnabled(True)
        self.card_color.setContent("Используется, пока музыка не играет" if s.tg_light_follow_cover else "Постоянный цвет подсветки")
        show(self.card_follow_cover, True)
        self.card_follow_cover.setEnabled(managed and on and takes_color)
        self.card_follow_cover.setContent("Цвет из обложки; чёрно-белая обложка — белый свет" if managed and on and takes_color else "Включите управление подсветкой и выберите цветной эффект ★")
        show(self.card_follow, clock and self.current().get("style") in digits.FOLLOW_LIGHT_STYLES)
        show(self.card_screen_br, True)
        self.layout_.invalidate()
        self.view.updateGeometry()

    # ---- helpers --------------------------------------------------------------

    def save_plain(self, key: str, value) -> None:
        setattr(self.settings, key, value)
        self.settings.save()

    def save(self, key: str, value) -> None:
        self.save_plain(key, value)
        self.tg.refresh()
        self.request_preview()

    def save_light(self, key: str, value) -> None:
        self.save_plain(key, value)
        self.tg.apply_lights()
        self.update_visibility()

    def set_mode(self, mode: str) -> None:
        self.tg.set_mode(mode)  # emits tg_mode -> update_visibility

    def toast(self, title: str, text: str, ok: bool = True) -> None:
        (InfoBar.success if ok else InfoBar.error)(title, text, duration=3000, parent=self.window(),
                                                   position=InfoBarPosition.TOP_RIGHT)

    def show_preview(self, images, theme: str) -> None:
        for tile, img in zip(self.tiles, images):
            tile.set_image(img)
            if img is None:
                tile.setText("—")
        self.switcher.set_name(theme)

    # ---- connection -------------------------------------------------------------

    def connect_device(self):
        self.commit_connection()
        if not self.settings.tg_ip or not self.settings.tg_token:
            self.status_card.setContent("Введите IP-адрес и LocalToken")
            return
        self.tg.reconnect()

    def commit_connection(self) -> None:
        ip, token = self.ip.text().strip(), self.token.text().strip()
        if token and not token.isdigit():
            self.status_card.setContent("LocalToken — это число")
            return
        if (ip, token) != (self.settings.tg_ip, self.settings.tg_token):
            self.settings.tg_ip, self.settings.tg_token = ip, token
            self.settings.save()
            self.tg.reconnect()
            self.update_visibility()

    def commit_hardware(self, value: int) -> None:
        self.settings.tg_hardware = value
        self.settings.save()
        self.tg.reconnect()

    def find_devices(self) -> None:
        self.find_btn.setEnabled(False)
        self.find_btn.setText("Поиск...")

        def run() -> None:
            try:
                found = discover()
            except TimesGateError as e:
                found, error = [], str(e)
            else:
                error = ""
            self.window().bridge.event.emit("tg_found", (found, error))
        threading.Thread(target=run, daemon=True).start()

    def show_found(self, found, error: str) -> None:
        self.find_btn.setEnabled(True)
        self.find_btn.setText("Найти")
        if not found:
            self.status_card.setContent(error or "Устройства не найдены — введите IP вручную")
            return
        menu = RoundMenu(parent=self)
        for dev in found:
            menu.addAction(Action(FluentIcon.WIFI, f"{dev.name}  —  {dev.ip}",
                                  triggered=lambda _=False, d=dev: self.use_device(d)))
        menu.exec(self.find_btn.mapToGlobal(QPoint(0, self.find_btn.height())))

    def use_device(self, dev) -> None:
        self.ip.setText(dev.ip)
        self.settings.tg_mac = dev.mac
        self.commit_connection()

    # ---- faces / packs ----------------------------------------------------------

    def open_editor(self, index):
        self.select_theme(index)
        self.window().open_internal_page(self.editor_page)

    def themes(self) -> list[dict]:
        if not self.settings.tg_themes:
            self.settings.tg_themes = [dict(t) for t in digits.DEFAULT_THEMES]
        return self.settings.tg_themes

    def current_index(self) -> int:
        return self.settings.tg_theme % len(self.themes())

    def current(self) -> dict:
        return self.themes()[self.current_index()]

    def reload_gallery(self) -> None:
        self.gallery.compact = self.settings.tg_mode == "gifs_clock"
        self.gallery.set_themes(self.themes(), self.current_index())
        self.show_editor()

    def show_editor(self) -> None:
        theme = self.current()
        style = theme.get("style")
        self.theme_name.setText(theme["name"])
        self.style_combo.blockSignals(True)
        styles = list(digits.STYLES)
        self.style_combo.setCurrentIndex(styles.index(style) if style in styles else 0)
        self.style_combo.blockSignals(False)
        self.follow_switch.blockSignals(True)
        self.follow_switch.setChecked(self.settings.tg_face_follow_cover)
        self.follow_switch.blockSignals(False)
        show(self.card_follow, style in digits.FOLLOW_LIGHT_STYLES)
        self.palette_note.setText("Ручная палитра используется, пока музыка не играет; во время музыки цвета берутся из обложки." if self.settings.tg_face_follow_cover else "Ручная палитра циферблата.")
        self.show_colors(theme)
        is_pack = style == "custom"
        show(self.pack_label, is_pack)
        show(self.pack_box, is_pack)
        chars = theme.get("chars") or {}
        for ch, slot in self.char_slots.items():
            slot.set_path(chars.get(ch, ""))
        self.switcher.set_name(theme["name"])

    def show_colors(self, theme: dict) -> None:
        """Pickers only for colours that change something right now."""
        roles = digits.editable_roles(dict(theme, follow_light=False))
        key = (theme.get("style"), tuple(r[0] for r in roles))
        defaults = {role: default for role, _, default in roles}
        if key == self._colors_key and self.colors_flow.count():
            for picker, role in self._pickers:  # same set: only update values
                picker.blockSignals(True)
                picker.setColor(QColor(theme.get(role) or defaults[role]))
                picker.blockSignals(False)
            return
        while self.colors_flow.count():
            widget = self.colors_flow.takeAt(0)  # this FlowLayout returns the widget itself
            if widget is not None:
                widget.hide()  # gone at once; deleteLater only runs in the event loop
                widget.setParent(None)
                widget.deleteLater()
        self._pickers = []
        for role, label, default in roles:
            cell = QWidget()
            lay = QHBoxLayout(cell)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            picker = InlineColorPicker(QColor(theme.get(role) or default), label)
            picker.setFixedWidth(64)
            picker.colorChanged.connect(lambda c, r=role: self.edit_theme(r, c.name().upper()))
            lay.addWidget(BodyLabel(label))
            lay.addWidget(picker)
            self.colors_flow.addWidget(cell)
            self._pickers.append((picker, role))
        self._colors_key = key
        show(self.colors_box, bool(roles))

    def commit_face_follow_cover(self, value):
        self.save("tg_face_follow_cover", value)
        self.show_editor()

    def reorder_themes(self, source, target):
        themes = self.themes()
        if not (0 <= source < len(themes) and 0 <= target < len(themes)) or source == target:
            return
        active = self.current()
        themes.insert(target,themes.pop(source))
        self.settings.tg_theme = next(i for i,t in enumerate(themes) if t is active)
        self.settings.save()
        self.reload_gallery()

    def select_theme(self, index: int) -> None:
        self.settings.tg_theme = index
        self.settings.save()
        if self.settings.tg_mode not in CLOCK_MODES:
            self.tg.set_mode("clock")  # picking a face means "draw it"
        self.gallery.set_current(self.themes(), index)
        self.show_editor()
        self.tg.refresh()
        self.request_preview()
        self.window().on_event("tg_theme", self.current()["name"])  # tray, home page

    def edit_theme(self, key: str, value) -> None:
        self.current()[key] = value
        self.save("tg_themes", self.settings.tg_themes)
        self.gallery.set_current(self.themes(), self.current_index())
        self.gallery.refresh_thumbnails(self.themes(), only=self.current_index())
        if key in ("style", "follow_light"):
            self.show_editor()

    def rename_theme(self) -> None:
        name = self.theme_name.text().strip()
        if name and name != self.current()["name"]:
            self.edit_theme("name", name)

    def add_theme(self, theme: dict) -> None:
        self.themes().append(theme)
        self.settings.tg_theme = len(self.themes()) - 1
        self.save("tg_themes", self.settings.tg_themes)
        self.reload_gallery()

    def new_pack(self) -> None:
        count = sum(1 for t in self.themes() if t.get("style") == "custom") + 1
        self.add_theme(packs.new_pack(f"Мой пак {count}"))
        self.toast("Новый пак", "Нажмите на слоты ниже и выберите картинки или GIF для цифр")

    def duplicate_theme(self, index: int) -> None:
        src = self.themes()[index]
        copy = packs.new_pack(f"{src['name']} (копия)", src) if src.get("style") == "custom" \
            else {k: v for k, v in src.items() if k != "id"} | {"name": f"{src['name']} (копия)"}
        self.add_theme(copy)

    def delete_theme(self, index: int) -> None:
        if len(self.themes()) <= 1:
            return
        theme = self.themes().pop(index)
        packs.delete_pack_files(theme)
        self.settings.tg_theme = min(self.settings.tg_theme, len(self.themes()) - 1)
        self.save("tg_themes", self.settings.tg_themes)
        self.reload_gallery()

    def export_pack(self, index: int) -> None:
        theme = self.themes()[index]
        choose_file(self, "Экспорт пака", PACK_FILTER,
                    lambda path: self._export_pack(theme,path), save=True, suggested=f"{theme['name']}.zip")

    def _export_pack(self, theme, path):
        try:
            packs.export_pack(theme, path)
            self.toast("Пак сохранён", Path(path).name)
        except OSError as e:
            self.toast("Ошибка экспорта", str(e), ok=False)

    def import_pack(self):
        choose_file(self,"Импорт пака",PACK_FILTER,self._import_pack)

    def _import_pack(self, path):
        try:
            theme = packs.import_pack(path)
        except packs.PackError as e:
            self.toast("Не получилось", str(e), ok=False)
            return
        self.add_theme(theme)
        self.toast("Пак добавлен", theme["name"])

    def set_pack_char(self, ch: str, source: str | None) -> str:
        theme = self.current()
        packs.set_char(theme, ch, source)
        self.save("tg_themes", self.settings.tg_themes)
        self.gallery.refresh_thumbnails(self.themes(), only=self.current_index())
        return (theme.get("chars") or {}).get(ch, "")

    def set_side(self, index: int, source: str | None) -> str:
        side = (list(self.settings.tg_side_media) + [""] * 4)[:4]
        for old in MEDIA_DIR.glob(f"side_{index}.*"):
            old.unlink(missing_ok=True)
        path = ""
        if source:
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            dst = MEDIA_DIR / f"side_{index}{Path(source).suffix.lower()}"
            shutil.copyfile(source, dst)  # a private copy survives the original being moved
            path = str(dst)
        side[index] = path
        self.save("tg_side_media", side)
        return path

    # ---- built-in face -------------------------------------------------------------------

    def fill_faces(self, faces: dict) -> None:
        self.face_combo.blockSignals(True)
        self.face_combo.clear()
        for face_id, name in faces.items():
            self.face_combo.addItem(f"{name}  ·  {face_id}", userData=face_id)
        if self.settings.tg_device_face not in faces:
            self.face_combo.addItem(f"Сохранённый · {self.settings.tg_device_face}",
                                    userData=self.settings.tg_device_face)
        self.face_combo.setCurrentIndex(max(self.face_combo.findData(self.settings.tg_device_face), 0))
        self.face_combo.blockSignals(False)

    def commit_face(self, index: int) -> None:
        if index >= 0:
            self.save_plain("tg_device_face", self.face_combo.itemData(index))
            if self.settings.tg_mode == "device":
                self.tg.refresh()  # switch to the newly chosen face right away

    def toggle_device_face(self) -> None:
        if self.settings.tg_mode == "device":
            self.tg.set_mode("clock")
            return
        self.tg.set_mode("device")
        self.toast("Встроенный циферблат", "Times Gate работает сам, программа не трогает экраны")

    # ---- lights / brightness ----------------------------------------------------------

    def fill_effects(self) -> None:
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        effects = effects_for_zone(self.settings.tg_light_zone)
        for eid, name, colored in effects:
            self.effect_combo.addItem(f"{name} ★" if colored else name, userData=eid)
        ids = [e[0] for e in effects]
        self.effect_combo.setCurrentIndex(ids.index(self.settings.tg_light_effect)
                                          if self.settings.tg_light_effect in ids else 0)
        self.effect_combo.blockSignals(False)

    def commit_zone(self, zone: int) -> None:
        self.settings.tg_light_zone = zone
        self.fill_effects()
        self.save_light("tg_light_effect", self.effect_combo.currentData())

    def commit_effect(self, index: int) -> None:
        if index >= 0:
            self.save_light("tg_light_effect", self.effect_combo.itemData(index))

    def commit_screen_brightness(self) -> None:
        self.save_plain("tg_brightness", self.screen_br.value())
        self.tg.apply_brightness()

    # ---- events ---------------------------------------------------------------------

    def on_event(self, name: str, payload) -> None:
        if self.connection_only and name not in ("tg", "tg_ip", "tg_found"):
            return
        if name == "tg":
            connected, text = payload
            self.status_card.setContent(("● " if connected else "○ ") + text)
            self.tg_status.setText(("● " if connected else "○ ") + text)
            self.connect_btn.setText("Переподключить" if connected else "Подключить")
            self.connection_dot.set_connected(connected, text)
        elif name == "tg_theme":  # also from tray / home page
            self.gallery.set_current(self.themes(), self.current_index())
            self.show_editor()
        elif name == "tg_mode":
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(list(MODES).index(payload))
            self.mode_combo.blockSignals(False)
            self.gallery.compact = self.settings.tg_mode == "gifs_clock"
            self.gallery.refresh_thumbnails(self.themes())
            self.update_visibility()
        elif name == "tg_preview":
            self.show_preview(*payload)
        elif name == "tg_ip":
            self.ip.setText(str(payload))
        elif name == "tg_found":
            self.show_found(*payload)
