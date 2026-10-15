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
from gi.repository import Gimp, GimpUi, GObject, GLib, Gtk, Gdk

PROC = "python-fu-portrait-panel"
GROUP_NAME = "插件改动"
BACKUP_NAME = "原图（锁定）"
CFG_FILE = "portrait-panel.json"
HELP = "从上往下按顺序点。先点「开始修这张」备份原图；灰色按钮是还没装或还没做的功能。"

# (group id, title, [(label, pdb name or None, tooltip)])
GROUPS = [
    ("start", "开始", [("开始修这张", "__start__", "复制一份原图并锁住，建「插件改动」图层组，之后的改动都放进组里")]),
    ("skin", "皮肤", [
        ("去油光", "python-fu-de-shine", "自动压暗油光，结果在带蒙版的新图层"),
        ("点修复", "python-fu-spot-heal", "用周围纹理补掉小斑点"),
        ("频率分离", "python-fu-fsep-oneclick", "拆成低频（颜色明暗）和高频（纹理）两层"),
        ("加深减淡", "python-fu-dnb-setup", "建 50% 灰加深减淡层和观察层"),
        ("轻柔涂抹", "python-fu-dnb-flow", "在加深减淡层上按流量轻涂"),
        ("磨皮", None, "还没做"),
    ]),
    ("face", "五官", [
        ("按脸液化", "python-fu-mesh-liquify-face", "自动认脸，滑动调眼睛、下颌、鼻宽"),
        ("液化", "python-fu-mesh-liquify", "推移、膨胀、收缩、旋转、还原"),
        ("亮眼", None, "还没做"),
        ("白牙", None, "还没做"),
    ]),
    ("aux", "辅助", [
        ("选出主体", "python-fu-subject-select", "把人或脸部皮肤做成选区"),
        ("人像笔刷", "python-fu-portrait-brush", "一键设好修图常用笔刷"),
        ("播放动作", "python-fu-action-play", "播放录好的动作"),
    ]),
    ("last", "最后", [
        ("批量导出", "python-fu-batch-export", "导出 JPEG/WebP/PNG"),
        ("锐化输出", None, "还没做"),
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
    return g


def _photo_layer(image):
    sel = [l for l in image.get_selected_layers() if not l.is_group()]
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
                ok = name == "__start__" or (name is not None and pdb.procedure_exists(name))
                b.set_sensitive(ok)
                b.set_tooltip_text(tip if ok else (tip if name is None else "没装：" + name))
                b.connect("clicked", self.on_button, name)
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
            proc = Gimp.get_pdb().lookup_procedure(name)
            cfg = proc.create_config()
            cfg.set_property("run-mode", Gimp.RunMode.INTERACTIVE)
            props = [p.name for p in cfg.list_properties()]
            if "image" in props:
                cfg.set_property("image", image)
            if "drawables" in props:
                ds = [l for l in image.get_selected_layers()] or [_photo_layer(image)]
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

    def on_close(self, *_):
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


Gimp.main(PortraitPanel.__gtype__, sys.argv)
