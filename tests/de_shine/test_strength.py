# Headless: mask peak == strength/100*255 (linear, what GIMP composites with), and flash on a spots image.
# Writes flattened PNGs to $DS_OUT (default <tmp>/ds_gimp) for external measuring.
import os, tempfile
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
pdb = Gimp.get_pdb()
OUT = os.environ.get("DS_OUT", os.path.join(tempfile.gettempdir(), "ds_gimp"))
os.makedirs(OUT, exist_ok=True)
FACE = os.environ.get("DS_FACE", "tests/data/astronaut.jpg")
FAILS = []


def need(cond, what):
    print("DS_STRENGTH %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def spots():
    """Skin-coloured field with bright specular dots, no face."""
    img = Gimp.Image.new(400, 300, Gimp.ImageBaseType.RGB)
    lay = Gimp.Layer.new(img, "spots", 400, 300, Gimp.ImageType.RGB_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(lay, None, 0)
    raw = bytearray(400 * 300 * 3)
    for y in range(300):
        for x in range(400):
            i = (y * 400 + x) * 3
            raw[i:i + 3] = bytes((205, 150, 125))
            for cx, cy in ((100, 100), (200, 150), (300, 200), (150, 230)):
                d2 = (x - cx) ** 2 + (y - cy) ** 2
                if d2 < 400:
                    v = int(255 - d2 * 0.12)
                    raw[i:i + 3] = bytes((v, v, max(0, v - 10)))
    lay.get_buffer().set(Gegl.Rectangle.new(0, 0, 400, 300), "R'G'B' u8", bytes(raw))
    return img


def run(source, strength, flash, tag):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(source)) if isinstance(source, str) else source()
    lay = img.get_layers()[0]
    proc = pdb.lookup_procedure("python-fu-de-shine")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", [lay])
    cfg.set_property("strength", float(strength))
    cfg.set_property("flash", flash)
    if tag == "spots":
        cfg.set_property("only-face", False)
    res = proc.run(cfg)
    st = res.index(0).value_nick
    m = img.get_layers()[0].get_mask()
    if m is None:
        need(False, "%s %d: %s, no mask" % (tag, strength, st))
        img.delete()
        return
    w, h = m.get_width(), m.get_height()
    r = Gegl.Rectangle.new(0, 0, w, h)
    lin = max(bytes(m.get_buffer().get(r, 1.0, "Y u8", Gegl.AbyssPolicy.NONE)))
    per = max(bytes(m.get_buffer().get(r, 1.0, "Y' u8", Gegl.AbyssPolicy.NONE)))
    want = int(round(strength / 100.0 * 255))
    print("DS_STRENGTH %s strength %d flash %s status %s mask_peak_linear %d (want %d) perceptual %d" % (
        tag, strength, flash, st, lin, want, per), flush=True)
    need(st == "success", "%s %d%s success" % (tag, strength, "F" if flash else ""))
    need(abs(lin - want) <= 1, "%s %d%s mask peak follows strength" % (tag, strength, "F" if flash else ""))
    img.flatten()
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path("%s/%s_%d%s.png" % (OUT, tag, strength, "F" if flash else "")), None)
    img.delete()


for s in (25, 50, 75, 100):
    run(FACE, s, False, "selfie")
run(FACE, 100, True, "selfie")
run(spots, 100, False, "spots")
run(spots, 100, True, "spots")
print("DS_STRENGTH done", flush=True)
print("DS_STRENGTH OK" if not FAILS else "DS_STRENGTH FAIL %d" % len(FAILS), flush=True)
