# Coldshift Dash desktop

The desktop companion to [Coldshift Dash](https://dash.coldshift.racing), the dashboard app for Android phones in the car. It prepares the phone's card and keeps it in step: the map for your region and its routing tiles and place search, your music, the car's look, voice packs, convoys, and backups of what was set or recorded on the phone (places, settings, the log book, the track, dashcam clips).

## Install

Download from [Releases](https://github.com/thefutureisnownow/coldshift-dash-desktop/releases):

**Mac (Apple Silicon):** the `.dmg`. Open it and drag Coldshift Dash onto Applications. It is signed and notarised, so it opens without warnings.

**Windows (64-bit):** the `.zip`. Unpack it and start `Coldshift Dash.exe`. It is not signed, so Windows SmartScreen warns the first time: More info, then Run anyway.

**Linux:** the `.AppImage` for your processor (`x86_64` for most PCs, `aarch64` for ARM). Make it executable (`chmod +x`) and start it; the x86_64 one needs glibc 2.35 or newer (Ubuntu 22.04 and later), the aarch64 one glibc 2.39 (Ubuntu 24.04 and later). For a phone on a USB cable Linux wants a udev rule: `sudo apt install android-sdk-platform-tools-common` on Debian and Ubuntu, `sudo dnf install android-tools` on Fedora, then plug the phone in again.

## Connecting the phone

The app reaches the phone over a USB cable with adb (Android's debugging bridge), or through its SD card in a card reader. The first time a phone is needed, the app offers to download adb from Google, and walks you through switching on USB debugging on the phone.

## Running from source

Python 3.11 or later:

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m dashsync.gui        # the app
    .venv/bin/python -m dashsync --help     # the same, on the command line

Tests: `.venv/bin/python -m unittest discover -s tests -t .` (one needs the car app's source: a `coldshift-dash` checkout beside this one).

## Building the app yourself

Each script puts its result in `packaging/dist/`:

    packaging/build-mac.sh        # macOS: Coldshift Dash.app in a .dmg (signed if you set CODESIGN_IDENTITY, else ad hoc)
    packaging/build-linux.sh      # Linux: an AppImage, built in Docker (ARCH=aarch64 for ARM)
    packaging\build-win.ps1       # Windows: a folder with Coldshift Dash.exe, zipped

Every build starts itself once without a screen (`--self-test`) before it is packed. For a release, the macOS build is made and signed first; publishing the release on GitHub then builds the Windows and Linux ones and attaches them (`.github/workflows/builds.yml`).

## Related

- [coldshift-dash](https://github.com/thefutureisnownow/coldshift-dash): the car app.
- [coldshift-dash-convoy](https://github.com/thefutureisnownow/coldshift-dash-convoy): the convoy relay.

## License

MIT, see [LICENSE](LICENSE); the packaged app as a whole is under the GPL, see [NOTICE](NOTICE).
