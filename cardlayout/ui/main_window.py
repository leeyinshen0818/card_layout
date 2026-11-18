from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QStandardPaths,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from cardlayout.models.card_side import CardSide, SideName
from cardlayout.models.card_size import MALAYSIA_IC
from cardlayout.models.detection import CardDetectionResult, Point
from cardlayout.models.orientation import OrientationAction
from cardlayout.models.layout import A4_LAYOUT
from cardlayout.services.card_detector import CardDetector
from cardlayout.services.card_processing import CardProcessingService
from cardlayout.services.image_exporter import ExportError, ImageExporter
from cardlayout.services.input_loader import InputLoadError, InputLoader, SUPPORTED_SUFFIXES
from cardlayout.services.layout_engine import LayoutEngine
from cardlayout.services.page_renderer import PageRenderer
from cardlayout.services.pdf_exporter import PDFExporter
from cardlayout.ui.card_input_widget import CardInputWidget
from cardlayout.ui.corner_editor import CornerEditorDialog
from cardlayout.ui.edit_panel import EditPanel
from cardlayout.ui.page_preview import PagePreview
from cardlayout.ui.scaling import UiScale, bounded_to_screen

FILE_FILTER = "Card sources (*.jpg *.jpeg *.png *.pdf)"
LAST_FOLDER_KEY = "dialogs/last_open_folder"
CARD_SIZE_CAPTION = "Malaysia IC / Driving Licence – 85.6 × 54 mm"
SIDES: tuple[SideName, SideName] = ("front", "back")


def _detection_failure() -> CardDetectionResult:
    return CardDetectionResult(
        success=False,
        confidence=0.0,
        confidence_level="none",
        method="processing_error",
        debug_info={"reason": "Detection processing failed"},
    )


class _DetectionSignals(QObject):
    # original card object, processed copy, detection result
    finished = Signal(object, object, object)


