from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from cardlayout.models.card_side import CardSide, SideName
from cardlayout.ui.image_utils import pil_to_qimage
from cardlayout.ui.scaling import UiScale, sharp_pixmap

STATUS_EMPTY = "Empty"
STATUS_DETECTING = "Detecting…"
STATUS_NOT_FOUND = "Card not found – set corners"
STATUS_CHECK = "Check corners"
STATUS_READY = "Ready"
ALL_STATUSES = (
    STATUS_EMPTY,
    STATUS_DETECTING,
    STATUS_NOT_FOUND,
    STATUS_CHECK,
    STATUS_READY,
)


def card_status(card: CardSide | None, *, busy: bool = False) -> tuple[str, str]:
    """Status wording and tone for one side; stays until the user handles it."""
    if card is None:
        return STATUS_EMPTY, "muted"
    if busy:
        return STATUS_DETECTING, "busy"
    if card.has_manual_correction:
        return STATUS_READY, "ok"
    detection = card.detection_result
    if detection is None:
        return STATUS_READY, "ok"
    if not detection.success:
        return STATUS_NOT_FOUND, "error"
    correction = card.automatic_perspective_result
    if correction is not None and correction.success:
        if correction.status == "corrected":
            return STATUS_READY, "ok"
        return STATUS_CHECK, "warn"
    if detection.method == "already_cropped":
        return STATUS_READY, "ok"
    return STATUS_CHECK, "warn"


def set_corners_emphasis(button: QPushButton, status: str) -> None:
    """Filled accent when corners need attention, bold outline otherwise."""
    emphasis = "strong" if status in (STATUS_CHECK, STATUS_NOT_FOUND) else "normal"
    if button.property("emphasis") != emphasis:
        button.setProperty("emphasis", emphasis)
        button.style().unpolish(button)
        button.style().polish(button)


class ClickablePreview(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)


