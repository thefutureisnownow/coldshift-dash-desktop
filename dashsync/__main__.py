"""coldshift dash card tools.

  python -m dashsync index       --card /Volumes/CARD            music index and covers
  python -m dashsync maps list   [africa]                        browse the map server
  python -m dashsync maps find   swaziland                       search it
  python -m dashsync maps get    africa/swaziland.map            download to the cache
  python -m dashsync maps install africa/swaziland.map --adb     download if needed, copy to the card
  python -m dashsync maps choose [south africa]                  pick your region (browse, search or a path)
  python -m dashsync maps status [--adb]                         your region on the server, here, on the card
  python -m dashsync maps sync --adb                             put your region on the card, updating it if newer
  python -m dashsync routing list                                the routing tiles your region needs
  python -m dashsync routing sync --adb                          put them on the card (offline navigation)
  python -m dashsync search sync --adb                           build the place search for your region, put it on the card
  python -m dashsync search find york street george              try a search here, as the app does it
  python -m dashsync places backup --adb                         copy the app's Home, Work and saved places to the workspace
  python -m dashsync places restore --adb                        put them back (the app merges them in)
  python -m dashsync voice new "My voice"                        start a voice pack for navigation prompts
  python -m dashsync voice lines my-voice                        the lines to record, and which are done
  python -m dashsync voice add my-voice turn_left left.mp3       add a recording for a line
  python -m dashsync voice install pack.zip / export ID pack.zip share packs
  python -m dashsync profile show | set car car.png | badge b.png   the vehicle's look (title bar, splash, ...)
  python -m dashsync profile sync --adb                          put it on the card
  python -m dashsync voice sync --adb                            put them on the card (choose one in the app's Settings)
  python -m dashsync recordings pull --adb --dest ~/Movies/dash  copy clips, marks and trips to the Mac
  python -m dashsync pull-all --workspace ~/dash --adb --serial ID   copy everything on the phone to this computer
  python -m dashsync music push --adb [--dry-run]                index the workspace's music and put it on the card
  python -m dashsync adb status                                  is adb installed, and where
  python -m dashsync adb setup --accept-licence                  download Google's standalone adb
  python -m dashsync adb devices                                 list phones (talks to none of them)
  python -m dashsync adb app --serial ID                         is the app on that phone, which version
  python -m dashsync adb wifi on --serial ID                     switch a cabled phone to adb over Wi-Fi

Everything is per vehicle:  vehicle list | new NAME | use ID   (the open vehicle's folder holds it all)
Where the card is:  --card /Volumes/CARD  (card reader)   or   --adb [--serial ID]  (phone on USB)
"""
import argparse
import os
import sys

from . import adbtool, layout, library, maps, mirror, paths, places, profile, recordings, routing, search, vehicles, voice
from .library import build_index
from .transport import open_sources, open_target


def _where(p):
    p.add_argument("--card", help="the card mounted as a folder")
    p.add_argument("--adb", action="store_true", help="the phone over USB (adb)")
    p.add_argument("--serial", help="adb serial, if more than one device is attached")
    p.add_argument("--adb-path", help="path to adb")


def _mb(n):
    return "%.0f MB" % (n / 1048576) if n < 1 << 30 else "%.1f GB" % (n / (1 << 30))


def cmd_index(a, ap):
    if a.card:
        p = layout.card_paths(a.card)
        music, out = p["music"], p["library"]
    elif a.music and a.out:
        music, out = a.music, a.out
    else:
        ap.error("give --card, or both --music and --out")
    if not os.path.isdir(music):
        sys.exit("no such music folder: " + music)

    def progress(done, total, rel):
        if sys.stderr.isatty() and (done % 25 == 0 or done == total):
            print("\r%d / %d" % (done, total), end="", file=sys.stderr, flush=True)

    if a.card:
        # the card itself: give files the names this phone can read, as a push would
        for rel, name in library.rename_on_card(music):
            print("renamed for the phone: %s -> %s" % (rel, name.rpartition("/")[2]))
    r = build_index(music, out, progress, prune=not a.keep_orphans)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    if r["renamed"] and not a.card:
        print("%d songs have emoji written as codes (U+1F3B6) in the index, since this phone garbles emoji; "
              "a push copies them to the card under those names" % len(r["renamed"]))
    print("indexed %(tracks)d tracks (%(read)d read, %(reused)d unchanged), %(covers)d covers, "
          "%(pruned_covers)d old covers removed, %(index_bytes)d byte index, %(seconds)s s" % r)


