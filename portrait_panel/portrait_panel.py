#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 人像面板 / Portrait Panel   (GIMP 3.0.x and 3.2.x)
# A non-modal GTK window with our retouch tools in working order. Each button
# runs an existing plug-in procedure by PDB name; tools that are not installed
# or not built yet are greyed out. The plug-in process keeps running until the
# window is closed. Step 1: frame only (buttons + 开始修这张 + group helper).
import json
import socket
import tempfile
import os
import sys

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, GimpUi, GObject, GLib, Gtk, Gdk, Gegl

PROC = "python-fu-portrait-panel"
GROUP_NAME = "插件改动"
BACKUP_NAME = "原图（锁定）"
CFG_FILE = "portrait-panel.json"
HELP = "从上往下按顺序点。按钮旁的 ? 看用法和前后对比；锐化放最后涂。先点“开始修这张”备份原图；灰色按钮是还没装或还没做的功能。"

# (group id, title, [(label, pdb name or None, tooltip)])
GROUPS = [
    ("start", "开始", [("开始修这张", "__start__", "复制一份原图并锁住，建“插件改动”图层组，之后的改动都放进组里")]),
    ("skin", "皮肤", [
        ("去除瑕疵", "ws:heal", "建一个空的“去除瑕疵”层，切到修复画笔（Ctrl+点取样，再点斑）。⚙ = 点修复插件（填坐标自动补）"),
        ("去油光", "ws:deshine", "建去油光层，蒙版全黑（画面不变），白色涂=去油光。⚙ = 去油光参数"),
        ("高低频", "ws:fsep", "建高低频组，选中低频层并设好软画笔。⚙ = 频率分离参数"),
        ("加深减淡", "ws:dnb", "建“提亮”和“压暗”两层，蒙版全黑，白色涂=生效。⚙ = 旧的 50% 灰加深减淡搭建"),
        ("轻柔涂抹", "python-fu-dnb-flow", "在加深减淡层上按流量轻涂"),
        ("磨皮", None, "还没做"),
        ("皮肤减红", "ws:dered", "建“皮肤减红”层（LCh 色度，不发亮），蒙版全黑，白色涂=减红。⚙ = 力度"),
        ("统一肤色", "ws:unify", "建“统一肤色”层（LCh 颜色轻拉），蒙版全黑，白色涂=统一。⚙ = 力度"),
    ]),
    ("face", "五官", [
        ("按脸液化", "python-fu-mesh-liquify-face", "打开按脸调整对话框：自动认脸，滑动调眼睛、下颌、鼻宽"),
        ("液化", "python-fu-mesh-liquify", "打开柔和网格液化对话框：推移、膨胀、收缩、旋转、还原"),
        ("眼部修饰", "ws:eye", "先框选眼睛，再点：建“眼白提亮”“瞳孔提亮”两组，蒙版全黑，只在选区里涂。⚙ = 调两组力度"),
        ("牙齿美白", "ws:teeth", "先框选牙齿再点：建提亮+去黄，蒙版全黑，不会涂成死白。⚙ = 力度"),
        ("卧蚕压色", "ws:undereye", "建压暗+去色，蒙版全黑，白色涂卧蚕。⚙ = 力度"),
    ]),
    ("aux", "辅助", [
        ("选择主体", "python-fu-subject-select", "打开“选出主体”对话框：把人或脸部皮肤做成选区（边缘略虚，不是发丝抠图）"),
        ("人像笔刷", "python-fu-portrait-brush", "打开人像笔刷对话框：一键设好修图常用笔刷、大小和低不透明度"),
        ("看看涂到哪了", "__preview__", "把选中层的蒙版显示成半透明红色；再点一下关闭"),
        ("涂擦切换", "__swap__", "前景/背景色互换（同 X 键）：白=涂，黑=擦"),
        ("播放动作", "python-fu-action-play", "播放录好的动作"),
    ]),
    ("last", "最后", [
        ("锐化", "ws:sharpen", "建锐化层（轻微 USM），蒙版全黑，白色涂=变锐。⚙ = 半径/力度/不透明度"),
        ("一键锐化", "__sharp_oneclick__", "按 ⚙ 里的参数直接锐化选区（没选区就整张），蒙版=选区，之后还能涂改"),
        ("更新锐化", "__sharp_refresh__", "锐化层按现在的画面重新生成，蒙版不变"),
        ("导出", "python-fu-batch-export", "打开批量导出对话框：JPEG/WebP/PNG，可缩放、锐化、水印"),
    ]),
]

CSS = b"""
.pp-help { color: #cfcfcf; font-size: 90%; }
.pp-title { font-weight: bold; margin-top: 6px; }
.pp-start  button { background: #3d6b4a; color: #fff; }
.pp-skin   button { background: #8a5a44; color: #fff; }
.pp-face   button { background: #4a5f8a; color: #fff; }
.pp-aux    button { background: #5c5c5c; color: #fff; }
.pp-last   button { background: #7a6a2e; color: #fff; }
.pp-start .pp-title { color: #7fc493; }
.pp-skin  .pp-title { color: #e0a080; }
.pp-face  .pp-title { color: #90a8e0; }
.pp-aux   .pp-title { color: #b0b0b0; }
.pp-last  .pp-title { color: #e0c860; }
button:disabled { background: #2e2e2e; color: #777; }
"""


def _cfg_path():
    try:
        return os.path.join(Gimp.directory(), CFG_FILE)
    except Exception:
        return os.path.join(os.path.expanduser("~"), "." + CFG_FILE)


def load_geometry():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            g = json.load(f)
        return [int(g[k]) for k in ("x", "y", "w", "h")]
    except Exception:
        return None


def save_geometry(win):
    try:
        x, y = win.get_position()
        w, h = win.get_size()
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump({"x": x, "y": y, "w": w, "h": h}, f)
    except Exception:
        pass


# workspace button -> (procedure for ⚙ / Shift+click, order rank inside 插件改动: higher = upper)
WS = {
    "ws:heal": ("python-fu-spot-heal", 1),
    "ws:deshine": ("python-fu-de-shine", 2),
    "ws:fsep": ("python-fu-fsep-oneclick", 0),   # replaces the photo, so it sits at the bottom
    "ws:dnb": ("python-fu-dnb-setup", 4),
    "ws:eye": ("__eyecfg__", 5),
    "ws:dered": ("__deredcfg__", 6),
    "ws:unify": ("__unifycfg__", 7),
    "ws:undereye": ("__undereyecfg__", 8),
    "ws:teeth": ("__teethcfg__", 9),
    "ws:sharpen": ("__sharpcfg__", 10),
}
WS_NAMES = {
    "ws:heal": "去除瑕疵（修复画笔：Ctrl+点取样，再点斑）",
    "ws:deshine": "去油光（白色涂=去油光，黑色涂=擦掉）",   # now a single Multiply layer
    "ws:fsep": "高低频（低频：软笔刷修明暗颜色；高频：修复/仿制修纹理）",
    "ws:dnb": "加深减淡",
    "ws:eye": "眼部修饰",
    "ws:dered": "皮肤减红",
    "ws:unify": "统一肤色",
    "ws:undereye": "卧蚕压色",
    "ws:teeth": "牙齿美白",
    "ws:sharpen": "锐化（白色涂=变锐，黑色涂=擦掉）",
}
DNB_UP_COLOR = "#c8b0a0"
DNB_UP_OPACITY = 80.0
DNB_UP = "提亮（白色涂=变亮，黑色涂=擦掉）"
DNB_DOWN = "压暗（白色涂=变暗，黑色涂=擦掉）"


def _color(name):
    from gi.repository import Gegl
    return Gegl.Color.new(name)


