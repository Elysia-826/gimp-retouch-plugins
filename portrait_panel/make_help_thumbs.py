# Dev tool: regenerate portrait_panel/help/*_before.jpg / *_after.jpg (240 px wide crops).
# GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
#   -b "exec(open('portrait_panel/make_help_thumbs.py').read(), {'__name__': 't'})"
# Each workspace is built on a fresh copy of the test photo and its mask is filled white
# (feathered, like soft-brush painting) over a face region (coords from tests/portrait_panel; mouth ~y2480-2600).
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio

SRC = os.environ.get("PP_HELP_SRC", "/workspace/retouch-trial/before.jpg")
OUT = os.path.abspath("portrait_panel/help")
spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)

CHEEK = ("ell", (1260, 1960, 300, 320))      # right cheek (viewer's right), below the eye
CHEEK_CROP = (1130, 1830, 560, 560)
# key: (workspace, selection made before the click or None, feathered mask fill, crop rect)
JOBS = {
    "dered":    ("ws:dered",    None, CHEEK, CHEEK_CROP),
    "unify":    ("ws:unify",    None, CHEEK, CHEEK_CROP),
    "dnb":      ("ws:dnb",      None, CHEEK, CHEEK_CROP),
    "deshine":  ("ws:deshine",  None, ("ell", (800, 1820, 170, 420)), (640, 1780, 500, 500)),
    "undereye": ("ws:undereye", None, ("ell", (450, 1705, 330, 80)), (380, 1560, 440, 280)),
    "eye":      ("ws:eye", ("ell", (400, 1595, 390, 115)), ("ell", (400, 1595, 390, 115)), (380, 1560, 440, 280)),
    "teeth":    ("ws:teeth", ("ell", (720, 2500, 480, 170)), ("ell", (720, 2500, 480, 170)), (660, 2440, 600, 320)),
    "sharpen":  ("ws:sharpen",  None, ("rect", (480, 1580, 240, 160)), (480, 1580, 240, 160)),   # 1:1 crop, eye
}


def select(img, kind, r):
    (img.select_ellipse if kind == "ell" else img.select_rectangle)(Gimp.ChannelOps.REPLACE, *r)


def save_crop(img, crop, path):
    d = img.duplicate(); d.flatten()
    d.crop(crop[2], crop[3], crop[0], crop[1])
    w = 240; h = max(1, round(crop[3] * w / crop[2]))
    if crop[2] != w:
        d.scale(w, h)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, d, Gio.File.new_for_path(path), None)
    d.delete()


for key, (ws, sel, fill, crop) in JOBS.items():
    try:
        img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(SRC))
        save_crop(img, crop, os.path.join(OUT, key + "_before.jpg"))
        if sel:
            select(img, *sel)
        msg = pp.build_workspace(img, ws)
        tgt = img.get_selected_layers()[0]
        m = tgt.get_mask()
        Gimp.context_push(); Gimp.context_set_opacity(100.0)
        Gimp.context_set_foreground(Gegl.Color.new("white"))
        select(img, *fill)
        Gimp.Selection.feather(img, 0 if key == "sharpen" else 40.0)
        m.edit_fill(Gimp.FillType.FOREGROUND); Gimp.Selection.none(img)
        Gimp.context_pop()
        save_crop(img, crop, os.path.join(OUT, key + "_after.jpg"))
        print("HELP ok", key, tgt.get_name(), flush=True)
        img.delete()
    except Exception as e:
        print("HELP FAIL", key, e, flush=True)