def _progress(done, total):
    if sys.stderr.isatty():
        print("\r%s of %s" % (_mb(done), _mb(total)), end="", file=sys.stderr, flush=True)


def _pick(entries, prompt):
    """Numbered choice on the terminal; returns an entry, "up", or None to stop."""
    for i, e in enumerate(entries, 1):
        print("%3d  %-40s %s" % (i, e["name"] + ("/" if e["dir"] else ""), "" if e["dir"] else _mb(e["approx_bytes"])))
    while True:
        try:
            ans = input(prompt).strip()
        except EOFError:
            return None
        if ans in ("", "q"):
            return None
        if ans == "..":
            return "up"
        if ans.isdigit() and 1 <= int(ans) <= len(entries):
            return entries[int(ans) - 1]
        print("type a number from the list")


def _choose_region(term):
    """The server path the user means: a path as given, a single search hit, or a choice on the terminal."""
    if term and "/" in term:
        return term
    if term:
        hits = maps.find(term)
        one = hits[0] if len(hits) == 1 else maps.best(hits, term)
        if one:
            return one["path"]
        if not hits:
            raise SystemExit("no map matches %r; run  maps choose  without a name to browse" % term)
        if not sys.stdin.isatty():
            raise SystemExit("%r matches %d maps; name one: %s" % (term, len(hits), ", ".join(h["path"] for h in hits)))
        e = _pick(hits, "which one (number, or Enter to stop)? ")
        return e["path"] if isinstance(e, dict) else None
    if not sys.stdin.isatty():
        raise SystemExit("name the region, e.g.  maps choose africa/south-africa-and-lesotho.map")
    trail = [""]
    while True:
        print("\n" + (trail[-1] + "/" if trail[-1] else "map server") + ":")
        e = _pick(maps.list_region(trail[-1]), "number to open or choose, .. to go up, Enter to stop: ")
        if e is None:
            return None
        if e == "up":
            if len(trail) > 1:
                trail.pop()
        elif e["dir"]:
            trail.append(e["path"])
        else:
            return e["path"]


def _when(dt):
    return dt.strftime("%Y-%m-%d") if dt else "?"


def cmd_maps(a, ap):
    if a.mcmd == "choose":
        path = _choose_region(" ".join(a.term) if a.term else None)
        if not path:
            print("nothing chosen; region is still %s" % (maps.chosen() or "not set"))
            return
        path, info = maps.choose(path)
        print("region: %s (%s, built %s)" % (path, _mb(info["bytes"]), _when(info["modified"])))
        print("next:  python -m dashsync maps sync --adb   (or --card /Volumes/CARD)")
    elif a.mcmd == "status":
        t = open_target(a.card, a.adb, a.serial, a.adb_path) if (a.card or a.adb or a.serial) else None
        st = maps.status(t, layout.MAPS_DIR)
        if not st["region"]:
            print("no region chosen yet: run  maps choose")
            return
        print("region: " + st["region"])
        srv = st["server"]
        print("server: " + ("%s, built %s" % (_mb(srv["bytes"]), _when(srv["modified"])) if srv
                            else "unreachable (%s)" % st.get("server_error")))
        c = st["cache"]
        print("here:   " + ("%s, built %s%s" % (_mb(c["bytes"]), _when(c["written"]), ", a newer build is on the server" if c["outdated"] else "")
                            if c else "not downloaded"))
        if t is not None:
            card = st["card"]
            line = ("not there" if not card else "same as here" if card["current"]
                    else "a different build (%s)" % _mb(card["bytes"]))
            if st["card_other"]:
                line += "; also " + ", ".join(st["card_other"]) + " (sync removes it)"
            print("card:   %s (%s)" % (line, t.label))
    elif a.mcmd == "sync":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)
        msg = maps.sync(t, layout.MAPS_DIR, _progress)
        if sys.stderr.isatty():
            print(file=sys.stderr)
        print(msg + " on " + t.label)
        note = maps.tell_app(t, msg)
        if note:
            print(note)
    elif a.mcmd == "list":
        for e in maps.list_region(a.path or ""):
            print("%-44s %s" % (e["path"] + ("/" if e["dir"] else ""), "" if e["dir"] else _mb(e["approx_bytes"])))
    elif a.mcmd == "find":
        hits = maps.find(" ".join(a.term))
        for e in hits:
            print("%-44s %s" % (e["path"], _mb(e["approx_bytes"])))
        if not hits:
            print("no map matches %r" % " ".join(a.term))
    elif a.mcmd in ("get", "install"):
        path = a.path if a.path.endswith(".map") else a.path + ".map"
        local = maps.download(path, _progress)
        if sys.stderr.isatty():
            print(file=sys.stderr)
        print("have %s (%s, checked)" % (local, _mb(os.path.getsize(local))))
        if a.mcmd == "install":
            t = open_target(a.card, a.adb, a.serial, a.adb_path)
            msg = maps.install(t, local, layout.MAPS_DIR, replace=a.replace, replace_older=a.replace)
            print(msg + " on " + t.label)
            note = maps.tell_app(t, msg)
            if note:
                print(note)
    elif a.mcmd == "installed":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)
        for e in maps.installed(t, layout.MAPS_DIR):
            print("%-40s %s" % (e.name, _mb(e.size)))


