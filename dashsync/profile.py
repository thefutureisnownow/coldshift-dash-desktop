"""The vehicle's look, edited here and put on the card for the app (Profile.java).

A vehicle keeps it in <vehicle>/profile/, the same files the card gets at <card>/coldshift.dash/profile/:

    profile.json  {"version": 1, "title": "PEPPERMINT CRISP",
                   "badges": ["badge-1.png", ...],      title bar, left to right (84 px high, drawn at 42)
                   "background": "background.jpg",      behind every page, 1280 x 720
                   "wordmark": "wordmark.png",          Media page logo, while nothing plays
                   "car": "car.png",                    top-down, front up: Sensors' tyres and map marker
                   "splash": {"background": "splash.jpg", "logo": "logo.png",
                              "effect": "shine" | "glow" | "rise" | "none", "position": "left" | "centre"},
                   "theme": {"accent": "#2f7bff", "panel", "text", "subtext", "highlight"},
                   "pages": ["media", "maps", "track", "sensors", "dashcam", "log", "convoy"]}   the tab bar; Settings
                                                       last ("obd" and "tpms" from before mean "sensors")

An image set to "" is not shown. A new vehicle starts with a copy of the app's built-in profile
(assets/profile/, a copy of the car app's) and its own name as the title.
Each chosen image is fitted to its place: backgrounds cropped to fill 1280 x 720, badges scaled to the
title bar's height, logos fitted inside their spot, the car cropped and centred on a square.
"""
import io
import json
import math
import os
import shutil
import time

from . import layout, paths

FOLDER = "profile"
SIZE = 620                  # the car picture's square
FILL = 0.82                 # the car's share of it
BADGE_H = 84
EFFECTS = ("shine", "glow", "rise", "none")
POSITIONS = ("left", "centre")
# image -> (file stem, how it is fitted)
IMAGES = {
    "background": ("background", "cover"),
    "splash.background": ("splash", "cover"),
    "splash.logo": ("logo", (840, 480)),
    "wordmark": ("wordmark", (1230, 258)),
    "car": ("car", "car"),
}


# the app's colours (Theme.apply makes its other shades from these) and pages (Settings always shows)
THEME = {"accent": "#2f7bff", "panel": "#070e1b", "text": "#e8eef7", "subtext": "#93a9c8", "highlight": "#e3b341"}
THEME_NAMES = {"accent": "Accent (buttons, edges, the route)", "panel": "Panels", "text": "Text",
               "subtext": "Secondary text", "highlight": "Highlight (MARK, warnings)"}
PRESETS = {"Blue": "#2f7bff", "Red": "#e4002b", "Orange": "#ff7a1a", "Green": "#1fb866", "Teal": "#13b5c8",
           "Purple": "#8a5cff", "Silver": "#9aa7b8"}
PAGES = [("media", "Media"), ("maps", "Maps"), ("track", "Track"), ("sensors", "Sensors (OBD2, TPMS)"), ("dashcam", "Dashcam"), ("log", "Log book"), ("convoy", "Convoy")]


def builtin_dir():
    """The app's built-in profile, when running from the repository; None otherwise."""
    d = paths.app_assets("profile")
    return d if os.path.exists(os.path.join(d, "profile.json")) else None


