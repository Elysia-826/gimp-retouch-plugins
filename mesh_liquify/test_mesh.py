# Headless functional test for python-fu-mesh-liquify. Run with python-fu-eval.
# Generates its own patterns. Prints MESH_TEST lines. Exits by raising on failure.
import math, os, struct, time
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl

Gegl.init(None)
pdb = Gimp.get_pdb()

def die(msg):
    print("MESH_TEST FAIL " + msg, flush=True)
    raise SystemExit(1)

def pixels(layer, fmt):
    w, h = layer.get_width(), layer.get_height()
    rect = Gegl.Rectangle.new(0, 0, w, h)
    raw = layer.get_buffer().get(rect, 1.0, fmt, Gegl.AbyssPolicy.NONE)
    return w, h, bytes(raw)

def paint(layer, fmt, bpp, fn):
    w, h = layer.get_width(), layer.get_height()
    buf = bytearray(w * h * bpp)
    fn(buf, w, h, bpp)
    rect = Gegl.Rectangle.new(0, 0, w, h)
    layer.get_buffer().set(rect, fmt, bytes(buf))
    layer.update(0, 0, w, h)
    return pixels(layer, fmt)

def new_image(w, h, base, ltype, fmt, bpp, fn):
    img = Gimp.Image.new(w, h, base)
    layer = Gimp.Layer.new(img, "test", w, h, ltype, 100.0, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, 0)
    before = paint(layer, fmt, bpp, fn)
    return img, layer, before

def call(img, layer, **kw):
    proc = pdb.lookup_procedure("python-fu-mesh-liquify")
    if proc is None:
        die("procedure missing")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", [layer]) if hasattr(cfg, "set_core_object_array") else cfg.set_property("drawables", [layer])
    for k, v in kw.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    st = res.index(0)
    if st != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        die("status %s %s args %s" % (st, err, kw))

def changed(a, b):
    n = 0
    # a,b bytes, compare per pixel of bpp
    if a == b:
        return 0
    # count differing pixels assuming bpp from equal length
    return 1 if a != b else 0

def count_diff(a, b, w, h, bpp, pred):
    n = 0
    maxch = 0
    for y in range(h):
        for x in range(w):
            if not pred(x, y):
                continue
            i = (y * w + x) * bpp
            d = 0
            for c in range(bpp):
                d = max(d, abs(a[i + c] - b[i + c]))
            if d:
                n += 1
                if d > maxch:
                    maxch = d
    return n, maxch

def centroid(raw, w, h, bpp, pred):
    sx = sy = n = 0
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * bpp
            if pred(raw, i):
                sx += x
                sy += y
                n += 1
    if n == 0:
        return None
    return sx / n, sy / n, n

def grid_face(buf, w, h, bpp):
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * bpp
            r = 40 + (x * 3) % 50
            g = 80 + (y * 5) % 40
            b = 140
            # grid lines
            if x % 20 == 0 or y % 20 == 0:
                r, g, b = 20, 20, 20
            # face-like disc
            dx, dy = x - w * 0.45, y - h * 0.48
            if dx * dx + dy * dy < (min(w, h) * 0.18) ** 2:
                r, g, b = 210, 170, 150
            # red marker just right of center-left, used to measure push
            if abs(x - 120) <= 2 and abs(y - 100) <= 2:
                r, g, b = 255, 0, 0
            buf[i] = r
            if bpp > 1:
                buf[i + 1] = g
            if bpp > 2:
                buf[i + 2] = b
            if bpp > 3:
                buf[i + 3] = 255

print("MESH_TEST proc", pdb.lookup_procedure("python-fu-mesh-liquify") is not None, flush=True)

