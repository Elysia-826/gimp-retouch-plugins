import contextlib
import os
import subprocess
import sys

from gi.repository import Gimp, Gegl, GLib

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


def soft_fail(what=None):
    """Call inside an except block: log the error and go on; RETOUCH_STRICT=1 re-raises it."""
    if os.environ.get("RETOUCH_STRICT") == "1":
        raise
    if what is None:
        f = sys._getframe(1)
        what = "%s:%d %s" % (os.path.basename(f.f_code.co_filename), f.f_lineno, f.f_code.co_name)
    try:
        print("[retouch] soft fail %s: %r" % (what, sys.exc_info()[1]), file=sys.stderr, flush=True)
    except Exception:
        pass


def add_menu_unless_panel(procedure):
    """Same button in 人像面板: no menu entry when the panel is installed next to this plug-in."""
    here = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(here, "..", "portrait_panel", "portrait_panel.py")):
        procedure.add_menu_path("<Image>/Filters/修图工具/")


GROUP_MESSAGE = "请选择一个普通图层，不要选图层组 / Select a normal layer, not a layer group"


def require_one_layer(procedure, drawables, message="请选择一个图层 / Select one layer", allow_group=False):
    """None when exactly one layer is selected, else the CALLING_ERROR to return."""
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(message))
    if drawables[0].is_group() and not allow_group:
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(GROUP_MESSAGE))
    return None


def set_drawables(cfg, drawables):
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", drawables)
    else:
        cfg.set_property("drawables", drawables)


def new_group(image, name):
    if hasattr(Gimp, "GroupLayer"):
        g = Gimp.GroupLayer.new(image, name)
    else:
        g = Gimp.Layer.group_new(image)
    g.set_name(name)
    return g


def note_recorded(procedure, args, image=None, layer=None):
    """If 动作录制 is recording, append this call. Missing recorder = do nothing."""
    try:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(os.path.join(here, "..", "action_record", "store.py"))
        if not os.path.isfile(path):
            return
        spec = importlib.util.spec_from_file_location("retouch_action_store", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        info = None
        if image is not None and layer is not None:
            lpath = os.path.normpath(os.path.join(here, "..", "action_record", "layers.py"))
            if os.path.isfile(lpath):
                lspec = importlib.util.spec_from_file_location("retouch_action_layers", lpath)
                lmod = importlib.util.module_from_spec(lspec)
                lspec.loader.exec_module(lmod)
                info = lmod.record_target(image, layer, procedure)
        mod.note_step(Gimp.directory() or "", procedure, args, info)
    except Exception:
        soft_fail("note_recorded")


@contextlib.contextmanager
def undo_group(image):
    started = image.undo_group_start()
    try:
        yield
    finally:
        if started:
            image.undo_group_end()
