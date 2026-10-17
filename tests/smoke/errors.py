ONE = "请选择一个图层 / Select one layer"
EXACT = "Select exactly one layer / 请选择一个图层"
EXPECT = {
    "python-fu-action-record-start": ("success", "success"),
    "python-fu-action-record-stop": ("execution-error", "execution-error"),
    "python-fu-action-play": ("execution-error", "execution-error"),
    "python-fu-de-shine": ("execution-error", "calling-error", ONE),
    "python-fu-dnb-flow": ("execution-error", "calling-error", ONE),
    "python-fu-dnb-setup": ("success", "calling-error", EXACT),
    "python-fu-fsep-oneclick": ("execution-error", "calling-error", EXACT),
    "python-fu-mesh-liquify": ("execution-error", "calling-error", EXACT),
    "python-fu-mesh-liquify-face": ("execution-error", "calling-error", EXACT),
    "python-fu-portrait-brush": ("success", "success"),
    "python-fu-spot-heal": ("execution-error", "calling-error", ONE),
    "python-fu-subject-select": ("execution-error", "calling-error", ONE),
}
procs = []
for line in open("bundle.lock", encoding="utf-8"):
    f = [c.strip() for c in line.split("|")]
    if not line.startswith("#") and len(f) > 10 and f[7] == NAME and f[3] == "ours":
        procs += [t[5:] for t in f[9].split() if t.startswith("proc:")]
for name in procs:
    if name not in EXPECT:
        die("no expected error statuses for " + name)
    want = EXPECT[name]
    for i, what in enumerate(("group", "none")):
        img, lay = portrait(64, 64)
        grp = Gimp.GroupLayer.new(img, "组")
        img.insert_layer(grp, None, 0)
        proc = pdb.lookup_procedure(name)
        cfg = proc.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("image", img)
        cfg.set_core_object_array("drawables", [grp] if what == "group" else [])
        res = proc.run(cfg)
        st = res.index(0).value_nick
        msg = res.index(1) if st == "calling-error" and res.length() > 1 else ""
        ok("%s on %s -> %s %s" % (name, what, st, msg or ""))
        if st != want[i]:
            die("%s on %s: %s, expected %s" % (name, what, st, want[i]))
        if st == "calling-error" and len(want) > 2 and msg != want[2]:
            die("%s on %s: message %r, expected %r" % (name, what, msg, want[2]))
        img.delete()
ok("errors OK")
