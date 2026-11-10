"""Voice packs for navigation prompts: kept in the workspace, edited a line at a time, put on the card.

The app speaks a prompt by playing lines one after another: "In two hundred metres," + "Turn left." +
"Then" + "Turn right." BRouter's routes carry no street names, so these LINES are all it needs.

A pack is a folder:
    voice.json    {"version": 1, "id": "angie", "name": "Angie", "lines": {"turn_left": "turn_left.mp3", ...}}
    <line>.mp3    one recording per line (MP3, or WAV, Ogg or M4A: the app plays what Android 4.4 plays)

A pack may be unfinished: the app skips the lines it lacks. The app has Angie built in
(assets/voice/angie/, a copy of the car app's, shown here as a reference) and also finds packs at
<card>/coldshift.dash/voice/<id>/; the voice is chosen in its Settings. Packs live in
<workspace>/voice/<id>/; `sync` makes the card hold exactly those. A pack is shared as a .zip
(`export`, `install`).

Recording lines with ElevenLabs is ours only: tools/make_voice_pack.py, not part of this tool.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile

from . import layout, paths

VOICE_DIR = layout.APP_DIR + "/voice"
FORMATS = (".mp3", ".wav", ".ogg", ".m4a")
MAX_SECONDS = 8
MAX_BYTES = 2 * 1024 * 1024

# key -> what to say. The app (Prompter.java, MapsPage.java, and Cues.java for the warnings) asks for these keys.
LINES = {
    "turn_left": "Turn left.",
    "turn_right": "Turn right.",
    "turn_slight_left": "Turn slightly left.",
    "turn_slight_right": "Turn slightly right.",
    "turn_sharp_left": "Turn sharp left.",
    "turn_sharp_right": "Turn sharp right.",
    "keep_left": "Keep left.",
    "keep_right": "Keep right.",
    "exit_left": "Take the exit on the left.",
    "exit_right": "Take the exit on the right.",
    "u_turn": "Make a U-turn.",
    "straight": "Continue straight.",
    "roundabout": "Enter the roundabout.",
    "roundabout_1": "At the roundabout, take the first exit.",
    "roundabout_2": "At the roundabout, take the second exit.",
    "roundabout_3": "At the roundabout, take the third exit.",
    "roundabout_4": "At the roundabout, take the fourth exit.",
    "roundabout_5": "At the roundabout, take the fifth exit.",
    "roundabout_6": "At the roundabout, take the sixth exit.",
    "roundabout_7": "At the roundabout, take the seventh exit.",
    "roundabout_8": "At the roundabout, take the eighth exit.",
    "destination": "You will reach your destination.",
    "in_2km": "In two kilometres,",
    "in_1km": "In one kilometre,",
    "in_500m": "In five hundred metres,",
    "in_300m": "In three hundred metres,",
    "in_200m": "In two hundred metres,",
    "in_100m": "In one hundred metres,",
    "then": "Then",
    "follow_5km": "Follow the road for five kilometres.",
    "follow_10km": "Follow the road for ten kilometres.",
    "follow_20km": "Follow the road for twenty kilometres.",
    "follow_50km": "Follow the road for fifty kilometres.",
    "arrived": "You have arrived at your destination.",
    "off_route": "Off route. Finding a new route.",
    "no_route": "No route found.",
    "gps_lost": "GPS signal lost.",
    "gps_back": "GPS signal is back.",
    # warnings, said after the app's warning chime (Cues.java, UI.java)
    "rec_stopped_storage": "Recording stopped. The storage is full.",
    "rec_stopped_error": "Recording stopped. There is a problem with the camera.",
    "rec_stopped_battery": "Recording stopped. The battery is low.",
    "check_engine": "The check engine light is on.",
    "engine_hot": "The engine is running hot.",
    "phone_hot": "The phone is getting too hot.",
    "fuel_stop": "Did you fill up? You can log it in the log book.",
}

# how the lines are shown for recording: (title, advice, keys)
GROUPS = [
    ("Turns", "Said on their own at the turn, or after a distance (“In two hundred metres, turn left”).",
     ["turn_left", "turn_right", "turn_slight_left", "turn_slight_right", "turn_sharp_left", "turn_sharp_right",
      "keep_left", "keep_right", "exit_left", "exit_right", "u_turn", "straight", "destination"]),
    ("Roundabouts", "As the turns.", ["roundabout"] + ["roundabout_%d" % i for i in range(1, 9)]),
    ("Distances", "Always followed by a turn: say them as the start of a sentence, voice up at the comma.",
     ["in_2km", "in_1km", "in_500m", "in_300m", "in_200m", "in_100m"]),
    ("Joining", "Between two turns: “Turn left. Then turn right.”", ["then"]),
    ("Long roads", "Said after a turn when the next is far away.", ["follow_5km", "follow_10km", "follow_20km", "follow_50km"]),
    ("Arrival and status", "Said on their own.", ["arrived", "off_route", "no_route", "gps_lost", "gps_back"]),
    ("Warnings", "Said after the warning chime. Without them the chime sounds alone.",
     ["rec_stopped_storage", "rec_stopped_error", "rec_stopped_battery", "check_engine", "engine_hot", "phone_hot",
      "fuel_stop"]),
]

# the sample the window and the app's Test button play
SAMPLE = ["in_200m", "turn_left", "then", "turn_right"]


def pack_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "voice"


def builtin_dir():
    """The app's built-in pack (Angie), when running from the repository; None otherwise."""
    d = paths.app_assets("voice", "angie")
    return d if os.path.exists(os.path.join(d, "voice.json")) else None


