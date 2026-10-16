# Headless: 锐化 one-click / 更新锐化 / parameters / registration.
# GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
#   -b "exec(open('tests/portrait_panel/test_sharpen.py').read(), {'__name__': 't'})"
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
SRC = os.environ.get("PP_TEST_IMAGE", "/workspace/retouch-trial/before.jpg")
print("SHARP version", pp.gimp_version(), "filters", pp.has_drawable_filters(), flush=True)

# registration
pdb = Gimp.get_pdb()
assert pdb.procedure_exists(pp.PROC), pp.PROC
labels = {lab: n for _g, _t, items in pp.GROUPS for lab, n, _tip in items}
assert labels.get("一键锐化") == "__sharp_oneclick__" and labels.get("更新锐化") == "__sharp_refresh__", labels
for lab in ("涂抹锐化", "一键锐化", "更新锐化"):
    assert 2 <= len(pp.help_text(lab).splitlines()) <= 3, lab


def load():
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(SRC))
    img.scale(600, round(600 * img.get_height() / img.get_width()))
    return img


def comp(image):
    d = image.duplicate(); l = d.flatten()
    w, h = l.get_width(), l.get_height()
    b = bytes(l.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    d.delete(); return b, w, h


def mask_bytes(lay):
    m = lay.get_mask()
    return bytes(m.get_buffer().get(Gegl.Rectangle.new(0, 0, m.get_width(), m.get_height()), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))


def diff_in_out(a, b, w, rect):
    x0, y0, rw, rh = rect; din = dout = 0
    for i in range(0, len(a), 3):
        p = i // 3; x, y = p % w, p // w
        d = abs(a[i] - b[i]) + abs(a[i+1] - b[i+1]) + abs(a[i+2] - b[i+2])
        if x0 <= x < x0 + rw and y0 <= y < y0 + rh: din += d
        else: dout += d
    return din, dout


saved = pp.sharpen_settings()
try:
    pp.set_sharpen_settings({"radius": 1.2, "amount": 0.8, "opacity": 100.0})
    img = load(); pp.start_retouch(img)
    before, w, h = comp(img)
    R = (150, 300, 200, 150)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, *R)
    msg = pp.sharpen_oneclick(img); print("SHARP", msg, flush=True)
    after, _, _ = comp(img)
    din, dout = diff_in_out(before, after, w, R)
    print("SHARP oneclick diff in=%d out=%d" % (din, dout), flush=True)
    assert din > 0 and dout == 0, (din, dout)
    lay = pp.find_sharpen(img)
    mb = mask_bytes(lay)
    bad = sum(1 for p, v in enumerate(mb)
              if (R[0] <= p % w < R[0] + R[2] and R[1] <= p // w < R[1] + R[3]) != (v == 255) or v not in (0, 255))
    assert bad == 0, bad
    print("SHARP mask == selection", flush=True)
    assert lay.get_filters() and lay.get_filters()[0].get_operation_name() == "gegl:unsharp-mask"
    cfg = lay.get_filters()[0].get_config()
    assert abs(cfg.get_property("std-dev") - 1.2) < 1e-6 and abs(cfg.get_property("scale") - 0.8) < 1e-6

    # later edit on the photo (black square inside the selection) -> stale until 更新锐化
    Gimp.Selection.none(img)
    photo = pp._working_layer(img)
    img.select_rectangle(Gimp.ChannelOps.REPLACE, 200, 330, 40, 40)
    Gimp.context_push(); Gimp.context_set_foreground(Gegl.Color.new("black"))
    photo.edit_fill(Gimp.FillType.FOREGROUND); Gimp.context_pop()
    Gimp.Selection.none(img)
    px = lambda b: b[(350 * w + 220) * 3]
    stale, _, _ = comp(img)
    assert px(stale) > 40, px(stale)            # sharpen snapshot still covers the edit
    lay.set_opacity(70.0)
    print("SHARP", pp.sharpen_refresh(img), flush=True)
    fresh, _, _ = comp(img)
    lay2 = pp.find_sharpen(img)
    assert px(fresh) < 10, px(fresh)
    assert mask_bytes(lay2) == mb, "mask changed"
    assert abs(lay2.get_opacity() - 70.0) < 0.01 and Gimp.Selection.is_empty(img)
    print("SHARP refresh keeps mask, picks up edit (%d -> %d)" % (px(stale), px(fresh)), flush=True)

    # parameters honoured: amount 0 -> no change; bigger amount -> bigger change
    res = {}
    for amt in (0.0, 0.3, 1.5):
        pp.set_sharpen_settings({"radius": 1.2, "amount": amt, "opacity": 100.0})
        im = load(); b0, w, h = comp(im)
        Gimp.Selection.none(im)
        pp.sharpen_oneclick(im)                  # no selection -> whole image, white mask
        assert min(mask_bytes(pp.find_sharpen(im))) == 255
        b1, _, _ = comp(im)
        res[amt] = sum(abs(x - y) for x, y in zip(b0, b1)); im.delete()
    print("SHARP amount diffs", res, flush=True)
    assert res[0.0] < res[0.3] * 0.05 and res[0.3] < res[1.5], res
    # paint-in mode still works (black mask, composite unchanged)
    im = load(); b0, _, _ = comp(im)
    pp.build_workspace(im, "ws:sharpen")
    assert max(mask_bytes(pp.find_sharpen(im))) == 0 and comp(im)[0] == b0
    print("SHARP paint-in mode ok", flush=True)
    print("SHARP ALL OK", flush=True)
finally:
    pp.set_sharpen_settings(saved)
