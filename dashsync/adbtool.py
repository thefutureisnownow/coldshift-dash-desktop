"""Find, install and use adb (Android Debug Bridge).

adb is how the tool reaches the phone: over the USB cable, or over Wi-Fi once switched on. It is
not part of this project and not bundled. `status()` says whether it is available and where; if
not, `setup()` downloads Google's standalone platform-tools (no Android SDK needed), or the user
can point the tool at an existing copy with `set_path()`.

Safety: `list_devices()` uses `adb devices -l`, which asks the adb server and never talks to a
phone. Nothing else touches a device until the caller passes that device's serial, so other phones
plugged into the same computer (a work phone, say) are listed but left alone.
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from . import layout, paths

NAME = "adb.exe" if os.name == "nt" else "adb"
FEED = "https://dl.google.com/android/repository/repository2-3.xml"
DL = "https://dl.google.com/android/repository/"
LICENCE_URL = "https://developer.android.com/studio/terms"
HOST = {"darwin": "macosx", "win32": "windows"}.get(sys.platform, "linux")


class AdbMissing(Exception):
    """adb is not available; the message says what to do."""


def probe(path, timeout=8):
    """Version string if `path` is a working adb, else None."""
    try:
        r = subprocess.run([path, "version"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Android Debug Bridge version ([\d.]+)", r.stdout or "")
    if r.returncode != 0 or not m:
        return None
    v = re.search(r"Version (\S+)", r.stdout)
    return (v.group(1) if v else m.group(1))


def _sdk_roots():
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    roots += [os.path.expanduser("~/Library/Android/sdk"), os.path.expanduser("~/Android/Sdk"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")]
    return [r for r in roots if r]


def candidates(explicit=None):
    """(source, path) in the order they are tried."""
    if explicit:
        yield "given on the command line", _as_exe(explicit)
    cfg = paths.load_config().get("adb")
    if cfg:
        yield "chosen in settings", cfg
    if os.environ.get("ADB"):
        yield "ADB environment variable", os.environ["ADB"]
    yield "downloaded by this tool", os.path.join(paths.tools_dir(), "platform-tools", NAME)
    found = shutil.which("adb")
    if found:
        yield "on your PATH", found
    for root in _sdk_roots():
        yield "Android SDK", os.path.join(root, "platform-tools", NAME)


def _as_exe(path):
    path = os.path.expanduser(path)
    return os.path.join(path, NAME) if os.path.isdir(path) else path


def find_adb(explicit=None):
    """(path, source, version) of the first working adb, or None."""
    seen = set()
    for source, path in candidates(explicit):
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        v = probe(path)
        if v:
            return path, source, v
    return None


def install_hint():
    own = "Press 'Download adb' (or run: python -m dashsync adb setup --accept-licence) and the tool fetches Google's standalone copy."
    if sys.platform == "darwin":
        other = "Or install it yourself, for example with Homebrew: brew install --cask android-platform-tools ."
    elif os.name == "nt":
        other = "Or install it yourself, for example: winget install Google.PlatformTools . Windows also needs your phone's USB driver."
    else:
        other = "Or install it with your package manager (on Debian and Ubuntu the package is called adb) and add yourself to the plugdev group."
    return own + " " + other + " Already have it? Use 'Choose adb path' and pick its folder."


def status(explicit=None):
    """What the settings page shows: whether adb works, where it is, and what to do if not."""
    f = find_adb(explicit)
    if f:
        return {"found": True, "path": f[0], "source": f[1], "version": f[2], "hint": ""}
    return {"found": False, "path": "", "source": "", "version": "", "hint": install_hint()}


def require(explicit=None):
    f = find_adb(explicit)
    if not f:
        raise AdbMissing("adb was not found. " + install_hint())
    return f[0]


def set_path(path):
    """Remember a user-chosen adb (a file, or the folder containing it). Raises ValueError if it is not adb."""
    exe = _as_exe(path)
    v = probe(exe) if os.path.isfile(exe) else None
    if not v:
        raise ValueError("%s is not a working adb" % exe)
    cfg = paths.load_config()
    cfg["adb"] = exe
    paths.save_config(cfg)
    return exe, v


def forget_path():
    cfg = paths.load_config()
    cfg.pop("adb", None)
    paths.save_config(cfg)


# ---- download ----

def _feed_entry():
    with urllib.request.urlopen(FEED, timeout=60) as r:
        root = ET.fromstring(r.read())
    for p in root.iter("remotePackage"):
        if p.get("path") != "platform-tools":
            continue
        rev = p.find("revision")
        ver = ".".join(rev.findtext(k) or "0" for k in ("major", "minor", "micro"))
        for a in p.find("archives"):
            if a.findtext("host-os") == HOST:
                c = a.find("complete")
                return {"version": ver, "url": DL + c.findtext("url"), "size": int(c.findtext("size")),
                        "sha1": c.findtext("checksum").strip().lower()}
    raise RuntimeError("Google's feed has no platform-tools for " + HOST)


def setup(accept_licence=False, progress=None):
    """Downloads and installs platform-tools for this computer into the tool's own folder.

    The Android SDK licence (LICENCE_URL) governs the download, so the caller must pass
    accept_licence=True after showing it to the user. Returns (path to adb, version).
    """
    if not accept_licence:
        raise PermissionError("the Android SDK licence (%s) must be accepted first" % LICENCE_URL)
    e = _feed_entry()
    tools = paths.tools_dir()
    zpath = os.path.join(tools, "platform-tools-download.zip")
    sha, done = hashlib.sha1(), 0
    with urllib.request.urlopen(e["url"], timeout=60) as r, open(zpath, "wb") as out:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, e["size"])
    if sha.hexdigest() != e["sha1"]:
        os.remove(zpath)
        raise RuntimeError("the download is corrupt (checksum mismatch); nothing was installed")
    target = os.path.join(tools, "platform-tools")
    stage = os.path.join(tools, "platform-tools.new")
    unpack = os.path.join(tools, "platform-tools.unpack")
    for d in (stage, unpack):
        shutil.rmtree(d, ignore_errors=True)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(unpack)
        for zi in z.infolist():
            mode = (zi.external_attr >> 16) & 0o777
            if mode and not zi.is_dir():      # zipfile drops the executable bits
                os.chmod(os.path.join(unpack, *zi.filename.split("/")), mode)
    os.replace(os.path.join(unpack, "platform-tools"), stage)
    shutil.rmtree(unpack, ignore_errors=True)
    exe = os.path.join(stage, NAME)
    if os.name != "nt":
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if not probe(exe):
        shutil.rmtree(stage, ignore_errors=True)
        os.remove(zpath)
        raise RuntimeError("the downloaded adb does not run on this computer")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(stage, target)
    os.remove(zpath)
    exe = os.path.join(target, NAME)
    return exe, probe(exe)


# ---- devices ----

def _run(adb, *args, timeout=30):
    return subprocess.run([adb] + list(args), capture_output=True, text=True, errors="replace", timeout=timeout)


def list_devices(adb):
    """Devices known to the adb server. Does not contact any phone."""
    out = _run(adb, "devices", "-l").stdout
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        devs.append({"serial": parts[0], "state": parts[1], "model": info.get("model", "").replace("_", " "),
                     "product": info.get("product", ""), "wifi": ":" in parts[0] and "." in parts[0]})
    return devs


STATE_HELP = {
    "unauthorized": "tap 'Allow USB debugging' on the phone",
    "offline": "unplug and replug the cable, or toggle USB debugging",
    "device": "",
}


def app_status(adb, serial, package=layout.PACKAGE):
    """Is the mobile app on this phone, which version, and does it have a recordings folder.
    Only call this for a device the user has chosen."""
    def sh(cmd):
        return _run(adb, "-s", serial, "shell", cmd).stdout
    path = sh("pm path %s" % package).strip()
    if not path.startswith("package:"):
        return {"installed": False, "version": "", "version_code": "", "android": sh("getprop ro.build.version.release").strip(),
                "model": sh("getprop ro.product.model").strip()}
    dump = sh("dumpsys package %s" % package)
    ver = re.search(r"versionName=(\S+)", dump)
    code = re.search(r"versionCode=(\d+)", dump)
    return {"installed": True, "version": ver.group(1) if ver else "", "version_code": code.group(1) if code else "",
            "android": sh("getprop ro.build.version.release").strip(), "model": sh("getprop ro.product.model").strip(),
            "has_recordings": sh("ls -d /storage/*/%s /storage/emulated/0/%s /storage/*/%s/Dashcam 2>/dev/null"
                                 % (layout.DASHCAM_DIR, layout.DASHCAM_DIR, layout.PHONE_DATA)).strip() != ""}


def install_app(adb, serial, apk):
    """Installs or updates the mobile app, keeping its data."""
    r = _run(adb, "-s", serial, "install", "-r", apk, timeout=300)
    out = (r.stdout + r.stderr).strip()
    if "Success" not in out:
        raise RuntimeError("install failed: " + out.splitlines()[-1] if out else "install failed")
    return True


# ---- Wi-Fi ----

def phone_wifi_ip(adb, serial):
    out = _run(adb, "-s", serial, "shell", "netcfg").stdout
    m = re.search(r"^wlan0\s+UP\s+(\d+\.\d+\.\d+\.\d+)/", out, re.M)
    if m:
        return m.group(1)
    out = _run(adb, "-s", serial, "shell", "ip -f inet addr show wlan0").stdout
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else None


def wifi_enable(adb, serial, port=5555):
    """Switch a USB-connected phone to adb over Wi-Fi. Returns the new serial, "ip:port".
    The phone and computer must be on the same network. Resets whenever the phone reboots."""
    ip = phone_wifi_ip(adb, serial)
    if not ip:
        raise RuntimeError("the phone is not connected to Wi-Fi")
    _run(adb, "-s", serial, "tcpip", str(port))
    import time
    time.sleep(2.5)
    target = "%s:%d" % (ip, port)
    out = _run(adb, "connect", target).stdout
    if "connected" not in out:
        raise RuntimeError("could not connect to %s: %s" % (target, out.strip()))
    return target


def wifi_disable(adb, wifi_serial, usb_serial=None):
    """Close the network port again. Needs the cable to put the phone back in USB mode."""
    _run(adb, "disconnect", wifi_serial)
    if usb_serial:
        _run(adb, "-s", usb_serial, "usb")
