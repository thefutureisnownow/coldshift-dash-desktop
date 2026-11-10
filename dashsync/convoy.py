"""Convoys from the computer: the convoy server's address, starting a convoy or reading a link or code,
and putting it on the phone (the relay is github.com/thefutureisnownow/coldshift-dash-convoy; PROTOCOL.md there).

There is no default host: each is someone's own. A host may need a start key to start a convoy (never to
join one); it is kept here per host, and goes to the phone with the host, never into the app itself.

The phone reads <card>/coldshift.dash/convoy.json:
    {"server": "https://host", "start_key"?: the host's, "name": the vehicle's name,
     "join"?: {"token", "name", "password"}, "sent": when}
It takes the host from a sync it has not seen ("sent"), so the latest change, here or on the phone, wins,
and joins a "join" it has not joined before (Convoy.java). Links are the server's watch page,
<server>/c/<token> (the QR code holds the same): opened in a browser they follow the convoy; given to this
tool, with the password if the convoy has one, they join it.
"""
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request

from . import layout, paths

FILE = layout.APP_DIR + "/convoy.json"
TIMEOUT = 10
# Cloudflare's browser check (on by default for a zone) turns away Python's own "Python-urllib" with 403
# (error 1010): a relay on Cloudflare would refuse this tool without a name of its own
HEADERS = {"User-Agent": "coldshift-dash-desktop (+https://dash.coldshift.racing)"}


class StartKeyNeeded(ValueError):
    """The host wants its start key to start a convoy: none was given, or a wrong one."""


def server():
    """The convoy server's address, as set in this tool (all vehicles share it); "" until one is."""
    return paths.global_config().get("convoy_server") or ""


def start_key(base):
    """The start key kept for that host ("" for none)."""
    return (paths.global_config().get("convoy_start_keys") or {}).get(base.rstrip("/"), "")


def set_start_key(base, key):
    """Keeps the host's start key (or with "", forgets it)."""
    g = paths.global_config()
    keys = dict(g.get("convoy_start_keys") or {})
    if key.strip():
        keys[base.rstrip("/")] = key.strip()
    else:
        keys.pop(base.rstrip("/"), None)
    g["convoy_start_keys"] = keys
    paths.save_global(g)


def set_server(url):
    url = url.strip().rstrip("/")
    if url and not re.match(r"^https?://[^/\s]+$", url):
        raise ValueError("give the server as http://host:port or https://host")
    g = paths.global_config()
    g["convoy_server"] = url
    paths.save_global(g)
    return url


def _call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers=dict(HEADERS, **({"Content-Type": "application/json"} if body is not None else {})))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            reply = json.loads(e.read())
        except ValueError:
            reply = {}
        msg = reply.get("error") or "the convoy server said %d" % e.code
        raise (StartKeyNeeded if reply.get("code") == "start_key" else ValueError)(msg)
    except (urllib.error.URLError, OSError) as e:
        raise ValueError("cannot reach the convoy server at %s (%s)" % (base, getattr(e, "reason", e)))


def check(base):
    """Raises ValueError unless a convoy server answers at that address."""
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/health", headers=HEADERS), timeout=TIMEOUT) as r:
            if r.read().strip() != b"ok":
                raise ValueError("%s answers, but is not a convoy server" % base)
    except (urllib.error.URLError, OSError) as e:
        raise ValueError("cannot reach the convoy server at %s (%s)" % (base, getattr(e, "reason", e)))


def start(base, name, password=""):
    """A new convoy: {"token", "name", "link", "password": bool, "key" (the starter's: ends it for everyone)}.
    Sends the host's start key if one is kept; StartKeyNeeded if the host wants one (or another)."""
    body = {"name": name.strip() or "Convoy", "password": password}
    if start_key(base):
        body["start_key"] = start_key(base)
    return _call(base, "POST", "/api/convoys", body)


def end(base, token, key):
    """Ends the convoy for everyone in it (the key is the one its starter was given)."""
    return _call(base, "POST", "/api/convoys/%s/end" % token, {"key": key})


def qr_png(base, token, scale=6):
    """The convoy's link as a QR code (PNG bytes), drawn by the server."""
    try:
        with urllib.request.urlopen(urllib.request.Request("%s/c/%s/qr.png?scale=%d" % (base, token, scale), headers=HEADERS),
                                    timeout=TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise ValueError("cannot get the QR code from %s (%s)" % (base, getattr(e, "reason", e)))


def link(base, token):
    return "%s/c/%s" % (base, token)


def read_link(text):
    """A convoy's link (<server>/c/<token>): (server, token). The link carries its server."""
    m = re.match(r"^(https?://[^/\s]+)/c/([A-Za-z0-9_-]{20,64})/?$", text.strip())
    if not m:
        raise ValueError("that is not a convoy link (it looks like https://…/c/…)")
    return m.group(1), m.group(2)


def vehicle_name(vehicle):
    try:
        with open(os.path.join(vehicle, paths.VEHICLE_FILE), encoding="utf-8") as f:
            return json.load(f).get("name", "")
    except (OSError, ValueError):
        return ""


def to_card(target, vehicle, base, join=None):
    """Puts the server's address (and a convoy to join) on the phone. Returns the app's reply."""
    # "sent": each sync is new to the phone, so it takes this host even if the same was sent before
    data = {"server": base, "name": vehicle_name(vehicle), "sent": str(int(time.time() * 1000))}
    if start_key(base):
        data["start_key"] = start_key(base)               # so the phone can start convoys there too
    if join:
        data["join"] = {"token": join["token"], "name": join.get("name", ""), "password": join.get("password", "")}
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        target.push(path, FILE)
    finally:
        os.remove(path)
    return target.notify_synced(["convoy"])
