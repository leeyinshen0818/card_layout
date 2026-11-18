from __future__ import annotations

import os
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QWidget,
)
from PIL import Image

from cardlayout.models.card_side import CardSide
from cardlayout.models.detection import CardDetectionResult
from cardlayout.models.perspective import PerspectiveResult
import cardlayout.ui.main_window as main_window_module
import cardlayout.__main__ as app_module
from cardlayout.ui.card_input_widget import card_status
from cardlayout.ui.main_window import MainWindow
from cardlayout.ui.scaling import MAX_SCALE, MIN_SCALE, compute_scale


def _click_card(window: MainWindow, side: str) -> None:
    layout = window.engine.calculate()
    rect = layout.front if side == "front" else layout.back
    target = window.preview._card_target(rect, window.preview._page_rect())
    QTest.mouseClick(
        window.preview,
        Qt.MouseButton.LeftButton,
        pos=target.center().toPoint(),
    )
    QApplication.processEvents()


def _card_side(tmp_path: Path, side: str, image: Image.Image | None = None) -> CardSide:
    source = image or Image.new(
        "RGB", (428, 270), (120, 150, 180) if side == "front" else (80, 110, 140)
    )
    return CardSide(
        side=side,  # type: ignore[arg-type]
        source_path=tmp_path / f"{side}.png",
        source_type="image",
        source_page=None,
        original_image=source,
        processed_image=source.copy(),
    )


def test_application_starts_maximized(monkeypatch) -> None:
    events: list[str] = []

    class _Application:
        def __init__(self, arguments) -> None:
            del arguments

        def setApplicationName(self, name: str) -> None:
            del name

        def setOrganizationName(self, name: str) -> None:
            del name

        def setWindowIcon(self, icon) -> None:
            assert icon == "application-icon"
            events.append("application-icon")

        def exec(self) -> int:
            return 0

    class _Window:
        def setWindowIcon(self, icon) -> None:
            assert icon == "application-icon"
            events.append("window-icon")

        def showMaximized(self) -> None:
            events.append("maximized")

    monkeypatch.setattr(app_module, "QApplication", _Application)
    monkeypatch.setattr(app_module, "MainWindow", _Window)
    monkeypatch.setattr(app_module, "QIcon", lambda path: "application-icon")

    assert app_module.main() == 0
    assert events == ["application-icon", "window-icon", "maximized"]


def test_ui_scale_tracks_available_logical_screen_area() -> None:
    # 1920x1080 at 125% minus the taskbar is the design baseline.
    assert compute_scale(1536, 816, 55) == pytest.approx(1.0)
    # 1920x1080 at 100%: proportionally larger.
    assert compute_scale(1920, 1032, 55) == pytest.approx(1.25, abs=0.02)
    # The shorter dimension limits the factor.
    assert compute_scale(1536, 600, 55) < 1536 / 1536
    # 1366x768 at 125% and huge screens are clamped.
    assert compute_scale(1093, 566, 55) == pytest.approx(MIN_SCALE)
    assert compute_scale(3840, 2112, 55) == pytest.approx(MAX_SCALE)


def _phone_photo(tmp_path: Path, name: str, angle: float = 22) -> Path:
    pixels = np.full((600, 800, 3), (45, 55, 65), dtype=np.uint8)
    box = cv2.boxPoints(((400, 300), (320, 202), angle)).astype(np.int32)
    cv2.fillConvexPoly(pixels, box, (225, 235, 245))
    cv2.polylines(pixels, [box], True, (10, 10, 10), 5)
    path = tmp_path / name
    Image.fromarray(pixels).save(path)
    return path


def _window_with_cards(tmp_path: Path, front=None, back=None) -> MainWindow:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.front = front if front is not None else _card_side(tmp_path, "front")
    window.back = back if back is not None else _card_side(tmp_path, "back")
    window._refresh()
    window.show()
    app.processEvents()
    return window