def brush_setup(image, opacity=20.0, method="gimp-paintbrush", hardness_soft=True):
    """Paintbrush, soft brush, FG white / BG black, low opacity. Returns notes on what failed."""
    notes = []
    calls = [
        ("paint method", lambda: Gimp.context_set_paint_method(method)),
        ("foreground", lambda: Gimp.context_set_foreground(_color("white"))),
        ("background", lambda: Gimp.context_set_background(_color("black"))),
        ("opacity", lambda: Gimp.context_set_opacity(float(opacity))),
        ("paint mode", lambda: Gimp.context_set_paint_mode(Gimp.LayerMode.NORMAL)),
    ]
    for label, fn in calls:
        try:
            fn()
        except Exception:
            notes.append(label)
    try:
        br = None
        for nm in ("Portrait Soft Round 人像柔圆", "2. Hardness 025"):
            br = Gimp.Brush.get_by_name(nm)
            if br is not None:
                break
        if br is not None:
            Gimp.context_set_brush(br)
        if hardness_soft:
            Gimp.context_set_brush_hardness(0.25)
        long_side = max(image.get_width(), image.get_height())
        Gimp.context_set_brush_size(max(10.0, long_side / 40.0))
    except Exception:
        notes.append("brush")
    return notes


def _working_layer(image):
    """The photo: top-level pixel layer that is not the locked backup."""
    for l in image.get_layers():
        try:
            if not l.is_group() and l.get_name() != BACKUP_NAME and l.get_visible():
                return l
        except Exception:
            continue
    for l in image.get_layers():
        if not l.is_group() and l.get_name() != BACKUP_NAME:
            return l
    return None


def _insert_ranked(image, group, item, rank):
    """Insert a new item into group so higher rank sits higher (children are top first)."""
    pos = 0
    for c in group.get_children():
        r = _rank_of(c)
        if r is not None and r > rank:
            pos += 1
    image.insert_layer(item, group, pos)


def _in_image(image, item):
    try:
        return item.get_image() is not None and item.get_image().get_id() == image.get_id()
    except Exception:
        return False


def _rank_of(item):
    try:
        n = item.get_name()
    except Exception:
        return None
    for k, v in WS_NAMES.items():
        if n == v:
            return WS[k][1]
    return None


def _find_child(group, name):
    for c in group.get_children():
        if c.get_name() == name:
            return c
    return None


def _new_group(image, name):
    g = Gimp.GroupLayer.new(image, name) if hasattr(Gimp, "GroupLayer") else Gimp.Layer.group_new(image)
    g.set_name(name)
    g.set_mode(Gimp.LayerMode.PASS_THROUGH)
    return g


def _solid_layer(image, name, color, mode, opacity):
    lay = Gimp.Layer.new(image, name, image.get_width(), image.get_height(),
                         Gimp.ImageType.RGB_IMAGE, opacity, mode)
    Gimp.context_push()
    try:
        Gimp.context_set_foreground(_color(color))
        lay.fill(Gimp.FillType.FOREGROUND)
    finally:
        Gimp.context_pop()
    return lay


def _black_mask(layer):
    m = layer.create_mask(Gimp.AddMaskType.BLACK)
    layer.add_mask(m)
    return m


def _select_mask(image, layer):
    image.set_selected_layers([layer])
    try:
        if layer.get_mask() is not None:
            layer.set_edit_mask(True)
    except Exception:
        pass


def _run_noninteractive(name, image, layer, **props):
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc is None:
        raise RuntimeError("没装：" + name)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", image)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    for k, v in props.items():
        cfg.set_property(k, v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        err = ""
        try:
            err = res.index(1)
        except Exception:
            pass
        raise RuntimeError("%s 没做成 %s" % (name, err or ""))


EYE_WHITE = "眼白提亮（白色涂=变亮，黑色涂=擦掉）"
EYE_IRIS = "瞳孔提亮（白色涂=变亮，黑色涂=擦掉）"
EYE_DEFAULTS = {"white": 28.0, "iris": 30.0}
EYE_LIFT_NAMES = {"white": "眼白提亮层", "iris": "瞳孔提亮层"}
EYE_DERED = "眼白去红血丝层"
EYE_DERED_OPACITY = 40.0   # opacity % of the white soft-light layer


def eye_strengths():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            g = json.load(f)
        return {k: float(g.get("eye_" + k, v)) for k, v in EYE_DEFAULTS.items()}
    except Exception:
        return dict(EYE_DEFAULTS)


def set_eye_strengths(vals, image=None):
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            g = json.load(f)
    except Exception:
        g = {}
    for k, v in vals.items():
        g["eye_" + k] = float(v)
    try:
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(g, f)
    except Exception:
        pass
    if image is not None:
        top = find_group(image)
        eg = _find_child(top, WS_NAMES["ws:eye"]) if top is not None else None
        if eg is not None:
            for sub, key in ((EYE_WHITE, "white"), (EYE_IRIS, "iris")):
                sg = _find_child(eg, sub)
                if sg is not None:
                    for c in sg.get_children():
                        n = c.get_name()
                        if n == EYE_LIFT_NAMES[key] or n.startswith("提亮"):
                            c.set_opacity(float(vals[key]))
            Gimp.displays_flush()


def build_eye(image, top, rank):
    """眼部修饰: needs a selection around the eye(s). Mode-based layers only (no photo
    pixels): white soft light lifts, a grey LCh-chroma layer takes the red out of
    the whites. Soft light keeps a non-white pixel below 255 and the black pupil black."""
    if Gimp.Selection.is_empty(image):
        return "请先框选眼睛（用椭圆或套索选区圈住眼睛），再点“眼部修饰”。"
    st = eye_strengths()
    _ok, _non, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
    image.undo_group_start()
    try:
        eg = _new_group(image, WS_NAMES["ws:eye"])
        _insert_ranked(image, top, eg, rank)
        subs = {}
        for sub in (EYE_IRIS, EYE_WHITE):          # 眼白 ends on top
            sg = _new_group(image, sub)
            image.insert_layer(sg, eg, 0)
            key = "white" if sub == EYE_WHITE else "iris"
            lift = _solid_layer(image, EYE_LIFT_NAMES[key], "white", Gimp.LayerMode.SOFTLIGHT, st[key])
            image.insert_layer(lift, sg, 0)
            if sub == EYE_WHITE:
                grey = _solid_layer(image, EYE_DERED, "#808080", Gimp.LayerMode.LCH_CHROMA, EYE_DERED_OPACITY)
                image.insert_layer(grey, sg, 1)
            m = sg.create_mask(Gimp.AddMaskType.BLACK)
            sg.add_mask(m)
            subs[sub] = sg
        _select_mask(image, subs[EYE_WHITE])
        notes = brush_setup(image, 20.0)
        try:
            Gimp.context_set_brush_size(max(3.0, min(x2 - x1, y2 - y1) / 4.0))
        except Exception:
            notes.append("brush size")
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“眼部修饰”：眼白提亮 / 瞳孔提亮，蒙版全黑。选区保留着，只能涂在选区里。"
            "已选中眼白的蒙版：白色软画笔 20% 涂眼白；瞳孔请在图层面板点“瞳孔提亮”组的蒙版再涂。"
            + (" 没设上：" + "、".join(notes) if notes else ""))



# ---- batch 2 item 7: 皮肤减红 / 统一肤色 / 卧蚕压色 / 牙齿美白 ----

DERED_LAYER = "皮肤减红层"
DERED_DEFAULT = 40.0
UNIFY_LAYER = "统一肤色层"
UNIFY_DEFAULT = 30.0
UNIFY_COLOR = "#c4a090"          # mid warm skin; LCh Color pulls hue/chroma gently
UNDER_DEFAULTS = {"dark": 55.0, "chroma": 35.0}
UNDER_NAMES = {"dark": "卧蚕压暗层", "chroma": "卧蚕去色层"}
TEETH_DEFAULTS = {"lift": 28.0, "chroma": 45.0}
TEETH_NAMES = {"lift": "牙齿提亮层", "chroma": "牙齿去黄层"}


def _json_cfg():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json_cfg(g):
    try:
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(g, f)
    except Exception:
        pass


def _cfg_float(key, default):
    try:
        return float(_json_cfg().get(key, default))
    except Exception:
        return float(default)


