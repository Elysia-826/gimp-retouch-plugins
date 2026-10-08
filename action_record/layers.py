# Which layer a recorded step used. No GIMP import: callers pass live layer objects.
# A path of names (plus an index when several siblings share a name) still finds a
# layer inside a group after a restart, including one that is hidden.

GENERATED_GROUPS = ("Frequency Separation", "Dodge & Burn")
SUBJECT_PROC = "python-fu-subject-select"


def _parent(layer):
    try:
        return layer.get_parent()
    except Exception:
        return None


def _siblings(image, layer):
    parent = _parent(layer)
    if parent is not None:
        return list(parent.get_children())
    return list(image.get_layers())


def _ancestor_names(layer):
    names = []
    parent = _parent(layer)
    guard = 0
    while parent is not None and guard < 30:
        guard += 1
        try:
            names.append(parent.get_name())
        except Exception:
            break
        parent = _parent(parent)
    return names


def inside_generated(layer):
    """True for any layer inside, or equal to, a group that frequency
    separation or dodge-and-burn creates (names those plug-ins assign)."""
    cur = layer
    guard = 0
    while cur is not None and guard < 40:
        guard += 1
        try:
            if cur.is_group() and cur.get_name() in GENERATED_GROUPS:
                return True
        except Exception:
            return False
        cur = _parent(cur)
    return False


def layer_ref(image, layer):
    chain = []
    cur = layer
    guard = 0
    while cur is not None and guard < 30:
        guard += 1
        siblings = _siblings(image, cur)
        name = cur.get_name()
        same = [item for item in siblings if item.get_name() == name]
        try:
            index = same.index(cur)
        except ValueError:
            index = 0
        chain.append({"name": name, "index": index})
        cur = _parent(cur)
    chain.reverse()
    ref = {"name": layer.get_name(), "path": chain}
    if _is_base(image, layer):
        # The bottom photo layer is named by the locale (Background / 背景),
        # so playback finds it by this role when the name does not match.
        ref["role"] = "base"
    return ref


def _is_base(image, layer):
    try:
        if _parent(layer) is not None or layer.is_group():
            return False
        roots = list(image.get_layers())
        return bool(roots) and roots[-1] == layer
    except Exception:
        return False


def _base_layer(image):
    try:
        roots = list(image.get_layers())
    except Exception:
        return None
    if not roots:
        return None
    last = roots[-1]
    try:
        if last.is_group():
            return None
    except Exception:
        return None
    return last


def _photo_source(image, active):
    """Same rule as subject select: below the outermost generated group, the
    first sibling that is a plain pixel layer and not another generated group."""
    group = None
    cur = active
    guard = 0
    while cur is not None and guard < 40:
        guard += 1
        try:
            if cur.is_group() and cur.get_name() in GENERATED_GROUPS:
                group = cur
        except Exception:
            break
        cur = _parent(cur)
    if group is None:
        return None
    siblings = _siblings(image, group)
    try:
        index = siblings.index(group)
    except ValueError:
        return None
    for item in siblings[index + 1:]:
        try:
            if item.is_group():
                if item.get_name() in GENERATED_GROUPS:
                    continue
                return None
            return item
        except Exception:
            return None
    return None


def record_target(image, layer, procedure):
    target = layer
    if procedure == SUBJECT_PROC and inside_generated(layer):
        source = _photo_source(image, layer)
        if source is not None:
            target = source
    return layer_ref(image, target)


BASE_NAMES = ("Background", "背景")


def _find_by_path(image, path):
    layers = list(image.get_layers())
    found = None
    for pos, part in enumerate(path):
        name = part.get("name")
        index = int(part.get("index") or 0)
        matches = [item for item in layers if item.get_name() == name]
        if index < 0 or index >= len(matches):
            return None
        found = matches[index]
        if pos < len(path) - 1:
            if not found.is_group():
                return None
            layers = list(found.get_children())
    return found


def find_layer(image, ref):
    path = (ref or {}).get("path") or []
    if not path:
        return None
    found = _find_by_path(image, path)
    if found is not None:
        return found
    # The bottom photo layer: GIMP names it by locale (Background in one
    # setup, 背景 in another). Match it by role, never by guessing a layer.
    is_base = (ref or {}).get("role") == "base"
    if not is_base and len(path) == 1 and path[0].get("name") in BASE_NAMES:
        is_base = True
    if is_base:
        return _base_layer(image)
    return None


def layer_label(ref):
    path = (ref or {}).get("path") or []
    if path:
        return " / ".join(part.get("name") or "?" for part in path)
    return (ref or {}).get("name") or "未知图层"
