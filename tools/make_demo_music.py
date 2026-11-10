"""A small demo music library for screenshots and videos, from TFINN's own games (no label's covers or songs): an
album per game, tagged (title, artist, album, track) with the game's art as the embedded cover, as the app shows it.

    DEMO_MUSIC_SRC=/path/to/sources python3 tools/make_demo_music.py [OUT]      (OUT: ../demo-vehicles/Music)

DEMO_MUSIC_SRC is the folder the albums' "dir" and "cover" below are found in; change ALBUMS for music of your own.
Needs mutagen and Pillow (this repository's .venv has both).
"""
import io
import os
import shutil
import sys

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK
from mutagen.oggvorbis import OggVorbis
from PIL import Image

EXT = os.environ.get("DEMO_MUSIC_SRC") or sys.exit("set DEMO_MUSIC_SRC to the folder the albums are in")
DEV = os.path.join(EXT, "Development")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALBUMS = [
    {"album": "Mosferatu (Original Soundtrack)", "folder": "Mosferatu",
     "dir": DEV + "/mosferatu-website/soundtrack/releases/v003/Mosferatu - Original Soundtrack - FLAC",
     "tracks": ["01 - title.flac", "04 - social-floor.flac", "07 - crypt.flac", "10 - lord-awakening.flac",
                "14 - party-memory.flac", "16 - victory.flac"], "cover": None},          # tagged, with its cover
    {"album": "Coldshift Racing: Lagoon FM", "folder": "Coldshift Racing - Lagoon FM",
     "dir": EXT + "/CR2/packs/coldshift.radio/radio/lagoon_fm",
     "tracks": ["lagoon_lights.mp3", "boardwalk_bounce.mp3", "leisure_isle.mp3", "low_tide.mp3", "oyster_catcher.mp3",
                "heads_and_tails.mp3"], "cover": EXT + "/CR2/packs/coldshift.radio/badges/lagoon_fm.png"},
    {"album": "Coldshift Racing: Road Trip Radio", "folder": "Coldshift Racing - Road Trip Radio",
     "dir": EXT + "/CR2/packs/coldshift.radio/radio/road_trip_radio",
     "tracks": ["full_tank.mp3", "open_window.mp3", "mile_markers.mp3", "passing_lane.mp3", "slipstream.mp3",
                "through_the_tollgate.mp3"], "cover": EXT + "/CR2/packs/coldshift.radio/badges/road_trip_radio.png"},
    {"album": "SNOEK'EM (Original Soundtrack)", "folder": "Snoek'em",
     "dir": DEV + "/Snoeken/assets/audio/music",
     "tracks": ["prologue.mp3", "knysna.mp3", "agulhas.mp3", "muizenberg.mp3", "golden_mile.mp3", "wild_coast.mp3"],
     "cover": DEV + "/snoekem-website/public/assets/game/icon-512.png"},
    {"album": "Budget Cuts (Original Soundtrack)", "folder": "Budget Cuts",
     "dir": EXT + "/BudgetCuts/assets/audio/music",
     "tracks": ["hub.ogg", "approach.ogg", "dungeon.ogg", "kazoo.ogg", "boss.ogg", "victory.ogg"],
     "cover": EXT + "/BudgetCuts/assets/brand/icon_1024_dark.png"},
    {"album": "Bludgeoning (Original Soundtrack)", "folder": "Bludgeoning",
     "dir": DEV + "/bludgeoning-website/public/assets/media",
     "tracks": ["march.mp3", "fanfare.mp3"], "cover": DEV + "/bludgeoning-website/public/assets/media/icon-512.png"},
]


def title(name):
    stem = os.path.splitext(name)[0]
    return stem.replace("_", " ").replace("-", " ").title().replace("'S", "'s")


def cover_jpeg(path):
    im = Image.open(path).convert("RGB")
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2, (im.width + side) // 2, (im.height + side) // 2))
    im = im.resize((500, 500), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "demo-vehicles", "Music")
    shutil.rmtree(out, ignore_errors=True)
    total = 0
    for a in ALBUMS:
        folder = os.path.join(out, a["folder"])
        os.makedirs(folder)
        art = cover_jpeg(a["cover"]) if a["cover"] else None
        for n, name in enumerate(a["tracks"], 1):
            src = os.path.join(a["dir"], name)
            ext = os.path.splitext(name)[1]
            t = title(name.split(" - ", 1)[-1]) if a["cover"] is None else title(name)
            dest = os.path.join(folder, "%02d - %s%s" % (n, t, ext))
            shutil.copy(src, dest)
            total += os.path.getsize(dest)
            if ext == ".flac":
                f = FLAC(dest)
                f["title"], f["album"], f["artist"], f["tracknumber"] = t, a["album"], "TFINN", str(n)
                f.save()
            elif ext == ".mp3":
                tags = ID3()
                tags.add(TIT2(encoding=3, text=t))
                tags.add(TPE1(encoding=3, text="TFINN"))
                tags.add(TALB(encoding=3, text=a["album"]))
                tags.add(TRCK(encoding=3, text=str(n)))
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=art))
                tags.save(dest)
            else:
                import base64
                f = OggVorbis(dest)
                f["title"], f["album"], f["artist"], f["tracknumber"] = t, a["album"], "TFINN", str(n)
                pic = Picture()
                pic.type, pic.mime, pic.desc, pic.data = 3, "image/jpeg", "Cover", art
                f["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
                f.save()
        print("%-36s %d tracks" % (a["album"], len(a["tracks"])))
    print("%.0f MB in %s" % (total / 1e6, out))


if __name__ == "__main__":
    main()
