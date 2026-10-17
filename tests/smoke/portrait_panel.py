import importlib.util, sys
G = os.environ["GIMP3_DIRECTORY"]
sys.path.insert(0, os.path.join(G, "plug-ins", "portrait_panel"))
spec = importlib.util.spec_from_file_location("pp", os.path.join(G, "plug-ins", "portrait_panel", "portrait_panel.py"))
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)
proc = pdb.lookup_procedure("python-fu-portrait-panel")
cfg = proc.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
if proc.run(cfg).index(0) != Gimp.PDBStatusType.CALLING_ERROR:
    die("non-interactive call should be refused")
keys = ["ws:dnb", "ws:fsep", "ws:heal"]
photo = os.environ.get("SMOKE_FACE")
if photo:
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(photo))
    keys.insert(1, "ws:deshine")
else:
    img, _ = portrait()
    ok("ws:deshine skipped (no face photo)")
before = pixels(img.duplicate().flatten())
for key in keys:
    msg = pp.build_workspace(img, key)
    sel = img.get_selected_layers()
    ok("%s -> %s | selected %s" % (key, msg, [l.get_name() for l in sel]))
    if len(sel) != 1 or (key in ("ws:dnb", "ws:deshine") and (sel[0].get_mask() is None or not sel[0].get_edit_mask())):
        die("%s: painting layer not selected" % key)
    d = max(abs(a - b) for a, b in zip(before, pixels(img.duplicate().flatten())))
    if d > 1:
        die("%s changed the picture (max diff %d)" % (key, d))
want = [
    (0, "插件改动", "group", "pass-through", 100, True, False),
    (1, "加深减淡", "group", "pass-through", 100, True, False),
    (2, "提亮（白色涂=变亮，黑色涂=擦掉）", "layer", "softlight", 80, True, True),
    (2, "压暗（白色涂=变暗，黑色涂=擦掉）", "layer", "softlight", 70, True, True),
    (1, "去油光（白色涂=去油光，黑色涂=擦掉）", "layer", "multiply", 100, True, True),
    (1, "去除瑕疵（修复画笔：Ctrl+点取样，再点斑）", "layer", "normal", 100, True, False),
    (1, "高低频（低频：软笔刷修明暗颜色；高频：修复/仿制修纹理）", "group", "pass-through", 100, True, False),
    (2, "Frequency Separation", "group", "normal", 100, True, False),
    (3, "High (高频)", "layer", "grain-merge", 100, True, False),
    (3, "Low (低频)", "layer", "normal", 100, True, False),
    (0, img.get_layers()[-2].get_name(), "layer", "normal", 100, False, False),
    (0, "原图（锁定）", "layer", "normal", 100, False, False)]
if not photo:
    del want[4]
expect_tree(img, want)
def walk(items):
    for l in items:
        yield l
        if l.is_group():
            yield from walk(l.get_children())
for l in [l for l in walk(img.get_layers()) if not l.is_group() and l.get_mask() is not None]:
    m = l.get_mask()
    if max(bytes(m.get_buffer().get(Gegl.Rectangle.new(0, 0, m.get_width(), m.get_height()), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))) != 0:
        die("mask of %s is not black" % l.get_name())
n0 = len(tree(img))
for l in walk(img.get_layers()):
    l.set_name("改名 " + l.get_name())
again = pp.build_workspace(img, "ws:dnb")
ok("renamed, ws:dnb again -> %s" % again)
if len(tree(img)) != n0 or not pp.start_retouch(img).startswith("已经开始过了"):
    show(img)
    die("renamed layers were not found by role")
ok("OK")