def cmd_routing(a, ap):
    if a.rcmd == "list":
        want = routing.wanted()
        for name, info in want:
            print("%-10s %8s  built %s%s" % (name, _mb(info["bytes"]), info["modified"].strftime("%Y-%m-%d"),
                                            "  (here)" if routing.cached(name, info) else ""))
        print("%d tiles, %s, for %s" % (len(want), _mb(sum(i["bytes"] for _, i in want)), maps.chosen()))
    elif a.rcmd == "sync":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)

        def progress(i, n, done, total, name):
            if sys.stderr.isatty():
                print("\r  downloading %d/%d %s  %s of %s" % (i, n, name, _mb(done), _mb(total)), end="\x1b[K",
                      file=sys.stderr, flush=True)

        r = routing.sync(t, progress)
        if sys.stderr.isatty():
            print(file=sys.stderr)
        print("routing: %(tiles)d tiles; %(downloaded)d downloaded, %(copied)d copied to the card, "
              "%(removed)d old ones removed" % r + " on " + t.label)


def cmd_search(a, ap):
    def progress(done, total):
        if sys.stderr.isatty():
            print("\r  downloading OpenStreetMap data  %s of %s" % (_mb(done), _mb(total)), end="\x1b[K",
                  file=sys.stderr, flush=True)

    def log(line):
        if sys.stderr.isatty():
            print(file=sys.stderr)
        print(line)

    if a.scmd == "build":
        path, built = search.prepare(progress=progress, log=log)
        print("%s: %s%s" % (path, _mb(os.path.getsize(path)), "" if built else " (already up to date)"))
    elif a.scmd == "find":
        path = search.local_db()
        if not os.path.exists(path):
            sys.exit("no search index built yet: run  search build")
        near = [float(x) for x in a.near.split(",")] if a.near else (None, None)
        for r in search.query(path, " ".join(a.text), near[0], near[1], a.limit):
            print("%-40s %-22s %s" % (r["name"][:40], r["detail"][:22], r["area"]))
    elif a.scmd == "sync":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)
        r = search.sync(t, progress, log=log)
        reply = t.notify_synced(["search"]) if r["copied"] else None
        print("search: %s, %s; %s%s" % (r["file"], _mb(r["bytes"]), "copied to the card" if r["copied"] else "already on the card",
                                       "; the app " + reply if reply else ""))


def cmd_places(a, ap):
    ws = _workspace(a)
    t = open_target(a.card, a.adb, a.serial, a.adb_path)
    if a.pcmd == "show":
        got = places.on_phone(t)
        print("phone:     " + (places.describe(got) if got is not None else "no places yet"))
        path = places.backup_path(ws)
        print("workspace: " + (places.describe(places.read(path)) if os.path.exists(path) else "no backup yet"))
    elif a.pcmd == "backup":
        r = places.backup(t, ws)
        if r["places"] is None:
            print("the phone has no places yet (they appear once Home, Work or a place is saved)")
        else:
            print("%s: %s%s" % (r["path"], places.describe(r["places"]), "" if r["changed"] else " (unchanged)"))
    elif a.pcmd == "restore":
        r = places.restore(t, ws)
        print("put back %s; %s" % (places.describe(r["places"]), "the app " + r["app"] if r["app"] else
                                   "the app merges them in when it next starts"))


