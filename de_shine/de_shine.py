#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 去油光 / De-shine   (GIMP 3.0.x and 3.2.x)
# Finds oily highlights on skin (brighter than the skin around them and paler),
# and pulls only their low-frequency brightness and colour toward the nearby
# skin tone. Pores and fine texture are copied from the photo. The photo layer
# is never changed: the result is a new layer with a layer mask.
#   新手 / Beginner: one layer, mask = detected shine x strength.
#   专业 / Pro: the same layer, plus a 去油光画笔 layer (full correction, black
#   mask) to paint in with white; brush opacity = strength.
# OpenCV runs in a host Python helper (deshine_helper.py), like subject_mask.
import os
import subprocess
import sys
import tempfile

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-de-shine"
LAYER = "去油光"
BRUSH_LAYER = "去油光画笔"

def _bytes(data):
    if data is None:
        return b""
    return bytes(data)


HELPER_PY_FILE = "retouch-helper-python.txt"   # one line: full path of a python that has OpenCV
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW: no console flash

def _python_candidates():
    """Pythons that may have OpenCV. An explicit choice first, then the usual places."""
    out = []

    def add(p):
        if p and os.path.isfile(p) and p not in out:
            out.append(p)

    add(os.environ.get("RETOUCH_HELPER_PYTHON", ""))
    try:
        gd = Gimp.directory()
    except Exception:
        gd = ""
    if gd:
        # the installer writes this file into each GIMP profile (Windows)
        for d in [gd] + [os.path.join(os.path.dirname(gd), v) for v in ("3.2", "3.0")]:
            try:
                with open(os.path.join(d, HELPER_PY_FILE), encoding="utf-8-sig") as fh:
                    add(fh.readline().strip().strip('"'))
            except OSError:
                pass
    if os.name == "nt":
        import glob
        import shutil
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            add(os.path.join(local, "Programs", "retouch-python", "python.exe"))
            for p in sorted(glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe")), reverse=True):
                add(p)
        for name in ("python.exe", "python3.exe"):
            p = shutil.which(name)
            if p and "WindowsApps" not in p:   # skip the Microsoft Store stub
                add(p)
    else:
        for cand in ("/usr/bin/python3", "/run/host/usr/bin/python3"):
            add(cand)
    return out

def _helper_env(site=""):
    env = os.environ.copy()
    if os.name == "nt":
        # GIMP's own Python settings must not leak into a different Python
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
    if site:
        env["PYTHONPATH"] = site + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env

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
    for py in _python_candidates():
        for sp in sites:
            env = _helper_env(sp)
            try:
                r = subprocess.run([py, "-c", "import cv2"], capture_output=True, env=env, timeout=60, **_NOWIN)
            except Exception:
                continue
            if r.returncode == 0:
                return py, env
    return None, None


def _model_path():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    if os.environ.get("DESHINE_MODEL"):
        cands.append(os.environ["DESHINE_MODEL"])
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



def _write_pgm(path, data, w, h):
    with open(path, "wb") as f:
        f.write(("P5\n%d %d\n255\n" % (w, h)).encode("ascii"))
        f.write(data)


def _read_pnm(path, w, h, ch):
    with open(path, "rb") as f:
        f.readline()
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        ww, hh = [int(x) for x in line.split()]
        f.readline()
        data = f.read(w * h * ch)
    if ww != w or hh != h or len(data) != w * h * ch:
        raise RuntimeError("助手结果尺寸不对 / Helper output size mismatch")
    return data


def _selection_for(image, layer):
    """Selection under the layer as Y' u8 bytes, or None when nothing is selected."""
    try:
        empty = Gimp.Selection.is_empty(image)
    except Exception:
        empty = True
    if empty:
        return None
    w, h = layer.get_width(), layer.get_height()
    _ok, ox, oy = layer.get_offsets()
    buf = image.get_selection().get_buffer()
    return _bytes(buf.get(Gegl.Rectangle.new(int(ox), int(oy), w, h), 1.0, "Y' u8", Gegl.AbyssPolicy.NONE))


def _run_helper(image, layer, sens, soft, only_face, flash=False):
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "deshine_helper.py")
    if not os.path.isfile(script):
        raise RuntimeError("找不到去油光助手。画面没有改动。 / deshine_helper.py is missing. Nothing was changed.")
    py, env = _cv2_launcher()
    if py is None:
        raise RuntimeError("需要本机 Python 里的 OpenCV（cv2）。画面没有改动。 / OpenCV is not available. Nothing was changed.")
    model = _model_path()
    if only_face and model is None:
        raise RuntimeError("「只处理脸部」要用 mesh_liquify 里的认脸模型，现在找不到。画面没有改动。 / Face model from mesh_liquify is missing. Nothing was changed.")
    w, h = layer.get_width(), layer.get_height()
    sel = _selection_for(image, layer)
    paths = []
    for suf in (".ppm", ".pgm", ".ppm", ".pgm"):
        fd, p = tempfile.mkstemp(prefix="de-shine-", suffix=suf)
        os.close(fd)
        paths.append(p)
    inp, selp, outp, maskp = paths
    try:
        _export_ppm(layer, inp)
        if sel is not None:
            _write_pgm(selp, sel, w, h)
        cmd = [py, script, model or "-", inp, selp if sel is not None else "-", outp, maskp,
               str(float(sens)), str(float(soft)), "1" if only_face else "0", "1" if flash else "0"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300, **_NOWIN)
        line = ""
        for part in (r.stdout or "").splitlines():
            if part.startswith("{"):
                line = part
        if not line:
            err = (r.stderr or "").strip().splitlines()
            tail = err[-1] if err else ("exit %s" % r.returncode)
            raise RuntimeError("去油光助手没有结果。画面没有改动。 / Helper returned nothing. Nothing was changed. " + tail)
        import json
        info = json.loads(line)
        if not info.get("ok"):
            code = info.get("error") or "fail"
            if code == "no-face":
                raise RuntimeError("没有找到脸。可以关掉「只处理脸部」，或先画选区。画面没有改动。 / No face found. Turn off 'only face' or make a selection. Nothing was changed.")
            if code == "no-cv2":
                raise RuntimeError("OpenCV 导入失败。画面没有改动。 / OpenCV import failed. Nothing was changed.")
            raise RuntimeError("去油光没有做成（%s）。画面没有改动。 / De-shine failed. Nothing was changed." % code)
        return _read_pnm(outp, w, h, 3), _read_pnm(maskp, w, h, 1), info
    finally:
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass


