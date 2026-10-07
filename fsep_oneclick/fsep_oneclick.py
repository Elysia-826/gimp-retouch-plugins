#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# One-click Frequency Separation / 一键频率分离  (GIMP 3.0.x and 3.2.x)
import sys, gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-fsep-oneclick"

def _blur(image, drawable, radius):
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure("plug-in-gauss")
    if proc is not None:
        cfg = proc.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("image", image)
        # 3.0/3.2 compat wrapper: drawables array or single drawable
        names = [p.get_name() for p in proc.get_arguments()]
        if "drawables" in names:
            cfg.set_core_object_array("drawables", [drawable]) if hasattr(cfg, "set_core_object_array") else cfg.set_property("drawables", [drawable])
        else:
            cfg.set_property("drawable", drawable)
        cfg.set_property("horizontal", float(radius))
        cfg.set_property("vertical", float(radius))
        if "method" in names:
            cfg.set_property("method", 1)
        res = proc.run(cfg)
        if res.index(0) == Gimp.PDBStatusType.SUCCESS:
            return
    # Fallback (GIMP 3.0.x/3.2.x have no plug-in-gauss): run gegl:gaussian-blur
    # in-process on the drawable buffer -> shadow buffer, then merge (undoable).
    Gegl.init(None)
    src_buf = drawable.get_buffer()
    dst_buf = drawable.get_shadow_buffer()
    g = Gegl.Node()
    src = g.create_child("gegl:buffer-source"); src.set_property("buffer", src_buf)
    blur = g.create_child("gegl:gaussian-blur")
    blur.set_property("std-dev-x", float(radius)); blur.set_property("std-dev-y", float(radius))
    blur.set_property("abyss-policy", Gegl.AbyssPolicy.CLAMP) if hasattr(Gegl, "AbyssPolicy") else None
    dst = g.create_child("gegl:write-buffer"); dst.set_property("buffer", dst_buf)
    src.link(blur); blur.link(dst); dst.process()
    dst_buf.flush()
    drawable.merge_shadow(True)
    drawable.update(0, 0, drawable.get_width(), drawable.get_height())

def default_radius(image):
    # ~4 px at 2000 px short side, scaled, clamped 2..30
    s = min(image.get_width(), image.get_height())
    return max(2.0, min(30.0, round(4.0 * s / 2000.0, 1)))

def separate(image, layer, radius):
    image.undo_group_start()
    try:
        pos = image.get_item_position(layer)
        parent = layer.get_parent()
        group = Gimp.GroupLayer.new(image, "Frequency Separation") if hasattr(Gimp, "GroupLayer") else Gimp.Layer.group_new(image)
        group.set_name("Frequency Separation")
        image.insert_layer(group, parent, pos)
        low = layer.copy(); low.set_name("Low (低频)")
        image.insert_layer(low, group, 0)
        low.set_mode(Gimp.LayerMode.NORMAL); low.set_opacity(100.0); low.set_visible(True)
        _blur(image, low, radius)
        # GIMP GRAIN_EXTRACT = lower - upper + 0.5, so High = Low-copy in
        # GRAIN_EXTRACT over an original copy, merged down (same result as
        # "new from visible", without relying on the projection in batch mode).
        base = layer.copy(); base.set_name("High (高频)")
        image.insert_layer(base, group, 0)
        base.set_mode(Gimp.LayerMode.NORMAL); base.set_opacity(100.0); base.set_visible(True)
        ext = low.copy(); ext.set_name("High-extract")
        image.insert_layer(ext, group, 0)
        ext.set_visible(True); ext.set_opacity(100.0)
        ext.set_mode(Gimp.LayerMode.GRAIN_EXTRACT)
        high = image.merge_down(ext, Gimp.MergeType.EXPAND_AS_NECESSARY)
        high.set_name("High (高频)")
        layer.set_visible(False)
        high.set_mode(Gimp.LayerMode.GRAIN_MERGE)
        image.set_selected_layers([high])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()

def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    if config.get_property("radius") <= 0:
        config.set_property("radius", default_radius(image))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "一键频率分离 / Frequency Separation")
        dlg.fill(["radius"])
        ok = dlg.run(); dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        separate(image, drawables[0], config.get_property("radius"))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

class FSep(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC]
    def do_create_procedure(self, name):
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("一键频率分离 / One-click Frequency Separation")
        p.add_menu_path("<Image>/Filters/人像精修/")
        p.set_documentation("Split layer into Low (blur) and High (grain-merge texture) layers in a group. 将图层分离为低频与高频。",
                            "Original layer is hidden and kept untouched below the group. Radius 0 = auto (~4px per 2000px).", name)
        p.set_attribution("Elysia", "Elysia", "2026")
        p.add_double_argument("radius", "Blur radius / 模糊半径 (0=auto)", "Low-frequency gaussian radius in px",
                              0.0, 200.0, 0.0, GObject.ParamFlags.READWRITE)
        return p

Gimp.main(FSep.__gtype__, sys.argv)
