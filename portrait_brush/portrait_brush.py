#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 人像笔刷 / Portrait brushes  (GIMP 3.0.x and 3.2.x)
# Sets the paint context for one retouch job: brush, size from the image,
# low opacity, soft dynamics. It does not paint and does not touch pixels.
# The brushes themselves are files in <GIMP config>/brushes/portrait-retouch/
# (made by make_brushes.py from a fixed seed, MIT).
# No numpy. No DrawableFilter. Only libgimp calls that exist in 3.0.4.
import sys
import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-portrait-brush"

SOFT = "Portrait Soft Round 人像柔圆"
PORES = "Portrait Skin Pores 皮肤毛孔"
HAIR = "Portrait Hair Strand 细发丝"
DYNAMICS = "Pressure Opacity"   # built into 3.0 and 3.2; a mouse paints at full pressure

# size is a fraction of the image's long side (4000 px reference), then clamped.
# opacity is the cap of one stroke (GIMP paints non-incremental by default).
PRESETS = {
    # 加深减淡：在 50% 灰柔光层上涂。前景白=减淡，按 X 换黑=加深。
    "dnb": dict(brush=SOFT, size=80.0, lo=12.0, hi=400.0, hardness=0.15, spacing=0.10,
                opacity=10.0, method="gimp-paintbrush", colors="white-black"),
    # 皮肤纹理：在高频层上涂。笔刷本身是平均 128 的灰，不会把颜色带偏。
    "texture": dict(brush=PORES, size=96.0, lo=32.0, hi=384.0, hardness=1.0, spacing=0.50,
                    opacity=25.0, method="gimp-paintbrush", colors=None),
    # 修复/仿制：小号柔边，低不透明度，多涂几次叠上去。
    "heal": dict(brush=SOFT, size=32.0, lo=8.0, hi=160.0, hardness=0.35, spacing=0.10,
                 opacity=30.0, method="gimp-heal", colors=None),
    # 细发丝：沿头发方向拖，补零散发丝。颜色用当前前景色。
    "hair": dict(brush=HAIR, size=64.0, lo=24.0, hi=256.0, hardness=1.0, spacing=0.05,
                 opacity=60.0, method="gimp-paintbrush", colors=None),
}
MODES = ["dnb", "texture", "heal", "hair"]


def _brush(name):
    b = Gimp.Brush.get_by_name(name)
    if b is None:
        Gimp.brushes_refresh()
        b = Gimp.Brush.get_by_name(name)
    if b is None:
        raise RuntimeError(
            "没有找到笔刷「%s」。请用安装脚本装上 portrait_brush 组件（笔刷放在 GIMP 配置目录的 brushes/portrait-retouch/）。"
            " / Brush not found; install the portrait_brush component." % name)
    return b


def _rgb(r, g, b):
    c = Gegl.Color.new("black")
    c.set_rgba(r, g, b, 1.0)
    return c


def brush_size(image, preset, scale):
    long_side = float(max(image.get_width(), image.get_height()))
    s = preset["size"] * long_side / 4000.0 * scale
    return float(round(min(preset["hi"], max(preset["lo"], s)), 1))


def apply_preset(image, mode, scale):
    p = PRESETS[mode]
    brush = _brush(p["brush"])
    Gimp.context_set_brush(brush)
    Gimp.context_set_brush_size(brush_size(image, p, scale))
    Gimp.context_set_brush_hardness(p["hardness"])
    Gimp.context_set_brush_spacing(p["spacing"])
    Gimp.context_set_brush_aspect_ratio(0.0)
    Gimp.context_set_brush_angle(0.0)
    Gimp.context_set_brush_force(0.5)
    Gimp.context_set_opacity(p["opacity"])
    Gimp.context_set_paint_mode(Gimp.LayerMode.NORMAL)
    Gimp.context_enable_dynamics(True)
    Gimp.context_set_dynamics_name(DYNAMICS)
    Gimp.context_set_paint_method(p["method"])
    if p["colors"] == "white-black":
        Gimp.context_set_foreground(_rgb(1.0, 1.0, 1.0))
        Gimp.context_set_background(_rgb(0.0, 0.0, 0.0))


def run(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "人像笔刷 / Portrait Brushes")
        dlg.fill(["mode", "size-scale"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        mi = config.get_choice_id("mode")
        mode = MODES[mi] if 0 <= mi < len(MODES) else "dnb"
        apply_preset(image, mode, config.get_property("size-scale"))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class PortraitBrush(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                               | Gimp.ProcedureSensitivityMask.DRAWABLES
                               | Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        p.set_menu_label("人像笔刷 / Portrait Brushes")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Set brush, size, low opacity and soft dynamics for one retouch job. Paints nothing. "
            "设置笔刷、大小、低不透明度和柔和动态，用于一项修图工作。不会画任何东西。",
            "Pick the tool first (Paintbrush for D&B, texture and hair; Heal or Clone for healing), "
            "then run this: opacity and mode go to the active tool, brush/size/hardness/spacing go to all paint tools. "
            "A mouse paints at full pressure; a pen softens with Pressure Opacity. "
            "GIMP has no flow setting reachable from a plug-in; opacity is the per-stroke cap. "
            "先选好工具（画笔：加深减淡/纹理/发丝；修复或仿制：修复），再运行：不透明度和模式作用于当前工具。"
            "Not verified by hand. 尚未人工验证。",
            name,
        )
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("dnb", 0, "加深减淡（灰层） / Dodge & burn on the grey layer",
               "Soft round, 10% opacity, white foreground (X = black)")
        ch.add("texture", 1, "皮肤纹理（高频层） / Skin texture on the high-frequency layer",
               "Pore brush, 25% opacity, neutral grey so the tone stays")
        ch.add("heal", 2, "修复/仿制（低不透明度） / Heal or clone at low opacity",
               "Small soft round, 30% opacity")
        ch.add("hair", 3, "细发丝 / Fine hair strands",
               "Strand brush follows the stroke direction, 60% opacity, current colour")
        p.add_choice_argument("mode", "Job / 用途", "What the brush is for.", ch, "dnb", F)
        p.add_double_argument("size-scale", "Size × / 大小倍数",
                              "1 = sized from the image's long side. 1 表示按图片长边自动定大小。",
                              0.25, 4.0, 1.0, F)
        return p


Gimp.main(PortraitBrush.__gtype__, sys.argv)
