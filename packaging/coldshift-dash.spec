# PyInstaller: Coldshift Dash.app on macOS (build-mac.sh runs this; it sets CODESIGN_IDENTITY, APP_VERSION and
# ICON), the Coldshift Dash folder with Coldshift Dash.exe on Windows (build-win.ps1; it sets APP_VERSION), and
# the folder that goes in the AppImage on Linux (linux/build.sh).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))
DESKTOP = os.path.dirname(HERE)
ASSETS = os.path.join(DESKTOP, "assets")            # what the app shows of the car app's (copies of them)
VERSION = os.environ.get("APP_VERSION", "0")
MAC, WIN = sys.platform == "darwin", os.name == "nt"

a = Analysis(
    [os.path.join(HERE, "entry.py")],
    pathex=[DESKTOP],
    datas=[(os.path.join(ASSETS, "brand"), "assets/brand"),
           (os.path.join(HERE, "icons", "icon-512.png"), "assets/brand"),      # the window's icon
           (os.path.join(ASSETS, "profile"), "assets/profile"),
           (os.path.join(ASSETS, "voice", "angie"), "assets/voice/angie")],
    hiddenimports=collect_submodules("dashsync"),
    excludes=["tkinter", "unittest", "pydoc", "test"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Coldshift Dash", console=False,
          icon=os.path.join(HERE, "icons", "icon.ico") if WIN else None,
          version=os.path.join(HERE, "build", "version-info.txt") if WIN else None,
          codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
          entitlements_file=os.path.join(HERE, "entitlements.plist") if MAC else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Coldshift Dash")
if MAC:
    app = BUNDLE(
        coll,
        name="Coldshift Dash.app",
        icon=os.environ.get("ICON") or os.path.join(HERE, "icons", "icon.icns"),
        bundle_identifier="racing.coldshift.dash.desktop",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Coldshift Dash",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "The Future is Now-Now (PTY) Ltd",
        },
    )
