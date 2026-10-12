# Headless: mask peak == strength/100*255 (linear, what GIMP composites with), and flash on a spots image.
# Writes flattened PNGs to /tmp/ds_gimp/ for external measuring.
import os
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
pdb = Gimp.get_pdb()
OUT = "/tmp/ds_gimp"
os.makedirs(OUT, exist_ok=True)


def run(path, strength, flash, tag):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    lay = img.get_layers()[0]
    proc = pdb.lookup_procedure("python-fu-de-shine")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [lay])
    else:
        cfg.set_property("drawables", [lay])
    cfg.set_property("strength", float(strength))
    cfg.set_property("flash", flash)
    res = proc.run(cfg)
    st = str(res.index(0))
    m = img.get_layers()[0].get_mask()
    w, h = m.get_width(), m.get_height()
    r = Gegl.Rectangle.new(0, 0, w, h)
    lin = max(bytes(m.get_buffer().get(r, 1.0, "Y u8", Gegl.AbyssPolicy.NONE)))
    per = max(bytes(m.get_buffer().get(r, 1.0, "Y' u8", Gegl.AbyssPolicy.NONE)))
    want = int(round(strength / 100.0 * 255))
    print("DS_STRENGTH %s strength %d flash %s status %s mask_peak_linear %d (want %d) perceptual %d %s" % (
        tag, strength, flash, st.split(".")[-1].split(" ")[0], lin, want, per, "OK" if abs(lin - want) <= 1 else "BAD"), flush=True)
    img.flatten()
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path("%s/%s_%d%s.png" % (OUT, tag, strength, "F" if flash else "")), None)
    img.delete()


for s in (25, 50, 75, 100):
    run("/workspace/retouch-trial/before.jpg", s, False, "selfie")
run("/workspace/retouch-trial/before.jpg", 100, True, "selfie")
run("/tmp/ds/spots.png", 100, False, "spots")
run("/tmp/ds/spots.png", 100, True, "spots")
print("DS_STRENGTH done", flush=True)
