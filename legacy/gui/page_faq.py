"""FAQ: about the program, authors, version, common questions, licences."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QGridLayout, QLabel
from qfluentwidgets import BodyLabel, CaptionLabel, SimpleCardWidget, IconWidget, FluentIcon, SubtitleLabel, TitleLabel

from core.version import APP_NAME, APP_VERSION, RELEASE_DATE

from .widgets import FoldGroup, Page

AUTHORS = [("Разработчик", "iriskaaf")]

QUESTIONS = [
    ("Ditoo не подключается",
     "Спарьте в Windows устройство «DitooPro-Audio» (Параметры → Bluetooth). Ditoo держит одно "
     "управляющее соединение: если рядом телефон с приложением Divoom, выключите на нём Bluetooth."),
    ("Обложка не появляется на Ditoo",
     "Обложка отправляется, только пока музыка играет; пока не играет, Ditoo нарочно не трогается. "
     "Смотрите «Состояние» в «Настройки → Музыка» и переключатель «Следить за музыкой»."),
    ("Медиасессия или Spotify Web API",
     "Медиасессия берёт трек и обложку у приложения Spotify на этом компьютере через Windows: "
     "мгновенно, без интернета, входа и лимитов. Web API нужен, только если музыка играет на другом "
     "устройстве (телефон, колонка). Spotify ограничивает частоту запросов к API, а при "
     "превышении может закрыть доступ на несколько часов."),
    ("Где взять LocalToken для Times Gate",
     "Приложение Divoom → Times Gate → настройки устройства. Это число; IP-адрес можно найти "
     "кнопкой «Найти» на вкладке Times Gate."),
    ("Подсветка чёрно-белых обложек",
     "При подборе по обложке чёрно-белая обложка включает белую подсветку. Для белого используется общий эффект обеих зон; цветная обложка возвращает выбранные зону и эффект."),
    ("Цвет подсветки не берётся с обложки",
     "Включите управление подсветкой и цветной эффект ★ в «Подсветке», затем включите «Подсветка под цвет обложки» в группе «Музыка». Циферблат настраивается независимо там же."),
    ("Часы застыли после выхода из программы",
     "Свои циферблаты рисует программа. Кнопка «Встроенный циферблат» отдаёт экраны самому Times Gate; "
     "его же можно включать автоматически при выходе."),
    ("Где хранятся настройки и логи",
     "Папка профиля доступна в «Настройки → Для разработчиков»: включите режим, затем откройте раздел «Данные». Токен Spotify хранится "
     "в диспетчере учётных данных Windows."),
]

CREDITS = [
    ("Python", "PSF License 2.0"),
    ("PyWinRT / winrt-runtime", "MIT"),
    ("PySide6 / Qt", "LGPL-3.0"),
    ("PySide6-Fluent-Widgets", "GPL-3.0"),
    ("Pillow", "MIT-CMU (HPND)"),
    ("requests", "Apache-2.0"),
    ("keyring", "MIT"),
    ("Шрифты Archivo Black, Unbounded, VT323, Space Mono, Instrument Serif, Press Start 2P, Outfit", "SIL OFL 1.1"),
    ("Протокол Ditoo", "по открытым проектам andreas-mausch, futpib, d03n3rfr1tz3/hass-divoom "
                       "и официальной документации Divoom"),
    ("Протокол Times Gate", "официальная документация Divoom и averhaegen/hacs-divoom-times-gate"),
]


def info_tile(icon, title, value):
    box = SimpleCardWidget()
    box.setFixedSize(132, 132)
    box.setToolTip(title + " · " + value)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(12, 12, 12, 12)
    image = IconWidget(icon)
    image.setFixedSize(24, 24)
    layout.addWidget(image, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addStretch()
    detail = BodyLabel(value)
    detail.setWordWrap(True)
    layout.addWidget(detail)
    label = CaptionLabel(title)
    label.setWordWrap(True)
    label.setTextColor("#606060", "#b8b8b8")
    layout.addWidget(label)
    return box


class FaqPage(Page):
    def __init__(self, parent=None):
        super().__init__("faq", "О программе", "Часы, обложки и подсветка ваших Divoom.", parent)
        from .tray import app_icon
        header = SimpleCardWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 20, 24, 20)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(64, 64))
        row.addWidget(icon)
        text = QVBoxLayout()
        text.addWidget(TitleLabel(APP_NAME))
        text.addWidget(CaptionLabel(f"Версия {APP_VERSION} · {RELEASE_DATE}"))
        row.addLayout(text, 1)
        self.add(header)
        from core.profile import TEST_MODE
        self.grid_boxes = []
        summary = [
            (FluentIcon.MUSIC, APP_NAME, "TEST" if TEST_MODE else "Windows"),
            (FluentIcon.INFO, "Версия", f"{APP_VERSION} · {RELEASE_DATE}"),
            (FluentIcon.PEOPLE, "Разработчики", "iriskaaf"),
            (FluentIcon.CONNECT, "Устройства", "Ditoo Pro · Times Gate"),
        ]
        self.add_grid([info_tile(*entry) for entry in summary])
        self.add(SubtitleLabel("Компоненты и лицензии"))
        icons = [FluentIcon.DEVELOPER_TOOLS, FluentIcon.LINK, FluentIcon.VIEW,
                 FluentIcon.PALETTE, FluentIcon.PHOTO, FluentIcon.WIFI,
                 FluentIcon.FINGERPRINT, FluentIcon.FONT, FluentIcon.BLUETOOTH,
                 FluentIcon.DATE_TIME]
        self.add_grid([info_tile(icons[i % len(icons)], "Шрифты" if name.startswith("Шрифты") else name, "Divoom / open source" if name.startswith("Протокол") else licence)
                       for i, (name, licence) in enumerate(CREDITS)])
        self.add(SubtitleLabel("Частые вопросы"))
        for question, answer in QUESTIONS:
            item = FoldGroup(question)
            content = QWidget()
            layout = QVBoxLayout(content)
            layout.setContentsMargins(20, 12, 20, 16)
            label = BodyLabel(answer)
            label.setWordWrap(True)
            layout.addWidget(label)
            item.addGroupWidget(content)
            self.add(item)

    def add_grid(self, tiles):
        box = QWidget()
        layout = QGridLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for i, tile in enumerate(tiles):
            layout.addWidget(tile, i // 5, i % 5)
        layout.setColumnStretch(5, 1)
        box.setFixedHeight(((len(tiles)+4)//5)*132 + ((len(tiles)+4)//5-1)*10)
        self.grid_boxes.append((layout, tiles))
        self.add(box)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = max(1, min(6, (self.viewport().width()-38) // 142))
        for layout, tiles in getattr(self, "grid_boxes", []):
            if layout.property("columns") == columns:
                continue
            layout.setProperty("columns", columns)
            for tile in tiles:
                layout.removeWidget(tile)
            for col in range(7):
                layout.setColumnStretch(col, 0)
            for i, tile in enumerate(tiles):
                layout.addWidget(tile, i // columns, i % columns)
            # Only the trailing empty column stretches: card gaps stay 10 px.
            layout.setColumnStretch(columns, 1)
            rows = (len(tiles)+columns-1)//columns
            layout.parentWidget().setFixedHeight(rows*132 + (rows-1)*10)
