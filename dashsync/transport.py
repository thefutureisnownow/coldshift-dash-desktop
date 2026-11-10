"""Two ways to reach the card: a mounted folder (card reader) or the phone over adb.

Both expose the same small interface, so maps and recordings code does not care which is used.
Paths passed in are POSIX-style and relative to the card root.
"""
import os
import re
import shutil
import subprocess

from . import adbtool, layout


class Entry:
    def __init__(self, name, size, mtime, is_dir):
        self.name, self.size, self.mtime, self.is_dir = name, size, mtime, is_dir

    def __repr__(self):
        return "Entry(%r, %d%s)" % (self.name, self.size, ", dir" if self.is_dir else "")


class FolderTarget:
    """The card (or a copy of its layout) mounted as a folder."""
    kind = "folder"

    def __init__(self, root):
        if not os.path.isdir(root):
            raise SystemExit("not a folder: " + root)
        self.root = root
        self.label = root

    def _p(self, rel):
        return os.path.join(self.root, *rel.split("/")) if rel else self.root

    def exists(self, rel):
        return os.path.exists(self._p(rel))

    def listdir(self, rel):
        p = self._p(rel)
        if not os.path.isdir(p):
            return []
        out = []
        for n in sorted(os.listdir(p)):
            if n.startswith("."):
                continue
            st = os.stat(os.path.join(p, n))
            out.append(Entry(n, st.st_size, st.st_mtime, os.path.isdir(os.path.join(p, n))))
        return out

    def free_bytes(self):
        return shutil.disk_usage(self.root).free

    def mkdirs(self, rel):
        os.makedirs(self._p(rel), exist_ok=True)

    def pull(self, rel, local):
        os.makedirs(os.path.dirname(local), exist_ok=True)
        shutil.copyfile(self._p(rel), local)

    def push(self, local, rel):
        dest = self._p(rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(local, dest + ".part")
        os.replace(dest + ".part", dest)

    def rename(self, rel, new_rel):
        dest = self._p(new_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(self._p(rel), dest)

    def notify_synced(self, what):
        """A card in a reader: the app reloads by itself when the card goes back in."""
        return None

    def remove(self, rel):
        p = self._p(rel)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)


def parse_df_free(text, mount):
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].rstrip("/") == mount.rstrip("/"):
            m = re.match(r"([\d.]+)([KMGT]?)$", parts[3])
            if m:
                return int(float(m.group(1)) * 1024 ** " KMGT".index(m.group(2) or " "))
    return None


# toolbox on Android 4.4: "-rw-rw-r-- root sdcard_r 996370 2026-11-04 10:27 a.jpg" (no size for a folder);
# toybox from Android 6 puts the link count after the mode: "-rwxrwx--- 1 root everybody 3548444 2026-11-04 10:43 a.jpg"
_LS = re.compile(r"^([dl-])\S+\s+(?:\d+\s+)?\S+\s+\S+\s+(?:(\d+)\s+)?(\d{4}-\d\d-\d\d \d\d:\d\d) (.+)$")
_LOST = re.compile(r"^(adb|error): ", re.M)     # adb's own complaint, not the phone's commands ("ls: ...")


