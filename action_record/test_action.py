# Headless checks for action recording. Run with gimp-console python-fu-eval.
# ACTION_PHASE=record then, in a new process, ACTION_PHASE=play.
import os
import shutil

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gio, Gegl

PHASE = os.environ.get("ACTION_PHASE", "record")
SRC = "/workspace/retouch-trial/before.jpg"
LOG = "/workspace/retouch-trial/action_replay_log.txt"
COPIES = {
    "prepare": "/tmp/action_replay_prepare.jpg",
    "record": "/tmp/action_replay_record.jpg",
    "play": "/tmp/action_replay_play.jpg",
    "other": "/tmp/action_replay_other.jpg",
}
ACTION = "只选主体"


def die(msg):
    print("ACTION_TEST FAIL " + msg, flush=True)
    raise SystemExit(1)


def log(line):
    print("ACTION_TEST " + line, flush=True)
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


def call(proc_name, image, layer, **kwargs):
    proc = Gimp.get_pdb().lookup_procedure(proc_name)
    if proc is None:
        die("not registered: " + proc_name)
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
    if not status_ok(res):
        detail = ""
        try:
            if res.length() > 1 and res.index(1) is not None:
                detail = " " + str(res.index(1))
        except Exception:
            pass
        die("%s status %s%s" % (proc_name, res.index(0), detail))
    return res


def layer_bytes(layer):
    w, h = layer.get_width(), layer.get_height()
    buf = layer.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(ext.x, ext.y, w, h)
    raw = buf.get(rect, 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)
    data = bytes(raw) if raw is not None else b""
    if len(data) != w * h * 3:
        raw4 = buf.get(rect, 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE)
        data4 = bytes(raw4) if raw4 is not None else b""
        if len(data4) != w * h * 4:
            die("cannot read layer %s" % layer.get_name())
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            rgb[i * 3:i * 3 + 3] = data4[i * 4:i * 4 + 3]
        data = bytes(rgb)
    return data


def tree(image):
    lines = []

    def walk(layers, depth):
        for layer in layers:
            lines.append("%s%s visible=%s" % ("  " * depth, layer.get_name(), int(bool(layer.get_visible()))))
            if layer.is_group():
                walk(layer.get_children(), depth + 1)

    walk(image.get_layers(), 0)
    return lines


def load(path):
    img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    if img is None:
        die("load failed " + path)
    return img


def channels(image):
    try:
        return [ch.get_name() for ch in (image.get_channels() or [])]
    except Exception:
        return []


def ensure_copies():
    if not os.path.isfile(SRC):
        die("source missing")
    for path in COPIES.values():
        shutil.copyfile(SRC, path)


def register():
    pdb = Gimp.get_pdb()
    for name in (
        "python-fu-action-record-start",
        "python-fu-action-record-stop",
        "python-fu-action-play",
    ):
        proc = pdb.lookup_procedure(name)
        if proc is None:
            die("missing procedure " + name)
        label = ""
        try:
            label = proc.get_menu_label() or ""
        except Exception:
            label = ""
        log("registered %s label=%s" % (name, label))


