# CardLayout

CardLayout is a privacy-friendly Windows desktop application for preparing the
front and back of a physical card for accurate A4 printing. Import images or PDF
pages, correct the card boundaries, preview the physical layout, and export a
print-ready PDF or 300-DPI JPG.

Everything runs locally. CardLayout does not upload documents, perform OCR, or
require an internet connection.

## Highlights

- Import JPG, JPEG, PNG, and PDF sources with **Open files…**, per-side
  **Choose**, or drag and drop.
- Open a two-page PDF as Front and Back in one step.
- Automatically detect the physical card boundary and correct perspective.
- Detect generic blue, white, grey, dark, red, low-saturation, and multicolored
  physical cards without using card color as a requirement.
- Handle low-texture card backs, weak edges, rounded corners, internal printed
  rectangles, and partial hand occlusion conservatively.
- Card detection runs in the background; each card shows a status chip.
- **Adjust corners…** on every card opens the four-corner editor directly.
- Rotate 180° or Mirror either side, and choose simple Sharpness and
  Brightness settings, independently for Front and Back.
- Move Front and Back vertically in precise 1 mm steps.
- Preview the complete A4 portrait page at the correct relative dimensions.
- Prepare and export a Front-only card without an empty Back placeholder.
- Export an A4 PDF or a 300-DPI JPG directly to Downloads.
- Run as a single standalone `CardLayout.exe` with no Python installation.
- Start maximized and scale the whole interface to the screen, from
  1366 × 768 laptops to 2560 × 1440 displays.

## Typical workflow

1. Select **Open files…** (one two-page PDF, or two files: first = Front,
   second = Back), use **Choose Front** / **Choose Back**, or drag files into
   the window.
2. Wait for each card's status chip to change from **Detecting…**.
3. If the chip says **Check corners** or **Card not found – set corners**, select
   **Adjust corners…** on that card (the button is highlighted) and drag the four
   corners onto the physical card.
4. For orientation, position, or picture changes, select **More edits…** or click
   the card on the A4 preview to open the Edit panel.
5. Review the A4 preview.
6. Select **Export PDF** or **Export JPG · 300 DPI**.

Status chips: **Empty**, **Detecting…**, **Ready**, **Check corners**, and
**Card not found – set corners**. A warning stays on the card until it is handled.

Exports are saved automatically in the Windows Downloads folder. Existing files
are never overwritten; CardLayout creates names such as `card-layout (1).pdf`.
After export, Windows Explorer opens the containing folder automatically.

## Input behavior

CardLayout supports:

- Individual `.jpg`, `.jpeg`, `.png`, and `.pdf` files for either side (a PDF
  chosen for one side uses Page 1 only)
- One two-page PDF, mapped as Page 1 → Front and Page 2 → Back
- Two files at once, mapped as first → Front and second → Back
- One-page PDFs, which leave Back empty
- PDFs with more than two pages, using only the first two pages with a notice
- Drag and drop of one PDF or up to two supported files

File dialogs remember the last folder used (first use starts in Documents).

PDF pages are rendered at high quality before entering the shared raster pipeline.
For PDF input only, border-connected white, off-white, cream, or light-gray page
whitespace can be removed before card detection. A safety margin protects rounded
corners, shadows, and weak card edges. JPG and PNG files do not receive this
PDF-specific trimming.

## Detection and correction

CardLayout uses a geometry-first OpenCV pipeline. Multiple contour, adaptive
threshold, multichannel edge, and Hough-line candidates are ranked together. It
prioritizes convex four-corner geometry, parallel/opposing edge support,
perspective plausibility, the expected outer perimeter, a softly scored card-size
ratio, and consistency with the rough detected region. Text, portraits, chips,
logos, holograms, card color, and internal rectangles are not treated as dominant
evidence.

Candidate selection is deliberately multi-stage. A larger pool of rough
candidates is retained for difficult perspective and occlusion scenes, then
contextual scoring distinguishes a coherent physical perimeter from unrelated
rectangles belonging to keyboards, monitors, mats, paper, or the surrounding
scene. Multi-signal contour boundaries are preferred over isolated Hough-line
rectangles when their footprints agree. Small printed rectangles and partial
reconstructions are prevented from outranking a credible full-card boundary.

A conservative **Complete Card Fast Path** can propose a directly observed quad
with strong outer-edge, geometry, aspect-ratio, and independent contour/line
evidence. The proposal is non-destructive: it does not change candidate scores,
override selection, or skip reconstruction. It is confirmed only when the
completed normal pipeline independently returns essentially the same area,
center, and geometry. Card-like rasters whose physical perimeter lies very near
all four image edges are handled as full-card inputs before internal rectangles
can compete.

For a card held by a hand, the detector can preserve or extrapolate the likely
outer geometry when a finger obscures an edge or corner. A lower-confidence but
credible full-card candidate is retained for review and manual adjustment instead
of being discarded. Genuinely tiny or implausible candidates still fail safely.

The top, right, bottom, and left edge confidences are tracked independently. A
weak or partly covered edge lowers confidence instead of forcing detection onto a
smaller internal rectangle. Suspicious refinements are rejected when they shrink,
expand, shift, or distort the rough card geometry without strong boundary support.

The image used for preview and export follows this safe fallback order:

1. Valid manual corner correction
2. Validated automatic perspective correction
3. Rough detected card crop
4. Original normalized image

A questionable refinement never replaces a usable rough detection. CardLayout
shows a review recommendation when it cannot confidently recover the full physical
boundary.

### Manual corners

The corner editor provides four labeled handles, connecting lines, a live
rectified preview, zoom, pan, Fit, 100%, reset-to-automatic, Done, and Cancel.
Invalid crossing, overlapping, non-convex, out-of-bounds, or near-zero-area corner
arrangements cannot be applied.

