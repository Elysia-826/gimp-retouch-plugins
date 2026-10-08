#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 点修复 / Spot heal  (GIMP 3.0.x and 3.2.x)
# One click fills a small spot from the surrounding skin via Resynthesizer.
# Thin dark lines (hair) and hard edges inside the spot are put back afterwards
# so they are not painted over. No numpy. No DrawableFilter.
import math
import sys
import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-spot-heal"


def _bytes(data):
    if data is None:
        return b""
    return bytes(data)


def _offsets(layer):
    off = layer.get_offsets()
    if len(off) >= 3:
        return int(off[1]), int(off[2])
    return int(off[0]), int(off[1])


def _lum_at(raw, bpp, i):
    if bpp == 1:
        return raw[i]
    return (raw[i] * 54 + raw[i + 1] * 183 + raw[i + 2] * 19) >> 8


def _window(layer, cx, cy, radius):
    w, h = layer.get_width(), layer.get_height()
    pad = int(radius) + 10
    x0 = max(0, int(cx) - pad)
    y0 = max(0, int(cy) - pad)
    x1 = min(w, int(cx) + pad + 1)
    y1 = min(h, int(cy) + pad + 1)
    bw, bh = x1 - x0, y1 - y0
    buf = layer.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(ext.x + x0, ext.y + y0, bw, bh)
    raw = _bytes(buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    fmt, bpp = "R'G'B'A u8", 4
    if len(raw) != bw * bh * 4:
        raw = _bytes(buf.get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
        fmt, bpp = "R'G'B' u8", 3
    if len(raw) != bw * bh * bpp:
        raw = _bytes(buf.get(rect, 1.0, "Y' u8", Gegl.AbyssPolicy.NONE))
        fmt, bpp = "Y' u8", 1
    if len(raw) != bw * bh * bpp:
        raise RuntimeError("Cannot read the layer / 读不到图层")
    return x0, y0, bw, bh, rect, bytearray(raw), fmt, bpp


def _thin_mask(raw, bw, bh, bpp, cx, cy, radius, x0, y0):
    """Pixels that belong to a thin dark line or a hard edge, in window coords."""
    lum = [0] * (bw * bh)
    for y in range(bh):
        row = y * bw
        for x in range(bw):
            lum[row + x] = _lum_at(raw, bpp, (row + x) * bpp)
    thin = bytearray(bw * bh)
    r2 = float(radius) * float(radius)
    for y in range(2, bh - 2):
        for x in range(2, bw - 2):
            ix, iy = x + x0, y + y0
            dx, dy = ix + 0.5 - cx, iy + 0.5 - cy
            if dx * dx + dy * dy > r2:
                continue
            i = y * bw + x
            gx = lum[i + 1] - lum[i - 1]
            gy = lum[i + bw] - lum[i - bw]
            here = lum[i]
            mean = _local_mean(lum, bw, x, y)
            # A hair is a few dark pixels. The middle of a blemish is a wide dark area.
            # The center of a 1px line has a weak gradient (both neighbors are skin),
            # so also accept a pixel that is much darker than its neighborhood but not a blob.
            dark = 0
            for yy in range(y - 2, y + 3):
                base = yy * bw
                for xx in range(x - 2, x + 3):
                    if lum[base + xx] <= here + 16:
                        dark += 1
            steep = abs(gx) + abs(gy) >= 36 and dark <= 9 and here + 24 < mean
            core = dark <= 7 and here + 18 < mean
            if steep or core:
                thin[i] = 1
    return thin, lum


def _local_mean(lum, bw, x, y):
    acc = n = 0
    for yy in range(y - 2, y + 3):
        base = yy * bw
        for xx in range(x - 2, x + 3):
            acc += lum[base + xx]
            n += 1
    return acc / float(n)


def _ring_median(lum, bw, bh, cx, cy, radius, x0, y0):
    vals = []
    r0 = radius + 2.0
    r1 = radius + 8.0
    for y in range(bh):
        for x in range(bw):
            dx = (x + x0) + 0.5 - cx
            dy = (y + y0) + 0.5 - cy
            d = math.hypot(dx, dy)
            if r0 <= d <= r1:
                vals.append(lum[y * bw + x])
    if not vals:
        return 128
    vals.sort()
    return vals[len(vals) // 2]


def _plan(layer, cx, cy, radius):
    w, h = layer.get_width(), layer.get_height()
    if cx < radius or cy < radius or cx >= w - radius or cy >= h - radius:
        return None, "点太靠近图层边缘 / click is too close to the layer edge"
    x0, y0, bw, bh, rect, raw, fmt, bpp = _window(layer, cx, cy, radius)
    thin, lum = _thin_mask(raw, bw, bh, bpp, cx, cy, radius, x0, y0)
    r2 = float(radius) * float(radius)
    disk = thin_n = blob = 0
    cx_i = int(cx) - x0
    cy_i = int(cy) - y0
    center_thin = False
    if 0 <= cx_i < bw and 0 <= cy_i < bh:
        center_thin = bool(thin[cy_i * bw + cx_i])
    med = _ring_median(lum, bw, bh, cx, cy, radius, x0, y0)
    gx_sum = gy_sum = 0
    for y in range(bh):
        for x in range(bw):
            dx = (x + x0) + 0.5 - cx
            dy = (y + y0) + 0.5 - cy
            if dx * dx + dy * dy > r2:
                continue
            disk += 1
            i = y * bw + x
            if thin[i]:
                thin_n += 1
                gx = abs(lum[i + 1] - lum[i - 1]) if 0 < x < bw - 1 else 0
                gy = abs(lum[i + bw] - lum[i - bw]) if 0 < y < bh - 1 else 0
                gx_sum += gx
                gy_sum += gy
            elif lum[i] + 28 < med:
                blob += 1
    if disk == 0:
        return None, "空的范围 / empty spot"
    # Click landed on a hair or a hard edge, and there is no wider blemish under it.
    if center_thin and blob < 12:
        return None, "这一点在头发或硬边上，没有涂抹 / click is on hair or a hard edge, nothing painted"
    if gx_sum + gy_sum < 80:
        direction = 0  # no strong line: sample all around
    elif gx_sum > gy_sum * 1.25:
        direction = 1  # vertical line: sample from the sides
    elif gy_sum > gx_sum * 1.25:
        direction = 2  # horizontal line: sample above and below
    else:
        direction = 0
    return {
        "x0": x0, "y0": y0, "bw": bw, "bh": bh, "rect": rect,
        "raw": raw, "fmt": fmt, "bpp": bpp, "thin": thin,
        "direction": direction,
    }, None


def _restore_thin(layer, plan):
    buf = layer.get_buffer()
    now = bytearray(_bytes(buf.get(plan["rect"], 1.0, plan["fmt"], Gegl.AbyssPolicy.NONE)))
    bpp = plan["bpp"]
    bw = plan["bw"]
    raw = plan["raw"]
    thin = plan["thin"]
    if len(now) != len(raw):
        raise RuntimeError("Layer size changed while healing / 修复时图层变了")
    for i, flag in enumerate(thin):
        if not flag:
            continue
        s = i * bpp
        now[s:s + bpp] = raw[s:s + bpp]
    buf.set(plan["rect"], plan["fmt"], bytes(now))
    layer.update(plan["x0"], plan["y0"], plan["bw"], plan["bh"])


def _heal_one(image, layer, cx, cy, radius, sampling):
    plan, why = _plan(layer, cx, cy, radius)
    if plan is None:
        return False, why
    ox, oy = _offsets(layer)
    image.set_selected_layers([layer])
    Gimp.Selection.none(image)
    image.select_ellipse(Gimp.ChannelOps.REPLACE, ox + cx - radius, oy + cy - radius, radius * 2.0, radius * 2.0)
    if Gimp.Selection.is_empty(image):
        return False, "选区是空的 / selection is empty"
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure("plug-in-heal-selection")
    if proc is None:
        raise RuntimeError("没有安装 Resynthesizer 的「修复选区」。本插件靠它来补纹理。 / Resynthesizer heal-selection is not installed.")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", image)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    cfg.set_property("adjustment", int(sampling))
    cfg.set_property("option", int(plan["direction"]))
    cfg.set_property("option-2", 1)  # fill inwards
    res = proc.run(cfg)
    st = res.index(0)
    if st != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        raise RuntimeError("修复选区失败 / heal failed: %s" % err)
    _restore_thin(layer, plan)
    return True, plan["direction"]


def spot_heal(image, layer, x, y, radius, x2, y2, x3, y3):
    if layer.is_group():
        raise RuntimeError("请选择普通图层，不要选图层组 / Choose a normal layer, not a group")
    if layer.get_lock_content():
        raise RuntimeError("图层已锁定 / Layer is locked")
    radius = float(radius)
    if radius < 4.0 or radius > 48.0:
        raise RuntimeError("半径要在 4 到 48 之间 / radius must be 4..48")
    pts = [(float(x), float(y))]
    if x2 >= 0.0 and y2 >= 0.0:
        pts.append((float(x2), float(y2)))
    if x3 >= 0.0 and y3 >= 0.0:
        pts.append((float(x3), float(y3)))
    sampling = int(max(12, min(36, round(radius * 1.6))))
    saved = None
    if not Gimp.Selection.is_empty(image):
        saved = Gimp.Selection.save(image)
    healed = 0
    notes = []
    image.undo_group_start()
    try:
        for cx, cy in pts:
            ok, info = _heal_one(image, layer, cx, cy, radius, sampling)
            if ok:
                healed += 1
            else:
                notes.append(info)
        if healed == 0:
            raise RuntimeError(notes[0] if notes else "没有可修复的点 / nothing to heal")
    except Exception:
        raise
    finally:
        if saved is not None:
            image.select_item(Gimp.ChannelOps.REPLACE, saved)
            image.remove_channel(saved)
        else:
            Gimp.Selection.none(image)
        image.undo_group_end()
    Gimp.displays_flush()
    return healed


def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR, GLib.Error("请选择一个图层 / Select one layer"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "点修复 / Spot Heal")
        dlg.fill(["x", "y", "radius", "x2", "y2", "x3", "y3"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        spot_heal(
            image, drawables[0],
            config.get_property("x"), config.get_property("y"), config.get_property("radius"),
            config.get_property("x2"), config.get_property("y2"),
            config.get_property("x3"), config.get_property("y3"),
        )
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class SpotHeal(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("点修复 / Spot Heal")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Heal a small spot from the surrounding texture. Thin lines and hard edges inside the spot are kept. 点掉小斑，细线和硬边会留着。",
            "The dialog cannot receive a click on the photo. Type the spot in layer pixels. Up to three points, one undo step. "
            "Uses Resynthesizer heal-selection. Hair-like thin dark lines are copied back after the fill so they are not smeared. "
            "Not verified by hand. 尚未人工验证。",
            name,
        )
        p.set_attribution("Elysia", "Elysia", "2026")
        p.add_double_argument("x", "Spot X / 点的 X", "Layer pixels. The dialog cannot click on the photo. 图层坐标。对话框不能在照片上点。",
                              0.0, 1000000.0, 0.0, F)
        p.add_double_argument("y", "Spot Y / 点的 Y", "Layer pixels.", 0.0, 1000000.0, 0.0, F)
        p.add_double_argument("radius", "Spot radius px / 斑点半径", "How big the blemish is, 4 to 48. Not the sampling width. 斑有多大，不是取样宽度。",
                              4.0, 48.0, 12.0, F)
        p.add_double_argument("x2", "Second X (<0 = none) / 第二点 X", "Optional. Same undo step. 可选，和第一点同一次撤销。",
                              -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("y2", "Second Y (<0 = none) / 第二点 Y", "Optional.", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("x3", "Third X (<0 = none) / 第三点 X", "Optional.", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("y3", "Third Y (<0 = none) / 第三点 Y", "Optional.", -1.0, 1000000.0, -1.0, F)
        return p


Gimp.main(SpotHeal.__gtype__, sys.argv)
