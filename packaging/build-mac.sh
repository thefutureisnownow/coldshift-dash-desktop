#!/bin/sh
# Coldshift Dash for macOS, built, signed and notarised here: dist/Coldshift-Dash-<version>-mac-<arch>.dmg
#
#   packaging/build-mac.sh
#
# Needs: Python 3 (PYTHON=… to choose one; the .app is for that Python's architecture), Xcode's command line tools,
# the Developer ID Application identity in the keychain (CODESIGN_IDENTITY=… for another), and, to notarise, the
# notarytool profile in the keychain (NOTARY_PROFILE=… names it).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DESKTOP=$(dirname "$HERE")
IDENTITY=${CODESIGN_IDENTITY:-"Developer ID Application: The Future is Now-Now (PTY) Ltd (SDJD9W9K58)"}
NOTARY=${NOTARY_PROFILE:-mosferatu}
PY=${PYTHON:-python3}
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$DESKTOP/dashsync/__init__.py")
ARCH=$("$PY" -c 'import platform; print(platform.machine())')
OUT="$HERE/dist"
WORK="$HERE/build"
VENV="$HERE/.venv"

echo "== Coldshift Dash $VERSION for macOS ($ARCH)"
# The identity is only a name (every signed app shows it); signing needs its private key in this keychain. Without
# it (anyone else's Mac), the app is signed ad hoc: it runs here, and elsewhere after right-click, Open.
if ! security find-identity -v -p codesigning | grep -qF "$IDENTITY"; then
  echo "no \"$IDENTITY\" in the keychain: an ad-hoc build, not notarised"
  IDENTITY="-"
fi
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade -r "$DESKTOP/requirements.txt" "pyinstaller>=6.16"

# the icon is packaging/icons/icon.icns (made from the dash logo by make_icons.py)
rm -rf "$WORK" && mkdir -p "$WORK"

# the app, every binary in it signed with the hardened runtime
rm -rf "$OUT"
CODESIGN_IDENTITY="$IDENTITY" APP_VERSION="$VERSION" ICON="$HERE/icons/icon.icns" \
  "$VENV/bin/pyinstaller" --noconfirm --log-level WARN --distpath "$OUT" --workpath "$WORK/pyinstaller" "$HERE/coldshift-dash.spec"
APP="$OUT/Coldshift Dash.app"
rm -rf "$OUT/Coldshift Dash"                      # the folder the .app was made from
codesign --verify --deep --strict "$APP"
echo "signed: $(codesign -dvv "$APP" 2>&1 | sed -n 's/^Authority=//p' | head -1)"

# the disk image: the app and a link to Applications, to drag it onto
DMG="$OUT/Coldshift-Dash-$VERSION-mac-$ARCH.dmg"
mkdir -p "$WORK/dmg"
ditto "$APP" "$WORK/dmg/Coldshift Dash.app"
ln -s /Applications "$WORK/dmg/Applications"
hdiutil create -quiet -volname "Coldshift Dash" -srcfolder "$WORK/dmg" -ov -format UDZO "$DMG"
[ "$IDENTITY" = "-" ] || codesign --sign "$IDENTITY" --timestamp "$DMG"

if [ "$IDENTITY" = "-" ]; then
  echo "NOT NOTARISED: ad-hoc build"
elif xcrun notarytool history --keychain-profile "$NOTARY" >/dev/null 2>&1; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY" --wait
  xcrun stapler staple -q "$DMG"
  spctl --assess --type open --context context:primary-signature --verbose "$DMG"
else
  echo "NOT NOTARISED: there is no notarytool profile '$NOTARY' in the keychain (see the top of this script)."
fi
echo "$DMG"
shasum -a 256 "$DMG"