def _pack(ws, pid):
    for folder, m in voice.packs(ws):
        if m["id"] == pid:
            return folder, m
    sys.exit("no voice pack %r in %s (voice list shows them)" % (pid, voice.packs_dir(ws)))


def cmd_voice(a, ap):
    ws = _workspace(a)
    if a.vcmd == "list":
        got = voice.packs(ws)
        for folder, m in got:
            print("%-12s %-20s %d of %d lines" % ((m["id"], m["name"]) + voice.recorded(m)))
        if not got:
            print("no voice packs in %s (the app has Angie built in)" % voice.packs_dir(ws))
    elif a.vcmd == "lines":
        folder, m = _pack(ws, a.pack)
        for key, text in voice.LINES.items():
            f = m["lines"].get(key)
            secs = voice.duration(os.path.join(folder, f)) if f else None
            print("%-18s %-44s %s" % (key, text, "%.1f s" % secs if secs else "-- not recorded"))
    elif a.vcmd == "new":
        folder = voice.create(ws, a.name, voice.builtin_dir() if a.from_angie else None)
        print("new voice pack:", folder)
    elif a.vcmd == "add":
        folder, m = _pack(ws, a.pack)
        print("%s: %s, %.1f s" % (m["name"], a.line, voice.set_line(folder, a.line, a.file)))
    elif a.vcmd == "install":
        m = voice.install(a.path, ws)
        print("added %s (%d of %d lines) to %s" % ((m["name"],) + voice.recorded(m) + (voice.packs_dir(ws),)))
    elif a.vcmd == "export":
        folder, m = _pack(ws, a.pack)
        print("exported", voice.export(folder, os.path.expanduser(a.zip)))
    elif a.vcmd == "sync":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)
        r = voice.sync(t, ws)
        print("voice: %s on the card; %d files changed, %d old packs removed%s" % (
            ", ".join(r["packs"]) or "no packs", r["copied"], r["removed"], "; the app " + r["app"] if r["app"] else ""))


def cmd_profile(a, ap):
    ws = _workspace(a)
    if a.prcmd == "show":
        prof = profile.load(ws)
        print("title:     %s" % (prof.get("title") or "(none)"))
        print("badges:    %s" % (", ".join(prof["badges"]) or "(none)"))
        for key in profile.IMAGES:
            print("%-18s %s" % (key + ":", profile.image(ws, key) or "(none)"))
        print("splash:    effect %(effect)s, logo %(position)s" % prof["splash"])
    elif a.prcmd == "set":
        profile.set_image(ws, a.what, a.picture)
        print("%s: %s" % (a.what, profile.image(ws, a.what)))
    elif a.prcmd == "none":
        profile.clear_image(ws, a.what)
        print("%s: none" % a.what)
    elif a.prcmd == "builtin":
        profile.builtin_image(ws, a.what)
        print("%s: the built-in one" % a.what)
    elif a.prcmd == "badge":
        profile.add_badge(ws, a.picture)
        print("badges: %s" % ", ".join(profile.load(ws)["badges"]))
    elif a.prcmd == "options":
        profile.set_options(ws, a.title, a.effect, a.position)
        print("saved")
    elif a.prcmd == "sync":
        t = open_target(a.card, a.adb, a.serial, a.adb_path)
        r = profile.sync(t, ws)
        print("profile: %s" % ("the app " + r["app"] if r["app"] else "copied" if r["changed"] else "already on the card"))


def cmd_recordings(a, ap):
    if a.rcmd == "pull":
        srcs = open_sources(a.card, a.adb, a.serial, a.adb_path)
        r = recordings.pull(srcs, os.path.expanduser(a.dest), delete_synced=a.delete_synced, force=a.force,
                            dry_run=a.dry_run)
        print("pulled %(pulled)d files (%(bytes)d bytes), %(skipped_done)d already had, %(skipped_busy)d busy, "
              "%(deleted)d removed from the card" % r)
        if r["missing_sources"] == len(srcs):
            sys.exit("no dashcam folder found; has the app recorded anything yet?")


