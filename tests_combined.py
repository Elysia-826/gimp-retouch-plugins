# python-fu-eval combined test. env: T_IN (image, default the repo astronaut), T_OUT (prefix)
import os, tempfile
from gi.repository import Gimp, Gio
src = os.environ.get("T_IN", "tests/data/astronaut.jpg"); out = os.environ.get("T_OUT", os.path.join(tempfile.gettempdir(), "comb"))
pdb = Gimp.get_pdb()
FAILS = []


def need(cond, what):
    print("COMB %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def st(r):
    v = r.index(0); return getattr(v, "value_nick", v)


def call(name, img, drs, **kw):
    p = pdb.lookup_procedure(name); c = p.create_config()
    c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
    c.set_core_object_array("drawables", drs)
    for k, v in kw.items(): c.set_property(k, v)
    return p.run(c)


def expect(tag, r, want="success"):
    s = st(r); print(tag, s, flush=True)
    need(s == want, "%s -> %s" % (tag, want))


def dump(ls, d=0):
    for l in ls:
        print("LAYER", "  " * d + l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden",
              "alpha" if l.has_alpha() else "noalpha", "group" if l.is_group() else "")
        if l.is_group(): dump(l.get_children(), d + 1)


def load():
    return Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))


heal = pdb.lookup_procedure("plug-in-heal-selection") is not None
for alpha in (False, True):
    img = load(); lay = img.get_layers()[0]
    if alpha: lay.add_alpha()
    print("=== source alpha", alpha, "auto-radius case")
    expect("FSEP", call("python-fu-fsep-oneclick", img, [lay], radius=0.0))
    grp = img.get_layers()[0]; high, low = grp.get_children()
    print("ALPHA high/low", high.has_alpha(), low.has_alpha())
    need(low.has_alpha() == alpha, "Low keeps the source alpha (%s)" % alpha)
    if heal:
        img.select_ellipse(Gimp.ChannelOps.REPLACE, 300, 250, 30, 30)
        expect("HEAL", call("plug-in-heal-selection", img, [high]))
        Gimp.Selection.none(img)
    else:
        print("HEAL skipped: Resynthesizer not installed", flush=True)
    img.set_selected_layers([grp])
    expect("DNB_on_group", call("python-fu-dnb-setup", img, [grp], **{"contrast-boost": True}))
    expect("DNB_on_top", call("python-fu-dnb-setup", img, [img.get_layers()[-1]], **{"place-on-top": True, "contrast-boost": True}))
    need(img.get_layers()[0].get_name() == "Dodge & Burn", "place-on-top puts D&B on top")
    dump(img.get_layers())
    if not alpha:
        d = img.duplicate(); d.flatten()
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, d, Gio.File.new_for_path(out + "_flat.png"))
# re-run detection + grayscale
img = load(); lay = img.get_layers()[0]
expect("DNB1", call("python-fu-dnb-setup", img, [lay]))
expect("DNB2", call("python-fu-dnb-setup", img, [img.get_layers()[-1]]))
print("STACK", [l.get_name() for l in img.get_layers()], "SEL", [l.get_name() for l in img.get_selected_layers()])
need([l.get_name() for l in img.get_layers()].count("Dodge & Burn") == 1, "a second run reuses the D&B group")
img.convert_grayscale(); expect("GRAY", call("python-fu-dnb-setup", img, [img.get_layers()[-1]]))
g = load(); g.convert_grayscale(); expect("GRAY_FRESH", call("python-fu-dnb-setup", g, [g.get_layers()[0]], **{"contrast-boost": True}))
# error path
img = load()
expect("DNB_empty", call("python-fu-dnb-setup", img, []), "calling-error")
expect("FSEP_empty", call("python-fu-fsep-oneclick", img, []), "calling-error")
print("COMB_TEST OK" if not FAILS else "COMB_TEST FAIL %d" % len(FAILS), flush=True)