def _set_cfg_floats(pairs, image=None, apply_fn=None):
    g = _json_cfg()
    for k, v in pairs.items():
        g[k] = float(v)
    _save_json_cfg(g)
    if image is not None and apply_fn is not None:
        apply_fn(image, {k: float(v) for k, v in pairs.items()})


def dered_strength():
    return _cfg_float("dered", DERED_DEFAULT)


def set_dered_strength(val, image=None):
    _set_cfg_floats({"dered": val}, image, _apply_dered)


def _apply_dered(image, vals):
    top = find_group(image)
    g = _find_child(top, WS_NAMES["ws:dered"]) if top is not None else None
    if g is None:
        return
    for c in (g.get_children() if g.is_group() else [g]):
        if c.get_name() == DERED_LAYER:
            c.set_opacity(float(vals["dered"]))
    Gimp.displays_flush()


def unify_strength():
    return _cfg_float("unify", UNIFY_DEFAULT)


def set_unify_strength(val, image=None):
    _set_cfg_floats({"unify": val}, image, _apply_unify)


def _apply_unify(image, vals):
    top = find_group(image)
    g = _find_child(top, WS_NAMES["ws:unify"]) if top is not None else None
    if g is None:
        return
    for c in (g.get_children() if g.is_group() else [g]):
        if c.get_name() == UNIFY_LAYER:
            c.set_opacity(float(vals["unify"]))
    Gimp.displays_flush()


def under_strengths():
    g = _json_cfg()
    return {k: float(g.get("under_" + k, v)) for k, v in UNDER_DEFAULTS.items()}


def set_under_strengths(vals, image=None):
    _set_cfg_floats({"under_" + k: v for k, v in vals.items()}, image, _apply_under)


def _apply_under(image, vals):
    # vals keys are under_dark / under_chroma or dark / chroma
    st = {k: float(vals.get("under_" + k, vals.get(k, UNDER_DEFAULTS[k]))) for k in UNDER_DEFAULTS}
    top = find_group(image)
    ug = _find_child(top, WS_NAMES["ws:undereye"]) if top is not None else None
    if ug is None:
        return
    for c in ug.get_children():
        for key, nm in UNDER_NAMES.items():
            if c.get_name() == nm:
                c.set_opacity(st[key])
    Gimp.displays_flush()


def teeth_strengths():
    g = _json_cfg()
    return {k: float(g.get("teeth_" + k, v)) for k, v in TEETH_DEFAULTS.items()}


def set_teeth_strengths(vals, image=None):
    _set_cfg_floats({"teeth_" + k: v for k, v in vals.items()}, image, _apply_teeth)


def _apply_teeth(image, vals):
    st = {k: float(vals.get("teeth_" + k, vals.get(k, TEETH_DEFAULTS[k]))) for k in TEETH_DEFAULTS}
    top = find_group(image)
    tg = _find_child(top, WS_NAMES["ws:teeth"]) if top is not None else None
    if tg is None:
        return
    for c in tg.get_children():
        for key, nm in TEETH_NAMES.items():
            if c.get_name() == nm:
                c.set_opacity(st[key])
    Gimp.displays_flush()


SHARP_DEFAULTS = {"radius": 0.8, "amount": 0.3, "opacity": 100.0}
SHARP_FILTER = "gegl:unsharp-mask"
SHARP_FILTER_LABEL = "锐化"


def sharpen_settings():
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            g = json.load(f)
        return {k: float(g.get("sharp_" + k, v)) for k, v in SHARP_DEFAULTS.items()}
    except Exception:
        return dict(SHARP_DEFAULTS)


def set_sharpen_settings(vals, image=None):
    try:
        with open(_cfg_path(), encoding="utf-8") as f:
            g = json.load(f)
    except Exception:
        g = {}
    for k, v in vals.items():
        g["sharp_" + k] = float(v)
    try:
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(g, f)
    except Exception:
        pass
    if image is not None:
        top = find_group(image)
        lay = _find_child(top, WS_NAMES["ws:sharpen"]) if top is not None else None
        if lay is not None and not lay.is_group():
            try:
                lay.set_opacity(float(vals.get("opacity", lay.get_opacity())))
            except Exception:
                pass
            _apply_sharpen_filter(lay, vals)
            Gimp.displays_flush()


def _apply_sharpen_filter(lay, st):
    """Attach or retune a non-destructive gegl:unsharp-mask on the layer."""
    filt = None
    try:
        for f in lay.get_filters():
            if f.get_operation_name() == SHARP_FILTER:
                filt = f
                break
    except Exception:
        filt = None
    if filt is None:
        filt = Gimp.DrawableFilter.new(lay, SHARP_FILTER, SHARP_FILTER_LABEL)
        lay.append_filter(filt)
    cfg = filt.get_config()
    cfg.set_property("std-dev", float(st.get("radius", SHARP_DEFAULTS["radius"])))
    cfg.set_property("scale", float(st.get("amount", SHARP_DEFAULTS["amount"])))
    cfg.set_property("threshold", 0.0)
    try:
        filt.update()
    except Exception:
        pass
    return filt


def has_drawable_filters():
    """Feature-detect non-destructive filters (Gimp.DrawableFilter, GIMP 3.0+). Never assume by version alone."""
    return hasattr(Gimp, "DrawableFilter") and hasattr(Gimp.Drawable, "append_filter")


def gimp_version():
    try:
        return (int(Gimp.MAJOR_VERSION), int(Gimp.MINOR_VERSION), int(Gimp.MICRO_VERSION))
    except Exception:
        return (3, 0, 0)


def find_sharpen(image):
    top = find_group(image)
    lay = _find_child(top, WS_NAMES["ws:sharpen"]) if top is not None else None
    return None if lay is None or lay.is_group() else lay


def _sharpen_snapshot(image, st):
    """New layer = current visible image (without any existing sharpen layer) + USM."""
    old = find_sharpen(image)
    vis = old.get_visible() if old is not None else None
    if old is not None:
        old.set_visible(False)
    try:
        lay = Gimp.Layer.new_from_visible(image, image, WS_NAMES["ws:sharpen"])
    finally:
        if old is not None:
            old.set_visible(vis)
    if not has_drawable_filters():
        raise RuntimeError("这个 GIMP 没有非破坏滤镜接口，锐化做不了。画面没有改动。")
    lay.set_mode(Gimp.LayerMode.NORMAL)
    lay.set_opacity(float(st["opacity"]))
    _apply_sharpen_filter(lay, st)
    return lay


def _copy_mask(image, src_layer, dst_layer):
    """Give dst_layer a mask identical to src_layer's (via the selection; the user's selection is restored)."""
    saved = None if Gimp.Selection.is_empty(image) else Gimp.Selection.save(image)
    try:
        image.select_item(Gimp.ChannelOps.REPLACE, src_layer.get_mask())
        dst_layer.add_mask(dst_layer.create_mask(Gimp.AddMaskType.SELECTION))
    finally:
        if saved is not None:
            image.select_item(Gimp.ChannelOps.REPLACE, saved)
            image.remove_channel(saved)
        else:
            Gimp.Selection.none(image)


def sharpen_oneclick(image):
    """一键锐化: sharpen the selection (whole image if none). Mask = selection, still paintable.
    Replaces an existing sharpen layer (its pixels are re-made from the current image)."""
    if not any(l.get_name() == BACKUP_NAME for l in image.get_layers()):
        start_retouch(image)
    st = sharpen_settings()
    sel = not Gimp.Selection.is_empty(image)
    image.undo_group_start()
    try:
        top = ensure_group(image)
        old = find_sharpen(image)
        lay = _sharpen_snapshot(image, st)
        if old is not None:
            pos = image.get_item_position(old)
            image.remove_layer(old)
            image.insert_layer(lay, top, pos)
            lay.set_name(WS_NAMES["ws:sharpen"])
        else:
            _insert_ranked(image, top, lay, WS["ws:sharpen"][1])
        lay.add_mask(lay.create_mask(Gimp.AddMaskType.SELECTION if sel else Gimp.AddMaskType.WHITE))
        _select_mask(image, lay)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已锐化%s（半径 %.1f、力度 %.1f、不透明度 %d%%）。蒙版就是选区，白色涂=加、黑色涂=擦；改了前面的步骤再点“更新锐化”。"
            % ("选区" if sel else "整张", st["radius"], st["amount"], round(st["opacity"])))