def folder_of(vehicle):
    return os.path.join(vehicle, FOLDER)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(vehicle, prof):
    d = folder_of(vehicle)
    tmp = os.path.join(d, "profile.json.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prof, f, indent=1)
    os.replace(tmp, os.path.join(d, "profile.json"))


def init(vehicle, title=None):
    """Gives a vehicle a profile if it has none: a copy of the built-in one, with `title` (default: the
    vehicle's name in capitals). A car.png already there (from before profiles) is kept."""
    d = folder_of(vehicle)
    if os.path.exists(os.path.join(d, "profile.json")):
        return
    os.makedirs(d, exist_ok=True)
    src = builtin_dir()
    prof = _read(os.path.join(src, "profile.json")) if src else {"version": 1, "badges": [], "splash": {}}
    for f in os.listdir(src) if src else []:
        if f != "profile.json" and not os.path.exists(os.path.join(d, f)):
            shutil.copyfile(os.path.join(src, f), os.path.join(d, f))
    if title is None:
        try:
            title = _read(os.path.join(vehicle, "vehicle.json")).get("name", "").upper()
        except (OSError, ValueError):
            title = ""
    if title and src and title.upper() != prof.get("title", "").upper():
        prof["title"] = title
    _save(vehicle, prof)


def load(vehicle):
    """The vehicle's profile.json (made from the built-in one first if it has none)."""
    init(vehicle)
    prof = _read(os.path.join(folder_of(vehicle), "profile.json"))
    prof.setdefault("badges", [])
    prof.setdefault("splash", {})
    prof["splash"].setdefault("effect", "shine")
    prof["splash"].setdefault("position", "left")
    return prof


def _get(prof, key):
    if key.startswith("splash."):
        return prof["splash"].get(key[7:], "")
    return prof.get(key, "")


def _put(prof, key, value):
    if key.startswith("splash."):
        prof["splash"][key[7:]] = value
    else:
        prof[key] = value


def image(vehicle, key):
    """The file for one of IMAGES, or None when it is not shown."""
    name = _get(load(vehicle), key)
    p = os.path.join(folder_of(vehicle), name) if name else None
    return p if p and os.path.exists(p) else None


def is_custom(vehicle, key):
    """Whether the picture in one of IMAGES is the vehicle's own (not the built-in one): replacing it with
    the built-in one, or none, deletes it."""
    mine = image(vehicle, key)
    if not mine:
        return False
    src = builtin_dir()
    theirs = os.path.join(src, os.path.basename(mine)) if src else None
    if not theirs or not os.path.exists(theirs) or os.path.getsize(theirs) != os.path.getsize(mine):
        return True
    with open(mine, "rb") as a, open(theirs, "rb") as b:
        return a.read() != b.read()


def badges(vehicle):
    d = folder_of(vehicle)
    return [os.path.join(d, b) for b in load(vehicle)["badges"] if os.path.exists(os.path.join(d, b))]


def current_car(vehicle):
    """The car picture the app shows for a vehicle (for icons), else the built-in one."""
    mine = image(vehicle, "car") if vehicle and os.path.isdir(vehicle) else None
    if mine:
        return mine
    b = builtin_dir()
    return os.path.join(b, "car.png") if b else None


# ---- fitting images ----

def _open(src):
    from PIL import Image
    try:
        im = Image.open(src)
        im.load()
        return im
    except Exception:
        raise ValueError("%s is not a picture this tool can read" % os.path.basename(src))


def _transparent(im):
    return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info


def cover(src, w=1280, h=720):
    """Cropped to fill w x h (the middle kept)."""
    from PIL import Image, ImageOps
    return ImageOps.fit(_open(src).convert("RGB"), (w, h), Image.LANCZOS)


def fit(src, w, h):
    """Trimmed to what is not transparent and fitted inside w x h, its shape kept."""
    from PIL import Image
    im = _open(src).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError("the picture is fully transparent")
    im = im.crop(box)
    k = min(w / im.width, h / im.height, 1.0)          # never enlarged: the app scales it when drawing
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def badge(src):
    """Scaled to the title bar's height (doubled), no wider than 8 times that (a long model name)."""
    from PIL import Image
    im = _open(src).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError("the picture is fully transparent")
    im = im.crop(box)
    k = BADGE_H / im.height
    if im.width * k > BADGE_H * 8:
        raise ValueError("that is very wide for a badge (the title bar is 42 px high); crop it first")
    return im.resize((max(1, round(im.width * k)), BADGE_H), Image.LANCZOS)


def prepare_car(src):
    """The car as the app wants it; raises ValueError when it cannot be one."""
    from PIL import Image
    im = _open(src)
    if not _transparent(im):
        raise ValueError("the car picture needs a transparent background (a PNG with the car cut out)")
    im = im.convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    if not box:
        raise ValueError("the picture is fully transparent")
    car = im.crop(box)
    if car.width >= car.height * 1.2:
        raise ValueError("the car looks sideways: it should be seen from above with the front pointing up")
    scale = SIZE * FILL / max(car.width, car.height)
    car = car.resize((max(1, round(car.width * scale)), max(1, round(car.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(car, ((SIZE - car.width) // 2, (SIZE - car.height) // 2), car)
    return out


def _store(vehicle, stem, im, jpeg=False):
    """Saves under a new name (so the card copy is always replaced), returning the file name."""
    d = folder_of(vehicle)
    name = "%s-%d.%s" % (stem, int(time.time() * 1000) % 10 ** 9, "jpg" if jpeg else "png")
    path = os.path.join(d, name)
    if jpeg:
        im.save(path, "JPEG", quality=88, optimize=True)
    else:
        im.save(path, "PNG", optimize=True)
    return name


def _unused(vehicle, prof):
    """Removes files in the profile folder that profile.json no longer names."""
    used = {_get(prof, k) for k in IMAGES} | set(prof["badges"]) | {"profile.json"}
    d = folder_of(vehicle)
    for f in os.listdir(d):
        if f not in used and not f.endswith(".part"):
            os.remove(os.path.join(d, f))


def set_image(vehicle, key, src):
    stem, how = IMAGES[key]
    if how == "cover":
        im, jpeg = cover(src), True
    elif how == "car":
        im, jpeg = prepare_car(src), False
    else:
        im, jpeg = fit(src, *how), False
    prof = load(vehicle)
    _put(prof, key, _store(vehicle, stem, im, jpeg))
    _save(vehicle, prof)
    _unused(vehicle, prof)


def clear_image(vehicle, key):
    """Not shown any more."""
    prof = load(vehicle)
    _put(prof, key, "")
    _save(vehicle, prof)
    _unused(vehicle, prof)


def builtin_image(vehicle, key):
    """Back to the app's built-in picture for this place."""
    src = builtin_dir()
    name = _get(_read(os.path.join(src, "profile.json")), key) if src else ""
    if not name:
        return clear_image(vehicle, key)
    prof = load(vehicle)
    shutil.copyfile(os.path.join(src, name), os.path.join(folder_of(vehicle), name))
    _put(prof, key, name)
    _save(vehicle, prof)
    _unused(vehicle, prof)


def add_badge(vehicle, src):
    prof = load(vehicle)
    prof["badges"].append(_store(vehicle, "badge", badge(src)))
    _save(vehicle, prof)


def remove_badge(vehicle, i):
    prof = load(vehicle)
    del prof["badges"][i]
    _save(vehicle, prof)
    _unused(vehicle, prof)


def move_badge(vehicle, i, delta):
    prof = load(vehicle)
    j = i + delta
    if 0 <= j < len(prof["badges"]):
        prof["badges"][i], prof["badges"][j] = prof["badges"][j], prof["badges"][i]
        _save(vehicle, prof)


def theme(vehicle):
    """The vehicle's five colours (the defaults where it has none)."""
    return dict(THEME, **{k: v for k, v in load(vehicle).get("theme", {}).items() if k in THEME})


def set_theme(vehicle, reset=False, **colours):
    """Sets some of the colours ("#rrggbb"); reset=True goes back to the defaults."""
    import re
    prof = load(vehicle)
    t = {} if reset else dict(prof.get("theme", {}))
    for k, v in colours.items():
        if k not in THEME:
            raise ValueError("no colour called %s" % k)
        if not re.match(r"^#[0-9a-fA-F]{6}$", v or ""):
            raise ValueError("colours are written #rrggbb, e.g. #2f7bff")
        t[k] = v.lower()
    t = {k: v for k, v in t.items() if v != THEME[k]}           # only what differs from the default
    if t:
        prof["theme"] = t
    else:
        prof.pop("theme", None)
    _save(vehicle, prof)


def pages(vehicle):
    """The pages the app's tab bar shows, in order (Settings comes after them)."""
    got = load(vehicle).get("pages")
    names = [p for p, _ in PAGES]
    if not isinstance(got, list):
        return names
    out = []
    for p in got:
        p = "sensors" if p in ("obd", "tpms") else p          # one tab since 1 Nov
        if p in names and p not in out:
            out.append(p)
    return out


def set_pages(vehicle, shown):
    names = [p for p, _ in PAGES]
    bad = [p for p in shown if p not in names]
    if bad:
        raise ValueError("no page called %s" % ", ".join(bad))
    prof = load(vehicle)
    prof["pages"] = [p for i, p in enumerate(shown) if p not in shown[:i]]
    _save(vehicle, prof)


def set_options(vehicle, title=None, effect=None, position=None):
    prof = load(vehicle)
    if title is not None:
        prof["title"] = title.strip()
    if effect is not None:
        if effect not in EFFECTS:
            raise ValueError("no splash effect %r" % effect)
        prof["splash"]["effect"] = effect
    if position is not None:
        if position not in POSITIONS:
            raise ValueError("no logo position %r" % position)
        prof["splash"]["position"] = position
    _save(vehicle, prof)


# ---- the map marker, as the app draws it ----

def marker(src, height=72):
    """The map marker the app draws from a car picture (PIL image): the solid body, `height` px long,
    a white outline and a soft shadow (MapHost.carIcon)."""
    from PIL import Image, ImageFilter
    im = _open(src).convert("RGBA")
    box = im.getchannel("A").point(lambda v: 255 if v > 200 else 0).getbbox() or (0, 0, im.width, im.height)
    body = im.crop(box)
    w = max(1, round(height * body.width / body.height))
    body = body.resize((w, height), Image.LANCZOS)
    pad = 9
    out = Image.new("RGBA", (w + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    alpha = body.getchannel("A")
    shadow = Image.new("RGBA", body.size, (0, 0, 0, 204))
    shadow.putalpha(alpha.point(lambda v: v * 204 // 255))
    blurred = Image.new("RGBA", out.size, (0, 0, 0, 0))
    blurred.paste(shadow, (pad, pad + 2), shadow)
    out = Image.alpha_composite(out, blurred.filter(ImageFilter.GaussianBlur(2.5)))
    white = Image.new("RGBA", body.size, (255, 255, 255, 255))
    white.putalpha(alpha)
    for i in range(16):
        a = math.pi * i / 8
        out.alpha_composite(white, (pad + round(2.5 * math.cos(a)), pad + round(2.5 * math.sin(a))))
    out.alpha_composite(body, (pad, pad))
    return out


def png_bytes(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ---- the card ----

def sync(target, vehicle, dry_run=False):
    """Makes <card>/coldshift.dash/profile/ hold exactly the vehicle's profile (profile.json last) and
    tells the app. Returns {"changed", "files", "app"}; with dry_run only counts the files it would change."""
    init(vehicle)
    d = folder_of(vehicle)
    mine = {f: os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if not f.endswith(".part")}
    on_card = {e.name: e.size for e in target.listdir(layout.PROFILE_DIR)}
    out = {"changed": False, "files": 0, "app": None}
    for f in sorted(mine, key=lambda f: f == "profile.json"):
        if on_card.get(f) != mine[f]:
            if not dry_run:
                target.push(os.path.join(d, f), layout.PROFILE_DIR + "/" + f)
            out["files"] += 1
    for f in set(on_card) - set(mine):
        if not dry_run:
            target.remove(layout.PROFILE_DIR + "/" + f)
        out["files"] += 1
    out["changed"] = out["files"] > 0
    if out["changed"] and not dry_run:
        out["app"] = target.notify_synced(["profile"])
    return out
