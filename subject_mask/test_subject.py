# Headless tests for python-fu-subject-select. Run with python-fu-eval.
import array
import json
import os

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio

Gegl.init(None)
pdb = Gimp.get_pdb()


def die(msg):
    print("SUBJ_TEST FAIL " + msg, flush=True)
    raise SystemExit(1)


def call(img, layer, mode, feather):
    proc = pdb.lookup_procedure("python-fu-subject-select")
    if proc is None:
        die("procedure missing")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    cfg.set_property("mode", mode)
    cfg.set_property("feather", float(feather))
    return proc.run(cfg)


def status_ok(res):
    st = res.index(0)
    name = getattr(st, "value_nick", None) or str(st)
    return ("SUCCESS" in str(name).upper()) or str(st).endswith("SUCCESS") or str(st) == "3"


def layer_bytes(layer):
    w, h = layer.get_width(), layer.get_height()
    raw = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)
    return w, h, bytes(raw)


def selection_floats(img):
    w, h = img.get_width(), img.get_height()
    raw = img.get_selection().get_buffer().get(
        Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y float", Gegl.AbyssPolicy.NONE)
    vals = array.array("f")
    vals.frombytes(bytes(raw))
    if len(vals) != w * h:
        die("selection size %d != %d" % (len(vals), w * h))
    return w, h, vals


def mean_box(vals, w, x0, y0, x1, y1):
    acc = 0.0
    n = 0
    for y in range(y0, y1):
        row = y * w
        for x in range(x0, x1):
            acc += vals[row + x]
            n += 1
    return acc / float(n or 1)


def frac_box(vals, w, x0, y0, x1, y1, thresh):
    n = 0
    hit = 0
    for y in range(y0, y1):
        row = y * w
        for x in range(x0, x1):
            n += 1
            if vals[row + x] > thresh:
                hit += 1
    return hit / float(n or 1)


def write_preview(path, photo, pw, sel, sw, box):
    bx, by, bw, bh = box
    y1 = max(0, int(by) - 20)
    y2 = min(photo and len(photo) // (pw * 3) or 0, int(by + 0.48 * bh))
    # photo is RGB bytes, row stride pw*3. Crop width 480 max by stepping.
    x1 = 0
    x2 = pw
    ch = y2 - y1
    if ch < 2:
        return
    step = max(1, int(round(pw / 480.0)))
    out_w = (x2 - x1) // step
    out_h = ch // step
    raw = bytearray(out_w * out_h * 3)
    for oy in range(out_h):
        sy = y1 + oy * step
        for ox in range(out_w):
            sx = x1 + ox * step
            i = (sy * pw + sx) * 3
            s = sel[sy * sw + sx]
            r, g, b = photo[i], photo[i + 1], photo[i + 2]
            if s < 0.08:
                r, g, b = int(r * 0.25), int(g * 0.25), int(b * 0.25)
            o = (oy * out_w + ox) * 3
            raw[o] = r
            raw[o + 1] = g
            raw[o + 2] = b
    with open(path, "wb") as f:
        f.write(("P6\n%d %d\n255\n" % (out_w, out_h)).encode("ascii"))
        f.write(raw)
    print("SUBJ_TEST preview %s %dx%d" % (path, out_w, out_h), flush=True)


print("SUBJ_TEST begin", flush=True)

blob = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("/tmp/person_blob.png"))
layer = blob.get_layers()[0]
before = layer_bytes(layer)[2]
res = call(blob, layer, "subject", 2.0)
print("SUBJ_TEST blob_status", res.index(0), flush=True)
if not status_ok(res):
    die("blob subject failed")
after = layer_bytes(layer)[2]
if before != after:
    die("blob pixels changed")
bw, bh, sel = selection_floats(blob)
head = mean_box(sel, bw, 100, 110, 140, 140)
corner = mean_box(sel, bw, 0, 0, 12, 12)
far = mean_box(sel, bw, 210, 10, 235, 40)
body = mean_box(sel, bw, 90, 170, 150, 250)
# 1px stray line drawn at x=124, y=40..68
stray_vals = [sel[y * bw + 124] for y in range(42, 68)]
stray = sum(stray_vals) / float(len(stray_vals))
print("SUBJ_TEST blob head %.3f body %.3f corner %.3f far %.3f stray %.3f" % (head, body, corner, far, stray), flush=True)
if head < 0.8 or body < 0.7:
    die("blob not covered")
if corner > 0.05 or far > 0.05:
    die("far background selected")
if stray < 0.12:
    die("stray hair not partly selected")
print("SUBJ_TEST blob_ok", flush=True)

res_skin = call(blob, layer, "skin", 2.0)
print("SUBJ_TEST blob_skin_status", res_skin.index(0), flush=True)
if status_ok(res_skin):
    die("skin mode should fail when no face is found")
if layer_bytes(layer)[2] != before:
    die("failed skin call changed pixels")
print("SUBJ_TEST blob_skin_refused", flush=True)

selfie_path = "/workspace/retouch-trial/before.jpg"
if not os.path.isfile(selfie_path):
    die("selfie missing")
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(selfie_path))
slayer = img.get_layers()[0]
s_before = layer_bytes(slayer)[2]
res = call(img, slayer, "subject", 2.0)
print("SUBJ_TEST selfie_status", res.index(0), flush=True)
if not status_ok(res):
    die("selfie subject failed")
