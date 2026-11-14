"""Copy from phone: this computer's copy of the vehicle replaced with what the phone has.

A vehicle's look, voices, map and music normally go from this computer to the phone. `pull` goes the
other way, for a new install or whenever the phone is the one to keep: the phone wins, and this
computer ends up holding what the phone holds.

    look     <card>/coldshift.dash/profile/          -> <vehicle>/profile/
    voices   <card>/coldshift.dash/voice/             -> <vehicle>/voice/
    map      <card>/coldshift.dash/maps/*.map         -> the map cache, and its region becomes the vehicle's
    music    <card>/coldshift.dash/Music/ and library/ -> <vehicle>/coldshift.dash/Music/ and library/

New and different files are copied; files this computer has that the phone does not are taken away. What
is replaced or taken away is moved, not deleted, into a folder beside it named <folder>.previous
(profile.previous, voice.previous, Music.previous, ...), which holds only the latest pull's. Songs this
computer keeps under other names (the phone's copies have card names, library.card_names) count as the
same song. Nothing on the phone changes.

Places, settings, the log book and the track come with every sync (backup.backup), and recordings with
the Recordings page. Routing tiles and the place search are not copied: they are made for the region,
and the next sync fetches them as usual.
"""
import os
import shutil
import unicodedata

from . import layout, maps, mirror, paths, profile, voice
from .library import card_names

# the parts in the order `pull` copies them, as `step` names them
STEPS = ("look from the phone", "voices from the phone", "map from the phone", "music from the phone")
PARTS = ("look", "voices", "map", "music")
SPARE = 512 * 1024 * 1024           # bytes left free on this computer's disk


def _nfc(s):
    return unicodedata.normalize("NFC", s)


def _local_files(folder):
    return mirror._local_files(folder) if os.path.isdir(folder) else {}


def _remove_empty(folder):
    """Removes the folders below `folder` that are left empty, deepest first."""
    for d, subs, files in os.walk(folder, topdown=False):
        if d != folder and not os.listdir(d):
            os.rmdir(d)


