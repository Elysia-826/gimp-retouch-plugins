# Headless measurements for 修颜's review of 08106fd: 提亮 strength, 去油光 pixel-free, 去油光 colour.
# Run with a separate GIMP dir: GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 ... exec(..., {'__name__':'t'})
import importlib.util, os, math
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
__import__("sys").path.insert(0, os.path.abspath("."))
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(os.environ.get("PP_TEST_IMAGE", "tests/data/astronaut.jpg")))
CHEEK = tuple(int(v) for v in os.environ.get("PP_BOX_CHEEK", "380,228,40,40").split(","))   # before.jpg: 1150,2050,200,200
NOSE = tuple(int(v) for v in os.environ.get("PP_BOX_NOSE", "428,226,30,36").split(","))   # before.jpg: 820,1820,160,200


FAILS = []


def need(cond, what):
    print("R3 %s %s" % ("check" if cond else "FAIL", what), flush=True)
    if not cond:
        FAILS.append(what)


def px(rect):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*rect), 1.0, "CIE LCH(ab) float", Gegl.AbyssPolicy.NONE)); d.delete()
    import array; a = array.array("f"); a.frombytes(b); return a


def stats(a):
    n = len(a) // 3
    L = sum(a[0::3]) / n; C = sum(a[1::3]) / n
    hx = sum(math.cos(math.radians(h)) for h in a[2::3]); hy = sum(math.sin(math.radians(h)) for h in a[2::3])
    return L, C, math.degrees(math.atan2(hy, hx))


def find(prefix):
    st = list(img.get_layers())
    while st:
        l = st.pop(0)
        if l.get_name().startswith(prefix):
            return l
        if l.is_group():
            st.extend(l.get_children())


def fill_mask(layer, rect, value):
    m = layer.get_mask()
    Gimp.context_push(); Gimp.context_set_opacity(100.0)
    Gimp.context_set_foreground(Gegl.Color.new("#%02x%02x%02x" % (value, value, value)))
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *rect); m.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.Selection.none(img); Gimp.context_pop()


print("R3", pp.build_workspace(img, "ws:fsep"), flush=True)
print("R3", pp.build_workspace(img, "ws:dnb"), flush=True)
up = find("提亮")
L0, C0, H0 = stats(px(CHEEK))
for v, tag in ((51, "one pass (20%)"), (255, "full")):
    fill_mask(up, CHEEK, v); L, C, H = stats(px(CHEEK))
    print("R3 (1) 提亮 %s: dL %+.1f, chroma %+.1f, hue %+.1f" % (tag, L - L0, C - C0, H - H0), flush=True)
    need(L - L0 >= 0 if v < 255 else L - L0 > 2, "提亮 %s brightens" % tag)
    need(abs(C - C0) < 3, "提亮 %s keeps chroma" % tag)
fill_mask(up, CHEEK, 0)
print("R3", pp.build_workspace(img, "ws:deshine"), flush=True)
ds = find("去油光")
print("R3 去油光 layer: %s mode=%s" % (ds.get_name(), str(ds.get_mode()).split(" ")[1]), flush=True)
need(ds.get_mode() == Gimp.LayerMode.MULTIPLY, "去油光 is multiply")
n0 = stats(px(NOSE))
fill_mask(ds, NOSE, 255); n1 = stats(px(NOSE))
print("R3 (3) 去油光 full on nose: dL %+.1f, chroma %+.1f, hue %+.1f" % (n1[0] - n0[0], n1[1] - n0[1], n1[2] - n0[2]), flush=True)
need(n1[0] < n0[0] and abs(n1[1] - n0[1]) < 3, "去油光 darkens, keeps chroma")
# (2) later 高低频 edit: darken the Low layer in the nose box by a flat amount; with 去油光
# painted full, the composite must follow the edit (not snap back)
low = find("Low")
Gimp.context_push(); Gimp.context_set_opacity(30.0); Gimp.context_set_foreground(Gegl.Color.new("#000000"))
img.select_rectangle(Gimp.ChannelOps.REPLACE, *NOSE); low.edit_fill(Gimp.FillType.FOREGROUND); Gimp.Selection.none(img); Gimp.context_pop()
n2 = stats(px(NOSE))
fill_mask(ds, NOSE, 0); n3 = stats(px(NOSE))
print("R3 (2) later Low edit: with 去油光 on dL %+.1f, without 去油光 dL %+.1f (edit shows through when both move)" % (n2[0] - n1[0], n3[0] - n0[0]), flush=True)
need(n2[0] - n1[0] < -3 and abs((n2[0] - n1[0]) - (n3[0] - n0[0])) < 2, "a later Low edit shows through 去油光")
print("R3 done", flush=True)
print("R3 OK" if not FAILS else "R3 FAIL %d" % len(FAILS), flush=True)
