# Headless: batch 2 item 7 — 皮肤减红 / 统一肤色 / 卧蚕压色 / 牙齿美白
# GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
#   -b "exec(open('tests/portrait_panel/test_batch7.py').read(), {'__name__': 't'})"
import importlib.util, os, math, array
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
__import__("sys").path.insert(0, os.path.abspath("."))
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("/workspace/retouch-trial/before.jpg"))
CHEEK = (1150, 2050, 200, 200)
UNDER = (580, 1690, 220, 70)     # under left eye
MOUTH = (780, 2480, 400, 140)   # 修颜: real mouth ~y2480–2600; old (780,2080) was nose tip


def px_rgb(rect):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*rect), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)); d.delete()
    return b


def px_lch(rect):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*rect), 1.0, "CIE LCH(ab) float", Gegl.AbyssPolicy.NONE)); d.delete()
    a = array.array("f"); a.frombytes(b); return a


def stats(a):
    n = len(a) // 3
    L = sum(a[0::3]) / n; C = sum(a[1::3]) / n
    hx = sum(math.cos(math.radians(h)) for h in a[2::3]); hy = sum(math.sin(math.radians(h)) for h in a[2::3])
    return L, C, math.degrees(math.atan2(hy, hx))


def fill_mask(layer, rect, value):
    m = layer.get_mask()
    Gimp.context_push(); Gimp.context_set_opacity(100.0)
    Gimp.context_set_foreground(Gegl.Color.new("#%02x%02x%02x" % (value, value, value)))
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *rect); m.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.Selection.none(img); Gimp.context_pop()


def find(name):
    st = list(img.get_layers())
    while st:
        l = st.pop(0)
        if l.get_name() == name:
            return l
        if l.is_group():
            st[0:0] = list(l.get_children())


def tree(it, ind=""):
    for c in it:
        print("B7  %s%s mode=%s op=%.0f mask=%s" % (
            ind, c.get_name(), str(c.get_mode()).split(" ")[1], c.get_opacity(),
            c.get_mask() is not None), flush=True)
        if c.is_group():
            tree(c.get_children(), ind + "  ")


full = (0, 0, img.get_width(), img.get_height())
before0 = px_rgb(full)

# --- 皮肤减红 ---
print("B7 dered:", pp.build_workspace(img, "ws:dered"), flush=True)
after_black = px_rgb(full)
print("B7 dered black-mask max diff = %d" % max(abs(a - b) for a, b in zip(before0[::7], after_black[::7])), flush=True)
dered = find(pp.DERED_LAYER)
L0, C0, H0 = stats(px_lch(CHEEK))
fill_mask(dered, CHEEK, 255)
L1, C1, H1 = stats(px_lch(CHEEK))
print("B7 dered full: dL %+.2f dC %+.2f dH %+.1f (want dL~0, dC<0)" % (L1 - L0, C1 - C0, H1 - H0), flush=True)
fill_mask(dered, CHEEK, 0)

# --- 统一肤色 ---
print("B7 unify:", pp.build_workspace(img, "ws:unify"), flush=True)
unify = find(pp.UNIFY_LAYER)
L0, C0, H0 = stats(px_lch(CHEEK))
fill_mask(unify, CHEEK, 255)
L1, C1, H1 = stats(px_lch(CHEEK))
print("B7 unify full: dL %+.2f dC %+.2f dH %+.1f" % (L1 - L0, C1 - C0, H1 - H0), flush=True)
fill_mask(unify, CHEEK, 0)

# --- 卧蚕压色 ---
print("B7 under:", pp.build_workspace(img, "ws:undereye"), flush=True)
ug = find(pp.WS_NAMES["ws:undereye"])
L0, C0, H0 = stats(px_lch(UNDER))
fill_mask(ug, UNDER, 255)
L1, C1, H1 = stats(px_lch(UNDER))
print("B7 under full: dL %+.2f dC %+.2f dH %+.1f (want dL<0, dC<=0)" % (L1 - L0, C1 - C0, H1 - H0), flush=True)
fill_mask(ug, UNDER, 0)

# --- 牙齿美白 ---
print("B7 teeth no sel:", pp.build_workspace(img, "ws:teeth"), flush=True)
img.select_ellipse(Gimp.ChannelOps.REPLACE, *MOUTH)
print("B7 teeth:", pp.build_workspace(img, "ws:teeth"), flush=True)
tg = find(pp.WS_NAMES["ws:teeth"])
base = px_rgb(MOUTH)
Gimp.context_push(); Gimp.context_set_opacity(100.0); Gimp.context_set_foreground(Gegl.Color.new("white"))
tg.get_mask().edit_fill(Gimp.FillType.FOREGROUND); Gimp.context_pop()
full_b = px_rgb(MOUTH)
lum = lambda b, i: 0.299 * b[i] + 0.587 * b[i + 1] + 0.114 * b[i + 2]
n = len(base) // 3
ds = [lum(full_b, i * 3) - lum(base, i * 3) for i in range(n)]
bright = [i for i in range(n) if lum(base, i * 3) > 120]
sat = lambda b, i: max(b[i:i+3]) - min(b[i:i+3])
s0 = sum(sat(base, i * 3) for i in bright) / max(1, len(bright))
s1 = sum(sat(full_b, i * 3) for i in bright) / max(1, len(bright))
print("B7 teeth full: mean lift %.1f, max channel %d->%d, bright chroma %.1f->%.1f, max lift %.1f" % (
    sum(ds) / n, max(base), max(full_b), s0, s1, max(ds)), flush=True)
print("B7 teeth not pure white: ok=%s" % (max(full_b) < 255 or max(ds) < 40), flush=True)

# strengths apply
pp.set_dered_strength(55.0, img)
pp.set_unify_strength(45.0, img)
pp.set_under_strengths({"dark": 70.0, "chroma": 50.0}, img)
pp.set_teeth_strengths({"lift": 40.0, "chroma": 60.0}, img)
print("B7 strengths:",
      find(pp.DERED_LAYER).get_opacity(),
      find(pp.UNIFY_LAYER).get_opacity(),
      find(pp.UNDER_NAMES["dark"]).get_opacity(),
      find(pp.UNDER_NAMES["chroma"]).get_opacity(),
      find(pp.TEETH_NAMES["lift"]).get_opacity(),
      find(pp.TEETH_NAMES["chroma"]).get_opacity(), flush=True)
pp.set_dered_strength(pp.DERED_DEFAULT)
pp.set_unify_strength(pp.UNIFY_DEFAULT)
pp.set_under_strengths(pp.UNDER_DEFAULTS)
pp.set_teeth_strengths(pp.TEETH_DEFAULTS)

top = pp.find_group(img)
print("B7 tree:", flush=True)
for name in ("皮肤减红", "统一肤色", "卧蚕压色", "牙齿美白"):
    tree([pp._find_child(top, name)])

# brush / selection context on last build (teeth)
sel = img.get_selected_layers()[0]
print("B7 ctx: selected=%s edit_mask=%s op=%.0f fg_whiteish=%s" % (
    sel.get_name(), sel.get_edit_mask(), Gimp.context_get_opacity(),
    Gimp.context_get_foreground().get_rgba()[0] > 0.9), flush=True)
print("B7 done", flush=True)
