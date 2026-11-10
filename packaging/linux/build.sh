#!/bin/sh
# Inside the build container (packaging/build-linux.sh starts it): /src is this repository, read-only; /out receives
# the AppImage.
set -eu
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' /src/dashsync/__init__.py)
ARCH=$(uname -m)
APPIMAGE="/out/Coldshift-Dash-$VERSION-linux-$ARCH.AppImage"

echo "== Coldshift Dash $VERSION for Linux ($ARCH)"
python3.12 -m venv /tmp/venv
/tmp/venv/bin/pip install -q --upgrade -r /src/requirements.txt "pyinstaller>=6.16"
APP_VERSION="$VERSION" /tmp/venv/bin/pyinstaller --noconfirm --log-level WARN \
  --distpath /tmp/dist --workpath /tmp/work /src/packaging/coldshift-dash.spec

# started once without a screen, every page of the window on a throwaway vehicle: a build that cannot start stops here
QT_QPA_PLATFORM=offscreen DASHSYNC_CONFIG=/tmp/self-test "/tmp/dist/Coldshift Dash/Coldshift Dash" --self-test
grep "self-test ok" /tmp/self-test/log.txt

APPDIR=/tmp/AppDir
mkdir -p "$APPDIR/usr/lib"
cp -a "/tmp/dist/Coldshift Dash" "$APPDIR/usr/lib/coldshift-dash"
cp /src/packaging/linux/AppRun /src/packaging/linux/coldshift-dash.desktop "$APPDIR/"
cp /src/packaging/icons/icon-512.png "$APPDIR/coldshift-dash.png"
ln -s coldshift-dash.png "$APPDIR/.DirIcon"

rm -f "$APPIMAGE"
ARCH="$ARCH" appimagetool --no-appstream --runtime-file /opt/appimage-runtime "$APPDIR" "$APPIMAGE"
chmod 755 "$APPIMAGE"
sha256sum "$APPIMAGE"
