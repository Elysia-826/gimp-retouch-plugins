import os, tempfile
from gi.repository import Gimp, Gio, Gegl
src = os.environ.get("DNB_IN", "tests/data/astronaut.jpg"); out = os.environ.get("DNB_OUT", os.path.join(tempfile.gettempdir(), "dnb"))
pdb = Gimp.get_pdb()
FAILS = []


def need(cond, what):
    print("DNB %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def flat(img):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(0, 0, l.get_width(), l.get_height()), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    d.delete(); return b


for blend, nick in (("soft-light", "softlight"), ("overlay", "overlay")):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
    lay = img.get_layers()[0]
    before = flat(img)
    p = pdb.lookup_procedure("python-fu-dnb-setup"); c = p.create_config()
    c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
    c.set_core_object_array("drawables", [lay])
    c.set_property("blend-mode", blend); c.set_property("contrast-boost", True)
    r = p.run(c); print("STATUS", blend, r.index(0))
    need(r.index(0) == Gimp.PDBStatusType.SUCCESS, blend + " success")
    rows = []

    def dump(ls, d=0):
        for l in ls:
            rows.append((d, l.get_name(), l.get_mode().value_nick, l.get_visible()))
            print("LAYER", "  " * d + l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden", "%.0f" % l.get_opacity())
            if l.is_group(): dump(l.get_children(), d + 1)
    dump(img.get_layers())
    need(rows[0][1] == "Dodge & Burn" and rows[0][2] == "pass-through", "Dodge & Burn pass-through group on top")
    need(any(m == nick and v for _, _, m, v in rows), "a visible %s layer" % nick)
    sel = img.get_selected_layers()
    print("SEL", [l.get_name() for l in sel])
    need(len(sel) == 1 and sel[0].get_mode().value_nick == nick, "the D&B layer is selected")
    fg = Gimp.context_get_foreground().get_rgba()
    print("FG", fg, "BG", Gimp.context_get_background().get_rgba())
    need(tuple(round(v, 3) for v in fg[:3]) == (1.0, 1.0, 1.0), "foreground white")
    if os.environ.get("HELPER"): img.get_layers()[0].get_children()[0].set_visible(True)
    img.flatten(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path(out + "_" + blend + ".png"))
    img.delete()
print("DNB_TEST OK" if not FAILS else "DNB_TEST FAIL %d" % len(FAILS), flush=True)