### Edit panel

**More edits…**, or clicking a card on the A4 preview, opens a docked panel on
the right. A **Front | Back** switch changes the edited side without closing it.
From top to bottom:

- **Corners**: **Adjust corners…** (same editor as on the card)
- **Orientation**: **Rotate 180°** and **Mirror** toggles; click again to undo
- **Position**: **▲ Up 1 mm** / **▼ Down 1 mm**, with the offset shown as
  Default, +2 mm, −2 mm, and so on
- **Picture**: Sharpness (Normal, Sharper) and Brightness (Normal,
  Bright + Contrast, Strong); the effect is shown live on the A4 preview
- **Reset this card**: restores automatic corners, normal orientation, normal
  picture settings, and the default position for that side

Front and Back keep independent settings. Orientation is stored as
non-destructive state after perspective correction and before picture settings.
The current dependencies do not provide reliable semantic text recognition, so
automatic orientation safely leaves uncertain images unchanged.

Opening or closing the panel only changes the UI. It does not rerun detection,
reload images, reset corners, or change physical A4 coordinates.

## A4 layout and exports

The built-in card preset is **Malaysia IC / Driving Licence – 85.6 × 54 mm**. Both sides are
centered horizontally on an A4 portrait page.

| Setting | Value |
| --- | ---: |
| A4 page | 210 × 297 mm |
| Front top position | 51.6 mm |
| Back top position | 125.6 mm |
| Gap between cards | 20 mm |
| JPG output | 2480 × 3508 px at 300 DPI |

Front and Back can each be moved up or down independently in 1 mm steps from the
Edit panel; **Reset this card** returns a side to its default position. These
adjustments change physical placement; opening the panel or resizing the window
does not.

When only Front is loaded, the configured Front position is preserved and the
rest of the page remains blank in both the preview and exported JPG/PDF. Loading
Back restores the normal two-sided layout.

For correctly sized output, print the exported PDF using **Actual Size** or
**100%**. Do not select Fit, Shrink, or Scale to Page.

## Standalone Windows app

The packaged application is one file:

```text
dist\CardLayout.exe
```

Copy only `CardLayout.exe` to the Desktop or any other folder on another Windows
computer and double-click it. The target computer does not need Python, pip,
VS Code, or separate dependencies.

The executable:

- Uses the bundled CardLayout icon in Explorer, the app window, and the taskbar
- Opens without a console window
- Starts maximized
- Bundles PySide6, OpenCV, NumPy, Pillow, PyMuPDF, and required Qt resources
- Excludes the `tests` directory
- Carries a Windows version resource (Properties › Details shows the version)

Because this is a PyInstaller one-file build, the first launch can take a little
longer while bundled files are extracted to a temporary directory. That temporary
runtime is cleaned up when the application closes.

## Responsive UI

The interface was designed for 1920 × 1080 at 125% Windows scaling. Every other
screen gets one proportional scale factor from its available area (taskbar
excluded), so spacing, panels, and buttons keep the same proportions; text sizes
come from real font metrics and never clip. On short screens the side panels
scroll vertically instead of squeezing controls.

## Run from source

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m cardlayout
```

The installed command can also launch the application:

```powershell
cardlayout
```

## Build the standalone EXE

Build on Windows with PyInstaller:

```powershell
python -m pip install -e ".[dev]" pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The completed single-file application is written to:

```text
dist\CardLayout.exe
```

The PyInstaller configuration is stored in `packaging\CardLayout.spec`. Resource
paths are resolved for both source execution and PyInstaller's temporary one-file
runtime, so the build does not depend on development-machine absolute paths.

## Tests

Run the complete test suite with:

```powershell
python -m pytest
```

The tests cover input normalization, PDF/JPG parity, PDF frame trimming, layout
geometry, exporters, detection scoring, low-texture backs, nested rectangles,
partial edge and corner occlusion, perspective refinement, collapse protection,
manual corners, orientation transforms, Front-only output, appearance corrections,
reset behavior, responsive UI, Edit panel interactions, multi-file import, and
background detection. GUI tests run without
manually opening the application.

The current suite contains **193 passing tests**. Detection regressions include
generic card colors, strong perspective, close-up and distant cards, cards held by
a hand, cluttered desks, monitor/keyboard distractors, strong internal rectangles,
low-contrast card backs, dense text, chips, portrait regions, rounded corners, and
complete cards on light or dark backgrounds. The packaged one-file Windows build
is also rebuilt after detector changes so `dist\CardLayout.exe` contains the
current pipeline.

## Privacy

- All image and PDF processing happens locally.
- No source files or document contents are uploaded.
- No OCR, face recognition, template matching, cloud service, or AI reconstruction
  is used.
- PDF pages are rendered in memory; hidden page-image files are not created.
- Detection diagnostics contain numeric geometry and confidence data, not document
  image content.

## Project structure

```text
cardlayout/
  models/       Card, detection, correction, size, and A4 layout state
  services/     Input, normalization, detection, rectification, and export
  ui/           Main window, card widgets, corner editor, and A4 preview
icon/            Application icon
packaging/       PyInstaller specification
tests/           Automated regression tests
build_windows.ps1
```

`CardSide.original_image` preserves the normalized source. Detection, automatic
perspective correction, manual correction, orientation, and appearance settings
remain separate states. `CardSide.best_image` is the single source used by the
side previews, A4 preview, PDF exporter, and JPG exporter.

## Current scope

CardLayout does not include background removal, white balance, saturation controls,
restoration, denoise, deblur, OCR, semantic automatic orientation recognition, or
AI-based image reconstruction. Appearance presets adjust existing pixels and
cannot restore missing detail.
