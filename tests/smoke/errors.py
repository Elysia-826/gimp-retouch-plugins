ONE = "请选择一个图层 / Select one layer"
EXACT = "Select exactly one layer / 请选择一个图层"
GROUP = "请选择一个普通图层，不要选图层组 / Select a normal layer, not a layer group"
EXPECT = {   # (on a group, on nothing): (status, message or None)
    "python-fu-action-record-start": (("calling-error", GROUP), ("calling-error", ONE)),
    "python-fu-action-record-stop": (("execution-error", None), ("execution-error", None)),
    "python-fu-action-play": (("calling-error", GROUP), ("calling-error", ONE)),
    "python-fu-de-shine": (("calling-error", GROUP), ("calling-error", ONE)),
    "python-fu-dnb-flow": (("calling-error", GROUP), ("calling-error", ONE)),
    "python-fu-dnb-setup": (("success", None), ("calling-error", EXACT)),
    "python-fu-fsep-oneclick": (("calling-error", GROUP), ("calling-error", EXACT)),
    "python-fu-mesh-liquify": (("calling-error", GROUP), ("calling-error", EXACT)),
    "python-fu-mesh-liquify-face": (("calling-error", GROUP), ("calling-error", EXACT)),
    "python-fu-portrait-brush": (("success", None), ("success", None)),
    "python-fu-spot-heal": (("calling-error", GROUP), ("calling-error", ONE)),
    "python-fu-subject-select": (("calling-error", GROUP), ("calling-error", ONE)),
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
        if st != want[i][0]:
            die("%s on %s: %s, expected %s" % (name, what, st, want[i][0]))
        if want[i][1] is not None and msg != want[i][1]:
            die("%s on %s: message %r, expected %r" % (name, what, msg, want[i][1]))
        img.delete()
ok("errors OK")