def sharpen_refresh(image):
    """更新锐化: re-make the sharpen pixels from the current visible image; keep mask, opacity, position."""
    old = find_sharpen(image)
    if old is None:
        return "还没有锐化层。先点“锐化”或“一键锐化”。"
    st = sharpen_settings()
    st["opacity"] = old.get_opacity()
    image.undo_group_start()
    try:
        lay = _sharpen_snapshot(image, st)
        parent = old.get_parent()
        pos = image.get_item_position(old)
        image.insert_layer(lay, parent, pos)
        if old.get_mask() is not None:
            _copy_mask(image, old, lay)
        lay.set_visible(old.get_visible())
        image.remove_layer(old)
        lay.set_name(WS_NAMES["ws:sharpen"])   # GIMP renamed the duplicate name while old existed
        _select_mask(image, lay)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return "锐化层已按现在的画面重新生成，蒙版没变。"


def build_sharpen(image, top, rank):
    """锐化: snapshot of current visible + non-destructive USM + black mask (paint white to sharpen).
    Lives in “最后”; captures whatever is below so earlier edits stay in the sharpen look."""
    st = sharpen_settings()
    image.undo_group_start()
    try:
        lay = _sharpen_snapshot(image, st)
        _insert_ranked(image, top, lay, rank)
        _black_mask(lay)
        _select_mask(image, lay)
        notes = brush_setup(image, 20.0)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“锐化”层（轻微 USM，默认半径 %.1f、力度 %.1f），蒙版全黑。白色软画笔 20%% 在眼睛、头发、衣服边缘轻涂；皮肤少涂以免毛孔夸张。⚙ 可调。"
            % (st["radius"], st["amount"])
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_dered(image, top, rank):
    """皮肤减红: grey LCh Chroma (no HSV brightening). Black mask, paint white to reduce red."""
    st = dered_strength()
    image.undo_group_start()
    try:
        g = _new_group(image, WS_NAMES["ws:dered"])
        _insert_ranked(image, top, g, rank)
        lay = _solid_layer(image, DERED_LAYER, "#808080", Gimp.LayerMode.LCH_CHROMA, st)
        image.insert_layer(lay, g, 0)
        _black_mask(lay)
        _select_mask(image, lay)
        notes = brush_setup(image, 20.0)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“皮肤减红”：LCh 色度灰层，蒙版全黑，不发亮。白色软画笔 20% 在发红皮肤上轻涂。"
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_unify(image, top, rank):
    """统一肤色: solid mid-skin in LCh Color — gentle hue/chroma pull, keeps L and texture."""
    st = unify_strength()
    image.undo_group_start()
    try:
        g = _new_group(image, WS_NAMES["ws:unify"])
        _insert_ranked(image, top, g, rank)
        lay = _solid_layer(image, UNIFY_LAYER, UNIFY_COLOR, Gimp.LayerMode.LCH_COLOR, st)
        image.insert_layer(lay, g, 0)
        _black_mask(lay)
        _select_mask(image, lay)
        notes = brush_setup(image, 20.0)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“统一肤色”：LCh 颜色轻拉（不磨皮、不塑胶感），蒙版全黑。白色软画笔 20% 在要统一的皮肤上轻涂。"
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_undereye(image, top, rank):
    """卧蚕压色: black soft-light darken + grey LCh chroma. User paints; no selection required."""
    st = under_strengths()
    image.undo_group_start()
    try:
        g = _new_group(image, WS_NAMES["ws:undereye"])
        _insert_ranked(image, top, g, rank)
        chroma = _solid_layer(image, UNDER_NAMES["chroma"], "#808080",
                              Gimp.LayerMode.LCH_CHROMA, st["chroma"])
        image.insert_layer(chroma, g, 0)
        dark = _solid_layer(image, UNDER_NAMES["dark"], "black",
                            Gimp.LayerMode.SOFTLIGHT, st["dark"])
        image.insert_layer(dark, g, 0)   # dark on top
        # shared group mask so one paint hits both
        m = g.create_mask(Gimp.AddMaskType.BLACK)
        g.add_mask(m)
        _select_mask(image, g)
        notes = brush_setup(image, 20.0)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“卧蚕压色”：压暗 + 去色，蒙版全黑。白色软画笔 20% 涂卧蚕；想淡一点就少涂或调 ⚙。"
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_teeth(image, top, rank):
    """牙齿美白: soft-light white (capped below pure white) + LCh chroma de-yellow. Needs selection."""
    if Gimp.Selection.is_empty(image):
        return "请先框选牙齿（用椭圆或套索圈住牙齿），再点“牙齿美白”。"
    st = teeth_strengths()
    _ok, _non, x1, y1, x2, y2 = Gimp.Selection.bounds(image)
    image.undo_group_start()
    try:
        g = _new_group(image, WS_NAMES["ws:teeth"])
        _insert_ranked(image, top, g, rank)
        chroma = _solid_layer(image, TEETH_NAMES["chroma"], "#808080",
                              Gimp.LayerMode.LCH_CHROMA, st["chroma"])
        image.insert_layer(chroma, g, 0)
        lift = _solid_layer(image, TEETH_NAMES["lift"], "white",
                            Gimp.LayerMode.SOFTLIGHT, st["lift"])
        image.insert_layer(lift, g, 0)
        m = g.create_mask(Gimp.AddMaskType.BLACK)
        g.add_mask(m)
        _select_mask(image, g)
        notes = brush_setup(image, 20.0)
        try:
            Gimp.context_set_brush_size(max(3.0, min(x2 - x1, y2 - y1) / 3.0))
        except Exception:
            notes.append("brush size")
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建“牙齿美白”：提亮 + 去黄，蒙版全黑；柔光提亮不会涂成死白。选区保留着，只能涂在选区里。"
            "白色软画笔 20% 轻涂牙齿。"
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_deshine(image, top, rank, title):
    """去油光 without photo pixels: run 去油光 on what is visible now, then turn the result
    into a darkening ratio (corrected / visible) on a Multiply layer. Multiply by a
    ratio only scales whatever is below, so later 高低频 edits are never reverted."""
    vis = Gimp.Layer.new_from_visible(image, image, "去油光临时合并")
    image.insert_layer(vis, None, 0)
    try:
        _run_noninteractive("python-fu-de-shine", image, vis, mode="pro", strength=100.0)
    except Exception:
        image.remove_layer(vis)
        raise
    image.undo_group_start()
    try:
        made = {l.get_name(): l for l in image.get_layers() if l.get_name() in ("去油光", "去油光画笔")}
        corr = made.get("去油光画笔")
        if corr is None:
            raise RuntimeError("去油光没有结果")
        corr.remove_mask(Gimp.MaskApplyMode.DISCARD)
        corr.set_visible(True)
        # vis directly above corr, Divide: merge = corr / vis (both in GIMP's linear light)
        image.reorder_item(vis, None, image.get_item_position(corr))
        vis.set_mode(Gimp.LayerMode.DIVIDE)
        vis.set_visible(True)
        ratio = image.merge_down(vis, Gimp.MergeType.EXPAND_AS_NECESSARY)
        for l in made.values():
            if l is not corr and l.is_valid():
                image.remove_layer(l)
        # grey ratio = darkening only, same for R/G/B: no hue shift (colour pull turned skin red)
        try:
            ratio.desaturate(Gimp.DesaturateMode.LUMINANCE)
        except Exception:
            pass
        ratio.set_name("去油光（白色涂=去油光，黑色涂=擦掉）")
        ratio.set_mode(Gimp.LayerMode.MULTIPLY)
        ratio.set_opacity(100.0)
        _black_mask(ratio)
        image.reorder_item(ratio, None, 0)   # out of the way, then into the group
        g = top
        # place as a plain layer inside 插件改动 at the 去油光 rank
        pos = 0
        for c in g.get_children():
            r = _rank_of(c)
            if r is not None and r > rank:
                pos += 1
        image.reorder_item(ratio, g, pos)
        _select_mask(image, ratio)
        notes = brush_setup(image, 20.0)
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return ("已建去油光层（只压暗，不会把之前的修图盖掉），蒙版全黑。白色软画笔 20% 在油光上轻涂。"
            + (" 没设上：" + "、".join(notes) if notes else ""))