def cmd_adb(a, ap):
    def need():
        try:
            return adbtool.require(a.adb_path if hasattr(a, "adb_path") else None)
        except adbtool.AdbMissing as e:
            sys.exit(str(e))

    if a.acmd == "status":
        st = adbtool.status(a.adb_path)
        if st["found"]:
            print("adb %s, %s\n  %s" % (st["version"], st["source"], st["path"]))
        else:
            print("adb is NOT installed (or not found).\n" + st["hint"])
            sys.exit(1)
    elif a.acmd == "setup":
        def progress(done, total):
            if sys.stderr.isatty():
                print("\r%s of %s" % (_mb(done), _mb(total)), end="", file=sys.stderr, flush=True)
        if not a.accept_licence:
            sys.exit("This downloads Google's Android SDK Platform-Tools, which are covered by the Android SDK\n"
                     "licence: %s\nRead it, then run again with --accept-licence." % adbtool.LICENCE_URL)
        path, ver = adbtool.setup(True, progress)
        if sys.stderr.isatty():
            print(file=sys.stderr)
        print("installed adb %s\n  %s" % (ver, path))
    elif a.acmd == "use":
        try:
            path, ver = adbtool.set_path(a.path)
        except ValueError as e:
            sys.exit(str(e))
        print("using adb %s at %s" % (ver, path))
    elif a.acmd == "forget":
        adbtool.forget_path()
        print("no adb path stored")
    elif a.acmd == "devices":
        adb = need()
        devs = adbtool.list_devices(adb)
        if not devs:
            print("no devices")
        for d in devs:
            h = adbtool.STATE_HELP.get(d["state"], "")
            print("%-22s %-13s %-14s %s%s" % (d["serial"], d["state"], "Wi-Fi" if d["wifi"] else "USB", d["model"],
                                              ("   <- " + h) if h else ""))
    elif a.acmd == "app":
        adb = need()
        if not a.serial:
            sys.exit("choose the phone with --serial (see: adb devices); other phones are never queried")
        st = adbtool.app_status(adb, a.serial)
        print("%s, Android %s" % (st["model"], st["android"]))
        if st["installed"]:
            print("coldshift dash %s (build %s) is installed%s" % (st["version"], st["version_code"],
                  "; has recordings" if st.get("has_recordings") else ""))
        else:
            print("coldshift dash is NOT installed on this phone")
            sys.exit(1)
    elif a.acmd == "install":
        adb = need()
        if not a.serial:
            sys.exit("choose the phone with --serial")
        adbtool.install_app(adb, a.serial, os.path.expanduser(a.apk))
        print("installed", a.apk)
    elif a.acmd == "wifi":
        adb = need()
        if not a.serial:
            sys.exit("choose the phone with --serial (the USB one when turning on, the IP:port one when turning off)")
        if a.state == "on":
            print("phone is now reachable as", adbtool.wifi_enable(adb, a.serial))
            print("(it forgets this when the phone reboots; 'wifi off' closes it)")
        else:
            adbtool.wifi_disable(adb, a.serial, a.usb_serial)
            print("disconnected" + ("; phone back in USB mode" if a.usb_serial else
                                   "; the phone's network port stays open until it reboots or you run this with --usb-serial"))


def _workspace(a):
    """The open vehicle's folder (or --workspace for this run only)."""
    ws = getattr(a, "workspace", None) or paths.load_config().get("workspace")
    if not ws:
        sys.exit("no vehicle yet: make one with  vehicle new NAME  (or open the window)")
    return os.path.abspath(os.path.expanduser(ws))


def cmd_vehicle(a, ap):
    if a.vecmd == "list":
        cur = vehicles.current()
        for v in vehicles.all():
            print("%s %-22s %-28s %s%s" % ("*" if cur and v["id"] == cur["id"] else " ", v["id"], v["name"], v["folder"],
                                         "" if v["exists"] else "  (folder missing)"))
    elif a.vecmd == "new":
        v = vehicles.create(a.name, a.folder)
        print("new vehicle %s in %s (now open)" % (v["name"], v["folder"]))
    elif a.vecmd == "add":
        v = vehicles.add(a.folder)
        print("added %s (%s), now open" % (v["name"], v["folder"]))
    elif a.vecmd == "use":
        vehicles.select(a.id)
        print("open:", vehicles.current()["name"])
    elif a.vecmd == "rename":
        vehicles.rename(a.id, a.name)
        print("renamed to", a.name)