if layer_bytes(slayer)[2] != s_before:
    die("selfie pixels changed")
sw, sh, ssel = selection_floats(img)
box = json.load(open("/tmp/face_box.json"))
bx, by, bw_, bh_ = [int(round(v)) for v in box["box"]]
face_frac = frac_box(ssel, sw, bx, by, bx + bw_, by + bh_, 0.5)
hair_frac = frac_box(ssel, sw, bx + int(0.25 * bw_), by, bx + int(0.75 * bw_), by + int(0.18 * bh_), 0.2)
wood_frac = frac_box(ssel, sw, sw - 70, 1100, sw - 8, 1800, 0.2)
shirt = frac_box(ssel, sw, 500, 3354, 1600, min(sh, 4500), 0.2)
bite = frac_box(ssel, sw, 430, 650, 540, 754, 0.2)
wood_block = frac_box(ssel, sw, 1900, 2200, min(sw, 2076), 2800, 0.2)
row_min = 1.0
for y in range(3354, min(sh, 4500), 80):
    row_min = min(row_min, frac_box(ssel, sw, 500, y, 1600, y + 1, 0.2))
print("SUBJ_TEST selfie face %.3f hair %.3f wood %.3f" % (face_frac, hair_frac, wood_frac), flush=True)
print("SUBJ_TEST gaps shirt %.3f row_min %.3f bite %.3f wood_block %.3f" % (shirt, row_min, bite, wood_block), flush=True)
if face_frac < 0.7:
    die("face box mostly unselected")
if shirt < 0.45 or row_min < 0.2:
    die("shirt below y=3354 is still a zero band")
if bite < 0.75:
    die("window-side hair bite is back")
if wood_block > 0.08:
    die("wood block got selected")


def kind_frac(x0, y0, x1, y1, kind, thresh=0.5):
    """Selected share of pixels in a box that look like wood or like hair."""
    x1 = min(x1, sw)
    y1 = min(y1, sh)
    n = 0
    hit = 0
    for y in range(y0, y1):
        row = y * sw
        for x in range(x0, x1):
            i = (row + x) * 3
            r, g, b = s_before[i], s_before[i + 1], s_before[i + 2]
            mx = max(r, g, b)
            ch = mx - min(r, g, b)
            gy = 0.299 * r + 0.587 * g + 0.114 * b
            if kind == "wood":
                # Wood here is saturated orange-yellow; shadowed skin is redder
                # and less saturated relative to its brightness.
                ok = r > b + 70 and g > b + 35 and ch > 0.5 * mx
            else:
                ok = gy < 135 and ch < 38
            if not ok:
                continue
            n += 1
            if ssel[row + x] > thresh:
                hit += 1
    return hit / float(n or 1), n


regions = [
    ("left_shoulder", 0, 2736, 837, 3300),
    ("left_clothes", 0, 2736, 837, 4608),
    ("right_clothes", 1239, 2736, 2076, 4608),
    ("left_hair_box", 0, 420, 480, 1430),
    ("wood1_box", 1880, 720, 2076, 1860),
    ("wood2_box", 1600, 2320, 1752, 2710),
    ("ear_box", 1752, 1860, 1958, 2316),
]
vals = {}
for name, x0, y0, x1, y1 in regions:
    vals[name] = frac_box(ssel, sw, x0, y0, min(x1, sw), min(y1, sh), 0.5)
    print("SUBJ_TEST region %s %.3f" % (name, vals[name]), flush=True)
with open("/tmp/subject_sel_v3.pgm", "wb") as f:
    f.write(("P5\n%d %d\n255\n" % (sw, sh)).encode("ascii"))
    f.write(bytes(int(max(0.0, min(1.0, v)) * 255 + 0.5) for v in ssel))
lh, lhn = kind_frac(0, 420, 480, 1430, "hair")
w1, w1n = kind_frac(1880, 720, 2076, 1860, "wood")
w2, w2n = kind_frac(1600, 2320, 1752, 2710, "wood")
print("SUBJ_TEST hairlike_in_left_hair %.3f (n=%d) woodlike_in_wood1 %.3f (n=%d) woodlike_in_wood2 %.3f (n=%d)" % (
    lh, lhn, w1, w1n, w2, w2n), flush=True)
