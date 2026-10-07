#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 一键加深减淡搭建 / One-click Dodge & Burn setup  (GIMP 3.0.x and 3.2.x)
import sys, gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-dnb-setup"

def _color(s):
    c = Gegl.Color.new(s)
    return c

def _new_layer(image, name, mode, opacity=100.0):
    l = Gimp.Layer.new(image, name, image.get_width(), image.get_height(),
                       Gimp.ImageType.RGBA_IMAGE if image.get_base_type() == Gimp.ImageBaseType.RGB
                       else Gimp.ImageType.GRAYA_IMAGE, opacity, mode)
    return l

def _group(image, name):
    g = Gimp.GroupLayer.new(image, name) if hasattr(Gimp, "GroupLayer") else Gimp.Layer.group_new(image)
    g.set_name(name)
    return g

def setup(image, layer, blend, contrast):
    image.undo_group_start()
    try:
        parent = layer.get_parent()
        pos = image.get_item_position(layer)
        grp = _group(image, "Dodge & Burn")
        image.insert_layer(grp, parent, pos)          # directly above active layer
        grp.set_mode(Gimp.LayerMode.PASS_THROUGH)     # blend children with layers below

        # Helper / observer group (hidden by default), placed on top
        helper = _group(image, "观察层 Helper")
        image.insert_layer(helper, grp, 0)
        if contrast:
            # Desaturated (luminosity) copy + S-curve contrast boost, Normal mode
            con = layer.copy(); con.set_name("对比增强 Contrast")
            image.insert_layer(con, helper, 0)
            con.set_mode(Gimp.LayerMode.NORMAL); con.set_opacity(100.0); con.set_visible(True)
            con.desaturate(Gimp.DesaturateMode.LUMINANCE)
            con.curves_spline(Gimp.HistogramChannel.VALUE,
                              [0.0, 0.0, 0.25, 0.12, 0.5, 0.5, 0.75, 0.88, 1.0, 1.0])
            con.set_visible(True)
        lum = _new_layer(image, "黑白 Luminosity", Gimp.LayerMode.HSL_COLOR)
        image.insert_layer(lum, helper, len(helper.get_children()))
        Gimp.context_set_foreground(_color("black"))
        lum.fill(Gimp.FillType.FOREGROUND)
        helper.set_mode(Gimp.LayerMode.PASS_THROUGH)
        helper.set_visible(False)

        # D&B layer: 50% grey, Soft Light / Overlay
        mode = Gimp.LayerMode.OVERLAY if blend == "overlay" else Gimp.LayerMode.SOFTLIGHT
        dnb = _new_layer(image, "加深减淡 D&B", mode)
        image.insert_layer(dnb, grp, len(grp.get_children()))   # below helper
        Gimp.context_set_foreground(_color("#808080"))
        dnb.fill(Gimp.FillType.FOREGROUND)

        Gimp.context_set_foreground(_color("white"))
        Gimp.context_set_background(_color("black"))
        image.set_selected_layers([dnb])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()

def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "一键加深减淡搭建 / Dodge & Burn Setup")
        dlg.fill(["blend-mode", "contrast-boost"])
        ok = dlg.run(); dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        setup(image, drawables[0], config.get_property("blend-mode"),
              config.get_property("contrast-boost"))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

class DnB(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC]
    def do_create_procedure(self, name):
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("一键加深减淡搭建 / One-click Dodge & Burn Setup")
        p.add_menu_path("<Image>/Filters/人像精修/")
        p.set_documentation("Create a 50% grey Dodge & Burn layer plus hidden luminosity helper group. 创建加深减淡图层与观察层。",
                            "Paint white to dodge, black to burn on the D&B layer. Toggle '观察层 Helper' to inspect unevenness.", name)
        p.set_attribution("Elysia", "Elysia", "2026")
        choice = Gimp.Choice.new()
        choice.add("soft-light", 0, "Soft Light / 柔光", "")
        choice.add("overlay", 1, "Overlay / 叠加", "")
        p.add_choice_argument("blend-mode", "Blend mode / 混合模式", "D&B layer mode",
                              choice, "soft-light", GObject.ParamFlags.READWRITE)
        p.add_boolean_argument("contrast-boost", "Helper contrast boost / 观察层增强对比",
                               "Add desaturated S-curve layer to helper group", True, GObject.ParamFlags.READWRITE)
        return p

Gimp.main(DnB.__gtype__, sys.argv)
