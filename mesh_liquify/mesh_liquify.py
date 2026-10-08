#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 柔和网格液化 / Soft mesh liquify  (GIMP 3.0.x and 3.2.x)
# Displacement is accumulated on a mesh and re-rendered from a hidden copy of
# the original pixels (gegl:map-relative). No numpy: the mesh is pure Python,
# the pixel resample is GEGL. Face-aware controls are not in this version.
import array, base64, math, os, struct, sys, time, uuid, gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-mesh-liquify"
KEY = "mesh-liquify-key"       # shared id on the paint layer and the state group
ROLE = "mesh-liquify-role"     # "original" on the hidden snapshot layer
DISP = "mesh-liquify-disp"     # native-endian mesh blob on the paint layer
MODES = ("push", "bloat", "pinch", "restore", "twirl")
# max pixel move at full strength, as a fraction of the brush radius
AMOUNT = {"push": 0.50, "bloat": 0.45, "pinch": 0.45, "twirl": 0.55}

def _bytes(data):
    if data is None:
        return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return bytes(data)

def _pstr(item, name):
    p = item.get_parasite(name)
    if p is None:
        return None
    raw = _bytes(p.get_data())
    return raw.decode("utf-8", "replace") if raw else None

def _pset(item, name, text):
    blob = text.encode("utf-8")
    flags = int(Gimp.PARASITE_PERSISTENT) | int(Gimp.PARASITE_UNDOABLE)
    if not item.attach_parasite(Gimp.Parasite.new(name, flags, blob)):
        raise RuntimeError("attach parasite failed: " + name)

class Mesh:
    """Sparse float32 (dx, dy) in layer pixels. Positive dx moves content right."""
    def __init__(self, lw, lh):
        self.lw, self.lh = lw, lh
        self.x = self.y = self.bw = self.bh = 0
        self.a = array.array("f")

    def ensure(self, x0, y0, x1, y1):
        x0 = max(0, int(x0)); y0 = max(0, int(y0))
        x1 = min(self.lw, int(x1)); y1 = min(self.lh, int(y1))
        if x1 <= x0 or y1 <= y0:
            return False
        if self.bw == 0:
            self.x, self.y, self.bw, self.bh = x0, y0, x1 - x0, y1 - y0
            self.a = array.array("f", [0.0]) * (self.bw * self.bh * 2)
            return True
        nx0, ny0 = min(self.x, x0), min(self.y, y0)
        nx1, ny1 = max(self.x + self.bw, x1), max(self.y + self.bh, y1)
        if (nx0, ny0, nx1, ny1) == (self.x, self.y, self.x + self.bw, self.y + self.bh):
            return True
        nw, nh = nx1 - nx0, ny1 - ny0
        na = array.array("f", [0.0]) * (nw * nh * 2)
        for row in range(self.bh):
            src = row * self.bw * 2
            dst = ((self.y - ny0 + row) * nw + (self.x - nx0)) * 2
            na[dst:dst + self.bw * 2] = self.a[src:src + self.bw * 2]
        self.x, self.y, self.bw, self.bh, self.a = nx0, ny0, nw, nh, na
        return True

    def max_abs(self):
        m = 0.0
        a = self.a
        for i in range(0, len(a), 2):
            m = max(m, math.hypot(a[i], a[i + 1]))
        return m

def _load_mesh(layer, w, h):
    # Parasite bytes are signed chars in the GIMP 3 binding, so the mesh is base64 text.
    m = Mesh(w, h)
    text = _pstr(layer, DISP)
    if not text:
        return m
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except Exception:
        return m
    head = struct.calcsize("<4sIIIIIII")
    if len(raw) < head:
        return m
    magic, ver, lw, lh, x, y, bw, bh = struct.unpack_from("<4sIIIIIII", raw)
    if magic != b"MLQ1" or ver != 1 or lw != w or lh != h:
        return m
    if bw == 0 or bh == 0:
        return m
    data = raw[head:]
    need = bw * bh * 2 * 4
    if len(data) != need or x < 0 or y < 0 or x + bw > w or y + bh > h:
        return m
    m.x, m.y, m.bw, m.bh = x, y, bw, bh
    m.a = array.array("f")
    m.a.frombytes(data)
    if sys.byteorder != "little":
        m.a.byteswap()
    if len(m.a) != bw * bh * 2:
        return Mesh(w, h)
    return m

