#!/usr/bin/env python3
"""One video from a camera test drive (Dashcam, Camera tab), each clip labelled with its setting, for comparing them.

    .venv/bin/python tools/make_camera_test_video.py RECORDINGS/tests/test_<time>.json [OUT.mp4]

RECORDINGS is what the desktop tool's Sync to PC writes to: the clips are in RECORDINGS/clips. Needs ffmpeg and Pillow.
"""
import json
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080


def font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def label_image(text, path):
    """A full-frame transparent picture with the setting's name in a dark box at the top left."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    f = font(44)
    box = draw.textbbox((0, 0), text, font=f)
    draw.rounded_rectangle((24, 24, box[2] + 64, box[3] + 60), 12, fill=(10, 12, 18, 200))
    draw.text((44, 40), text, font=f, fill=(255, 255, 255, 255))
    img.save(path)


def usable(manifest, clips_dir):
    """The clips that exist on this computer, with their labels, in filmed order."""
    out = []
    for c in manifest["clips"]:
        path = os.path.join(clips_dir, c["clip"])
        if os.path.exists(path):
            out.append((path, c["label"] + (" (refused: %s)" % c["refused"] if c.get("refused") else "")))
    return out


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    path = argv[1]
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    clips = usable(manifest, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "clips"))
    if not clips:
        raise SystemExit("none of this test's clips are on this computer yet: use Sync to PC first")
    out = argv[2] if len(argv) > 2 else os.path.splitext(path)[0] + "_review.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        cmd, parts = ["ffmpeg", "-hide_banner", "-v", "error", "-y"], []
        for i, (clip, label) in enumerate(clips):
            png = os.path.join(tmp, "%03d.png" % i)
            label_image("%s  (%d of %d)" % (label, i + 1, len(clips)), png)
            cmd += ["-i", clip, "-i", png]
            parts.append("[%d:v]fps=30,scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1[b%d];"
                         "[b%d][%d:v]overlay=0:0:format=auto,format=yuv420p[v%d];" % (2 * i, W, H, W, H, i, i, 2 * i + 1, i))
        joined = "".join("[v%d]" % i for i in range(len(clips)))
        cmd += ["-filter_complex", "".join(parts) + joined + "concat=n=%d:v=1:a=0[out]" % len(clips), "-map", "[out]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", out]
        subprocess.run(cmd, check=True)
    print("%s: %d clips" % (out, len(clips)))


if __name__ == "__main__":
    main(sys.argv)