def _drop_layer(image, name):
    for l in list(image.get_layers()):
        try:
            if l.get_name() == name and not l.is_group():
                image.remove_layer(l)
        except Exception:
            continue


def _new_layer(image, layer, name, rgb, maskbytes):
    w, h = layer.get_width(), layer.get_height()
    _ok, ox, oy = layer.get_offsets()
    nl = Gimp.Layer.new(image, name, w, h, Gimp.ImageType.RGB_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
    parent = layer.get_parent()
    pos = image.get_item_position(layer)
    image.insert_layer(nl, parent, pos)
    nl.set_offsets(int(ox), int(oy))
    buf = nl.get_buffer()
    buf.set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B' u8", rgb)
    buf.flush()
    nl.update(0, 0, w, h)
    m = nl.create_mask(Gimp.AddMaskType.BLACK)
    nl.add_mask(m)
    if maskbytes is not None:
        mb = m.get_buffer()
        mb.set(Gegl.Rectangle.new(0, 0, w, h), "Y u8", maskbytes)
        mb.flush()
        m.update(0, 0, w, h)
    return nl, m


def apply(image, layer, pro, strength, sens, soft, only_face, flash=False):
    if layer.is_group():
        raise RuntimeError("请选中照片图层，不要选图层组 / Choose the photo layer, not a group")
    rgb, mask, info = _run_helper(image, layer, sens, soft, only_face, flash)
    k = max(0.0, min(100.0, float(strength))) / 100.0
    scaled = mask.translate(bytes(int(v * k + 0.5) for v in range(256)))
    image.undo_group_start()
    try:
        _drop_layer(image, LAYER)
        _drop_layer(image, BRUSH_LAYER)
        auto, amask = _new_layer(image, layer, LAYER, rgb, scaled)
        if pro:
            brush, bmask = _new_layer(image, layer, BRUSH_LAYER, rgb, None)
            image.reorder_item(brush, auto.get_parent(), image.get_item_position(auto))
            image.set_selected_layers([brush])
            try:
                image.set_selected_drawables([bmask]) if hasattr(image, "set_selected_drawables") else None
            except Exception:
                pass
            try:
                bmask.set_edit_mask(True) if hasattr(bmask, "set_edit_mask") else brush.set_edit_mask(True)
            except Exception:
                pass
            try:
                Gimp.context_set_foreground(Gegl.Color.new("white"))
                Gimp.context_set_background(Gegl.Color.new("black"))
                Gimp.context_set_paint_method("gimp-paintbrush")
                Gimp.context_set_opacity(max(5.0, float(strength)))
                Gimp.context_set_brush_hardness(0.0) if hasattr(Gimp, "context_set_brush_hardness") else None
            except Exception:
                pass
        else:
            image.set_selected_layers([auto])
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
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "去油光 / De-shine")
        dlg.fill(["mode", "strength", "sensitivity", "softness", "only-face", "flash"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        pro = config.get_choice_id("mode") == 1
        layer = drawables[0]
        apply(image, layer, pro, config.get_property("strength"), config.get_property("sensitivity"),
              config.get_property("softness"), bool(config.get_property("only-face")),
              bool(config.get_property("flash")))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class DeShine(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("去油光 / De-shine")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Tone down oily shine on skin, keep the texture. 压掉皮肤油光，保留纹理。",
            "Result goes on a new layer with a mask; the photo is not changed. Beginner: one layer, "
            "mask = shine x strength. Pro: adds a 去油光画笔 layer with a black mask to paint in with white. "
            "'Only face' needs the YuNet model from mesh_liquify. An existing selection limits the area. "
            "Not verified by hand. 尚未人工验证。",
            name,
        )
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("beginner", 0, "Beginner / 新手", "One slider, done")
        ch.add("pro", 1, "Pro / 专业", "Also a 去油光画笔 layer to paint in by hand")
        p.add_choice_argument("mode", "Mode / 模式", "Beginner or pro.", ch, "beginner", F)
        p.add_double_argument("strength", "Strength / 力度", "How much shine to remove (mask opacity).", 0.0, 100.0, 50.0, F)
        p.add_double_argument("sensitivity", "Sensitivity / 检测灵敏度", "Higher also catches fainter shine.", 0.0, 100.0, 50.0, F)
        p.add_double_argument("softness", "Edge softness / 边缘柔和度", "Blur of the mask edge.", 0.0, 100.0, 30.0, F)
        p.add_boolean_argument("only-face", "Only face / 只处理脸部", "Limit to detected faces (eyes and mouth left out).", True, F)
        p.add_boolean_argument("flash", "Flash hard light / 闪光灯硬光",
                               "Direct flash: catch larger near-white hotspots and give them back a little grain from nearby skin.", False, F)
        return p


Gimp.main(DeShine.__gtype__, sys.argv)
