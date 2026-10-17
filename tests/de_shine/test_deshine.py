# Headless test for python-fu-de-shine. Run with python-fu-eval (see README).
import os
import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl, Gio
Gegl.init(None)
pdb = Gimp.get_pdb()
SRC = os.environ.get("DESHINE_TEST_IMAGE", "/workspace/retouch-trial/before.jpg")
NECK = [int(v) for v in os.environ.get("DESHINE_NECK", "500,2850,800,3150").split(",") if v]


def die(m):
    print("DESHINE_TEST FAIL " + m, flush=True)
    raise SystemExit(1)


def px(d, fmt="R'G'B' u8"):
    w, h = d.get_width(), d.get_height()
    return bytes(d.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, fmt, Gegl.AbyssPolicy.NONE))


def call(img, layer, mode, strength=50.0, only_face=True, flash=False):
    proc = pdb.lookup_procedure("python-fu-de-shine")
    if proc is None:
        die("procedure missing")
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", img)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    cfg.set_property("mode", mode)
    cfg.set_property("strength", strength)
    cfg.set_property("only-face", only_face)
    cfg.set_property("flash", flash)
    return proc.run(cfg)


def ok(res):
    return "SUCCESS" in str(res.index(0)).upper()


for mode in ("beginner", "pro", "flash"):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(SRC))
    photo = img.get_layers()[0]
    before = px(photo)
    res = call(img, photo, "pro" if mode == "pro" else "beginner", flash=(mode == "flash"))
    if not ok(res):
        die("%s status %s" % (mode, res.index(0)))
    if px(photo) != before:
        die("photo layer changed")
    names = [l.get_name() for l in img.get_layers()]
    print("DESHINE_TEST %s layers %s" % (mode, names), flush=True)
    want = ["去油光画笔", "去油光"] if mode == "pro" else ["去油光"]
    if names[:len(want)] != want:
        die("layers wrong")
    auto = img.get_layers()[names.index("去油光")]
    m = auto.get_mask()
    if m is None:
        die("no mask")
    mb = px(m, "Y u8")  # linear, what GIMP composites with
    mx = max(mb)
    cover = sum(1 for v in mb[::7] if v > 20) * 7.0 / len(mb)
    print("DESHINE_TEST mask max %d cover %.3f" % (mx, cover), flush=True)
    if mx < 60 or mx > 135:
        die("mask max should be about strength 50%")
    if cover <= 0 or cover > 0.25:
        die("mask coverage odd")
    # highlights reduced: mean luma where mask is strong
    ap = px(auto)
    w = auto.get_width()
    d = n = 0.0
    for i in range(0, len(mb), 3):
        if mb[i] > 100:
            j = i * 3
            d += (sum(before[j:j + 3]) - sum(ap[j:j + 3])) / 3.0
            n += 1
    print("DESHINE_TEST strong px %d mean luma drop %.2f" % (n, d / max(n, 1)), flush=True)
    if n == 0 or d / n < 3:
        die("highlights not reduced")
    if NECK:
        x0, y0, x1, y1 = NECK
        neck = max(mb[y * w + x] for y in range(y0, y1, 5) for x in range(x0, x1, 5))
        print("DESHINE_TEST neck mask max %d" % neck, flush=True)
        if neck != 0:
            die("neck processed")
    if mode == "pro":
        bl = img.get_layers()[0]
        if max(px(bl.get_mask(), "Y' u8")) != 0:
            die("brush mask not black")
        fg = Gimp.context_get_foreground()
        print("DESHINE_TEST fg %s paint %s" % (fg.get_rgba(), Gimp.context_get_paint_method()), flush=True)
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path("/tmp/deshine_%s.xcf" % mode), None)
    img.flatten()
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, img, Gio.File.new_for_path("/tmp/deshine_%s.png" % mode), None)
    img.delete()
print("DESHINE_TEST ok", flush=True)
