"""The desktop app's icon, from the dash logo (packaging/icons/dash-logo-1024.png): icon.icns (macOS), icon.ico
(Windows) and icon-512.png (the window's icon everywhere, and the AppImage's). Run again when the logo changes:

    .venv/bin/python packaging/make_icons.py

The logo is a black-edged mark on a transparent background, which disappears on a dark Dock or taskbar,
so it sits on a light tile: for macOS a rounded square inside the margin Apple's grid leaves (824 of
1024 px, with a soft shadow), for Windows and Linux the same tile filling the picture."""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "icons", "dash-logo-1024.png")
OUT = os.path.join(HERE, "icons")
TOP, BOTTOM = (255, 255, 255), (218, 225, 235)      # the tile, lit from above


def tile(size, radius):
    """A size x size rounded square with the logo on it, on a transparent background."""
    big = size * 2                                   # drawn at twice the size: smooth corners
    grad = Image.new("RGB", (1, big))
    for y in range(big):
        k = y / (big - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(TOP, BOTTOM)))
    face = grad.resize((big, big)).convert("RGBA")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius * 2, fill=255)
    face.putalpha(mask)
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    k = big * 0.76 / max(logo.size)
    logo = logo.resize((round(logo.width * k), round(logo.height * k)), Image.LANCZOS)
    face.alpha_composite(logo, ((big - logo.width) // 2, (big - logo.height) // 2))
    return face.resize((size, size), Image.LANCZOS)


def mac():
    """The tile on Apple's grid: 824 px in a 1024 px picture, with the shadow its icons have."""
    out = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((100, 112, 924, 936), 185, fill=(0, 0, 0, 90))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    out.alpha_composite(tile(824, 185), (100, 100))
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    mac().save(os.path.join(OUT, "icon.icns"))
    full = tile(1024, 200)
    full.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-512.png"))
    full.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "icon.ico"),
                                                sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("written:", ", ".join(sorted(os.listdir(OUT))))
