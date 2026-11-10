import json
import os
import shutil
import tempfile
import unittest

from PIL import Image, ImageDraw

from dashsync import profile
from dashsync.transport import FolderTarget


def picture(path, size, box=None, color=(220, 30, 40, 255), mode="RGBA"):
    im = Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else (90, 90, 90))
    if box:
        ImageDraw.Draw(im).rounded_rectangle(box, 20, fill=color if mode == "RGBA" else color[:3])
    im.save(path)
    return path


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.v = os.path.join(self.tmp, "vehicle")
        os.makedirs(self.v)
        with open(os.path.join(self.v, "vehicle.json"), "w") as f:
            json.dump({"name": "Lemon Drizzle"}, f)
        self.car = picture(os.path.join(self.tmp, "car.png"), (400, 300), (160, 40, 250, 260))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_new_vehicle_starts_from_the_builtin_look_with_its_own_name(self):
        if not profile.builtin_dir():
            self.skipTest("not running from the repository")
        prof = profile.load(self.v)
        self.assertEqual(prof["title"], "LEMON DRIZZLE")
        self.assertGreaterEqual(len(profile.badges(self.v)), 1)
        self.assertTrue(profile.image(self.v, "splash.logo"))

    def test_images_are_fitted_to_their_place(self):
        profile.set_image(self.v, "background", picture(os.path.join(self.tmp, "bg.jpg"), (2000, 900), mode="RGB"))
        self.assertEqual(Image.open(profile.image(self.v, "background")).size, (1280, 720))
        profile.set_image(self.v, "splash.logo", picture(os.path.join(self.tmp, "logo.png"), (3000, 1000), (100, 100, 2900, 900)))
        self.assertLessEqual(Image.open(profile.image(self.v, "splash.logo")).size[0], 840)
        car = Image.open(profile.set_image(self.v, "car", self.car) or profile.image(self.v, "car"))
        self.assertEqual(car.size, (profile.SIZE, profile.SIZE))
        box = car.getchannel("A").getbbox()
        self.assertAlmostEqual(box[3] - box[1], profile.SIZE * profile.FILL, delta=2)

    def test_badges_add_move_remove_and_unused_files_go(self):
        profile.load(self.v)
        n = len(profile.badges(self.v))
        profile.add_badge(self.v, picture(os.path.join(self.tmp, "b.png"), (300, 200), (10, 10, 290, 190)))
        b = profile.badges(self.v)
        self.assertEqual(len(b), n + 1)
        self.assertEqual(Image.open(b[-1]).height, profile.BADGE_H)
        if n:
            profile.move_badge(self.v, n, -1)
            self.assertEqual(profile.badges(self.v)[n - 1], b[-1])
            profile.remove_badge(self.v, n - 1)
        else:
            profile.remove_badge(self.v, 0)
        self.assertFalse(os.path.exists(b[-1]))
        self.assertEqual(len(profile.badges(self.v)), n)

    def test_none_and_builtin(self):
        profile.clear_image(self.v, "wordmark")
        self.assertIsNone(profile.image(self.v, "wordmark"))
        self.assertEqual(profile.load(self.v)["wordmark"], "")
        if profile.builtin_dir():
            profile.builtin_image(self.v, "wordmark")
            self.assertTrue(profile.image(self.v, "wordmark"))

    def test_pictures_it_cannot_use(self):
        flat = picture(os.path.join(self.tmp, "flat.jpg"), (100, 200), mode="RGB")
        side = picture(os.path.join(self.tmp, "side.png"), (300, 100), (0, 0, 299, 99))
        with self.assertRaises(ValueError):
            profile.prepare_car(flat)
        with self.assertRaises(ValueError):
            profile.prepare_car(side)
        with self.assertRaises(ValueError):
            profile.add_badge(self.v, picture(os.path.join(self.tmp, "wide.png"), (2000, 50), (0, 0, 1999, 49)))
        with self.assertRaises(ValueError):
            profile.set_options(self.v, effect="explode")

    def test_marker_is_the_body_at_72_px_with_an_outline(self):
        profile.set_image(self.v, "car", self.car)
        m = profile.marker(profile.image(self.v, "car"))
        self.assertEqual(m.height, 72 + 18)
        self.assertEqual(m.getpixel((m.width // 2, 9 + 36))[:3], (220, 30, 40))
        self.assertEqual(m.getpixel((m.width // 2, 7))[:3], (255, 255, 255))

    def test_theme_and_pages(self):
        self.assertEqual(profile.theme(self.v), profile.THEME)
        profile.set_theme(self.v, accent="#E4002B", text=profile.THEME["text"])
        self.assertEqual(profile.load(self.v)["theme"], {"accent": "#e4002b"})     # only what differs is kept
        with self.assertRaises(ValueError):
            profile.set_theme(self.v, accent="red")
        with self.assertRaises(ValueError):
            profile.set_theme(self.v, glow="#ffffff")
        profile.set_theme(self.v, reset=True)
        self.assertNotIn("theme", profile.load(self.v))
        self.assertEqual(profile.pages(self.v), [p for p, _ in profile.PAGES])
        profile.set_pages(self.v, ["maps", "media", "maps"])
        self.assertEqual(profile.pages(self.v), ["maps", "media"])
        with self.assertRaises(ValueError):
            profile.set_pages(self.v, ["settings"])                                 # always shown; not a choice

    def test_sync_mirrors_the_profile_with_its_json_last(self):
        os.makedirs(os.path.join(self.tmp, "card", "coldshift.dash", "profile"))
        with open(os.path.join(self.tmp, "card", "coldshift.dash", "profile", "old.png"), "w") as f:
            f.write("x")
        card = FolderTarget(os.path.join(self.tmp, "card"))
        pushed = []
        orig = card.push
        card.push = lambda local, rel: (pushed.append(os.path.basename(rel)), orig(local, rel))
        self.assertTrue(profile.sync(card, self.v)["changed"])
        self.assertEqual(pushed[-1], "profile.json")
        on_card = sorted(os.listdir(os.path.join(self.tmp, "card", "coldshift.dash", "profile")))
        self.assertEqual(on_card, sorted(os.listdir(profile.folder_of(self.v))))
        self.assertFalse(profile.sync(card, self.v)["changed"])


if __name__ == "__main__":
    unittest.main()
