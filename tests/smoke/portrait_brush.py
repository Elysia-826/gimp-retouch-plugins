want = {
    "dnb": ("Portrait Soft Round 人像柔圆", 0.15, 0.10, 10, "gimp-paintbrush"),
    "texture": ("Portrait Skin Pores 皮肤毛孔", 1.0, 0.50, 25, "gimp-paintbrush"),
    "heal": ("Portrait Soft Round 人像柔圆", 0.35, 0.10, 30, "gimp-heal"),
    "hair": ("Portrait Hair Strand 细发丝", 1.0, 0.05, 60, "gimp-paintbrush"),
}
for mode, w in want.items():
    img, lay = portrait()
    src = pixels(lay)
    call("python-fu-portrait-brush", img, [lay], mode=mode)
    got = (Gimp.context_get_brush().get_name(), round(Gimp.context_get_brush_hardness(), 2),
           round(Gimp.context_get_brush_spacing(), 2), round(Gimp.context_get_opacity()), Gimp.context_get_paint_method())
    ok("%s %s dynamics=%s" % (mode, got, Gimp.context_get_dynamics_name()))
    if got != w or Gimp.context_get_dynamics_name() != "Pressure Opacity" or Gimp.context_get_paint_mode() != Gimp.LayerMode.NORMAL:
        die("%s settings differ, want %s" % (mode, w))
    expect_tree(img, [(0, "背景", "layer", "normal", 100, True, False)])
    if pixels(lay) != src:
        die("pixels changed")
ok("OK")
