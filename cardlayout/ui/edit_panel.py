from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from cardlayout.models.card_side import CardSide, SideName
from cardlayout.ui.card_input_widget import card_status, set_corners_emphasis
from cardlayout.ui.scaling import UiScale, content_size

# Only these presets are offered; the model keeps every other preset.
SHARPNESS_CHOICES = (("normal", "Normal"), ("sharper", "Sharper"))
BRIGHTNESS_CHOICES = (
    ("normal", "Normal"),
    ("bright_contrast", "Bright + Contrast"),
    ("strong_bright_contrast", "Strong"),
)


def position_text(offset_mm: float) -> str:
    if abs(offset_mm) < 0.0005:
        return "Default"
    sign = "+" if offset_mm > 0 else "−"
    return f"{sign}{abs(offset_mm):g} mm"


def orientation_toggles(card: CardSide) -> tuple[bool, bool]:
    """(rotate_180 active, mirror active) for the stored flip pair.

    Rotate 180 flips both axes and Mirror flips horizontally, so these two
    toggles are independent: rotate = vertical flip, mirror = H xor V.
    """
    state = card.orientation_state
    return state.flip_vertical, state.flip_horizontal != state.flip_vertical


def has_user_edits(card: CardSide, offset_mm: float) -> bool:
    return (
        card.has_manual_correction
        or not card.orientation_state.is_normal
        or not card.image_correction_state.is_normal
        or abs(offset_mm) >= 0.0005
    )


def _invalidate_tree(layout: QLayout) -> None:
    for index in range(layout.count()):
        child = layout.itemAt(index).layout()
        if child is not None:
            _invalidate_tree(child)
    layout.invalidate()


def _segment_row(
    choices: tuple[tuple[str, str], ...], parent: QWidget
) -> tuple[QHBoxLayout, dict[str, QPushButton], QButtonGroup]:
    """Adjacent checkable buttons styled as one segmented control."""
    row = QHBoxLayout()
    row.setSpacing(0)
    group = QButtonGroup(parent)
    group.setExclusive(True)
    buttons: dict[str, QPushButton] = {}
    for index, (key, text) in enumerate(choices):
        button = QPushButton(text)
        button.setObjectName("segmentButton")
        button.setCheckable(True)
        position = (
            "first" if index == 0 else "last" if index == len(choices) - 1 else "middle"
        )
        button.setProperty("segment", position)
        group.addButton(button)
        row.addWidget(button, 1)
        buttons[key] = button
    return row, buttons, group


