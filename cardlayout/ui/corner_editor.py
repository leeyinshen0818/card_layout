from __future__ import annotations

from collections.abc import Callable

from PIL import Image
from PySide6.QtCore import QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QPen, QPixmap, QPolygonF, QTransform, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from cardlayout.models.detection import Point
from cardlayout.models.perspective import PerspectiveResult
from cardlayout.services.perspective_corrector import PerspectiveCorrector
from cardlayout.ui.image_utils import pil_to_qimage
from cardlayout.ui.scaling import UiScale, bounded_to_screen, sharp_pixmap


HANDLE_RADIUS = 8


class _CornerHandle(QGraphicsEllipseItem):
    def __init__(
        self,
        point: Point,
        bounds: tuple[int, int],
        moved: Callable[[], None],
    ) -> None:
        super().__init__(
            -HANDLE_RADIUS, -HANDLE_RADIUS, 2 * HANDLE_RADIUS, 2 * HANDLE_RADIUS
        )
        self._bounds = bounds
        self._moved = moved
        self.setBrush(QBrush(QColor("#ffffff")))
        self.setPen(QPen(QColor("#245fc5"), 3))
        self.setZValue(5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setPos(*point)

    def itemChange(self, change, value):  # type: ignore[no-untyped-def]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            point = value
            return QPointF(
                min(max(0.0, point.x()), self._bounds[0] - 1.0),
                min(max(0.0, point.y()), self._bounds[1] - 1.0),
            )
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self._moved()
        return result


class CornerEditorCanvas(QGraphicsView):
    """Image-coordinate corner canvas with stable zoom and pan mapping."""

    corners_changed = Signal(object)
    CORNER_NAMES = ("TL", "TR", "BR", "BL")

    def __init__(
        self,
        image: Image.Image,
        points: tuple[Point, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image_size = image.size
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._pixmap_item.setPixmap(QPixmap.fromImage(pil_to_qimage(image)))
        self._scene.addItem(self._pixmap_item)
        self._scene.setSceneRect(0, 0, image.width, image.height)
        self._polygon = QGraphicsPolygonItem()
        self._polygon.setPen(QPen(QColor("#2f7cf6"), 3))
        self._polygon.setBrush(QBrush(QColor(47, 124, 246, 28)))
        self._polygon.setZValue(3)
        self._scene.addItem(self._polygon)
        self._handles: list[_CornerHandle] = []
        self._labels: list[QGraphicsSimpleTextItem] = []
        for name, point in zip(self.CORNER_NAMES, points, strict=True):
            handle = _CornerHandle(point, image.size, self._handles_moved)
            self._scene.addItem(handle)
            # A child of the handle inherits its zoom-independent coordinates,
            # so the label keeps a fixed screen-pixel gap outside the card.
            label = QGraphicsSimpleTextItem(name, handle)
            font = QFont(label.font())
            font.setBold(True)
            font.setPointSizeF(max(font.pointSizeF(), 9.0) + 1.0)
            label.setFont(font)
            label.setBrush(QBrush(QColor("#ffffff")))
            label.setPen(QPen(QColor("#0f172a"), 0.8))
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setPos(self._label_offset(name, label))
            self._handles.append(handle)
            self._labels.append(label)
        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QBrush(QColor("#172033")))
        self.setMinimumSize(520, 420)
        self._handles_moved()
        QTimer.singleShot(0, self.fit_image)

    @property
    def corners(self) -> tuple[Point, ...]:
        return tuple((handle.pos().x(), handle.pos().y()) for handle in self._handles)

    def set_corners(self, points: tuple[Point, ...]) -> None:
        for handle, point in zip(self._handles, points, strict=True):
            handle.setPos(*point)
        self._handles_moved()

    def fit_image(self) -> None:
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_actual_size(self) -> None:
        self.setTransform(QTransform())

    def wheelEvent(self, event: QWheelEvent) -> None:
        old_scale = self.transform().m11()
        factor = 1.22 if event.angleDelta().y() > 0 else 1 / 1.22
        new_scale = old_scale * factor
        if 0.03 <= new_scale <= 16.0:
            self.scale(factor, factor)
        event.accept()

    def _handles_moved(self) -> None:
        if len(self._handles) != 4:
            return
        polygon = QPolygonF([handle.pos() for handle in self._handles])
        self._polygon.setPolygon(polygon)
        self.corners_changed.emit(self.corners)

    @staticmethod
    def _label_offset(name: str, label: QGraphicsSimpleTextItem) -> QPointF:
        """Place the label diagonally outside its corner, clear of the handle."""
        bounds = label.boundingRect()
        gap = HANDLE_RADIUS + 4
        x = -gap - bounds.width() if name in ("TL", "BL") else gap
        y = -gap - bounds.height() if name in ("TL", "TR") else gap
        return QPointF(x, y)


def _button_style(ui: UiScale) -> str:
    px = ui.px
    return f"""
        QPushButton {{ min-height: {px(28)}px; padding: 0 {px(12)}px; border-radius: {px(6)}px; font-weight: 600; }}
        QPushButton#secondaryButton {{ background: #ffffff; color: #234c86; border: 1px solid #9fb2cc; }}
        QPushButton#secondaryButton:hover {{ background: #edf3fb; }}
        QPushButton#primaryButton {{ background: #245fc5; color: white; border: 1px solid #245fc5; }}
        QPushButton#primaryButton:hover {{ background: #1d4fa8; }}
        QPushButton#primaryButton:disabled {{ background: #f1f3f6; color: #aab2bf; border-color: #e2e6ec; }}
    """


class CornerEditorDialog(QDialog):
    """Focused four-corner workflow with debounced rectified preview."""

    def __init__(
        self,
        image: Image.Image,
        automatic_points: tuple[Point, ...],
        corrector: PerspectiveCorrector,
        detector_confidence: float,
        current_points: tuple[Point, ...] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image = image
        self._corrector = corrector
        self._detector_confidence = detector_confidence
        self._automatic_points = automatic_points
        self._result: PerspectiveResult | None = None
        self.setWindowTitle("Adjust Card Corners")
        # Same proportional factor as the main window; never larger than the
        # available screen so Done/Cancel always stay reachable.
        self.ui = UiScale.for_widget(parent if parent is not None else self)
        ui = self.ui
        self.setMinimumSize(bounded_to_screen(ui.size(720, 480), self))
        self.resize(bounded_to_screen(ui.size(1040, 620), self))

        self.canvas = CornerEditorCanvas(image, current_points or automatic_points)
        self.canvas.setMinimumSize(ui.size(420, 320))
        self.preview = QLabel("Rectified preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(ui.px(220))
        self.preview.setStyleSheet(
            "background:#eef2f7; border:1px solid #cbd5e1; color:#64748b;"
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.preview)
        splitter.setSizes([ui.px(650), ui.px(270)])

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#b42318; font-weight:600;")
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.canvas.fit_image)
        self.actual_button = QPushButton("100%")
        self.actual_button.clicked.connect(self.canvas.set_actual_size)
        self.reset_button = QPushButton("Reset to Automatic")
        self.reset_button.clicked.connect(
            lambda: self.canvas.set_corners(self._automatic_points)
        )
        for button in (self.fit_button, self.actual_button, self.reset_button):
            button.setObjectName("secondaryButton")
            button.setAutoDefault(False)
        controls = QHBoxLayout()
        instructions = QLabel("Drag TL, TR, BR, and BL onto the physical card corners.")
        instructions.setWordWrap(True)
        controls.addWidget(instructions, 1)
        controls.addStretch()
        controls.addWidget(self.fit_button)
        controls.addWidget(self.actual_button)
        controls.addWidget(self.reset_button)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText("Done")
        self.apply_button.setObjectName("primaryButton")
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setObjectName("secondaryButton")
        # Own button styling so the dialog looks the same with or without the
        # main window's style sheet; the main window still sets the font.
        self.setStyleSheet(_button_style(ui))
        self.buttons.clicked.connect(self._button_clicked)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._update_rectified_preview)
        self.canvas.corners_changed.connect(self._corners_changed)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.warning)
        layout.addWidget(self.buttons)
        self._corners_changed(self.canvas.corners)

    @property
    def result(self) -> PerspectiveResult | None:
        return self._result

    def _corners_changed(self, points: object) -> None:
        corners = points  # Signal payload is a tuple of image-coordinate points.
        valid, warning = self._corrector.validate_quad(
            corners, self._image.size  # type: ignore[arg-type]
        )
        self.apply_button.setEnabled(valid)
        self.warning.setText("" if valid else (warning or "Invalid corners"))
        if valid:
            self._preview_timer.start()
        else:
            self._preview_timer.stop()
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Move the handles to form a valid card outline")

    def _update_rectified_preview(self) -> None:
        result = self._make_result()
        if not result.success or result.rectified_image is None:
            self.apply_button.setEnabled(False)
            self.warning.setText(result.warning or "Correction failed")
            return
        pixmap = QPixmap.fromImage(pil_to_qimage(result.rectified_image))
        target = self.preview.size()
        target.setWidth(max(1, target.width() - 20))
        target.setHeight(max(1, target.height() - 20))
        self.preview.setPixmap(
            sharp_pixmap(pixmap, target, self.devicePixelRatioF())
        )
        self.preview.setText("")

    def _make_result(self) -> PerspectiveResult:
        return self._corrector.correct(
            self._image,
            self.canvas.corners,
            detector_confidence=self._detector_confidence,
            method="manual",
            refine=False,
        )

    def _button_clicked(self, button: QPushButton) -> None:
        role = self.buttons.buttonRole(button)
        if role == QDialogButtonBox.ButtonRole.ApplyRole:
            result = self._make_result()
            if result.success:
                self._result = result
                self.accept()
            else:
                self.warning.setText(result.warning or "Correction failed")
        elif role == QDialogButtonBox.ButtonRole.RejectRole:
            self.reject()
