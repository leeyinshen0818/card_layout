"""Resolution-aware UI sizing helpers built only on Qt APIs.

The interface was designed on a 1920x1080 display at 125% Windows scaling,
which leaves about 1536x816 logical pixels once the taskbar is excluded.  Every
other screen gets one proportional factor derived from its real available
area, so the window keeps the same proportions instead of squeezing fixed-pixel
controls.  Controls are additionally sized from real font metrics so text never
clips when fonts round up.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QWidget

BASELINE_AVAILABLE = QSize(1536, 816)
MIN_SCALE = 0.72
MAX_SCALE = 1.75
MIN_FONT_PT = 7.0


def compute_scale(
    available_width: int, available_height: int, chrome_height: int = 0
) -> float:
    """Return the clamped factor relating an available area to the baseline.

    ``chrome_height`` is the non-scaling window furniture (title bar and
    status bar). It is removed from both the baseline and the measured screen,
    so the baseline always yields exactly 1.0.
    """
    width_ratio = available_width / BASELINE_AVAILABLE.width()
    height_ratio = max(1, available_height - chrome_height) / max(
        1, BASELINE_AVAILABLE.height() - chrome_height
    )
    return min(MAX_SCALE, max(MIN_SCALE, min(width_ratio, height_ratio)))


def available_size(widget: QWidget | None = None) -> QSize:
    """Available screen area in logical pixels (taskbar already excluded)."""
    screen = widget.screen() if widget is not None else None
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return QSize(BASELINE_AVAILABLE)
    return screen.availableGeometry().size()


def title_bar_height(widget: QWidget | None = None) -> int:
    style = widget.style() if widget is not None else QApplication.style()
    return max(0, style.pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight))


def window_chrome_height(widget: QWidget | None = None) -> int:
    status_bar = QFontMetrics(QApplication.font()).height() + 8
    return title_bar_height(widget) + status_bar


@dataclass(frozen=True, slots=True)
class UiScale:
    """One proportional factor plus conversion helpers for design values."""

    factor: float = 1.0

    @classmethod
    def for_widget(cls, widget: QWidget | None = None) -> UiScale:
        size = available_size(widget)
        return cls(
            compute_scale(size.width(), size.height(), window_chrome_height(widget))
        )

    def px(self, value: float) -> int:
        """Scale a design pixel value (never collapsing a positive value)."""
        if value <= 0:
            return 0
        return max(1, int(round(value * self.factor)))

    def pt(self, value: float) -> str:
        """Scale a design point size for style sheets, with a legibility floor."""
        return f"{max(MIN_FONT_PT, value * self.factor):.2f}pt"

    def size(self, width: float, height: float) -> QSize:
        return QSize(self.px(width), self.px(height))


def bounded_to_screen(desired: QSize, widget: QWidget | None = None) -> QSize:
    """Limit a window/dialog size to the available screen minus its title bar."""
    available = available_size(widget)
    return QSize(
        max(1, min(desired.width(), available.width())),
        max(1, min(desired.height(), available.height() - title_bar_height(widget))),
    )


def content_size(widgets: Iterable[QWidget], design: QSize) -> QSize:
    """Largest polished size hint among widgets, never below the design size."""
    width, height = design.width(), design.height()
    for widget in widgets:
        widget.ensurePolished()
        hint = widget.sizeHint()
        width = max(width, hint.width())
        height = max(height, hint.height())
    return QSize(width, height)


def grid_columns(
    available_width: int, item_width: int, spacing: int, maximum: int
) -> int:
    """How many equally sized items fit in one row (at least one)."""
    if item_width <= 0:
        return max(1, maximum)
    fitting = (available_width + spacing) // (item_width + spacing)
    return int(max(1, min(maximum, fitting)))


def sharp_pixmap(source: QPixmap, target: QSize, device_pixel_ratio: float) -> QPixmap:
    """Aspect-fit ``source`` into a logical ``target`` at physical resolution."""
    ratio = max(1.0, float(device_pixel_ratio))
    physical = QSize(
        max(1, int(round(target.width() * ratio))),
        max(1, int(round(target.height() * ratio))),
    )
    scaled = source.scaled(
        physical,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(ratio)
    return scaled
