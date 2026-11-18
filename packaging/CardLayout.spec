import re
from pathlib import Path

project_root = Path(SPECPATH).parent
icon_file = project_root / "icon" / "cardlayout_icon.ico"
version_file = project_root / "packaging" / "version_info.txt"

# The exe version resource must match the package version.
_package_version = re.search(
    r'__version__ = "([^"]+)"',
    (project_root / "cardlayout" / "__init__.py").read_text(encoding="utf-8"),
).group(1)
if f"'FileVersion', '{_package_version}.0'" not in version_file.read_text(encoding="utf-8"):
    raise SystemExit(f"packaging/version_info.txt does not match version {_package_version}")

# Standard PyInstaller hooks and static import analysis provide the PySide6,
# OpenCV, NumPy, Pillow, and PyMuPDF binaries/plugins used by CardLayout. Do not
# collect all PyMuPDF submodules: its unrelated command-line tools pull in a
# large scientific/notebook stack that the desktop application never uses.

a = Analysis(
    [str(project_root / "cardlayout" / "__main__.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(icon_file), "icon"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tests",
        "testing",
        # Optional PyMuPDF table/notebook integrations are not used by
        # CardLayout and otherwise pull hundreds of megabytes into the build.
        "pandas",
        "scipy",
        "matplotlib",
        "IPython",
        "jupyter",
        "jupyter_client",
        "nbformat",
        "notebook",
        "traitlets",
        "zmq",
        "psutil",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CardLayout",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file),
    version=str(version_file),
)
