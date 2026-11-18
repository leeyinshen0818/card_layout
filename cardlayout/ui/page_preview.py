from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from cardlayout.models.card_side import CardSide, SideName
from cardlayout.services.layout_engine import LayoutEngine
from cardlayout.ui.image_utils import pil_to_qimage
from cardlayout.ui.scaling import UiScale, sharp_pixmap


class PagePreview(QWidget):
    """A4 page preview; clicking a placed card selects it for editing."""

    side_selected = Signal(str)

    def __init__(self, engine: LayoutEngine, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.engine = engine
        self.front: CardSide | None = None
        self.back: CardSide | None = None
        self.selected_side: SideName | None = None
        self.busy_sides: frozenset[str] = frozenset()
        self._pixmaps: dict[str, tuple[object, QPixmap]] = {}
        self._ui = UiScale()
        self.setMinimumSize(350, 470)
        self.setMouseTracking(True)

    def apply_scale(self, ui: UiScale) -> None:
        self._ui = ui
        self.setMinimumSize(ui.size(350, 470))
        self.update()

    def set_sides(
        self,
        front: CardSide | None,
        back: CardSide | None,
        busy_sides: frozenset[str] = frozenset(),
    ) -> None:
        self.front = front
        self.back = back
        self.busy_sides = busy_sides
        if self.selected_side is not None and self._card(self.selected_side) is None:
            self.selected_side = None
        self.update()

    def select_side(self, side: SideName, *, emit: bool = True) -> None:
        self.selected_side = side
        self.update()
        if emit:
            self.side_selected.emit(side)

    def clear_selection(self) -> None:
        self.selected_side = None
        self.update()

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#e9edf3"))

        layout = self.engine.calculate()
        page_rect = self._page_rect()

        painter.fillRect(page_rect.translated(5, 7), QColor(30, 41, 59, 35))
        painter.fillRect(page_rect, Qt.GlobalColor.white)
        painter.setPen(QPen(QColor("#cbd3df"), 1))
        painter.drawRect(page_rect)

        for side_name, rect in (("front", layout.front), ("back", layout.back)):
            target = self._card_target(rect, page_rect)
            card = self._card(side_name)
            if card is None:
                self._draw_placeholder(painter, target, side_name.title())
            else:
                self._draw_card(painter, target, card, side_name)

    def _draw_placeholder(self, painter: QPainter, target: QRectF, label: str) -> None:
        painter.save()
        pen = QPen(QColor("#cfd6e0"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(target)
        painter.setPen(QColor("#a7b1bf"))
        painter.drawText(target, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _draw_card(
        self, painter: QPainter, target: QRectF, card: CardSide, side_name: str
    ) -> None:
        painter.save()
        painter.setClipRect(target)
        painter.fillRect(target, QColor("#f7f9fc"))
        image = card.best_image
        cached = self._pixmaps.get(side_name)
        if cached is None or cached[0] is not image:
            cached = (image, QPixmap.fromImage(pil_to_qimage(image)))
            self._pixmaps[side_name] = cached
        scaled = sharp_pixmap(cached[1], target.size().toSize(), self.devicePixelRatioF())
        logical = scaled.deviceIndependentSize()
        image_rect = QRectF(
            target.center().x() - logical.width() / 2,
            target.center().y() - logical.height() / 2,
            logical.width(),
            logical.height(),
        )
        painter.drawPixmap(image_rect, scaled, QRectF(scaled.rect()))
        if side_name in self.busy_sides:
            painter.fillRect(target, QColor(255, 255, 255, 170))
            painter.setPen(QColor("#1d4fa8"))
            painter.drawText(target, Qt.AlignmentFlag.AlignCenter, "Detecting…")
        painter.restore()
        if self.selected_side == side_name:
            painter.setPen(QPen(QColor("#245fc5"), 3))
        else:
            painter.setPen(QPen(QColor("#9aa7b8"), 1))
        painter.drawRect(target)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        side = self._side_at(event.position())
        if side is not None:
            self.select_side(side)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cursor = (
            Qt.CursorShape.PointingHandCursor
            if self._side_at(event.position()) is not None
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def _card(self, side: str) -> CardSide | None:
        if side == "front":
            return self.front
        if side == "back":
            return self.back
        return None

    def _page_rect(self) -> QRectF:
        # Keep a modest breathing space while allowing the paper to use the
        # center workspace more effectively at normal desktop window sizes.
        margin = 18.0
        layout = self.engine.calculate()
        scale = min(
            max(1.0, self.width() - margin * 2) / layout.page_width_mm,
            max(1.0, self.height() - margin * 2) / layout.page_height_mm,
        )
        page_width = layout.page_width_mm * scale
        page_height = layout.page_height_mm * scale
        return QRectF(
            (self.width() - page_width) / 2,
            (self.height() - page_height) / 2,
            page_width,
            page_height,
        )

    def _card_target(self, rect, page_rect: QRectF) -> QRectF:
        layout = self.engine.calculate()
        x_scale = page_rect.width() / layout.page_width_mm
        y_scale = page_rect.height() / layout.page_height_mm
        return QRectF(
            page_rect.left() + rect.x * x_scale,
            page_rect.top() + rect.y * y_scale,
            rect.width * x_scale,
            rect.height * y_scale,
        )

    def _side_at(self, position) -> SideName | None:
        layout = self.engine.calculate()
        page_rect = self._page_rect()
        for side_name, rect in (("front", layout.front), ("back", layout.back)):
            if self._card(side_name) is not None and self._card_target(
                rect, page_rect
            ).contains(position):
                return side_name  # type: ignore[return-value]
        return None