def _mirror(target, remote, local, accept=None, aliases=None, prune=True, dry_run=False, progress=None):
    """Makes `local` hold what the card has under `remote` (the phone wins): copies the card's files that
    are missing or of another size here, and with `prune` takes away files the card does not have.
    Replaced and taken-away files are moved into <local>.previous, emptied first. `accept(sub)` limits the
    card's files; `aliases` maps a card name to this computer's name for the same file. Returns
    {"present", "copy", "bytes", "replaced", "removed"}."""
    out = {"present": target.exists(remote), "copy": 0, "bytes": 0, "replaced": 0, "removed": 0}
    card = {_nfc(sub): size for sub, size in mirror.walk(target, remote, accept)} if out["present"] else {}
    aliases = aliases or {}

    def here(sub):
        return aliases.get(sub, sub)

    mine = _local_files(local)
    copy = [sub for sub, size in card.items() if mine.get(here(sub)) != size]
    replace = [here(sub) for sub in copy if here(sub) in mine]
    remove = sorted(set(mine) - {here(sub) for sub in card}) if prune else []
    out.update(copy=len(copy), bytes=sum(card[s] for s in copy), replaced=len(replace), removed=len(remove))
    if dry_run:
        return out
    if copy:
        os.makedirs(local, exist_ok=True)
        free = shutil.disk_usage(local).free
        if free < out["bytes"] + SPARE:
            raise RuntimeError("not enough space on this computer: need %.1f GB and keep 0.5 GB spare, %.1f GB free"
                               % (out["bytes"] / 1e9, free / 1e9))
    moved = replace + remove
    if moved:
        prev = local + ".previous"
        if os.path.isdir(prev):
            shutil.rmtree(prev)
        for sub in moved:
            dest = os.path.join(prev, *sub.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(os.path.join(local, *sub.split("/")), dest)
        _remove_empty(local)
    if copy and out["present"]:
        mirror.pull_section(target, remote, local, accept, overwrite=True, aliases=aliases,
                            progress=progress)
    return out


# ---- the parts ----

def look(target, vehicle, dry_run=False):
    """The phone's look replaces this vehicle's. A phone without one leaves the vehicle the built-in look.
    Adds "title" (the phone's) once copied."""
    out = _mirror(target, layout.PROFILE_DIR, profile.folder_of(vehicle), dry_run=dry_run)
    out["title"] = None
    if not dry_run and os.path.exists(os.path.join(profile.folder_of(vehicle), "profile.json")):
        out["title"] = profile.load(vehicle).get("title")
    return out


def voices(target, vehicle, dry_run=False):
    """The phone's voice packs replace this vehicle's. Adds "packs": the ids the phone has."""
    out = _mirror(target, voice.VOICE_DIR, voice.packs_dir(vehicle), dry_run=dry_run)
    out["packs"] = [e.name for e in target.listdir(voice.VOICE_DIR)
                    if e.is_dir and target.exists(voice.VOICE_DIR + "/" + e.name + "/voice.json")]
    return out


def find_region(name):
    """The server path of the map called `name` (e.g. south-africa-and-lesotho.map), or None when the
    server has none or several by that name."""
    hits = [e for e in maps.catalog() if e["name"] == name]
    return hits[0]["path"] if len(hits) == 1 else None


def the_map(target, dry_run=False, progress=None):
    """The phone's map: copied into the map cache (so the next sync need not download it), and its region
    made this vehicle's. {"name", "bytes", "copied", "region", "was": the region before, "found": the
    server has the phone's map (None when it could not be asked)}."""
    on_card = sorted(maps.installed(target, layout.MAPS_DIR), key=lambda e: e.name)
    was = maps.chosen()
    out = {"name": None, "bytes": 0, "copied": False, "region": was, "was": was, "found": None}
    if not on_card:
        return out
    e = on_card[0]                      # the app shows the first
    out["name"], out["bytes"] = e.name, e.size
    have = maps.cached(e.name)
    need = not have or os.path.getsize(have) != e.size
    out["copied"] = need
    if dry_run:
        return out
    if need:
        final = os.path.join(paths.cache_dir(), e.name)
        tmp = final + ".phone.part"
        os.makedirs(paths.cache_dir(), exist_ok=True)
        if shutil.disk_usage(paths.cache_dir()).free < e.size + SPARE:
            raise RuntimeError("not enough space for the map: need %.1f GB and keep 0.5 GB spare" % (e.size / 1e9))
        try:
            target.pull(layout.MAPS_DIR + "/" + e.name, tmp)
            if progress:
                progress(e.size, e.size)
            maps.check(tmp)
            os.replace(tmp, final)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    if was and os.path.basename(was) == e.name:
        out["found"] = True
        return out
    try:
        region = find_region(e.name)
    except Exception:                   # offline: the Maps page can choose it later
        return out
    out["found"] = bool(region)
    if region:
        cfg = paths.load_config()
        cfg["map_region"] = region
        paths.save_config(cfg)
        out["region"] = region
    return out


def music(target, vehicle, dry_run=False, progress=None, music_path="", music_match=""):
    """The phone's music and its index replace this vehicle's. With music_path or music_match only those
    songs are copied, and nothing is taken away. {"present", "songs", "bytes", "replaced", "removed"}."""
    music_remote = layout.MUSIC_DIR
    if not target.exists(music_remote) and target.exists(layout.LEGACY_MUSIC_DIR):
        music_remote = layout.LEGACY_MUSIC_DIR          # music dropped on the card by hand
    local = os.path.join(vehicle, *layout.MUSIC_DIR.split("/"))
    # songs this computer has under names the card carries without emoji
    aliases = {_nfc(card): mine for mine, card in card_names(list(_local_files(local))).items() if card != mine}
    accept = mirror._music_filter(music_path, music_match)
    r = _mirror(target, music_remote, local, accept, aliases, prune=accept is None, dry_run=dry_run,
                progress=(lambda i, n, d, t, name: progress(d, t)) if progress else None)
    if accept is None:
        _mirror(target, layout.LIBRARY_DIR, os.path.join(vehicle, *layout.LIBRARY_DIR.split("/")), dry_run=dry_run)
    return {"present": r["present"], "songs": r["copy"], "bytes": r["bytes"], "replaced": r["replaced"],
            "removed": r["removed"]}


def pull(target, vehicle, only=None, dry_run=False, step=None, progress=None, music_path="", music_match=""):
    """Replaces this computer's look, voices, map and music with the phone's (or with dry_run, says what
    it would). `step(name)` as each part starts (STEPS), `progress(done, total)` in bytes. Returns
    {part: result}."""
    only = set(only or PARTS)
    out = {}
    for name, part in zip(STEPS, PARTS):
        if part not in only:
            continue
        if step:
            step(name)
        if part == "look":
            out[part] = look(target, vehicle, dry_run)
        elif part == "voices":
            out[part] = voices(target, vehicle, dry_run)
        elif part == "map":
            out[part] = the_map(target, dry_run, progress)
        else:
            out[part] = music(target, vehicle, dry_run, progress, music_path, music_match)
    return out


def _size(n):
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


def _n(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else many or one + "s")


def says(r):
    """A pull's result (or dry run) as short phrases: what came (or comes) from the phone."""
    out = []
    lk = r.get("look") or {}
    if lk.get("copy") or lk.get("removed"):
        out.append("its look" + (" (%s)" % lk["title"] if lk.get("title") else "") if lk.get("present")
                   else "the built-in look (the phone has no look of its own)")
    vo = r.get("voices") or {}
    if vo.get("copy") or vo.get("removed"):
        out.append(_n(len(vo["packs"]), "voice pack") if vo["packs"] else "no voice packs (only the built-in voice)")
    mp = r.get("map") or {}
    if mp.get("name") and (mp.get("copied") or mp.get("region") != mp.get("was") or not mp.get("was")):
        out.append("the map (%s)" % mp["name"][:-4])
    mu = r.get("music") or {}
    if mu.get("songs"):
        out.append("%s (%s)" % (_n(mu["songs"], "song"), _size(mu["bytes"])))
    return out


def moved(r):
    """The folders a pull's result moved this computer's files into, as names ("profile.previous", ...)."""
    names = (("look", "profile.previous"), ("voices", "voice.previous"), ("music", "Music.previous"))
    return [name for part, name in names if (r.get(part) or {}).get("replaced") or (r.get(part) or {}).get("removed")]
