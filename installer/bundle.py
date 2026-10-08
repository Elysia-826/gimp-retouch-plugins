#!/usr/bin/env python3
"""gimp-retouch-plugins selectable installer (phase 1). Invoked via ../install.sh.
Data: ../components.txt, ../bundle.lock, ../presets/*.txt. No component names are hard-coded here."""
import argparse, datetime, glob, hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile, zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
STATE = os.environ.get("GIMP_BUNDLE_STATE") or os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")), "gimp-retouch-bundle")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "gimp-retouch-bundle")
RECORD = os.path.join(STATE, "installed.json")
LAST = os.path.join(STATE, "last.toml")
EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_USAGE = 0, 1, 2, 64
KINDS = {"ours", "deb", "apt", "git-meson", "zip", "rawfile", "flatpak", "icu-wrapper", "config"}
SUDO_KINDS = {"deb", "apt", "git-meson"}
GIMPS = ["3.0", "3.2"]
JSON_OUT = False
BACKUP_DIR = os.path.join(HOME, "gimp-bundle-backups")
PRESERVE_DEFAULT = "language,theme,icon-theme,prefer-dark-theme,theme-color-scheme,font-relative-size,override-theme-icon-size,custom-icon-size,icon-size,import-raw-plug-in"

class Usage(Exception):
    pass

def say(*a):
    print(*a, file=sys.stderr if JSON_OUT else sys.stdout, flush=True)

def warn(msg):
    print("WARN: " + msg, file=sys.stderr, flush=True)

# ---------------------------------------------------------------- catalog
def _rows(path, ncols):
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = [c.strip() for c in line.rstrip("\n").split("|")]
            if len(cols) != ncols:
                raise ValueError("%s:%d: expected %d columns, got %d" % (os.path.basename(path), ln, ncols, len(cols)))
            out.append((ln, cols))
    return out

def _list(s):
    return [] if s in ("", "-") else [x.strip() for x in s.split(",") if x.strip()]

def load_catalog():
    comps, order = {}, []
    for ln, c in _rows(os.path.join(REPO, "components.txt"), 7):
        comps[c[0]] = dict(id=c[0], category=c[1], requires=_list(c[2]), recommends=_list(c[3]),
                           os=_list(c[4]), overwrites=c[5] == "y", desc=c[6], line=ln)
        order.append(c[0])
    builds = []
    for ln, c in _rows(os.path.join(REPO, "bundle.lock"), 12):
        params = {}
        for kv in c[10].split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1); params[k.strip()] = v.strip()
        builds.append(dict(build=c[0], gimp=_list(c[1]), version=c[2], kind=c[3], source=c[4], pin=c[5],
                           license=c[6], component=c[7], dest=c[8], verify=c[9].split() if c[9] not in ("", "-") else [],
                           params=params, notes=c[11], line=ln))
    presets = {}
    for p in sorted(glob.glob(os.path.join(REPO, "presets", "*.txt"))):
        with open(p, encoding="utf-8") as fh:
            presets[os.path.splitext(os.path.basename(p))[0]] = [l.split("#")[0].strip() for l in fh if l.split("#")[0].strip()]
    return comps, order, builds, presets

def check_catalog(comps, builds, presets):
    errs = []
    ids = set(comps)
    for c in comps.values():
        if c["category"] not in ("ours", "third-party", "community"):
            errs.append("components.txt:%d %s: bad category %s" % (c["line"], c["id"], c["category"]))
        for r in c["requires"] + c["recommends"]:
            if r not in ids:
                errs.append("components.txt:%d %s: unknown requires/recommends id %s" % (c["line"], c["id"], r))
        if not c["desc"]:
            errs.append("components.txt:%d %s: empty description" % (c["line"], c["id"]))
        if "linux" in c["os"] and not any(b["component"] == c["id"] for b in builds):   # Windows-only ids live in install.ps1
            errs.append("components.txt:%d %s: no build in bundle.lock" % (c["line"], c["id"]))
    seen = set()
    for b in builds:
        w = "bundle.lock:%d %s" % (b["line"], b["build"])
        if b["build"] in seen: errs.append(w + ": duplicate build id")
        seen.add(b["build"])
        if b["component"] not in ids: errs.append(w + ": component '%s' not in components.txt" % b["component"])
        if b["kind"] not in KINDS: errs.append(w + ": unknown kind " + b["kind"])
        if not b["license"] or b["license"] == "-": errs.append(w + ": license empty")
        if b["kind"] in ("ours", "icu-wrapper"):
            if b["pin"] != "-": errs.append(w + ": pin should be '-' for kind " + b["kind"])
        elif not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", b["pin"]):
            errs.append(w + ": pin is not a sha256/commit")
        for g in b["gimp"]:
            if g not in GIMPS + ["host"]: errs.append(w + ": bad gimp " + g)
        for t in b["verify"]:
            if not re.fullmatch(r"(proc|def|cmd):\S+|cmdver:\S+=\S*", t): errs.append(w + ": bad verify token " + t)
        if b["kind"] == "ours":
            for f in b["source"].split():
                if not os.path.isfile(os.path.join(REPO, f)): errs.append(w + ": repo file missing " + f)
        if b["kind"] not in ("flatpak",) and b["dest"] in ("", "-"): errs.append(w + ": dest missing")
    for n, lst in presets.items():
        for i in lst:
            if i not in ids: errs.append("presets/%s.txt: unknown component %s" % (n, i))
    return errs

# ---------------------------------------------------------------- helpers
def sh(cmd, check=False, capture=True, env=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=capture, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (r.returncode, cmd if isinstance(cmd, str) else " ".join(cmd),
                                                             (r.stderr or "")[-800:]))
    return r

def sha_file(p):
    try:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for blk in iter(lambda: fh.read(1 << 20), b""):
                h.update(blk)
        return h.hexdigest()
    except OSError:
        return None

def tpl(s, gimp):
    prof = os.path.join(HOME, ".config/GIMP", gimp) if gimp in GIMPS else ""
    return (s.replace("{plugdir}", os.path.join(prof, "plug-ins")).replace("{profile}", prof)
             .replace("{home}", HOME).replace("{gimp}", gimp))

def detect_gimps():
    found = {}
    if shutil.which("gimp-console-3.0"):
        found["3.0"] = "apt"
    if shutil.which("flatpak") and sh(["flatpak", "info", "--user", "org.gimp.GIMP"]).returncode == 0:
        found["3.2"] = "flatpak"
    return found

def gimp_running():
    out = []
    for n in ("gimp-3.0", "gimp", "gimp-3.2"):
        r = sh(["pgrep", "-a", "-x", n])
        out += [l for l in r.stdout.splitlines() if l.strip()]
    if shutil.which("flatpak"):
        r = sh(["flatpak", "ps"])
        out += [l for l in r.stdout.splitlines() if "org.gimp.GIMP" in l]
    return out

def fp_commit(ref):
    r = sh(["flatpak", "info", "--user", "-c", ref])
    return r.stdout.strip() if r.returncode == 0 else None

def fp_ref(b):
    return b["source"].split(":", 1)[1]

def dpkg_ver(pkg):
    r = sh(["dpkg-query", "-W", "-f=${Version}", pkg])
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None

def cmd_version(cmd):
    r = subprocess.run(cmd + " --version", shell=True, capture_output=True, text=True)  # some CLIs exit non-zero
    m = re.search(r"version\s+([0-9][0-9.]*)", (r.stdout or "") + (r.stderr or ""))
    return m.group(1) if m else None

def git_short():
    r = sh(["git", "-C", REPO, "rev-parse", "--short", "HEAD"])
    return r.stdout.strip() if r.returncode == 0 else "unknown"

# ---------------------------------------------------------------- per-kind check / install
def icu_wrapper_text(b):
    p = b["params"]
    return ("#!/bin/sh\n# Wrapper: links the GMic extension against ICU 77 copied from %s.\n"
            'HERE="$(dirname "$(readlink -f "$0")")"\n'
            'export LD_LIBRARY_PATH="$HERE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
            'exec %s "$@"\n') % (p["runtime"], p["target"])

def _strip_comments(t):
    return "\n".join(l for l in (t or "").splitlines() if not l.startswith("# "))

def runtime_libdir(b):
    r = sh(["flatpak", "info", "--user", "--show-location", b["params"]["runtime"]])
    return os.path.join(r.stdout.strip(), "files/lib/x86_64-linux-gnu") if r.returncode == 0 else None

