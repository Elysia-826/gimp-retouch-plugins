# python3 tests/install_lock.py <gimp_dir>: copy our GIMP 3.0 plug-ins from bundle.lock into <gimp_dir>, like the installer does.
import os, shutil, sys
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
g = sys.argv[1]
bad = 0
for line in open(os.path.join(repo, "bundle.lock"), encoding="utf-8"):
    f = [c.strip() for c in line.split("|")]
    if line.startswith("#") or len(f) < 11 or f[3] != "ours" or "3.0" not in f[1].split(","):
        continue
    dest = f[8].replace("{plugdir}", os.path.join(g, "plug-ins")).replace("{profile}", g)
    ex = dict(kv.split("=", 1) for kv in f[10].split(";") if "=" in kv).get("exec")
    os.makedirs(dest, exist_ok=True)
    for s in f[4].split():
        src = os.path.join(repo, s)
        if not os.path.isfile(src):
            print("INSTALL MISSING %s %s" % (f[7], s), flush=True)
            bad += 1
            continue
        d = os.path.join(dest, os.path.basename(s))
        shutil.copyfile(src, d)
        os.chmod(d, 0o755 if os.path.basename(s) == ex else 0o644)
sys.exit(1 if bad else 0)
