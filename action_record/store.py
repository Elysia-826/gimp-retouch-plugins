# Saved actions and the in-progress recording. No GIMP import: the other
# plug-ins load this file and pass in the config directory GIMP is using.
import json
import os

BUILTIN = {
    "自然修图准备": [
        {"procedure": "python-fu-fsep-oneclick", "args": {"radius": 0.0}},
        {"procedure": "python-fu-dnb-setup", "args": {
            "blend-mode": "soft-light",
            "contrast-boost": True,
            "place-on-top": False,
        }},
    ],
}

_BAD = set('/\\:*?"<>|')


def check_name(name):
    name = (name or "").strip()
    if not name or name in (".", "..") or len(name) > 80:
        raise ValueError("名称不能为空，也不能超过 80 个字 / Empty or too-long name")
    if any(c in _BAD or ord(c) < 32 for c in name):
        raise ValueError("名称里不能有路径符号 / Name must not contain path characters")
    if name in BUILTIN:
        raise ValueError("这个名字是内置动作，不能覆盖 / That name is a built-in action")
    return name


def session_path(gimp_dir):
    return os.path.join(gimp_dir, "action-record", "session.json")


def actions_dir(gimp_dir):
    return os.path.join(gimp_dir, "action-record", "actions")


def search_dirs(gimp_dir):
    """This GIMP's action folder first, then the other version's folder."""
    found = []

    def add(path):
        if path and path not in found:
            found.append(path)

    if gimp_dir:
        add(actions_dir(gimp_dir))
        parent = os.path.dirname(os.path.abspath(gimp_dir))
        for ver in ("3.0", "3.2"):
            add(os.path.join(parent, ver, "action-record", "actions"))
    home = os.path.expanduser("~")
    for base in (
        os.path.join(home, ".config", "GIMP"),
        os.path.join(home, ".var", "app", "org.gimp.GIMP", "config", "GIMP"),
    ):
        for ver in ("3.0", "3.2"):
            add(os.path.join(base, ver, "action-record", "actions"))
    return found


def _read(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("bad json")
    return data


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _clean_args(args):
    out = {}
    for key, value in (args or {}).items():
        if isinstance(value, bool):
            out[str(key)] = value
        elif isinstance(value, (int, float)):
            out[str(key)] = value
        else:
            out[str(key)] = str(value)
    return out


def note_step(gimp_dir, procedure, args, layer=None):
    """Append one step if a recording session is open. Never raises.

    layer is the path recorded by layers.record_target, or None for a step
    that should keep using whatever layer is current (the built-in action).
    """
    try:
        if not gimp_dir or not procedure:
            return
        path = session_path(gimp_dir)
        if not os.path.isfile(path):
            return
        data = _read(path)
        if not data.get("recording"):
            return
        steps = list(data.get("steps") or [])
        step = {"procedure": str(procedure), "args": _clean_args(args)}
        if isinstance(layer, dict) and layer.get("path"):
            step["layer"] = layer
        steps.append(step)
        data["steps"] = steps
        _write(path, data)
    except Exception:
        return


def start(gimp_dir):
    _write(session_path(gimp_dir), {"recording": True, "steps": []})


def stop(gimp_dir, name):
    name = check_name(name)
    path = session_path(gimp_dir)
    if not os.path.isfile(path):
        raise ValueError("没有在录制 / Not recording")
    data = _read(path)
    if not data.get("recording"):
        raise ValueError("没有在录制 / Not recording")
    steps = list(data.get("steps") or [])
    if not steps:
        raise ValueError("这一段里没有可保存的步骤 / Nothing was recorded")
    dest = os.path.join(actions_dir(gimp_dir), name + ".json")
    _write(dest, {"name": name, "version": 1, "steps": steps})
    try:
        os.remove(path)
    except OSError:
        pass
    return dest


def load_action(gimp_dir, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("要播放哪个动作 / Name the action to play")
    if name in BUILTIN:
        return {"name": name, "builtin": True, "steps": BUILTIN[name]}
    check_name(name)
    for folder in search_dirs(gimp_dir):
        path = os.path.join(folder, name + ".json")
        if not os.path.isfile(path):
            continue
        data = _read(path)
        if data.get("name") == name and isinstance(data.get("steps"), list):
            data["path"] = path
            return data
    raise ValueError("没有这个动作 / No saved action named " + name)
