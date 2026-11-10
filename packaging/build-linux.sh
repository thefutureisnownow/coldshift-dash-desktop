#!/bin/sh
# Coldshift Dash for Linux, built in Docker on any machine that has it: dist/Coldshift-Dash-<version>-linux-<arch>.AppImage
# (GitHub runs this for a release, .github/workflows/builds.yml; it works the same on a Mac or PC with Docker.)
#
#   packaging/build-linux.sh                x86_64
#   ARCH=aarch64 packaging/build-linux.sh   arm64
#
# PyInstaller only packages what's installed where it runs, so this runs in Ubuntu 22.04. Its C library sets the oldest
# Linux the AppImage starts on (glibc 2.35), and it's the oldest the Qt packages install on (PySide6 needs glibc 2.34).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DESKTOP=$(dirname "$HERE")
ARCH=${ARCH:-x86_64}
case "$ARCH" in
  x86_64) PLATFORM=linux/amd64 ;;
  aarch64) PLATFORM=linux/arm64 ;;
  *) echo "ARCH is x86_64 or aarch64"; exit 2 ;;
esac
IMAGE=coldshift-dash-linux-build:$ARCH
mkdir -p "$HERE/dist"
docker build --quiet --platform "$PLATFORM" --build-arg ARCH="$ARCH" -t "$IMAGE" "$HERE/linux" >/dev/null
docker run --rm --platform "$PLATFORM" -v "$DESKTOP:/src:ro" -v "$HERE/dist:/out" "$IMAGE" /src/packaging/linux/build.sh
