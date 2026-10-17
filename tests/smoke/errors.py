procs = []
for line in open("bundle.lock", encoding="utf-8"):
    f = [c.strip() for c in line.split("|")]
    if not line.startswith("#") and len(f) > 10 and f[7] == NAME and f[3] == "ours":
        procs += [t[5:] for t in f[9].split() if t.startswith("proc:")]
for name in procs:
    for what in ("group", "none"):
        img, lay = portrait(64, 64)
        grp = Gimp.GroupLayer.new(img, "组")
        img.insert_layer(grp, None, 0)
        proc = pdb.lookup_procedure(name)
        cfg = proc.create_config()
        cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        cfg.set_property("image", img)
        cfg.set_core_object_array("drawables", [grp] if what == "group" else [])
        st = proc.run(cfg).index(0)
        ok("%s on %s -> %s" % (name, what, st.value_nick))
        img.delete()
ok("errors OK")
