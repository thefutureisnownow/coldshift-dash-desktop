# Where the Linux AppImage is built (packaging/build-linux.sh), on the oldest Ubuntu the Qt packages install on: 22.04
# for x86_64, 24.04 for aarch64 (whose PySide6 wheels need its newer C library). BASE chooses; Python 3.12 comes from
# the deadsnakes archive on 22.04 and is the system's own on 24.04. The X and Wayland libraries are here so that PyInstaller finds
# them and puts them in the AppImage.
ARG BASE=ubuntu:22.04
FROM ${BASE}
ARG ARCH=x86_64
# no questions while installing: tzdata otherwise asks for a region and waits for an answer for ever
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl file binutils gpg-agent software-properties-common \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get install -y --no-install-recommends python3.12 python3.12-venv python3.12-dev \
      libegl1 libgl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libfreetype6 libxkbcommon0 libxkbcommon-x11-0 \
      libwayland-client0 libwayland-cursor0 libwayland-egl1 \
      libx11-6 libx11-xcb1 libxcb1 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
      libxcb-randr0 libxcb-render0 libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-util1 \
      libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
 && rm -rf /var/lib/apt/lists/*
# The AppImage tools, pinned by hash. appimagetool is unpacked, as a container has no FUSE to run it directly.
RUN set -eu; \
    case "$ARCH" in \
      x86_64)  TOOL=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0; RUNTIME=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d ;; \
      aarch64) TOOL=f0837e7448a0c1e4e650a93bb3e85802546e60654ef287576f46c71c126a9158; RUNTIME=00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444 ;; \
    esac; \
    cd /opt; \
    curl -fsSL -o tool.AppImage "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$ARCH.AppImage"; \
    curl -fsSL -o appimage-runtime "https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-$ARCH"; \
    echo "$TOOL  tool.AppImage" | sha256sum -c -; \
    echo "$RUNTIME  appimage-runtime" | sha256sum -c -; \
    chmod +x tool.AppImage; \
    ./tool.AppImage --appimage-extract >/dev/null; \
    mv squashfs-root appimagetool; \
    rm tool.AppImage; \
    ln -s /opt/appimagetool/AppRun /usr/local/bin/appimagetool