def test_edit_panel_buttons_fit_their_text_and_scroll_only_vertically(
    tmp_path: Path,
) -> None:
    window = _window_with_cards(tmp_path)
    window._open_editor("front")
    QApplication.processEvents()
    panel = window.edit_panel
    buttons = [
        panel.rotate_button,
        panel.mirror_button,
        panel.up_button,
        panel.down_button,
        panel.corners_button,
        panel.reset_button,
        *panel.side_buttons.values(),
        *panel.sharpness_buttons.values(),
        *panel.brightness_buttons.values(),
    ]
    for button in buttons:
        assert button.width() >= button.minimumSizeHint().width()
        assert button.height() >= button.minimumSizeHint().height()
    assert panel.width() >= panel.minimumWidth()
    assert panel.scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert window.controls_scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    window.close()


def test_main_window_uses_clean_responsibility_based_layout() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()

    texts = [label.text() for label in window.findChildren(QLabel)]
    assert "CardLayout" not in texts
    assert window.findChild(QFrame, "header") is None
    assert not any("No uploads" in text for text in texts)
    assert window.size_caption.text() == (
        "Malaysia IC / Driving Licence – 85.6 × 54 mm"
    )
    assert "Print exported PDF at Actual Size / 100%" in texts
    assert window.open_button.text() == "Open files…"
    assert window.open_button.geometry().top() < window.front_widget.geometry().top()
    assert window.front_widget.geometry().bottom() < window.swap_button.geometry().top()
    assert window.swap_button.geometry().bottom() < window.back_widget.geometry().top()
    assert window.swap_button.text() == "⇅  Swap Front / Back"
    assert window.export_pdf_button.objectName() == "primaryButton"
    assert window.export_jpg_button.objectName() == "jpgButton"
    assert window.findChild(QWidget, "previewControls") is None
    window.close()