def phase_record():
    if os.environ.get("ACTION_KEEP_LOG") != "1":
        with open(LOG, "w", encoding="utf-8") as fh:
            fh.write("")
    log("version %s dir %s" % (Gimp.version(), Gimp.directory()))
    register()
    ensure_copies()
    img = load(COPIES["prepare"])
    layer = img.get_layers()[0]
    before = layer_bytes(layer)
    base_name = layer.get_name()
    call("python-fu-action-play", img, layer, **{"action-name": "自然修图准备"})
    after = layer_bytes(layer)
    names = tree(img)
    for line in names:
        log("prepare-layer " + line)
    needed = ["Frequency Separation", "Low (低频)", "High (高频)", "Dodge & Burn", "加深减淡 D&B", "观察层 Helper"]
    blob = "\n".join(names)
    for name in needed:
        if name not in blob:
            die("missing layer " + name)
    same = before == after
    log("prepare-base-layer %s pixels-unchanged %s" % (base_name, int(same)))
    if not same:
        die("base photo pixels changed")
    if layer.get_visible():
        die("original layer was not kept hidden under the frequency group")
    img2 = load(COPIES["record"])
    layer2 = img2.get_layers()[0]
    before2 = layer_bytes(layer2)
    call("python-fu-action-record-start", img2, layer2)
    call("python-fu-subject-select", img2, layer2, mode="subject", feather=2.0)
    call("python-fu-action-record-stop", img2, layer2, **{"action-name": ACTION})
    same2 = layer_bytes(layer2) == before2
    ch = channels(img2)
    log("record-channel %s pixels-unchanged %s" % (",".join(ch), int(same2)))
    if "主体选区" not in ch:
        die("subject channel missing after the recorded call")
    if not same2:
        die("subject select changed pixels")
    other = load(COPIES["other"])
    if "主体选区" in channels(other):
        die("an image that was not played already has the channel")
    log("record-other-image channels=%s" % ",".join(channels(other)))
    gdir = Gimp.directory()
    path = os.path.join(gdir, "action-record", "actions", ACTION + ".json")
    if not os.path.isfile(path):
        die("json not written: " + path)
    log("saved " + path)
    log("record-ok")


def phase_play():
    log("play-version %s dir %s" % (Gimp.version(), Gimp.directory()))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "retouch_action_store",
        "/workspace/retouch-plugins/action_record/store.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    loaded = mod.load_action(Gimp.directory(), ACTION)
    log("play-source %s" % loaded.get("path", "builtin"))
    ensure_copies()
    img = load(COPIES["play"])
    layer = img.get_layers()[0]
    before = layer_bytes(layer)
    if "主体选区" in channels(img):
        die("fresh copy already has a subject channel")
    call("python-fu-action-play", img, layer, **{"action-name": ACTION})
    ch = channels(img)
    same = layer_bytes(layer) == before
    log("play-channel %s pixels-unchanged %s" % (",".join(ch), int(same)))
    if "主体选区" not in ch:
        die("played action did not create 主体选区")
    if not same:
        die("playback changed pixels")
    other = load(COPIES["other"])
    other_layer = other.get_layers()[0]
    if "主体选区" in channels(other):
        die("second image was affected before playback")
    log("second-image-before-play channels=%s" % ",".join(channels(other)))
    call("python-fu-action-play", other, other_layer, **{"action-name": ACTION})
    if "主体选区" not in channels(other):
        die("playback on the second image did not create the channel")
    log("second-image-after-play channels=%s" % ",".join(channels(other)))
    log("ALL_OK")




SEQ_NAME = "三步对准图层"


def _soft(proc_name, image, layer, **kwargs):
    proc = Gimp.get_pdb().lookup_procedure(proc_name)
    if proc is None:
        return "missing"
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
    return "ok" if status_ok(res) else "fail %s" % res.index(0)


def _selected_name(image):
    try:
        layers = image.get_selected_layers()
    except Exception:
        return ""
    if not layers:
        return ""
    return layers[0].get_name()


