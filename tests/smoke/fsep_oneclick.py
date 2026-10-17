img, lay = portrait()
src = pixels(lay)
before = img.duplicate()
call("python-fu-fsep-oneclick", img, [lay])
expect_tree(img, [
    (0, "Frequency Separation", "group", "normal", 100, True, False),
    (1, "High (高频)", "layer", "grain-merge", 100, True, False),
    (1, "Low (低频)", "layer", "normal", 100, True, False),
    (0, "背景", "layer", "normal", 100, False, False)])
if pixels(lay) != src:
    die("original layer changed")
if [l.get_name() for l in img.get_selected_layers()] != ["High (高频)"]:
    die("High is not selected")
a, b = img.duplicate().flatten(), before.flatten()
d = max(abs(x - y) for x, y in zip(pixels(a), pixels(b)))
ok("composite max diff vs original %d" % d)
if d > 2:
    die("High + Low do not rebuild the photo")
ok("OK")
