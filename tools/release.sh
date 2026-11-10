#!/bin/sh
# A release of the desktop app: the Mac app built, signed and notarised here, then stored on GitHub. Publishing
# the release starts GitHub's Windows and Linux builds, which add theirs (.github/workflows/builds.yml).
#
#   tools/release.sh            packaging/dist: the .dmg and SHA256SUMS, to try first
#   tools/release.sh --upload   ... then tags the commit v<version> and makes the GitHub Release with them
#
# The version is dashsync/__init__.py's VERSION. Signing and notarising are packaging/build-mac.sh's.
# LINUX_ARCHS="x86_64 aarch64" also builds those AppImages here, in Docker (none unless set).
set -eu
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' dashsync/__init__.py)
if [ -n "$(git status --porcelain)" ]; then
  [ "${1:-}" = "--upload" ] && { echo "the working tree has changes: commit them first, so the release is that commit"; exit 1; }
  echo "(the working tree has changes: fine for a try, not for a release)"
fi
packaging/build-mac.sh                    # first: it empties packaging/dist
for arch in ${LINUX_ARCHS:-}; do
  ARCH=$arch packaging/build-linux.sh
done
(cd packaging/dist && shasum -a 256 Coldshift-Dash-*.dmg Coldshift-Dash-*.AppImage 2>/dev/null > SHA256SUMS; cat SHA256SUMS)
if [ "${1:-}" = "--upload" ]; then
  git tag -a "v$VERSION" -m "Coldshift Dash desktop $VERSION"
  git push origin "v$VERSION"
  # (the AppImages only if LINUX_ARCHS built some: ls names none otherwise)
  gh release create "v$VERSION" packaging/dist/Coldshift-Dash-*.dmg $(ls packaging/dist/Coldshift-Dash-*.AppImage 2>/dev/null) packaging/dist/SHA256SUMS \
    --title "Coldshift Dash desktop $VERSION" --generate-notes
fi
