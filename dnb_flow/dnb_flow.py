#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 轻柔涂抹 / Gentle dodge-burn stroke  (GIMP 3.0.x and 3.2.x)
# Paint on the 50% grey Soft Light layer from dnb_setup.
# Flow is how fast ONE stroke builds. Opacity is that stroke's cap.
# They are not multiplied by pen pressure unless a pressure value is passed in.
# This plugin cannot read a live tablet. No numpy. No DrawableFilter.
import math
import sys
import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-dnb-flow"


def _bytes(data):
    if data is None:
        return b""
    return bytes(data)


def _falloff(d, radius, inner, span):
    if d >= radius:
        return 0.0
    if d <= inner:
        return 1.0
    t = (d - inner) / span
    u = 1.0 - t
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def _dabs(x1, y1, x2, y2, step):
    if x2 < 0.0 or y2 < 0.0:
        return [(x1, y1)]
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist < 0.5:
        return [(x1, y1)]
    n = max(1, int(round(dist / step)))
    return [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n + 1)]


def _read(layer):
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(ext.x, ext.y, w, h)
    raw = _bytes(buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    if len(raw) == w * h * 4:
        return rect, bytearray(raw), 4, "R'G'B'A u8"
    raw = _bytes(buf.get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    if len(raw) == w * h * 3:
        return rect, bytearray(raw), 3, "R'G'B' u8"
    raw = _bytes(buf.get(rect, 1.0, "Y' u8", Gegl.AbyssPolicy.NONE))
    if len(raw) == w * h:
        return rect, bytearray(raw), 1, "Y' u8"
    raise RuntimeError("Cannot read the layer / 读不到图层")


def apply_stroke(image, layer, mode, x1, y1, x2, y2, radius, flow, opacity, hardness, spacing, pressure):
    """One stroke. Overlapping dabs build toward opacity, and stop there."""
    if layer.is_group():
        raise RuntimeError("请选中加深减淡的灰色图层，不要选图层组 / Choose the grey paint layer, not a group")
    if layer.get_lock_content():
        raise RuntimeError("图层已锁定 / Layer is locked")
    radius = float(radius)
    if radius < 2.0 or radius > 800.0:
        raise RuntimeError("半径要在 2 到 800 / radius must be 2..800")
    flow = max(0.0, min(100.0, float(flow))) / 100.0
    opacity = max(0.0, min(100.0, float(opacity))) / 100.0
    if flow <= 0.0 or opacity <= 0.0:
        return 0
    # Pressure is not read from a tablet. Only an explicit 0..1 value scales flow.
    if pressure >= 0.0:
        flow *= max(0.0, min(1.0, float(pressure)))
        if flow <= 0.0:
            return 0
    hardness = max(0.0, min(0.95, float(hardness)))
    spacing = max(0.08, min(1.0, float(spacing)))
    step = max(1.0, radius * spacing)
    dabs = _dabs(float(x1), float(y1), float(x2), float(y2), step)
    w, h = layer.get_width(), layer.get_height()
    minx = min(p[0] for p in dabs) - radius
    maxx = max(p[0] for p in dabs) + radius
    miny = min(p[1] for p in dabs) - radius
    maxy = max(p[1] for p in dabs) + radius
    x0 = max(0, int(math.floor(minx)))
    y0 = max(0, int(math.floor(miny)))
    x1b = min(w, int(math.ceil(maxx)) + 1)
    y1b = min(h, int(math.ceil(maxy)) + 1)
    if x1b <= x0 or y1b <= y0:
        return 0
    inner = hardness * radius
    span = max(1e-6, radius - inner)
    rect, raw, bpp, fmt = _read(layer)
    dodge = mode != "burn"
    changed = 0
    for y in range(y0, y1b):
        py = y + 0.5
        for x in range(x0, x1b):
            px = x + 0.5
            coverage = 0.0
            for dx, dy in dabs:
                d = math.hypot(px - dx, py - dy)
                f = _falloff(d, radius, inner, span) * flow
                if f <= 0.0 or coverage >= 1.0:
                    continue
                coverage += f * (1.0 - coverage)
            if coverage <= 0.0:
                continue
            amount = coverage * opacity
            if amount <= 0.0:
                continue
            i = (y * w + x) * bpp
            for c in range(min(3, bpp)):
                old = raw[i + c]
                if dodge:
                    new = old + (255 - old) * amount
                else:
                    new = old * (1.0 - amount)
                ni = int(new + 0.5)
                if ni < 0:
                    ni = 0
                elif ni > 255:
                    ni = 255
                if ni != old:
                    raw[i + c] = ni
                    changed += 1
    if changed == 0:
        return 0
    image.undo_group_start()
    try:
        layer.get_buffer().set(rect, fmt, bytes(raw))
        layer.update(0, 0, w, h)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return changed


def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR, GLib.Error("请选择一个图层 / Select one layer"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "轻柔涂抹 / Gentle D&B Stroke")
        dlg.fill(["mode", "x1", "y1", "x2", "y2", "radius", "flow", "opacity", "hardness", "spacing", "pressure"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        mi = config.get_choice_id("mode")
        mode = "burn" if mi == 1 else "dodge"
        apply_stroke(
            image, drawables[0], mode,
            config.get_property("x1"), config.get_property("y1"),
            config.get_property("x2"), config.get_property("y2"),
            config.get_property("radius"), config.get_property("flow"),
            config.get_property("opacity"), config.get_property("hardness"),
            config.get_property("spacing"), config.get_property("pressure"),
        )
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class DnbFlow(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("轻柔涂抹 / Gentle D&B Stroke")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "One soft dodge or burn stroke on the grey overlay. Flow builds within the stroke; opacity is the cap. 在灰色加深减淡层上涂一笔。流量是这一笔叠多快，不透明度是这一笔的上限。",
            "Does not read a tablet. Leave pressure at -1 so it is not a third multiplier. "
            "Select the 50% grey layer from 一键加深减淡搭建, not the photo. "
            "A second run is a second stroke and can build further. Not verified by hand. 尚未人工验证。",
            name,
        )
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("dodge", 0, "Dodge / 减淡", "Move grey toward white")
        ch.add("burn", 1, "Burn / 加深", "Move grey toward black")
        p.add_choice_argument("mode", "Mode / 模式", "Dodge or burn on the grey layer.", ch, "dodge", F)
        p.add_double_argument("x1", "Start X / 起点 X", "Layer pixels. The dialog cannot follow the pen. 图层坐标。对话框跟不了笔。",
                              0.0, 1000000.0, 0.0, F)
        p.add_double_argument("y1", "Start Y / 起点 Y", "Layer pixels.", 0.0, 1000000.0, 0.0, F)
        p.add_double_argument("x2", "End X (<0 = one dab) / 终点 X", "Straight stroke. Below 0 paints a single dab.",
                              -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("y2", "End Y (<0 = one dab) / 终点 Y", "Straight stroke.", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("radius", "Radius px / 半径", "Soft edge. Default is a gentle portrait dab.",
                              2.0, 800.0, 48.0, F)
        p.add_double_argument("flow", "Flow / 流量 (0-100)",
                              "How fast this stroke builds. Not multiplied by opacity into a stamp. 这一笔叠多快。",
                              0.0, 100.0, 18.0, F)
        p.add_double_argument("opacity", "Opacity cap / 不透明度上限 (0-100)",
                              "The most this one stroke may reach, even where dabs overlap. 这一笔最多到这里，重叠也不会超过。",
                              0.0, 100.0, 24.0, F)
        p.add_double_argument("hardness", "Hardness / 硬度 (0=最柔)", "0 is fully soft.",
                              0.0, 0.95, 0.0, F)
        p.add_double_argument("spacing", "Dab spacing / 间距 (占半径)", "0.25 means dabs every quarter of the radius.",
                              0.08, 1.0, 0.22, F)
        p.add_double_argument("pressure", "Pressure (-1 = off) / 压力",
                              "This plugin cannot read a live pen. -1 leaves pressure out. 0..1 scales flow only, and only if you type it. 读不到数位板。-1 表示没有压力这一项。",
                              -1.0, 1.0, -1.0, F)
        return p


Gimp.main(DnbFlow.__gtype__, sys.argv)