def _save_mesh(layer, mesh):
    if mesh.bw == 0:
        layer.detach_parasite(DISP)
        return
    a = mesh.a
    if sys.byteorder != "little":
        a = array.array("f", a)
        a.byteswap()
    blob = struct.pack("<4sIIIIIII", b"MLQ1", 1, mesh.lw, mesh.lh, mesh.x, mesh.y, mesh.bw, mesh.bh) + a.tobytes()
    _pset(layer, DISP, base64.b64encode(blob).decode("ascii"))

def _walk_group(layers, key):
    for layer in layers:
        if layer.is_group() and _pstr(layer, KEY) == key:
            return layer
        if layer.is_group():
            found = _walk_group(layer.get_children(), key)
            if found is not None:
                return found
    return None

def _original_of(group):
    if group is None:
        return None
    for child in group.get_children():
        if _pstr(child, ROLE) == "original":
            return child
    return None

def _make_state(image, layer):
    key = _pstr(layer, KEY) or uuid.uuid4().hex
    group = Gimp.GroupLayer.new(image, "液化状态 Liquify State")
    if not image.insert_layer(group, None, len(image.get_layers())):
        raise RuntimeError("insert state group failed")
    group.set_visible(False)
    orig = layer.copy()
    orig.set_name("原始像素 Original")
    orig.detach_parasite(DISP)
    orig.detach_parasite(KEY)
    if not image.insert_layer(orig, group, 0):
        raise RuntimeError("insert original snapshot failed")
    orig.set_lock_content(True)
    _pset(group, KEY, key)
    _pset(layer, KEY, key)
    _pset(orig, ROLE, "original")
    return group, orig

def _drop_state(image, layer, group):
    if group is not None:
        image.remove_layer(group)
    layer.detach_parasite(DISP)

def _weights(image, layer, x, y, w, h):
    """Selection as 0..1, or None when there is no selection (whole layer)."""
    sel = image.get_selection()
    if Gimp.Selection.is_empty(image):
        return None
    _ok, ox, oy = layer.get_offsets()
    rect = Gegl.Rectangle.new(int(x + ox), int(y + oy), int(w), int(h))
    raw = sel.get_buffer().get(rect, 1.0, "Y float", Gegl.AbyssPolicy.NONE)
    vals = array.array("f")
    vals.frombytes(_bytes(raw))
    if len(vals) != w * h:
        raise RuntimeError("selection mask size mismatch / 选区蒙版尺寸不对")
    return vals

def _falloff(d, radius, inner, span):
    if d >= radius:
        return 0.0
    if d <= inner:
        return 1.0
    t = (d - inner) / span
    s = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)   # smootherstep, flat derivative at both ends
    return 1.0 - s

def _sample_y(drawable, layer, x, y, w, h):
    """Luminance 0..1 of drawable over a layer-pixel rectangle. 1 = white."""
    _ok, lox, loy = layer.get_offsets()
    try:
        _ok2, dox, doy = drawable.get_offsets()
    except Exception:
        dox = doy = 0
    rect = Gegl.Rectangle.new(int(x + lox - dox), int(y + loy - doy), int(w), int(h))
    raw = drawable.get_buffer().get(rect, 1.0, "Y float", Gegl.AbyssPolicy.NONE)
    vals = array.array("f")
    vals.frombytes(_bytes(raw))
    if len(vals) != w * h:
        raise RuntimeError("freeze mask size mismatch / 冻结蒙版尺寸不对")
    return vals

