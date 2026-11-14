"""Copy folders between the card and a workspace on the computer.

The workspace mirrors the card's music, so a new computer can be filled from the phone (pull_all) and the
phone's music from the workspace (push_music):

    <workspace>/coldshift.dash/Music/      the music, as on the card
    <workspace>/coldshift.dash/library/    the music index and covers (can be rebuilt with `index`)
    <workspace>/recordings/clips|marks|trips

The first two are laid out exactly as on the card. The look, voice packs and map come from the phone
with fromphone, which puts them where the vehicle keeps them.

Rules that protect data on the computer:
  * a file that already exists with the same size counts as done and is not copied again, so
    pulling onto a computer that already has part of the music only fetches the rest;
  * a file that exists with a DIFFERENT size is left alone and reported as a conflict, unless
    overwrite=True (a partial copy never looks like that: copies go to a .part file first);
  * the copy is checked against the size on the card before it replaces anything;
  * nothing is ever deleted from the computer, and from the card only by push_music with
    delete_extra=True (music on the card that the workspace does not have).

Pushing follows the same rules the other way: a file on the card with a different size is a
conflict, left alone unless overwrite=True.
"""
import json
import os
import shutil
import time
import unicodedata

from . import layout, recordings
from .library import build_index, card_names

SECTIONS = ("library", "music", "recordings")
STATE = ".dashsync-workspace.json"


def _entries(target, rel):
    return [e for e in target.listdir(rel) if not e.name.endswith(".part")]


def walk(target, rel, accept=None, _prefix=""):
    """(path relative to `rel`, size) for every file below rel, in a stable order."""
    for e in _entries(target, rel):
        sub = _prefix + e.name
        if e.is_dir:
            yield from walk(target, rel + "/" + e.name, accept, sub + "/")
        elif accept is None or accept(sub):
            yield sub, e.size


def _plan(target, remote, local, accept, overwrite, aliases=None):
    """Sort what is on the card into: to copy, already there, and conflicts. `aliases` maps a card
    name to the workspace's name for the same file (songs renamed for the phone)."""
    todo, have, conflicts = [], [], []
    for sub, size in walk(target, remote, accept):
        dest = os.path.join(local, *(aliases or {}).get(unicodedata.normalize("NFC", sub), sub).split("/"))
        if os.path.exists(dest):
            have_size = os.path.getsize(dest)
            if have_size == size:
                have.append((sub, size))
                continue
            conflicts.append((sub, size, have_size))
            if not overwrite:
                continue
        todo.append((remote + "/" + sub, dest, sub, size))
    return todo, have, conflicts


def pull_section(target, remote, local, accept=None, overwrite=False, dry_run=False, progress=None, aliases=None):
    """Mirror one folder from the card. Returns counts; raises RuntimeError if the disk is too small."""
    out = {"present": target.exists(remote), "pulled": 0, "bytes": 0, "had": 0, "conflicts": [], "would_pull": 0,
           "would_bytes": 0}
    if not out["present"]:
        return out
    todo, have, conflicts = _plan(target, remote, local, accept, overwrite, aliases)
    out["had"] = len(have)
    out["conflicts"] = [(sub, card, mine) for sub, card, mine in conflicts if not overwrite]
    need = sum(t[3] for t in todo)
    if dry_run:
        out["would_pull"], out["would_bytes"] = len(todo), need
        return out
    if todo:
        os.makedirs(local, exist_ok=True)
        free = shutil.disk_usage(local).free
        if free < need + 512 * 1024 * 1024:
            raise RuntimeError("not enough space: need %.1f GB and keep 0.5 GB spare, %.1f GB free"
                               % (need / 1e9, free / 1e9))
    done_bytes = 0
    for i, (rrel, dest, sub, size) in enumerate(todo):
        tmp = dest + ".part"
        target.pull(rrel, tmp)
        if os.path.getsize(tmp) != size:
            os.remove(tmp)
            raise RuntimeError("size mismatch after copying %s: card has %d bytes" % (sub, size))
        os.replace(tmp, dest)
        done_bytes += size
        out["pulled"] += 1
        out["bytes"] += size
        if progress:
            progress(i + 1, len(todo), done_bytes, need, sub)
    return out


def _music_filter(path_prefix, match):
    if not path_prefix and not match:
        return None
    pre = path_prefix.strip("/").lower()
    m = (match or "").lower()

    def accept(sub):
        low = sub.lower()
        return (not pre or low == pre or low.startswith(pre + "/")) and (not m or m in low)
    return accept