def ours_targets(b, g):
    dest = tpl(b["dest"], g)
    srcs = [os.path.join(REPO, f) for f in b["source"].split()]
    if dest.endswith("/"):
        return [(s, os.path.join(dest, os.path.basename(s))) for s in srcs]
    return [(srcs[0], dest)]

def check(b, g, record):
    """-> (state, detail) state in ok | mismatch | absent | unknown"""
    k, p = b["kind"], b["params"]
    if k == "ours":
        t = ours_targets(b, g)
        have = [d for _, d in t if os.path.exists(d)]
        if not have: return "absent", ""
        return ("ok", "") if all(sha_file(s) == sha_file(d) for s, d in t) else ("mismatch", "files differ from repo")
    if k == "deb":
        v = dpkg_ver(p["pkg"])
        if v is None: return "absent", ""
        return ("ok", v) if v == b["version"] and os.path.exists(p.get("check", "/")) else ("mismatch", "dpkg %s=%s" % (p["pkg"], v))
    if k == "apt":
        vs = {}
        for spec in p["pkgs"].split():
            n, v = spec.split("=", 1); vs[n] = (dpkg_ver(n), v)
        if all(cur is None for cur, _ in vs.values()): return "absent", ""
        bad = ["%s=%s" % (n, cur) for n, (cur, want) in vs.items() if cur != want]
        return ("mismatch", " ".join(bad)) if bad else ("ok", b["version"])
    if k == "git-meson":
        exe, chk = tpl(p.get("exe") or "", g), tpl(p.get("check") or "", g)
        if not (exe and os.path.exists(exe)): return "absent", ""
        try:
            txt = open(chk, encoding="utf-8", errors="replace").read() if chk else ""
        except OSError:
            return "mismatch", "missing " + chk
        if p.get("reject") and p["reject"] in txt:
            return "mismatch", "installed build contains '%s' (wrong version)" % p["reject"]
        rec = rec_get(record, b["component"], g, b["build"])
        legacy = os.path.join(STATE, "%s-%s" % (g, b["build"]))          # state file of the old install.sh
        try:
            legacy_pin = open(legacy).read().strip()
        except OSError:
            legacy_pin = None
        if (rec and rec.get("pin") == b["pin"]) or legacy_pin == b["pin"]:
            return "ok", "pinned " + b["pin"][:7]
        return "ok", "compatible (pin not recorded)"
    if k == "zip":
        dest = tpl(b["dest"], g)
        if not os.path.isdir(dest): return "absent", ""
        f, _, text = p.get("vercheck", "::").partition("::")
        try:
            ok = text in open(os.path.join(dest, f), encoding="utf-8", errors="replace").read()
        except OSError:
            ok = False
        return ("ok", b["version"]) if ok else ("mismatch", "version marker not found")
    if k == "rawfile":
        d = tpl(b["dest"], g)
        if not os.path.exists(d): return "absent", ""
        return ("ok", b["version"]) if sha_file(d) == b["pin"] else ("mismatch", "sha256 differs")
    if k == "flatpak":
        c = fp_commit(fp_ref(b))
        if c is None: return "absent", ""
        return ("ok", c[:7]) if c == b["pin"] else ("mismatch", "commit " + c[:7])
    if k == "icu-wrapper":
        d = tpl(b["dest"], g); w = os.path.join(d, os.path.basename(d.rstrip("/")))
        if not os.path.exists(w): return "absent", ""
        try:
            cur = open(w).read()
        except OSError:
            cur = ""
        if _strip_comments(cur) != _strip_comments(icu_wrapper_text(b)) or not os.access(w, os.X_OK):
            return "mismatch", "wrapper differs"
        ld = runtime_libdir(b)
        for lib in p["libs"].split(","):
            if ld is None or sha_file(os.path.join(d, "lib", lib)) != sha_file(os.path.join(ld, lib)):
                return "mismatch", "ICU lib differs: " + lib
        return "ok", ""
    if k == "config":
        rec = rec_get(record, b["component"], g, b["build"])
        return ("ok", b["version"]) if rec and rec.get("pin") == b["pin"] else ("absent", "")
    return "unknown", "kind " + k

def fetch(url, sha, name):
    dest = os.path.join(CACHE, name)
    if sha_file(dest) == sha:
        return dest
    os.makedirs(CACHE, exist_ok=True)
    tmp = dest + ".part"
    sh(["curl", "-fsSL", "--retry", "3", "-o", tmp, url], check=True)
    got = sha_file(tmp)
    if got != sha:
        os.unlink(tmp)
        raise RuntimeError("sha256 mismatch for %s: got %s expected %s" % (url, got, sha))
    os.replace(tmp, dest)
    return dest

def config_srcdir_plan(b, g, archive=None):
    cands = []
    for c in b["params"].get("srcdir", ".config/GIMP/{gimp}").split(","):
        if tpl(c, g) not in cands: cands.append(tpl(c, g))
    if archive and os.path.exists(archive):
        with tarfile.open(archive) as tf:
            names = [n.split("/", 1)[1] if "/" in n else "" for n in tf.getnames()]
        for c in cands:
            if any(n == c or n.startswith(c + "/") for n in names):
                return c, cands
        return None, cands
    return None, cands

def describe(b, g, reinstall):
    """human readable action + whether it uses sudo"""
    k, p = b["kind"], b["params"]
    if k == "ours": return "copy %s -> %s" % (b["source"], tpl(b["dest"], g)), False
    if k == "deb": return "download %s (sha256 %s…) ; sudo apt-get install %s./deb" % (b["source"], b["pin"][:12], "--reinstall " if reinstall else ""), True
    if k == "apt": return "sudo apt-get install -y %s%s" % ("--reinstall " if reinstall else "", p["pkgs"]), True
    if k == "git-meson":
        if p.get("userdir") == "1":
            return "sudo apt-get install build deps (%s); git clone %s @%s; meson build; meson install to a staging dir; copy plug-ins -> %s" % (
                p.get("builddeps", ""), b["source"], b["pin"][:7], tpl(b["dest"], g)), True
        return "sudo apt-get install build deps (%s); git clone %s @%s; meson build; sudo meson install" % (p.get("builddeps", ""), b["source"], b["pin"][:7]), True
    if k == "zip": return "download %s ; unpack %s -> %s" % (b["source"], p.get("subdir", ""), tpl(b["dest"], g)), False
    if k == "rawfile": return "download %s -> %s" % (b["source"], tpl(b["dest"], g)), False
    if k == "flatpak": return "flatpak install --user flathub %s ; pin commit %s" % (fp_ref(b), b["pin"][:7]), False
    if k == "icu-wrapper": return "write wrapper %s + copy %s from %s" % (tpl(b["dest"], g), p["libs"], p["runtime"]), False
    if k == "config":
        arch = os.path.join(CACHE, "%s-%s.tar.gz" % (b["build"], b["version"]))
        chosen, cands = config_srcdir_plan(b, g, arch if sha_file(arch) == b["pin"] else None)
        if chosen:
            src = "archive dir %s%s" % (chosen, "" if chosen == cands[0] else " (%s not in archive -> fallback)" % cands[0])
        else:
            src = "first existing of: %s" % ", ".join(cands)
        return "download %s ; overlay %s -> %s (OVERWRITES SETTINGS)" % (b["source"], src, tpl(b["dest"], g)), False
    return "?", False

