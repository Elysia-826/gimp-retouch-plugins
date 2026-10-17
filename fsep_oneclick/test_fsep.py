# run via python-fu-eval; env FS_IN input, FS_OUT output prefix
import os, tempfile
from gi.repository import Gimp, Gio, Gegl
src = os.environ.get("FS_IN", "tests/data/astronaut.jpg"); out = os.environ.get("FS_OUT", os.path.join(tempfile.gettempdir(), "fs"))
pdb = Gimp.get_pdb()
FAILS = []


def need(cond, what):
    print("FS %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def flat(img):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(0, 0, l.get_width(), l.get_height()), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    d.delete(); return b


img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
lay = img.get_layers()[0]
before = flat(img)
p = pdb.lookup_procedure("python-fu-fsep-oneclick")
c = p.create_config()
c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
c.set_core_object_array("drawables", [lay])
c.set_property("radius", 4.0)
r = p.run(c); print("STATUS", r.index(0), r.index(1) if r.length() > 1 else "")
need(r.index(0) == Gimp.PDBStatusType.SUCCESS, "success")


def dump(ls, d=0):
    for l in ls:
        print("LAYER", "  " * d + l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden")
        if l.is_group(): dump(l.get_children(), d + 1)
dump(img.get_layers())
kids = img.get_layers()[0].get_children()
need([k.get_mode().value_nick for k in kids] == ["grain-merge", "normal"], "High grain-merge over Low normal")
after = flat(img)
ds = [abs(a - b) for a, b in zip(before, after)]
diff = max(ds)
over = sum(1 for v in ds if v > 2) / len(ds)
print("FS composite max diff %d, share > 2: %.4f%%, mean %.3f" % (diff, over * 100, sum(ds) / len(ds)))
need(over <= 0.001 and sum(ds) / len(ds) <= 1.5, "High + Low rebuild the original (8-bit clips a few near-black values)")
low = [l for l in kids if l.get_name().startswith("Low")][0]
lb = bytes(low.get_buffer().get(Gegl.Rectangle.new(0, 0, low.get_width(), low.get_height()), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
blur = sum(abs(lb[i] - lb[i + 3]) for i in range(0, len(lb) - 3, 3 * 97)) / (len(lb) // (3 * 97))
sharp = sum(abs(before[i] - before[i + 3]) for i in range(0, len(before) - 3, 3 * 97)) / (len(before) // (3 * 97))
print("FS neighbour diff original %.2f low %.2f" % (sharp, blur))
need(blur < sharp * 0.8, "Low is blurred")
d2 = img.duplicate(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, d2, Gio.File.new_for_path(out + "_low.png"))
img.flatten(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(out + "_flat.png"))
print("FSEP_TEST OK" if not FAILS else "FSEP_TEST FAIL %d" % len(FAILS), flush=True)