def build_workspace(image, key):
    """Build one skin workspace inside 插件改动. Returns a status line."""
    remove_previews(image)   # never merged into 去油光, never left in the stack
    if not any(l.get_name() == BACKUP_NAME for l in image.get_layers()):
        start_retouch(image)
    top = ensure_group(image)
    title = WS_NAMES[key]
    rank = WS[key][1]
    old = _find_child(top, title)
    photo = _working_layer(image)
    if photo is None:
        raise RuntimeError("找不到照片图层")
    builders = {
        "ws:eye": build_eye,
        "ws:dered": build_dered,
        "ws:unify": build_unify,
        "ws:undereye": build_undereye,
        "ws:teeth": build_teeth,
        "ws:sharpen": build_sharpen,
    }
    if key in builders and old is None:
        return builders[key](image, top, rank)
    if key == "ws:eye":
        wg = _find_child(old, EYE_WHITE)
        _select_mask(image, wg if wg is not None else old)
        brush_setup(image, 20.0)
        return "“眼部修饰”已经有了，已选中眼白的蒙版。"
    if key == "ws:teeth":
        _select_mask(image, old)
        brush_setup(image, 20.0)
        return "“牙齿美白”已经有了，已选中蒙版。"
    if key in ("ws:dered", "ws:unify", "ws:undereye"):
        target = old
        if old.is_group() and key != "ws:undereye":
            kids = [c for c in old.get_children() if not c.is_group()]
            target = kids[0] if kids else old
        _select_mask(image, target)
        brush_setup(image, 20.0)
        return "“%s”已经有了，已重新选中。" % title
    if old is not None:
        # already built: just select it again and set the brush
        target = old
        if old.is_group():
            kids = [c for c in old.get_children() if not c.is_group()]
            target = kids[0] if kids else old
        _select_mask(image, target)
        notes = brush_setup(image, 100.0 if key == "ws:heal" else 20.0,
                            "gimp-heal" if key == "ws:heal" else "gimp-paintbrush", key != "ws:heal")
        return "“%s”已经有了，已重新选中。" % title + (" 没设上：" + "、".join(notes) if notes else "")

    if key == "ws:fsep":
        # fsep builds its group above the photo and hides the photo (composite unchanged)
        _run_noninteractive("python-fu-fsep-oneclick", image, photo, radius=0.0)
    if key == "ws:deshine":
        return build_deshine(image, top, rank, title)
    image.undo_group_start()
    try:
        notes = []
        if key == "ws:heal":
            lay = Gimp.Layer.new(image, title, image.get_width(), image.get_height(),
                                 Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
            _insert_ranked(image, top, lay, rank)
            image.set_selected_layers([lay])
            notes = brush_setup(image, 100.0, "gimp-heal", False)
            try:
                Gimp.context_set_sample_merged(True)
            except Exception:
                notes.append("sample merged")
            msg = "已建“去除瑕疵”空层，切到修复画笔（不透明度 100%）：Ctrl+点干净皮肤取样，再点斑。"
        elif key == "ws:deshine":
            g = _new_group(image, title)
            _insert_ranked(image, top, g, rank)
            brush = auto = None
            for l in image.get_layers():
                if l.get_name() == "去油光画笔":
                    brush = l
                elif l.get_name() == "去油光":
                    auto = l
            for l in (auto, brush):          # brush layer ends on top
                if l is not None:
                    image.reorder_item(l, g, 0)
            if auto is not None:
                auto.set_name("自动去油光（蒙版已清空；想要自动结果就把蒙版填白）")
                m = auto.get_mask()
                if m is not None:
                    Gimp.context_set_background(_color("black"))
                    m.fill(Gimp.FillType.BACKGROUND)
            if brush is not None:
                brush.set_name("去油光画笔（白色涂=去油光）")
                _select_mask(image, brush)
            notes = brush_setup(image, 20.0)
            msg = "已建去油光层，蒙版全黑（画面没变）。用白色软画笔在油光上轻涂。"
        elif key == "ws:fsep":
            fs = None
            for l in image.get_layers():
                if l.is_group() and l.get_name() == "Frequency Separation":
                    fs = l
                    break
            g = _new_group(image, title)
            _insert_ranked(image, top, g, rank)
            low = None
            if fs is not None:
                image.reorder_item(fs, g, 0)
                for c in fs.get_children():
                    if c.get_name().startswith("Low"):
                        low = c
            # fsep hid the photo; the High/Low pair now shows the same picture
            if low is not None:
                image.set_selected_layers([low])
            notes = brush_setup(image, 20.0)
            msg = "已建高低频，选中了低频层，白色/取色软画笔低不透明度修明暗。纹理用修复画笔在高频层上修。"
        elif key == "ws:dnb":
            g = _new_group(image, title)
            _insert_ranked(image, top, g, rank)
            # solid white / black in soft light: no photo pixels, so they act on
            # whatever is below (高低频, 去瑕疵 ...), like an adjustment
            g.set_mode(Gimp.LayerMode.PASS_THROUGH)   # blend with the layers below, not inside the group
            down = _solid_layer(image, DNB_DOWN, "black", Gimp.LayerMode.SOFTLIGHT, 70.0)
            image.insert_layer(down, g, 0)
            _black_mask(down)
            # warm light grey, not white: lifts gently without greying the skin
            up = _solid_layer(image, DNB_UP, DNB_UP_COLOR, Gimp.LayerMode.SOFTLIGHT, DNB_UP_OPACITY)
            image.insert_layer(up, g, 0)
            _black_mask(up)
            _select_mask(image, up)
            notes = brush_setup(image, 20.0)
            msg = "已建“提亮”和“压暗”两层（柔光，不会把之前的修图盖掉），蒙版全黑。选中了提亮的蒙版：白色软画笔 20% 轻涂。"
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return msg + (" 没设上：" + "、".join(notes) if notes else "")


PREVIEW_NAME = "蒙版预览（再点一下关闭）"
_preview_src = {}   # image id -> layer id whose mask is previewed


def remove_previews(image):
    n = 0
    for l in list(image.get_layers()):
        try:
            if l.get_name() == PREVIEW_NAME:
                image.remove_layer(l)
                n += 1
        except Exception:
            continue
    return n


def toggle_preview(image):
    """Red overlay of the selected layer's mask, at the very top (outside 插件改动).
    Second call removes it and goes back to painting the mask."""
    if remove_previews(image):
        src = _preview_src.pop(image.get_id(), None)
        lay = Gimp.Layer.get_by_id(src) if src is not None else None
        if lay is not None and lay.is_valid():
            _select_mask(image, lay)
        Gimp.displays_flush()
        return "已关闭蒙版预览，回到蒙版继续涂。"
    sel = [l for l in image.get_selected_layers() if not l.is_group()]
    if not sel or sel[0].get_mask() is None:
        return "选中的图层没有蒙版，没法预览。"
    src = sel[0]
    m = src.get_mask()
    _ok, ox, oy = src.get_offsets()
    w, h = m.get_width(), m.get_height()
    data = bytes(m.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
    image.undo_group_start()
    try:
        pv = _solid_layer(image, PREVIEW_NAME, "#ff2020", Gimp.LayerMode.NORMAL, 50.0)
        image.insert_layer(pv, None, 0)
        pm = pv.create_mask(Gimp.AddMaskType.BLACK)
        pv.add_mask(pm)
        pm.get_buffer().set(Gegl.Rectangle.new(int(ox), int(oy), w, h), "Y u8", data)
        pm.update(0, 0, image.get_width(), image.get_height())
        _preview_src[image.get_id()] = src.get_id()
        _select_mask(image, src)    # keep painting on the real mask
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return "红色 = 已经涂到的地方。再点一下关闭（关面板时也会自动删掉）。"


# ---- layer helpers (used by later steps too) ----

def find_group(image):
    for l in image.get_layers():
        try:
            if l.is_group() and l.get_name() == GROUP_NAME:
                return l
        except Exception:
            continue
    return None


def ensure_group(image):
    """The “插件改动” group at the top of the stack; created if missing."""
    g = find_group(image)
    if g is not None:
        return g
    g = Gimp.GroupLayer.new(image, GROUP_NAME) if hasattr(Gimp, "GroupLayer") else Gimp.Layer.group_new(image)
    if not hasattr(Gimp, "GroupLayer"):
        g.set_name(GROUP_NAME)
    image.insert_layer(g, None, 0)
    g.set_mode(Gimp.LayerMode.PASS_THROUGH)
    return g


def _photo_layer(image):
    sel = [l for l in image.get_selected_layers() if not l.is_group() and l.get_name() != BACKUP_NAME]
    if sel:
        return sel[0]
    for l in reversed(image.get_layers()):
        if not l.is_group():
            return l
    return None


def start_retouch(image):
    """Copy the photo as a locked, hidden backup at the bottom; create the group.
    The photo layer itself stays as is and remains the working layer."""
    for l in image.get_layers():
        if l.get_name() == BACKUP_NAME:
            ensure_group(image)
            return "已经开始过了：原图备份和“插件改动”组都在。"
    photo = _photo_layer(image)
    if photo is None:
        raise RuntimeError("这张图里没有可用的图层")
    image.undo_group_start()
    try:
        bak = photo.copy()
        bak.set_name(BACKUP_NAME)
        image.insert_layer(bak, None, len(image.get_layers()))
        bak.set_visible(False)
        for fn in ("set_lock_content", "set_lock_position", "set_lock_alpha", "set_lock_visibility"):
            try:
                getattr(bak, fn)(True)
            except Exception:
                pass
        ensure_group(image)
        image.set_selected_layers([photo])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()
    return "好了：原图已备份并锁住（最底下，隐藏），上面建了“插件改动”组。"


# ---- single instance: TCP on 127.0.0.1 + lock file with the port (works on Windows too) ----
LOCK_PATH = os.path.join(tempfile.gettempdir(), "gimp-portrait-panel-%s.lock" % (os.environ.get("USERNAME") or os.environ.get("USER") or "u"))


def ping_existing(lock_path=None, msg=b"raise"):
    """True if a live panel answered (and was told to come to the front). Stale/missing lock -> False."""
    try:
        with open(lock_path or LOCK_PATH, encoding="utf-8") as f:
            port = int(f.read().split()[0])
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as c:
            c.sendall(msg)
            return c.recv(16) == b"ok"
    except Exception:
        return False


def claim_instance(lock_path=None):
    """Bind a listener and write the lock file (overwrites a stale one). -> non-blocking server socket."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0)); srv.listen(4); srv.setblocking(False)
    with open(lock_path or LOCK_PATH, "w", encoding="utf-8") as f:
        f.write("%d %d\n" % (srv.getsockname()[1], os.getpid()))
    return srv


def poll_instance(srv, on_raise):
    """Accept pending pings; call on_raise() for each. Safe to call from a GLib timeout."""
    while True:
        try:
            c, _ = srv.accept()
        except (BlockingIOError, OSError):
            return
        try:
            c.settimeout(0.5)
            if c.recv(16).startswith(b"raise"):
                c.sendall(b"ok"); on_raise()
        except Exception:
            pass
        finally:
            c.close()


def release_instance(srv, lock_path=None):
    try:
        port = srv.getsockname()[1]; srv.close()
        with open(lock_path or LOCK_PATH, encoding="utf-8") as f:
            mine = int(f.read().split()[0]) == port
        if mine:
            os.remove(lock_path or LOCK_PATH)
    except Exception:
        pass


# ---- batch 2 item 9: per-button usage help (tooltip + ? popup) ----
HELP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help")
# label -> (2-3 plain lines: what / how to paint / when, thumbnail key or None)
BUTTON_HELP = {
    "开始修这张": ("备份一份原图并锁住，建“插件改动”组。\n不用涂，点一下就行。\n每张图第一步先点它。", None),
    "去除瑕疵": ("建空的修复层，切到修复画笔。\n按住 Ctrl 点干净皮肤取样，再点痘痘、斑点。\n先去瑕疵，再做别的。", None),
    "去油光": ("压暗反光的油亮处；只压暗，不会把之前的修图盖掉。\n蒙版全黑，白色软画笔 20% 在额头、鼻头、下巴的亮斑上轻涂。\n脸上反光明显时用。", "deshine"),
    "高低频": ("把照片拆成两层：低频管颜色和明暗，高频管毛孔纹理。\n低频用软笔刷涂匀色块；高频用修复/仿制修纹理。\n原图有备份，不会丢。要细修皮肤时用。", None),
    "加深减淡": ("建“提亮”和“压暗”两层，蒙版全黑。\n白色软画笔低不透明度：亮的地方涂压暗，暗的地方涂提亮。\n修凹凸不平、塑造轮廓时用。", "dnb"),
    "轻柔涂抹": ("在加深减淡层上按很低的流量慢慢涂。\n来回多涂几次叠加效果。\n做完“加深减淡”后用。", None),
    "磨皮": ("还没做。", None),
    "皮肤减红": ("降低皮肤的红色，不会发亮。\n蒙版全黑，白色软画笔在发红的脸颊、鼻翼轻涂。\n涂满会发灰，20% 轻涂即可。", "dered"),
    "统一肤色": ("把皮肤颜色轻轻往统一的肤色靠，保留纹理。\n蒙版全黑，白色软画笔 20% 在色块不匀的地方轻涂。\n脸上颜色深一块浅一块时用。", "unify"),
    "按脸液化": ("自动找到脸，用滑块调眼睛大小、下颌、鼻宽。\n点了会弹出对话框，不用涂，拖滑块看预览。\n想整体微调脸型时用。", None),
    "液化": ("网格液化：推、膨胀、收缩、旋转、还原。\n点了会弹出对话框，在里面用笔刷拖动。\n局部修形（发际、轮廓）时用，幅度要小。", None),
    "眼部修饰": ("先框选眼睛再点；白色软画笔涂眼白（提亮、去红血丝）。\n瞳孔：在图层面板点“瞳孔提亮”组的蒙版，再在瞳孔上涂。\n⚙ 调力度，默认眼白 28、瞳孔 30。", "eye"),
    "牙齿美白": ("提亮牙齿并去黄，不会变成死白。只在露出牙齿的照片上用。\n先框选牙齿再点；选区只圈牙齿，别圈到嘴唇。\n白色软画笔 20% 只涂牙齿。", None),
    "卧蚕压色": ("把眼下发暗发青的地方压暗并去色。蒙版全黑，白色软画笔沿卧蚕涂。\n涂满会很重，只用 20% 轻涂一两遍；\n觉得重就点 ⚙ 调小。", "undereye"),
    "选择主体": ("把整个人或脸部皮肤做成选区（边缘略虚）。\n点了会弹出对话框，在里面选范围，不用涂。\n只想改人或只改背景时用。", None),
    "人像笔刷": ("点开后选步骤，笔刷大小和不透明度自动设好。\n选好后直接在蒙版上涂。\n换不同修图步骤时用。", None),
    "看看涂到哪了": ("把选中层的蒙版显示成半透明红色。\n再点一下关闭。\n想检查有没有漏涂、涂出界时用。", None),
    "涂擦切换": ("前景、背景色互换（同 X 键）。\n白色=涂上效果，黑色=擦掉效果。\n涂多了想擦回来时用。", None),
    "播放动作": ("播放之前录好的一串操作。\n不用涂。\n多张照片要重复同样步骤时用。", None),
    "锐化": ("新建一层轻微锐化（是点按钮那一刻画面的拷贝）。\n蒙版全黑，白色软画笔轻涂眼睛、头发、衣服边缘，皮肤少涂。\n最好最后做；之后又改了前面的步骤，点“更新锐化”，涂过的地方不会变旧。", "sharpen"),
    "一键锐化": ("按 ⚙ 里的半径、力度直接锐化选区；没选区就锐化整张。\n结果是新的一层，蒙版就是选区，白色涂=加、黑色涂=擦。\n眼睛、头发要快速锐化时用；前面改了再点“更新锐化”。", None),
    "更新锐化": ("锐化层按现在的画面重新生成，蒙版、不透明度都不变。\n锐化之后又改了前面的步骤（比如去瑕疵、液化）时点一下。\n不用涂。", None),
    "导出": ("批量导出 JPEG/WebP/PNG，可缩放、锐化、加水印。\n点了会弹出对话框，不用涂。\n全部修完最后一步用。", None),
}


def help_thumbs(label):
    """-> (before path, after path) or None if no example exists."""
    key = BUTTON_HELP.get(label, ("", None))[1]
    if not key:
        return None
    b, a = (os.path.join(HELP_DIR, "%s_%s.jpg" % (key, w)) for w in ("before", "after"))
    return (b, a) if os.path.exists(b) and os.path.exists(a) else None


def help_text(label, fallback=""):
    return BUTTON_HELP.get(label, (fallback, None))[0]


class Panel:
    def __init__(self, image):
        self.image = image
        self.win = Gtk.Window(title="人像面板")
        self.win.set_keep_above(False)
        self.win.set_border_width(10)
        geo = load_geometry()
        if geo:
            self.win.move(geo[0], geo[1])
            self.win.resize(max(200, geo[2]), max(200, geo[3]))
        else:
            self.win.set_default_size(300, 760)
        self.win.connect("delete-event", self.on_close)

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        help_l = Gtk.Label(label=HELP)
        help_l.set_line_wrap(True)
        help_l.set_xalign(0.0)
        help_l.get_style_context().add_class("pp-help")
        outer.pack_start(help_l, False, False, 0)

        self.img_combo = Gtk.ComboBoxText()
        self.img_combo.set_tooltip_text("要修的图片。打开了新图后点“刷新”")
        row = Gtk.Box(spacing=4)
        row.pack_start(self.img_combo, True, True, 0)
        rb = Gtk.Button(label="刷新")
        rb.connect("clicked", lambda *_: self.refresh_images())
        row.pack_start(rb, False, False, 0)
        outer.pack_start(row, False, False, 0)

        pdb = Gimp.get_pdb()
        for gid, title, items in GROUPS:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.get_style_context().add_class("pp-" + gid)
            t = Gtk.Label(label=title)
            t.set_xalign(0.0)
            t.get_style_context().add_class("pp-title")
            box.pack_start(t, False, False, 0)
            grid = Gtk.FlowBox()
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            grid.set_max_children_per_line(2)
            grid.set_homogeneous(True)
            for label, name, tip in items:
                b = Gtk.Button(label=label)
                if name in WS:
                    need = {"ws:deshine": "python-fu-de-shine", "ws:fsep": "python-fu-fsep-oneclick"}.get(name)
                    ok = need is None or pdb.procedure_exists(need)
                else:
                    ok = name in ("__start__", "__preview__", "__swap__", "__sharp_oneclick__", "__sharp_refresh__") or (name is not None and pdb.procedure_exists(name))
                b.set_sensitive(ok)
                b.set_tooltip_text(help_text(label, tip) if ok or name is None else "没装：" + str(name))
                b.connect("clicked", self.on_button, name)
                if name == "__swap__":
                    self.swap_btn = b
                    self.update_swap_label()
                cell = Gtk.Box(spacing=2)
                cell.pack_start(b, True, True, 0)
                q = Gtk.Button(label="?")
                q.set_tooltip_text("“%s”怎么用（附前后对比）" % label)
                q.connect("clicked", lambda _w, lab=label: self.help_dialog(lab))
                cell.pack_start(q, False, False, 0)
                if name in WS:
                    gear = Gtk.Button(label="⚙")
                    gproc = WS[name][0]
                    gear.set_sensitive(gproc.startswith("__") or pdb.procedure_exists(gproc))
                    gear.set_tooltip_text("打开参数对话框（也可 Shift+点按钮）：" + gproc)
                    gear.connect("clicked", self.on_button, gproc)
                    cell.pack_start(gear, False, False, 0)
                grid.add(cell)
            box.pack_start(grid, False, False, 0)
            outer.pack_start(box, False, False, 0)

        self.status = Gtk.Label(label="")
        self.status.set_line_wrap(True)
        self.status.set_xalign(0.0)
        outer.pack_end(self.status, False, False, 0)
        cb = Gtk.Button(label="关闭面板")
        cb.connect("clicked", lambda *_: (self.on_close(), self.win.destroy()))
        outer.pack_end(cb, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(outer)
        self.win.add(sw)
        self.refresh_images()
        self.win.show_all()

    def refresh_images(self):
        self.images = list(Gimp.get_images())
        self.img_combo.remove_all()
        active = 0
        for i, im in enumerate(self.images):
            name = ""
            for getter in ("get_file", "get_imported_file", "get_xcf_file"):
                try:
                    f = getattr(im, getter)()
                    if f is not None and f.get_path():
                        name = os.path.basename(f.get_path())
                        break
                except Exception:
                    continue
            if not name:
                try:
                    name = im.get_name()
                except Exception:
                    name = "未命名"
            self.img_combo.append_text("[%d] %s" % (im.get_id(), name))
            if self.image is not None and im.get_id() == self.image.get_id():
                active = i
        if self.images:
            self.img_combo.set_active(active)

    def current_image(self):
        i = self.img_combo.get_active()
        if 0 <= i < len(self.images) and self.images[i].is_valid():
            return self.images[i]
        self.refresh_images()
        return self.images[0] if self.images else None

    def on_button(self, _b, name):
        image = self.current_image()
        if image is None:
            self.status.set_text("没有打开的图片")
            return
        try:
            if name == "__start__":
                self.status.set_text(start_retouch(image))
                return
            if name in WS:
                ok, state = Gtk.get_current_event_state()
                if ok and (state & Gdk.ModifierType.SHIFT_MASK):
                    name = WS[name][0]
                else:
                    self.status.set_text(build_workspace(image, name))
                    return
            if name == "__eyecfg__":
                self.eye_dialog(image)
                return
            if name == "__deredcfg__":
                self.simple_strength_dialog(
                    image, "皮肤减红力度",
                    "数值越大，涂满时减红越强。默认 40。",
                    [("dered", "减红", dered_strength(), 0, 80)],
                    lambda vals: set_dered_strength(vals["dered"], image))
                return
            if name == "__unifycfg__":
                self.simple_strength_dialog(
                    image, "统一肤色力度",
                    "数值越大，涂满时拉色越明显。默认 30，建议别太大以免假。",
                    [("unify", "统一", unify_strength(), 0, 70)],
                    lambda vals: set_unify_strength(vals["unify"], image))
                return
            if name == "__undereyecfg__":
                st = under_strengths()
                self.simple_strength_dialog(
                    image, "卧蚕压色力度",
                    "压暗 + 去色。默认压暗 55、去色 35。",
                    [("dark", "压暗", st["dark"], 0, 90),
                     ("chroma", "去色", st["chroma"], 0, 80)],
                    lambda vals: set_under_strengths(vals, image))
                return
            if name == "__teethcfg__":
                st = teeth_strengths()
                self.simple_strength_dialog(
                    image, "牙齿美白力度",
                    "提亮用柔光，不会涂成死白。默认提亮 28、去黄 45。",
                    [("lift", "提亮", st["lift"], 0, 60),
                     ("chroma", "去黄", st["chroma"], 0, 80)],
                    lambda vals: set_teeth_strengths(vals, image))
                return
            if name == "__sharpcfg__":
                st = sharpen_settings()
                self.simple_strength_dialog(
                    image, "锐化参数",
                    "半径越大越影响大结构；力度越大越锐。默认半径 0.8、力度 0.3（和批量导出一样偏轻）。不透明度是整层上限。",
                    [("radius", "半径", st["radius"], 0.1, 5.0, 0.05),
                     ("amount", "力度", st["amount"], 0.0, 2.0, 0.05),
                     ("opacity", "不透明度", st["opacity"], 0, 100, 1)],
                    lambda vals: set_sharpen_settings(vals, image))
                return
            if name == "__sharp_oneclick__":
                self.status.set_text(sharpen_oneclick(image))
                return
            if name == "__sharp_refresh__":
                self.status.set_text(sharpen_refresh(image))
                return
            if name == "__preview__":
                self.status.set_text(toggle_preview(image))
                return
            if name == "__swap__":
                Gimp.context_swap_colors()
                self.update_swap_label()
                Gimp.displays_flush()
                return
            proc = Gimp.get_pdb().lookup_procedure(name)
            cfg = proc.create_config()
            cfg.set_property("run-mode", Gimp.RunMode.INTERACTIVE)
            props = [p.name for p in cfg.list_properties()]
            if "image" in props:
                cfg.set_property("image", image)
            if "drawables" in props:
                ds = [l for l in image.get_selected_layers() if not l.is_group()] or [_working_layer(image)]
                if hasattr(cfg, "set_core_object_array"):
                    cfg.set_core_object_array("drawables", ds)
                else:
                    cfg.set_property("drawables", ds)
            res = proc.run(cfg)
            st = res.index(0)
            self.status.set_text("完成" if st == Gimp.PDBStatusType.SUCCESS else
                                 ("对话框已关闭，没有改动" if st == Gimp.PDBStatusType.CANCEL else "没做成：%s" % name))
        except Exception as e:
            self.status.set_text("出错：%s" % e)
        finally:
            # dialogs of other plug-ins / ⚙ dialogs leave the panel behind the image window
            GLib.idle_add(self._raise_panel)
        Gimp.displays_flush()

    def _raise_panel(self):
        try:
            self.win.deiconify()
            self.win.present_with_time(Gdk.CURRENT_TIME)
            # some window managers ignore present() from a background plug-in; a brief keep-above forces it
            self.win.set_keep_above(True)
            GLib.timeout_add(200, lambda: (self.win.set_keep_above(False), False)[1])
        except Exception:
            pass
        return False

    def help_dialog(self, label):
        d = Gtk.Dialog(title="怎么用：" + label, transient_for=self.win, modal=False)
        d.add_button("知道了", Gtk.ResponseType.CLOSE)
        box = d.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        d.set_default_size(420, -1)
        lab = Gtk.Label(label=help_text(label, "暂无说明"))
        lab.set_line_wrap(True); lab.set_xalign(0.0)
        lab.set_width_chars(30); lab.set_max_width_chars(40)
        box.pack_start(lab, False, False, 4)
        th = help_thumbs(label)
        if th:
            row = Gtk.Box(spacing=6)
            for cap, path in (("之前", th[0]), ("之后", th[1])):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                col.pack_start(Gtk.Image.new_from_file(path), False, False, 0)
                col.pack_start(Gtk.Label(label=cap), False, False, 0)
                row.pack_start(col, False, False, 0)
            box.pack_start(row, False, False, 0)
            note = Gtk.Label(label="示例只作参考；实际用 20%～30% 软画笔轻涂，效果以你涂的为准。")
            note.set_line_wrap(True); note.set_xalign(0.0); note.get_style_context().add_class("pp-help")
            box.pack_start(note, False, False, 0)
        d.connect("response", lambda w, _r: (w.destroy(), GLib.idle_add(self._raise_panel)))
        d.show_all()
        d.resize(420, 1)   # shrink to content (text-only popups had ~100px blank)

    def eye_dialog(self, image):
        st = eye_strengths()
        d = Gtk.Dialog(title="眼部修饰力度", transient_for=self.win, modal=True)
        d.add_buttons("取消", Gtk.ResponseType.CANCEL, "确定", Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        lab = Gtk.Label(label="数值越大，涂满时越亮。眼白默认 28，瞳孔默认 30；改了会同时用到已建好的图层。")
        lab.set_line_wrap(True)
        box.pack_start(lab, False, False, 0)
        scales = {}
        for key, text in (("white", "眼白提亮"), ("iris", "瞳孔提亮")):
            row = Gtk.Box(spacing=6)
            row.pack_start(Gtk.Label(label=text), False, False, 0)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 80, 1)
            sc.set_value(st[key])
            sc.set_hexpand(True)
            row.pack_start(sc, True, True, 0)
            box.pack_start(row, False, False, 0)
            scales[key] = sc
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            set_eye_strengths({k: v.get_value() for k, v in scales.items()}, image)
            self.status.set_text("眼部修饰力度已保存。")
        d.destroy()


    def simple_strength_dialog(self, image, title, help_text, scales_spec, on_ok):
        """scales_spec: list of (key, label, value, lo, hi[, step]). on_ok(dict)."""
        d = Gtk.Dialog(title=title, transient_for=self.win, modal=True)
        d.add_buttons("取消", Gtk.ResponseType.CANCEL, "确定", Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        lab = Gtk.Label(label=help_text)
        lab.set_line_wrap(True)
        box.pack_start(lab, False, False, 0)
        scales = {}
        for spec in scales_spec:
            key, text_, val, lo, hi = spec[:5]
            step = float(spec[5]) if len(spec) > 5 else 1.0
            row = Gtk.Box(spacing=6)
            row.pack_start(Gtk.Label(label=text_), False, False, 0)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
            sc.set_value(float(val))
            sc.set_hexpand(True)
            if step < 1:
                sc.set_digits(2)
            row.pack_start(sc, True, True, 0)
            box.pack_start(row, False, False, 0)
            scales[key] = sc
        d.show_all()
        if d.run() == Gtk.ResponseType.OK:
            on_ok({k: v.get_value() for k, v in scales.items()})
            self.status.set_text(title.replace("力度", "").replace("参数", "") + "已保存。")
        d.destroy()

    def update_swap_label(self):
        try:
            fg = Gimp.context_get_foreground().get_rgba()
            lum = 0.3 * fg[0] + 0.6 * fg[1] + 0.1 * fg[2]
            self.swap_btn.set_label("涂擦：%s" % ("白=涂" if lum >= 0.5 else "黑=擦"))
        except Exception:
            pass

    def on_close(self, *_):
        for im in Gimp.get_images():
            try:
                remove_previews(im)
            except Exception:
                pass
        Gimp.displays_flush()
        save_geometry(self.win)
        Gtk.main_quit()
        return False


def run(procedure, run_mode, image, drawables, config, data):
    # Filters > Repeat / Re-show re-invoke with WITH_LAST_VALS; that is still a user click, so open the panel.
    if run_mode == Gimp.RunMode.NONINTERACTIVE:
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
                                           GLib.Error("人像面板只能交互使用 / interactive only"))
    if ping_existing():          # a panel is already open: it brings itself to the front
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    GimpUi.init(PROC)
    srv = claim_instance()
    panel = Panel(image)
    GLib.timeout_add(300, lambda: (poll_instance(srv, panel._raise_panel), True)[1])
    try:
        Gtk.main()
    finally:
        release_instance(srv)
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class PortraitPanel(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        p.set_menu_label("人像面板 / Portrait Panel")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation("Portrait retouch panel: our tools in working order. 人像修图面板。",
                            "Non-modal window; buttons call existing plug-ins. Not verified by hand. 尚未人工验证。", name)
        p.set_attribution("Elysia", "Elysia", "2026")
        return p


if __name__ == "__main__":
    Gimp.main(PortraitPanel.__gtype__, sys.argv)
