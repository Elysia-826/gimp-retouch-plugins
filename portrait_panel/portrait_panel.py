#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 人像面板 / Portrait Panel   (GIMP 3.0.x and 3.2.x)
# A non-modal GTK window with our retouch tools in working order. Each button
# runs an existing plug-in procedure by PDB name; tools that are not installed
# or not built yet are greyed out. The plug-in process keeps running until the
# window is closed. Step 1: frame only (buttons + 开始修这张 + group helper).
import json
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
HELP = "从上往下按顺序点。先点「开始修这张」备份原图；灰色按钮是还没装或还没做的功能。"

# (group id, title, [(label, pdb name or None, tooltip)])
GROUPS = [
    ("start", "开始", [("开始修这张", "__start__", "复制一份原图并锁住，建「插件改动」图层组，之后的改动都放进组里")]),
    ("skin", "皮肤", [
        ("去除瑕疵", "ws:heal", "建一个空的「去除瑕疵」层，切到修复画笔（Ctrl+点取样，再点斑）。⚙ = 点修复插件（填坐标自动补）"),
        ("去油光", "ws:deshine", "建去油光层，蒙版全黑（画面不变），白色涂=去油光。⚙ = 去油光参数"),
        ("高低频", "ws:fsep", "建高低频组，选中低频层并设好软画笔。⚙ = 频率分离参数"),
        ("加深减淡", "ws:dnb", "建「提亮」「压暗」两层，蒙版全黑，白色涂=生效。⚙ = 旧的 50% 灰加深减淡搭建"),
        ("轻柔涂抹", "python-fu-dnb-flow", "在加深减淡层上按流量轻涂"),
        ("磨皮", None, "还没做"),
        ("皮肤减红/统一肤色", None, "还没做"),
    ]),
    ("face", "五官", [
        ("按脸液化", "python-fu-mesh-liquify-face", "自动认脸，滑动调眼睛、下颌、鼻宽"),
        ("液化", "python-fu-mesh-liquify", "推移、膨胀、收缩、旋转、还原"),
        ("亮眼", None, "还没做"),
        ("白牙", None, "还没做"),
        ("卧蚕压色", None, "还没做"),
    ]),
    ("aux", "辅助", [
        ("选出主体", "python-fu-subject-select", "把人或脸部皮肤做成选区"),
        ("人像笔刷", "python-fu-portrait-brush", "一键设好修图常用笔刷"),
        ("看看涂到哪了", "__preview__", "把选中层的蒙版显示成半透明红色；再点一下关闭"),
        ("涂擦切换", "__swap__", "前景/背景色互换（同 X 键）：白=涂，黑=擦"),
        ("播放动作", "python-fu-action-play", "播放录好的动作"),
    ]),
    ("last", "最后", [
        ("锐化输出", None, "还没做"),
        ("批量导出", "python-fu-batch-export", "导出 JPEG/WebP/PNG"),
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
}
WS_NAMES = {
    "ws:heal": "去除瑕疵（修复画笔：Ctrl+点取样，再点斑）",
    "ws:deshine": "去油光（白色涂=去油光，黑色涂=擦掉）",
    "ws:fsep": "高低频（低频：软笔刷修明暗颜色；高频：修复/仿制修纹理）",
    "ws:dnb": "加深减淡",
}
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


def build_workspace(image, key):
    """Build one skin workspace inside 插件改动. Returns a status line."""
    if not any(l.get_name() == BACKUP_NAME for l in image.get_layers()):
        start_retouch(image)
    top = ensure_group(image)
    title = WS_NAMES[key]
    rank = WS[key][1]
    old = _find_child(top, title)
    photo = _working_layer(image)
    if photo is None:
        raise RuntimeError("找不到照片图层")
    if old is not None:
        # already built: just select it again and set the brush
        target = old
        if old.is_group():
            kids = [c for c in old.get_children() if not c.is_group()]
            target = kids[0] if kids else old
        _select_mask(image, target)
        notes = brush_setup(image, 100.0 if key == "ws:heal" else 20.0,
                            "gimp-heal" if key == "ws:heal" else "gimp-paintbrush", key != "ws:heal")
        return "「%s」已经有了，已重新选中。" % title + (" 没设上：" + "、".join(notes) if notes else "")

    if key == "ws:fsep":
        # fsep builds its group above the photo and hides the photo (composite unchanged)
        _run_noninteractive("python-fu-fsep-oneclick", image, photo, radius=0.0)
    if key == "ws:deshine":
        # work on what is visible now (after 高低频/去瑕疵 edits), not the original photo,
        # so the correction layer does not bring back old pixels where it is painted
        vis = Gimp.Layer.new_from_visible(image, image, "去油光临时合并")
        image.insert_layer(vis, None, 0)
        try:
            _run_noninteractive("python-fu-de-shine", image, vis, mode="pro", strength=100.0)
        finally:
            image.remove_layer(vis)

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
            msg = "已建「去除瑕疵」空层，切到修复画笔（不透明度 100%）：Ctrl+点干净皮肤取样，再点斑。"
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
            up = _solid_layer(image, DNB_UP, "white", Gimp.LayerMode.SOFTLIGHT, 70.0)
            image.insert_layer(up, g, 0)
            _black_mask(up)
            _select_mask(image, up)
            notes = brush_setup(image, 20.0)
            msg = "已建「提亮」「压暗」两层（纯白/纯黑柔光，不带原图像素），蒙版全黑。选中了提亮的蒙版：白色软画笔 20% 轻涂。"
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
    """The 「插件改动」 group at the top of the stack; created if missing."""
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
            return "已经开始过了：原图备份和「插件改动」组都在。"
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
    return "好了：原图已备份并锁住（最底下，隐藏），上面建了「插件改动」组。"


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
        self.img_combo.set_tooltip_text("要修的图片。打开了新图后点「刷新」")
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
                    ok = name in ("__start__", "__preview__", "__swap__") or (name is not None and pdb.procedure_exists(name))
                b.set_sensitive(ok)
                b.set_tooltip_text(tip if ok else (tip if name is None else "没装：" + str(name)))
                b.connect("clicked", self.on_button, name)
                if name == "__swap__":
                    self.swap_btn = b
                    self.update_swap_label()
                if name in WS:
                    cell = Gtk.Box(spacing=2)
                    cell.pack_start(b, True, True, 0)
                    gear = Gtk.Button(label="⚙")
                    gproc = WS[name][0]
                    gear.set_sensitive(pdb.procedure_exists(gproc))
                    gear.set_tooltip_text("打开参数对话框（也可 Shift+点按钮）：" + gproc)
                    gear.connect("clicked", self.on_button, gproc)
                    cell.pack_start(gear, False, False, 0)
                    grid.add(cell)
                else:
                    grid.add(b)
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
            if name == "__preview__":
                self.status.set_text(toggle_preview(image))
                return
            if name == "__swap__":
                Gimp.context_swap_colors()
                self.update_swap_label()
                Gimp.displays_flush()
                return
            if name in WS:
                ok, state = Gtk.get_current_event_state()
                if ok and (state & Gdk.ModifierType.SHIFT_MASK):
                    name = WS[name][0]
                else:
                    self.status.set_text(build_workspace(image, name))
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
                                 ("已取消" if st == Gimp.PDBStatusType.CANCEL else "没做成：%s" % name))
        except Exception as e:
            self.status.set_text("出错：%s" % e)
        Gimp.displays_flush()

    def update_swap_label(self):
        try:
            fg = Gimp.context_get_foreground().get_rgba()
            lum = 0.3 * fg[0] + 0.6 * fg[1] + 0.1 * fg[2]
            self.swap_btn.set_label("涂擦切换\n当前：%s" % ("白=涂" if lum >= 0.5 else "黑=擦"))
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
    if run_mode != Gimp.RunMode.INTERACTIVE:
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
                                           GLib.Error("人像面板只能交互使用 / interactive only"))
    GimpUi.init(PROC)
    Panel(image)
    Gtk.main()
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
