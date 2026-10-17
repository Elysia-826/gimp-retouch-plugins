# Headless: step 3 of 人像面板 - D&B/去油光 do not bring back original pixels over 高低频 edits,
# mask preview toggle, FG/BG swap, backup locks. Run from repo root with python-fu-eval.
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
__import__("sys").path.insert(0, os.path.abspath("."))
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(os.environ.get("PP_TEST_IMAGE", "tests/data/astronaut.jpg")))
R = tuple(int(v) for v in os.environ.get("PP_BOX_CHEEK", "380,228,40,40").split(","))   # cheek/nose box (before.jpg: 700,1700,400,400)


FAILS = []


def need(cond, what):
    print("ST3 %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def comp_mean(image):
    d = image.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*R), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)); d.delete()
    return sum(b) / len(b)


def find(image, prefix):
    st = list(image.get_layers())
    while st:
        l = st.pop(0)
        if l.get_name().startswith(prefix):
            return l
        if l.is_group():
            st.extend(l.get_children())


def fill_mask(layer, color):
    m = layer.get_mask()
    Gimp.context_push(); Gimp.context_set_opacity(100.0); Gimp.context_set_foreground(Gegl.Color.new(color))
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *R); m.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.Selection.none(img); Gimp.context_pop()


print("ST3", pp.build_workspace(img, "ws:fsep"), flush=True)
orig = comp_mean(img)
low = find(img, "Low")
Gimp.context_push(); Gimp.context_set_foreground(Gegl.Color.new("#406080"))
img.select_rectangle(Gimp.ChannelOps.REPLACE, *R); low.edit_fill(Gimp.FillType.FOREGROUND); Gimp.Selection.none(img); Gimp.context_pop()
edited = comp_mean(img)
print("ST3 box mean: original %.1f, after 高低频 edit %.1f" % (orig, edited), flush=True)
need(abs(edited - orig) > 5, "the Low edit changes the box")
print("ST3", pp.build_workspace(img, "ws:dnb"), flush=True)
print("ST3", pp.build_workspace(img, "ws:deshine"), flush=True)
built = comp_mean(img)
print("ST3 after building, masks black: %.1f" % built, flush=True)
need(abs(built - edited) <= 0.5, "black masks keep the edited composite")
up = find(img, "提亮"); fill_mask(up, "white"); a = comp_mean(img); fill_mask(up, "black")
dn = find(img, "压暗"); fill_mask(dn, "white"); a2 = comp_mean(img); fill_mask(dn, "black")
# since 00c1442 去油光 is one Multiply layer named WS_NAMES["ws:deshine"] (was 去油光画笔)
br = find(img, pp.WS_NAMES["ws:deshine"]); fill_mask(br, "white"); b = comp_mean(img); fill_mask(br, "black")
print("ST3 mask white in box -> 提亮 %.1f, 压暗 %.1f, 去油光 %.1f (edited %.1f; jumping to %.1f would mean old pixels came back)" % (a, a2, b, edited, orig), flush=True)
need(a > edited + 2, "提亮 brightens")
need(a2 < edited - 2, "压暗 darkens")
need(b <= edited + 0.5 and abs(b - orig) >= abs(edited - orig) - 1, "去油光 only darkens and does not bring back old pixels")
pp._select_mask(img, br); fill_mask(br, "white")
print("ST3 preview on:", pp.toggle_preview(img), "| top:", img.get_layers()[0].get_name(), flush=True)
need(img.get_layers()[0].get_name() == pp.PREVIEW_NAME, "preview layer on top")
pm = img.get_layers()[0].get_mask()
mb = bytes(pm.get_buffer().get(Gegl.Rectangle.new(0, 0, pm.get_width(), pm.get_height()), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
print("ST3 preview mask white px %d (box = %d), selected=%s" % (sum(1 for v in mb if v > 128), R[2] * R[3], [l.get_name() for l in img.get_selected_layers()]), flush=True)
need(abs(sum(1 for v in mb if v > 128) - R[2] * R[3]) <= R[2] * R[3] * 0.02, "preview shows exactly the painted box")
print("ST3 preview off:", pp.toggle_preview(img), "| top:", img.get_layers()[0].get_name(), "| edit_mask", img.get_selected_layers()[0].get_edit_mask(), flush=True)
need(img.get_layers()[0].get_name() != pp.PREVIEW_NAME and img.get_selected_layers()[0].get_edit_mask(), "preview off returns to the mask")
img.set_selected_layers([find(img, "Background")])
nm = pp.toggle_preview(img)
print("ST3 no-mask:", nm, flush=True)
need("没有蒙版" in nm, "no-mask layer is refused")
Gimp.context_set_foreground(Gegl.Color.new("white")); Gimp.context_set_background(Gegl.Color.new("black"))
Gimp.context_swap_colors(); print("ST3 swap -> fg", Gimp.context_get_foreground().get_rgba(), flush=True)
need(tuple(Gimp.context_get_foreground().get_rgba()[:3]) == (0.0, 0.0, 0.0), "swap gives black")
bak = find(img, "原图（锁定）")
print("ST3 backup locks: content=%s position=%s alpha=%s visibility=%s has_alpha=%s" % (
    bak.get_lock_content(), bak.get_lock_position(), bak.get_lock_alpha(),
    bak.get_lock_visibility() if hasattr(bak, "get_lock_visibility") else "n/a", bak.has_alpha()), flush=True)
need(bak.get_lock_content() and bak.get_lock_position(), "backup is locked")
try:
    bak.set_lock_alpha(True); print("ST3 set_lock_alpha direct ->", bak.get_lock_alpha(), flush=True)
except Exception as e:
    print("ST3 set_lock_alpha direct error:", e, flush=True)
print("ST3 done", flush=True)
print("ST3 OK" if not FAILS else "ST3 FAIL %d" % len(FAILS), flush=True)