def install(b, g, reinstall, sudo_ok):
    """perform; returns record dict (method, files, ...)"""
    k, p = b["kind"], b["params"]
    if k in SUDO_KINDS and not sudo_ok:
        raise RuntimeError("needs sudo (no passwordless sudo with --yes, or sudo declined)")
    if k == "ours":
        files = []
        for s, d in ours_targets(b, g):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copyfile(s, d + ".new"); os.chmod(d + ".new", 0o644); os.replace(d + ".new", d)
            if os.path.basename(d) == p.get("exec"):
                os.chmod(d, 0o755)
            files.append(d)
        if b["gimp"] == ["host"] and os.path.dirname(files[0]) not in os.environ.get("PATH", "").split(":"):
            warn("%s is not on PATH" % os.path.dirname(files[0]))
        return dict(method="copy", files=files)
    if k == "deb":
        deb = fetch(b["source"], b["pin"], "%s_%s.deb" % (p["pkg"], b["version"]))
        sh(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"] + (["--reinstall"] if reinstall else []) + [deb], check=True)
        if dpkg_ver(p["pkg"]) != b["version"]:
            raise RuntimeError("dpkg %s version is %s after install" % (p["pkg"], dpkg_ver(p["pkg"])))
        return dict(method="deb", package=p["pkg"], deb_sha256=b["pin"])
    if k == "apt":
        pk = p["pkgs"].split()
        sh(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"] + (["--reinstall"] if reinstall else []) + pk, check=True)
        for t in b["verify"]:
            if t.startswith("cmdver:"):
                c, v = t[7:].split("=", 1)
                if v and cmd_version(c) != v: raise RuntimeError("%s --version != %s" % (c, v))
        return dict(method="apt", packages=pk)
    if k == "git-meson":
        src = os.path.join(CACHE, b["build"])
        sh(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"] + p.get("builddeps", "").split(), check=True)
        if not os.path.isdir(os.path.join(src, ".git")):
            sh(["git", "clone", "-q", b["source"], src], check=True)
        sh(["git", "-C", src, "fetch", "-q", "--tags", "origin"])
        sh(["git", "-C", src, "checkout", "-q", b["pin"]], check=True)
        if sh(["git", "-C", src, "rev-parse", "HEAD"]).stdout.strip() != b["pin"]:
            raise RuntimeError("checkout is not the pinned commit")
        shutil.rmtree(os.path.join(src, "build"), ignore_errors=True)
        sh(["meson", "setup", os.path.join(src, "build"), src] + p.get("meson", "").split(), check=True)
        sh(["ninja", "-C", os.path.join(src, "build")], check=True)
        if p.get("userdir") == "1":
            # User plug-ins dir: lives in $HOME, so reinstalling the GIMP
            # package (which recreates /usr/lib/.../plug-ins) does not drop it.
            stage = tempfile.mkdtemp(dir=CACHE)
            try:
                sh(["meson", "install", "-C", os.path.join(src, "build"), "--no-rebuild", "--destdir", stage], check=True)
                found = [r for r, ds, fs in os.walk(stage) if r.endswith(os.path.join("gimp", g, "plug-ins"))]
                if not found:
                    raise RuntimeError("meson install produced no gimp/%s/plug-ins" % g)
                dest = tpl(b["dest"], g).rstrip("/")
                os.makedirs(dest, exist_ok=True)
                files = []
                for name in sorted(os.listdir(found[0])):
                    s_ = os.path.join(found[0], name)
                    d_ = os.path.join(dest, name)
                    if not os.path.isdir(s_):
                        continue
                    shutil.rmtree(d_, ignore_errors=True)
                    shutil.copytree(s_, d_)
                    for root, dirs, fls in os.walk(d_):
                        for f in fls:
                            fp = os.path.join(root, f)
                            os.chmod(fp, 0o755)
                    files.append(d_ + "/")
            finally:
                shutil.rmtree(stage, ignore_errors=True)
            return dict(method="copy", files=files)
        sh(["sudo", "meson", "install", "-C", os.path.join(src, "build"), "--no-rebuild"], check=True)
        log = os.path.join(src, "build/meson-logs/install-log.txt")
        return dict(method="meson-install", install_log=log, files=_meson_files(log))
    if k == "zip":
        z = fetch(b["source"], b["pin"], "%s-%s.zip" % (b["build"], b["version"]))
        dest = tpl(b["dest"], g).rstrip("/")
        x = tempfile.mkdtemp(dir=CACHE)
        try:
            zipfile.ZipFile(z).extractall(x)
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(os.path.join(x, p.get("subdir", "")), dest)
        finally:
            shutil.rmtree(x, ignore_errors=True)
        for root, dirs, files in os.walk(dest):
            for n in dirs + files:
                fp = os.path.join(root, n); m = os.stat(fp).st_mode
                os.chmod(fp, m & ~0o022)
        if p.get("exec"): os.chmod(os.path.join(dest, p["exec"]), 0o755)
        if p.get("noexec"): os.chmod(os.path.join(dest, p["noexec"]), 0o644)
        return dict(method="zip", files=[dest + "/"])
    if k == "rawfile":
        f = fetch(b["source"], b["pin"], "%s-%s%s" % (b["build"], b["version"], os.path.splitext(b["source"])[1]))
        d = tpl(b["dest"], g); os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(f, d); os.chmod(d, 0o755)
        return dict(method="copy", files=[d])
    if k == "flatpak":
        ref = fp_ref(b)
        if sh(["flatpak", "remote-list", "--user"]).stdout.find("flathub") < 0:
            sh(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"], check=True)
        if fp_commit(ref) is None:
            sh(["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", ref], check=True)
        elif reinstall:
            sh(["flatpak", "install", "--user", "-y", "--noninteractive", "--reinstall", "flathub", ref], check=True)
        if fp_commit(ref) != b["pin"]:
            sh(["flatpak", "update", "--user", "-y", "--noninteractive", "--commit=" + b["pin"], ref], check=True)
        if fp_commit(ref) != b["pin"]:
            raise RuntimeError("commit %s != pinned" % (fp_commit(ref) or "?")[:7])
        return dict(method="flatpak", ref=ref, commit=b["pin"])
    if k == "icu-wrapper":
        d = tpl(b["dest"], g); w = os.path.join(d, os.path.basename(d.rstrip("/")))
        ld = runtime_libdir(b)
        if not ld: raise RuntimeError("runtime %s not installed" % p["runtime"])
        os.makedirs(os.path.join(d, "lib"), exist_ok=True)
        files = []
        for lib in p["libs"].split(","):
            shutil.copyfile(os.path.realpath(os.path.join(ld, lib)), os.path.join(d, "lib", lib)); files.append(os.path.join(d, "lib", lib))
        with open(w + ".new", "w") as fh:
            fh.write(icu_wrapper_text(b))
        os.chmod(w + ".new", 0o755); os.replace(w + ".new", w); files.append(w)
        return dict(method="generated", files=files)
    if k == "config":
        t = fetch(b["source"], b["pin"], "%s-%s.tar.gz" % (b["build"], b["version"]))
        chosen, cands = config_srcdir_plan(b, g, t)
        if not chosen: raise RuntimeError("none of %s in archive" % cands)
        say("    PhotoGIMP source dir for GIMP %s: %s" % (g, chosen))
        x = tempfile.mkdtemp(dir=CACHE)
        try:
            with tarfile.open(t) as tf:
                tf.extractall(x, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
            top = os.path.join(x, os.listdir(x)[0], chosen)
            dest = tpl(b["dest"], g)
            pre = profile_tar(g, "photogimp-pre-%s-%s.tgz" % (g, _stamp()))     # dedicated, never deduped
            say("    dedicated pre-PhotoGIMP backup: " + pre)
            rc = os.path.join(dest, "gimprc")
            old_rc = open(rc, encoding="utf-8", errors="replace").read() if os.path.exists(rc) else ""
            shutil.copytree(top, dest, dirs_exist_ok=True)
            files = [os.path.join(dest, n) for n in os.listdir(top)]
            keys = [k.strip() for k in p.get("preserve", PRESERVE_DEFAULT).split(",") if k.strip()]
            kept = preserve_gimprc(rc, old_rc, keys)
            if kept: say("    kept your gimprc settings: " + ", ".join(kept))
        finally:
            shutil.rmtree(x, ignore_errors=True)
        return dict(method="config-overlay", srcdir=chosen, files=files, pre_backup=pre, preserved=kept)
    raise RuntimeError("unknown kind " + k)

def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def profile_tar(g, name):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = os.path.join(BACKUP_DIR, name)
    with tarfile.open(out, "w:gz") as tf:
        tf.add(os.path.join(HOME, ".config/GIMP", g), arcname=os.path.join(".config/GIMP", g))
    return out

def preserve_gimprc(rc, old_text, keys):
    """After an overlay: put back the user's single-line settings for `keys`; drop overlay lines for keys the user never set."""
    if not os.path.exists(rc):
        return []
    new = open(rc, encoding="utf-8", errors="replace").read().split("\n")
    old = {}
    for line in old_text.split("\n"):
        m = re.match(r"^\(([\w-]+)\s.*\)\s*$", line)
        if m and m.group(1) in keys: old[m.group(1)] = line
    out, done = [], set()
    for line in new:
        m = re.match(r"^\(([\w-]+)[\s)]", line)
        if m and m.group(1) in keys:
            k = m.group(1)
            if k in old and k not in done: out.append(old[k]); done.add(k)
            continue                                   # overlay value dropped
        out.append(line)
    for k, line in old.items():
        if k not in done:
            out.insert(1 if out and out[0].startswith("#") else 0, line); done.add(k)
    with open(rc + ".new", "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    os.replace(rc + ".new", rc)
    return sorted(done)

def archive_gimps(archive):
    with tarfile.open(archive) as tf:
        names = tf.getnames()
    return sorted({m.group(1) for n in names for m in [re.match(r"^\.?/?\.config/GIMP/([0-9.]+)(/|$)", n)] if m})

def restore_profile(archive, g, pre_backup=True):
    """Replace ~/.config/GIMP/<g> with the archive's copy (exact). Current state is backed up first."""
    prof = os.path.join(HOME, ".config/GIMP", g)
    pre = backup(g, BACKUP_DIR) if (pre_backup and os.path.isdir(prof)) else None
    x = tempfile.mkdtemp(prefix=".restore-", dir=os.path.join(HOME, ".config/GIMP"))
    try:
        with tarfile.open(archive) as tf:
            prefix = os.path.join(".config/GIMP", g)
            norm = lambda n: re.sub(r"^(\./|/)+", "", n)
            mem = [m for m in tf.getmembers() if norm(m.name) == prefix or norm(m.name).startswith(prefix + "/")]
            if not mem: raise RuntimeError("archive has no %s" % prefix)
            kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tf.extractall(x, members=mem, **kw)
        src = os.path.join(x, ".config/GIMP", g)
        old = prof + ".restore-old"
        if os.path.exists(old): shutil.rmtree(old)
        if os.path.isdir(prof): os.rename(prof, old)
        try:
            os.rename(src, prof)
        except Exception:
            if os.path.isdir(old): os.rename(old, prof)
            raise
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(x, ignore_errors=True)
    return pre

def files_tar(paths, name):
    """Back up arbitrary (absolute) paths before removal; root-owned but readable files are fine."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    out = os.path.join(BACKUP_DIR, name)
    with tarfile.open(out, "w:gz") as tf:
        for p in paths:
            p = p.rstrip("/")
            if os.path.lexists(p): tf.add(p, arcname=p.lstrip("/"))
    return out

def _meson_files(log):
    try:
        return [l.strip() for l in open(log) if l.strip() and not l.startswith("#")]
    except OSError:
        return []

def adopt_info(b, g):
    k, p = b["kind"], b["params"]
    if k == "ours": return dict(method="copy", files=[d for _, d in ours_targets(b, g)])
    if k == "deb": return dict(method="deb", package=p["pkg"])
    if k == "apt": return dict(method="apt", packages=p["pkgs"].split())
    if k == "git-meson":
        if p.get("userdir") == "1":
            exe, chk = tpl(p.get("exe") or "", g), tpl(p.get("check") or "", g)
            return dict(method="copy", files=[os.path.dirname(x) + "/" for x in (exe, chk) if x])
        for log in (os.path.join(CACHE, b["build"], "build/meson-logs/install-log.txt"),
                    os.path.join(CACHE, "resynthesizer", "build/meson-logs/install-log.txt")):
            if os.path.exists(log):
                return dict(method="meson-install", install_log=log, files=_meson_files(log))
        return dict(method="meson-install", install_log=None, files=[p.get("exe")])
    if k == "zip": return dict(method="zip", files=[tpl(b["dest"], g).rstrip("/") + "/"])
    if k == "rawfile": return dict(method="copy", files=[tpl(b["dest"], g)])
    if k == "flatpak": return dict(method="flatpak", ref=fp_ref(b), commit=fp_commit(fp_ref(b)))
    if k == "icu-wrapper":
        d = tpl(b["dest"], g)
        return dict(method="generated", files=[os.path.join(d, "lib", l) for l in p["libs"].split(",")] + [os.path.join(d, os.path.basename(d.rstrip("/")))])
    return dict(method=k)

# ---------------------------------------------------------------- registration
def pluginrc(g):
    try:
        return open(os.path.join(HOME, ".config/GIMP", g, "pluginrc"), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""

def registered(b, g, rc_cache):
    if not b["verify"]:
        return None
    for t in b["verify"]:
        kind, _, val = t.partition(":")
        if kind in ("proc", "def"):
            rc = rc_cache.setdefault(g, pluginrc(g))
            if kind == "proc" and '(proc-def "%s"' % val not in rc: return False
            if kind == "def" and val + '"' not in rc: return False
        elif kind == "cmd":
            if not (shutil.which(val) or os.access(tpl(b["dest"], g), os.X_OK)): return False
        elif kind == "cmdver":
            c, v = val.split("=", 1)
            cv = cmd_version(c)
            if cv is None or (v and cv != v): return False
    return True

def refresh(g, log_dir):
    prof = os.path.join(HOME, ".config/GIMP", g)
    before = set(os.listdir(prof)) if os.path.isdir(prof) else set()
    tags = os.path.join(prof, "tags.xml"); tags_bak = None
    if os.path.exists(tags):
        tags_bak = tags + ".bundle-tmp"; shutil.copy2(tags, tags_bak)
    if g == "3.0":
        cmd = ["timeout", "300", "gimp-console-3.0", "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", "(gimp-quit 0)"]
    else:
        cmd = ["timeout", "300", "flatpak", "run", "--filesystem=" + REPO, "--command=gimp-console-3.2", "org.gimp.GIMP",
               "-i", "--batch-interpreter=plug-in-script-fu-eval", "-b", "(gimp-quit 0)"]
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "verify-%s.log" % g), "w") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    for f in ("colorrc", "extensionrc", "parasiterc", "templaterc", "unitrc"):
        if f not in before and os.path.exists(os.path.join(prof, f)):
            os.unlink(os.path.join(prof, f))
    if tags_bak:
        os.replace(tags_bak, tags)

# ---------------------------------------------------------------- record / backup
def rec_load():
    try:
        return json.load(open(RECORD))
    except (OSError, ValueError):
        return {"format": 1, "components": {}}

def rec_get(record, comp, g, build):
    return record.get("components", {}).get(comp, {}).get(g, {}).get("builds", {}).get(build)

def rec_put(record, comp, g, build, data):
    record.setdefault("components", {}).setdefault(comp, {}).setdefault(g, {"gimp": g, "builds": {}})["builds"][build] = data

def rec_save(record):
    os.makedirs(STATE, exist_ok=True)
    record["updated"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = RECORD + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, RECORD)

def backup(g, backup_dir):
    """content-deduped: identical profile content -> reuse previous archive"""
    prof = os.path.join(HOME, ".config/GIMP", g)
    if not os.path.isdir(prof):
        return None
    h = hashlib.sha256()
    for root, dirs, files in os.walk(prof):
        dirs.sort()
        for f in sorted(files):
            fp = os.path.join(root, f)
            if os.path.islink(fp) or not os.path.isfile(fp): continue
            h.update(os.path.relpath(fp, prof).encode() + b"\0" + (sha_file(fp) or "").encode() + b"\n")
    digest = h.hexdigest()
    os.makedirs(backup_dir, exist_ok=True)
    idx = os.path.join(backup_dir, "index.json")
    try:
        index = json.load(open(idx))
    except (OSError, ValueError):
        index = {}
    if digest in index and os.path.exists(index[digest]):
        return index[digest] + " (deduped: identical content)"
    out = os.path.join(backup_dir, "gimp-%s-config-%s.tgz" % (g, datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    with tarfile.open(out, "w:gz") as tf:
        tf.add(prof, arcname=os.path.join(".config/GIMP", g))
    index[digest] = out
    json.dump(index, open(idx, "w"), indent=1)
    return out

# ---------------------------------------------------------------- config / selection
def parse_toml(path):
    cfg = {}
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        raise Usage("cannot read config %s: %s" % (path, e))
    for n, line in enumerate(text.splitlines(), 1):
        s = line.split("#", 1)[0].strip()
        if not s: continue
        m = re.fullmatch(r'([A-Za-z_][\w-]*)\s*=\s*(.+)', s)
        if not m: raise Usage("%s:%d: cannot parse '%s'" % (path, n, line.strip()))
        k, v = m.group(1), m.group(2).strip()
        if re.fullmatch(r'"[^"]*"', v): cfg[k] = v[1:-1]
        elif v in ("true", "false"): cfg[k] = v == "true"
        elif re.fullmatch(r'\[\s*("[^"]*"\s*(,\s*"[^"]*"\s*)*,?)?\s*\]', v): cfg[k] = re.findall(r'"([^"]*)"', v)
        else: raise Usage("%s:%d: unsupported value '%s'" % (path, n, v))
    unknown = set(cfg) - {"gimp", "preset", "add", "remove", "photogimp"}
    if unknown: raise Usage("%s: unknown keys %s" % (path, ", ".join(sorted(unknown))))
    return cfg

def write_last(cfg, selected):
    os.makedirs(STATE, exist_ok=True)
    q = lambda l: "[" + ", ".join('"%s"' % x for x in l) + "]"
    with open(LAST, "w") as fh:
        fh.write("# effective selection of the last successful run (%s)\n" % datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        fh.write("# components: %s\n" % ", ".join(selected))
        fh.write('gimp = "%s"\npreset = "%s"\nadd = %s\nremove = %s\nphotogimp = %s\n' % (
            cfg["gimp"], cfg.get("preset") or "", q(cfg.get("add", [])), q(cfg.get("remove", [])), "true" if cfg.get("photogimp") else "false"))

# ---------------------------------------------------------------- main
def main(argv):
    global JSON_OUT
    ap = argparse.ArgumentParser(prog="install.sh", add_help=True,
        description="gimp-retouch-plugins selectable installer (Linux). Exit: 0 ok, 1 partial, 2 failed, 64 usage.")
    ap.error = lambda m: (_ for _ in ()).throw(Usage(m))
    ap.add_argument("--gimp", choices=["3.0", "3.2", "all"])
    ap.add_argument("--only", choices=["ours", "third-party", "community", "all"], default="all")
    ap.add_argument("--preset"); ap.add_argument("--config")
    ap.add_argument("--add", action="append", default=[], metavar="ID[,ID]")
    ap.add_argument("--remove", action="append", default=[], metavar="ID[,ID]")
    ap.add_argument("--with-raw", action="store_true", help="= --add raw2tiff")
    ap.add_argument("--with-photogimp", action="store_true", help="= --add photogimp")
    ap.add_argument("--reinstall", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true", help="no prompts (headless)")
    ap.add_argument("--json", action="store_true"); ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--backup-dir", default=os.path.join(HOME, "gimp-bundle-backups"))
    ap.add_argument("--menu", action="store_true", help="interactive menu (whiptail or numbered prompt) even when a selection is given; terminal only")
    ap.add_argument("--force", action="store_true", help="uninstall even if another installed component requires it")
    ap.add_argument("--purge", action="store_true", help="uninstall also removes system packages (deb/apt) and shared flatpak runtimes")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true"); mode.add_argument("--status", action="store_true")
    mode.add_argument("--check-catalog", action="store_true"); mode.add_argument("--list-backups", action="store_true")
    mode.add_argument("--uninstall", action="append", metavar="ID[,ID]")
    mode.add_argument("--restore", metavar="BACKUP.tgz")
    a = ap.parse_args(argv)
    JSON_OUT = a.json
    global BACKUP_DIR
    BACKUP_DIR = os.path.abspath(os.path.expanduser(a.backup_dir))

    comps, order, builds, presets = load_catalog()
    if a.check_catalog:
        errs = check_catalog(comps, builds, presets)
        for e in errs: print("ERROR " + e)
        print("catalog: %d components, %d builds, %d presets: %s" % (len(comps), len(builds), len(presets), "OK" if not errs else "%d problem(s)" % len(errs)))
        return EXIT_OK if not errs else EXIT_FAILED
    if a.list:
        print("%-17s %-12s %-12s %-13s %-14s %s" % ("COMPONENT", "CATEGORY", "REQUIRES", "RECOMMENDS", "GIMP", "说明"))
        for i in order:
            c = comps[i]
            gs = sorted({g for b in builds if b["component"] == i for g in b["gimp"]})
            print("%-17s %-12s %-12s %-13s %-14s %s%s" % (i, c["category"], ",".join(c["requires"]) or "-", ",".join(c["recommends"]) or "-",
                  ",".join(gs), c["desc"], "  [overwrites config]" if c["overwrites"] else ""))
        print("\nPRESETS")
        for n, l in presets.items():
            print("  %-8s %s" % (n, " ".join(l)))
        return EXIT_OK

    if (a.uninstall or a.restore) and (a.preset or a.add or a.remove or a.config or a.with_raw or a.with_photogimp or a.reinstall or a.menu):
        raise Usage("--uninstall/--restore cannot be combined with selection options (--preset/--add/--remove/--config/--with-*/--reinstall/--menu)")
    if a.menu and (a.list or a.status or a.check_catalog or a.list_backups):
        raise Usage("--menu is only for installing")
    if a.list_backups:
        return list_backups(a)
    present = detect_gimps()
    record = rec_load()
    if a.uninstall:
        return do_uninstall(a, comps, order, builds, present, record)
    if a.restore:
        return do_restore(a, present)
    if a.status:
        rc_cache = {}
        res = {"gimp": {g: {"present": g in present, "packaging": present.get(g)} for g in GIMPS}, "components": []}
        for i in order:
            entry = {"id": i, "category": comps[i]["category"], "targets": {}}
            for g in GIMPS + ["host"]:
                bs = [b for b in builds if b["component"] == i and g in b["gimp"]]
                if not bs or (g in GIMPS and g not in present): continue
                st = [(b, *check(b, g, record)) for b in bs]
                regs = [registered(b, g, rc_cache) for b in bs]
                entry["targets"][g] = {
                    "installed": all(s in ("ok", "mismatch") for _, s, _ in st),
                    "version": ", ".join("%s=%s" % (b["build"], b["version"]) for b in bs),
                    "registered": None if all(r is None for r in regs) else all(r is not False for r in regs),
                    "matches_lock": all(s == "ok" for _, s, _ in st),
                    "recorded": all(rec_get(record, i, g, b["build"]) is not None for b in bs),
                    "builds": {b["build"]: {"state": s, "detail": d} for b, s, d in st}}
            res["components"].append(entry)
        if a.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print("%-17s %-5s %-9s %-10s %-8s %s" % ("COMPONENT", "GIMP", "INSTALLED", "REGISTERED", "LOCK", "VERSION"))
            for e in res["components"]:
                for g, t in e["targets"].items():
                    print("%-17s %-5s %-9s %-10s %-8s %s" % (e["id"], g, t["installed"], t["registered"], t["matches_lock"], t["version"]))
        return EXIT_OK

    # ---- selection
    cfg = parse_toml(a.config) if a.config else {}
    split = lambda l: [x.strip() for v in l for x in v.split(",") if x.strip()]
    if a.preset: cfg["preset"] = a.preset
    cfg["add"] = cfg.get("add", []) + split(a.add) + (["raw2tiff"] if a.with_raw else [])
    cfg["remove"] = cfg.get("remove", []) + split(a.remove)
    if a.with_photogimp: cfg["photogimp"] = True
    if a.gimp: cfg["gimp"] = a.gimp
    if cfg.get("preset") and cfg["preset"] not in presets:
        raise Usage("unknown preset '%s' (have: %s)" % (cfg["preset"], ", ".join(presets)))
    for i in cfg["add"] + cfg["remove"]:
        if i not in comps: raise Usage("unknown component '%s' (see --list)" % i)
    if cfg.get("gimp") not in (None, "3.0", "3.2", "all"):
        raise Usage("gimp must be 3.0, 3.2 or all")
    menu_ui = None
    nothing = not cfg.get("preset") and not cfg["add"] and not cfg.get("photogimp")
    if a.menu or nothing:
        if a.yes or not sys.stdin.isatty() or not sys.stdout.isatty():
            if a.menu: raise Usage("--menu needs an interactive terminal and cannot be used with --yes")
            raise Usage("nothing selected: pass --preset minimal|portrait|full, --add ID[,ID] or --config FILE (see --list)")
        import menu
        last = {}
        if os.path.exists(LAST):
            try: last = parse_toml(LAST)
            except Usage: last = {}
        try:
            ui, path = menu.run_menu(cfg, last, comps, order, builds, presets, present, os.path.join(STATE, "menu-selection.toml"))
        except menu.Abort as e:
            raise Usage("menu: %s" % e)
        cfg = parse_toml(path)                 # execute exactly what was written
        cfg.setdefault("add", []); cfg.setdefault("remove", [])
        for i in cfg["add"] + cfg["remove"]:
            if i not in comps: raise Usage("unknown component '%s' in %s" % (i, path))
        menu_ui = (menu, ui, path)
    sel = list(presets.get(cfg.get("preset"), [])) if cfg.get("preset") else []
    sel += [i for i in cfg["add"] if i not in sel]
    if cfg.get("photogimp") and "photogimp" in comps and "photogimp" not in sel: sel.append("photogimp")
    sel = [i for i in sel if i not in cfg["remove"]]
    if a.only != "all":
        sel = [i for i in sel if comps[i]["category"] == a.only]
    notes = []
    changed = True
    while changed:
        changed = False
        for i in list(sel):
            for r in comps[i]["requires"]:
                if r not in sel:
                    sel.append(r); changed = True
                    notes.append("%s requires %s -> added automatically" % (i, r))
    sel = [i for i in order if i in sel]
    for i in sel:
        for r in comps[i]["recommends"]:
            if r not in sel: notes.append("hint: %s recommends %s (not selected; add with --add %s)" % (i, r, r))
    ov = [i for i in sel if "重叠" in comps[i]["desc"]]
    if len(ov) > 1: notes.append("note: %s overlap in function (both kept)" % " and ".join(ov))

    # ---- GIMP target
    tty = sys.stdin.isatty()
    if not a.dry_run and not a.yes and not tty:
        raise Usage("not a terminal: pass --yes for unattended installs (or --dry-run)")
    needs_gimp = any(g in GIMPS for i in sel for b in builds if b["component"] == i for g in b["gimp"])
    if cfg.get("gimp") is None and needs_gimp:
        if len(present) > 1:
            if a.yes or not tty:
                raise Usage("both GIMP 3.0 and 3.2 are installed: choose with --gimp 3.0|3.2|all (or gimp = \"...\" in --config)")
            ans = input("Both GIMP 3.0 (apt) and 3.2 (Flatpak) found. Install for [3.0/3.2/all]? ").strip()
            if ans not in ("3.0", "3.2", "all"): raise Usage("invalid answer '%s'" % ans)
            cfg["gimp"] = ans
        elif present:
            cfg["gimp"] = next(iter(present))
        else:
            raise Usage("no GIMP 3.0 (apt) or 3.2 (Flatpak --user) found")
    cfg.setdefault("gimp", "all")
    targets = GIMPS if cfg["gimp"] == "all" else [cfg["gimp"]]

    say("==> selection: %s  (preset=%s add=%s remove=%s only=%s)" % (" ".join(sel), cfg.get("preset") or "-", cfg["add"] or "-", cfg["remove"] or "-", a.only))
    say("==> GIMP targets: %s   (detected: %s)" % (" ".join(targets), ", ".join("%s/%s" % kv for kv in present.items()) or "none"))
    for n in notes: say("    " + n)
    run = gimp_running()
    if run: warn("GIMP is running (%s). Not killing it; restart GIMP afterwards to load plug-ins." % "; ".join(run))

    # ---- plan
    items = []          # dict(comp, gimp, build, state, detail, action, sudo, result, reason)
    for i in sel:
        c = comps[i]
        if "linux" not in c["os"]:
            items.append(dict(comp=i, gimp="-", build="-", result="skipped", reason="unsupported on linux")); continue
        host = [b for b in builds if b["component"] == i and "host" in b["gimp"]]
        tgts = [("host", host)] if host else []
        for g in targets:
            bs = [b for b in builds if b["component"] == i and g in b["gimp"]]
            if not bs and not host:
                items.append(dict(comp=i, gimp=g, build="-", result="skipped", reason="no build for GIMP %s" % g)); continue
            if g not in present and bs:
                items.append(dict(comp=i, gimp=g, build="-", result="skipped", reason="GIMP %s not installed" % g)); continue
            if bs: tgts.append((g, bs))
        for g, bs in tgts:
            for b in bs:
                st, det = check(b, g, record)
                it = dict(comp=i, gimp=g, build=b["build"], b=b, state=st, detail=det)
                if st == "ok" and not a.reinstall:
                    it.update(result="skipped", reason="already present (%s)" % (det or "matches lock"))
                else:
                    it["action"], it["sudo"] = describe(b, g, a.reinstall)
                    it["result"] = "planned"
                items.append(it)
    planned = [it for it in items if it["result"] == "planned"]
    sudo_steps = [it for it in planned if it.get("sudo")]
    say("==> plan (%d action(s), %d with sudo):" % (len(planned), len(sudo_steps)))
    for it in items:
        if it["result"] == "planned":
            say("    [%s] %-15s %-22s %s%s" % (it["gimp"], it["comp"], it["build"], "SUDO " if it.get("sudo") else "", it["action"]))
        else:
            say("    [%s] %-15s %-22s skip: %s" % (it["gimp"], it["comp"], it["build"], it["reason"]))
    if sudo_steps:
        say("==> sudo steps: " + "; ".join("%s/%s" % (it["comp"], it["build"]) for it in sudo_steps))

    rc_cache = {}
    if a.dry_run:
        for it in items:
            if "b" in it and it["result"] != "planned" and (it["gimp"] in present or it["gimp"] == "host"):
                it["registered"] = registered(it["b"], it["gimp"], rc_cache)
        return finish(a, items, cfg, sel, record, dry=True)

    # ---- confirm + sudo
    sudo_ok = True
    if planned and not a.yes:
        if menu_ui:
            mod, ui, path = menu_ui
            ok = mod.confirm(ui, path, len(planned), ["[%s] %s/%s: %s" % (it["gimp"], it["comp"], it["build"], "; ".join(x.strip() for x in re.split(r"\s*[;]\s*", it["action"]) if "sudo" in x)[:160] or it["action"][:120]) for it in sudo_steps], notes)
        else:
            q = "Proceed with %d action(s)%s? [y/N] " % (len(planned), " (sudo: %d)" % len(sudo_steps) if sudo_steps else "")
            ok = input(q).strip().lower() in ("y", "yes")
        if not ok:
            say("aborted"); return EXIT_USAGE
        if sudo_steps:
            sudo_ok = subprocess.run(["sudo", "-v"]).returncode == 0
    elif sudo_steps:
        sudo_ok = subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
        if not sudo_ok: warn("--yes without passwordless sudo: %d sudo step(s) will be skipped as failed" % len(sudo_steps))

    # ---- backup (per GIMP profile that will be touched; deduped)
    touched = sorted({it["gimp"] for it in planned if it["gimp"] in GIMPS})
    for g in touched:
        try:
            say("==> backup GIMP %s profile -> %s" % (g, backup(g, a.backup_dir)))
        except Exception as e:
            say("backup failed (%s); aborting" % e); return EXIT_FAILED

    # ---- adopt existing installs into the record
    for it in items:
        if it.get("state") == "ok" and it["result"] == "skipped" and rec_get(record, it["comp"], it["gimp"], it["build"]) is None:
            b = it["b"]
            rec_put(record, it["comp"], it["gimp"], it["build"], dict(adopted=True, version=b["version"],
                    pin=b["pin"] if b["pin"] != "-" else "repo@" + git_short(), when=_now(), **adopt_info(b, it["gimp"])))
            it["reason"] += ", adopted into record"

    # ---- execute
    failed_builds = set()
    for it in planned:
        b = it["b"]
        if any((it["comp"], it["gimp"]) == fb for fb in failed_builds):
            it.update(result="failed", reason="earlier build of this component failed"); continue
        say("==> [%s] %s/%s: %s" % (it["gimp"], it["comp"], it["build"], it["action"]))
        try:
            info = install(b, it["gimp"], a.reinstall, sudo_ok)
            st, det = check(b, it["gimp"], record)
            if st != "ok" and b["kind"] not in ("config", "git-meson"):
                raise RuntimeError("post-install check: %s %s" % (st, det))
            rec_put(record, it["comp"], it["gimp"], it["build"], dict(adopted=False, version=b["version"],
                    pin=b["pin"] if b["pin"] != "-" else "repo@" + git_short(), when=_now(), **info))
            it.update(result="installed", reason="")
        except Exception as e:
            it.update(result="failed", reason=str(e).strip().splitlines()[0][:300])
            failed_builds.add((it["comp"], it["gimp"]))
            say("    FAILED: " + it["reason"])
    rec_save(record)

    # ---- registration check
    if not a.no_verify:
        for g in targets:
            if g in present and any(it["gimp"] == g and it["result"] == "installed" for it in items):
                say("==> GIMP %s: headless registration refresh" % g)
                refresh(g, CACHE)
        for it in items:
            if "b" in it and (it["gimp"] in present or it["gimp"] == "host"):
                r = registered(it["b"], it["gimp"], rc_cache)
                it["registered"] = r
                if r is False and it["result"] != "failed":
                    it.update(result="failed", reason=(it.get("reason") or "") + " NOT REGISTERED")
    return finish(a, items, cfg, sel, record, dry=False)

# ---------------------------------------------------------------- uninstall / restore / backups
def _ask_gimp(what, options, a):
    if a.yes or not sys.stdin.isatty():
        raise Usage("%s exists for GIMP %s: choose with --gimp" % (what, " and ".join(options)))
    ans = input("%s exists for GIMP %s. Which? [%s/all] " % (what, " and ".join(options), "/".join(options))).strip()
    if ans == "all": return options
    if ans not in options: raise Usage("invalid answer '%s'" % ans)
    return [ans]

def _uninstall_plan(b, r, a):
    """-> (action, sudo, skip_reason)"""
    m = r.get("method")
    files = [f for f in (r.get("files") or []) if f]
    if m in ("copy", "generated", "zip"):
        return "back up + remove %d path(s): %s" % (len(files), " ".join(files)[:160]), False, None
    if m == "meson-install":
        if not files: return None, False, "no install log recorded; remove manually"
        return "back up + sudo rm %d file(s) from meson install log" % len(files), True, None
    if m in ("deb", "apt"):
        pk = [r["package"]] if m == "deb" else [x.split("=")[0] for x in r.get("packages", [])]
        if not a.purge: return None, False, "system package(s) %s kept (use --purge)" % " ".join(pk)
        return "sudo apt-get remove -y %s" % " ".join(pk), True, None
    if m == "flatpak":
        if b and b["params"].get("shared") and not a.purge:
            return None, False, "shared flatpak runtime %s kept (use --purge)" % r.get("ref")
        return "flatpak uninstall --user -y %s" % r.get("ref"), False, None
    if m == "config-overlay":
        if not r.get("pre_backup") or not os.path.exists(r["pre_backup"]):
            return None, False, "FAIL:no dedicated pre-install backup recorded"
        return "restore profile exactly from %s" % r["pre_backup"], False, None
    return None, False, "FAIL:unknown install method %s" % m

def _rm_paths(paths, b, g):
    for p in paths:
        p2 = p.rstrip("/")
        if os.path.isdir(p2) and not os.path.islink(p2): shutil.rmtree(p2)
        elif os.path.lexists(p2): os.remove(p2)
    if b and b["dest"].endswith("/"):
        d = tpl(b["dest"], g).rstrip("/")
        if os.path.isdir(d):
            for root, dirs, files in os.walk(d, topdown=False):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True); continue
                try: os.rmdir(root)
                except OSError: pass

def do_uninstall(a, comps, order, builds, present, record):
    split = lambda l: [x.strip() for v in l for x in v.split(",") if x.strip()]
    ids = split(a.uninstall)
    for i in ids:
        if i not in comps: raise Usage("unknown component '%s' (see --list)" % i)
    tty = sys.stdin.isatty()
    if not a.dry_run and not a.yes and not tty:
        raise Usage("not a terminal: pass --yes for unattended uninstalls (or --dry-run)")
    rec = record.get("components", {})
    bmap = {b["build"]: b for b in builds}
    lock_order = [b["build"] for b in builds]
    items, notes = [], []
    for cid in ids:
        recorded = list(rec.get(cid, {}))
        if not recorded:
            items.append(dict(comp=cid, gimp="-", build="-", result="skipped", reason="not in install record (nothing to remove)")); continue
        gs = [g for g in recorded if g in GIMPS]; hosts = [g for g in recorded if g == "host"]
        if a.gimp:
            want = GIMPS if a.gimp == "all" else [a.gimp]
            targets = [g for g in gs if g in want] + hosts
        else:
            targets = (gs if len(gs) < 2 else _ask_gimp(cid, gs, a)) + hosts
        if not targets:
            items.append(dict(comp=cid, gimp=a.gimp, build="-", result="skipped", reason="not recorded for GIMP %s" % a.gimp)); continue
        for g in targets:
            same = lambda x: g == "host" or "host" in rec[x] or g in rec[x]
            blockers = [x for x in rec if x not in ids and cid in comps.get(x, {}).get("requires", []) and same(x)]
            if blockers and not a.force:
                items.append(dict(comp=cid, gimp=g, build="-", result="failed", reason="blocked: required by installed %s (use --force)" % ", ".join(blockers))); continue
            if blockers: notes.append("forced: %s still requires %s" % (", ".join(blockers), cid))
            for x in rec:
                if x not in ids and cid in comps.get(x, {}).get("recommends", []) and same(x):
                    notes.append("[%s] warning: installed %s recommends %s; that part of its workflow will be unavailable (%s)"
                                 % (g, x, cid, comps[cid]["desc"]))
            bl = rec[cid][g]["builds"]
            for bid in sorted(bl, key=lambda k: -lock_order.index(k) if k in lock_order else 0):
                r = bl[bid]; b = bmap.get(bid)
                act, sudo, skip = _uninstall_plan(b, r, a)
                it = dict(comp=cid, gimp=g, build=bid, r=r, b=b, sudo=sudo)
                if skip and skip.startswith("FAIL:"): it.update(result="failed", reason=skip[5:])
                elif skip: it.update(result="skipped", reason=skip)
                else: it.update(result="planned", action=act)
                items.append(it)
    planned = [i for i in items if i["result"] == "planned"]
    sudo_steps = [i for i in planned if i.get("sudo")]
    say("==> uninstall plan (%d action(s), %d with sudo):" % (len(planned), len(sudo_steps)))
    for it in items:
        say("    [%s] %-15s %-22s %s%s" % (it["gimp"], it["comp"], it["build"], "SUDO " if it.get("sudo") and it["result"] == "planned" else "",
                                         it.get("action") if it["result"] == "planned" else "%s: %s" % (it["result"], it["reason"])))
    for n in notes: say("    " + n)
    if sudo_steps: say("==> sudo steps: " + "; ".join("%s/%s" % (i["comp"], i["build"]) for i in sudo_steps))
    clean = lambda: [{k: v for k, v in i.items() if k not in ("b", "r")} for i in items]
    if a.dry_run:
        items[:] = clean()
        return finish(a, items, {"gimp": a.gimp}, ids, record, dry=True, extra="removed")
    sudo_ok = True
    if planned and not a.yes:
        if input("Remove %d item(s)%s? [y/N] " % (len(planned), " (sudo: %d)" % len(sudo_steps) if sudo_steps else "")).strip().lower() not in ("y", "yes"):
            say("aborted"); return EXIT_USAGE
        if sudo_steps: sudo_ok = subprocess.run(["sudo", "-v"]).returncode == 0
    elif sudo_steps:
        sudo_ok = subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
        if not sudo_ok: warn("--yes without passwordless sudo: %d sudo step(s) will fail" % len(sudo_steps))
    if gimp_running(): warn("GIMP is running; restart it after uninstalling (not killing it).")
    # one file backup per (component, target) before anything is removed
    groups = {}
    for it in planned:
        if it["r"].get("method") in ("copy", "generated", "zip", "meson-install"):
            groups.setdefault((it["comp"], it["gimp"]), []).extend(it["r"].get("files") or [])
    bk = {}
    for (cid, g), paths in groups.items():
        bk[(cid, g)] = files_tar(paths, "uninstall-%s-%s-%s.tgz" % (cid, g, _stamp()))
        say("==> backup of %s files (%s) -> %s" % (cid, g, bk[(cid, g)]))
    refresh_g = set()
    for it in planned:
        r, b, g, m = it["r"], it["b"], it["gimp"], it["r"].get("method")
        say("==> [%s] %s/%s: %s" % (g, it["comp"], it["build"], it["action"]))
        try:
            if it.get("sudo") and not sudo_ok: raise RuntimeError("needs sudo (no passwordless sudo with --yes, or sudo declined)")
            if m in ("copy", "generated", "zip"):
                _rm_paths(r.get("files") or [], b, g)
            elif m == "meson-install":
                files = [f for f in r["files"] if os.path.lexists(f)]
                if files: sh(["sudo", "rm", "-f"] + files, check=True)
                base = tpl(b["dest"], g).rstrip("/") if b else None
                for d in sorted({os.path.dirname(f) for f in r["files"]}, key=len, reverse=True):
                    if base and d.startswith(base + "/"): sh(["sudo", "rmdir", "--ignore-fail-on-non-empty", d])
            elif m in ("deb", "apt"):
                pk = [r["package"]] if m == "deb" else [x.split("=")[0] for x in r.get("packages", [])]
                sh(["sudo", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "remove", "-y"] + pk, check=True)
            elif m == "flatpak":
                sh(["flatpak", "uninstall", "--user", "-y", "--noninteractive", r["ref"]], check=True)
            elif m == "config-overlay":
                pre = restore_profile(r["pre_backup"], g, pre_backup=True)
                it["note"] = "state before restore saved: %s" % pre
            builds_rec = rec[it["comp"]][g]["builds"]
            builds_rec.pop(it["build"], None)
            if not builds_rec: rec[it["comp"]].pop(g, None)
            if not rec[it["comp"]]: rec.pop(it["comp"], None)
            it.update(result="removed", reason="backup: %s" % bk.get((it["comp"], g), it.get("note", "-")))
            if g in GIMPS and m != "config-overlay": refresh_g.add(g)
        except Exception as e:
            it.update(result="failed", reason=str(e).strip().splitlines()[0][:300]); say("    FAILED: " + it["reason"])
    if any(i["result"] == "removed" for i in items): rec_save(record)
    if not a.no_verify:
        rc_cache = {}
        for g in sorted(refresh_g):
            if g in present:
                say("==> GIMP %s: headless registration refresh" % g); refresh(g, CACHE)
        for it in items:
            if it["result"] == "removed" and it.get("b") and it["gimp"] in refresh_g:
                still = registered(it["b"], it["gimp"], rc_cache)
                it["registered"] = still
                if still: it["reason"] += " (WARNING: still registered)"
    items[:] = clean()
    return finish(a, items, {"gimp": a.gimp}, ids, record, dry=False, extra="removed")

def do_restore(a, present):
    path = os.path.abspath(os.path.expanduser(a.restore))
    if not os.path.isfile(path): raise Usage("backup not found: " + path)
    try:
        inside = archive_gimps(path)
    except (tarfile.TarError, OSError) as e:
        raise Usage("not a readable .tgz: %s (%s)" % (path, e))
    if not inside: raise Usage("%s contains no GIMP profile (.config/GIMP/<ver>)" % path)
    if a.gimp:
        targets = inside if a.gimp == "all" else [a.gimp]
        for g in targets:
            if g not in inside: raise Usage("%s has no profile for GIMP %s (has: %s)" % (path, g, ", ".join(inside)))
    else:
        targets = inside if len(inside) < 2 else _ask_gimp("backup " + os.path.basename(path), inside, a)
    tty = sys.stdin.isatty()
    if not a.dry_run and not a.yes and not tty:
        raise Usage("not a terminal: pass --yes (or --dry-run)")
    items = [dict(comp="profile", gimp=g, build=os.path.basename(path), result="planned",
                  action="back up current ~/.config/GIMP/%s, then replace it exactly with the archive copy" % g) for g in targets]
    for it in items: say("    [%s] %s" % (it["gimp"], it["action"]))
    if a.dry_run:
        return finish(a, items, {"gimp": a.gimp}, [], {}, dry=True, extra="restored")
    if not a.yes and input("Restore %d profile(s)? [y/N] " % len(items)).strip().lower() not in ("y", "yes"):
        say("aborted"); return EXIT_USAGE
    run = gimp_running()
    if run: warn("GIMP is running (%s); it may overwrite restored settings on exit. Not killing it." % "; ".join(run))
    for it in items:
        try:
            pre = restore_profile(path, it["gimp"], pre_backup=True)
            it.update(result="restored", reason="previous state: %s" % pre)
        except Exception as e:
            it.update(result="failed", reason=str(e)[:300])
    return finish(a, items, {"gimp": a.gimp}, [], {}, dry=False, extra="restored")

def list_backups(a):
    rows = []
    try:
        idx = json.load(open(os.path.join(BACKUP_DIR, "index.json")))
    except (OSError, ValueError):
        idx = {}
    deduped = {os.path.basename(v) for v in idx.values()}
    for p in sorted(glob.glob(os.path.join(BACKUP_DIR, "*.tgz")), key=os.path.getmtime):
        n = os.path.basename(p)
        kind = ("profile" if re.match(r"gimp-\d\.\d-config-", n) else "profile (old install.sh)" if n.startswith("gimp-config-")
                else "photogimp-pre-install" if n.startswith("photogimp-pre-") else "uninstalled-files" if n.startswith("uninstall-") else "other")
        try:
            gs = archive_gimps(p) if kind != "uninstalled-files" else []
        except (tarfile.TarError, OSError):
            gs = ["?"]
        rows.append(dict(path=p, kind=kind, gimp=gs, size=os.path.getsize(p), restorable=bool(gs) and gs != ["?"],
                         dedup_index=n in deduped,
                         mtime=datetime.datetime.fromtimestamp(os.path.getmtime(p)).astimezone().isoformat(timespec="seconds")))
    if a.json:
        print(json.dumps({"backup_dir": BACKUP_DIR, "backups": rows}, indent=2, ensure_ascii=False))
    else:
        print("backup dir: " + BACKUP_DIR)
        print("%-25s %-24s %-8s %8s  %s" % ("TIME", "KIND", "GIMP", "SIZE", "FILE"))
        for r in rows:
            print("%-25s %-24s %-8s %7.1fM  %s" % (r["mtime"], r["kind"], ",".join(r["gimp"]) or "-", r["size"] / 1e6, os.path.basename(r["path"])))
    return EXIT_OK

def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

def finish(a, items, cfg, sel, record, dry, extra=None):
    n_inst = sum(1 for i in items if i["result"] == "installed")
    n_skip = sum(1 for i in items if i["result"] == "skipped")
    n_fail = sum(1 for i in items if i["result"] == "failed")
    n_plan = sum(1 for i in items if i["result"] == "planned")
    n_extra = sum(1 for i in items if extra and i["result"] == extra)
    if n_fail == 0: status, code = "ok", EXIT_OK
    elif n_inst + n_skip + n_extra > 0: status, code = "partial", EXIT_PARTIAL
    else: status, code = "failed", EXIT_FAILED
    reg = lambda r: "-" if r is None else ("yes" if r else "NO")
    if a.json:
        counts = {"installed": n_inst, "skipped": n_skip, "failed": n_fail, "planned": n_plan}
        if extra: counts[extra] = n_extra
        print(json.dumps({"status": status, "dry_run": dry, "gimp": cfg.get("gimp"), "components": sel,
                          "counts": counts,
                          "items": [{k: v for k, v in i.items() if k != "b"} for i in items]}, indent=2, ensure_ascii=False))
    else:
        print("\n%-5s %-17s %-22s %-10s %-10s %s" % ("GIMP", "COMPONENT", "BUILD", "RESULT", "REGISTERED", "DETAIL"))
        print("-" * 100)
        for i in items:
            print("%-5s %-17s %-22s %-10s %-10s %s" % (i["gimp"], i["comp"], i["build"], i["result"], reg(i.get("registered")),
                                                       i.get("reason") or i.get("action", "")))
    if dry:
        print("DRY-RUN: %d action(s) would run; nothing was changed" % n_plan)
    elif status == "ok" and not extra:
        write_last(cfg, sel)
    print("STATUS=%s installed=%d skipped=%d failed=%d%s" % (status, n_inst, n_skip, n_fail, " %s=%d" % (extra, n_extra) if extra else ""))
    return code

if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        print("STATUS=failed installed=0 skipped=0 failed=0")
        sys.exit(EXIT_USAGE)
    except KeyboardInterrupt:
        sys.exit(EXIT_USAGE)
