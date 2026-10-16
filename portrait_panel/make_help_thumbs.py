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
    "dered":    ("ws:dered",    None, "strokes", (1250, 1950, 280, 280)),   # ~0.86x, tighter
    "unify":    ("ws:unify",    None, CHEEK, (1250, 1950, 300, 300)),   # tighter crop, max-strength fill
    "dnb":      ("ws:dnb",      None, "strokes", (1250, 1950, 280, 280)),
    "deshine":  ("ws:deshine",  None, ("ell", (800, 1820, 170, 420)), (760, 1880, 260, 260)),   # tighter
    "undereye": ("ws:undereye", None, "strokes", (380, 1560, 440, 280)),
    "eye":      ("ws:eye", ("ell", (400, 1595, 390, 115)), ("ell", (400, 1595, 390, 115)), (380, 1560, 440, 280)),
    # teeth: no thumbnail (test photo has a closed mouth) -> text-only help
    "sharpen":  ("ws:sharpen",  None, ("rect", (480, 1580, 240, 160)), (560, 1600, 96, 64)),   # 2.5x zoom on lashes / iris edge
}

# ~30% soft-brush strokes (feathered elongated dabs, filled at 30% opacity, overlapping like 2-3 passes)
STROKES = {
    "dered":    [(1290, 2000, 220, 70), (1320, 2080, 200, 70), (1300, 2160, 180, 60)],
    "dnb":      [(1290, 2000, 220, 70), (1320, 2080, 200, 70), (1300, 2160, 180, 60)],
    "undereye": [(470, 1710, 290, 50), (500, 1725, 230, 40)],
}

# stroke opacity per key: ~55% soft brush for dnb / dered (30% was too faint to see), 30% for undereye
STROKE_OPACITY = {"dered": 55.0, "dnb": 55.0, "undereye": 30.0}
# sharpen example uses a stronger-than-default setting so the effect is visible in a thumbnail
pp.sharpen_settings = lambda: dict(pp.SHARP_DEFAULTS, radius=1.2, amount=0.6)


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
        Gimp.context_push()
        Gimp.context_set_foreground(Gegl.Color.new("white"))
        if fill == "strokes":
            Gimp.context_set_opacity(STROKE_OPACITY[key])
            for r in STROKES[key]:
                select(img, "ell", r)
                Gimp.Selection.feather(img, 30.0)
                m.edit_fill(Gimp.FillType.FOREGROUND)
        else:
            Gimp.context_set_opacity(100.0)
            select(img, *fill)
            Gimp.Selection.feather(img, 0 if key == "sharpen" else 40.0)
            m.edit_fill(Gimp.FillType.FOREGROUND)
        Gimp.Selection.none(img)
        Gimp.context_pop()
        save_crop(img, crop, os.path.join(OUT, key + "_after.jpg"))
        print("HELP ok", key, tgt.get_name(), flush=True)
        img.delete()
    except Exception as e:
        print("HELP FAIL", key, e, flush=True)
