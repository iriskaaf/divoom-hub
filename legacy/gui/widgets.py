"""Shared Fluent (Windows 11) building blocks for the pages."""

from __future__ import annotations

import logging

from PIL import Image
from PySide6.QtCore import QObject, Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, ComboBox, FluentIcon, LargeTitleLabel, ScrollArea, SettingCard,
                            SettingCardGroup, Slider, SmoothMode, StrongBodyLabel, SwitchButton,
                            TransparentToolButton, PushButton, ColorPickerButton, SimpleCardWidget, CardWidget, themeColor, setCustomStyleSheet, isDarkTheme)


class TileArtwork(QWidget):
    """Fixed-height illustration area; preserve aspect ratio and click the whole card."""
    def __init__(self, icon: QIcon, height: int, parent=None):
        super().__init__(parent)
        self.icon = icon
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        self.icon.paint(painter, self.rect(), Qt.AlignmentFlag.AlignCenter,
                        QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled)


class ChoiceTile(CardWidget):
    """Selectable device/source tile with local artwork and a Fluent accent outline."""
    def __init__(self, title, subtitle="", parent=None, *, artwork=None, artwork_height=96):
        super().__init__(parent)
        self.checked = False
        self.setMinimumSize(180, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)
        layout.addStretch()
        self.artwork = None
        if artwork is not None:
            self.artwork = TileArtwork(artwork, artwork_height, self)
            layout.addWidget(self.artwork)
        self.label = StrongBodyLabel(title)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.detail = BodyLabel(subtitle)
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.detail)
        layout.addStretch()
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

    def setChecked(self, checked):
        self.checked = checked
        self.update()

    def isChecked(self):
        return self.checked

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.checked:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(getattr(self, "outline_color", themeColor()), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 6, 6)


class TitleStatusDot(QLabel):
    """Align the dot with the visible title glyphs, rather than its line box."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = QColor("#FF7979")
        self.setFixedWidth(18)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def glyph_center(self):
        metrics = self.title.fontMetrics()
        ink = metrics.tightBoundingRect(self.title.text())
        return (self.height()-metrics.height())/2 + metrics.ascent() + ink.top() + ink.height()/2

    def set_connected(self, connected, text):
        self.color = QColor("#6CCB5F" if connected else "#FF7979")
        self.setToolTip(text)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        from PySide6.QtCore import QPointF
        painter.drawEllipse(QPointF(9, self.glyph_center()), 6, 6)


class StableGroup(QWidget):
    """A section with one layout owner and no scroll area or forced resize."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.widgets = []
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(10)
        self.titleLabel = StrongBodyLabel(title)
        self.root.addWidget(self.titleLabel)
        self.body = QWidget(self)
        self.cardLayout = QVBoxLayout(self.body)
        self.cardLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout.setSpacing(4)
        self.root.addWidget(self.body)

    def addSettingCard(self, widget):
        self.widgets.append(widget)
        self.cardLayout.addWidget(widget)

    def addGroupWidget(self, widget):
        self.addSettingCard(widget)

    def setExpand(self, expanded):
        pass  # connection dialogs use the same API; an ordinary section stays open

    def _adjustViewSize(self):
        self.cardLayout.invalidate()
        self.updateGeometry()


