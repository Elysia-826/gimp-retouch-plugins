img, lay = portrait()
src = pixels(lay)
call("python-fu-subject-select", img, [lay], mode="subject")
expect_tree(img, [(0, "背景", "layer", "normal", 100, True, False)])
chans = [(c.get_name(), c.get_visible()) for c in img.get_channels()]
ok("channels %s" % chans)
if chans != [("主体选区", False)]:
    die("hidden channel 主体选区 missing")
if Gimp.Selection.is_empty(img):
    die("empty selection")
inside = Gimp.Selection.value(img, 180, 216)
corner = Gimp.Selection.value(img, 4, 4)
ok("selection face=%.0f corner=%.0f" % (inside, corner))
if inside < 200 or corner > 50:
    die("selection does not follow the subject")
if pixels(lay) != src:
    die("pixels changed")
ok("OK")
