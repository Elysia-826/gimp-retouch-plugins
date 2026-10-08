# Real menu flow, headless: every call uses whatever layer is active, as the
# menu does. Run with gimp-console python-fu-eval.
#   MENU_PHASE=record  MENU_TAG=<3.0|3.2>   record and save 菜单流程-<tag>
#   MENU_PHASE=play    MENU_PLAY=<names, comma-separated>   new process
import json
import os
import shutil

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gio, Gegl

SRC = "/workspace/retouch-trial/before.jpg"
LOG = "/workspace/retouch-trial/action_replay_log.txt"
PHASE = os.environ.get("MENU_PHASE", "record")
TAG = os.environ.get("MENU_TAG", "x")


def die(msg):
    log("FAIL " + msg)
    raise SystemExit(1)


def log(line):
    print("MENU_TEST " + line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def status_ok(res):
    st = res.index(0)
    try:
        if st == Gimp.PDBStatusType.SUCCESS:
            return True
    except Exception:
        pass
    try:
        return int(st) == int(Gimp.PDBStatusType.SUCCESS)
    except Exception:
        return False


def err_text(res):
    try:
        if res.length() > 1 and res.index(1) is not None:
            return str(res.index(1))
    except Exception:
        pass
    return ""


def active(image):
    layers = image.get_selected_layers()
    if not layers:
        die("no active layer")
    return layers[0]


def active_or_bottom(image):
    layers = image.get_selected_layers()
    return layers[0] if layers else image.get_layers()[-1]


def run_active(proc_name, image, **kwargs):
    """Call a procedure the way the menu does: on the active drawable."""
    proc = Gimp.get_pdb().lookup_procedure(proc_name)
    if proc is None:
        die("not registered " + proc_name)
    layer = active(image)
    cfg = proc.create_config()
    cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
    cfg.set_property("image", image)
    if hasattr(cfg, "set_core_object_array"):
        cfg.set_core_object_array("drawables", [layer])
    else:
        cfg.set_property("drawables", [layer])
    for key, value in kwargs.items():
        cfg.set_property(key, value)
    res = proc.run(cfg)
    return layer.get_name(), status_ok(res), err_text(res)


def copy(name):
    dst = "/tmp/menu_flow_%s_%s.jpg" % (TAG, name)
    shutil.copyfile(SRC, dst)
    return dst


def load(path):
    return Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))


def pixels(layer):
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    ext = buf.get_extent()
    raw = buf.get(Gegl.Rectangle.new(ext.x, ext.y, w, h), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)
    return bytes(raw) if raw is not None else b""


def channels(image):
    return [c.get_name() for c in (image.get_channels() or [])]


def bottom(image):
    return image.get_layers()[-1]


def tree(image):
    out = []

    def walk(items, depth):
        for item in items:
            out.append("  " * depth + item.get_name())
            if item.is_group():
                walk(item.get_children(), depth + 1)

    walk(image.get_layers(), 0)
    return out


def record():
    name = "菜单流程-" + TAG
    log("=== menu-flow record GIMP %s dir %s base-name-check ===" % (Gimp.version(), Gimp.directory()))
    img = load(copy("record"))
    base = bottom(img)
    log("base layer name %s" % base.get_name())
    before = pixels(base)
    on, ok, err = run_active("python-fu-action-record-start", img)
    if not ok:
        die("start " + err)
    on, ok, err = run_active("python-fu-fsep-oneclick", img, radius=8.0)
    log("step1 fsep on=%s ok=%d %s" % (on, int(ok), err))
    if not ok:
        die("fsep failed")
    on, ok, err = run_active("python-fu-dnb-setup", img)
    log("step2 dnb on=%s ok=%d %s" % (on, int(ok), err))
    if not ok:
        die("dnb failed")
    gray = active(img)
    on, ok, err = run_active("python-fu-subject-select", img, mode="subject", feather=2.0)
    log("step3 subject on=%s ok=%d err=%s" % (on, int(ok), err or "-"))
    if not ok:
        die("subject select failed during recording: " + err)
    ch = channels(img)
    log("record channels=%s" % ",".join(ch))
    if "主体选区" not in ch:
        die("no 主体选区 after recorded subject select")
    # Non-recordable steps while recording: desaturate the active gray layer
    # (no visible change, it is already gray) and a spot-heal call.
    # Subject select leaves its channel active, so go back to the gray layer.
    img.set_selected_layers([gray])
    try:
        gray.desaturate(Gimp.DesaturateMode.LUMINANCE)
        log("desaturate-while-recording on=%s" % gray.get_name())
    except Exception as exc:
        log("desaturate-while-recording error %s" % exc)
    on, ok, err = run_active("python-fu-spot-heal", img, x=8.0, y=8.0, radius=6.0)
    log("spot-heal-while-recording on=%s ok=%d" % (on, int(ok)))
    if not img.get_selected_layers():
        img.set_selected_layers([active_or_bottom(img)])
    on, ok, err = run_active("python-fu-action-record-stop", img, **{"action-name": name})
    if not ok:
        die("stop " + err)
    diff = 0 if pixels(base) == before else 1
    log("record base pixel diff %d" % diff)
    if diff:
        die("base pixels changed")
    path = os.path.join(Gimp.directory(), "action-record", "actions", name + ".json")
    data = json.load(open(path, encoding="utf-8"))
    steps = data["steps"]
    procs = [s["procedure"] for s in steps]
    log("json %s steps=%d procs=%s" % (path, len(steps), ",".join(procs)))
    if len(steps) != 3:
        die("expected 3 steps")
    if float(steps[0]["args"]["radius"]) != 8.0:
        die("radius not 8")
    for s in steps:
        ref = s.get("layer") or {}
        log("json-step %s args=%s layer=%s role=%s" % (
            s["procedure"], json.dumps(s["args"], ensure_ascii=False),
            " / ".join(x["name"] for x in ref.get("path", [])), ref.get("role", "-")))
    s3 = steps[2]["layer"]
    if len(s3["path"]) != 1 or s3["path"][0]["name"] != base.get_name() or s3.get("role") != "base":
        die("step 3 does not target the photo layer: %s" % s3)
    # Recording off: subject select straight on High (高频) of a fresh copy.
    img2 = load(copy("high"))
    run_active("python-fu-fsep-oneclick", img2, radius=8.0)
    on, ok, err = run_active("python-fu-subject-select", img2, mode="subject", feather=2.0)
    log("recording-off subject on=%s ok=%d channels=%s err=%s" % (on, int(ok), ",".join(channels(img2)), err or "-"))
    if not ok or "主体选区" not in channels(img2):
        die("subject select on High failed with recording off")
    log("record-ok " + name)


