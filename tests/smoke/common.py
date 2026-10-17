import math, os, random
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio

Gegl.init(None)
pdb = Gimp.get_pdb()
NAME = os.environ.get("SMOKE_NAME", "smoke")


def die(msg):
    print("SMOKE FAIL %s %s" % (NAME, msg), flush=True)
    raise SystemExit(1)


def ok(msg):
    print("SMOKE %s %s" % (NAME, msg), flush=True)


def portrait(w=360, h=480):
    rnd = random.Random(7)
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "背景", w, h, Gimp.ImageType.RGB_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    raw = bytearray(w * h * 3)
    cx, cy, ax, ay = w * 0.5, h * 0.45, w * 0.3, h * 0.33
    for y in range(h):
        for x in range(w):
            n = rnd.randint(-6, 6)
            if ((x - cx) / ax) ** 2 + ((y - cy) / ay) ** 2 <= 1.0:
                r, g, b = 214, 168, 140
                if (x - cx * 1.1) ** 2 + (y - cy * 0.8) ** 2 < 400:
                    r, g, b = 250, 238, 228
            elif y > h * 0.8:
                r, g, b = 60, 110, 70
            else:
                r, g, b = 120 + y // 8, 90, 60
            i = (y * w + x) * 3
            raw[i], raw[i + 1], raw[i + 2] = [max(0, min(255, c + n)) for c in (r, g, b)]
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' u8", bytes(raw))
    return img, lay


def save_png(img, path):
    d = img.duplicate()
    d.flatten()
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, d, Gio.File.new_for_path(path), None)
    d.delete()


def call(name, image=None, layers=None, **kw):
    proc = pdb.lookup_procedure(name)
    if proc is None:
        die("not registered: " + name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    if image is not None:
        cfg.set_property("image", image)
        cfg.set_core_object_array("drawables", layers or image.get_selected_layers())
    for k, v in kw.items():
        cfg.set_property(k.replace("_", "-"), v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        die("%s returned %s %s" % (name, res.index(0), res.index(1) if res.length() > 1 else ""))
    return res


def tree(image):
    out = []

    def walk(items, d):
        for l in items:
            mask = None if l.is_group() else l.get_mask()
            out.append((d, l.get_name(), "group" if l.is_group() else "layer", l.get_mode().value_nick,
                        round(l.get_opacity()), bool(l.get_visible()), mask is not None))
            if l.is_group():
                walk(l.get_children(), d + 1)

    walk(image.get_layers(), 0)
    return out


def show(image):
    for t in tree(image):
        print("SMOKE %s TREE %s" % (NAME, t), flush=True)


def expect_tree(image, want):
    got = tree(image)
    show(image)
    if got != want:
        die("layer tree differs, want %s" % (want,))
    ok("tree ok (%d items)" % len(got))


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    return bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
