import contextlib
import os
import subprocess

from gi.repository import Gimp, Gegl

HELPER_PY_FILE = "retouch-helper-python.txt"   # one line: full path of a python that has OpenCV
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW: no console flash


def _bytes(data):
    if data is None:
        return b""
    return bytes(data)


def _python_candidates():
    """Pythons that may have OpenCV. An explicit choice first, then the usual places."""
    out = []

    def add(p):
        if p and os.path.isfile(p) and p not in out:
            out.append(p)

    add(os.environ.get("RETOUCH_HELPER_PYTHON", ""))
    try:
        gd = Gimp.directory()
    except Exception:
        gd = ""
    if gd:
        # the installer writes this file into each GIMP profile (Windows)
        for d in [gd] + [os.path.join(os.path.dirname(gd), v) for v in ("3.2", "3.0")]:
            try:
                with open(os.path.join(d, HELPER_PY_FILE), encoding="utf-8-sig") as fh:
                    add(fh.readline().strip().strip('"'))
            except OSError:
                pass
    if os.name == "nt":
        import glob
        import shutil
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            add(os.path.join(local, "Programs", "retouch-python", "python.exe"))
            for p in sorted(glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe")), reverse=True):
                add(p)
        for name in ("python.exe", "python3.exe"):
            p = shutil.which(name)
            if p and "WindowsApps" not in p:   # skip the Microsoft Store stub
                add(p)
    else:
        for cand in ("/usr/bin/python3", "/run/host/usr/bin/python3"):
            add(cand)
    return out


def _helper_env(site=""):
    env = os.environ.copy()
    if os.name == "nt":
        # GIMP's own Python settings must not leak into a different Python
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
    if site:
        env["PYTHONPATH"] = site + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _cv2_launcher():
    """A python that can import cv2. Flatpak GIMP does not have it; the host one does."""
    homes = []
    if os.environ.get("HOME"):
        homes.append(os.environ["HOME"])
    homes.append(os.path.expanduser("~"))
    for home in list(homes):
        host = "/run/host" + home
        if os.path.isdir(host):
            homes.append(host)
    sites = [""]
    seen = set()
    for home in homes:
        local = os.path.join(home, ".local", "lib")
        if not os.path.isdir(local):
            continue
        for name in sorted(os.listdir(local)):
            sp = os.path.join(local, name, "site-packages")
            if os.path.isdir(sp) and sp not in seen:
                seen.add(sp)
                sites.append(sp)
    for py in _python_candidates():
        for sp in sites:
            env = _helper_env(sp)
            try:
                r = subprocess.run([py, "-c", "import cv2"], capture_output=True, env=env, timeout=60, **_NOWIN)
            except Exception:
                continue
            if r.returncode == 0:
                return py, env
    return None, None


def _export_ppm(layer, path):
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(ext.x, ext.y, w, h)
    raw = _bytes(buf.get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE))
    if len(raw) != w * h * 3:
        raw4 = _bytes(buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
        if len(raw4) != w * h * 4:
            raise RuntimeError("读不到图层像素 / Cannot read the layer")
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            rgb[i * 3:i * 3 + 3] = raw4[i * 4:i * 4 + 3]
        raw = bytes(rgb)
    with open(path, "wb") as f:
        f.write(("P6\n%d %d\n255\n" % (w, h)).encode("ascii"))
        f.write(raw)


@contextlib.contextmanager
def undo_group(image):
    started = image.undo_group_start()
    try:
        yield
    finally:
        if started:
            image.undo_group_end()
