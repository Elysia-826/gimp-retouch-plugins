# python3 tests/lint.py: code rules for the plug-in sources (not tests).
import os, re, subprocess, sys
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = [f for f in subprocess.run(["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True).stdout.split()
         if not f.startswith(("tests/", "installer/")) and not os.path.basename(f).startswith("test_") and "/" in f]
shipped = set()
for row in open(os.path.join(repo, "bundle.lock"), encoding="utf-8"):
    cols = [c.strip() for c in row.split("|")]
    if len(cols) > 4 and cols[3] == "ours":
        shipped.update(p for p in cols[4].split() if p.endswith(".py"))
rules = [(r"undo_group_(start|end)\(", "use `with undo_group(image):` from retouch_common", lambda f: f != "retouch_common.py"),
         (r"/home/box|/workspace|/tmp/", "no machine paths in shipped code; use an env var or tempfile", lambda f: f in shipped)]
bad = 0
for f in files + sorted(shipped - set(files)):
    for n, line in enumerate(open(os.path.join(repo, f), encoding="utf-8"), 1):
        for pat, why, applies in rules:
            if applies(f) and re.search(pat, line):
                print("LINT %s:%d %s (%s)" % (f, n, line.strip(), why))
                bad += 1
print("LINT %s (%d files)" % ("OK" if not bad else "FAIL", len(files)))
sys.exit(1 if bad else 0)
