# Headless proof for 人像笔刷. Run inside gimp-console (3.0) or flatpak gimp-console-3.2:
#   -b 'exec(open(".../test_portrait_brush.py").read())'
# Input: /tmp/pb/before_copy.jpg (a copy). Writes /tmp/pb/res_<ver>.json and crops.
import hashlib, json, math, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
pdb = Gimp.get_pdb()
V = Gimp.version()
SRC = os.environ.get("PB_SRC", "/tmp/pb/before_copy.jpg")
OUT = "/tmp/pb"
R = {"version": V, "checks": []}

def check(name, ok, detail=""):
    R["checks"].append([name, bool(ok), detail])
    print("PB_TEST %s %s %s" % ("OK  " if ok else "FAIL", name, detail), flush=True)

def ok_status(res):
    st = res.index(0)
    try:
        return st == Gimp.PDBStatusType.SUCCESS or int(st) == int(Gimp.PDBStatusType.SUCCESS)
    except Exception:
        return st == 3

def call(name, image, drawables, **kw):
    proc = pdb.lookup_procedure(name)
    if proc is None:
        raise RuntimeError("missing " + name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", image)
    try:
        cfg.set_core_object_array("drawables", drawables)
    except Exception:
        cfg.set_property("drawables", drawables)
    for k, v in kw.items():
        if isinstance(v, str):
            cfg.set_property(k, v)
        else:
            cfg.set_property(k, v)
    res = proc.run(cfg)
    if not ok_status(res):
        raise RuntimeError("%s failed: %s" % (name, res.index(1) if res.length() > 1 else ""))
    return res

def grab(d, x, y, w, h, fmt="R'G'B'A u8"):
    return bytes(d.get_buffer().get(Gegl.Rectangle.new(x, y, w, h), 1.0, fmt, Gegl.AbyssPolicy.NONE))

def layer_hash(layer):
    return hashlib.sha256(grab(layer, 0, 0, layer.get_width(), layer.get_height())).hexdigest()

def stats(raw):
    n = len(raw) // 4
    out = []
    for c in range(3):
        vals = raw[c::4]
        m = sum(vals) / n
        out.append((m, math.sqrt(max(0.0, sum(v * v for v in vals) / n - m * m))))
    lum = [(raw[i] * 54 + raw[i + 1] * 183 + raw[i + 2] * 19) / 256.0 for i in range(0, len(raw), 4)]
    lm = sum(lum) / n
    ls = math.sqrt(max(0.0, sum(v * v for v in lum) / n - lm * lm))
    return dict(mean_rgb=[round(a, 2) for a, _ in out], std_rgb=[round(b, 2) for _, b in out], lum_mean=round(lm, 2), lum_std=round(ls, 2))

def visible(img):
    v = Gimp.Layer.new_from_visible(img, img, "vis")
    img.insert_layer(v, None, 0)
    return v

def save_ppm(raw, w, h, path):
    with open(path, "wb") as f:
        f.write(b"P6 %d %d 255\n" % (w, h))
        f.write(bytes(b for i in range(0, len(raw), 4) for b in raw[i:i + 3]))

Gimp.context_push()          # keep the user's saved context untouched
try:
    # ---- 1. brushes in the brush list
    names = {}
    for b in Gimp.brushes_get_list("Portrait"):
        names[b.get_name()] = b
    want = {"Portrait Soft Round 人像柔圆": "vbr", "Portrait Skin Pores 皮肤毛孔": "gbr", "Portrait Hair Strand 细发丝": "gih"}
    R["brushes"] = {}
    for n, kind in want.items():
        b = names.get(n)
        info = None
        if b is not None:
            gi_ = b.get_info()
            info = dict(width=gi_[1], height=gi_[2], mask_bpp=gi_[3], color_bpp=gi_[4], generated=bool(b.is_generated()))
            if b.is_generated():
                info["hardness"] = round(b.get_hardness()[1], 3); info["radius"] = round(b.get_radius()[1], 2)
        R["brushes"][n] = info
        check("brush listed: " + n, b is not None, json.dumps(info, ensure_ascii=False))
    check("soft round is generated, hardness 0.15", (R["brushes"]["Portrait Soft Round 人像柔圆"] or {}).get("hardness") == 0.15)
    check("pores brush is a colour pixmap (paints its own neutral grey)", (R["brushes"]["Portrait Skin Pores 皮肤毛孔"] or {}).get("color_bpp") == 3)

    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(SRC))
    photo = img.get_layers()[0]
    W, H = img.get_width(), img.get_height()
    L = max(W, H)
    photo_hash0 = layer_hash(photo)

    # ---- 2. each job sets the expected context values
    exp = {
        "dnb": dict(brush="Portrait Soft Round 人像柔圆", base=80.0, lo=12.0, hi=400.0, hardness=0.15, spacing=0.10, opacity=10.0, method="gimp-paintbrush"),
        "texture": dict(brush="Portrait Skin Pores 皮肤毛孔", base=96.0, lo=32.0, hi=384.0, hardness=1.0, spacing=0.50, opacity=25.0, method="gimp-paintbrush"),
        "heal": dict(brush="Portrait Soft Round 人像柔圆", base=32.0, lo=8.0, hi=160.0, hardness=0.35, spacing=0.10, opacity=30.0, method="gimp-heal"),
        "hair": dict(brush="Portrait Hair Strand 细发丝", base=64.0, lo=24.0, hi=256.0, hardness=1.0, spacing=0.05, opacity=60.0, method="gimp-paintbrush"),
    }
    R["context"] = {}
    for mode, e in exp.items():
        # start from something different so a no-op would show
        Gimp.context_set_opacity(100.0); Gimp.context_set_brush_size(5.0); Gimp.context_set_dynamics_name("Pressure Size")
        call("python-fu-portrait-brush", img, [photo], mode=mode, **{"size-scale": 1.0})
        size = float(round(min(e["hi"], max(e["lo"], e["base"] * L / 4000.0)), 1))
        got = dict(brush=Gimp.context_get_brush().get_name(), size=round(Gimp.context_get_brush_size(), 2),
                   hardness=round(Gimp.context_get_brush_hardness(), 3), spacing=round(Gimp.context_get_brush_spacing(), 3),
                   opacity=round(Gimp.context_get_opacity(), 2), paint_mode=int(Gimp.context_get_paint_mode()),
                   dynamics=Gimp.context_get_dynamics_name(), dynamics_on=bool(Gimp.context_are_dynamics_enabled()),
                   method=Gimp.context_get_paint_method())
        if mode == "dnb":
            fg = Gimp.context_get_foreground().get_rgba(); bg = Gimp.context_get_background().get_rgba()
            got["fg"] = [round(c, 3) for c in fg[:3]]; got["bg"] = [round(c, 3) for c in bg[:3]]
        R["context"][mode] = dict(expected_size=size, got=got)
        good = (got["brush"] == e["brush"] and abs(got["size"] - size) < 0.11 and abs(got["hardness"] - e["hardness"]) < 1e-3
                and abs(got["spacing"] - e["spacing"]) < 1e-3 and abs(got["opacity"] - e["opacity"]) < 1e-3
                and got["paint_mode"] == int(Gimp.LayerMode.NORMAL) and got["dynamics"] == "Pressure Opacity" and got["dynamics_on"]
                and got["method"] == e["method"])
        if mode == "dnb":
            good = good and got["fg"] == [1.0, 1.0, 1.0] and got["bg"] == [0.0, 0.0, 0.0]
        check("context %s" % mode, good, json.dumps(got, ensure_ascii=False) + " expected size %.1f" % size)
    # size-scale
    call("python-fu-portrait-brush", img, [photo], mode="dnb", **{"size-scale": 0.5})
    s_half = Gimp.context_get_brush_size()
    check("size-scale 0.5 halves the D&B brush", abs(s_half - round(80.0 * L / 4000.0 * 0.5, 1)) < 0.11, "%.1f" % s_half)

    # ---- 3. helper layers: frequency separation + D&B setup on the photo
    call("python-fu-fsep-oneclick", img, [photo], radius=0.0)
    fs = [l for l in img.get_layers() if l.get_name() == "Frequency Separation"][0]
    high = [l for l in fs.get_children() if l.get_name() == "High (高频)"][0]
    call("python-fu-dnb-setup", img, [photo])
    dg = [l for l in img.get_layers() if l.get_name() == "Dodge & Burn"][0]
    dnb = [l for l in dg.get_children() if l.get_name() == "加深减淡 D&B"][0]
    # D&B group is often hidden-free; keep everything as created

    # cheek (right cheek from the face box used by subject select tests)
    CX, CY = 620, 2001
    BX, BY, BS = CX - 16, CY - 16, 32                 # small measuring box 32x32
    big = 160
    vis0 = visible(img); comp0 = grab(vis0, BX, BY, BS, BS)
    crop_tex0 = grab(vis0, CX - big // 2, CY - big // 2, big, big); img.remove_layer(vis0)
    hi0 = grab(high, BX, BY, BS, BS)

    # ---- 4. texture stroke on the high-frequency layer
    call("python-fu-portrait-brush", img, [photo], mode="texture", **{"size-scale": 1.0})
    img.set_selected_layers([high])
    ok = Gimp.paintbrush_default(high, [CX - 70.0, float(CY), CX + 70.0, float(CY)])
    hi1 = grab(high, BX, BY, BS, BS)
    vis1 = visible(img); comp1 = grab(vis1, BX, BY, BS, BS)
    crop_after = grab(vis1, CX - big // 2, CY - big // 2, big, big); img.remove_layer(vis1)
    R["texture"] = dict(stroke_ok=bool(ok), box=[BX, BY, BS, BS],
                        high_before=stats(hi0), high_after=stats(hi1),
                        comp_before=stats(comp0), comp_after=stats(comp1))
    t = R["texture"]
    dmean = max(abs(a - b) for a, b in zip(t["comp_after"]["mean_rgb"], t["comp_before"]["mean_rgb"]))
    check("texture stroke adds fine texture (high-freq std up)", t["high_after"]["lum_std"] > t["high_before"]["lum_std"] * 1.15,
          "HF lum std %.2f -> %.2f, mean %.2f -> %.2f" % (t["high_before"]["lum_std"], t["high_after"]["lum_std"], t["high_before"]["lum_mean"], t["high_after"]["lum_mean"]))
    check("texture keeps the average colour (composite mean shift <= 2.0)", dmean <= 2.0,
          "composite mean RGB %s -> %s, max shift %.2f; std lum %.2f -> %.2f" % (t["comp_before"]["mean_rgb"], t["comp_after"]["mean_rgb"], dmean, t["comp_before"]["lum_std"], t["comp_after"]["lum_std"]))

    # ---- 5. soft round stroke on the grey D&B layer
    call("python-fu-portrait-brush", img, [photo], mode="dnb", **{"size-scale": 1.0})
    # dnb_setup places its group above the photo, i.e. under the frequency
    # separation group here; put it on top so the stroke is visible in the composite.
    img.reorder_item(dg, None, 0)
    DY = CY + 120
    rx, ry, rw, rh = CX - 130, DY - 80, 260, 160
    d0 = grab(dnb, rx, ry, rw, rh)
    vis2 = visible(img); c0 = grab(vis2, rx, ry, rw, rh)
    crop_dnb0 = grab(vis2, CX - big // 2, DY - big // 2, big, big); img.remove_layer(vis2)
    img.set_selected_layers([dnb])
    ok2 = Gimp.paintbrush_default(dnb, [CX - 60.0, float(DY), CX + 60.0, float(DY)])
    d1 = grab(dnb, rx, ry, rw, rh)
    vis3 = visible(img); c1 = grab(vis3, rx, ry, rw, rh)
    crop_dnb = grab(vis3, CX - big // 2, DY - big // 2, big, big); img.remove_layer(vis3)
    peak = max(abs(d1[i] - d0[i]) for i in range(0, len(d0)) if i % 4 != 3)
    peakc = max(abs(c1[i] - c0[i]) for i in range(0, len(c0)) if i % 4 != 3)
    grey0 = sorted(set(d0[i] for i in range(0, len(d0), 4)))
    # GIMP 3 paints in linear light: 10% white over sRGB 128 lands at ~147.5
    def lin(v): v /= 255.0; return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    def srgb(l): return 255.0 * (12.92 * l if l <= 0.0031308 else 1.055 * l ** (1 / 2.4) - 0.055)
    cap = srgb(0.9 * lin(128) + 0.1) - 128.0
    R["dnb"] = dict(stroke_ok=bool(ok2), grey_before=grey0[:5], peak_change_dnb_layer=peak, peak_change_composite=peakc,
                    cap_10pct_linear=round(cap, 1))
    check("D&B soft stroke stays low opacity", 0 < peak <= cap + 1.0,
          "peak change on D&B layer %d/255 (10%% white over 128 in linear light = %.1f); composite peak %d/255" % (peak, cap, peakc))

    # ---- 6. photo layer untouched
    check("photo layer pixels untouched", layer_hash(photo) == photo_hash0, photo_hash0[:16])

    # crops for the preview
    save_ppm(crop_tex0, big, big, "%s/tex_before_%s.ppm" % (OUT, V))
    save_ppm(crop_after, big, big, "%s/tex_after_%s.ppm" % (OUT, V))
    save_ppm(crop_dnb0, big, big, "%s/dnb_before_%s.ppm" % (OUT, V))
    save_ppm(crop_dnb, big, big, "%s/dnb_after_%s.ppm" % (OUT, V))
    img.delete()

    # ---- 7. hair strand brush follows the stroke direction
    def hair_test(horizontal):
        im = Gimp.Image.new(400, 400, Gimp.ImageBaseType.RGB)
        bgl = Gimp.Layer.new(im, "bg", 400, 400, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        im.insert_layer(bgl, None, 0)
        lay = Gimp.Layer.new(im, "hair", 400, 400, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        im.insert_layer(lay, None, 0)
        call("python-fu-portrait-brush", im, [lay], mode="hair", **{"size-scale": 1.0})
        Gimp.context_set_brush_size(64.0)
        Gimp.context_set_opacity(100.0)
        c = Gegl.Color.new("black"); Gimp.context_set_foreground(c)
        # Point strokes (Gimp.paintbrush_default) carry no direction, so an
        # angular .gih would always use one cell. Stroke a path with emulated
        # dynamics instead, which is how GIMP fills in the stroke direction.
        x0, y0, x1, y1 = (60.0, 200.0, 340.0, 200.0) if horizontal else (200.0, 60.0, 200.0, 340.0)
        path = Gimp.Path.new(im, "hair-test")
        im.insert_path(path, None, 0)
        path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER, [x0, y0, x0, y0, x0, y0, x1, y1, x1, y1, x1, y1], False)
        Gimp.context_set_stroke_method(Gimp.StrokeMethod.PAINT_METHOD)
        Gimp.context_set_paint_method("gimp-paintbrush")
        Gimp.context_set_emulate_brush_dynamics(True)
        lay.edit_stroke_item(path)
        Gimp.context_set_emulate_brush_dynamics(False)
        raw = grab(lay, 100, 100, 200, 200)
        a = [raw[i] for i in range(3, len(raw), 4)]
        gx = gy = 0
        for y in range(1, 199):
            for x in range(1, 199):
                v = a[y * 200 + x]
                gx += abs(v - a[y * 200 + x - 1]); gy += abs(v - a[(y - 1) * 200 + x])
        full = grab(lay, 0, 0, 400, 400)
        alpha = bytes(full[i] for i in range(3, len(full), 4))
        with open("%s/hair_%s_%s.pgm" % (OUT, "h" if horizontal else "v", V), "wb") as f:
            f.write(b"P5 400 400 255\n" + bytes(255 - x for x in alpha))
        im.delete()
        return gx, gy
    gxh, gyh = hair_test(True)
    gxv, gyv = hair_test(False)
    R["hair"] = dict(horizontal=dict(grad_x=gxh, grad_y=gyh), vertical=dict(grad_x=gxv, grad_y=gyv))
    check("hair strands run along a horizontal stroke", gyh > 2.5 * gxh, "grad_y/grad_x = %.2f" % (gyh / max(1, gxh)))
    check("hair strands run along a vertical stroke", gxv > 2.5 * gyv, "grad_x/grad_y = %.2f" % (gxv / max(1, gyv)))
finally:
    Gimp.context_pop()

R["all_ok"] = all(c[1] for c in R["checks"])
json.dump(R, open("%s/res_%s.json" % (OUT, V), "w"), ensure_ascii=False, indent=1)
print("PB_TEST DONE all_ok=%s" % R["all_ok"], flush=True)