def pull_all(target, sources, workspace, only=None, music_path="", music_match="", overwrite=False,
             dry_run=False, log=print, progress=None):
    """Fill `workspace` from the card. `target` is where the folders are, `sources` where recordings may be.
    Returns {section: result}."""
    only = set(only or SECTIONS)
    unknown = only - set(SECTIONS)
    if unknown:
        raise ValueError("unknown section(s): " + ", ".join(sorted(unknown)))
    os.makedirs(workspace, exist_ok=True)
    res = {}
    music_remote = layout.MUSIC_DIR
    if not target.exists(music_remote) and target.exists(layout.LEGACY_MUSIC_DIR):
        music_remote = layout.LEGACY_MUSIC_DIR          # music dropped on the card by hand
    plan = (("library", layout.LIBRARY_DIR, layout.LIBRARY_DIR, None),
            ("music", music_remote, layout.MUSIC_DIR, _music_filter(music_path, music_match)))
    for name, remote, local, accept in plan:
        if name not in only:
            continue
        local_dir = os.path.join(workspace, *local.split("/"))
        aliases = None
        if name == "music" and os.path.isdir(local_dir):
            # songs the workspace has under names the card carries without emoji
            aliases = {card: mine for mine, card in card_names(list(_local_files(local_dir))).items() if card != mine}
        r = pull_section(target, remote, local_dir, accept, overwrite, dry_run,
                         progress if name == "music" else None, aliases)
        res[name] = r
        if not r["present"]:
            log("%-10s nothing on the phone" % name)
        elif dry_run:
            log("%-10s would copy %d files (%.1f MB); %d already here" % (name, r["would_pull"], r["would_bytes"] / 1e6, r["had"]))
        else:
            log("%-10s copied %d files (%.1f MB); %d already here" % (name, r["pulled"], r["bytes"] / 1e6, r["had"]))
        for sub, card, mine in r["conflicts"]:
            log("  CONFLICT, kept your copy: %s (card %d bytes, yours %d); use --overwrite to replace" % (sub, card, mine))
    if "recordings" in only:
        rr = recordings.pull(sources, os.path.join(workspace, "recordings"), dry_run=dry_run, log=lambda m: None)
        res["recordings"] = rr
        log("%-10s %s" % ("recordings", ("would copy" if dry_run else "copied") + " %d files; %d already here" % (rr["pulled"], rr["skipped_done"])
                           if rr["missing_sources"] < len(sources) else "nothing on the phone"))
    if not dry_run:
        meta = {"last_pull": int(time.time()), "device": getattr(target, "label", "")}
        with open(os.path.join(workspace, STATE), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
    return res


# ---- push: workspace to card ----

def _local_files(folder):
    """{path relative to folder (NFC, '/'): size} for every file below it, skipping dotfiles and .part."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or name.endswith(".part"):
                continue
            full = os.path.join(dirpath, name)
            rel = unicodedata.normalize("NFC", os.path.relpath(full, folder).replace(os.sep, "/"))
            out[rel] = os.path.getsize(full)
    return out


def plan_push(target, local, remote, overwrite=False, rename=False):
    """Compares a workspace folder with the card's: {"copy": [(sub, card name, size)], "same": n,
    "conflicts": [(card name, card size, workspace size)], "extra": [(card name, size)],
    "move": [(old card name, card name)], "renamed": n}. With rename, files get their card names
    (library.card_names), and a file already on the card under its workspace name is moved to its
    card name instead of copied again. With overwrite, conflicts are in "copy" as well."""
    mine = _local_files(local) if os.path.isdir(local) else {}
    names = card_names(list(mine)) if rename else {sub: sub for sub in mine}
    card = {}
    if target.exists(remote):
        card = {unicodedata.normalize("NFC", sub): size for sub, size in walk(target, remote)}
    plan = {"copy": [], "same": 0, "conflicts": [], "extra": [], "move": [],
            "renamed": sum(1 for sub, name in names.items() if sub != name)}
    moved = set()
    for sub in sorted(mine):
        size, name = mine[sub], names[sub]
        if name not in card and sub != name and card.get(sub) == size:
            plan["move"].append((sub, name))
            moved.add(sub)
        elif name not in card:
            plan["copy"].append((sub, name, size))
        elif card[name] == size:
            plan["same"] += 1
        else:
            plan["conflicts"].append((name, card[name], size))
            if overwrite:
                plan["copy"].append((sub, name, size))
    wanted = set(names.values())
    plan["extra"] = sorted((sub, size) for sub, size in card.items() if sub not in wanted and sub not in moved)
    return plan


def _push_files(target, local, remote, items, progress=None, label=""):
    """Copies (workspace sub, card name, size) items, checking each by its size on the card."""
    need = sum(size for _, _, size in items)
    done_bytes = 0
    for i, (sub, name, size) in enumerate(items):
        dest = remote + "/" + name
        target.push(os.path.join(local, *sub.split("/")), dest)
        got = [e for e in target.listdir(dest.rpartition("/")[0])
               if unicodedata.normalize("NFC", e.name) == name.rpartition("/")[2]]
        if not got or got[0].size != size:
            raise RuntimeError("size mismatch after copying %s to the card" % name)
        done_bytes += size
        if progress:
            progress(i + 1, len(items), done_bytes, need, label + name)


def _remove_empty_folders(target, remote, removed):
    """After deleting files, removes the folders they leave empty (deepest first), never `remote` itself."""
    folders = set()
    for sub in removed:
        parts = sub.split("/")[:-1]
        folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    for folder in sorted(folders, key=lambda f: -f.count("/")):
        rel = remote + "/" + folder
        if target.exists(rel) and not target.listdir(rel):
            target.remove(rel)


def push_music(target, workspace, overwrite=False, delete_extra=False, dry_run=False, progress=None,
               indexing=None):
    """Puts the workspace's music and its index on the card, then tells the app to reload.

    1. index the workspace's music (fast when nothing changed; `indexing(done, total, rel)`),
    2. copy music the card lacks (and, with overwrite, files whose size differs), under names this
       phone can read (library.card_names); a song already on the card under its old name is
       renamed there instead,
    3. with delete_extra, remove music on the card the workspace does not have,
    4. copy the library: the covers the card lacks, then index.json (always); remove covers the index
       no longer uses,
    5. ask the running app to reload its music.
    Music goes before the index, so the app never reads an index naming files that are not there.
    Returns the plans and what was done; with dry_run only the plans."""
    music = os.path.join(workspace, *layout.MUSIC_DIR.split("/"))
    library = os.path.join(workspace, *layout.LIBRARY_DIR.split("/"))
    if not os.path.isdir(music):
        raise SystemExit("this vehicle has no music yet (put songs in %s)" % music)
    index = build_index(music, library, progress=indexing)
    mplan = plan_push(target, music, layout.MUSIC_DIR, overwrite, rename=True)
    lplan = plan_push(target, library, layout.LIBRARY_DIR, overwrite=True)
    art = layout.ART_DIR + "/"
    lcopy = [item for item in lplan["copy"] if item[0].startswith(art)]
    # the index always goes (160 KB): a tag fix can leave its size unchanged
    lcopy.append((layout.INDEX_NAME, layout.INDEX_NAME, os.path.getsize(os.path.join(library, layout.INDEX_NAME))))
    # covers are generated, so the ones the index no longer uses (or empty leftovers) go
    stale_art = [sub for sub, _ in lplan["extra"] if sub.startswith(art)]
    out = {"index": index, "music": mplan, "library_copy": len(lcopy), "stale_covers": len(stale_art), "copied": 0,
           "bytes": 0, "deleted": 0, "moved": 0, "app": None}
    if dry_run:
        return out
    need = sum(item[2] for item in mplan["copy"]) + sum(item[2] for item in lcopy)
    free = target.free_bytes()
    if free is not None and free < need + 100 * 1024 * 1024:
        raise SystemExit("not enough space on the card: need %.1f GB and keep 0.1 GB spare, %.1f GB free"
                         % (need / 1e9, free / 1e9))
    for old_name, name in mplan["move"]:
        target.rename(layout.MUSIC_DIR + "/" + old_name, layout.MUSIC_DIR + "/" + name)
    _remove_empty_folders(target, layout.MUSIC_DIR, [old_name for old_name, _ in mplan["move"]])
    out["moved"] = len(mplan["move"])
    _push_files(target, music, layout.MUSIC_DIR, mplan["copy"], progress)
    out["copied"] = len(mplan["copy"])
    out["bytes"] = sum(item[2] for item in mplan["copy"])
    if delete_extra:
        for sub, _ in mplan["extra"]:
            target.remove(layout.MUSIC_DIR + "/" + sub)
        out["deleted"] = len(mplan["extra"])
        _remove_empty_folders(target, layout.MUSIC_DIR, [sub for sub, _ in mplan["extra"]])
    # the index last of all, after its covers
    _push_files(target, library, layout.LIBRARY_DIR, lcopy, progress, label="library/")
    for sub in stale_art:
        target.remove(layout.LIBRARY_DIR + "/" + sub)
    out["app"] = target.notify_synced(["music"])
    return out