# Shadowed wood beside the hair: same yellow family as the lit wood, so the
# saturated-wood test above misses it. R>G>B with a wide red-blue gap.
sw_hit = 0
sw_n = 0
sw_max = 0
for y in range(1620, min(1960, sh)):
    run = 0
    best = 0
    for x in range(1900, min(1965, sw)):
        i = (y * sw + x) * 3
        r, g, b = s_before[i], s_before[i + 1], s_before[i + 2]
        ch = max(r, g, b) - min(r, g, b)
        is_wood = r > g and g > b and r > b + 55 and ch > 48
        sel = ssel[y * sw + x] > 0.5
        if is_wood:
            sw_n += 1
            if sel:
                sw_hit += 1
        if is_wood and sel:
            run += 1
            if run > best:
                best = run
        else:
            run = 0
    if best > sw_max:
        sw_max = best
sw_frac = sw_hit / float(sw_n or 1)
print("SUBJ_TEST shadow_wood frac %.3f (n=%d) max_width %d" % (sw_frac, sw_n, sw_max), flush=True)
if sw_frac > 0.08 or sw_max > 24:
    die("shadowed wood beside the hair is selected")
if vals["left_clothes"] < 0.85 or vals["left_shoulder"] < 0.85:
    die("left shoulder or clothes missing")
if lh < 0.8:
    die("left outer hair missing")
if w1 > 0.1 or w2 > 0.1:
    die("wood selected")
if hair_frac < 0.4:
    die("hair at top of head not selected")
# The far-right strip beside the head is hair on this selfie, not the wood.
# The wood that must stay out is wood_block, checked above.
write_preview("/tmp/subject_preview.ppm", s_before, sw, ssel, sw, (bx, by, bw_, bh_))
step = max(1, int(round(sw / 480.0)))
out_w = sw // step
out_h = sh // step
raw = bytearray(out_w * out_h * 3)
for oy in range(out_h):
    sy = oy * step
    for ox in range(out_w):
        sx = ox * step
        i = (sy * sw + sx) * 3
        s = ssel[sy * sw + sx]
        r, g, b = s_before[i], s_before[i + 1], s_before[i + 2]
        if s < 0.08:
            r, g, b = int(r * 0.25), int(g * 0.25), int(b * 0.25)
        o = (oy * out_w + ox) * 3
        raw[o] = r
        raw[o + 1] = g
        raw[o + 2] = b
with open("/tmp/subject_preview4.ppm", "wb") as f:
    f.write(("P6\n%d %d\n255\n" % (out_w, out_h)).encode("ascii"))
    f.write(raw)
print("SUBJ_TEST preview4 /tmp/subject_preview4.ppm %dx%d" % (out_w, out_h), flush=True)
print("SUBJ_TEST selfie_subject_ok", flush=True)

res = call(img, slayer, "skin", 2.0)
print("SUBJ_TEST skin_status", res.index(0), flush=True)
if not status_ok(res):
    die("skin failed")
if layer_bytes(slayer)[2] != s_before:
    die("skin changed pixels")
sw, sh, skin = selection_floats(img)
re = box["right_eye"]
le = box["left_eye"]
nose = box["nose"]
iod = ((le[0] - re[0]) ** 2 + (le[1] - re[1]) ** 2) ** 0.5
cr = ((re[0] + nose[0]) / 2.0 - iod * 0.28, (re[1] + nose[1]) / 2.0 + iod * 0.18)
cl = ((le[0] + nose[0]) / 2.0 + iod * 0.28, (le[1] + nose[1]) / 2.0 + iod * 0.18)

def patch(vals, pt, rad=5):
    x, y = int(pt[0]), int(pt[1])
    return mean_box(vals, sw, x - rad, y - rad, x + rad, y + rad)

cheek_r = patch(skin, cr)
cheek_l = patch(skin, cl)
eye_r = patch(skin, re, 4)
eye_l = patch(skin, le, 4)
hair_s = mean_box(skin, sw, bx + int(0.3 * bw_), by, bx + int(0.7 * bw_), by + int(0.12 * bh_))
wood_s = mean_box(skin, sw, sw - 70, 1100, sw - 8, 1800)
print("SUBJ_TEST skin cheekR %.3f cheekL %.3f eyeR %.3f eyeL %.3f hair %.3f wood %.3f" % (
    cheek_r, cheek_l, eye_r, eye_l, hair_s, wood_s), flush=True)
if cheek_r < 0.6 or cheek_l < 0.6:
    die("cheeks not in skin mask")
if eye_r > 0.25 or eye_l > 0.25:
    die("eyes still in skin mask")
if hair_s > 0.2:
    die("hair in skin mask")
if wood_s > 0.05:
    die("wall in skin mask")
print("SUBJ_TEST skin_ok", flush=True)
print("SUBJ_TEST ALL_OK", flush=True)