def play():
    log("=== menu-flow play GIMP %s dir %s ===" % (Gimp.version(), Gimp.directory()))
    jobs = []
    for name in [n for n in os.environ.get("MENU_PLAY", "").split(",") if n]:
        jobs.append((name, None))
        jobs.append((name, "背景"))
    for name, rename in jobs:
        img = load(copy("play"))
        base = bottom(img)
        if rename:
            # Same photo, but the base layer named the way a Chinese GIMP names it.
            base.set_name(rename)
        before = pixels(base)
        on, ok, err = run_active("python-fu-action-play", img, **{"action-name": name})
        diff = 0 if pixels(base) == before else 1
        log("play %s base=%s ok=%d channels=%s diff=%d err=%s" % (
            name, base.get_name(), int(ok), ",".join(channels(img)), diff, err or "-"))
        if not ok or "主体选区" not in channels(img) or diff:
            die("play failed " + name)
        other = load(copy("other"))
        if "主体选区" in channels(other):
            die("unplayed image has 主体选区")
        log("unplayed image channels=%s" % (",".join(channels(other)) or "-"))
    # Missing target: a saved action whose layer does not exist.
    gdir = Gimp.directory()
    miss = os.path.join(gdir, "action-record", "actions", "缺图层测试.json")
    with open(miss, "w", encoding="utf-8") as fh:
        json.dump({"name": "缺图层测试", "version": 1, "steps": [{
            "procedure": "python-fu-subject-select",
            "args": {"mode": "subject", "feather": 2.0},
            "layer": {"name": "不存在的图层", "path": [{"name": "不存在的组", "index": 0}, {"name": "不存在的图层", "index": 0}]},
        }]}, fh, ensure_ascii=False)
    img = load(copy("miss"))
    run_active("python-fu-fsep-oneclick", img, radius=8.0)
    tree_before = tree(img)
    pix_before = [pixels(bottom(img))]
    on, ok, err = run_active("python-fu-action-play", img, **{"action-name": "缺图层测试"})
    same = tree(img) == tree_before and [pixels(bottom(img))] == pix_before and "主体选区" not in channels(img)
    log("missing-layer ok=%d unchanged=%d err=%s" % (int(ok), int(same), err))
    os.remove(miss)
    if ok or not same:
        die("missing layer did not stop cleanly")
    builtin_hit = []
    for ver in ("3.0", "3.2"):
        p = os.path.join(os.path.dirname(gdir), ver, "action-record", "actions", "自然修图准备.json")
        if os.path.exists(p):
            builtin_hit.append(p)
    img = load(copy("builtin"))
    base = bottom(img)
    before = pixels(base)
    on, ok, err = run_active("python-fu-action-play", img, **{"action-name": "自然修图准备"})
    log("builtin ok=%d base diff=%d json-files=%s" % (int(ok), 0 if pixels(base) == before else 1, ",".join(builtin_hit) or "none"))
    for line in tree(img):
        log("builtin-tree " + line)
    if not ok or builtin_hit or pixels(base) != before:
        die("built-in action check")
    log("play-ok")


if PHASE == "record":
    record()
elif PHASE == "play":
    play()
else:
    die("bad phase")
