"""The file contract between the desktop tool and the Android app.

Everything lives in one folder on the card, <card>/coldshift.dash/, and the app reads it at start-up,
doing the work itself (scanning tags) when a piece is missing:

    <card>/coldshift.dash/Music/...                    the music, any folder layout
    <card>/coldshift.dash/library/index.json           tags, durations and cover keys for every track
    <card>/coldshift.dash/library/art/<key>.jpg        320 px square covers, shared between tracks
    <card>/coldshift.dash/maps/*.map                   Mapsforge map files (the app uses the first)
    <card>/coldshift.dash/profile/                     per-vehicle settings (reserved)

A plain <card>/Music folder is still accepted for the music, so music copied onto a card by hand works.

Recordings are the exception: Android 4.4 only lets an app write inside its own folder on the card, so
the dashcam writes to (from Android 11, with all-files access, <card>/coldshift.dash/phone/Dashcam/: see on_phone)
    <card>/Android/data/racing.coldshift.dash/files/Dashcam/
        NNNNNN_<time>[_L].mp4 + .srt + .gcsv loop clips ("_L" = locked) with a GPS subtitle file and a gyro log
        marks/mark_NNNN_<time>.json/.gpx/.mp4   marks and their lossless export
        trips/trip_<time>.csv                one point per second while recording
"""
import os

APP_DIR = "coldshift.dash"
MUSIC_DIR = APP_DIR + "/Music"
LEGACY_MUSIC_DIR = "Music"
LIBRARY_DIR = APP_DIR + "/library"
MAPS_DIR = APP_DIR + "/maps"
PROFILE_DIR = APP_DIR + "/profile"
INDEX_NAME = "index.json"
ART_DIR = "art"

PACKAGE = "racing.coldshift.dash"
# The app's own folder on a secondary card (Android 4.4 only lets an app write there), and its
# counterpart on internal storage, which the app falls back to when there is no card.
APP_DATA = "Android/data/" + PACKAGE + "/files"
DASHCAM_DIR = APP_DATA + "/Dashcam"
# From Android 11 that folder is hidden from adb, so there the app (with all-files access) keeps the same files
# in <card>/coldshift.dash/phone instead, and the constants above name where they are on Android 4.4.
PHONE_DATA = APP_DIR + "/phone"



def on_phone(target, rel):
    """`rel`, a path under APP_DATA as the constants name it, where this card has it: under coldshift.dash/phone
    when the app keeps its files there, else as it is."""
    if rel.startswith(APP_DATA) and target.exists(PHONE_DATA):
        return PHONE_DATA + rel[len(APP_DATA):]
    return rel


INDEX_VERSION = 1
AUDIO_EXT = (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav")
ART_SIZE = 320
ART_QUALITY = 86


def card_paths(card):
    """Standard locations for a card whose root folder is `card`."""
    def join(rel):
        return os.path.join(card, *rel.split("/"))
    music = join(MUSIC_DIR)
    if not os.path.isdir(music) and os.path.isdir(join(LEGACY_MUSIC_DIR)):
        music = join(LEGACY_MUSIC_DIR)
    return {
        "music": music,
        "library": join(LIBRARY_DIR),
        "maps": join(MAPS_DIR),
        "dashcam": join(DASHCAM_DIR),
    }


def mounted_cards():
    """Drives mounted on this computer that have the app's folder: a phone's card in a card reader."""
    import string
    import sys
    if sys.platform == "darwin":
        roots = [os.path.join("/Volumes", n) for n in sorted(os.listdir("/Volumes"))] if os.path.isdir("/Volumes") else []
    elif os.name == "nt":
        roots = ["%s:\\" % d for d in string.ascii_uppercase[3:]]
    else:
        user = os.environ.get("USER", "")
        roots = []
        for base in ("/media/" + user, "/run/media/" + user, "/media", "/mnt"):
            if os.path.isdir(base):
                roots += [os.path.join(base, n) for n in sorted(os.listdir(base))]
    found = []
    for r in roots:
        try:
            if os.path.isdir(os.path.join(r, APP_DIR)):
                found.append(r)
        except OSError:
            pass
    return found
