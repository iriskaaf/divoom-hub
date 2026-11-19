"""Gallery of clock faces: a grid of cards with live thumbnails."""

from __future__ import annotations

import threading

from PySide6.QtCore import QPoint, Qt, Signal, QMimeData
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (Action, BodyLabel, CaptionLabel, CardWidget, FlowLayout, FluentIcon,
                            IconWidget, RoundMenu, themeColor, TransparentToolButton)

from timesgate import digits

from .widgets import to_pixmap

THUMB_TILE = 40
CARD_W, CARD_H = 236, 100
THEME_MIME = "application/x-divoomhub-theme"


class ThemeCard(CardWidget):
    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setAcceptDrops(True)
        self._dragging = False
        self.setToolTip("Перетащите для изменения порядка. Правый клик — действия.")
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(6)
        self.thumb = QLabel("Загрузка…")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(THUMB_TILE * 5 + 12, THUMB_TILE)
        self.thumb.setStyleSheet("background: #101012; border-radius: 4px; color: #a0a0a0;")
        lay.addWidget(self.thumb)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.check = IconWidget(FluentIcon.ACCEPT_MEDIUM)
        self.check.setFixedSize(14, 14)
        self.name = BodyLabel("")
        self.style_label = CaptionLabel("")
        self.style_label.setTextColor("#707070", "#9a9a9a")
        row.addWidget(self.check)
        row.addWidget(self.name)
        row.addStretch()
        row.addWidget(self.style_label)
        self.edit_button = TransparentToolButton(FluentIcon.EDIT)
        self.edit_button.setToolTip("Редактировать циферблат")
        row.addWidget(self.edit_button)
        lay.addLayout(row)
        self.bar = QWidget(self)  # accent underline for the selected card
        self.bar.setFixedHeight(3)
        self.bar.hide()

    def mousePressEvent(self, event):
        self._press_position = event.position().toPoint()
        self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton and
                hasattr(self, "_press_position") and not self._dragging and
                (event.position().toPoint()-self._press_position).manhattanLength() >= QApplication.startDragDistance()):
            self._dragging = True
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(THEME_MIME,str(self.index).encode("ascii"))
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._dragging:
            super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        source = event.source()
        if isinstance(source,ThemeCard) and source.parentWidget() is self.parentWidget():
            event.acceptProposedAction()

    def dropEvent(self, event):
        source = event.source()
        if isinstance(source,ThemeCard) and source.parentWidget() is self.parentWidget():
            self.parentWidget().moved.emit(source.index,self.index)
            event.acceptProposedAction()

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(e)
        self.bar.setGeometry(14, self.height() - 4, self.width() - 28, 3)

    def set_compact(self, compact):
        self.setFixedSize(148, 132) if compact else self.setFixedSize(CARD_W, CARD_H)
        self.thumb.setFixedSize(124, 76) if compact else self.thumb.setFixedSize(212, 40)
        self.compact = compact
        if hasattr(self, "_full_name"):
            self.name.setText(self.name.fontMetrics().elidedText(self._full_name, Qt.TextElideMode.ElideRight, 74 if compact else 130))

    def set_theme(self, theme: dict, selected: bool) -> None:
        self._full_name = theme["name"]
        metrics = self.name.fontMetrics()
        self.name.setText(metrics.elidedText(theme["name"], Qt.TextElideMode.ElideRight, 74 if getattr(self, "compact", False) else 130))
        self.name.setToolTip(theme["name"])
        style = digits.STYLES.get(theme.get("style", ""), "")
        self.style_label.setText("" if style == theme["name"] else style)
        self.check.setVisible(selected)
        self.bar.setStyleSheet(f"background: {themeColor().name()}; border-radius: 1px;")
        self.bar.setVisible(selected)

    def set_thumbnail(self, image) -> None:
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: transparent;")
        self.thumb.setPixmap(to_pixmap(image, image.width))


class ThemeGallery(QWidget):
    """Emits selected(index) and menu actions: duplicate/export/delete(index)."""

    moved = Signal(int, int)
    edit = Signal(int)
    selected = Signal(int)
    duplicate = Signal(int)
    export = Signal(int)
    delete = Signal(int)
    _thumbs_ready = Signal(int, object, object)  # generation, index, image

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = FlowLayout(self, needAni=False)
        self.flow.setContentsMargins(0, 4, 0, 4)
        self.flow.setHorizontalSpacing(10)
        self.flow.setVerticalSpacing(10)
        self.cards: list[ThemeCard] = []
        self._generation = 0
        self.compact = False
        self._thumbs_ready.connect(self._on_thumb)

    def set_themes(self, themes: list[dict], current: int) -> None:
        """Rebuild cards (when the list changed) and render thumbnails in the background."""
        if len(themes) != len(self.cards):
            for c in self.cards:
                self.flow.removeWidget(c)
                c.deleteLater()
            self.cards = []
            for i in range(len(themes)):
                c = ThemeCard(i, self)
                c.edit_button.clicked.connect(lambda _=False, i=i: self.edit.emit(i))
                c.clicked.connect(lambda i=i: self.selected.emit(i))
                c.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                c.customContextMenuRequested.connect(lambda pos, c=c: self._menu(c, pos))
                self.flow.addWidget(c)
                self.cards.append(c)
        for i, (c, t) in enumerate(zip(self.cards, themes)):
            c.set_theme(t, i == current)
        self.refresh_thumbnails(themes)

    def set_current(self, themes: list[dict], current: int) -> None:
        for i, (c, t) in enumerate(zip(self.cards, themes)):
            c.set_theme(t, i == current)

    def refresh_thumbnails(self, themes: list[dict], only: int | None = None) -> None:
        if only is None:
            self._generation += 1  # a full refresh supersedes the previous full one
        generation = self._generation
        compact = self.compact
        for card in self.cards:
            card.set_compact(compact)
        jobs = [(i, dict(t)) for i, t in enumerate(themes) if only is None or i == only]

        def run() -> None:
            for i, theme in jobs:
                if only is None and generation != self._generation:
                    return
                try:
                    img = digits.theme_thumbnail(theme, tile=72 if compact else THUMB_TILE, compact=compact)
                except Exception:
                    continue
                try:
                    self._thumbs_ready.emit(generation, i, img)
                except RuntimeError:
                    return
        threading.Thread(target=run, name="theme-thumbs", daemon=True).start()

    def _on_thumb(self, generation: int, index: int, image) -> None:
        if generation == self._generation and index < len(self.cards):
            self.cards[index].set_thumbnail(image)

    def _menu(self, card: ThemeCard, pos) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.ACCEPT, "Выбрать", triggered=lambda: self.selected.emit(card.index)))
        if card.index > 0:
            menu.addAction(Action(FluentIcon.LEFT_ARROW, "Переместить раньше", triggered=lambda: self.moved.emit(card.index,card.index-1)))
        if card.index+1 < len(self.cards):
            menu.addAction(Action(FluentIcon.RIGHT_ARROW, "Переместить позже", triggered=lambda: self.moved.emit(card.index,card.index+1)))
        menu.addAction(Action(FluentIcon.COPY, "Дублировать", triggered=lambda: self.duplicate.emit(card.index)))
        menu.addAction(Action(FluentIcon.SAVE_AS, "Экспорт пака...", triggered=lambda: self.export.emit(card.index)))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.DELETE, "Удалить", triggered=lambda: self.delete.emit(card.index)))
        menu.exec(card.mapToGlobal(pos if isinstance(pos, QPoint) else QPoint(0, 0)))
