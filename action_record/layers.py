# Which layer a recorded step used. No GIMP import: callers pass live layer objects.
# A path of names (plus an index when several siblings share a name) still finds a
# layer inside a group after a restart, including one that is hidden.

GENERATED_GROUPS = ("Frequency Separation", "Dodge & Burn")
HELPER_LAYER_NAMES = ("加深减淡 D&B",)
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
    """True for the dodge-and-burn paint layer and anything inside the groups
    frequency separation or dodge-and-burn create."""
    try:
        if layer.get_name() in HELPER_LAYER_NAMES:
            return True
        if layer.is_group() and layer.get_name() in GENERATED_GROUPS:
            return True
    except Exception:
        return False
    return any(name in GENERATED_GROUPS for name in _ancestor_names(layer))


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
    return {"name": layer.get_name(), "path": chain}


def _photo_source(image, active):
    """The pixel layer frequency separation hid: the non-group sibling just
    under that group. Not a color or a coordinate, so it is not this photo."""
    group = None
    parent = _parent(active)
    while parent is not None:
        if parent.get_name() == "Frequency Separation":
            group = parent
            break
        parent = _parent(parent)
    if group is not None:
        siblings = _siblings(image, group)
        try:
            index = siblings.index(group)
        except ValueError:
            index = -1
        if 0 <= index + 1 < len(siblings):
            sibling = siblings[index + 1]
            if not sibling.is_group() and not inside_generated(sibling):
                return sibling
    outside = []

    def walk(layers):
        for item in layers:
            if item.is_group():
                if item.get_name() not in GENERATED_GROUPS:
                    walk(list(item.get_children()))
            elif not inside_generated(item):
                outside.append(item)

    walk(list(image.get_layers()))
    if len(outside) == 1:
        return outside[0]
    hidden = [item for item in outside if not item.get_visible()]
    if len(hidden) == 1:
        return hidden[0]
    return outside[0] if outside else None


def record_target(image, layer, procedure):
    target = layer
    if procedure == SUBJECT_PROC and inside_generated(layer):
        source = _photo_source(image, layer)
        if source is not None:
            target = source
    return layer_ref(image, target)


def find_layer(image, ref):
    path = (ref or {}).get("path") or []
    if not path:
        return None
    layers = list(image.get_layers())
    found = None
    for part in path:
        name = part.get("name")
        index = int(part.get("index") or 0)
        matches = [item for item in layers if item.get_name() == name]
        if index < 0 or index >= len(matches):
            return None
        found = matches[index]
        if part is not path[-1]:
            if not found.is_group():
                return None
            layers = list(found.get_children())
    return found


def layer_label(ref):
    path = (ref or {}).get("path") or []
    if path:
        return " / ".join(part.get("name") or "?" for part in path)
    return (ref or {}).get("name") or "未知图层"
