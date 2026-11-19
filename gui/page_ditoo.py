from __future__ import annotations

from qfluentwidgets import ComboBox, FluentIcon, PrimaryPushButton, PushButton, SpinBox, TransparentToolButton

from bluetooth import ditoo_commands as cmd
from bluetooth.connection import DitooConnection
from core.player import Engine
from core.settings import Settings

from .widgets import choose_file, Page, card, combo, show, slider, switch


class DitooPage(Page):
    def __init__(self, settings: Settings, engine: Engine, parent=None):
        super().__init__("ditoo", "Ditoo Pro",
                         "Обложка текущего трека на экране Ditoo по Bluetooth. "
                         "Пока музыка не играет, Ditoo не трогается.", parent)
        self.settings, self.engine = settings, engine
        s = settings

        self.device_group = g = self.group("Устройство")
        self.device_combo = ComboBox()
        self.device_combo.setMinimumWidth(280)
        refresh = TransparentToolButton(FluentIcon.SYNC)
        refresh.setToolTip("Обновить список")
        refresh.clicked.connect(self.refresh_devices)
        g.addSettingCard(card(FluentIcon.BLUETOOTH, "Устройство",
                              "Спаренный в Windows DitooPro-Audio", self.device_combo, refresh))
        self.show_all = switch(False, lambda _: self.refresh_devices())
        self.show_all_card = card(FluentIcon.VIEW, "Показывать все Bluetooth-устройства",
                                  "Ditoo не нашёлся по имени — выберите его из полного списка", self.show_all)
        g.addSettingCard(self.show_all_card)
        self.connect_btn = PrimaryPushButton("Подключить")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.status_card = card(FluentIcon.CONNECT, "Состояние", "○ Не подключено", self.connect_btn)
        g.addSettingCard(self.status_card)
        g.addSettingCard(card(FluentIcon.SYNC, "Подключаться автоматически",
                              "Подхватывать Ditoo через несколько секунд после включения",
                              switch(s.auto_reconnect, lambda v: self.save("auto_reconnect", v))))
        box, self.brightness = slider(0, 100, s.brightness)
        self.brightness.sliderReleased.connect(self.commit_brightness)
        self.brightness_card = card(FluentIcon.BRIGHTNESS, "Яркость экрана", "", box)
        self.screen_group = self.group("Экран")
        self.screen_group.addSettingCard(self.brightness_card)

        g = self.group("Обработка обложки", collapsible=True)
        self.art_sliders = {}
        for key, icon, title in (("contrast", FluentIcon.CONSTRACT, "Контраст"),
                                 ("saturation", FluentIcon.PALETTE, "Насыщенность"),
                                 ("art_brightness", FluentIcon.BRIGHTNESS, "Яркость картинки")):
            box, sl = slider(0, 200, round(getattr(s, key) * 100))
            sl.sliderReleased.connect(self.commit_artwork)
            self.art_sliders[key] = sl
            g.addSettingCard(card(icon, title, "100 — без изменений", box))
        reset = PushButton("Сбросить")
        reset.clicked.connect(self.reset_artwork)
        g.addSettingCard(card(FluentIcon.RETURN, "Настройки обложки по умолчанию", "", reset))

        g = self.group("Когда музыка не играет")
        self.idle_combo = combo({k: v[0] for k, v in cmd.DISPLAY_MODES.items()}, s.idle_mode,
                                self.commit_idle_mode)
        test = PushButton("Проверить")
        test.clicked.connect(self.try_idle_mode)
        g.addSettingCard(card(FluentIcon.HOME, "Режим Ditoo", "Включается один раз после остановки музыки",
                              self.idle_combo, test))
        delay = SpinBox()
        delay.setRange(0, 600)
        delay.setSuffix(" с")
        delay.setValue(s.idle_delay_s)
        delay.valueChanged.connect(lambda v: self.save("idle_delay_s", v))
        self.delay_card = card(FluentIcon.STOP_WATCH, "Задержка", "Короткая пауза не переключает экран", delay)
        g.addSettingCard(self.delay_card)

        self.manual_group = g = self.group("Ручные тесты", collapsible=True)
        for icon, title, text, handler in (
            (FluentIcon.PHOTO, "Тестовая картинка", "Показать", engine.show_test_pattern),
            (FluentIcon.FOLDER, "Картинка из файла", "Выбрать...", self.pick_image),
            (FluentIcon.BROOM, "Очистить экран", "Очистить", engine.clear_display),
        ):
            b = PushButton(text)
            b.clicked.connect(handler)
            g.addSettingCard(card(icon, title, "", b))
        lights = []
        for text, action in (("Вкл/выкл", cmd.KeyboardLight.TOGGLE), ("← Эффект", cmd.KeyboardLight.PREV),
                             ("Эффект →", cmd.KeyboardLight.NEXT)):
            b = PushButton(text)
            b.clicked.connect(lambda _=False, a=action: engine.keyboard_light(a))
            lights.append(b)
        g.addSettingCard(card(FluentIcon.HIGHTLIGHT, "Подсветка клавиш", "Стоковая прошивка умеет только эффекты",
                              *lights))
        setup = PushButton(FluentIcon.CONNECT, "Настроить подключение")
        setup.clicked.connect(lambda: self.window().open_connection("ditoo"))
        self.setup_hint = card(FluentIcon.BLUETOOTH, "Ditoo Pro ещё не выбран",
                               "Выберите спаренное Bluetooth-устройство", setup)
        self.layout_.insertWidget(3, self.setup_hint)
        self.connected = False
        self.refresh_devices()
        self.update_visibility()

    def update_visibility(self) -> None:
        show(self.setup_hint, not self.settings.ditoo_address)
        self.device_group.setVisible(getattr(self, "connection_open", False))
        show(self.screen_group, self.connected)
        show(self.delay_card, self.settings.idle_mode != "keep")
        show(self.manual_group, self.connected and self.settings.developer_mode)
        self.layout_.invalidate()
        self.view.updateGeometry()

    # ---- actions ---------------------------------------------------------

    def save(self, key: str, value) -> None:
        setattr(self.settings, key, value)
        self.settings.save()

    def refresh_devices(self) -> None:
        current = self.device_combo.currentData() or self.settings.ditoo_address
        self.device_combo.clear()
        found = DitooConnection.scan(include_all=self.show_all.isChecked())
        for d in found:
            self.device_combo.addItem(f"{d.name}  ({d.address})", userData=d.address)
        # the full list is only a fallback for a Ditoo with an unusual name
        show(self.show_all_card, self.show_all.isChecked() or not found)
        saved = self.settings.ditoo_address
        if saved and self.device_combo.findData(saved) < 0:
            self.device_combo.addItem(f"Сохранённое ({saved})", userData=saved)
        if self.device_combo.count() == 0:
            self.device_combo.addItem("Нет спаренных Divoom", userData=None)
        self.device_combo.setCurrentIndex(max(self.device_combo.findData(current), 0))

    def toggle_connection(self) -> None:
        if self.connect_btn.text() == "Отключить":
            self.engine.disconnect_ditoo()
        elif self.device_combo.currentData():
            self.engine.connect_ditoo(self.device_combo.currentData())

    def commit_brightness(self) -> None:
        self.save("brightness", self.brightness.value())
        self.engine.apply_brightness()

    def commit_artwork(self) -> None:
        for key, sl in self.art_sliders.items():
            setattr(self.settings, key, sl.value() / 100)
        self.settings.save()
        self.engine.refresh_artwork()

    def commit_idle_mode(self, value: str) -> None:
        self.save("idle_mode", value)
        self.update_visibility()

    def reset_artwork(self) -> None:
        defaults = Settings()
        for key, sl in self.art_sliders.items():
            sl.setValue(round(getattr(defaults, key) * 100))
        self.commit_artwork()

    def try_idle_mode(self) -> None:
        if self.settings.idle_mode != "keep":
            self.engine.set_display_mode(self.settings.idle_mode)

    def pick_image(self) -> None:
        choose_file(self, "Картинка для Ditoo", "Изображения (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
                    self.engine.show_file)

    # ---- events ----------------------------------------------------------

    def on_event(self, name: str, payload) -> None:
        if name == "ditoo":
            connected, text = payload
            self.status_card.setContent(("● " if connected else "○ ") + text)
            self.connect_btn.setText("Отключить" if connected else "Подключить")
            if connected != self.connected:
                self.connected = connected
                self.update_visibility()