def phase_seq():
    log("--- layer-target record %s dir %s ---" % (Gimp.version(), Gimp.directory()))
    ensure_copies()
    img = load(COPIES["record"])
    photo = img.get_layers()[0]
    before = layer_bytes(photo)
    call("python-fu-action-record-start", img, photo)
    call("python-fu-fsep-oneclick", img, photo, radius=8.0)
    current = _selected_name(img)
    log("after-fsep-selected %s" % current)
    sel = img.get_selected_layers()[0]
    call("python-fu-dnb-setup", img, sel)
    gray = img.get_selected_layers()[0]
    log("after-dnb-selected %s" % gray.get_name())
    # Subject select is invoked on the original photo, while the current layer
    # is the gray dodge-and-burn layer the previous step left behind.
    call("python-fu-subject-select", img, photo, mode="subject", feather=2.0)
    spot = _soft("python-fu-spot-heal", img, gray, x=8.0, y=8.0, radius=6.0, x2=-1.0, y2=-1.0, x3=-1.0, y3=-1.0)
    log("spot-heal-while-recording %s" % spot)
    call("python-fu-action-record-stop", img, photo, **{"action-name": SEQ_NAME})
    same = layer_bytes(photo) == before
    log("record-base-pixels-unchanged %s" % int(same))
    if not same:
        die("recording changed the base photo")
    path = os.path.join(Gimp.directory(), "action-record", "actions", SEQ_NAME + ".json")
    if not os.path.isfile(path):
        die("seq json missing " + path)
    import json
    data = json.load(open(path, encoding="utf-8"))
    steps = data.get("steps") or []
    log("seq-steps %d" % len(steps))
    if len(steps) != 3:
        die("expected 3 steps, got %d" % len(steps))
    procs = [s.get("procedure") for s in steps]
    log("seq-procs %s" % ",".join(procs))
    if "spot" in ",".join(procs) or "liquify" in ",".join(procs):
        die("a non-recordable step was stored")
    if steps[0].get("args", {}).get("radius") != 8 and steps[0].get("args", {}).get("radius") != 8.0:
        die("radius was not 8: %s" % steps[0].get("args"))
    for step in steps:
        label = " / ".join(p.get("name", "?") for p in (step.get("layer") or {}).get("path") or [])
        log("seq-step %s radius=%s layer=%s" % (step.get("procedure"), step.get("args"), label))
        if not (step.get("layer") or {}).get("path"):
            die("step missing target layer")
    sub = steps[2]
    if sub["args"].get("mode") != "subject":
        die("subject mode not stored")
    if "加深减淡" in " / ".join(p.get("name", "") for p in sub["layer"]["path"]):
        die("subject step stored the dodge-and-burn layer")
    if "Frequency Separation" in " / ".join(p.get("name", "") for p in sub["layer"]["path"]):
        die("subject step stored a frequency-separation layer")
    builtin = os.path.join(Gimp.directory(), "action-record", "actions", "自然修图准备.json")
    log("builtin-json-exists %s" % int(os.path.isfile(builtin)))
    if os.path.isfile(builtin):
        die("built-in action wrote a json file")
    log("seq-record-ok " + path)


def phase_seqplay():
    log("--- layer-target play %s dir %s ---" % (Gimp.version(), Gimp.directory()))
    ensure_copies()
    img = load(COPIES["play"])
    photo = img.get_layers()[0]
    before = layer_bytes(photo)
    if "主体选区" in channels(img):
        die("fresh image already has 主体选区")
    call("python-fu-action-play", img, photo, **{"action-name": SEQ_NAME})
    ch = channels(img)
    diff = 0 if layer_bytes(photo) == before else 1
    log("seq-play-channel %s pixel-diff %d" % (",".join(ch), diff))
    for line in tree(img):
        log("seq-play-layer " + line)
    if "主体选区" not in ch:
        die("playback did not create 主体选区")
    if diff != 0:
        die("playback changed base pixels")
    other = load(COPIES["other"])
    log("seq-second-image-channels %s" % ",".join(channels(other)))
    if "主体选区" in channels(other):
        die("second image has 主体选区 without playback")
    prep = load(COPIES["prepare"])
    base = prep.get_layers()[0]
    base_before = layer_bytes(base)
    call("python-fu-action-play", prep, base, **{"action-name": "自然修图准备"})
    for line in tree(prep):
        log("builtin-layer " + line)
    same = layer_bytes(base) == base_before
    log("builtin-base %s pixels-unchanged %s visible %s" % (base.get_name(), int(same), int(bool(base.get_visible()))))
    if not same:
        die("built-in changed base pixels")
    builtin = os.path.join(Gimp.directory(), "action-record", "actions", "自然修图准备.json")
    # also the other version's folder
    other_dir = os.path.join(os.path.dirname(Gimp.directory()), "3.0" if Gimp.directory().endswith("3.2") else "3.2", "action-record", "actions", "自然修图准备.json")
    exists = os.path.isfile(builtin) or os.path.isfile(other_dir)
    log("builtin-json-exists %s" % int(exists))
    if exists:
        die("built-in action created a json file")
    log("seq-play-ok")

if PHASE == "record":
    phase_record()
elif PHASE == "play":
    phase_play()
elif PHASE == "seq":
    phase_seq()
elif PHASE == "seqplay":
    phase_seqplay()
else:
    die("bad phase")