class AdbTarget:
    """The phone, with its SD card (or internal storage if there is no card). Which volume is the card
    differs: the G7 has it at /storage/sdcard1, the Y625 at /storage/sdcard0 (its internal storage being
    sdcard1), so it is found as the app finds it: the volume vold mounts from /dev/block/vold."""
    kind = "adb"

    def __init__(self, serial=None, adb=None, card=None):
        try:
            self.adb = adb and adbtool.require(adb) or adbtool.require()
        except adbtool.AdbMissing as e:
            raise SystemExit(str(e))
        self.serial = serial or self._only_device()
        self.card = card or self._find_card()
        self.root = self.card
        self.label = "phone %s (%s)" % (self.serial, self.card)

    def _find_card(self):
        for line in self._sh("cat /proc/mounts")[1].splitlines():
            f = line.split()
            if len(f) > 1 and f[0].startswith("/dev/block/vold/") and f[1].startswith("/mnt/media_rw/"):
                return "/storage/" + f[1][len("/mnt/media_rw/"):]
        return "/storage/emulated/0"

    def _cmd(self, *a):
        return [self.adb, "-s", self.serial] + list(a)

    def _only_device(self):
        """Never guesses between phones: with more than one attached the caller must name one."""
        devs = [d for d in adbtool.list_devices(self.adb)]
        ready = [d for d in devs if d["state"] == "device"]
        if len(ready) == 1 and len(devs) == 1:
            return ready[0]["serial"]
        if not devs:
            raise SystemExit("no phone found over adb; plug it in with USB debugging on, or use --card")
        lines = ["%d adb devices found; choose one with --serial:" % len(devs)]
        for d in devs:
            help_ = adbtool.STATE_HELP.get(d["state"], "")
            lines.append("  %-22s %-13s %s%s" % (d["serial"], d["state"], d["model"], ("  (%s)" % help_) if help_ else ""))
        raise SystemExit("\n".join(lines))

    def _sh(self, command):
        """(exit code, output) of a command on the phone. Losing the phone stops the job with a message, so
        that no answer cannot be read as an empty card or a missing folder."""
        r = subprocess.run(self._cmd("shell", command), capture_output=True, text=True, errors="replace")
        if r.returncode != 0 and _LOST.search(r.stderr or ""):
            raise SystemExit("The phone stopped answering (%s). Check its cable or Wi-Fi connection, then try again."
                             % r.stderr.strip().splitlines()[0])
        return r.returncode, r.stdout

    def _q(self, rel):
        path = self.card + ("/" + rel if rel else "")
        return "'" + path.replace("'", "'\\''") + "'"

    def _abs(self, rel):
        return self.card + ("/" + rel if rel else "")

    def exists(self, rel):
        return self._sh("ls -d %s 2>/dev/null" % self._q(rel))[1].strip() != ""

    def listdir(self, rel):
        out = []
        for line in self._sh("ls -l %s" % self._q(rel))[1].splitlines():
            m = _LS.match(line.rstrip("\r"))
            if not m or m.group(4).startswith("."):
                continue
            kind, size, when, name = m.groups()
            out.append(Entry(name, int(size or 0), 0, kind == "d"))
        return sorted(out, key=lambda e: e.name)

    def free_bytes(self):
        """Free space on the card from toolbox `df`, which prints sizes like 22.4G; None if unreadable."""
        return parse_df_free(self._sh("df %s" % self._q(""))[1], self.card)

    def mkdirs(self, rel):
        self._sh("mkdir -p %s" % self._q(rel))

    def pull(self, rel, local):
        os.makedirs(os.path.dirname(local), exist_ok=True)
        r = subprocess.run(self._cmd("pull", self._abs(rel), local), capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(local):
            raise RuntimeError("adb pull failed for %s: %s" % (rel, (r.stderr or r.stdout).strip()))

    def push(self, local, rel):
        dest = self._abs(rel)
        self.mkdirs(os.path.dirname(rel))
        r = subprocess.run(self._cmd("push", local, dest + ".part"), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("adb push failed: " + (r.stderr or r.stdout).strip())
        self._sh("mv %s %s" % (self._q(rel + ".part"), self._q(rel)))

    def remove(self, rel):
        self._sh("rm -r %s" % self._q(rel))

    def rename(self, rel, new_rel):
        self.mkdirs(new_rel.rpartition("/")[0])
        code, out = self._sh("mv %s %s" % (self._q(rel), self._q(new_rel)))
        if code != 0 or out.strip():
            raise RuntimeError("could not rename %s on the card: %s" % (rel, out.strip()))

    def notify_synced(self, what):
        """Tells the running app which parts of the card changed ("maps", "music"), so it reloads them
        instead of needing a restart. Returns the app's reply ("reloaded maps"), or None if the app is
        not running (it reads the card afresh when it starts)."""
        try:
            out = self._sh("am broadcast -a %s.SYNCED --es what %s" % (layout.PACKAGE, ",".join(what)))[1]
        except SystemExit:      # the copy is done; the app reads the card afresh when it starts
            return None
        m = re.search(r'data="([^"]*)"', out)
        return m.group(1) if m else None


def open_target(card=None, adb=False, serial=None, adb_path=None):
    if card:
        return FolderTarget(card)
    if adb or serial:
        return AdbTarget(serial, adb_path)
    raise SystemExit("choose where the card is: --card /Volumes/CARD  or  --adb [--serial ID]")


def open_sources(card=None, adb=False, serial=None, adb_path=None):
    """Everywhere the app may have written recordings: the card, and over adb also internal storage
    (the app falls back to it when no card is inserted)."""
    first = open_target(card, adb, serial, adb_path)
    if first.kind == "adb":
        return [first] + ([AdbTarget(first.serial, first.adb, "/storage/emulated/0")] if first.card != "/storage/emulated/0" else [])
    return [first]
