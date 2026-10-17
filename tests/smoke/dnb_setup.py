for blend, nick in (("soft-light", "softlight"), ("overlay", "overlay")):
    img, lay = portrait()
    src = pixels(lay)
    call("python-fu-dnb-setup", img, [lay], blend_mode=blend)
    expect_tree(img, [
        (0, "Dodge & Burn", "group", "pass-through", 100, True, False),
        (1, "观察层 Helper", "group", "pass-through", 100, False, False),
        (2, "对比增强 Contrast", "layer", "normal", 100, True, False),
        (2, "黑白 Luminosity", "layer", "hsl-color", 100, True, False),
        (1, "加深减淡 D&B", "layer", nick, 100, True, False),
        (0, "背景", "layer", "normal", 100, True, False)])
    sel = img.get_selected_layers()
    if [l.get_name() for l in sel] != ["加深减淡 D&B"]:
        die("D&B layer is not selected")
    g = pixels(sel[0])
    if set(g[0::4]) != {128} or set(g[1::4]) != {128} or set(g[2::4]) != {128}:
        die("D&B layer is not 50% grey")
    if pixels(lay) != src:
        die("original layer changed")
    fg = Gimp.context_get_foreground().get_rgba()
    if (round(fg[0], 3), round(fg[1], 3), round(fg[2], 3)) != (1.0, 1.0, 1.0):
        die("foreground is not white")
ok("OK")