class DisclosureChevron(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded = False
        self.setFixedSize(16, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(8, 8)
        painter.rotate(180 if self.expanded else 0)
        from PySide6.QtCore import QRectF
        FluentIcon.CHEVRON_DOWN_MED.render(painter, QRectF(-6, -6, 12, 12))


class RevealViewport(QWidget):
    def sizeHint(self):
        return QSize(0, min(16777215, self.maximumHeight()))

    def minimumSizeHint(self):
        return QSize(0, 0)


class FoldGroup(StableGroup):
    """A single animated disclosure for occasional controls, without nested scrolling."""
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.titleLabel.hide()
        self.isExpand = False
        self.header = PushButton(self)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(16, 0, 16, 0)
        label = BodyLabel(title)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        self.chevron = DisclosureChevron(self.header)
        row.addWidget(self.chevron)
        setCustomStyleSheet(self.header, "PushButton {text-align:left;padding-left:16px;}",
                            "PushButton {text-align:left;padding-left:16px;}")
        self.header.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.header.setMinimumHeight(44)
        self.header.setAccessibleName(title)
        self.root.insertWidget(0, self.header)
        self.reveal = RevealViewport(self)
        self.root.removeWidget(self.body)
        self.body.setParent(self.reveal)
        self.panel = SimpleCardWidget(self.body)
        self.cardLayout.setContentsMargins(16, 12, 16, 12)
        self.cardLayout.setSpacing(8)
        self.cardLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Paint a single backing panel behind the existing content layout.
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.panel.lower()
        self.body.installEventFilter(self)
        self.reveal.setMaximumHeight(0)
        self.root.addWidget(self.reveal)
        self.root.setSpacing(0)
        self.header.clicked.connect(lambda: self.setExpand(not self.isExpand))
        self.animation = QPropertyAnimation(self.reveal, b"maximumHeight", self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._reveal_frame)
        self.animation.finished.connect(self._finish)

    def setExpand(self, expanded):
        if self.isExpand == expanded:
            return
        self.isExpand = expanded
        self.chevron.expanded = expanded
        self.chevron.update()
        self.animation.stop()
        self._scroll_page = self.parentWidget()
        while self._scroll_page is not None and not isinstance(self._scroll_page, Page):
            self._scroll_page = self._scroll_page.parentWidget()
        if self._scroll_page is not None:
            bar = self._scroll_page.verticalScrollBar()
            if not getattr(self, "_anchor_connected", False):
                bar.rangeChanged.connect(self._range_changed)
                bar.valueChanged.connect(self._scroll_changed)
                self._anchor_connected = True
                self._scroll_page.view.installEventFilter(self)
            from PySide6.QtCore import QPoint
            self._anchor_y = self.header.mapTo(self._scroll_page.viewport(), QPoint(0,0)).y()
        self.body.resize(self.reveal.width(), self._content_height())
        self.animation.setStartValue(self.reveal.height())
        self.animation.setEndValue(self._content_height() if expanded else 0)
        self.animation.start()

    def _content_height(self):
        width = self.reveal.width()
        if self.cardLayout.hasHeightForWidth():
            return max(0, self.cardLayout.totalHeightForWidth(width))
        return self.cardLayout.sizeHint().height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "reveal"):
            self.body.resize(self.reveal.width(), self._content_height())
            if self.isExpand and self.animation.state() == QPropertyAnimation.State.Stopped:
                self.reveal.setMaximumHeight(self._content_height())
                self.reveal.updateGeometry()

    def _adjustViewSize(self):
        super()._adjustViewSize()
        if self.isExpand and self.animation.state() == QPropertyAnimation.State.Stopped:
            self.reveal.setMaximumHeight(self._content_height())
            self.reveal.updateGeometry()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        page = getattr(self, "_scroll_page", None)
        if page is not None and watched is page.view and event.type() == QEvent.Type.Move:
            self._keep_anchor()
        if watched is self.body and event.type() == QEvent.Type.Resize:
            self.panel.setGeometry(self.body.rect())
        return super().eventFilter(watched, event)

    def _reveal_frame(self):
        self.reveal.updateGeometry()
        self.updateGeometry()
        self.body.resize(self.reveal.width(), self._content_height())
        self.body.move(0, min(0, self.reveal.maximumHeight()-self.body.height()))
        self.root.activate()
        self._keep_anchor()
        QTimer.singleShot(0, self._keep_anchor)

    def _scroll_changed(self, _value):
        self._keep_anchor()

    def _range_changed(self, _minimum, _maximum):
        self._keep_anchor()

    def _keep_anchor(self):
        page = getattr(self, "_scroll_page", None)
        if page is not None and self.isVisible():
            from PySide6.QtCore import QPoint
            delta = self.header.mapTo(page.viewport(), QPoint(0,0)).y()-self._anchor_y
            if delta:
                bar = page.verticalScrollBar()
                bar.setValue(bar.value()+delta)

    def _finish(self):
        self.reveal.setMaximumHeight(self._content_height() if self.isExpand else 0)
        self.body.move(0, 0 if self.isExpand else -self.body.height())
        self._keep_anchor()
        page = getattr(self, "_scroll_page", None)
        if page is not None:
            QTimer.singleShot(50, self._detach_anchor)

    def _detach_anchor(self):
        page = getattr(self, "_scroll_page", None)
        if self.animation.state() != QPropertyAnimation.State.Stopped:
            return
        if page is not None and getattr(self, "_anchor_connected", False):
            self._anchor_connected = False
            page.view.removeEventFilter(self)
            try:
                page.verticalScrollBar().rangeChanged.disconnect(self._range_changed)
                page.verticalScrollBar().valueChanged.disconnect(self._scroll_changed)
            except (RuntimeError, TypeError):
                pass


class Bridge(QObject):
    """Moves engine events and log lines from worker threads to the GUI thread."""
    event = Signal(str, object)
    log_line = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: Bridge):
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.log_line.emit(self.format(record))


def to_pixmap(image: Image.Image, size: int) -> QPixmap:
    img = image.convert("RGB")
    qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3,
                  QImage.Format.Format_RGB888).copy()
    mode = (Qt.TransformationMode.FastTransformation if img.width <= 32
            else Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(qimg).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, mode)