def _freeze_gate(mask, w, h, feather):
    """0 on frozen pixels (luminance >= 0.5), rising smoothly to 1 over `feather` px on the free side.
    Returns None when nothing in the rectangle is frozen."""
    n = w * h
    INF = 1000000
    dist = array.array("i", [INF]) * n
    frozen = False
    for i, v in enumerate(mask):
        if v >= 0.5:
            dist[i] = 0
            frozen = True
    if not frozen:
        return None
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            v = dist[i]
            if x:
                v = min(v, dist[i - 1] + 3)
            if y:
                v = min(v, dist[i - w] + 3)
                if x:
                    v = min(v, dist[i - w - 1] + 4)
                if x + 1 < w:
                    v = min(v, dist[i - w + 1] + 4)
            dist[i] = v
    for y in range(h - 1, -1, -1):
        row = y * w
        for x in range(w - 1, -1, -1):
            i = row + x
            v = dist[i]
            if x + 1 < w:
                v = min(v, dist[i + 1] + 3)
            if y + 1 < h:
                v = min(v, dist[i + w] + 3)
                if x + 1 < w:
                    v = min(v, dist[i + w + 1] + 4)
                if x:
                    v = min(v, dist[i + w - 1] + 4)
            dist[i] = v
    feat = max(1.0, float(feather))
    gate = array.array("f", [0.0]) * n
    for i, d3 in enumerate(dist):
        if d3 <= 0:
            continue
        d = d3 / 3.0
        if d >= feat:
            gate[i] = 1.0
        else:
            u = d / feat
            gate[i] = u * u * u * (u * (u * 6.0 - 15.0) + 10.0)
    return gate

def deform(mesh, mode, x1, y1, x2, y2, radius, strength, hardness, angle, clockwise, weights, wx, wy, ww, wh,
           freeze_src=None, freeze_feather=0.0, layer=None):
    """Add one soft brush to the mesh. Returns True if any sample was visited."""
    r = float(radius)
    if r < 1.0:
        raise RuntimeError("radius must be >= 1 / 笔刷半径至少 1")
    tstr = max(0.0, min(100.0, float(strength))) / 100.0
    if tstr <= 0.0:
        return False
    if mode == "restore" and mesh.bw == 0:
        return False
    use_seg = (mode == "push" and x2 >= 0.0 and y2 >= 0.0
               and (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1) >= 0.25)
    if use_seg:
        minx, maxx = min(x1, x2), max(x1, x2)
        miny, maxy = min(y1, y2), max(y1, y2)
    else:
        minx = maxx = x1
        miny = maxy = y1
    # clip to the selection's bounding box when there is one, else the layer
    if weights is not None:
        cx0, cy0, cx1, cy1 = wx, wy, wx + ww, wy + wh
    else:
        cx0, cy0, cx1, cy1 = 0, 0, mesh.lw, mesh.lh
    ix0 = max(cx0, int(math.floor(minx - r)))
    iy0 = max(cy0, int(math.floor(miny - r)))
    ix1 = min(cx1, int(math.ceil(maxx + r)) + 1)
    iy1 = min(cy1, int(math.ceil(maxy + r)) + 1)
    if not mesh.ensure(ix0, iy0, ix1, iy1):
        return False
    gate = None
    gx = gy = gw = 0
    if freeze_src is not None and layer is not None:
        feat = float(freeze_feather)
        if feat <= 0.0:
            feat = max(8.0, min(80.0, r * 0.25))
        pad = int(math.ceil(feat))
        gx = max(0, ix0 - pad); gy = max(0, iy0 - pad)
        gx1 = min(mesh.lw, ix1 + pad); gy1 = min(mesh.lh, iy1 + pad)
        if gx1 > gx and gy1 > gy:
            mask = _sample_y(freeze_src, layer, gx, gy, gx1 - gx, gy1 - gy)
            gate = _freeze_gate(mask, gx1 - gx, gy1 - gy, feat)
            gw = gx1 - gx
    inner = max(0.0, min(0.95, float(hardness))) * r
    span = max(1e-6, r - inner)
    r2 = r * r
    if mode == "push":
        amount = tstr * r * AMOUNT["push"]
        if use_seg:
            vx, vy = x2 - x1, y2 - y1
            L2 = vx * vx + vy * vy
            L = math.sqrt(L2)
            dirx, diry = vx / L, vy / L
        else:
            rad = math.radians(float(angle))
            dirx, diry = math.cos(rad), math.sin(rad)
            vx = vy = L2 = 0.0
    elif mode == "bloat":
        amount = tstr * r * AMOUNT["bloat"]
    elif mode == "pinch":
        amount = -tstr * r * AMOUNT["pinch"]
    elif mode == "twirl":
        amount = (tstr if clockwise else -tstr) * r * AMOUNT["twirl"]
    elif mode == "restore":
        amount = tstr
    else:
        raise RuntimeError("unknown mode / 未知模式: " + str(mode))
    if mode != "restore" and mesh.bw == 0:
        return False
    a = mesh.a
    ox, oy, bw = mesh.x, mesh.y, mesh.bw
    touched = False
    for y in range(iy0, iy1):
        py = y + 0.5
        row = (y - oy) * bw
        for x in range(ix0, ix1):
            if weights is not None:
                wsel = weights[(y - wy) * ww + (x - wx)]
                if wsel <= 0.0:
                    continue
            else:
                wsel = 1.0
            px = x + 0.5
            if mode == "push" and use_seg:
                tt = ((px - x1) * vx + (py - y1) * vy) / L2
                if tt < 0.0:
                    tt = 0.0
                elif tt > 1.0:
                    tt = 1.0
                ddx = px - (x1 + tt * vx)
                ddy = py - (y1 + tt * vy)
            else:
                ddx = px - x1
                ddy = py - y1
            d2 = ddx * ddx + ddy * ddy
            if d2 >= r2:
                continue
            d = math.sqrt(d2) if d2 > 0.0 else 0.0
            f = _falloff(d, r, inner, span) * wsel
            g = 1.0
            if gate is not None:
                g = gate[(y - gy) * gw + (x - gx)]
            if g <= 0.0:
                # Frozen pixels stay put, including any displacement already stored.
                i = (row + (x - ox)) * 2
                if a[i] != 0.0 or a[i + 1] != 0.0:
                    a[i] = 0.0
                    a[i + 1] = 0.0
                    touched = True
                continue
            f *= g
            if f <= 0.0:
                continue
            i = (row + (x - ox)) * 2
            if mode == "restore":
                k = 1.0 - amount * f
                if k < 0.0:
                    k = 0.0
                a[i] *= k
                a[i + 1] *= k
                if abs(a[i]) < 1e-4:
                    a[i] = 0.0
                if abs(a[i + 1]) < 1e-4:
                    a[i + 1] = 0.0
            elif mode == "push":
                a[i] += dirx * amount * f
                a[i + 1] += diry * amount * f
            elif mode == "twirl":
                # tangential, 0 at the center (no pinch singularity)
                s = amount * f / r
                a[i] += -ddy * s
                a[i + 1] += ddx * s
            else:
                # bloat / pinch: radial, also 0 at the center
                s = amount * f / r
                a[i] += ddx * s
                a[i + 1] += ddy * s
            touched = True
    if touched and mesh.max_abs() < 1e-3:
        mesh.x = mesh.y = mesh.bw = mesh.bh = 0
        mesh.a = array.array("f")
    return touched

