# Headless: batch 2 item 8 — wire 液化/选择主体/人像笔刷/锐化/导出 into portrait_panel
# GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
#   -b "exec(open('tests/portrait_panel/test_batch8.py').read(), {'__name__': 't'})"
import importlib.util, os, math
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio

spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)

img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("/workspace/retouch-trial/before.jpg"))
BOX = (900, 2000, 200, 200)   # cheek/detail box for sharpen contrast


def flat_rgb(rect):
    d = img.duplicate(); l = d.flatten()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(*rect), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)); d.delete()
    return b


def local_contrast(b):
    """Mean absolute difference vs 3x3 neighbourhood (rough texture measure)."""
    w, h = BOX[2], BOX[3]
    px = [(b[i], b[i + 1], b[i + 2]) for i in range(0, len(b), 3)]
    def lum(p): return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]
    s, n = 0.0, 0
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            c = lum(px[y * w + x])
            for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
                s += abs(c - lum(px[(y + dy) * w + (x + dx)]))
                n += 1
    return s / max(1, n)


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


# --- button wiring: labels + PDB / ws keys ---
want = {
    "手动液化": "python-fu-mesh-liquify",
    "脸型微调": "python-fu-mesh-liquify-face",
    "选择主体": "python-fu-subject-select",
    "设好笔刷": "python-fu-portrait-brush",
    "涂抹锐化": "ws:sharpen",
    "导出图片": "python-fu-batch-export",
}
flat = {lab: name for _g, _t, items in pp.GROUPS for lab, name, _tip in items}
for lab, name in want.items():
    got = flat.get(lab)
    print("B8 wire %s -> %s (want %s) ok=%s" % (lab, got, name, got == name), flush=True)
    assert got == name, (lab, got, name)

# none of these should be None / "还没做"
assert flat.get("涂抹锐化") is not None and flat.get("涂抹锐化") != None
assert "还没做" not in str([tip for _g, _t, items in pp.GROUPS for lab, name, tip in items if lab == "涂抹锐化"])

# PDB existence (plugins must be installed into GIMP3_DIRECTORY)
pdb = Gimp.get_pdb()
for lab, name in want.items():
    if name.startswith("ws:"):
        print("B8 callable %s: workspace always-on" % lab, flush=True)
        continue
    ok = pdb.procedure_exists(name)
    print("B8 callable %s (%s): %s" % (lab, name, ok), flush=True)
    assert ok, "missing procedure %s — install into GIMP3_DIRECTORY" % name

# --- 锐化 workspace ---
before = flat_rgb(BOX)
c0 = local_contrast(before)
print("B8 sharpen:", pp.build_workspace(img, "ws:sharpen"), flush=True)
after_black = flat_rgb(BOX)
print("B8 sharpen black-mask maxdiff=%d contrast0=%.3f" % (
    max(abs(a - b) for a, b in zip(before, after_black)), c0), flush=True)
assert max(abs(a - b) for a, b in zip(before, after_black)) == 0

sharp = find(pp.WS_NAMES["ws:sharpen"])
assert sharp is not None and sharp.get_mask() is not None
ops = [f.get_operation_name() for f in sharp.get_filters()]
print("B8 sharpen filters:", ops, "op=%.0f" % sharp.get_opacity(), flush=True)
assert pp.SHARP_FILTER in ops

# stronger amount so contrast clearly rises when mask is white
pp.set_sharpen_settings({"radius": 1.5, "amount": 1.2, "opacity": 100.0}, img)
fill_mask(sharp, BOX, 255)
after = flat_rgb(BOX)
c1 = local_contrast(after)
md = max(abs(a - b) for a, b in zip(before, after))
print("B8 sharpen white-mask maxdiff=%d contrast %.3f -> %.3f" % (md, c0, c1), flush=True)
assert md > 0 and c1 > c0 * 1.01, (md, c0, c1)

# retune via settings sticks
pp.set_sharpen_settings({"radius": 0.8, "amount": 0.3, "opacity": 80.0}, img)
print("B8 sharpen retuned opacity=%.0f" % sharp.get_opacity(), flush=True)
assert abs(sharp.get_opacity() - 80.0) < 0.5
pp.set_sharpen_settings(pp.SHARP_DEFAULTS, img)

# again = select existing
print("B8 sharpen again:", pp.build_workspace(img, "ws:sharpen"), flush=True)
sel = img.get_selected_layers()[0]
print("B8 ctx: selected=%s edit_mask=%s" % (sel.get_name(), sel.get_edit_mask()), flush=True)

# tree under 插件改动
top = pp.find_group(img)
print("B8 tree child names:", [c.get_name() for c in top.get_children()], flush=True)
print("B8 done", flush=True)
