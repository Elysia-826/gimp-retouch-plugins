# python3 tests/check_pluginrc.py <gimp_dir> <component>: the plug-in and its procedures from bundle.lock are in pluginrc.
import os, re, sys
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
g, comp = sys.argv[1], sys.argv[2]
rc = open(os.path.join(g, "pluginrc"), encoding="utf-8", errors="replace").read()
blocks = {m.group(1): m.group(2) for m in re.finditer(r'\(plug-in-def "([^"]+)"(.*?)(?=\n\(plug-in-def |\Z)', rc, re.S)}
bad = 0
for line in open(os.path.join(repo, "bundle.lock"), encoding="utf-8"):
    f = [c.strip() for c in line.split("|")]
    if line.startswith("#") or len(f) < 11 or f[3] != "ours" or f[7] != comp or "exec=" not in f[10]:
        continue
    ex = dict(kv.split("=", 1) for kv in f[10].split(";") if "=" in kv)["exec"]
    key = "${gimp_dir}/plug-ins/%s/%s" % (os.path.basename(f[8].rstrip("/")), ex)
    body = blocks.get(key)
    if body is None:
        print("REG FAIL %s: %s not in pluginrc" % (comp, key))
        bad += 1
        continue
    for tok in f[9].split():
        if tok.startswith("proc:"):
            p = tok[5:]
            ok = '(proc-def "%s"' % p in body
            print("REG %s %s %s" % ("ok" if ok else "FAIL", comp, p))
            bad += not ok
print("REG %s %s" % (comp, "OK" if not bad else "FAIL"))
sys.exit(1 if bad else 0)