def _render(orig, layer, mesh):
    """Resample the untouched snapshot through the mesh into the paint layer."""
    Gegl.init(None)
    src = orig.get_buffer()
    dst = layer.get_shadow_buffer()
    ext = src.get_extent()
    if mesh.bw == 0:
        src.copy(ext, Gegl.AbyssPolicy.NONE, dst, dst.get_extent())
    else:
        aux = Gegl.Buffer.new("YA float", ext.x, ext.y, ext.width, ext.height)
        neg = array.array("f", mesh.a)
        for i in range(len(neg)):
            neg[i] = -neg[i]          # content moves +d  =>  sample at -d
        rect = Gegl.Rectangle.new(mesh.x + ext.x, mesh.y + ext.y, mesh.bw, mesh.bh)
        aux.set(rect, "YA float", neg.tobytes())
        g = Gegl.Node()
        s = g.create_child("gegl:buffer-source"); s.set_property("buffer", src)
        a = g.create_child("gegl:buffer-source"); a.set_property("buffer", aux)
        m = g.create_child("gegl:map-relative")
        m.set_property("scaling", 1.0)
        m.set_property("sampler-type", Gegl.SamplerType.LINEAR)
        m.set_property("abyss-policy", Gegl.AbyssPolicy.CLAMP)
        o = g.create_child("gegl:write-buffer"); o.set_property("buffer", dst)
        s.connect_to("output", m, "input")
        a.connect_to("output", m, "aux")
        m.connect_to("output", o, "input")
        o.process()
    dst.flush()
    # merge_shadow only replaces pixels inside the current selection. The shadow
    # is a full-frame render, so suspend the selection or frozen-vs-free edits
    # outside it never land (selection-as-freeze).
    saved = None
    image = layer.get_image()
    if image is not None and not Gimp.Selection.is_empty(image):
        saved = Gimp.Selection.save(image)
        Gimp.Selection.none(image)
    try:
        layer.merge_shadow(True)
    finally:
        if saved is not None:
            image.select_item(Gimp.ChannelOps.REPLACE, saved)
            image.remove_channel(saved)
    layer.update(0, 0, layer.get_width(), layer.get_height())

