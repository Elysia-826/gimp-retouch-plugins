# Headless tests for python-fu-dnb-flow. Grey overlay, not the photo.
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl

Gegl.init(None)
pdb = Gimp.get_pdb()

def die(msg):
    print("FLOW_TEST FAIL " + msg, flush=True)
    raise SystemExit(1)

def grey_image():
    w, h = 220, 140
    img = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "加深减淡 D&B", w, h, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.SOFTLIGHT)
    img.insert_layer(layer, None, 0)
    raw = bytes([128, 128, 128, 255]) * (w * h)
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", raw)
    layer.update(0, 0, w, h)
    return img, layer

def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    return w, h, raw

def call(img, layer, **kw):
    proc = pdb.lookup_procedure("python-fu-dnb-flow")
    if proc is None:
        die("procedure missing")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    base = dict(mode="dodge", x1=40.0, y1=70.0, x2=180.0, y2=70.0,
                radius=22.0, flow=55.0, opacity=20.0, hardness=0.0, spacing=0.18, pressure=-1.0)
    base.update(kw)
    for k, v in base.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        die("status %s %s" % (res.index(0), err))

def max_delta(raw, before, w, h):
    md = 0
    mx = my = 0
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            d = raw[i] - before[i]
            if d > md:
                md = d
                mx, my = x, y
    return md, mx, my

def outside(raw, before, w, h, pred):
    n = 0
    for y in range(h):
        for x in range(w):
            if not pred(x, y):
                continue
            i = (y * w + x) * 4
            if raw[i:i + 4] != before[i:i + 4]:
                n += 1
    return n

img, layer = grey_image()
w, h, before = pixels(layer)
call(img, layer)
_, _, one = pixels(layer)
d1, x1, y1 = max_delta(one, before, w, h)
cap = 127.0 * 0.20
# center of the stroke should have climbed most of the way to the cap
center = one[(70 * w + 110) * 4] - 128
far = outside(one, before, w, h, lambda x, y: y < 30 or y > 110)
# smoothness along the middle of the stroke
jumps = 0
prev = one[(70 * w + 50) * 4]
for x in range(51, 170):
    v = one[(70 * w + x) * 4]
    if abs(v - prev) > jumps:
        jumps = abs(v - prev)
    prev = v
print("FLOW_TEST one max_delta=%d at %d,%d center=%d cap=%.1f far=%d max_step=%d" % (
    d1, x1, y1, center, cap, far, jumps), flush=True)
if d1 > int(cap + 1.01):
    die("one stroke passed the opacity cap: %d > %.1f" % (d1, cap))
if d1 < cap * 0.80:
    die("overlapping dabs did not approach the cap: %d vs %.1f" % (d1, cap))
if far != 0:
    die("pixels outside the radius changed")
if jumps > 4:
    die("stroke is blotchy, adjacent step %d" % jumps)

call(img, layer)
_, _, two = pixels(layer)
d2, _, _ = max_delta(two, before, w, h)
# second stroke's own step must also respect the cap against the pixels it started from
over = 0
peak_step = 0
for y in range(h):
    for x in range(w):
        i = (y * w + x) * 4
        step = two[i] - one[i]
        if step > peak_step:
            peak_step = step
        room = (255 - one[i]) * 0.20
        if step > room + 1.01:
            over += 1
far2 = outside(two, before, w, h, lambda x, y: y < 30 or y > 110)
print("FLOW_TEST two max_delta=%d second_step=%d over_cap=%d far=%d" % (d2, peak_step, over, far2), flush=True)
if d2 <= d1:
    die("second stroke did not build further")
if over != 0:
    die("second stroke stepped past its own opacity cap")
if far2 != 0:
    die("second stroke touched pixels outside the radius")
img.delete()

# burn stays within its cap and goes darker
img, layer = grey_image()
w, h, before = pixels(layer)
call(img, layer, mode="burn")
_, _, burnt = pixels(layer)
drop = 0
for y in range(h):
    for x in range(w):
        i = (y * w + x) * 4
        drop = max(drop, before[i] - burnt[i])
print("FLOW_TEST burn max_drop=%d cap=%.1f" % (drop, 128 * 0.20), flush=True)
if drop > int(128 * 0.20 + 1.01):
    die("burn passed the cap")
if drop < 128 * 0.20 * 0.80:
    die("burn did not approach the cap")
img.delete()

print("FLOW_TEST OK", flush=True)