def read_pack(folder):
    """A pack's voice.json, checked: an id usable as a folder name, and every line it lists there."""
    with open(os.path.join(folder, "voice.json"), encoding="utf-8") as f:
        meta = json.load(f)
    if not isinstance(meta.get("lines"), dict) or not meta.get("id") or not meta.get("name"):
        raise ValueError("%s is not a voice pack" % folder)
    if meta["id"] != pack_id(meta["id"]):
        raise ValueError("%s has an id the app cannot use as a folder name: %r" % (meta["name"], meta["id"]))
    missing = [k for k, v in meta["lines"].items() if not os.path.exists(os.path.join(folder, v))]
    if missing:
        raise ValueError("%s is missing the files for: %s" % (meta["name"], ", ".join(missing)))
    return meta


def _write(folder, meta):
    tmp = os.path.join(folder, "voice.json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    os.replace(tmp, os.path.join(folder, "voice.json"))


def recorded(meta):
    """(lines recorded, lines the app asks for)."""
    return sum(1 for k in LINES if k in meta["lines"]), len(LINES)


def packs_dir(workspace):
    return os.path.join(workspace, "voice")


def packs(workspace):
    """[(folder, voice.json)] for the packs in the workspace."""
    root = packs_dir(workspace)
    out = []
    for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = os.path.join(root, name)
        if os.path.exists(os.path.join(folder, "voice.json")):
            out.append((folder, read_pack(folder)))
    return out


def _free_id(workspace, name):
    base = pack_id(name)
    pid, n = base, 2
    while os.path.exists(os.path.join(packs_dir(workspace), pid)) or pid == "angie" and builtin_dir():
        pid, n = "%s-%d" % (base, n), n + 1
    return pid


def create(workspace, name, copy_from=None):
    """A new pack, empty or with copy_from's recordings. Returns its folder. Its id stays fixed, so a
    rename does not leave an old copy on the card; it never takes the built-in pack's id."""
    name = name.strip()
    if not name:
        raise ValueError("give the voice a name")
    pid = _free_id(workspace, name)
    folder = os.path.join(packs_dir(workspace), pid)
    if copy_from:
        src = read_pack(copy_from)
        shutil.copytree(copy_from, folder)
        lines = src["lines"]
    else:
        os.makedirs(folder)
        lines = {}
    _write(folder, {"version": 1, "id": pid, "name": name, "lines": lines})
    return folder


def rename(folder, name):
    meta = read_pack(folder)
    if not name.strip():
        raise ValueError("give the voice a name")
    meta["name"] = name.strip()
    _write(folder, meta)


def delete(folder):
    read_pack(folder)                        # only ever a pack folder
    shutil.rmtree(folder)


def duration(path):
    """Seconds of audio in a file, or None if it is not audio this tool can read."""
    try:
        import mutagen
        f = mutagen.File(path)
        return float(f.info.length) if f is not None and f.info.length else None
    except Exception:
        return None


def check_recording(path):
    """Seconds, if the file can be a line; raises ValueError saying why not."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMATS:
        raise ValueError("use an MP3 (or WAV, Ogg or M4A) file")
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("%s is over %d MB; a line is a few seconds" % (os.path.basename(path), MAX_BYTES // 1048576))
    secs = duration(path)
    if secs is None:
        raise ValueError("%s is not an audio file this tool can read" % os.path.basename(path))
    if secs > MAX_SECONDS:
        raise ValueError("%s is %.0f seconds long; a line should be a few seconds" % (os.path.basename(path), secs))
    return secs


def set_line(folder, key, src):
    """Puts a recording in the pack for a line (replacing the old one). Returns its length in seconds."""
    if key not in LINES:
        raise ValueError("the app has no line called %s" % key)
    secs = check_recording(src)
    meta = read_pack(folder)
    name = key + os.path.splitext(src)[1].lower()
    tmp = os.path.join(folder, name + ".part")
    shutil.copyfile(src, tmp)
    old = meta["lines"].get(key)
    os.replace(tmp, os.path.join(folder, name))
    if old and old != name and os.path.exists(os.path.join(folder, old)):
        os.remove(os.path.join(folder, old))
    meta["lines"][key] = name
    _write(folder, meta)
    return secs


def remove_line(folder, key):
    meta = read_pack(folder)
    old = meta["lines"].pop(key, None)
    _write(folder, meta)
    if old and os.path.exists(os.path.join(folder, old)):
        os.remove(os.path.join(folder, old))


def export(folder, zip_path):
    """The pack as a .zip someone else can install."""
    meta = read_pack(folder)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        z.write(os.path.join(folder, "voice.json"), meta["id"] + "/voice.json")
        for f in sorted(set(meta["lines"].values())):
            z.write(os.path.join(folder, f), meta["id"] + "/" + f)
    return zip_path


def install(src, workspace):
    """Adds a shared pack (its folder or a .zip of it) to the workspace, replacing one with the same id.
    Returns its voice.json."""
    tmp = tempfile.mkdtemp()
    try:
        if zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as z:
                for n in z.namelist():
                    if n.startswith("/") or ".." in n.split("/"):
                        raise ValueError("%s has a file outside the pack: %s" % (src, n))
                z.extractall(tmp)
            found = [d for d, _, fs in os.walk(tmp) if "voice.json" in fs]
            if len(found) != 1:
                raise ValueError("%s should hold one voice pack (one voice.json)" % src)
            folder = found[0]
        else:
            folder = src
        meta = read_pack(folder)
        dest = os.path.join(packs_dir(workspace), meta["id"])
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.makedirs(packs_dir(workspace), exist_ok=True)
        shutil.copytree(folder, dest)
        return meta
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sync(target, workspace, dry_run=False):
    """Makes <card>/coldshift.dash/voice/ hold exactly the vehicle's packs (copying files whose size
    differs) and tells the app. Returns {"packs", "copied", "removed", "app"}; with dry_run only counts
    what it would change ("copied": files, "removed": packs)."""
    want = packs(workspace)
    out = {"packs": [m["name"] for _, m in want], "copied": 0, "removed": 0, "app": None}
    on_card = {e.name for e in target.listdir(VOICE_DIR) if e.is_dir}
    for folder, meta in want:
        rel = VOICE_DIR + "/" + meta["id"]
        have = {e.name: e.size for e in target.listdir(rel)} if meta["id"] in on_card else {}
        files = sorted(set(meta["lines"].values()))
        for f in files:                        # voice.json last, so the app never sees a half-copied pack
            if have.get(f) != os.path.getsize(os.path.join(folder, f)):
                if not dry_run:
                    target.push(os.path.join(folder, f), rel + "/" + f)
                out["copied"] += 1
        if have.get("voice.json") != os.path.getsize(os.path.join(folder, "voice.json")):
            if not dry_run:
                target.push(os.path.join(folder, "voice.json"), rel + "/voice.json")
            out["copied"] += 1
        for extra in set(have) - set(files) - {"voice.json"}:
            if not dry_run:
                target.remove(rel + "/" + extra)
            out["copied"] += 1
    keep = {m["id"] for _, m in want}
    for name in on_card - keep:
        if not dry_run:
            target.remove(VOICE_DIR + "/" + name)
        out["removed"] += 1
    if (out["copied"] or out["removed"]) and not dry_run:
        out["app"] = target.notify_synced(["voice"])
    return out