def cmd_music(a, ap):
    ws = _workspace(a)
    t = open_target(a.card, a.adb, a.serial, a.adb_path)
    print("workspace:", ws, "\nto:", t.label)

    def indexing(done, total, rel):
        if sys.stderr.isatty():
            print("\r  indexing %d/%d" % (done, total), end="\x1b[K", file=sys.stderr, flush=True)

    def progress(i, n, done, total, name):
        if sys.stderr.isatty():
            print("\r  %d/%d  %s of %s  %s" % (i, n, _mb(done), _mb(total), name[:50]), end="\x1b[K", file=sys.stderr, flush=True)

    r = mirror.push_music(t, ws, a.overwrite, a.delete_extra, a.dry_run, progress, indexing)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    m = r["music"]
    verb = "would copy" if a.dry_run else "copied"
    print("music:    %s %d files (%s); %d already on the card" % (verb, len(m["copy"]), _mb(sum(x[2] for x in m["copy"])), m["same"]))
    if m["renamed"]:
        print("  %d songs have emoji in their names, which this phone garbles; on the card each emoji is its code (U+1F3B6)" % m["renamed"])
    if m["move"]:
        print("  %s %d songs already on the card to those names" % ("would rename" if a.dry_run else "renamed", len(m["move"])))
    for sub, card, mine in m["conflicts"]:
        print("  %s %s (card %d bytes, workspace %d)" % ("REPLACED" if a.overwrite and not a.dry_run else "CONFLICT, kept the card's:", sub, card, mine))
    if m["extra"]:
        if a.delete_extra:
            print("  %s %d files on the card that the workspace does not have" % ("would delete" if a.dry_run else "deleted", len(m["extra"])))
        else:
            print("  %d files on the card are not in the workspace (kept; --delete-extra removes them)" % len(m["extra"]))
        for sub, _ in m["extra"][:5]:
            print("    " + sub)
    print("library:  %s %d files (index and covers)%s" % (verb, r["library_copy"], ", %s %d unused covers" % (
        "would remove" if a.dry_run else "removed", r["stale_covers"]) if r["stale_covers"] else ""))
    if not a.dry_run:
        print("the app " + r["app"] if r["app"] else ("the app is not running; it reads the new music when it starts"
                                                      if t.kind == "adb" else "the app reloads when the card goes back in"))


def cmd_pull_all(a, ap):
    ws = _workspace(a)
    srcs = open_sources(a.card, a.adb, a.serial, a.adb_path)
    only = [x.strip() for x in a.only.split(",")] if a.only else None

    def progress(i, n, done, total, name):
        if sys.stderr.isatty():
            print("\r  %d/%d  %s of %s  %s" % (i, n, _mb(done), _mb(total), name[:50]), end="\x1b[K", file=sys.stderr, flush=True)
        elif i % 25 == 0 or i == n:
            print("  %d/%d  %s of %s" % (i, n, _mb(done), _mb(total)))

    print("workspace:", ws, "\nfrom:", srcs[0].label)
    try:
        mirror.pull_all(srcs[0], srcs, ws, only, a.music_path or "", a.music_match or "", a.overwrite, a.dry_run,
                        progress=progress)
    except (RuntimeError, ValueError) as e:
        sys.exit(str(e))
    if sys.stderr.isatty():
        print(file=sys.stderr)


