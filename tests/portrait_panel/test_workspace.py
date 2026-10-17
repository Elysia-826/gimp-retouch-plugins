# Headless: build the 4 skin workspaces of 人像面板 on a photo; check tree, black masks,
# unchanged composite, context. Run from the repo root with python-fu-eval.
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
__import__("sys").path.insert(0, os.path.abspath("."))
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
SRC = os.environ.get("PP_TEST_IMAGE", "tests/data/astronaut.jpg")
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(SRC))


FAILS = []


def need(cond, what):
    print("PP_TEST %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def composite(image):
    d = image.duplicate(); l = d.flatten()
    w, h = l.get_width(), l.get_height()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    d.delete(); return b


def tree(items, ind=""):
    for l in items:
        extra = []
        if not l.is_group():
            m = l.get_mask()
            if m is not None:
                mb = bytes(m.get_buffer().get(Gegl.Rectangle.new(0, 0, m.get_width(), m.get_height()), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
                extra.append("mask_max=%d" % max(mb))
                need(max(mb) == 0, l.get_name() + " mask is black")
            extra.append("mode=%s op=%.0f" % (str(l.get_mode()).split(" ")[1], l.get_opacity()))
        print("PP_TEST %s%s%s vis=%s %s" % (ind, "[G] " if l.is_group() else "", l.get_name(), l.get_visible(), " ".join(extra)), flush=True)
        if l.is_group():
            tree(l.get_children(), ind + "  ")


before = composite(img)
for key in ("ws:dnb", "ws:deshine", "ws:fsep", "ws:heal"):
    msg = pp.build_workspace(img, key)
    sel = img.get_selected_layers()
    edit = sel[0].get_edit_mask() if sel and not sel[0].is_group() and sel[0].get_mask() is not None else False
    print("PP_TEST %s -> %s | selected=%s edit_mask=%s | fg=%s op=%.0f method=%s brush=%s hard=%.2f size=%.0f" % (
        key, msg, [l.get_name() for l in sel], edit, Gimp.context_get_foreground().get_rgba(),
        Gimp.context_get_opacity(), Gimp.context_get_paint_method(),
        Gimp.context_get_brush().get_name(), Gimp.context_get_brush_hardness(), Gimp.context_get_brush_size()), flush=True)
    after = composite(img)
    dmax = max(abs(a - b) for a, b in zip(before[::5], after[::5]))
    print("PP_TEST   composite max diff vs original = %d" % dmax, flush=True)
    need(dmax <= 1, key + " keeps the composite")
    if key in ("ws:dnb", "ws:deshine"):
        need(edit, key + " selects the mask")
tree(img.get_layers())
again = pp.build_workspace(img, "ws:dnb")
print("PP_TEST again dnb ->", again, flush=True)
need("已经有了" in again, "second ws:dnb reuses the first")
print("PP_TEST done", flush=True)
print("PP_TEST OK" if not FAILS else "PP_TEST FAIL %d" % len(FAILS), flush=True)