class CardInputWidget(QFrame):
    choose_requested = Signal(str)
    remove_requested = Signal(str)
    edit_requested = Signal(str)
    corners_requested = Signal(str)

    PLACEHOLDER = "Drop or choose a file"

    def __init__(self, side: SideName, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.side = side
        self._card: CardSide | None = None
        self._busy = False
        self._source_pixmap: QPixmap | None = None
        self._source_image: object | None = None
        self._file_text = ""
        self._preview_inset = 16
        self.setObjectName("cardInput")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.title = QLabel(side.upper())
        self.title.setObjectName("sideTitle")
        self.status_chip = QLabel()
        self.status_chip.setObjectName("statusChip")
        self.heading = QHBoxLayout()
        self.heading.addWidget(self.title)
        self.heading.addStretch()
        self.heading.addWidget(self.status_chip)

        self.file_label = QLabel()
        self.file_label.setObjectName("fileName")
        self.file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        self.preview = ClickablePreview(self.PLACEHOLDER)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(115)
        # Ignore the pixmap's size hint: the preview fills the space it is
        # given and must not grow the side panel (and force scrolling).
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.preview.setObjectName("sidePreview")
        self.preview.clicked.connect(self._request_edit)

        self.choose_button = QPushButton(f"Choose {side.title()}")
        self.choose_button.setObjectName("secondaryButton")
        self.choose_button.clicked.connect(
            lambda: self.choose_requested.emit(self.side)
        )
        self.remove_button = QPushButton("Remove")
        self.remove_button.setObjectName("quietButton")
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.side)
        )
        self.file_buttons = QHBoxLayout()
        self.file_buttons.addWidget(self.choose_button, 1)
        self.file_buttons.addWidget(self.remove_button)

        self.corners_button = QPushButton("Adjust corners…")
        self.corners_button.setObjectName("cornersButton")
        self.corners_button.clicked.connect(self._request_corners)
        self.more_button = QPushButton("More edits…")
        self.more_button.setObjectName("secondaryButton")
        self.more_button.clicked.connect(self._request_edit)
        self.edit_buttons = QHBoxLayout()
        self.edit_buttons.addWidget(self.corners_button, 3)
        self.edit_buttons.addWidget(self.more_button, 2)

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(16, 14, 16, 14)
        self.content_layout.setSpacing(9)
        self.content_layout.addLayout(self.heading)
        self.content_layout.addWidget(self.file_label)
        self.content_layout.addWidget(self.preview, 1)
        self.content_layout.addLayout(self.file_buttons)
        self.content_layout.addLayout(self.edit_buttons)
        self.set_card(None)

    def apply_scale(self, ui: UiScale) -> None:
        """Adjust only UI sizing; card state and processing remain untouched."""
        self.preview.setMinimumHeight(ui.px(84))
        self.content_layout.setContentsMargins(
            ui.px(11), ui.px(9), ui.px(11), ui.px(9)
        )
        self.content_layout.setSpacing(ui.px(6))
        self.file_buttons.setSpacing(ui.px(6))
        self.edit_buttons.setSpacing(ui.px(6))
        self._preview_inset = ui.px(16)
        self.setMinimumWidth(self._widest_heading())
        self._update_file_label()
        self._update_pixmap()

    def _widest_heading(self) -> int:
        """Minimum width so the longest status chip never clips."""
        current = (self.status_chip.text(), self.status_chip.property("tone"))
        widest = 0
        for text in ALL_STATUSES:
            self._show_status(text, "muted")
            self.status_chip.ensurePolished()
            widest = max(widest, self.status_chip.sizeHint().width())
        self._show_status(*current)
        self.title.ensurePolished()
        margins = self.content_layout.contentsMargins()
        return (
            self.title.sizeHint().width()
            + max(0, self.heading.spacing())
            + widest
            + margins.left()
            + margins.right()
            + 2 * self.frameWidth()
            + 4
        )

    def _set_file_text(self, text: str) -> None:
        self._file_text = text
        self._update_file_label()

    def _update_file_label(self) -> None:
        """Elide long file names instead of cutting glyphs; tooltip keeps the path."""
        width = self.file_label.contentsRect().width()
        if width <= 1:
            self.file_label.setText(self._file_text)
            return
        self.file_label.setText(
            self.file_label.fontMetrics().elidedText(
                self._file_text, Qt.TextElideMode.ElideMiddle, width
            )
        )

    def _request_edit(self) -> None:
        if self._card is not None and not self._busy:
            self.edit_requested.emit(self.side)

    def _request_corners(self) -> None:
        if self._card is not None and not self._busy:
            self.corners_requested.emit(self.side)

    def set_card(self, card: CardSide | None, *, busy: bool = False) -> None:
        self._card = card
        self._busy = busy and card is not None
        status, tone = card_status(card, busy=self._busy)
        self._show_status(status, tone)
        set_corners_emphasis(self.corners_button, status)
        self.corners_button.setEnabled(card is not None and not self._busy)
        self.more_button.setEnabled(card is not None and not self._busy)
        self.remove_button.setEnabled(card is not None)
        if card is None:
            self._source_pixmap = None
            self._source_image = None
            self._set_file_text("No file chosen")
            self.file_label.setToolTip("")
            self.preview.setPixmap(QPixmap())
            self.preview.setText(self.PLACEHOLDER)
            self.preview.setToolTip("")
            self.preview.setCursor(Qt.CursorShape.ArrowCursor)
            return

        self._set_file_text(card.display_name)
        self.file_label.setToolTip(str(card.source_path))
        self.preview.setText("")
        self.preview.setToolTip("" if self._busy else "Click to edit this card")
        self.preview.setCursor(
            Qt.CursorShape.ArrowCursor
            if self._busy
            else Qt.CursorShape.PointingHandCursor
        )
        self._update_preview_source()

    def _show_status(self, text: str, tone: str) -> None:
        self.status_chip.setText(f"● {text}")
        self.status_chip.setProperty("status", text)
        if self.status_chip.property("tone") != tone:
            self.status_chip.setProperty("tone", tone)
            self.status_chip.style().unpolish(self.status_chip)
            self.status_chip.style().polish(self.status_chip)

    @property
    def status_text(self) -> str:
        return str(self.status_chip.property("status"))

    def _update_preview_source(self) -> None:
        if self._card is None:
            return
        image = self._card.best_image
        # Re-converting the same PIL image on every refresh is wasted work.
        if image is not self._source_image or self._source_pixmap is None:
            self._source_pixmap = QPixmap.fromImage(pil_to_qimage(image))
            self._source_image = image
        self._update_pixmap()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)  # type: ignore[arg-type]
        self._update_file_label()
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._source_pixmap is None or self.preview.width() < 2:
            return
        target = self.preview.size()
        target.setWidth(max(1, target.width() - self._preview_inset))
        target.setHeight(max(1, target.height() - self._preview_inset))
        self.preview.setPixmap(
            sharp_pixmap(self._source_pixmap, target, self.devicePixelRatioF())
        )