class _DetectionTask(QRunnable):
    """Runs detection on a private copy so the UI thread never sees it mid-way."""

    def __init__(
        self,
        processor: CardProcessingService,
        original: CardSide,
        signals: _DetectionSignals,
    ) -> None:
        super().__init__()
        self.processor = processor
        self.original = original
        self.work = replace(original)
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.processor.detect(self.work)
        except Exception:
            result = _detection_failure()
            self.work.apply_detection(result)
        self.signals.finished.emit(self.original, self.work, result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.front: CardSide | None = None
        self.back: CardSide | None = None
        self.input_loader = InputLoader()
        self.card_processor = CardProcessingService(CardDetector(MALAYSIA_IC))
        self.engine = LayoutEngine(A4_LAYOUT, MALAYSIA_IC)
        self.renderer = PageRenderer(self.engine)
        self.jpg_exporter = ImageExporter(self.renderer)
        self.pdf_exporter = PDFExporter(self.renderer)
        self.settings = QSettings("CardLayout", "CardLayout")
        self.edit_side: SideName | None = None

        # Detection runs off the UI thread, one card at a time, because the
        # detector/corrector instances are shared.
        self._detect_pool = QThreadPool(self)
        self._detect_pool.setMaxThreadCount(1)
        self._detect_signals = _DetectionSignals(self)
        self._detect_signals.finished.connect(self._detection_finished)
        self._pending: dict[str, CardSide] = {}
        self._tasks: dict[str, _DetectionTask] = {}

        # One proportional factor from the real available screen area replaces
        # the old compact/regular switch (1.0 on 1920x1080 at 125% scaling).
        self.ui = UiScale.for_widget(self)
        self.ui_scale = self.ui.factor
        self._panel_width = self.ui.px(280)

        self.setWindowTitle("CardLayout")
        self.setMinimumSize(bounded_to_screen(self.ui.size(900, 600), self))
        self.resize(bounded_to_screen(self.ui.size(1180, 760), self))
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_style()
        self._apply_metrics()
        self._refresh()

    # ----------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        ui = self.ui
        self.open_button = QPushButton("Open files…")
        self.open_button.setObjectName("secondaryButton")
        self.open_button.setToolTip(
            "One 2-page PDF (page 1 = Front, page 2 = Back) or two files "
            "(first = Front, second = Back)"
        )
        self.open_button.clicked.connect(self._choose_files)
        self.swap_button = QPushButton("⇅  Swap Front / Back")
        self.swap_button.setObjectName("quietButton")
        self.swap_button.clicked.connect(self._swap_sides)

        self.front_widget = CardInputWidget("front")
        self.back_widget = CardInputWidget("back")
        for widget in (self.front_widget, self.back_widget):
            widget.choose_requested.connect(self._choose_side)
            widget.remove_requested.connect(self._remove_side)
            widget.edit_requested.connect(self._open_editor)
            widget.corners_requested.connect(self._adjust_corners)

        import_caption = QLabel("IMPORT")
        import_caption.setObjectName("sectionCaption")
        self.size_caption = QLabel(CARD_SIZE_CAPTION)
        self.size_caption.setObjectName("sizeCaption")
        self.size_caption.setWordWrap(True)

        controls_layout = QVBoxLayout()
        controls_margin = ui.px(12)
        controls_layout.setContentsMargins(
            controls_margin, controls_margin, controls_margin, controls_margin
        )
        controls_layout.setSpacing(ui.px(8))
        controls_layout.addWidget(import_caption)
        controls_layout.addWidget(self.open_button)
        controls_layout.addWidget(self.front_widget)
        controls_layout.addWidget(self.swap_button)
        controls_layout.addWidget(self.back_widget)
        controls_layout.addWidget(self.size_caption)
        controls_layout.addStretch()

        controls = QWidget()
        controls.setLayout(controls_layout)
        controls.setObjectName("controlsPanel")
        scroll = QScrollArea()
        scroll.setObjectName("controlsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(controls)
        self.controls_scroll = scroll

        preview_title = QLabel("A4 PORTRAIT PREVIEW")
        preview_title.setObjectName("sectionCaption")
        self.preview_hint = QLabel("Click a card to adjust")
        self.preview_hint.setObjectName("previewHint")
        self.preview = PagePreview(self.engine)
        self.preview.side_selected.connect(self._open_editor)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        preview_heading = QHBoxLayout()
        preview_heading.addWidget(preview_title)
        preview_heading.addStretch()
        preview_heading.addWidget(self.preview_hint)
        preview_layout = QVBoxLayout()
        preview_margin = ui.px(12)
        preview_layout.setContentsMargins(
            preview_margin, preview_margin, preview_margin, preview_margin
        )
        preview_layout.addLayout(preview_heading)
        preview_layout.addWidget(self.preview, 1)
        self.preview_panel = QWidget()
        self.preview_panel.setObjectName("previewPanel")
        self.preview_panel.setLayout(preview_layout)

        self.edit_panel = EditPanel()
        self.edit_panel.side_switch_requested.connect(self._open_editor)
        self.edit_panel.close_requested.connect(self._close_editor)
        self.edit_panel.orientation_toggled.connect(self._apply_orientation_action)
        self.edit_panel.position_step_requested.connect(self._step_position)
        self.edit_panel.preset_selected.connect(self._select_correction_preset)
        self.edit_panel.adjust_corners_requested.connect(self._adjust_edited_corners)
        self.edit_panel.reset_requested.connect(self._reset_edited_card)
        self.edit_panel.hide()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(scroll)
        self.splitter.addWidget(self.preview_panel)
        self.splitter.addWidget(self.edit_panel)
        self.splitter.setSizes([ui.px(325), ui.px(850), 0])
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, True)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        export_pdf = QPushButton("Export PDF")
        export_pdf.setObjectName("primaryButton")
        export_pdf.clicked.connect(self._export_pdf)
        export_jpg = QPushButton("Export JPG · 300 DPI")
        export_jpg.setObjectName("jpgButton")
        export_jpg.clicked.connect(self._export_jpg)
        self.export_pdf_button = export_pdf
        self.export_jpg_button = export_jpg
        print_note = QLabel("Print exported PDF at Actual Size / 100%")
        print_note.setObjectName("footerNote")
        export_bar = QHBoxLayout()
        export_horizontal = ui.px(16)
        export_vertical = ui.px(8)
        export_bar.setContentsMargins(
            export_horizontal, export_vertical, export_horizontal, export_vertical
        )
        export_bar.setSpacing(ui.px(10))
        export_bar.addWidget(print_note)
        export_bar.addStretch()
        export_bar.addWidget(export_jpg)
        export_bar.addWidget(export_pdf)
        export_widget = QFrame()
        export_widget.setObjectName("exportBar")
        export_widget.setLayout(export_bar)

        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.splitter, 1)
        central_layout.addWidget(export_widget)
        central = QWidget()
        central.setLayout(central_layout)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Drop one or two JPG, PNG, or PDF files to begin")

    # ------------------------------------------------------------ file dialogs
    def _start_folder(self) -> str:
        saved = str(self.settings.value(LAST_FOLDER_KEY, "") or "")
        if saved and Path(saved).is_dir():
            return saved
        for location in (
            QStandardPaths.StandardLocation.DocumentsLocation,
            QStandardPaths.StandardLocation.PicturesLocation,
        ):
            folder = QStandardPaths.writableLocation(location)
            if folder and Path(folder).is_dir():
                return folder
        return str(Path.home())

    def _remember_folder(self, path: str) -> None:
        self.settings.setValue(LAST_FOLDER_KEY, str(Path(path).resolve().parent))
        self.settings.sync()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open files", self._start_folder(), FILE_FILTER
        )
        if paths:
            self._remember_folder(paths[0])
            self._open_paths(paths)

    def _choose_side(self, side: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Choose {side.title()}", self._start_folder(), FILE_FILTER
        )
        if path:
            self._remember_folder(path)
            self._load_side(path, side)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- loading
    def _open_paths(self, paths: list[str]) -> None:
        """One 2-page PDF -> page 1 Front, page 2 Back; two files -> Front, Back."""
        paths = [str(path) for path in paths]
        if not paths:
            return
        ignored = len(paths) > 2
        paths = paths[:2]
        notices: list[str] = []
        if len(paths) == 1 and Path(paths[0]).suffix.lower() == ".pdf":
            self._load_two_page_pdf(paths[0])
        else:
            for path, side in zip(paths, SIDES):
                notice = self._load_side(path, side, show_notice=False)
                if notice:
                    notices.append(f"{side.title()}: {notice}")
        if ignored:
            notices.append("Only the first two files were used.")
        if notices:
            QMessageBox.information(self, "Files opened", "\n".join(notices))

    def _load_side(
        self, path: str, side: SideName, *, show_notice: bool = True
    ) -> str | None:
        try:
            result = self.input_loader.load_side(path, side)
        except InputLoadError as exc:
            self._show_error("Could not open file", str(exc))
            return None
        self._set_card(side, result.card_side)
        self._start_detection([side])
        self.statusBar().showMessage(
            f"Loaded {result.card_side.display_name}. Detecting the card…"
        )
        if result.notice and show_notice:
            QMessageBox.information(self, "PDF pages", result.notice)
        return result.notice

    def _load_two_page_pdf(self, path: str) -> None:
        try:
            result = self.input_loader.load_two_page_pdf(path)
        except InputLoadError as exc:
            self._show_error("Could not open PDF", str(exc))
            return
        self._set_card("front", result.front)
        self._set_card("back", result.back)
        self._start_detection([side for side in SIDES if self._card(side) is not None])
        self.statusBar().showMessage(
            f"Loaded {Path(path).name}. Detecting the cards…"
        )
        if result.notice:
            QMessageBox.information(self, "PDF pages", result.notice)

    def _card(self, side: str) -> CardSide | None:
        return self.front if side == "front" else self.back

    def _set_card(self, side: str, card: CardSide | None) -> None:
        """Assign a side; any detection still running for the old card is dropped."""
        task = self._tasks.pop(side, None)
        if task is not None:
            self._detect_pool.tryTake(task)
        self._pending.pop(side, None)
        if side == "front":
            self.front = card
        else:
            self.back = card

    # -------------------------------------------------------------- detection
    def _start_detection(self, sides: list[SideName]) -> None:
        for side in sides:
            card = self._card(side)
            if card is None:
                continue
            task = _DetectionTask(self.card_processor, card, self._detect_signals)
            self._pending[side] = card
            self._tasks[side] = task
            self._detect_pool.start(task)
        self._refresh()

    def is_detecting(self, side: str | None = None) -> bool:
        if side is None:
            return bool(self._pending)
        return side in self._pending

    def wait_for_detection(self) -> None:
        """Block until queued detections finish and their results are applied."""
        for _ in range(100):
            if not self._pending:
                return
            self._detect_pool.waitForDone()
            QApplication.processEvents()

    def _detection_finished(
        self, original: object, work: object, result: object
    ) -> None:
        for side in SIDES:
            if self._pending.get(side) is original and self._card(side) is original:
                self._pending.pop(side, None)
                self._tasks.pop(side, None)
                if side == "front":
                    self.front = work  # type: ignore[assignment]
                else:
                    self.back = work  # type: ignore[assignment]
                self._refresh()
                self.statusBar().showMessage(
                    f"{side.title()}: {self._detection_message(result)}", 8000  # type: ignore[arg-type]
                )
                return
        # The side was replaced or removed meanwhile: the result is discarded.

    @staticmethod
    def _detection_message(result: CardDetectionResult) -> str:
        if result.success and result.confidence_level == "high":
            return "Card found."
        if result.success:
            return "Card found – please check the corners."
        return "Card not found – use Adjust corners."

    # ---------------------------------------------------------- side actions
    def _remove_side(self, side: str) -> None:
        self._set_card(side, None)
        self._refresh()
        self.statusBar().showMessage(f"{side.title()} removed", 3000)

    def _swap_sides(self) -> None:
        if self._pending:
            return
        old_front, old_back = self.front, self.back
        self.front = old_back.assigned_to("front") if old_back else None
        self.back = old_front.assigned_to("back") if old_front else None
        self._refresh()
        self.statusBar().showMessage("Front and Back swapped", 3000)

    def _card_widget(self, side: str) -> CardInputWidget:
        return self.front_widget if side == "front" else self.back_widget

    # ------------------------------------------------------------- edit panel
    def _open_editor(self, side: str) -> None:
        if self._card(side) is None:
            return
        self.edit_side = side  # type: ignore[assignment]
        self.preview.select_side(side, emit=False)  # type: ignore[arg-type]
        if not self.edit_panel.isVisible():
            previous = self.splitter.sizes()
            left_width = previous[0] if previous else self.ui.px(325)
            self.edit_panel.show()
            available = max(0, self.splitter.width() - left_width - self._panel_width)
            self.splitter.setSizes(
                [left_width, max(self.preview.minimumWidth(), available), self._panel_width]
            )
        self._refresh()

    def _close_editor(self) -> None:
        self.edit_side = None
        self.preview.clear_selection()
        self.edit_panel.hide()
        self.preview.updateGeometry()
        self.preview.update()

    def _edited_card(self) -> CardSide | None:
        if self.edit_side is None or self.is_detecting(self.edit_side):
            return None
        return self._card(self.edit_side)

    def _apply_orientation_action(self, action: OrientationAction) -> None:
        card = self._edited_card()
        if card is None:
            return
        card.apply_orientation(card.orientation_state.apply_action(action))
        self._refresh()

    def _select_correction_preset(self, category: str, key: str) -> None:
        card = self._edited_card()
        if card is None:
            return
        state = card.image_correction_state
        if category == "sharpen":
            state = state.with_sharpen(key)  # type: ignore[arg-type]
        elif category == "tone":
            state = state.with_tone(key)  # type: ignore[arg-type]
        else:
            return
        card.apply_image_correction(state)
        self._refresh()

    def _step_position(self, delta_mm: float) -> None:
        if self._edited_card() is None:
            return
        self.engine.adjust_vertical_offset(self.edit_side, delta_mm)  # type: ignore[arg-type]
        self._refresh()

    def _reset_edited_card(self) -> None:
        card = self._edited_card()
        if card is None:
            return
        self.card_processor.reset_user_edits(card)
        self.engine.reset_vertical_offset(self.edit_side)  # type: ignore[arg-type]
        self._refresh()
        self.statusBar().showMessage(f"{self.edit_side.title()} card reset", 4000)  # type: ignore[union-attr]

    def _adjust_edited_corners(self) -> None:
        if self._edited_card() is not None:
            self._adjust_corners(self.edit_side)  # type: ignore[arg-type]

    def _editor_points(
        self, card: CardSide
    ) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
        """(automatic, current) corners; a failed detection starts near the edges."""
        corrector = self.card_processor.perspective_corrector
        automatic_points: tuple[Point, ...] | None = None
        detection = card.detection_result
        if detection is not None and len(detection.polygon_points) == 4:
            try:
                ordered = corrector.order_corners(detection.polygon_points)
            except ValueError:
                ordered = None
            if ordered is not None:
                automatic_points = tuple(
                    (float(point[0]), float(point[1])) for point in ordered
                )
        automatic = card.automatic_perspective_result
        if automatic is not None and len(automatic.refined_points) == 4:
            automatic_points = automatic.refined_points
        if automatic_points is None:
            width, height = card.original_image.size
            inset = round(min(width, height) * 0.04)
            right, bottom = float(width - 1 - inset), float(height - 1 - inset)
            automatic_points = (
                (float(inset), float(inset)),
                (right, float(inset)),
                (right, bottom),
                (float(inset), bottom),
            )
        manual = card.manual_perspective_result
        current_points = (
            manual.source_points
            if manual is not None and len(manual.source_points) == 4
            else automatic_points
        )
        return automatic_points, current_points

    def _adjust_corners(self, side: str) -> None:
        card = self._card(side)
        if card is None or self.is_detecting(side):
            return
        automatic_points, current_points = self._editor_points(card)
        dialog = CornerEditorDialog(
            card.original_image,
            automatic_points,
            self.card_processor.perspective_corrector,
            card.detection_result.confidence if card.detection_result else 0.0,
            current_points=current_points,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result is None:
            return
        if self._card(side) is not card:
            return
        card.apply_manual_correction(dialog.result)
        self._refresh()
        self.statusBar().showMessage(f"{side.title()} corners set", 5000)

    # ---------------------------------------------------------------- refresh
    def _refresh(self) -> None:
        busy = frozenset(self._pending)
        self.front_widget.set_card(self.front, busy="front" in busy)
        self.back_widget.set_card(self.back, busy="back" in busy)
        self.swap_button.setEnabled(
            not busy and (self.front is not None or self.back is not None)
        )
        self.preview_hint.setVisible(self.front is not None or self.back is not None)
        if self.edit_side is not None and self._card(self.edit_side) is None:
            self._close_editor()
        self.preview.set_sides(self.front, self.back, busy)
        if self.edit_side is not None:
            self.preview.select_side(self.edit_side, emit=False)
            self.edit_panel.set_target(
                self.edit_side,
                self._card(self.edit_side),
                self.engine.vertical_offset(self.edit_side),
                front_available=self.front is not None,
                back_available=self.back is not None,
                busy=self.edit_side in busy,
            )

    # ----------------------------------------------------------------- export
    def _export_pdf(self) -> None:
        try:
            path = self._automatic_export_path(".pdf")
        except OSError as exc:
            self._show_error("Export failed", f"Could not access Downloads: {exc}")
            return
        self._run_export("PDF", path, self.pdf_exporter.export)

    def _export_jpg(self) -> None:
        try:
            path = self._automatic_export_path(".jpg")
        except OSError as exc:
            self._show_error("Export failed", f"Could not access Downloads: {exc}")
            return
        self._run_export("JPG", path, self.jpg_exporter.export)

    @staticmethod
    def _downloads_directory() -> Path:
        standard_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        return Path(standard_path) if standard_path else Path.home() / "Downloads"

    def _automatic_export_path(self, suffix: str) -> Path:
        downloads = self._downloads_directory()
        downloads.mkdir(parents=True, exist_ok=True)
        candidate = downloads / f"card-layout{suffix}"
        sequence = 1
        while candidate.exists():
            candidate = downloads / f"card-layout ({sequence}){suffix}"
            sequence += 1
        return candidate

    def _run_export(self, kind: str, path: str | Path, exporter: object) -> None:
        exported = False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            exporter(path, self.front, self.back)  # type: ignore[operator]
            self.statusBar().showMessage(f"{kind} exported to {path}", 8000)
            exported = True
        except ExportError as exc:
            self._show_error("Export failed", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        if exported:
            output_folder = Path(path).resolve().parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_folder)))

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        if paths and len(paths) <= 2 and all(p.suffix.lower() in SUPPORTED_SUFFIXES for p in paths):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()][:2]
        self._open_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Never let a worker emit into a window that is going away.
        self._detect_pool.clear()
        self._detect_pool.waitForDone()
        super().closeEvent(event)

    def _show_error(self, title: str, message: str) -> None:
        self.statusBar().showMessage(message, 7000)
        QMessageBox.warning(self, title, message)

    # ------------------------------------------------------------------ style
    def _apply_metrics(self) -> None:
        """Size panels from polished widgets once the style sheet is applied."""
        ui = self.ui
        for widget in (self.front_widget, self.back_widget):
            widget.apply_scale(ui)
        self.preview.apply_scale(ui)
        self.edit_panel.apply_scale(ui)
        self._panel_width = self.edit_panel.preferred_width(ui)
        self.edit_panel.setMinimumWidth(self._panel_width)
        self.edit_panel.setMaximumWidth(self._panel_width + ui.px(40))
        controls = self.controls_scroll.widget()
        controls.ensurePolished()
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        left_minimum = max(ui.px(300), controls.minimumSizeHint().width() + scrollbar)
        self.controls_scroll.setMinimumWidth(left_minimum)
        self.controls_scroll.setMaximumWidth(max(left_minimum, ui.px(350)))
        self.splitter.setSizes([max(left_minimum, ui.px(325)), ui.px(850), 0])

    def _apply_style(self) -> None:
        px, pt = self.ui.px, self.ui.pt
        style = f"""
            QMainWindow, QWidget {{ background: #f4f6f9; color: #1e293b; font-family: "Segoe UI"; font-size: {pt(9)}; }}
            QLabel {{ background: transparent; }}
            QFrame#exportBar {{ background: #ffffff; border: 0; border-top: 1px solid #dce2ea; }}
            QLabel#sectionCaption, QLabel#sideTitle {{ color: #475569; font-size: {pt(8)}; font-weight: 700; letter-spacing: 1px; }}
            QLabel#fileName {{ color: #7b8798; font-size: {pt(8)}; }}
            QLabel#sizeCaption, QLabel#footerNote, QLabel#previewHint {{ color: #64748b; font-size: {pt(8)}; }}
            QLabel#statusChip {{ font-size: {pt(8)}; font-weight: 600; border-radius: {px(9)}px; padding: {px(1)}px {px(8)}px; color: #64748b; background: #eef2f6; }}
            QLabel#statusChip[tone="busy"] {{ color: #1d4fa8; background: #e8f0ff; }}
            QLabel#statusChip[tone="ok"] {{ color: #166534; background: #e7f5ec; }}
            QLabel#statusChip[tone="warn"] {{ color: #8a4b00; background: #fdf1dc; }}
            QLabel#statusChip[tone="error"] {{ color: #b42318; background: #fdeceb; }}
            QFrame#cardInput {{ background: #ffffff; border: 1px solid #dce2ea; border-radius: {px(9)}px; }}
            QLabel#sidePreview {{ background: #f7f9fc; color: #8a96a8; border: 1px dashed #c3ccd8; border-radius: {px(5)}px; }}
            QWidget#previewPanel {{ background: #e9edf3; }}
            QFrame#editPanel {{ background: #ffffff; border: 0; border-left: 1px solid #dce2ea; }}
            QScrollArea#editScroll, QScrollArea#editScroll > QWidget, QWidget#editBody {{ background: transparent; border: 0; }}
            QLabel#editTitle {{ color: #0f172a; font-size: {pt(11)}; font-weight: 700; }}
            QLabel#editSection {{ color: #475569; font-size: {pt(8)}; font-weight: 700; letter-spacing: 1px; padding-top: {px(8)}px; }}
            QLabel#editSubheading {{ color: #64748b; font-size: {pt(8)}; }}
            QLabel#positionValue {{ color: #0f172a; font-weight: 700; }}
            QPushButton {{ min-height: {px(28)}px; padding: 0 {px(10)}px; border-radius: {px(6)}px; font-weight: 600; background: #ffffff; color: #334155; border: 1px solid #cbd4e0; }}
            QPushButton:hover {{ background: #edf3fb; }}
            QPushButton#primaryButton {{ background: #245fc5; color: white; border: 1px solid #245fc5; }}
            QPushButton#primaryButton:hover {{ background: #1d4fa8; border-color: #1d4fa8; }}
            QPushButton#jpgButton {{ background: #0f766e; color: white; border: 1px solid #0f766e; }}
            QPushButton#jpgButton:hover {{ background: #0b5f58; border-color: #0b5f58; }}
            QPushButton#secondaryButton {{ background: #ffffff; color: #234c86; border: 1px solid #9fb2cc; }}
            QPushButton#secondaryButton:hover {{ background: #edf3fb; }}
            QPushButton#quietButton {{ background: transparent; color: #64748b; border: 1px solid #dde3ea; font-weight: 400; }}
            QPushButton#quietButton:hover {{ background: #eef2f6; color: #334155; }}
            QPushButton#cornersButton {{ background: #ffffff; color: #1d4fa8; border: 1px solid #245fc5; font-weight: 700; }}
            QPushButton#cornersButton:hover {{ background: #edf3fb; }}
            QPushButton#cornersButton[emphasis="strong"] {{ background: #245fc5; color: white; border: 1px solid #245fc5; }}
            QPushButton#cornersButton[emphasis="strong"]:hover {{ background: #1d4fa8; border-color: #1d4fa8; }}
            QPushButton#toggleButton, QPushButton#segmentButton {{ background: #ffffff; color: #334155; border: 1px solid #cbd4e0; padding: 0 {px(8)}px; }}
            QPushButton#toggleButton:hover, QPushButton#segmentButton:hover {{ background: #f1f5fb; }}
            QPushButton#toggleButton:checked, QPushButton#segmentButton:checked {{ background: #e8f0ff; color: #194b9b; border: 1px solid #4f7fc8; }}
            QPushButton#segmentButton[segment="first"] {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
            QPushButton#segmentButton[segment="middle"] {{ border-radius: 0; border-left: 0; }}
            QPushButton#segmentButton[segment="last"] {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: 0; }}
            QPushButton#segmentButton[segment="middle"]:checked, QPushButton#segmentButton[segment="last"]:checked {{ border-left: 1px solid #4f7fc8; }}
            QPushButton#panelCloseButton {{ min-width: 0; min-height: 0; padding: 0; background: transparent; color: #64748b; border: 0; font-size: {pt(15)}; font-weight: 400; }}
            QPushButton#panelCloseButton:hover {{ background: #eef2f7; color: #0f172a; }}
            QPushButton:disabled, QPushButton#secondaryButton:disabled, QPushButton#quietButton:disabled, QPushButton#segmentButton:disabled, QPushButton#toggleButton:disabled, QPushButton#cornersButton:disabled, QPushButton#cornersButton[emphasis="strong"]:disabled {{ color: #aab2bf; background: #f4f6f9; border-color: #e2e6ec; }}
            QScrollArea {{ background: #f4f6f9; }}
            QSplitter::handle {{ background: #dce2ea; width: 1px; }}
            QStatusBar {{ background: #ffffff; color: #64748b; border-top: 1px solid #dce2ea; font-size: {pt(8)}; }}
            QStatusBar QLabel {{ background: transparent; }}
            """
        self.setStyleSheet(style)