class EditPanel(QFrame):
    """Docked editor for one card side (orientation, position, picture, corners)."""

    side_switch_requested = Signal(str)
    close_requested = Signal()
    orientation_toggled = Signal(str)
    position_step_requested = Signal(float)
    preset_selected = Signal(str, str)
    adjust_corners_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editPanel")
        self.side: SideName | None = None

        self.title = QLabel("Edit")
        self.title.setObjectName("editTitle")
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("panelCloseButton")
        self.close_button.setToolTip("Close")
        self.close_button.clicked.connect(self.close_requested.emit)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(self.title, 1)
        title_row.addWidget(self.close_button)

        switch_row, self.side_buttons, self._side_group = _segment_row(
            (("front", "Front"), ("back", "Back")), self
        )
        for side, button in self.side_buttons.items():
            button.clicked.connect(
                lambda checked=False, target=side: self.side_switch_requested.emit(
                    target
                )
            )

        body = QWidget()
        body.setObjectName("editBody")
        self.body = body
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)

        self.body_layout.addWidget(self._heading("CORNERS"))
        self.corners_button = QPushButton("Adjust corners…")
        self.corners_button.setObjectName("cornersButton")
        self.corners_button.clicked.connect(self.adjust_corners_requested.emit)
        self.body_layout.addWidget(self.corners_button)

        self.body_layout.addWidget(self._heading("ORIENTATION"))
        self.rotate_button = QPushButton("Rotate 180°")
        self.mirror_button = QPushButton("Mirror")
        orientation_row = QHBoxLayout()
        for action, button in (
            ("rotate_180", self.rotate_button),
            ("flip_horizontal", self.mirror_button),
        ):
            button.setObjectName("toggleButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, selected=action: self.orientation_toggled.emit(
                    selected
                )
            )
            orientation_row.addWidget(button, 1)
        self.orientation_row = orientation_row
        self.body_layout.addLayout(orientation_row)

        self.body_layout.addWidget(self._heading("POSITION"))
        self.up_button = QPushButton("▲ Up 1 mm")
        self.down_button = QPushButton("▼ Down 1 mm")
        self.position_label = QLabel("Default")
        self.position_label.setObjectName("positionValue")
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position_label.setToolTip("Distance from the default place on the page")
        for button, delta in ((self.up_button, -1.0), (self.down_button, 1.0)):
            button.setObjectName("secondaryButton")
            button.setAutoRepeat(True)
            button.clicked.connect(
                lambda checked=False, step=delta: self.position_step_requested.emit(
                    step
                )
            )
        position_row = QHBoxLayout()
        position_row.addWidget(self.up_button, 1)
        position_row.addWidget(self.position_label)
        position_row.addWidget(self.down_button, 1)
        self.position_row = position_row
        self.body_layout.addLayout(position_row)

        self.body_layout.addWidget(self._heading("PICTURE"))
        self.body_layout.addWidget(self._subheading("Sharpness"))
        sharp_row, self.sharpness_buttons, self._sharp_group = _segment_row(
            SHARPNESS_CHOICES, self
        )
        self.body_layout.addLayout(sharp_row)
        self.body_layout.addWidget(self._subheading("Brightness"))
        tone_row, self.brightness_buttons, self._tone_group = _segment_row(
            BRIGHTNESS_CHOICES, self
        )
        self.body_layout.addLayout(tone_row)
        for category, buttons in (
            ("sharpen", self.sharpness_buttons),
            ("tone", self.brightness_buttons),
        ):
            for key, button in buttons.items():
                button.clicked.connect(
                    lambda checked=False, group=category, preset=key: (
                        self.preset_selected.emit(group, preset)
                    )
                )

        self.body_layout.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("editScroll")
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidget(body)

        self.reset_button = QPushButton("Reset this card")
        self.reset_button.setObjectName("quietButton")
        self.reset_button.setToolTip(
            "Automatic corners, normal orientation, normal picture and default position"
        )
        self.reset_button.clicked.connect(self.reset_requested.emit)

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.addLayout(title_row)
        self.outer_layout.addLayout(switch_row)
        self.outer_layout.addWidget(self.scroll, 1)
        self.outer_layout.addWidget(self.reset_button)
        self.apply_scale(UiScale())

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("editSection")
        return label

    @staticmethod
    def _subheading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("editSubheading")
        return label

    def apply_scale(self, ui: UiScale) -> None:
        self.outer_layout.setContentsMargins(
            ui.px(12), ui.px(9), ui.px(12), ui.px(12)
        )
        self.outer_layout.setSpacing(ui.px(8))
        self.body_layout.setSpacing(ui.px(5))
        self.orientation_row.setSpacing(ui.px(6))
        self.position_row.setSpacing(ui.px(6))
        close = content_size([self.close_button], ui.size(26, 26))
        side = max(close.width(), close.height())
        self.close_button.setFixedSize(side, side)
        # Wide enough that "-12 mm" never makes the row jump.
        self.position_label.ensurePolished()
        self.position_label.setMinimumWidth(
            self.position_label.fontMetrics().horizontalAdvance("−88 mm")
            + ui.px(8)
        )

    def preferred_width(self, ui: UiScale) -> int:
        """Design width, widened if the polished content needs more."""
        self.ensurePolished()
        # Row minimums are cached from before the style sheet was applied.
        _invalidate_tree(self.outer_layout)
        _invalidate_tree(self.body_layout)
        margins = self.outer_layout.contentsMargins()
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        content = max(
            self.body_layout.minimumSize().width(),
            self.outer_layout.minimumSize().width() - margins.left() - margins.right(),
        )
        return max(
            ui.px(280),
            content + margins.left() + margins.right() + scrollbar + 2 * self.frameWidth(),
        )

    def set_target(
        self,
        side: SideName,
        card: CardSide | None,
        offset_mm: float,
        *,
        front_available: bool,
        back_available: bool,
        busy: bool = False,
    ) -> None:
        self.side = side
        self.title.setText(f"Edit – {side.title()}")
        self.side_buttons["front"].setEnabled(front_available)
        self.side_buttons["back"].setEnabled(back_available)
        self.side_buttons[side].setChecked(True)
        self.position_label.setText(position_text(offset_mm))

        editable = card is not None and not busy
        self.body.setEnabled(editable)
        self.reset_button.setEnabled(editable and has_user_edits(card, offset_mm))
        if card is None:
            return
        set_corners_emphasis(self.corners_button, card_status(card)[0])
        rotated, mirrored = orientation_toggles(card)
        self.rotate_button.setChecked(rotated)
        self.mirror_button.setChecked(mirrored)
        state = card.image_correction_state
        self._check_exclusive(self._sharp_group, self.sharpness_buttons, state.sharpen)
        self._check_exclusive(self._tone_group, self.brightness_buttons, state.tone)

    @staticmethod
    def _check_exclusive(
        group: QButtonGroup, buttons: dict[str, QPushButton], key: str
    ) -> None:
        # A preset that is not offered (kept in the model) shows nothing checked.
        group.setExclusive(False)
        for preset, button in buttons.items():
            button.setChecked(preset == key)
        group.setExclusive(True)
