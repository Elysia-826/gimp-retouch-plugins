def mask_max(layer):
    m = layer.get_mask()
    w, h = m.get_width(), m.get_height()
    return max(bytes(m.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "Y u8", Gegl.AbyssPolicy.NONE)))

img, lay = portrait()
src = pixels(lay)
call("python-fu-de-shine", img, [lay], only_face=False)
expect_tree(img, [
    (0, "去油光", "layer", "normal", 100, True, True),
    (0, "背景", "layer", "normal", 100, True, False)])
mx = mask_max(img.get_layers()[0])
ok("beginner mask max %d" % mx)
if mx != 128:
    die("strength 50 should give mask peak 128")
if pixels(lay) != src:
    die("original layer changed")
img, lay = portrait()
call("python-fu-de-shine", img, [lay], only_face=False, mode="pro")
expect_tree(img, [
    (0, "去油光画笔", "layer", "normal", 100, True, True),
    (0, "去油光", "layer", "normal", 100, True, True),
    (0, "背景", "layer", "normal", 100, True, False)])
top = img.get_layers()[0]
if mask_max(top) != 0:
    die("brush mask is not black")
if [l.get_name() for l in img.get_selected_layers()] != ["去油光画笔"] or not top.get_edit_mask():
    die("brush mask is not the edit target")
if round(Gimp.context_get_opacity()) != 50:
    die("brush opacity is not the strength")
ok("OK")