def main(argv=None):
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(prog="dashsync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ix = sub.add_parser("index", help="build the music index and cover art the app reads")
    ix.add_argument("--card", help="card root; reads <card>/coldshift.dash/Music, writes <card>/coldshift.dash/library")
    ix.add_argument("--music", help="music folder (instead of --card)")
    ix.add_argument("--out", help="library output folder (instead of --card)")
    ix.add_argument("--keep-orphans", action="store_true", help="do not delete covers no track uses")

    mp = sub.add_parser("maps", help="map files")
    ms = mp.add_subparsers(dest="mcmd", required=True)
    ml = ms.add_parser("list"); ml.add_argument("path", nargs="?", help="server folder, e.g. africa")
    mf = ms.add_parser("find"); mf.add_argument("term", nargs="+")
    mg = ms.add_parser("get"); mg.add_argument("path", help="e.g. africa/swaziland.map")
    mi = ms.add_parser("install"); mi.add_argument("path"); _where(mi)
    mi.add_argument("--replace", action="store_true", help="remove a different map already on the card")
    mn = ms.add_parser("installed"); _where(mn)
    mc = ms.add_parser("choose", help="pick your region; remembered for status and sync")
    mc.add_argument("term", nargs="*", help="a server path, or part of a name; leave out to browse")
    mt = ms.add_parser("status", help="your region on the server, in the cache and on the card"); _where(mt)
    my = ms.add_parser("sync", help="put your region on the card (downloads or updates it first)"); _where(my)

    ro = sub.add_parser("routing", help="routing tiles for offline navigation (BRouter)")
    ros = ro.add_subparsers(dest="rcmd", required=True)
    ros.add_parser("list", help="the tiles your map region needs")
    rsy = ros.add_parser("sync", help="download them and put them on the card"); _where(rsy)

    se = sub.add_parser("search", help="offline place search (from OpenStreetMap)")
    ses = se.add_subparsers(dest="scmd", required=True)
    ses.add_parser("build", help="download the region's OpenStreetMap data and build the search file")
    sf = ses.add_parser("find", help="search the built file"); sf.add_argument("text", nargs="+")
    sf.add_argument("--near", help="lat,lon to rank by distance from"); sf.add_argument("--limit", type=int, default=8)
    ssy = ses.add_parser("sync", help="build it if needed and put it on the card"); _where(ssy)

    pl = sub.add_parser("places", help="the app's Home, Work, saved and recent places")
    pls = pl.add_subparsers(dest="pcmd", required=True)
    for name, text in (("show", "what the phone and the backup hold"), ("backup", "copy them to the workspace"),
                       ("restore", "put the workspace's copy back; the app merges it in")):
        pp = pls.add_parser(name, help=text); _where(pp)
        pp.add_argument("--workspace", help="a vehicle folder to use for this run (default: the open vehicle)")

    vo = sub.add_parser("voice", help="voice packs for navigation prompts")
    vos = vo.add_subparsers(dest="vcmd", required=True)
    vos.add_parser("list", help="the workspace's packs")
    vl = vos.add_parser("lines", help="a pack's lines, and which are recorded"); vl.add_argument("pack", help="its id")
    vn = vos.add_parser("new", help="start a pack"); vn.add_argument("name")
    vn.add_argument("--from-angie", action="store_true", help="start with copies of the built-in voice's lines")
    va = vos.add_parser("add", help="put a recording in a pack for one line")
    va.add_argument("pack"); va.add_argument("line", choices=list(voice.LINES)); va.add_argument("file")
    vi = vos.add_parser("install", help="add a pack someone shared (its folder or a .zip)"); vi.add_argument("path")
    ve = vos.add_parser("export", help="a pack as a .zip to share"); ve.add_argument("pack"); ve.add_argument("zip")
    vsy = vos.add_parser("sync", help="make the card hold the workspace's packs"); _where(vsy)
    for x in vos.choices.values():
        x.add_argument("--workspace", help="a vehicle folder to use for this run (default: the open vehicle)")

    ve = sub.add_parser("vehicle", help="vehicles: everything here is kept per vehicle")
    ves = ve.add_subparsers(dest="vecmd", required=True)
    ves.add_parser("list", help="the vehicles (* is open)")
    vn_ = ves.add_parser("new", help="a new vehicle"); vn_.add_argument("name"); vn_.add_argument("--folder")
    vad = ves.add_parser("add", help="a vehicle folder from elsewhere (another computer, a backup)"); vad.add_argument("folder")
    vu = ves.add_parser("use", help="open a vehicle"); vu.add_argument("id")
    vr = ves.add_parser("rename", help="rename a vehicle"); vr.add_argument("id"); vr.add_argument("name")

    pr = sub.add_parser("profile", help="the vehicle's look: title bar, background, splash, logos, car picture")
    prs = pr.add_subparsers(dest="prcmd", required=True)
    prs.add_parser("show", help="what the look is made of")
    for name, text in (("set", "use a picture for one place"), ("none", "show nothing in one place"),
                       ("builtin", "put the app's own picture back in one place")):
        x = prs.add_parser(name, help=text); x.add_argument("what", choices=list(profile.IMAGES))
        if name == "set":
            x.add_argument("picture")
    pb = prs.add_parser("badge", help="add a title-bar badge"); pb.add_argument("picture")
    po = prs.add_parser("options", help="title text and splash effect")
    po.add_argument("--title"); po.add_argument("--effect", choices=profile.EFFECTS); po.add_argument("--position", choices=profile.POSITIONS)
    psy = prs.add_parser("sync", help="put the look on the card"); _where(psy)
    for x in prs.choices.values():
        x.add_argument("--workspace", help="a vehicle folder to use for this run (default: the open vehicle)")

    rc = sub.add_parser("recordings", help="dashcam clips, marks and trips")
    rs = rc.add_subparsers(dest="rcmd", required=True)
    rp = rs.add_parser("pull"); _where(rp)
    rp.add_argument("--dest", required=True, help="folder on the Mac")
    rp.add_argument("--delete-synced", action="store_true", help="remove files from the card once safely copied")
    rp.add_argument("--force", action="store_true", help="copy again even if already pulled")
    rp.add_argument("--dry-run", action="store_true")

    pa = sub.add_parser("pull-all", help="copy everything on the phone (maps, music, recordings...) into a workspace")
    _where(pa)
    pa.add_argument("--workspace", help="a vehicle folder to use for this run (default: the open vehicle)")
    pa.add_argument("--only", help="comma list of: " + ", ".join(mirror.SECTIONS))
    pa.add_argument("--music-path", help="only music under this folder, e.g. 'Pet Shop Boys'")
    pa.add_argument("--music-match", help="only music whose path contains this text")
    pa.add_argument("--overwrite", action="store_true", help="replace local files that differ from the card's")
    pa.add_argument("--dry-run", action="store_true", help="show what would be copied")

    mu = sub.add_parser("music", help="music: put the workspace's music on the card")
    mus = mu.add_subparsers(dest="mucmd", required=True)
    mp_ = mus.add_parser("push", help="index the workspace's music, copy what the card lacks, then the index"); _where(mp_)
    mp_.add_argument("--workspace", help="a vehicle folder to use for this run (default: the open vehicle)")
    mp_.add_argument("--overwrite", action="store_true", help="replace card files whose size differs from the workspace's")
    mp_.add_argument("--delete-extra", action="store_true", help="remove music on the card that the workspace does not have")
    mp_.add_argument("--dry-run", action="store_true", help="show what would be copied")

    ad = sub.add_parser("adb", help="adb: find or install it, list phones, check the app, Wi-Fi")
    asub = ad.add_subparsers(dest="acmd", required=True)
    for name, text in (("status", "is adb available"), ("devices", "list phones"), ("forget", "clear a stored adb path")):
        asub.add_parser(name, help=text).add_argument("--adb-path", help="path to adb")
    su = asub.add_parser("setup", help="download Google's standalone platform-tools")
    su.add_argument("--accept-licence", action="store_true", help="you have read the Android SDK licence")
    su.add_argument("--adb-path", help=argparse.SUPPRESS)
    us = asub.add_parser("use", help="use an adb you already have"); us.add_argument("path")
    ap_ = asub.add_parser("app", help="is the app installed on a phone"); ap_.add_argument("--serial"); ap_.add_argument("--adb-path")
    ai = asub.add_parser("install", help="install or update the app from an .apk"); ai.add_argument("apk")
    ai.add_argument("--serial"); ai.add_argument("--adb-path")
    aw = asub.add_parser("wifi", help="adb over Wi-Fi"); aw.add_argument("state", choices=["on", "off"])
    aw.add_argument("--serial"); aw.add_argument("--usb-serial", help="when turning off: the phone's USB serial"); aw.add_argument("--adb-path")

    a = ap.parse_args(argv)
    {"index": cmd_index, "maps": cmd_maps, "music": cmd_music, "routing": cmd_routing, "search": cmd_search,
     "places": cmd_places, "voice": cmd_voice, "profile": cmd_profile, "vehicle": cmd_vehicle, "recordings": cmd_recordings, "adb": cmd_adb, "pull-all": cmd_pull_all}[a.cmd](a, ap)


if __name__ == "__main__":
    main()