# --- RGB push ---
img, layer, (w, h, before) = new_image(
    240, 180, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
print("MESH_TEST empty_selection", Gimp.Selection.is_empty(img), flush=True)
t0 = time.perf_counter()
call(img, layer, mode="push", x1=120.0, y1=100.0, x2=-1.0, y2=-1.0,
     radius=50.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True)
dt = time.perf_counter() - t0
_, _, after = pixels(layer, "R'G'B'A u8")
# outside brush (radius 50 around 120,100) must be identical
out_n, out_max = count_diff(before, after, w, h, 4, lambda x, y: (x - 120) ** 2 + (y - 100) ** 2 > 52 ** 2)
in_n, in_max = count_diff(before, after, w, h, 4, lambda x, y: (x - 120) ** 2 + (y - 100) ** 2 <= 48 ** 2)
c0 = centroid(before, w, h, 4, lambda raw, i: raw[i] > 250 and raw[i + 1] < 5 and raw[i + 2] < 5)
c1 = centroid(after, w, h, 4, lambda raw, i: raw[i] > 200 and raw[i + 1] < 40 and raw[i + 2] < 40)
if c0 is None or c1 is None:
    die("red marker missing c0=%s c1=%s" % (c0, c1))
shift = c1[0] - c0[0]
print("MESH_TEST push outside=%d/%d inside=%d maxch=%d shift=%.2f (from %.1f) time=%.2fs" % (
    out_n, out_max, in_n, in_max, shift, c0[0], dt), flush=True)
if out_n != 0:
    die("push changed pixels outside the brush")
if in_n < 50:
    die("push moved too few pixels")
# strength 80, radius 50 => about 20px. Soft brush, marker is at center so ~15-24.
if shift < 8:
    die("push shift too small: %.2f" % shift)

# straight stroke push further right, different place
call(img, layer, mode="push", x1=40.0, y1=40.0, x2=90.0, y2=40.0,
     radius=18.0, strength=70.0, hardness=0.0, angle=90.0, clockwise=True)
_, _, after2 = pixels(layer, "R'G'B'A u8")
# far corner must still match the original (never inside either brush)
corner = count_diff(before, after2, w, h, 4, lambda x, y: x > 200 and y > 150)
print("MESH_TEST stroke_corner_diff %d" % corner[0], flush=True)
if corner[0] != 0:
    die("stroke touched the far corner")
seg_n, _ = count_diff(after, after2, w, h, 4, lambda x, y: abs(y - 40) < 16 and 30 < x < 100)
print("MESH_TEST stroke_moved %d" % seg_n, flush=True)
if seg_n < 20:
    die("stroke push did not move pixels along the segment")

# --- bloat then restore ---
img2, layer2, (w2, h2, b0) = new_image(
    200, 200, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
cx, cy, rad = 100.0, 100.0, 60.0
call(img2, layer2, mode="bloat", x1=cx, y1=cy, x2=-1.0, y2=-1.0,
     radius=rad, strength=90.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, b1 = pixels(layer2, "R'G'B'A u8")
bn, bmax = count_diff(b0, b1, w2, h2, 4, lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= 55 ** 2)
bo, _ = count_diff(b0, b1, w2, h2, 4, lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 > 63 ** 2)
# a pixel on the ring should move outward: sample the red marker if it is inside, else compare a known grid pixel's movement via mean radius of dark grid? 
# Use centroid of the face-colored disc... simpler: mean distance from center of pixels that CHANGED is not the metric.
# Check a single channel ridge: pixel that was unique. We'll measure how far the value at the center moved back on restore.
center_i = (int(cy) * w2 + int(cx)) * 4
print("MESH_TEST bloat inside=%d maxch=%d outside=%d center %s -> %s" % (
    bn, bmax, bo, list(b0[center_i:center_i+4]), list(b1[center_i:center_i+4])), flush=True)
if bo != 0:
    die("bloat changed pixels outside the brush")
if bn < 100:
    die("bloat moved too few pixels")
call(img2, layer2, mode="restore", x1=cx, y1=cy, x2=-1.0, y2=-1.0,
     radius=rad, strength=100.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, b2 = pixels(layer2, "R'G'B'A u8")
# center falloff is 1, so center pixel must match the original exactly
if b2[center_i:center_i+4] != b0[center_i:center_i+4]:
    die("restore did not return the center pixel: %s vs %s" % (list(b2[center_i:center_i+4]), list(b0[center_i:center_i+4])))
rn, _ = count_diff(b0, b2, w2, h2, 4, lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= 55 ** 2)
print("MESH_TEST restore remaining_inside=%d (was %d) center_ok=1" % (rn, bn), flush=True)
if rn >= bn:
    die("restore did not reduce the difference")

# marker on a gradient: bloat moves it outward, restore brings it back
def grad(buf, w, h, bpp):
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * bpp
            buf[i] = x % 256
            buf[i+1] = y % 256
            buf[i+2] = 30
            buf[i+3] = 255
            if abs(x - 130) <= 2 and abs(y - 100) <= 2:
                buf[i], buf[i+1], buf[i+2] = 255, 0, 0

imgm, laym, (wm, hm, m0) = new_image(
    200, 200, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grad)
def redc(raw):
    return centroid(raw, wm, hm, 4, lambda b, i: b[i] > 240 and b[i+1] < 20 and b[i+2] < 20)
call(imgm, laym, mode="bloat", x1=100.0, y1=100.0, x2=-1.0, y2=-1.0,
     radius=70.0, strength=90.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, m1 = pixels(laym, "R'G'B'A u8")
call(imgm, laym, mode="restore", x1=100.0, y1=100.0, x2=-1.0, y2=-1.0,
     radius=70.0, strength=100.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, m2 = pixels(laym, "R'G'B'A u8")
c0, c1, c2 = redc(m0), redc(m1), redc(m2)
print("MESH_TEST marker %s -> bloat %s -> restore %s" % (c0, c1, c2), flush=True)
if not c0 or not c1 or not c2:
    die("marker missing")
outward = c1[0] - c0[0]
back = c2[0] - c0[0]
print("MESH_TEST bloat_shift=%.2f restore_shift=%.2f" % (outward, back), flush=True)
if outward < 4:
    die("bloat did not move marker outward")
if abs(back) > abs(outward) * 0.6:
    die("restore did not bring marker back")
mo, _ = count_diff(m0, m1, wm, hm, 4, lambda x, y: (x-100)**2+(y-100)**2 > 74**2)
if mo != 0:
    die("marker bloat touched outside")
imgm.delete()

# pinch and twirl just have to move something and spare the outside
for mode, extra in (("pinch", {}), ("twirl", {"clockwise": False})):
    im, ly, (ww, hh, src) = new_image(
        160, 160, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
    call(im, ly, mode=mode, x1=80.0, y1=80.0, x2=-1.0, y2=-1.0,
         radius=40.0, strength=80.0, hardness=0.2, angle=0.0, clockwise=extra.get("clockwise", True))
    _, _, dst = pixels(ly, "R'G'B'A u8")
    inn, _ = count_diff(src, dst, ww, hh, 4, lambda x, y: (x-80)**2+(y-80)**2 <= 36**2)
    out, _ = count_diff(src, dst, ww, hh, 4, lambda x, y: (x-80)**2+(y-80)**2 > 43**2)
    print("MESH_TEST %s inside=%d outside=%d" % (mode, inn, out), flush=True)
    if out != 0 or inn < 30:
        die("%s failed inside=%d outside=%d" % (mode, inn, out))
    im.delete()

# --- selection: right half protected ---
img3, layer3, (w3, h3, s0) = new_image(
    180, 120, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
img3.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 90, 120)
print("MESH_TEST selection_empty", Gimp.Selection.is_empty(img3), flush=True)
call(img3, layer3, mode="push", x1=80.0, y1=60.0, x2=-1.0, y2=-1.0,
     radius=40.0, strength=100.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, s1 = pixels(layer3, "R'G'B'A u8")
# x>=90 is outside the selection (rectangle is [0,90)). Allow 1px edge ambiguity, check x>=94
prot, _ = count_diff(s0, s1, w3, h3, 4, lambda x, y: x >= 94)
left, _ = count_diff(s0, s1, w3, h3, 4, lambda x, y: x <= 70 and abs(y-60) < 30)
print("MESH_TEST selection protected=%d moved_left=%d" % (prot, left), flush=True)
if prot != 0:
    die("selection did not protect the right side")
if left < 10:
    die("selection blocked the whole brush")
img3.delete()

# --- grayscale, no alpha ---
def gray_paint(buf, w, h, bpp):
    for y in range(h):
        for x in range(w):
            buf[(y * w + x) * bpp] = (x * 2 + y) % 256
img4, layer4, (w4, h4, g0) = new_image(
    100, 80, Gimp.ImageBaseType.GRAY, Gimp.ImageType.RGBA_IMAGE, "Y' u8", 1, gray_paint)
call(img4, layer4, mode="bloat", x1=40.0, y1=40.0, x2=-1.0, y2=-1.0,
     radius=24.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, g1 = pixels(layer4, "Y' u8")
gn, _ = count_diff(g0, g1, w4, h4, 1, lambda x, y: True)
go, _ = count_diff(g0, g1, w4, h4, 1, lambda x, y: (x-40)**2+(y-40)**2 > 27**2)
print("MESH_TEST gray changed=%d outside=%d" % (gn, go), flush=True)
if gn < 10 or go != 0:
    die("grayscale failed")
img4.delete()

# --- alpha: transparent corner stays, semi-transparent blob moves ---
def alpha_paint(buf, w, h, bpp):
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * bpp
            buf[i:i+3] = b"\x10\x80\xc0"
            buf[i+3] = 0
            if abs(x - 50) <= 3 and abs(y - 50) <= 3:
                buf[i:i+3] = b"\xff\x20\x20"
                buf[i+3] = 140
img5, layer5, (w5, h5, a0) = new_image(
    120, 120, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, alpha_paint)
call(img5, layer5, mode="push", x1=50.0, y1=50.0, x2=-1.0, y2=-1.0,
     radius=30.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, a1 = pixels(layer5, "R'G'B'A u8")
# corner alpha must stay 0
if a1[3] != 0 or a1[(10 * w5 + 10) * 4 + 3] != 0:
    die("alpha corner changed")
c_a0 = centroid(a0, w5, h5, 4, lambda raw, i: raw[i+3] > 100)
c_a1 = centroid(a1, w5, h5, 4, lambda raw, i: raw[i+3] > 80)
print("MESH_TEST alpha centroid %s -> %s" % (c_a0, c_a1), flush=True)
if c_a0 is None or c_a1 is None or c_a1[0] <= c_a0[0] + 2:
    die("alpha blob did not move right")
img5.delete()

# --- 2000px timing (long side) ---
def big_paint(buf, w, h, bpp):
    for y in range(0, h, 4):
        for x in range(w):
            i = (y * w + x) * bpp
            buf[i] = x % 251
            buf[i+1] = y % 251
            buf[i+2] = 80
            buf[i+3] = 255
    # fill the skipped rows cheaply
    for y in range(h):
        if y % 4 == 0:
            continue
        src = ((y - y % 4) * w) * bpp
        dst = (y * w) * bpp
        buf[dst:dst + w * bpp] = buf[src:src + w * bpp]
img6, layer6, _ = new_image(
    2000, 1400, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, big_paint)
t0 = time.perf_counter()
call(img6, layer6, mode="bloat", x1=1000.0, y1=700.0, x2=-1.0, y2=-1.0,
     radius=400.0, strength=50.0, hardness=0.0, angle=0.0, clockwise=True)
dt = time.perf_counter() - t0
print("MESH_TEST big2000 seconds=%.2f" % dt, flush=True)
if dt > 60:
    die("2000px bloat too slow: %.1fs" % dt)
img6.delete()

# hidden state group exists on the first image and is not visible
names = []
def dump(ls, ind=0):
    for l in ls:
        names.append((ind, l.get_name(), l.get_visible()))
        if l.is_group():
            dump(l.get_children(), ind+1)
dump(img.get_layers())
print("MESH_TEST layers", names, flush=True)
if not any((not vis) and "Liquify State" in n for _, n, vis in names):
    die("hidden state group missing")

img.delete()
img2.delete()

# --- freeze layer: right half white, brush straddles the edge ---
def half(buf, w, h, bpp):
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * bpp
            buf[i] = (x * 3) % 256
            buf[i+1] = (y * 5) % 256
            buf[i+2] = 40
            buf[i+3] = 255

imgf, layf, (wf, hf, f0) = new_image(
    180, 100, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, half)
fr = Gimp.Layer.new(imgf, "冻结", wf, hf, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
imgf.insert_layer(fr, None, 0)
rect = Gegl.Rectangle.new(0, 0, wf, hf)
fr.get_buffer().set(rect, "R'G'B'A u8", bytes([0, 0, 0, 255]) * (wf * hf))
rect2 = Gegl.Rectangle.new(110, 0, wf - 110, hf)
fr.get_buffer().set(rect2, "R'G'B'A u8", bytes([255, 255, 255, 255]) * ((wf - 110) * hf))
fr.update(0, 0, wf, hf)
Gimp.Selection.none(imgf)
call(imgf, layf, mode="push", x1=100.0, y1=50.0, x2=-1.0, y2=-1.0,
     radius=40.0, strength=80.0, hardness=0.0, angle=180.0, clockwise=True,
     **{"freeze": "layer", "freeze-layer": fr, "freeze-feather": 16.0})
_, _, f1 = pixels(layf, "R'G'B'A u8")
fz, fzmax = count_diff(f0, f1, wf, hf, 4, lambda x, y: x >= 110)
free, freemax = count_diff(f0, f1, wf, hf, 4, lambda x, y: x <= 90 and (x-100)**2+(y-50)**2 <= 36**2)
near, nearmax = count_diff(f0, f1, wf, hf, 4, lambda x, y: 100 <= x < 110 and abs(y-50) <= 8)
far, farmax = count_diff(f0, f1, wf, hf, 4, lambda x, y: 70 <= x <= 82 and abs(y-50) <= 8)
vis = fr.get_visible()
still = any(l.get_name() == "冻结" for l in imgf.get_layers())
state_hidden = None
for l in imgf.get_layers():
    if l.is_group() and "Liquify State" in l.get_name():
        state_hidden = (not l.get_visible())
print("MESH_TEST freeze_layer frozen=%d/%d free=%d near_max=%d far_max=%d visible=%s still=%s state_hidden=%s" % (
    fz, fzmax, free, nearmax, farmax, vis, still, state_hidden), flush=True)
if fz != 0:
    die("frozen pixels moved")
if vis or not still:
    die("freeze layer should stay and be hidden")
if state_hidden is not True:
    die("liquify state group visibility changed")
if free < 20:
    die("freeze blocked the free side")
if farmax <= nearmax:
    die("freeze edge was not softer than the free interior (near %d far %d)" % (nearmax, farmax))

# selection still limits, freeze is extra: only x<60 may be edited, freeze covers x>=40
imgf.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 60, hf)
# new image so the mesh is fresh
imgf.delete()
imgs, lays, (ws, hs, s0b) = new_image(
    180, 100, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, half)
frs = Gimp.Layer.new(imgs, "冻结", ws, hs, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
imgs.insert_layer(frs, None, 0)
frs.get_buffer().set(Gegl.Rectangle.new(0, 0, ws, hs), "R'G'B'A u8", bytes([0, 0, 0, 255]) * (ws * hs))
frs.get_buffer().set(Gegl.Rectangle.new(40, 0, ws - 40, hs), "R'G'B'A u8", bytes([255, 255, 255, 255]) * ((ws - 40) * hs))
frs.update(0, 0, ws, hs)
imgs.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0, 70, hs)
call(imgs, lays, mode="bloat", x1=50.0, y1=50.0, x2=-1.0, y2=-1.0,
     radius=30.0, strength=90.0, hardness=0.0, angle=0.0, clockwise=True,
     **{"freeze": "layer", "freeze-layer": frs, "freeze-feather": 8.0})
_, _, s1b = pixels(lays, "R'G'B'A u8")
outside_sel, _ = count_diff(s0b, s1b, ws, hs, 4, lambda x, y: x >= 72)
frozen2, _ = count_diff(s0b, s1b, ws, hs, 4, lambda x, y: x >= 40 and x < 70)
moved2, _ = count_diff(s0b, s1b, ws, hs, 4, lambda x, y: x <= 30 and abs(y-50) < 20)
print("MESH_TEST freeze_plus_selection outside=%d frozen=%d moved=%d" % (outside_sel, frozen2, moved2), flush=True)
if outside_sel != 0 or frozen2 != 0 or moved2 < 5:
    die("selection limit + freeze failed")
imgs.delete()

# selection turned into freeze (no extra edit limit)
imgt, layt, (wt, ht, t0b) = new_image(
    160, 80, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, half)
imgt.select_rectangle(Gimp.ChannelOps.REPLACE, 90, 0, 70, ht)
call(imgt, layt, mode="push", x1=80.0, y1=40.0, x2=-1.0, y2=-1.0,
     radius=36.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True,
     **{"freeze": "selection", "freeze-feather": 10.0})
_, _, t1b = pixels(layt, "R'G'B'A u8")
fz3, _ = count_diff(t0b, t1b, wt, ht, 4, lambda x, y: x >= 90)
mv3, _ = count_diff(t0b, t1b, wt, ht, 4, lambda x, y: x <= 70 and (x-80)**2+(y-40)**2 < 30**2)
print("MESH_TEST freeze_selection frozen=%d moved=%d" % (fz3, mv3), flush=True)
if fz3 != 0 or mv3 < 10:
    die("selection-as-freeze failed")
imgt.delete()


def _edge_paint(buf, w, h, bpp):
    # Wood on the left, textured skin on the right, soft boundary between.
    for y in range(h):
        for x in range(w):
            n = ((x * 13 + y * 3) % 11) - 5
            if x > 108:
                r = 160 + n
            elif x < 96:
                r = 42
            else:
                u = (x - 96) / 12.0
                r = (1.0 - u) * 42 + u * (160 + n)
            i = (y * w + x) * bpp
            buf[i] = max(0, min(255, int(r)))
            buf[i + 1] = buf[i]
            buf[i + 2] = buf[i]
            buf[i + 3] = 255

def _band_width(raw, w, h):
    # Longest run of pixels that are between the wood and the skin, per row.
    acc = rows = 0
    for y in range(25, 55):
        run = best = 0
        for x in range(w):
            v = raw[(y * w + x) * 4]
            if 55 < v < 150:
                run += 1
                if run > best:
                    best = run
            else:
                run = 0
        if best:
            acc += best
            rows += 1
    return acc / float(rows or 1)

def _hipass(raw, w):
    s = n = 0
    for y in range(20, 60):
        for x in range(130, 180):
            i = (y * w + x) * 4
            s += abs(raw[i] - raw[i + 4])
            n += 1
    return s / float(n)

def _run_edge(clean):
    flag = "/tmp/mesh-liquify-no-clean"
    if clean:
        if os.path.exists(flag):
            os.remove(flag)
    else:
        open(flag, "w").close()
    im, lay, (ew, eh, e0) = new_image(
        240, 80, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, _edge_paint)
    fr = Gimp.Layer.new(im, "冻结", ew, eh, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    im.insert_layer(fr, None, 0)
    fr.get_buffer().set(Gegl.Rectangle.new(0, 0, ew, eh), "R'G'B'A u8", bytes([0, 0, 0, 255]) * (ew * eh))
    fr.get_buffer().set(Gegl.Rectangle.new(0, 0, 90, eh), "R'G'B'A u8", bytes([255, 255, 255, 255]) * (90 * eh))
    fr.update(0, 0, ew, eh)
    Gimp.Selection.none(im)
    call(im, lay, mode="push", x1=120.0, y1=40.0, x2=-1.0, y2=-1.0,
         radius=70.0, strength=70.0, hardness=0.0, angle=0.0, clockwise=True,
         **{"freeze": "layer", "freeze-layer": fr, "freeze-feather": 40.0})
    _, _, e1 = pixels(lay, "R'G'B'A u8")
    wb = _band_width(e0, ew, eh)
    wa = _band_width(e1, ew, eh)
    hb = _hipass(e0, ew)
    ha = _hipass(e1, ew)
    fz, fzmax = count_diff(e0, e1, ew, eh, 4, lambda x, y: x < 90)
    hidden = (not fr.get_visible())
    state_ok = False
    for l in im.get_layers():
        if l.is_group() and "Liquify State" in l.get_name():
            state_ok = (not l.get_visible())
    im.delete()
    return wb, wa, hb, ha, fz, fzmax, hidden, state_ok

wb, wa, hb, ha, fz, fzmax, hidden, state_ok = _run_edge(True)
wb0, wa0, hb0, ha0, fz0, fzmax0, _, _ = _run_edge(False)
flag = "/tmp/mesh-liquify-no-clean"
if os.path.exists(flag):
    os.remove(flag)
print("MESH_TEST edge_clean before_width=%.2f after_width=%.2f noclean_after=%.2f hipass %.3f -> %.3f (noclean %.3f) frozen=%d/%d hidden=%s state=%s" % (
    wb, wa, wa0, hb, ha, ha0, fz, fzmax, hidden, state_ok), flush=True)
if fz != 0 or fz0 != 0:
    die("edge test moved frozen pixels")
if not hidden or not state_ok:
    die("edge test changed freeze or state visibility")
if wa >= wa0 - 0.5:
    die("edge reconstruct did not narrow the boundary (%.2f vs %.2f)" % (wa, wa0))
if wa > wb + 1.5:
    die("boundary still wider than the original (%.2f vs %.2f)" % (wa, wb))
if ha < hb * 0.75:
    die("skin texture high-pass dropped (%.3f vs %.3f)" % (ha, hb))


def call_named(name, img, layer, **kw):
    proc = pdb.lookup_procedure(name)
    if proc is None:
        die("procedure missing " + name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    cfg.set_core_object_array("drawables", [layer]) if hasattr(cfg, "set_core_object_array") else cfg.set_property("drawables", [layer])
    for k, v in kw.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    st = res.index(0)
    if st != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        die("status %s %s %s" % (name, st, err))

def _stroke_named(img):
    for l in img.get_layers():
        if l.get_name() == "液化笔触":
            return l
    return None

def _paint_bar(layer, x0, x1, y0, y1):
    w, h = layer.get_width(), layer.get_height()
    raw = bytearray(layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    xa, xb = min(x0, x1), max(x0, x1)
    ya, yb = min(y0, y1), max(y0, y1)
    for y in range(max(0, ya), min(h, yb + 1)):
        for x in range(max(0, xa), min(w, xb + 1)):
            i = (y * w + x) * 4
            raw[i:i + 4] = b"\xff\xff\xff\xff"
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", bytes(raw))
    layer.update(0, 0, w, h)

# prepare: transparent layer, no liquify state yet
imgb, layb, _ = new_image(
    180, 110, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
call_named("python-fu-mesh-liquify-stroke-layer", imgb, layb)
stlay = _stroke_named(imgb)
if stlay is None:
    die("stroke layer was not created")
groups = [l for l in imgb.get_layers() if l.is_group() and "Liquify" in l.get_name()]
alpha = bytes(stlay.get_buffer().get(Gegl.Rectangle.new(10, 10, 1, 1), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
sel = imgb.get_selected_layers()
print("MESH_TEST stroke_prepare name=%s alpha=%s groups=%d selected=%s" % (
    stlay.get_name(), list(alpha), len(groups), sel[0].get_name() if sel else None), flush=True)
if list(alpha) != [0, 0, 0, 0] or groups or not sel or sel[0] != stlay:
    die("stroke prepare layer is wrong")
call_named("python-fu-mesh-liquify-stroke-layer", imgb, layb)
if sum(1 for l in imgb.get_layers() if l.get_name() == "液化笔触") != 1:
    die("second prepare created a duplicate stroke layer")

# horizontal painted stroke pushes a marker to the right
_paint_bar(stlay, 30, 150, 98, 102)
call(imgb, layb, mode="push", path="layer", **{"stroke-layer": stlay},
     x1=-1.0, y1=-1.0, x2=-1.0, y2=-1.0,
     radius=26.0, strength=80.0, hardness=0.0, angle=90.0, clockwise=True)
_, _, sb = pixels(layb, "R'G'B'A u8")
# grid_face marker starts at x=120, y=100, on the painted horizontal stroke.
c1 = centroid(sb, 180, 110, 4, lambda raw, i: raw[i] > 200 and raw[i + 1] < 40 and raw[i + 2] < 40)
print("MESH_TEST stroke_push marker=%s hidden=%s still=%s" % (
    c1, (not stlay.get_visible()), _stroke_named(imgb) is not None), flush=True)
if c1 is None or c1[0] < 126:
    die("painted stroke did not push the marker right: %s" % (c1,))
if stlay.get_visible() or _stroke_named(imgb) is None:
    die("stroke layer should stay and be hidden")
state_ok = any(l.is_group() and (not l.get_visible()) and "Liquify" in l.get_name() for l in imgb.get_layers())
if not state_ok:
    die("liquify state group missing or visible after stroke push")
imgb.delete()

# vertical stroke pushes down; freeze on the lower part stays put
imgv, layv, (wv, hv, v0) = new_image(
    160, 140, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4, grid_face)
call_named("python-fu-mesh-liquify-stroke-layer", imgv, layv)
stv = _stroke_named(imgv)
_paint_bar(stv, 78, 82, 20, 120)
frv = Gimp.Layer.new(imgv, "冻结", wv, hv, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
imgv.insert_layer(frv, None, 0)
frv.get_buffer().set(Gegl.Rectangle.new(0, 0, wv, hv), "R'G'B'A u8", bytes([0, 0, 0, 255]) * (wv * hv))
frv.get_buffer().set(Gegl.Rectangle.new(0, 100, wv, hv - 100), "R'G'B'A u8", bytes([255, 255, 255, 255]) * (wv * (hv - 100)))
frv.update(0, 0, wv, hv)
Gimp.Selection.none(imgv)
call(imgv, layv, mode="push", path="layer", **{"stroke-layer": stv, "freeze": "layer", "freeze-layer": frv, "freeze-feather": 8.0},
     x1=-1.0, y1=-1.0, x2=-1.0, y2=-1.0,
     radius=22.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, v1 = pixels(layv, "R'G'B'A u8")
fz, fzmax = count_diff(v0, v1, wv, hv, 4, lambda x, y: y >= 100)
moved, _ = count_diff(v0, v1, wv, hv, 4, lambda x, y: y <= 70 and abs(x - 80) <= 18)
print("MESH_TEST stroke_freeze frozen=%d/%d moved=%d stroke_hidden=%s freeze_hidden=%s" % (
    fz, fzmax, moved, (not stv.get_visible()), (not frv.get_visible())), flush=True)
if fz != 0 or moved < 10:
    die("stroke+freeze failed")
if stv.get_visible() or frv.get_visible():
    die("stroke or freeze layer stayed visible")
imgv.delete()


def _state_hidden(img):
    groups = [l for l in img.get_layers() if l.is_group() and "Liquify" in l.get_name()]
    return groups

# two strokes, undo one matches only the first, undo again matches the original
imgu, layu, (wu, hu, uorig) = new_image(
    180, 100, Gimp.ImageBaseType.RGB, Gimp.ImageType.RGBA_IMAGE, "R'G'B'A u8", 4,
    lambda buf, w, h, bpp: (
        [buf.__setitem__(slice((y * w + x) * bpp, (y * w + x) * bpp + 4),
                         bytes([255, 40, 40, 255] if 36 <= x <= 40 and 30 <= y <= 70 else [70, 110, 160, 255]))
         for y in range(h) for x in range(w)]))
fru = Gimp.Layer.new(imgu, "冻结", wu, hu, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
imgu.insert_layer(fru, None, 0)
fru.get_buffer().set(Gegl.Rectangle.new(0, 0, wu, hu), "R'G'B'A u8", bytes([0, 0, 0, 255]) * (wu * hu))
fru.get_buffer().set(Gegl.Rectangle.new(140, 0, wu - 140, hu), "R'G'B'A u8", bytes([255, 255, 255, 255]) * ((wu - 140) * hu))
fru.update(0, 0, wu, hu)
Gimp.Selection.none(imgu)
call(imgu, layu, mode="push", path="line", freeze="layer", **{"freeze-layer": fru, "freeze-feather": 8.0},
     x1=40.0, y1=50.0, x2=-1.0, y2=-1.0,
     radius=22.0, strength=80.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, us1 = pixels(layu, "R'G'B'A u8")
call(imgu, layu, mode="push", path="line", freeze="layer", **{"freeze-layer": fru, "freeze-feather": 8.0},
     x1=100.0, y1=50.0, x2=-1.0, y2=-1.0,
     radius=36.0, strength=70.0, hardness=0.0, angle=0.0, clockwise=True)
_, _, us2 = pixels(layu, "R'G'B'A u8")
if us1 == us2 or us1 == uorig:
    die("two strokes did not change pixels in two steps")
fz2, _ = count_diff(uorig, us2, wu, hu, 4, lambda x, y: x >= 140)
if fz2 != 0:
    die("frozen pixels moved after two strokes: %d" % fz2)
call_named("python-fu-mesh-liquify-undo", imgu, layu)
_, _, uu1 = pixels(layu, "R'G'B'A u8")
d1, _ = count_diff(us1, uu1, wu, hu, 4, lambda x, y: True)
d2, _ = count_diff(us2, uu1, wu, hu, 4, lambda x, y: True)
fz1, _ = count_diff(uorig, uu1, wu, hu, 4, lambda x, y: x >= 140)
st1 = _state_hidden(imgu)
print("MESH_TEST undo1 diff_vs_stroke1=%d diff_vs_stroke2=%d frozen=%d groups=%d hidden=%s" % (
    d1, d2, fz1, len(st1), all(not g.get_visible() for g in st1)), flush=True)
if d1 != 0 or d2 == 0 or fz1 != 0 or len(st1) != 1 or st1[0].get_visible():
    die("undo one stroke did not restore the first stroke")
call_named("python-fu-mesh-liquify-undo", imgu, layu)
_, _, uu0 = pixels(layu, "R'G'B'A u8")
d0, _ = count_diff(uorig, uu0, wu, hu, 4, lambda x, y: True)
st0 = _state_hidden(imgu)
print("MESH_TEST undo2 diff_vs_original=%d groups=%d hidden=%s" % (
    d0, len(st0), all(not g.get_visible() for g in st0)), flush=True)
if d0 != 0 or len(st0) != 1 or st0[0].get_visible():
    die("undo both strokes did not match the original, or the hidden group was removed")
call_named("python-fu-mesh-liquify-redo", imgu, layu)
_, _, ur1 = pixels(layu, "R'G'B'A u8")
dr, _ = count_diff(us1, ur1, wu, hu, 4, lambda x, y: True)
print("MESH_TEST redo1 diff_vs_stroke1=%d" % dr, flush=True)
if dr != 0:
    die("redo did not restore the first stroke")
call_named("python-fu-mesh-liquify-redo", imgu, layu)
_, _, ur2 = pixels(layu, "R'G'B'A u8")
dr2, _ = count_diff(us2, ur2, wu, hu, 4, lambda x, y: True)
fzr, _ = count_diff(uorig, ur2, wu, hu, 4, lambda x, y: x >= 140)
print("MESH_TEST redo2 diff_vs_stroke2=%d frozen=%d freeze_hidden=%s" % (
    dr2, fzr, (not fru.get_visible())), flush=True)
if dr2 != 0 or fzr != 0 or fru.get_visible():
    die("redo second stroke failed")
imgu.delete()

print("MESH_TEST OK", flush=True)
