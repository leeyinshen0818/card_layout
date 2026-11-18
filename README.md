# CardLayout

A local Windows app that puts the front and back of an ID card or driving licence on one A4 page, ready to print at actual size.

Load photos or PDFs, and CardLayout finds each card, straightens it, and places it on the page. Everything runs on your computer. Nothing is uploaded.

## Features

- Open two photos (front and back) or one 2-page PDF with **Open files...**, or drag and drop them onto the window.
- Automatic card detection with perspective correction. If a card is not found, or needs a check, use **Adjust corners...** and drag the four corners.
- **More edits...** opens the Edit panel: Rotate 180° and Mirror, move the card up or down in 1 mm steps, Sharpness and Brightness choices, and **Reset this card**.
- Live A4 preview. Cards are placed at 85.6 × 54 mm (Malaysia IC and driving licence).
- Export **PDF** or **JPG (300 DPI)**. Files are saved to your Downloads folder.
- Layout adapts to the screen size and Windows display scaling.

Print the exported PDF at **Actual Size / 100%** so the card prints at its real size.

## Download

Get `CardLayout.exe` from the [Releases](../../releases) page and run it. No installation is needed.

The app is not code-signed, so Windows SmartScreen may show a warning the first time. Choose **More info**, then **Run anyway**. The first start takes a few seconds.

## Run from source

Requires Windows and Python 3.10 or newer.

```powershell
python -m pip install -r requirements.txt
python -m cardlayout
```

## Build the exe

```powershell
.\build_windows.ps1
```

The result is `dist\CardLayout.exe`.

## Tests

```powershell
python -m pytest -q
```

## Privacy

Do not commit real ID photos or scans to this repository. Keep test images outside the project folder.
