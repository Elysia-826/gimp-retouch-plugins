# Headless: 眼部修饰 on before.jpg with an ellipse around the left eye. Run with
# exec(open('tests/portrait_panel/test_eye.py').read(), {'__name__': 't'}) from repo root.
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
__import__("sys").path.insert(0, os.path.abspath("."))
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("/workspace/retouch-trial/before.jpg"))
E = (560, 1560, 240, 130)    # around the eye at (675,1621)


def px(image, rect):
    d = image.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*rect), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)); d.delete()
    return b


print("EYE no selection:", pp.build_workspace(img, "ws:eye"), flush=True)
full = (0, 0, img.get_width(), img.get_height())
before_all = px(img, full)
img.select_ellipse(Gimp.ChannelOps.REPLACE, *E)
print("EYE", pp.build_workspace(img, "ws:eye"), flush=True)
after_all = px(img, full)
print("EYE black masks: max diff whole image = %d" % max(abs(a - b) for a, b in zip(before_all[::3], after_all[::3])), flush=True)
sel = img.get_selected_layers()[0]
print("EYE selected=%s edit_mask=%s op=%.0f size=%.0f fg=%s sel_empty=%s" % (sel.get_name(), sel.get_edit_mask(), Gimp.context_get_opacity(),
      Gimp.context_get_brush_size(), Gimp.context_get_foreground().get_rgba(), Gimp.Selection.is_empty(img)), flush=True)
top = pp.find_group(img); eg = pp._find_child(top, "眼部修饰")
def tree(it, ind=""):
    for c in it:
        print("EYE  %s%s mode=%s op=%.0f mask=%s" % (ind, c.get_name(), str(c.get_mode()).split(" ")[1], c.get_opacity(), c.get_mask() is not None), flush=True)
        if c.is_group(): tree(c.get_children(), ind + "  ")
tree([eg])
base = px(img, E)
for sub in (pp.EYE_WHITE, pp.EYE_IRIS):
    sg = pp._find_child(eg, sub); m = sg.get_mask()
    Gimp.context_push(); Gimp.context_set_opacity(100.0); Gimp.context_set_foreground(Gegl.Color.new("white"))
    m.edit_fill(Gimp.FillType.FOREGROUND); Gimp.context_pop()   # fills inside the selection only
    full_b = px(img, E)
    lum = lambda b, i: 0.299 * b[i] + 0.587 * b[i + 1] + 0.114 * b[i + 2]
    n = len(base) // 3
    ds = [lum(full_b, i * 3) - lum(base, i * 3) for i in range(n)]
    bright = [i for i in range(n) if lum(base, i * 3) > 150]          # eye-white / skin-ish pixels
    dark = [i for i in range(n) if lum(base, i * 3) < 40]             # pupil
    sat0 = sum(max(base[i*3:i*3+3]) - min(base[i*3:i*3+3]) for i in bright) / max(1, len(bright))
    sat1 = sum(max(full_b[i*3:i*3+3]) - min(full_b[i*3:i*3+3]) for i in bright) / max(1, len(bright))
    hs = lambda b, i: (max(b[i:i+3]) - min(b[i:i+3])) / max(1, max(b[i:i+3]))
    s0 = sum(hs(base, i*3) for i in bright) / max(1, len(bright)); s1 = sum(hs(full_b, i*3) for i in bright) / max(1, len(bright))
    print("EYE %s bright-px mean lift %.1f, HSV sat %.3f->%.3f (%+.0f%%)" % (sub[:4], sum(ds[i] for i in bright) / max(1, len(bright)), s0, s1, (s1/s0-1)*100 if s0 else 0), flush=True)
    print("EYE %s mask full: max lift %.1f, mean lift %.1f, max channel after %d (before %d), pupil(<40) mean lift %.1f, bright-px chroma %.1f->%.1f" % (
        sub[:4], max(ds), sum(ds) / n, max(full_b), max(base), sum(ds[i] for i in dark) / max(1, len(dark)), sat0, sat1), flush=True)
    Gimp.context_push(); Gimp.context_set_opacity(100.0); Gimp.context_set_foreground(Gegl.Color.new("black"))
    m.edit_fill(Gimp.FillType.FOREGROUND); Gimp.context_pop()
pp.set_eye_strengths({"white": 55.0, "iris": 20.0}, img)
print("EYE strengths applied:", [(c.get_name(), round(c.get_opacity())) for s in eg.get_children() for c in s.get_children()], flush=True)
pp.set_eye_strengths(pp.EYE_DEFAULTS)
print("EYE done", flush=True)