def liquify(image, layer, mode, x1, y1, x2, y2, radius, strength, hardness, angle, clockwise,
            freeze_mode="none", freeze_layer=None, freeze_feather=0.0):
    if layer.is_group() or _pstr(layer, ROLE) == "original":
        raise RuntimeError("Choose a normal paint layer, not the hidden liquify snapshot or a group / 请选择普通图层")
    if layer.get_lock_content():
        raise RuntimeError("Layer is locked / 图层已锁定")
    w, h = layer.get_width(), layer.get_height()
    freeze_src = None
    if freeze_mode == "selection":
        if Gimp.Selection.is_empty(image):
            raise RuntimeError("No selection to turn into a freeze / 没有选区，没法冻结")
        freeze_src = image.get_selection()
        # The selection becomes the freeze. It is not also the edit limit,
        # otherwise the only pixels we could move would be the frozen ones.
        bx, by, bw, bh = 0, 0, w, h
        weights = None
    else:
        hit, bx, by, bw, bh = layer.mask_intersect()
        if not hit or bw <= 0 or bh <= 0:
            return
        weights = _weights(image, layer, bx, by, bw, bh)
        if freeze_mode == "layer":
            if freeze_layer is None:
                raise RuntimeError("Pick a freeze layer (white = frozen) / 请选择冻结图层，白色为冻住")
            if freeze_layer == layer or _pstr(freeze_layer, ROLE) == "original":
                raise RuntimeError("Freeze layer must be a different layer / 冻结图层不能是正在修的图层或原始像素")
            freeze_src = freeze_layer
    if x1 < 0.0 or y1 < 0.0:
        x1 = bx + bw / 2.0
        y1 = by + bh / 2.0
    key = _pstr(layer, KEY)
    group = _walk_group(image.get_layers(), key) if key else None
    orig = _original_of(group)
    if orig is not None and (orig.get_width() != w or orig.get_height() != h):
        _drop_state(image, layer, group)
        group, orig = None, None
    mesh = _load_mesh(layer, w, h) if orig is not None else Mesh(w, h)
    t0 = time.perf_counter()
    touched = deform(mesh, mode, x1, y1, x2, y2, radius, strength, hardness, angle, clockwise,
                     weights, bx, by, bw, bh, freeze_src, freeze_feather, layer)
    if not touched:
        return
    image.undo_group_start()
    try:
        if orig is None:
            group, orig = _make_state(image, layer)
        _save_mesh(layer, mesh)
        _render(orig, layer, mesh)
        # A visible freeze layer would cover the photo. Keep it, just hide it.
        if freeze_mode == "layer" and freeze_layer is not None:
            freeze_layer.set_visible(False)
        image.set_selected_layers([layer])
    finally:
        image.undo_group_end()
    if os.environ.get("MESH_LIQUIFY_LOG"):
        print("[mesh-liquify] mode=%s max_disp=%.3f bbox=%d,%d %dx%d %.2fs" % (
            mode, mesh.max_abs(), mesh.x, mesh.y, mesh.bw, mesh.bh, time.perf_counter() - t0),
            file=sys.stderr, flush=True)
    Gimp.displays_flush()

def _mode(config):
    i = config.get_choice_id("mode")
    if 0 <= i < len(MODES):
        return MODES[i]
    return "push"

