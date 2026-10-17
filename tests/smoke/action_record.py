img, lay = portrait()
call("python-fu-action-play", img, [lay], action_name="自然修图准备")
expect_tree(img, [
    (0, "Frequency Separation", "group", "normal", 100, True, False),
    (1, "Dodge & Burn", "group", "pass-through", 100, True, False),
    (2, "观察层 Helper", "group", "pass-through", 100, False, False),
    (3, "对比增强 Contrast", "layer", "normal", 100, True, False),
    (3, "黑白 Luminosity", "layer", "hsl-color", 100, True, False),
    (2, "加深减淡 D&B", "layer", "softlight", 100, True, False),
    (1, "High (高频)", "layer", "grain-merge", 100, True, False),
    (1, "Low (低频)", "layer", "normal", 100, True, False),
    (0, "背景", "layer", "normal", 100, False, False)])
img, lay = portrait()
call("python-fu-action-record-start", img, [lay])
call("python-fu-dnb-setup", img, [lay], blend_mode="overlay")
call("python-fu-action-record-stop", img, [lay], action_name="smoke")
rec = tree(img)
img2, lay2 = portrait()
call("python-fu-action-play", img2, [lay2], action_name="smoke")
ok("recorded %d items" % len(rec))
if tree(img2) != rec or rec[4][3] != "overlay":
    show(img2)
    die("played action differs from the recording")
ok("OK")