class PixelPreview(QLabel):
    """Rounded dark tile showing a PIL image (pixel art stays crisp)."""

    def __init__(self, size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.tile = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #101012; border-radius: 8px; color: #8a8a8a; font-size: 22px;")

    def set_image(self, image: Image.Image | None) -> None:
        if image is None:
            self.clear()
        else:
            self.setPixmap(to_pixmap(image, self.tile))


class OpaquePageSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#272727" if isDarkTheme() else "#F9F9F9"))


class Page(ScrollArea):
    """Scrollable page: large title, optional subtitle, then groups of cards."""

    def __init__(self, object_name: str, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.view = OpaquePageSurface()
        self.view.setObjectName("view")
        self.layout_ = QVBoxLayout(self.view)
        self.layout_.setContentsMargins(24, 20, 24, 24)
        self.layout_.setSpacing(16)
        self.layout_.setAlignment(Qt.AlignmentFlag.AlignTop)
        title_label = LargeTitleLabel(title)
        self.layout_.addWidget(title_label)
        if subtitle:
            sub = BodyLabel(subtitle)
            sub.setWordWrap(True)
            sub.setTextColor("#606060", "#a0a0a0")
            self.layout_.addWidget(sub)
        self.layout_.addSpacing(12)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The library's timer-driven smooth scrolling feels laggy; native Windows
        # scrolling is immediate and still smooth on precision touchpads.
        self.setSmoothMode(SmoothMode.NO_SMOOTH, Qt.Orientation.Vertical)
        self.verticalScrollBar().setSingleStep(32)
        self.setStyleSheet("QScrollArea {border:none;background:transparent;}")

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx,dy)
        # Do not leave cached/blitted copies of transparent children after a scroll.
        self.viewport().update()
        self.view.update()

    def group(self, title: str, collapsible=False) -> StableGroup:
        g = FoldGroup(title, self.view) if collapsible else StableGroup(title, self.view)
        self.layout_.addWidget(g)
        return g

    def add(self, widget: QWidget) -> QWidget:
        self.layout_.addWidget(widget)
        return widget


class WrappedCard(SettingCard):
    """Keep controls visible and give long labels enough room to wrap."""

    def __init__(self, icon, title, content):
        super().__init__(icon, title, content)
        self.hBoxLayout.setStretch(2, 1)
        self.hBoxLayout.setStretch(4, 0)
        for label in (self.titleLabel, self.contentLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(0)
            self.vBoxLayout.setAlignment(label, Qt.AlignmentFlag.AlignVCenter)

    def _fit_text(self) -> None:
        width = self.vBoxLayout.geometry().width()
        if width < 1:
            return
        height = sum(label.heightForWidth(width) for label in
                     (self.titleLabel, self.contentLabel) if not label.isHidden())
        wanted = max(64 if not self.contentLabel.isHidden() else 50, height + 20)
        if wanted != self.height():
            self.setFixedHeight(wanted)
            self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_text()

    def setContent(self, content: str) -> None:  # noqa: N802
        super().setContent(content)
        self._fit_text()


def card(icon, title: str, content: str = "", *widgets: QWidget) -> SettingCard:
    """A settings card with controls aligned on its right side."""
    c = WrappedCard(icon, title, content or None)
    for i, w in enumerate(widgets):
        if i:
            c.hBoxLayout.addSpacing(8)
        c.hBoxLayout.addWidget(w, 0, Qt.AlignmentFlag.AlignRight)
    c.hBoxLayout.addSpacing(16)
    return c


def show(widget: QWidget, visible: bool) -> None:
    """Show/hide a widget; a setting group re-lays itself out (it has a fixed height)."""
    if widget.isHidden() == (not visible):
        return
    widget.setVisible(visible)
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, StableGroup):
            parent._adjustViewSize()
            break
        if isinstance(parent, SettingCardGroup):
            parent.cardLayout.invalidate()
            parent.adjustSize()
            break
        parent = parent.parentWidget()


def switch(checked: bool, on_change) -> SwitchButton:
    s = SwitchButton()
    s.setOnText("Вкл")
    s.setOffText("Выкл")
    s.setChecked(checked)
    s.checkedChanged.connect(on_change)
    return s


class WheelSafeSlider(Slider):
    def wheelEvent(self, event):
        event.ignore()  # keep wheel scrolling on the page; change values by dragging


def slider(minimum: int, maximum: int, value: int, width: int = 220) -> tuple[QWidget, Slider]:
    """Slider with its value printed next to it."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    s = WheelSafeSlider(Qt.Orientation.Horizontal)
    s.setRange(minimum, maximum)
    s.setValue(value)
    s.setFixedWidth(width)
    label = BodyLabel(str(value))
    label.setFixedWidth(34)
    s.valueChanged.connect(lambda v: label.setText(str(v)))
    lay.addWidget(s)
    lay.addWidget(label)
    return box, s


def combo(items: dict, current, on_change, width: int = 240) -> ComboBox:
    """ComboBox over {value: label}; on_change receives the value."""
    c = ComboBox()
    c.setMinimumWidth(width)
    values = list(items)
    for value in values:
        c.addItem(str(items[value]), userData=value)
    if current in values:
        c.setCurrentIndex(values.index(current))
    c.currentIndexChanged.connect(lambda i: on_change(values[i]) if 0 <= i < len(values) else None)
    return c


class ThemeSwitcher(QWidget):
    """<- name -> with a fixed-width name, so the arrows never move."""

    def __init__(self, on_step, width: int = 180, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        prev_btn = TransparentToolButton(FluentIcon.LEFT_ARROW)
        next_btn = TransparentToolButton(FluentIcon.RIGHT_ARROW)
        prev_btn.setToolTip("Предыдущая тема")
        next_btn.setToolTip("Следующая тема")
        prev_btn.clicked.connect(lambda: on_step(-1))
        next_btn.clicked.connect(lambda: on_step(+1))
        self.label = StrongBodyLabel("")
        self.label.setFixedWidth(width)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(prev_btn)
        lay.addWidget(self.label)
        lay.addWidget(next_btn)

    def set_name(self, name: str) -> None:
        metrics = self.label.fontMetrics()
        self.label.setText(metrics.elidedText(name, Qt.TextElideMode.ElideRight, self.label.width()))
        self.label.setToolTip(name)




class InlineColorPicker(ColorPickerButton):
    def __init__(self, color, title, parent=None):
        super().__init__(color,title,parent)
        self.clicked.disconnect()
        self.clicked.connect(self.open_picker)

    def open_picker(self):
        from PySide6.QtWidgets import QColorDialog
        host = self.window()
        page = Page("color_picker", self.title, parent=host)
        chooser = QColorDialog(self.color)
        chooser.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        chooser.setParent(page.view, Qt.WindowType.Widget)
        page.add(chooser)
        chooser.show()
        close = host.open_internal_page(page, delete=True)
        def accept():
            color = chooser.currentColor()
            self.setColor(color)
            self.colorChanged.emit(color)
            close()
        chooser.accepted.connect(accept)
        chooser.rejected.connect(close)


def choose_file(owner, title, file_filter, on_selected, *, save=False, suggested=""):
    from PySide6.QtWidgets import QFileDialog
    host = owner.window()
    page = Page("file_picker",title,parent=host)
    class InlineFileDialog(QFileDialog):
        def accept(self):
            from pathlib import Path
            selected = self.selectedFiles()
            if not selected:
                return
            path = Path(selected[0])
            if path.is_dir():
                self.setDirectory(str(path))
                return
            if (not save and not path.is_file()) or (save and not path.parent.is_dir()):
                error.setText("Проверьте путь: файл или папка не найдены")
                return
            error.clear()
            self.accepted.emit()
    chooser = InlineFileDialog()
    error = BodyLabel("")
    page.add(error)
    chooser.setOption(QFileDialog.Option.DontUseNativeDialog)
    chooser.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
    chooser.setFileMode(QFileDialog.FileMode.AnyFile if save else QFileDialog.FileMode.ExistingFile)
    chooser.setNameFilter(file_filter)
    if save:
        chooser.setDefaultSuffix("zip")
        chooser.setOption(QFileDialog.Option.DontConfirmOverwrite)
    if suggested:
        chooser.selectFile(suggested)
    chooser.setParent(page.view,Qt.WindowType.Widget)
    page.add(chooser)
    chooser.show()
    close = host.open_internal_page(page,delete=True)
    def finish(path):
        close()
        on_selected(path)
    def accept():
        from pathlib import Path
        selected = chooser.selectedFiles()
        if not selected:
            return
        path = selected[0]
        if save and Path(path).exists():
            chooser.hide()
            confirmation = SimpleCardWidget()
            layout = QVBoxLayout(confirmation)
            layout.addWidget(BodyLabel("Файл уже существует. Заменить его?"))
            row = QHBoxLayout()
            replace = PushButton("Заменить")
            cancel = PushButton("Отмена")
            row.addWidget(cancel)
            row.addWidget(replace)
            layout.addLayout(row)
            page.add(confirmation)
            replace.clicked.connect(lambda: finish(path))
            def resume():
                confirmation.hide()
                confirmation.deleteLater()
                chooser.show()
            cancel.clicked.connect(resume)
        else:
            finish(path)
    chooser.accepted.connect(accept)
    chooser.rejected.connect(close)
