"""Builds three made-up demo cars for screenshots and videos, with no car maker's name or badge anywhere:
Peppermint Crisp (teal), Lemon Drizzle (yellow) and Granadilla (purple). Each becomes a vehicle folder the desktop
tool can put on a phone (profile.sync), in OUT/<id>/ with vehicle.json and profile/.

    python3 tools/make_demo_profiles.py FONTS_DIR [OUT]      (OUT: ../demo-vehicles)

Sources: art/demo-profiles/demo-cars-key-1.png: the three
cars from above on a flat magenta backdrop, keyed out here. The background, splash and logo are the built-in look's
(assets/profile). FONTS_DIR holds Roboto-BoldItalic.ttf from the phone (adb pull
/system/fonts/Roboto-BoldItalic.ttf), for each car's name as its wordmark.
"""
import json
import os
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = ROOT
sys.path.insert(0, DESKTOP)
from dashsync import profile  # noqa: E402

SHEET = os.path.join(ROOT, "art", "demo-profiles", "demo-cars-key-1.png")
BUILTIN = os.path.join(DESKTOP, "assets", "profile")
CARS = [  # left to right on the sheet
    {"id": "peppermint-crisp", "name": "Peppermint Crisp", "accent": "#13b5c8"},
    {"id": "lemon-drizzle", "name": "Lemon Drizzle", "accent": "#f2c200"},
    {"id": "granadilla", "name": "Granadilla", "accent": "#8a5cff"},
]


def key_out(im):
    """The magenta backdrop made transparent, and its pink spill taken off the edges."""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            d = ((255 - r) ** 2 + g ** 2 + (255 - b) ** 2) ** 0.5     # distance from #ff00ff
            a = 0 if d < 70 else 255 if d > 150 else int((d - 70) / 80 * 255)
            if a < 255:
                spill = min(r, b) - g
                if spill > 0:
                    r, b = r - spill, b - spill
            px[x, y] = (r, g, b, a)
    return im


def split(im, n):
    """The n cars, left to right: each one's own box within its column."""
    w, h = im.size
    out = []
    for i in range(n):
        col = im.crop((i * w // n, 0, (i + 1) * w // n, h))
        out.append(col.crop(col.getchannel("A").getbbox()))
    return out


def wordmark(fonts, name, accent):
    """The car's name in Roboto bold italic: the first word white, the rest in its colour."""
    font = ImageFont.truetype(os.path.join(fonts, "Roboto-BoldItalic.ttf"), 200)
    first, _, rest = name.upper().partition(" ")
    rest = (" " + rest) if rest else ""
    wa = font.getlength(first)
    im = Image.new("RGBA", (int(wa + font.getlength(rest)) + 80, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.text((20, 230), first, font=font, fill=(255, 255, 255, 255), anchor="ls")
    colour = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
    d.text((20 + wa, 230), rest, font=font, fill=colour if rest else (255, 255, 255, 255), anchor="ls")
    return im.crop(im.getchannel("A").getbbox())


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    fonts = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) == 3 else os.path.join(os.path.dirname(ROOT), "demo-vehicles")
    cars = split(key_out(Image.open(SHEET)), len(CARS))
    for car, picture in zip(CARS, cars):
        folder = os.path.join(out, car["id"])
        prof = os.path.join(folder, "profile")
        shutil.rmtree(prof, ignore_errors=True)
        os.makedirs(prof)
        for f in ("background.jpg", "splash.jpg", "logo.png", "badge-1.png"):
            shutil.copy(os.path.join(BUILTIN, f), prof)
        raw = os.path.join(prof, "car-source.png")
        picture.save(raw)
        profile.prepare_car(raw).save(os.path.join(prof, "car.png"), optimize=True)
        os.remove(raw)
        wordmark(fonts, car["name"], car["accent"]).save(os.path.join(prof, "wordmark.png"), optimize=True)
        with open(os.path.join(prof, "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "title": car["name"].upper(), "badges": ["badge-1.png"],
                       "background": "background.jpg", "wordmark": "wordmark.png", "car": "car.png",
                       "splash": {"background": "splash.jpg", "logo": "logo.png", "effect": "shine", "position": "left"},
                       "theme": {"accent": car["accent"]}}, f, indent=1)
        with open(os.path.join(folder, "vehicle.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "id": car["id"], "name": car["name"]}, f, indent=1)
        print(car["name"], "->", folder)


if __name__ == "__main__":
    main()