def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "柔和液化 / Soft Mesh Liquify")
        dlg.fill(["mode", "radius", "strength", "hardness", "x1", "y1", "x2", "y2", "angle", "clockwise",
                  "freeze", "freeze-layer", "freeze-feather"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        fr_i = config.get_choice_id("freeze")
        fr_mode = ("none", "layer", "selection")[fr_i] if 0 <= fr_i <= 2 else "none"
        liquify(image, drawables[0], _mode(config),
                config.get_property("x1"), config.get_property("y1"),
                config.get_property("x2"), config.get_property("y2"),
                config.get_property("radius"), config.get_property("strength"),
                config.get_property("hardness"), config.get_property("angle"),
                config.get_property("clockwise"),
                fr_mode, config.get_property("freeze-layer"), config.get_property("freeze-feather"))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

class MeshLiquify(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC]

    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("柔和液化 / Soft Mesh Liquify")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Soft mesh liquify: push along a stroke, bloat, pinch, twirl, or restore toward the original. 柔和网格液化。",
            "One call is one brush dab or one straight stroke. Edges fall off smoothly (no hard crease). "
            "A hidden group '液化状态 Liquify State' keeps the original pixels so Restore can ease back. "
            "Coordinates are layer pixels; x1/y1 < 0 uses the selection (or layer) center. "
            "x2/y2 < 0 means a single dab (push then uses angle). Respects an existing selection. "
            "Freeze (冻结): a separate layer where white pixels never move, or turn the current selection into a freeze. "
            "Near a freeze edge, free pixels ease to zero so the mesh does not tear. Frozen pixels themselves stay put. The freeze layer is hidden after use; unhide it if you want to edit the mask.",
            name)
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("push", 0, "Push along stroke / 推移", "Move pixels along the stroke")
        ch.add("bloat", 1, "Bloat / 膨胀", "Push pixels outward from the center")
        ch.add("pinch", 2, "Pinch / 收缩", "Pull pixels inward")
        ch.add("restore", 3, "Restore / 还原", "Ease the mesh back toward the original")
        ch.add("twirl", 4, "Twirl / 旋转", "Rotate pixels around the center")
        p.add_choice_argument("mode", "Mode / 模式", None, ch, "push", F)
        p.add_double_argument("radius", "Brush radius px / 笔刷半径", "Soft falloff reaches zero at this radius",
                              1.0, 4000.0, 80.0, F)
        p.add_double_argument("strength", "Strength / 强度 (0-100)",
                              "100 pushes by about half the radius; restore 100 clears the center of the brush",
                              0.0, 100.0, 40.0, F)
        p.add_double_argument("hardness", "Hardness / 硬度 (0=最柔)",
                              "0 is fully soft. Higher keeps a flat center, still smooth at the edge",
                              0.0, 0.95, 0.0, F)
        p.add_double_argument("x1", "Center / stroke start X (<0 = auto)", "Layer pixels", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("y1", "Center / stroke start Y (<0 = auto)", "Layer pixels", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("x2", "Stroke end X (<0 = single dab)", "Push only. Both x2 and y2 must be >= 0",
                              -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("y2", "Stroke end Y (<0 = single dab)", "Push only", -1.0, 1000000.0, -1.0, F)
        p.add_double_argument("angle", "Push angle degrees / 推移角度", "Used when there is no stroke end. 0 = right, 90 = down",
                              -360.0, 360.0, 0.0, F)
        p.add_boolean_argument("clockwise", "Twirl clockwise / 顺时针旋转", "Twirl only", True, F)
        fr = Gimp.Choice.new()
        fr.add("none", 0, "No freeze / 不冻结", "")
        fr.add("layer", 1, "Freeze layer / 用冻结图层", "White pixels stay put. The layer is hidden after use; unhide it to edit the mask. 用完会自动隐藏，要改蒙版再打开眼睛。")
        fr.add("selection", 2, "Turn selection into freeze / 把当前选区变成冻结",
               "Selected pixels stay put. The selection is not also an edit limit for this stroke.")
        p.add_choice_argument("freeze", "Freeze / 冻结",
                              "Protected pixels do not move. Paint white on a layer named 冻结, or freeze the current selection.",
                              fr, "none", F)
        p.add_drawable_argument("freeze-layer", "Freeze layer / 冻结图层（白=冻住）",
                                "White = frozen. Hidden after this stroke; unhide it if you want to edit the mask. 用完会隐藏该图层，不删除。要改蒙版再取消隐藏。",
                                True, F)
        p.add_double_argument("freeze-feather", "Freeze edge softness px / 冻结边缘柔化 (0=自动)",
                              "Free pixels next to the freeze fade to zero over this many pixels. 0 = about a quarter of the brush radius. Frozen pixels never move.",
                              0.0, 400.0, 0.0, F)
        return p

Gimp.main(MeshLiquify.__gtype__, sys.argv)
