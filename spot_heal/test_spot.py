# Headless tests for python-fu-spot-heal.
import os
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl

Gegl.init(None)
pdb = Gimp.get_pdb()

def die(msg):
    print("SPOT_TEST FAIL " + msg, flush=True)
    raise SystemExit(1)

def noise_at(x, y):
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return 148 + (n % 27) - 13

def paint(layer, fn):
    w, h = layer.get_width(), layer.get_height()
    bpp = 4
    buf = bytearray(w * h * bpp)
    fn(buf, w, h, bpp)
    rect = Gegl.Rectangle.new(0, 0, w, h)
    layer.get_buffer().set(rect, "R'G'B'A u8", bytes(buf))
    layer.update(0, 0, w, h)

def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = bytes(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    return w, h, raw

def lum(raw, i):
    return (raw[i] * 54 + raw[i + 1] * 183 + raw[i + 2] * 19) >> 8

def call(img, layer, **kw):
    proc = pdb.lookup_procedure("python-fu-spot-heal")
    if proc is None:
        die("procedure missing")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    for k, v in kw.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    st = res.index(0)
    if st != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        die("status %s %s" % (st, err))

def call_status(img, layer, **kw):
    proc = pdb.lookup_procedure("python-fu-spot-heal")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    for k, v in kw.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    err = ""
    if res.index(0) != Gimp.PDBStatusType.SUCCESS and res.length() > 1 and res.index(1) is not None:
        err = str(res.index(1))
    return res.index(0), err

def skin(buf, w, h, bpp, spot, hair, spot_v=28):
    for y in range(h):
        for x in range(w):
            v = noise_at(x, y)
            if spot and (x - 90) * (x - 90) + (y - 80) * (y - 80) <= 36:
                v = spot_v
            if hair and x == 90 and 24 <= y <= 136:
                v = 16
            i = (y * w + x) * bpp
            g = v - 6 if v >= 6 else 0
            b = v - 16 if v >= 16 else 0
            buf[i] = v
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = 255

def mean_std(raw, w, pred):
    acc = acc2 = n = 0
    h = len(raw) // (w * 4)
    for y in range(h):
        for x in range(w):
            if not pred(x, y):
                continue
            v = lum(raw, (y * w + x) * 4)
            acc += v
            acc2 += v * v
            n += 1
    if n == 0:
        return 0, 0, 0
    mean = acc / float(n)
    var = acc2 / float(n) - mean * mean
    if var < 0:
        var = 0
    return mean, var ** 0.5, n

def count_diff(a, b, w, h, pred):
    n = 0
    for y in range(h):
        for x in range(w):
            if not pred(x, y):
                continue
            i = (y * w + x) * 4
            if a[i:i + 4] != b[i:i + 4]:
                n += 1
    return n

# --- spot on noisy skin ---
img = Gimp.Image.new(180, 160, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(img, "skin", 180, 160, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(layer, None, 0)
paint(layer, lambda buf, w, h, bpp: skin(buf, w, h, bpp, True, False))
w, h, before = pixels(layer)
mb, sb, nb = mean_std(before, w, lambda x, y: (x - 90) ** 2 + (y - 80) ** 2 <= 16)
call(img, layer, x=90.0, y=80.0, radius=12.0, x2=-1.0, y2=-1.0, x3=-1.0, y3=-1.0)
w, h, after = pixels(layer)
ma, sa, na = mean_std(after, w, lambda x, y: (x - 90) ** 2 + (y - 80) ** 2 <= 16)
# texture in a ring that the brush should not flatten: just outside the spot but
# the heal only replaces the selection, so this ring must stay byte-identical.
ring_diff = count_diff(before, after, w, h, lambda x, y: 16 <= (x - 90) ** 2 + (y - 80) ** 2 <= 22 * 22 and (x - 90) ** 2 + (y - 80) ** 2 > 12 * 12)
# wait, selection is radius 12, so outside r=12 must be identical. ring between 13 and 22:
out_diff = count_diff(before, after, w, h, lambda x, y: (x - 90) ** 2 + (y - 80) ** 2 > 14.0 * 14.0)
far = count_diff(before, after, w, h, lambda x, y: x < 40 or y < 30 or x > 140)
patch_m, patch_s, _ = mean_std(before, w, lambda x, y: 20 <= x < 40 and 20 <= y < 40)
print("SPOT_TEST spot before_mean=%.1f after_mean=%.1f after_std=%.2f skin_std=%.2f outside=%d far=%d" % (
    mb, ma, sa, patch_s, out_diff, far), flush=True)
if mb > 80:
    die("spot was not dark before")
if ma < 110:
    die("spot center still dark: %.1f" % ma)
if sa < patch_s * 0.35:
    die("healed spot went flat (std %.2f vs skin %.2f)" % (sa, patch_s))
if out_diff != 0 or far != 0:
    die("pixels outside the click changed (beyond radius+2)")
img.delete()

# --- hair line through the spot ---
img = Gimp.Image.new(180, 160, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(img, "hair", 180, 160, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(layer, None, 0)
paint(layer, lambda buf, w, h, bpp: skin(buf, w, h, bpp, True, True, 96))
w, h, before = pixels(layer)
call(img, layer, x=90.0, y=80.0, radius=12.0, x2=-1.0, y2=-1.0, x3=-1.0, y3=-1.0)
w, h, after = pixels(layer)
# line pixel restored
i = (80 * w + 90) * 4
line_l = lum(after, i)
left_l = lum(after, (80 * w + 82) * 4)
right_l = lum(after, (80 * w + 98) * 4)
dark = 0
for x in range(78, 103):
    if lum(after, (80 * w + x) * 4) < 70:
        dark += 1
# hair outside the brush stays
hair_far = lum(after, (40 * w + 90) * 4)
hair_far_b = lum(before, (40 * w + 90) * 4)
side = mean_std(after, w, lambda x, y: abs(y - 80) <= 3 and 4 <= abs(x - 90) <= 8)
print("SPOT_TEST hair line=%d side=%.1f contrast=%d dark_px=%d hair_far %d->%d" % (
    line_l, (left_l + right_l) / 2.0, int((left_l + right_l) / 2 - line_l), dark, hair_far_b, hair_far), flush=True)
if line_l > 60:
    die("hair through the spot was painted over: lum %d" % line_l)
if (left_l + right_l) / 2 - line_l < 40:
    die("hair is no longer darker than the healed skin")
if dark > 3:
    die("hair smeared into a wide band (%d px)" % dark)
if hair_far != hair_far_b:
    die("hair outside the brush changed")
# spot beside the hair is gone
side_mean = side[0]
print("SPOT_TEST hair_side_mean=%.1f" % side_mean, flush=True)
if side_mean < 100:
    die("blemish beside the hair is still dark: %.1f" % side_mean)
img.delete()

# clicking the hair itself, away from any spot, must refuse
img = Gimp.Image.new(180, 160, Gimp.ImageBaseType.RGB)
layer = Gimp.Layer.new(img, "onlyhair", 180, 160, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
img.insert_layer(layer, None, 0)
paint(layer, lambda buf, w, h, bpp: skin(buf, w, h, bpp, False, True))
w, h, before = pixels(layer)
st, err = call_status(img, layer, x=90.0, y=80.0, radius=10.0, x2=-1.0, y2=-1.0, x3=-1.0, y3=-1.0)
w, h, after = pixels(layer)
diff = count_diff(before, after, w, h, lambda x, y: True)
print("SPOT_TEST refuse_hair status=%s diff=%d err=%s" % (st, diff, err[:60]), flush=True)
if st == Gimp.PDBStatusType.SUCCESS or diff != 0:
    die("click on hair should change nothing")
img.delete()

print("SPOT_TEST OK", flush=True)
