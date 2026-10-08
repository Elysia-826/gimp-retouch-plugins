#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 选出主体 / Select subject   (GIMP 3.0.x and 3.2.x)
# One plugin, two modes: the person, or face skin only.
# The edge is GrabCut or border color, plus a short dark-pixel expansion.
# That is not a hair matte. No numpy here. No DrawableFilter.
# OpenCV runs in a host Python helper, same idea as mesh_liquify's face helper.
import os
import subprocess
import sys
import tempfile

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-subject-select"

def _note_recorded(procedure, args):
    """If 动作录制 is recording, append this call. Missing recorder = do nothing."""
    try:
        import importlib.util
        path = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "action_record", "store.py"))
        if not os.path.isfile(path):
            return
        spec = importlib.util.spec_from_file_location("retouch_action_store", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        gdir = Gimp.directory() if hasattr(Gimp, "directory") else ""
        mod.note_step(gdir or "", procedure, args)
    except Exception:
        return




def _bytes(data):
    if data is None:
        return b""
    return bytes(data)


def _cv2_launcher():
    """A python that can import cv2. Flatpak GIMP does not have it; the host one does."""
    homes = []
    if os.environ.get("HOME"):
        homes.append(os.environ["HOME"])
    homes.append(os.path.expanduser("~"))
    for extra in ("/home/box", "/run/host/home/box"):
        if os.path.isdir(extra):
            homes.append(extra)
    sites = [""]
    seen = set()
    for home in homes:
        local = os.path.join(home, ".local", "lib")
        if not os.path.isdir(local):
            continue
        for name in sorted(os.listdir(local)):
            sp = os.path.join(local, name, "site-packages")
            if os.path.isdir(sp) and sp not in seen:
                seen.add(sp)
                sites.append(sp)
    pythons = []
    for cand in ("/usr/bin/python3", "/run/host/usr/bin/python3"):
        if os.path.exists(cand):
            pythons.append(cand)
    for py in pythons:
        for sp in sites:
            env = os.environ.copy()
            if sp:
                env["PYTHONPATH"] = sp + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            try:
                r = subprocess.run([py, "-c", "import cv2"], capture_output=True, env=env, timeout=30)
            except Exception:
                continue
            if r.returncode == 0:
                return py, env
    return None, None


def _model_path():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    if os.environ.get("SUBJECT_MASK_MODEL"):
        cands.append(os.environ["SUBJECT_MASK_MODEL"])
    cands.append(os.path.join(here, "face_detection_yunet_2023mar.onnx"))
    cands.append(os.path.join(here, "..", "mesh_liquify", "face_detection_yunet_2023mar.onnx"))
    homes = [os.environ.get("HOME") or "", os.path.expanduser("~"), "/home/box"]
    for home in homes:
        if not home:
            continue
        for ver in ("3.0", "3.2"):
            cands.append(os.path.join(home, ".config", "GIMP", ver, "plug-ins", "mesh_liquify", "face_detection_yunet_2023mar.onnx"))
            cands.append(os.path.join(home, ".var", "app", "org.gimp.GIMP", "config", "GIMP", ver, "plug-ins", "mesh_liquify", "face_detection_yunet_2023mar.onnx"))
    for cand in cands:
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _export_ppm(layer, path):
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(ext.x, ext.y, w, h)
    raw = _bytes(buf.get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    if len(raw) != w * h * 3:
        raw4 = _bytes(buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
        if len(raw4) != w * h * 4:
            raise RuntimeError("读不到图层像素 / Cannot read the layer")
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            rgb[i * 3:i * 3 + 3] = raw4[i * 4:i * 4 + 3]
        raw = bytes(rgb)
    with open(path, "wb") as f:
        f.write(("P6\n%d %d\n255\n" % (w, h)).encode("ascii"))
        f.write(raw)


def _read_pgm(path, w, h):
    with open(path, "rb") as f:
        magic = f.readline().strip()
        if magic != b"P5":
            raise RuntimeError("蒙版格式不对 / Bad mask file")
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        ww, hh = [int(x) for x in line.split()]
        maxv = f.readline().strip()
        if ww != w or hh != h or maxv != b"255":
            raise RuntimeError("蒙版尺寸不对 / Mask size does not match the layer")
        data = f.read(w * h)
    if len(data) != w * h:
        raise RuntimeError("蒙版不完整 / Truncated mask")
    return data


def _run_helper(layer, mode):
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "subject_select.py")
    if not os.path.isfile(script):
        raise RuntimeError("找不到选区助手 / Selection helper is missing. Nothing was changed.")
    py, env = _cv2_launcher()
    if py is None:
        raise RuntimeError("需要本机 Python 里的 OpenCV（cv2）。画面没有改动。 / OpenCV is not available. Nothing was changed.")
    model = _model_path()
    if mode == "skin" and model is None:
        raise RuntimeError("皮肤选区要用 mesh_liquify 里的认脸模型，现在找不到。画面没有改动。 / Face model from mesh_liquify is missing. Nothing was changed.")
    fd1, ppm = tempfile.mkstemp(prefix="subject-mask-", suffix=".ppm")
    fd2, pgm = tempfile.mkstemp(prefix="subject-mask-", suffix=".pgm")
    os.close(fd1)
    os.close(fd2)
    try:
        _export_ppm(layer, ppm)
        cmd = [py, script, model or "-", ppm, pgm, mode]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
        line = ""
        for part in (r.stdout or "").splitlines():
            if part.startswith("{"):
                line = part
        if not line:
            err = (r.stderr or "").strip().splitlines()
            tail = err[-1] if err else ("exit %s" % r.returncode)
            raise RuntimeError("选区助手没有结果。画面没有改动。 / Helper returned nothing. Nothing was changed. " + tail)
        import json
        info = json.loads(line)
        if not info.get("ok"):
            code = info.get("error") or "fail"
            if code == "no-face":
                raise RuntimeError("没有找到脸，没有做皮肤选区。画面没有改动。 / No face, so no skin selection. Nothing was changed.")
            if code == "no-subject":
                raise RuntimeError("分不出主体（背景不干净，也没认到脸）。画面没有改动。 / Could not separate a subject. Nothing was changed.")
            if code == "no-cv2":
                raise RuntimeError("OpenCV 导入失败。画面没有改动。 / OpenCV import failed. Nothing was changed.")
            raise RuntimeError("选区没有做成（%s）。画面没有改动。 / Selection failed. Nothing was changed." % code)
        mask = _read_pgm(pgm, layer.get_width(), layer.get_height())
        return mask, info
    finally:
        for path in (ppm, pgm):
            try:
                os.remove(path)
            except OSError:
                pass


def _drop_named(image, name):
    try:
        channels = image.get_channels()
    except Exception:
        return
    for ch in channels or []:
        try:
            if ch.get_name() == name:
                image.remove_channel(ch)
        except Exception:
            continue


def apply_selection(image, layer, mode, feather):
    if layer.is_group():
        raise RuntimeError("请选中照片图层，不要选图层组 / Choose the photo layer, not a group")
    mask, info = _run_helper(layer, mode)
    w, h = layer.get_width(), layer.get_height()
    _ok, ox, oy = layer.get_offsets()
    ox, oy = int(ox), int(oy)
    name = "皮肤选区" if mode == "skin" else "主体选区"
    # Skin feather stays small so the eye holes are not painted shut.
    radius = float(feather)
    if mode == "skin":
        radius = min(radius, 1.0)
    radius = max(0.0, min(20.0, radius))
    image.undo_group_start()
    try:
        _drop_named(image, name)
        ch = Gimp.Channel.new(image, name, image.get_width(), image.get_height(), 50.0, Gegl.Color.new("black"))
        image.insert_channel(ch, None, 0)
        ch.get_buffer().set(Gegl.Rectangle.new(ox, oy, w, h), "Y' u8", mask)
        ch.set_visible(False)
        image.select_item(Gimp.ChannelOps.REPLACE, ch)
        if radius > 0.0:
            Gimp.Selection.feather(image, radius)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return info


def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR, GLib.Error("请选择一个图层 / Select one layer"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "选出主体 / Select Subject")
        dlg.fill(["mode", "feather"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        mi = config.get_choice_id("mode")
        mode = "skin" if mi == 1 else "subject"
        apply_selection(image, drawables[0], mode, config.get_property("feather"))
        _note_recorded(PROC, {"mode": mode, "feather": float(config.get_property("feather"))})
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class SubjectMask(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("选出主体 / Select Subject")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Select the person, or face skin only. Edge is feathered a little. 选出人或脸部皮肤，边缘略虚。",
            "Not a hair matte: stray hairs are only a short dark-pixel expansion from the silhouette. "
            "Backlit hair can still be cut off. Skin mode needs the YuNet model shipped with mesh_liquify. "
            "Eyes and the mouth are punched out of the skin selection when a face is found. "
            "Not verified by hand. 尚未人工验证。不是发丝抠图。",
            name,
        )
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("subject", 0, "Subject / 主体", "The person, with a slightly soft edge")
        ch.add("skin", 1, "Skin / 皮肤", "Face skin, not hair. Eyes and mouth left out when a face is found")
        p.add_choice_argument("mode", "Mode / 模式", "Subject selection or a skin-only selection.", ch, "subject", F)
        p.add_double_argument(
            "feather", "Feather px / 羽化",
            "Subject uses this. Skin uses at most 1 px so the eyes stay out. 0 keeps the helper edge only.",
            0.0, 20.0, 2.0, F)
        return p


Gimp.main(SubjectMask.__gtype__, sys.argv)