def test_exports_save_directly_to_downloads_without_save_dialog(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    saved_paths: list[Path] = []
    opened_folders: list[Path] = []

    monkeypatch.setattr(window, "_downloads_directory", lambda: tmp_path)
    monkeypatch.setattr(
        window.jpg_exporter,
        "export",
        lambda path, front, back: saved_paths.append(Path(path)),
    )
    monkeypatch.setattr(
        window.pdf_exporter,
        "export",
        lambda path, front, back: saved_paths.append(Path(path)),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: pytest.fail("Save As dialog must not open"),
    )
    monkeypatch.setattr(
        main_window_module.QDesktopServices,
        "openUrl",
        lambda url: opened_folders.append(Path(url.toLocalFile())) or True,
    )

    (tmp_path / "card-layout.jpg").touch()
    window._export_jpg()
    window._export_pdf()

    assert saved_paths == [
        tmp_path / "card-layout (1).jpg",
        tmp_path / "card-layout.pdf",
    ]
    assert opened_folders == [tmp_path.resolve(), tmp_path.resolve()]
    assert "exported to" in window.statusBar().currentMessage()
    window.close()


def test_edit_panel_position_buttons_move_each_side_and_show_offset(
    tmp_path: Path,
) -> None:
    window = _window_with_cards(tmp_path)
    panel = window.edit_panel

    _click_card(window, "front")
    assert window.preview.selected_side == "front"
    assert panel.isVisible()
    assert panel.position_label.text() == "Default"

    QTest.mouseClick(panel.down_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.down_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.engine.vertical_offset("front") == 2.0
    assert panel.position_label.text() == "+2 mm"

    _click_card(window, "back")
    QTest.mouseClick(panel.up_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.up_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.engine.vertical_offset("front") == 2.0
    assert window.engine.vertical_offset("back") == -2.0
    assert panel.position_label.text() == "−2 mm"

    QTest.mouseClick(panel.close_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not panel.isVisible()
    assert window.preview.selected_side is None
    window.close()


def test_empty_preview_slot_is_a_faint_placeholder_and_not_clickable(
    tmp_path: Path,
) -> None:
    window = _window_with_cards(tmp_path)
    window._set_card("back", None)
    window._refresh()
    QApplication.processEvents()

    page_rect = window.preview._page_rect()
    back_rect = window.preview._card_target(
        window.engine.calculate().back, page_rect
    ).toAlignedRect()
    image = window.preview.grab().toImage()
    inside = QPoint(
        back_rect.left() + back_rect.width() // 4,
        back_rect.top() + back_rect.height() // 4,
    )
    assert image.pixelColor(inside).getRgb()[:3] == (255, 255, 255)
    border = image.pixelColor(QPoint(back_rect.left(), back_rect.center().y()))
    assert min(border.getRgb()[:3]) > 180  # faint, not a solid dark frame

    _click_card(window, "back")
    assert window.preview.selected_side is None
    assert not window.edit_panel.isVisible()
    window.close()


def test_rotate_and_mirror_are_independent_toggles(tmp_path: Path) -> None:
    pattern = Image.new("RGB", (4, 2))
    pattern.putdata(
        [
            (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
            (255, 0, 255), (0, 255, 255), (40, 50, 60), (70, 80, 90),
        ]
    )
    window = _window_with_cards(
        tmp_path,
        _card_side(tmp_path, "front", pattern),
        _card_side(tmp_path, "back", pattern.copy()),
    )
    panel = window.edit_panel
    _click_card(window, "front")

    QTest.mouseClick(panel.mirror_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.mirror_button.isChecked() and not panel.rotate_button.isChecked()
    assert window.front.best_image.tobytes() == pattern.transpose(
        Image.Transpose.FLIP_LEFT_RIGHT
    ).tobytes()
    assert window.back.orientation_state.is_normal

    QTest.mouseClick(panel.rotate_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.mirror_button.isChecked() and panel.rotate_button.isChecked()
    assert window.front.best_image.tobytes() == pattern.transpose(
        Image.Transpose.FLIP_TOP_BOTTOM
    ).tobytes()

    QTest.mouseClick(panel.mirror_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert not panel.mirror_button.isChecked() and panel.rotate_button.isChecked()
    assert window.front.best_image.tobytes() == pattern.transpose(
        Image.Transpose.ROTATE_180
    ).tobytes()

    QTest.mouseClick(panel.rotate_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.front.orientation_state.is_normal
    assert window.front.best_image.tobytes() == pattern.tobytes()
    assert not hasattr(panel, "orientation_status")
    window.close()


def test_card_panel_is_clean_and_reset_this_card_restores_everything(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    path = _phone_photo(tmp_path, "phone-photo.png")
    window = MainWindow()
    window.show()
    app.processEvents()
    window._load_side(str(path), "front")
    window.wait_for_detection()

    assert window.front is not None
    assert window.front.detection_result is not None
    assert window.front.detection_result.success
    assert window.front.rectified_image is not None
    original_bytes = window.front.original_image.tobytes()
    automatic_bytes = window.front.best_image.tobytes()

    card = window.front_widget
    for removed in ("edit_button", "reset_button", "clear_button"):
        assert not hasattr(card, removed)
    assert card.choose_button.text() == "Choose Front"
    assert card.remove_button.text() == "Remove"
    assert card.corners_button.text() == "Adjust corners…"
    assert card.more_button.text() == "More edits…"
    assert not window.back_widget.corners_button.isEnabled()
    assert not window.back_widget.more_button.isEnabled()
    assert window.back_widget.preview.text() == "Drop or choose a file"

    QTest.mouseClick(card.more_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    panel = window.edit_panel
    assert panel.isVisible()
    assert not panel.reset_button.isEnabled()
    assert set(panel.sharpness_buttons) == {"normal", "sharper"}
    assert set(panel.brightness_buttons) == {
        "normal",
        "bright_contrast",
        "strong_bright_contrast",
    }
    assert panel.brightness_buttons["strong_bright_contrast"].text() == "Strong"

    QTest.mouseClick(panel.sharpness_buttons["sharper"], Qt.MouseButton.LeftButton)
    QTest.mouseClick(
        panel.brightness_buttons["bright_contrast"], Qt.MouseButton.LeftButton
    )
    QTest.mouseClick(panel.rotate_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.down_button, Qt.MouseButton.LeftButton)
    manual = window.card_processor.apply_manual_correction(
        window.front, window.front.detection_result.polygon_points
    )
    assert manual.success
    window._refresh()
    app.processEvents()
    assert window.front.image_correction_state.sharpen == "sharper"
    assert window.front.best_image.tobytes() != automatic_bytes
    assert panel.reset_button.isEnabled()

    QTest.mouseClick(panel.reset_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.front.image_correction_state.is_normal
    assert window.front.orientation_state.is_normal
    assert not window.front.has_manual_correction
    assert window.engine.vertical_offset("front") == 0.0
    assert window.front.best_image.tobytes() == automatic_bytes
    assert window.front.original_image.tobytes() == original_bytes
    assert panel.isVisible()
    assert not panel.reset_button.isEnabled()
    assert panel.sharpness_buttons["normal"].isChecked()

    QTest.mouseClick(card.remove_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.front is None
    assert not panel.isVisible()
    assert card.status_text == "Empty"
    window.close()


def test_edit_panel_switches_target_without_closing(tmp_path: Path) -> None:
    window = _window_with_cards(tmp_path)
    panel = window.edit_panel
    closed_width = window.preview_panel.width()

    QTest.mouseClick(window.front_widget.preview, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.isVisible()
    assert panel.title.text() == "Edit – Front"
    assert panel.side_buttons["front"].isChecked()
    assert window.preview.selected_side == "front"
    assert window.preview_panel.width() < closed_width
    assert panel.geometry().left() >= window.preview_panel.geometry().right()

    QTest.mouseClick(
        panel.sharpness_buttons["sharper"], Qt.MouseButton.LeftButton
    )
    QTest.mouseClick(panel.side_buttons["back"], Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.isVisible()
    assert panel.title.text() == "Edit – Back"
    assert window.edit_side == "back"
    assert window.preview.selected_side == "back"
    assert panel.sharpness_buttons["normal"].isChecked()

    QTest.mouseClick(
        panel.brightness_buttons["bright_contrast"], Qt.MouseButton.LeftButton
    )
    QApplication.processEvents()
    assert window.front.image_correction_state.sharpen == "sharper"
    assert window.front.image_correction_state.tone == "normal"
    assert window.back.image_correction_state.sharpen == "normal"
    assert window.back.image_correction_state.tone == "bright_contrast"

    QTest.mouseClick(panel.side_buttons["front"], Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert panel.sharpness_buttons["sharper"].isChecked()

    # With only one side loaded the other target cannot be chosen.
    window._remove_side("back")
    QApplication.processEvents()
    assert panel.isVisible()
    assert not panel.side_buttons["back"].isEnabled()

    window.resize(1050, 720)
    QApplication.processEvents()
    assert panel.geometry().left() >= window.preview_panel.geometry().right()
    assert window.preview.width() >= window.preview.minimumWidth()
    window.close()


def test_card_status_wording(tmp_path: Path) -> None:
    card = _card_side(tmp_path, "front")
    assert card_status(None) == ("Empty", "muted")
    assert card_status(card, busy=True)[0] == "Detecting…"

    card.apply_detection(
        CardDetectionResult(success=False, confidence=0.1, confidence_level="low")
    )
    assert card_status(card) == ("Card not found – set corners", "error")

    rough = ((10.0, 10.0), (400.0, 12.0), (398.0, 260.0), (12.0, 258.0))
    card.apply_detection(
        CardDetectionResult(
            success=True,
            confidence=0.5,
            confidence_level="medium",
            polygon_points=rough,
            cropped_image=card.original_image.copy(),
        )
    )
    card.apply_automatic_correction(
        PerspectiveResult(
            success=True,
            source_points=rough,
            refined_points=rough,
            rectified_image=card.original_image.copy(),
            status="review",
        )
    )
    assert card_status(card) == ("Check corners", "warn")

    card.apply_manual_correction(
        PerspectiveResult(
            success=True,
            source_points=rough,
            rectified_image=card.original_image.copy(),
            status="corrected",
            method="manual",
        )
    )
    assert card_status(card) == ("Ready", "ok")

    window = _window_with_cards(tmp_path, front=card)
    assert window.front_widget.status_text == "Ready"
    assert window.front_widget.status_chip.isVisible()
    window._set_card("back", None)
    window._refresh()
    assert window.back_widget.status_text == "Empty"
    window.close()


def test_failed_detection_status_stays_on_card_and_corners_open_from_edges(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "plain.png"
    Image.new("RGB", (600, 400), (90, 90, 90)).save(path)
    window = MainWindow()
    window._load_side(str(path), "front")
    window.wait_for_detection()
    assert window.front is not None
    assert window.front_widget.status_text == "Card not found – set corners"
    window.statusBar().clearMessage()
    app.processEvents()
    assert window.front_widget.status_text == "Card not found – set corners"

    captured = {}

    class _Editor:
        result = None

        def __init__(self, image, automatic_points, corrector, confidence, current_points, parent):
            del image, corrector, confidence, parent
            captured["automatic"] = automatic_points
            captured["current"] = current_points

        def exec(self):
            return 0

    monkeypatch.setattr(main_window_module, "CornerEditorDialog", _Editor)
    window._open_editor("front")
    QTest.mouseClick(window.edit_panel.corners_button, Qt.MouseButton.LeftButton)
    corners = captured["automatic"]
    assert len(corners) == 4
    assert corners[0][0] < 50 and corners[2][0] > 550
    window.close()


def test_adjust_corners_button_is_emphasised_by_state_and_opens_editor(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "plain.png"
    Image.new("RGB", (600, 400), (90, 90, 90)).save(path)
    window = MainWindow()
    window.show()
    window._load_side(str(path), "front")
    window.wait_for_detection()
    card = window.front_widget
    assert card.status_text == "Card not found – set corners"
    assert card.corners_button.property("emphasis") == "strong"
    window._open_editor("front")
    app.processEvents()
    panel_layout = window.edit_panel.body_layout
    # Corners is the first section, directly under the Front | Back switch.
    assert panel_layout.itemAt(0).widget().text() == "CORNERS"
    assert panel_layout.indexOf(window.edit_panel.corners_button) == 1
    assert window.edit_panel.corners_button.property("emphasis") == "strong"

    opened: list[str] = []

    class _Editor:
        def __init__(self, image, automatic_points, corrector, confidence, current_points, parent):
            del corrector, confidence, current_points, parent
            opened.append("editor")
            self.result = PerspectiveResult(
                success=True,
                source_points=automatic_points,
                rectified_image=image.copy(),
                status="corrected",
                method="manual",
            )

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "CornerEditorDialog", _Editor)
    QTest.mouseClick(card.corners_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert opened == ["editor"]
    assert card.status_text == "Ready"
    assert card.corners_button.property("emphasis") == "normal"
    assert window.edit_panel.corners_button.property("emphasis") == "normal"
    assert card.more_button.objectName() == "secondaryButton"
    window.close()


def test_open_files_routes_pdf_pages_and_file_pairs(
    tmp_path: Path,
    monkeypatch,
    sample_jpg: Path,
    sample_png: Path,
    two_page_pdf: Path,
    three_page_pdf: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    two_page, three_page = two_page_pdf, three_page_pdf
    infos: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda parent, title, text: infos.append(text)
    )
    window = MainWindow()
    window.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(two_page)], ""),
    )
    QTest.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    window.wait_for_detection()
    assert window.front.source_path == two_page and window.front.source_page == 1
    assert window.back.source_path == two_page and window.back.source_page == 2
    assert window.settings.value(main_window_module.LAST_FOLDER_KEY) == str(
        tmp_path.resolve()
    )

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(sample_png), str(sample_jpg)], ""),
    )
    QTest.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    window.wait_for_detection()
    assert window.front.source_path == sample_png and window.front.side == "front"
    assert window.back.source_path == sample_jpg and window.back.side == "back"
    assert infos == []

    # Two files where one is a multi-page PDF: that side uses page 1 only.
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(sample_jpg), str(three_page)], ""),
    )
    QTest.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    window.wait_for_detection()
    assert window.front.source_path == sample_jpg
    assert window.back.source_path == three_page and window.back.source_page == 1
    assert len(infos) == 1 and infos[0].startswith("Back:")

    # Per-side Choose loads only that side and starts in the remembered folder.
    starts: list[str] = []

    def _choose(parent, caption, start, file_filter):
        starts.append(start)
        return str(two_page), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", _choose)
    QTest.mouseClick(window.front_widget.choose_button, Qt.MouseButton.LeftButton)
    window.wait_for_detection()
    assert starts == [str(tmp_path.resolve())]
    assert window.front.source_path == two_page and window.front.source_page == 1
    assert window.back.source_path == three_page
    window.close()
    app.processEvents()


def test_detection_runs_in_background_and_stale_results_are_discarded(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    path = _phone_photo(tmp_path, "slow.png", angle=12)
    gate = threading.Event()
    window = MainWindow()
    real_detect = window.card_processor.detect

    def _slow_detect(card):
        gate.wait(5)
        return real_detect(card)

    monkeypatch.setattr(window.card_processor, "detect", _slow_detect)
    window._load_side(str(path), "front")
    # Loading returned while detection is still blocked in the worker.
    assert window.is_detecting("front")
    assert window.front_widget.status_text == "Detecting…"
    assert not window.front_widget.corners_button.isEnabled()
    assert window.back_widget.choose_button.isEnabled()
    assert window.front_widget.remove_button.isEnabled()
    pending = window.front

    window._remove_side("front")
    gate.set()
    window._detect_pool.waitForDone()
    app.processEvents()
    assert window.front is None
    assert pending.detection_result is None
    assert window.front_widget.status_text == "Empty"

    gate.clear()
    window._load_side(str(path), "front")
    first = window.front
    window._load_side(str(path), "front")
    second = window.front
    gate.set()
    window.wait_for_detection()
    assert window.front is not first and window.front is not second
    assert window.front.source_path == second.source_path
    assert window.front.detection_result is not None
    assert window.front_widget.status_text in {"Ready", "Check corners"}
    window.close()


def test_corner_editor_starts_from_refined_automatic_corners(
    monkeypatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    image = Image.new("RGB", (800, 600), (80, 100, 120))
    rough = ((100.0, 100.0), (700.0, 110.0), (690.0, 490.0), (105.0, 480.0))
    refined = ((106.0, 104.0), (694.0, 114.0), (685.0, 484.0), (110.0, 476.0))
    side = CardSide(
        side="front",
        source_path=tmp_path / "refined-start.png",
        source_type="image",
        source_page=None,
        original_image=image,
        processed_image=image.copy(),
    )
    side.apply_detection(
        CardDetectionResult(
            success=True,
            confidence=0.9,
            confidence_level="high",
            polygon_points=rough,
            cropped_image=image.crop((100, 100, 700, 490)),
        )
    )
    side.apply_automatic_correction(
        PerspectiveResult(
            success=True,
            source_points=rough,
            refined_points=refined,
            rectified_image=Image.new("RGB", (856, 540), "white"),
            confidence=0.9,
            confidence_level="high",
            status="corrected",
            method="automatic",
        )
    )
    captured = {}

    class _CancelledEditor:
        result = None

        def __init__(self, image, automatic_points, corrector, confidence, current_points, parent):
            del image, corrector, confidence, parent
            captured["automatic"] = automatic_points
            captured["current"] = current_points

        def exec(self):
            return 0

    monkeypatch.setattr(main_window_module, "CornerEditorDialog", _CancelledEditor)
    window = MainWindow()
    window.front = side
    window._adjust_corners("front")

    assert captured["automatic"] == refined
    assert captured["current"] == refined
    window.close()
    app.processEvents()
