#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 动作录制 / Record and replay a few retouch steps.  (GIMP 3.0.x and 3.2.x)
# Records only procedures that already take parameters. Not paint strokes.
import os
import sys

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
from gi.repository import Gimp, GimpUi, GObject, GLib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layers
import store

START = "python-fu-action-record-start"
STOP = "python-fu-action-record-stop"
PLAY = "python-fu-action-play"
PROCS = [START, STOP, PLAY]


def _gimp_dir():
    d = Gimp.directory()
    if d:
        return d
    return os.path.join(GLib.get_user_config_dir(), "GIMP", "3.0")


def _fail(procedure, status, text):
    return procedure.new_return_values(status, GLib.Error(text))


def _status_ok(res):
    st = res.index(0)
    try:
        if st == Gimp.PDBStatusType.SUCCESS:
            return True
    except Exception:
        pass
    try:
        return int(st) == int(Gimp.PDBStatusType.SUCCESS)
    except Exception:
        return False


def _active_layer(image, fallback):
    try:
        layers = image.get_selected_layers()
    except Exception:
        layers = None
    if layers:
        return layers[0]
    return fallback


def _set_drawables(cfg, proc, layer):
    names = [p.get_name() for p in proc.get_arguments()]
    if "drawables" in names:
        if hasattr(cfg, "set_core_object_array"):
            cfg.set_core_object_array("drawables", [layer])
        else:
            cfg.set_property("drawables", [layer])
    elif "drawable" in names:
        cfg.set_property("drawable", layer)


def _set_arg(cfg, key, value):
    if key in ("radius", "feather"):
        cfg.set_property(key, float(value))
    elif key in ("contrast-boost", "place-on-top"):
        cfg.set_property(key, bool(value))
    else:
        cfg.set_property(key, value)


def _select_target(image, target):
    """Select the recorded layer. Unhide only when selection itself refuses a
    hidden layer, and say so by returning True so the caller can hide it again."""
    try:
        image.set_selected_layers([target])
        return False
    except Exception:
        if target.get_visible():
            raise
    target.set_visible(True)
    image.set_selected_layers([target])
    return True


def _run_step(image, layer, step):
    name = step.get("procedure")
    if not name:
        raise RuntimeError("步骤缺少过程名 / A step has no procedure")
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc is None:
        raise RuntimeError("找不到 %s，请先安装对应插件 / Procedure is not installed: %s" % (name, name))
    ref = step.get("layer")
    unhid = False
    if ref:
        target = layers.find_layer(image, ref)
        if target is None or not isinstance(target, Gimp.Layer):
            raise RuntimeError(
                "找不到记录的图层「%s」，这一步没有改到别的图层上。" % layers.layer_label(ref))
        unhid = _select_target(image, target)
    else:
        # Built-in steps have no recorded layer: use whatever is current,
        # which is how running the two plugins by hand behaves.
        target = _active_layer(image, layer)
        if target is None or not isinstance(target, Gimp.Layer):
            raise RuntimeError("请选择一个图层再播放 / Select a layer before playing")
    try:
        cfg = proc.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("image", image)
        _set_drawables(cfg, proc, target)
        for key, value in (step.get("args") or {}).items():
            _set_arg(cfg, key, value)
        res = proc.run(cfg)
        if not _status_ok(res):
            detail = ""
            try:
                if res.length() > 1 and res.index(1) is not None:
                    detail = " " + str(res.index(1))
            except Exception:
                pass
            raise RuntimeError("播放失败 %s%s / Playback failed" % (name, detail))
    finally:
        if unhid:
            try:
                target.set_visible(False)
            except Exception:
                pass
    return target


def run_start(procedure, run_mode, image, drawables, config, data):
    try:
        store.start(_gimp_dir())
    except Exception as exc:
        return _fail(procedure, Gimp.PDBStatusType.EXECUTION_ERROR, str(exc))
    Gimp.displays_flush()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def run_stop(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(STOP)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "停止录制 / Stop Recording")
        dlg.fill(["action-name"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        path = store.stop(_gimp_dir(), config.get_property("action-name"))
    except Exception as exc:
        return _fail(procedure, Gimp.PDBStatusType.EXECUTION_ERROR, str(exc))
    Gimp.message("已保存动作 / Saved action: " + path)
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def run_play(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PLAY)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "播放动作 / Play Action")
        dlg.fill(["action-name"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    layer = drawables[0] if drawables else None
    try:
        action = store.load_action(_gimp_dir(), config.get_property("action-name"))
        image.undo_group_start()
        try:
            for step in action.get("steps") or []:
                layer = _run_step(image, layer, step)
        finally:
            image.undo_group_end()
    except Exception as exc:
        return _fail(procedure, Gimp.PDBStatusType.EXECUTION_ERROR, str(exc))
    Gimp.displays_flush()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


_RUN = {START: run_start, STOP: run_stop, PLAY: run_play}


class ActionRecord(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return list(PROCS)

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, _RUN[name], None)
        p.set_image_types("*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_attribution("Elysia", "Elysia", "2026")
        if name == START:
            p.set_menu_label("开始录制 / Start Recording")
            p.set_documentation(
                "开始把后面的几步记下来。只记一键频率分离、加深减淡搭建、选出主体。尚未人工验证。",
                "Freehand paint, liquify strokes and spot-heal clicks are not recorded. Not verified by hand.",
                name,
            )
        elif name == STOP:
            p.set_menu_label("停止录制 / Stop Recording")
            p.set_documentation(
                "给刚录的步骤起个名字并保存。尚未人工验证。",
                "The action is stored as JSON in this GIMP version's config. Playback also looks at the other version. Not verified by hand.",
                name,
            )
            p.add_string_argument("action-name", "Name / 动作名称", "Name to save the recording under", "", F)
        else:
            p.set_menu_label("播放动作 / Play Action")
            p.set_documentation(
                "按名字播放已保存的动作，或内置的「自然修图准备」。尚未人工验证。",
                "自然修图准备 runs frequency separation at its own default (radius 0 = auto), then dodge-and-burn setup at its own defaults. Not verified by hand.",
                name,
            )
            p.add_string_argument(
                "action-name", "Name / 动作名称",
                "Saved action name, or the built-in 自然修图准备",
                "自然修图准备", F,
            )
        p.add_menu_path("<Image>/Filters/修图工具/")
        return p


Gimp.main(ActionRecord.__gtype__, sys.argv)
