#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 柔和网格液化 / Soft mesh liquify  (GIMP 3.0.x and 3.2.x)
# Displacement is accumulated on a mesh and re-rendered from a hidden copy of
# the original pixels (gegl:map-relative). No numpy: the mesh is pure Python,
# the pixel resample is GEGL. Face sliders use the same mesh.
import array, base64, json, math, os, struct, subprocess, sys, tempfile, time, uuid, gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl

PROC = "python-fu-mesh-liquify"
PROC_STROKE = "python-fu-mesh-liquify-stroke-layer"
PROC_UNDO = "python-fu-mesh-liquify-undo"
PROC_REDO = "python-fu-mesh-liquify-redo"
PROC_FACE = "python-fu-mesh-liquify-face"
STROKE_NAME = "液化笔触"
KEY = "mesh-liquify-key"       # shared id on the paint layer and the state group
ROLE = "mesh-liquify-role"     # "original" on the hidden snapshot layer
DISP = "mesh-liquify-disp"     # native-endian mesh blob on the paint layer
HIST = "mesh-liquify-hist"     # earlier meshes, oldest first; one entry per stroke
REDO = "mesh-liquify-redo"
HIST_MAX = 24
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

def _mesh_blob(mesh):
    """MLQ1 bytes, or empty bytes when the mesh is identity."""
    if mesh.bw == 0:
        return b""
    a = mesh.a
    if sys.byteorder != "little":
        a = array.array("f", a)
        a.byteswap()
    return struct.pack("<4sIIIIIII", b"MLQ1", 1, mesh.lw, mesh.lh, mesh.x, mesh.y, mesh.bw, mesh.bh) + a.tobytes()

def _mesh_from_blob(blob, w, h):
    m = Mesh(w, h)
    if not blob:
        return m
    head = struct.calcsize("<4sIIIIIII")
    if len(blob) < head:
        return m
    magic, ver, lw, lh, x, y, bw, bh = struct.unpack_from("<4sIIIIIII", blob)
    if magic != b"MLQ1" or ver != 1 or lw != w or lh != h or bw == 0 or bh == 0:
        return m
    data = blob[head:]
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
    blob = _mesh_blob(mesh)
    if not blob:
        layer.detach_parasite(DISP)
        return
    _pset(layer, DISP, base64.b64encode(blob).decode("ascii"))

def _load_stack(layer, name):
    text = _pstr(layer, name)
    if not text:
        return []
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except Exception:
        return []
    head = struct.calcsize("<4sII")
    if len(raw) < head:
        return []
    magic, ver, count = struct.unpack_from("<4sII", raw)
    if magic != b"MLHS" or ver != 1 or count > 1000:
        return []
    off = head
    out = []
    for _i in range(count):
        if off + 4 > len(raw):
            return []
        n = struct.unpack_from("<I", raw, off)[0]
        off += 4
        if n > len(raw) - off:
            return []
        out.append(raw[off:off + n])
        off += n
    return out

def _save_stack(layer, name, items):
    if not items:
        layer.detach_parasite(name)
        return
    parts = [struct.pack("<4sII", b"MLHS", 1, len(items))]
    for blob in items:
        parts.append(struct.pack("<I", len(blob)))
        parts.append(blob)
    _pset(layer, name, base64.b64encode(b"".join(parts)).decode("ascii"))

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
    orig.detach_parasite(HIST)
    orig.detach_parasite(REDO)
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
    layer.detach_parasite(HIST)
    layer.detach_parasite(REDO)

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

def _lum_rect(drawable, x, y, w, h):
    """Layer-pixel luminance (0..1) from a drawable whose buffer is layer-sized."""
    buf = drawable.get_buffer()
    ext = buf.get_extent()
    rect = Gegl.Rectangle.new(int(ext.x + x), int(ext.y + y), int(w), int(h))
    raw = buf.get(rect, 1.0, "Y float", Gegl.AbyssPolicy.CLAMP)
    vals = array.array("f")
    vals.frombytes(_bytes(raw))
    if len(vals) != w * h:
        return None
    return vals

def _smoother(t):
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

def _clean_edges(mesh, src, gate, gx, gy, gw, gh):
    """Keep a contrast boundary from being sheared open.

    Where a soft edge (jaw against wood, a hard step) sits in a steep
    part of the displacement, every pixel of that boundary is given the
    same displacement as the free side just outside it, so the boundary
    moves as one piece. Frozen pixels stay at 0. Skin away from the
    boundary keeps the brush displacement, so texture is not blurred.
    """
    if os.environ.get("MESH_LIQUIFY_NO_CLEAN") or os.path.exists("/tmp/mesh-liquify-no-clean"):
        return
    if mesh.bw < 12 or mesh.bh < 12 or src is None:
        return
    lum = _lum_rect(src, mesh.x, mesh.y, mesh.bw, mesh.bh)
    if lum is None:
        return
    w, h = mesh.bw, mesh.bh
    span = 4
    mag = array.array("f", [0.0]) * (w * h)
    # Horizontal contrast only. A jaw/wood boundary is mostly vertical;
    # pores cancel across 8px. Vertical boundaries are handled per row,
    # horizontal ones per column below.
    for y in range(h):
        row = y * w
        for x in range(span, w - span):
            mag[row + x] = abs(lum[row + x + span] - lum[row + x - span])
    a = mesh.a
    ox, oy = mesh.x, mesh.y

    def gate_at(x, y):
        if gate is None:
            return 1.0
        lx, ly = ox + x, oy + y
        if lx < gx or ly < gy or lx >= gx + gw or ly >= gy + gh:
            return 1.0
        return gate[(ly - gy) * gw + (lx - gx)]

    def put(x, y, dx, dy):
        g = gate_at(x, y)
        # Frozen, and the first part of the feather, stay as the brush left
        # them (frozen is exactly 0). Writing the full free-side move there
        # would drag the protected side.
        if g < 0.35:
            return False
        j = (y * w + x) * 2
        a[j] = dx
        a[j + 1] = dy
        return True

    def get(x, y):
        j = (y * w + x) * 2
        return a[j], a[j + 1]

    def lock_run(y, a0, b0, horizontal):
        # a0..b0 inclusive is the contrast ramp in mesh coords along the axis.
        if b0 - a0 < 1:
            return
        if horizontal:
            # vary x, fixed y
            def outside(side):
                x = a0 - 3 if side < 0 else b0 + 3
                if x < 0 or x >= w:
                    return None
                if gate_at(x, y) <= 0.0:
                    return None
                return get(x, y)
        else:
            def outside(side):
                yy = a0 - 3 if side < 0 else b0 + 3
                if yy < 0 or yy >= h:
                    return None
                if gate_at(y, yy) <= 0.0:
                    return None
                return get(y, yy)
        left, right = outside(-1), outside(1)
        def hm(s):
            return -1.0 if s is None else math.hypot(s[0], s[1])
        if hm(left) <= 0.5 and hm(right) <= 0.5:
            return
        D = left if hm(left) >= hm(right) else right
        # only bother when the ramp's own displacement disagrees with D
        mid = (a0 + b0) // 2
        if horizontal:
            c = get(mid, y)
        else:
            c = get(y, mid)
        if abs(D[0] - c[0]) < 0.8 and abs(D[1] - c[1]) < 0.8:
            return
        # The smeared boundary shows up where the moved pixels land, about
        # |D| px on the free side of the source edge. Hold displacement
        # constant across that whole trip so the resample crosses the edge
        # in one step instead of sliding along it.
        reach = int(math.hypot(D[0], D[1])) + 2
        if reach > 48:
            reach = 48
        free_is_right = hm(right) > hm(left)
        if horizontal:
            if free_is_right:
                lo, hi = a0, min(w - 1, b0 + reach)
            else:
                lo, hi = max(0, a0 - reach), b0
            for x in range(lo, hi + 1):
                if x < a0 or x > b0:
                    dx0, dy0 = get(x, y)
                    if dx0 == 0.0 and dy0 == 0.0:
                        continue
                put(x, y, D[0], D[1])
        else:
            if free_is_right:
                lo, hi = a0, min(h - 1, b0 + reach)
            else:
                lo, hi = max(0, a0 - reach), b0
            for yy in range(lo, hi + 1):
                if yy < a0 or yy > b0:
                    dx0, dy0 = get(y, yy)
                    if dx0 == 0.0 and dy0 == 0.0:
                        continue
                put(y, yy, D[0], D[1])

    # Vertical boundaries, one row at a time.
    for y in range(h):
        row = y * w
        x = span
        while x < w - span:
            m = mag[row + x]
            if m < 0.07 or m < mag[row + x - 1] or m < mag[row + x + 1]:
                x += 1
                continue
            a0 = b0 = x
            while a0 > span and mag[row + a0 - 1] > m * 0.45:
                a0 -= 1
            while b0 + 1 < w - span and mag[row + b0 + 1] > m * 0.45:
                b0 += 1
            lock_run(y, a0, b0, True)
            x = b0 + 2
    # Horizontal boundaries (chin, brow): wide gradient down the columns.
    vmag = array.array("f", [0.0]) * (w * h)
    for y in range(span, h - span):
        row = y * w
        up = (y - span) * w
        dn = (y + span) * w
        for x in range(w):
            vmag[row + x] = abs(lum[dn + x] - lum[up + x])
    for x in range(w):
        y = span
        while y < h - span:
            m = vmag[y * w + x]
            if m < 0.07 or m < vmag[(y - 1) * w + x] or m < vmag[(y + 1) * w + x]:
                y += 1
                continue
            a0 = b0 = y
            while a0 > span and vmag[(a0 - 1) * w + x] > m * 0.45:
                a0 -= 1
            while b0 + 1 < h - span and vmag[(b0 + 1) * w + x] > m * 0.45:
                b0 += 1
            lock_run(x, a0, b0, False)
            y = b0 + 2
    if gate is not None:
        for y in range(h):
            for x in range(w):
                if gate_at(x, y) <= 0.0:
                    j = (y * w + x) * 2
                    a[j] = 0.0
                    a[j + 1] = 0.0


def _closest_poly(px, py, segs, r2):
    """Distance and unit tangent of the nearest polyline segment, or None."""
    best = r2
    bestd = None
    bx = by = 0.0
    for x1, y1, vx, vy, L2, ux, uy in segs:
        if L2 < 1e-8:
            dx, dy = px - x1, py - y1
        else:
            t = ((px - x1) * vx + (py - y1) * vy) / L2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            dx = px - (x1 + t * vx)
            dy = py - (y1 + t * vy)
        d2 = dx * dx + dy * dy
        if d2 < best:
            best = d2
            bestd = math.sqrt(d2) if d2 > 0.0 else 0.0
            bx, by = ux, uy
    if bestd is None:
        return None
    return bestd, bx, by

def _thin(m, w, h):
    """Zhang-Suen thinning. m is a mutable 0/1 bytearray, row-major."""
    def at(x, y):
        if x < 0 or y < 0 or x >= w or y >= h:
            return 0
        return m[y * w + x]
    for _pass in range(48):
        changed = False
        for step in (0, 1):
            kill = []
            for y in range(1, h - 1):
                row = y * w
                for x in range(1, w - 1):
                    if not m[row + x]:
                        continue
                    p2 = at(x, y - 1); p3 = at(x + 1, y - 1); p4 = at(x + 1, y)
                    p5 = at(x + 1, y + 1); p6 = at(x, y + 1); p7 = at(x - 1, y + 1)
                    p8 = at(x - 1, y); p9 = at(x - 1, y - 1)
                    B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if B < 2 or B > 6:
                        continue
                    seq = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
                    A = 0
                    for i in range(8):
                        if seq[i] == 0 and seq[i + 1] == 1:
                            A += 1
                    if A != 1:
                        continue
                    if step == 0:
                        if p2 and p4 and p6:
                            continue
                        if p4 and p6 and p8:
                            continue
                    else:
                        if p2 and p4 and p8:
                            continue
                        if p2 and p6 and p8:
                            continue
                    kill.append(row + x)
            if kill:
                changed = True
                for i in kill:
                    m[i] = 0
        if not changed:
            break

_N8 = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))

def _walk_skeleton(mask, w, h):
    """Longest 8-connected path. Starts at the upper-left endpoint so a
    left-to-right stroke pushes right (paint order is not stored)."""
    def nbs(x, y):
        out = []
        for dx, dy in _N8:
            xx, yy = x + dx, y + dy
            if 0 <= xx < w and 0 <= yy < h and mask[yy * w + xx]:
                out.append((xx, yy))
        return out
    pts = [(x, y) for y in range(h) for x in range(w) if mask[y * w + x]]
    if not pts:
        return []
    ends = [p for p in pts if len(nbs(*p)) <= 1]
    if not ends:
        ends = [min(pts)]
    def walk(start):
        path = [start]
        seen = {start}
        prev = None
        cur = start
        while True:
            opts = [p for p in nbs(*cur) if p not in seen]
            if not opts:
                break
            if prev is None or len(opts) == 1:
                nxt = opts[0]
            else:
                vx, vy = cur[0] - prev[0], cur[1] - prev[1]
                nxt = max(opts, key=lambda p: (p[0] - cur[0]) * vx + (p[1] - cur[1]) * vy)
            path.append(nxt)
            seen.add(nxt)
            prev, cur = cur, nxt
        return path
    best = []
    for e in ends:
        path = walk(e)
        if len(path) > len(best):
            best = path
    # Prefer the end that is upper-left as the start.
    if len(best) >= 2 and best[-1] < best[0]:
        best.reverse()
    step = 3
    out = best[::step]
    if out[-1] != best[-1]:
        out.append(best[-1])
    return out

def _trace_stroke(stroke, paint):
    """Centerline of a painted stroke, in paint-layer pixels."""
    w, h = stroke.get_width(), stroke.get_height()
    if w < 2 or h < 2:
        raise RuntimeError("Stroke layer is empty / 笔触图层是空的")
    if w * h > 6000 * 6000:
        raise RuntimeError("Stroke layer is too large / 笔触图层太大")
    buf = stroke.get_buffer()
    ext = buf.get_extent()
    raw = _bytes(buf.get(Gegl.Rectangle.new(ext.x, ext.y, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))
    if len(raw) != w * h * 4:
        raise RuntimeError("Cannot read the stroke layer / 读不到笔触图层")
    ink = bytearray(w * h)
    nink = 0
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(h):
        row = y * w
        base = row * 4
        for x in range(w):
            if raw[base + x * 4 + 3] > 40:
                ink[row + x] = 1
                nink += 1
                if x < x0: x0 = x
                if y < y0: y0 = y
                if x > x1: x1 = x
                if y > y1: y1 = y
    if nink < 2:
        raise RuntimeError("Paint a stroke on the layer first (transparent layer, GIMP brush) / 请先在透明的「液化笔触」图层上用画笔画一条线")
    if nink > w * h * 0.35:
        raise RuntimeError("The stroke layer is mostly filled. Paint a line on a transparent layer / 这个图层几乎铺满了，请在透明图层上画一条线")
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    # One empty pixel of padding so the stroke is not stuck to the array
    # border (thinning never edits the outer row, and would then do nothing).
    pw, ph = bw + 2, bh + 2
    sub = bytearray(pw * ph)
    for y in range(bh):
        src = (y + y0) * w + x0
        dst = (y + 1) * pw + 1
        sub[dst:dst + bw] = ink[src:src + bw]
    _thin(sub, pw, ph)
    sk = [(x - 1, y - 1) for x, y in _walk_skeleton(sub, pw, ph)]
    if len(sk) < 2:
        raise RuntimeError("Could not follow the stroke / 没能顺着这条笔触走下来")
    _ok, sox, soy = stroke.get_offsets()
    _ok, pox, poy = paint.get_offsets()
    dx, dy = sox - pox, soy - poy
    return [(x0 + x + dx, y0 + y + dy) for x, y in sk]

def _find_stroke_layer(layers):
    for layer in layers:
        if layer.is_group():
            if _pstr(layer, KEY):
                continue
            found = _find_stroke_layer(layer.get_children())
            if found is not None:
                return found
        elif layer.get_name() == STROKE_NAME:
            return layer
    return None

def prepare_stroke_layer(image, layer):
    """Add (or reveal) a transparent layer the user paints with GIMP's brush."""
    if layer is not None and layer.is_group():
        raise RuntimeError("Select a normal layer first / 请先选中普通图层")
    existing = _find_stroke_layer(image.get_layers())
    image.undo_group_start()
    try:
        if existing is not None:
            existing.set_visible(True)
            image.set_selected_layers([existing])
            return
        w, h = image.get_width(), image.get_height()
        sl = Gimp.Layer.new(image, STROKE_NAME, w, h, Gimp.ImageType.RGBA_IMAGE, 100.0, Gimp.LayerMode.NORMAL)
        if not image.insert_layer(sl, None, 0):
            raise RuntimeError("Could not add the stroke layer / 加不上液化笔触图层")
        sl.get_buffer().set(Gegl.Rectangle.new(0, 0, w, h), "R'G'B'A u8", bytes(w * h * 4))
        sl.update(0, 0, w, h)
        image.set_selected_layers([sl])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()

def deform(mesh, mode, x1, y1, x2, y2, radius, strength, hardness, angle, clockwise, weights, wx, wy, ww, wh,
           freeze_src=None, freeze_feather=0.0, layer=None, sample=None, poly=None, reverse=False):
    """Add one soft brush to the mesh. Returns True if any sample was visited."""
    # Painted strokes have no pen order. Default is left-to-right (vertical:
    # top-to-bottom). Reverse flips that tangent so a horizontal line pushes
    # toward smaller x.
    if reverse and poly is not None and len(poly) >= 2:
        poly = list(reversed(poly))
    r = float(radius)
    if r < 1.0:
        raise RuntimeError("radius must be >= 1 / 笔刷半径至少 1")
    tstr = max(0.0, min(100.0, float(strength))) / 100.0
    if tstr <= 0.0:
        return False
    if mode == "restore" and mesh.bw == 0:
        return False
    use_poly = mode == "push" and poly is not None and len(poly) >= 2
    use_seg = (not use_poly and mode == "push" and x2 >= 0.0 and y2 >= 0.0
               and (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1) >= 0.25)
    if use_poly:
        minx = min(p[0] for p in poly)
        maxx = max(p[0] for p in poly)
        miny = min(p[1] for p in poly)
        maxy = max(p[1] for p in poly)
    elif use_seg:
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
    gx = gy = gw = gh = 0
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
            gh = gy1 - gy
    inner = max(0.0, min(0.95, float(hardness))) * r
    span = max(1e-6, r - inner)
    r2 = r * r
    segs = []
    if use_poly:
        for i in range(len(poly) - 1):
            sx1, sy1 = poly[i]
            sx2, sy2 = poly[i + 1]
            svx, svy = sx2 - sx1, sy2 - sy1
            sL2 = svx * svx + svy * svy
            if sL2 < 1e-8:
                continue
            sL = math.sqrt(sL2)
            segs.append((sx1, sy1, svx, svy, sL2, svx / sL, svy / sL))
        if not segs:
            return False
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
        if reverse and not use_poly:
            dirx, diry = -dirx, -diry
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
            pdirx = pdiry = 0.0
            if use_poly:
                hit = _closest_poly(px, py, segs, r2)
                if hit is None:
                    continue
                d, pdirx, pdiry = hit
                d2 = d * d
            elif mode == "push" and use_seg:
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
            if not use_poly:
                d2 = ddx * ddx + ddy * ddy
                d = math.sqrt(d2) if d2 > 0.0 else 0.0
            if d2 >= r2:
                continue
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
                if use_poly:
                    a[i] += pdirx * amount * f
                    a[i + 1] += pdiry * amount * f
                else:
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
    if touched and mode != "restore":
        _clean_edges(mesh, sample if sample is not None else layer, gate, gx, gy, gw, gh)
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
            freeze_mode="none", freeze_layer=None, freeze_feather=0.0, stroke_layer=None, reverse=False):
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
    poly = None
    if stroke_layer is not None:
        if mode != "push":
            raise RuntimeError("A painted stroke is push only / 笔触图层只能用来推移")
        if stroke_layer == layer or _pstr(stroke_layer, ROLE) == "original":
            raise RuntimeError("Stroke layer must be a different layer / 笔触图层不能是正在修的图层")
        if freeze_layer is not None and stroke_layer == freeze_layer:
            raise RuntimeError("Stroke layer and freeze layer must be different / 笔触图层和冻结图层要分开")
        poly = _trace_stroke(stroke_layer, layer)
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
    sample = orig if orig is not None else layer
    before_blob = _mesh_blob(mesh)
    touched = deform(mesh, mode, x1, y1, x2, y2, radius, strength, hardness, angle, clockwise,
                     weights, bx, by, bw, bh, freeze_src, freeze_feather, layer, sample, poly, reverse)
    if not touched:
        return
    image.undo_group_start()
    try:
        if orig is None:
            group, orig = _make_state(image, layer)
        hist = _load_stack(layer, HIST)
        hist.append(before_blob)
        if len(hist) > HIST_MAX:
            hist = hist[-HIST_MAX:]
        _save_stack(layer, HIST, hist)
        _save_stack(layer, REDO, [])
        _save_mesh(layer, mesh)
        _render(orig, layer, mesh)
        # A visible freeze layer would cover the photo. Keep it, just hide it.
        if freeze_mode == "layer" and freeze_layer is not None:
            freeze_layer.set_visible(False)
        # The painted stroke would cover the photo. Keep the layer, just hide it.
        if stroke_layer is not None:
            stroke_layer.set_visible(False)
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

def _face_from_box(x, y, w, h):
    """Landmarks from a rough box. Not a detector: proportions only."""
    return {
        "box": (float(x), float(y), float(w), float(h)),
        "right_eye": (x + 0.33 * w, y + 0.40 * h),
        "left_eye": (x + 0.67 * w, y + 0.40 * h),
        "nose": (x + 0.50 * w, y + 0.57 * h),
        "mouth_right": (x + 0.36 * w, y + 0.72 * h),
        "mouth_left": (x + 0.64 * w, y + 0.72 * h),
        "score": None,
        "manual": True,
    }

def _jaw_ends(face):
    x, y, w, h = face["box"]
    ml, mr = face["mouth_left"], face["mouth_right"]
    mouth_y = (ml[1] + mr[1]) * 0.5
    bottom = y + h
    jy = mouth_y + 0.35 * max(8.0, bottom - mouth_y)
    jy = min(y + h * 0.88, max(y + h * 0.62, jy))
    return (x + 0.22 * w, jy), (x + 0.78 * w, jy)

def _dump_face(face, eye, jaw, nose):
    try:
        payload = {
            "manual": bool(face.get("manual")),
            "score": face.get("score"),
            "box": list(face["box"]),
            "right_eye": list(face["right_eye"]),
            "left_eye": list(face["left_eye"]),
            "nose": list(face["nose"]),
            "mouth_right": list(face["mouth_right"]),
            "mouth_left": list(face["mouth_left"]),
            "jaw": [list(p) for p in _jaw_ends(face)],
            "eye": eye, "jaw_slider": jaw, "nose_slider": nose,
        }
        with open("/tmp/mesh-liquify-face-last.json", "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass

def _cv2_launcher():
    """A python that can import cv2. Flatpak GIMP does not have it; the host one does."""
    homes = []
    for key in ("HOME",):
        if os.environ.get(key):
            homes.append(os.environ[key])
    homes.append(os.path.expanduser("~"))
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
    pythons = []
    for cand in ("/usr/bin/python3", "/run/host/usr/bin/python3"):
        if os.path.exists(cand):
            pythons.append(cand)
    for py in pythons:
        for sp in sites:
            env = os.environ.copy()
            if sp:
                env["PYTHONPATH"] = sp + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            try:
                r = subprocess.run([py, "-c", "import cv2"], capture_output=True, env=env, timeout=30)
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
            raise RuntimeError("Cannot read the layer / 读不到图层像素")
        rgb = bytearray(w * h * 3)
        for i in range(w * h):
            rgb[i * 3:i * 3 + 3] = raw4[i * 4:i * 4 + 3]
        raw = bytes(rgb)
    with open(path, "wb") as f:
        f.write(("P6\n%d %d\n255\n" % (w, h)).encode("ascii"))
        f.write(raw)

def _detect_face(layer):
    here = os.path.dirname(os.path.abspath(__file__))
    model = os.path.join(here, "face_detection_yunet_2023mar.onnx")
    script = os.path.join(here, "face_detect.py")
    if not os.path.isfile(model) or not os.path.isfile(script):
        raise RuntimeError("找不到认脸用的小模型。画面没有改动。 / Face model is missing. Nothing was changed.")
    py, env = _cv2_launcher()
    if py is None:
        raise RuntimeError("自动认脸需要本机 Python 里的 OpenCV（cv2），现在没有。请改用「手动画框」。画面没有改动。 / OpenCV is not available. Use the manual box. Nothing was changed.")
    fd, ppm = tempfile.mkstemp(prefix="mesh-liquify-face-", suffix=".ppm")
    os.close(fd)
    try:
        _export_ppm(layer, ppm)
        r = subprocess.run([py, script, model, ppm], capture_output=True, text=True, env=env, timeout=90)
    finally:
        try:
            os.remove(ppm)
        except OSError:
            pass
    line = ""
    for part in (r.stdout or "").splitlines():
        if part.startswith("{"):
            line = part
    if not line:
        raise RuntimeError("认脸没有返回结果。画面没有改动。 / Face detection returned nothing. Nothing was changed.")
    info = json.loads(line)
    if not info.get("ok"):
        err = info.get("error")
        if err == "no-cv2":
            raise RuntimeError("自动认脸需要本机的 OpenCV（cv2）。画面没有改动。 / OpenCV is missing. Nothing was changed.")
        raise RuntimeError("没有找到脸，画面没有改动。 / No face found, nothing was changed.")
    box = info["box"]
    return {
        "box": tuple(box),
        "right_eye": tuple(info["right_eye"]),
        "left_eye": tuple(info["left_eye"]),
        "nose": tuple(info["nose"]),
        "mouth_right": tuple(info["mouth_right"]),
        "mouth_left": tuple(info["mouth_left"]),
        "score": info.get("score"),
        "manual": False,
    }

def _edit_limits(image, layer, freeze_mode, freeze_layer):
    w, h = layer.get_width(), layer.get_height()
    freeze_src = None
    if freeze_mode == "selection":
        if Gimp.Selection.is_empty(image):
            raise RuntimeError("No selection to turn into a freeze / 没有选区，没法冻结")
        return None, 0, 0, w, h, image.get_selection()
    hit, bx, by, bw, bh = layer.mask_intersect()
    if not hit or bw <= 0 or bh <= 0:
        return "empty", 0, 0, 0, 0, None
    weights = _weights(image, layer, bx, by, bw, bh)
    if freeze_mode == "layer":
        if freeze_layer is None:
            raise RuntimeError("Pick a freeze layer (white = frozen) / 请选择冻结图层，白色为冻住")
        if freeze_layer == layer or _pstr(freeze_layer, ROLE) == "original":
            raise RuntimeError("Freeze layer must be a different layer / 冻结图层不能是正在修的图层或原始像素")
        freeze_src = freeze_layer
    return weights, bx, by, bw, bh, freeze_src

def _apply_face_mesh(mesh, face, eye, jaw, nose, weights, bx, by, bw, bh, freeze_src, freeze_feather, layer, sample):
    touched = False
    def dab(mode, x, y, radius, strength, angle=0.0):
        nonlocal touched
        if strength <= 0.0 or radius < 1.0:
            return
        if deform(mesh, mode, x, y, -1.0, -1.0, radius, strength, 0.0, angle, True,
                  weights, bx, by, bw, bh, freeze_src, freeze_feather, layer, sample, None, False):
            touched = True
    inter = abs(face["left_eye"][0] - face["right_eye"][0])
    eye_r = max(8.0, 0.16 * inter)
    if abs(eye) >= 0.05:
        mode = "bloat" if eye > 0.0 else "pinch"
        for key in ("right_eye", "left_eye"):
            dab(mode, face[key][0], face[key][1], eye_r, abs(eye))
    if abs(jaw) >= 0.05:
        left, right = _jaw_ends(face)
        box_w = face["box"][2]
        jaw_r = max(14.0, 0.18 * box_w)
        # Positive narrows: image-left jaw pushes right, image-right jaw pushes left.
        if jaw > 0.0:
            a_left, a_right = 0.0, 180.0
        else:
            a_left, a_right = 180.0, 0.0
        dab("push", left[0], left[1], jaw_r, abs(jaw), a_left)
        dab("push", right[0], right[1], jaw_r, abs(jaw), a_right)
    if abs(nose) >= 0.05:
        nx, ny = face["nose"]
        half = max(4.0, 0.12 * inter)
        nose_r = max(8.0, 0.10 * inter)
        if nose > 0.0:
            a_left, a_right = 0.0, 180.0
        else:
            a_left, a_right = 180.0, 0.0
        dab("push", nx - half, ny, nose_r, abs(nose), a_left)
        dab("push", nx + half, ny, nose_r, abs(nose), a_right)
    return touched

def face_adjust(image, layer, source, eye, jaw, nose, box, freeze_mode="none", freeze_layer=None, freeze_feather=0.0):
    if layer.is_group() or _pstr(layer, ROLE) == "original":
        raise RuntimeError("Choose a normal paint layer, not the hidden liquify snapshot or a group / 请选择普通图层")
    if layer.get_lock_content():
        raise RuntimeError("Layer is locked / 图层已锁定")
    eye = max(-20.0, min(20.0, float(eye)))
    jaw = max(-30.0, min(30.0, float(jaw)))
    nose = max(-20.0, min(20.0, float(nose)))
    if source == "box":
        x, y, bw, bh = box
        if bw < 20.0 or bh < 20.0:
            raise RuntimeError("画一个大概的脸框（宽高至少 20）。画面没有改动。 / Draw a rough face box at least 20 px. Nothing was changed.")
        face = _face_from_box(x, y, bw, bh)
    else:
        face = _detect_face(layer)
    _dump_face(face, eye, jaw, nose)
    if abs(eye) < 0.05 and abs(jaw) < 0.05 and abs(nose) < 0.05:
        return
    limits = _edit_limits(image, layer, freeze_mode, freeze_layer)
    weights, bx, by, bw, bh, freeze_src = limits
    if weights == "empty":
        return
    w, h = layer.get_width(), layer.get_height()
    key = _pstr(layer, KEY)
    group = _walk_group(image.get_layers(), key) if key else None
    orig = _original_of(group)
    if orig is not None and (orig.get_width() != w or orig.get_height() != h):
        _drop_state(image, layer, group)
        group, orig = None, None
    mesh = _load_mesh(layer, w, h) if orig is not None else Mesh(w, h)
    sample = orig if orig is not None else layer
    before_blob = _mesh_blob(mesh)
    touched = _apply_face_mesh(mesh, face, eye, jaw, nose, weights, bx, by, bw, bh, freeze_src, freeze_feather, layer, sample)
    if not touched:
        return
    image.undo_group_start()
    try:
        if orig is None:
            group, orig = _make_state(image, layer)
        hist = _load_stack(layer, HIST)
        hist.append(before_blob)
        if len(hist) > HIST_MAX:
            hist = hist[-HIST_MAX:]
        _save_stack(layer, HIST, hist)
        _save_stack(layer, REDO, [])
        _save_mesh(layer, mesh)
        _render(orig, layer, mesh)
        if freeze_mode == "layer" and freeze_layer is not None:
            freeze_layer.set_visible(False)
        image.set_selected_layers([layer])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()

def run_face(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC_FACE)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "按脸调整 / Face Adjust")
        dlg.fill(["source", "eye", "jaw", "nose", "box-x", "box-y", "box-width", "box-height",
                  "freeze", "freeze-layer", "freeze-feather"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        src_i = config.get_choice_id("source")
        source = "box" if src_i == 1 else "auto"
        fr_i = config.get_choice_id("freeze")
        fr_mode = ("none", "layer", "selection")[fr_i] if 0 <= fr_i <= 2 else "none"
        face_adjust(image, drawables[0], source,
                    config.get_property("eye"), config.get_property("jaw"), config.get_property("nose"),
                    (config.get_property("box-x"), config.get_property("box-y"),
                     config.get_property("box-width"), config.get_property("box-height")),
                    fr_mode, config.get_property("freeze-layer"), config.get_property("freeze-feather"))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

def run(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "柔和液化 / Soft Mesh Liquify")
        dlg.fill(["mode", "path", "stroke-layer", "reverse", "radius", "strength", "hardness", "x1", "y1", "x2", "y2", "angle", "clockwise",
                  "freeze", "freeze-layer", "freeze-feather"])
        ok = dlg.run()
        dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    try:
        fr_i = config.get_choice_id("freeze")
        fr_mode = ("none", "layer", "selection")[fr_i] if 0 <= fr_i <= 2 else "none"
        path_i = config.get_choice_id("path")
        stroke = config.get_property("stroke-layer") if path_i == 1 else None
        if path_i == 1 and stroke is None:
            raise RuntimeError("Pick the painted stroke layer / 请选择画好的「液化笔触」图层")
        liquify(image, drawables[0], _mode(config),
                config.get_property("x1"), config.get_property("y1"),
                config.get_property("x2"), config.get_property("y2"),
                config.get_property("radius"), config.get_property("strength"),
                config.get_property("hardness"), config.get_property("angle"),
                config.get_property("clockwise"),
                fr_mode, config.get_property("freeze-layer"), config.get_property("freeze-feather"),
                stroke, bool(config.get_property("reverse")))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

def step_stroke(image, layer, redo):
    """Put back the mesh from one stroke ago, or reapply an undone stroke.
    The hidden 液化状态 group stays; pixels are drawn from it again."""
    if layer.is_group() or _pstr(layer, ROLE) == "original":
        raise RuntimeError("Choose the paint layer, not the hidden snapshot / 请选择正在修的图层")
    w, h = layer.get_width(), layer.get_height()
    key = _pstr(layer, KEY)
    group = _walk_group(image.get_layers(), key) if key else None
    orig = _original_of(group)
    if orig is None or group is None:
        raise RuntimeError("The hidden group 液化状态 is missing, so this stroke cannot be stepped back. Do not delete that group. / 没有隐藏的「液化状态」组，撤不回这一笔。别删那个组。")
    src_name = REDO if redo else HIST
    dst_name = HIST if redo else REDO
    stack = _load_stack(layer, src_name)
    if not stack:
        if redo:
            raise RuntimeError("Nothing to redo / 没有可重做的液化笔")
        raise RuntimeError("Nothing to undo / 没有可撤销的液化笔")
    blob = stack.pop()
    current = _mesh_blob(_load_mesh(layer, w, h))
    other = _load_stack(layer, dst_name)
    other.append(current)
    if len(other) > HIST_MAX:
        other = other[-HIST_MAX:]
    mesh = _mesh_from_blob(blob, w, h)
    image.undo_group_start()
    try:
        _save_stack(layer, src_name, stack)
        _save_stack(layer, dst_name, other)
        _save_mesh(layer, mesh)
        _render(orig, layer, mesh)
        if group is not None:
            group.set_visible(False)
        image.set_selected_layers([layer])
    finally:
        image.undo_group_end()
    Gimp.displays_flush()

def run_step(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    try:
        step_stroke(image, drawables[0], bool(data))
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


def run_undo_stroke(procedure, run_mode, image, drawables, config, data):
    return run_step(procedure, run_mode, image, drawables, config, False)

def run_redo_stroke(procedure, run_mode, image, drawables, config, data):
    return run_step(procedure, run_mode, image, drawables, config, True)

def run_prepare_stroke(procedure, run_mode, image, drawables, config, data):
    if len(drawables) != 1 or not isinstance(drawables[0], Gimp.Layer):
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("Select exactly one layer / 请选择一个图层"))
    try:
        prepare_stroke_layer(image, drawables[0])
    except Exception as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class MeshLiquify(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC, PROC_STROKE, PROC_UNDO, PROC_REDO, PROC_FACE]

    def do_create_procedure(self, name):
        if name == PROC_STROKE:
            return self._make_stroke_proc(name)
        if name == PROC_UNDO:
            return self._make_step_proc(name, False)
        if name == PROC_REDO:
            return self._make_step_proc(name, True)
        if name == PROC_FACE:
            return self._make_face_proc(name)
        return self._make_liquify_proc(name)

    def _make_face_proc(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_face, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("按脸调整 / Face Adjust")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Slight eye size and a soft jaw (plus nose width) on one detected face, using the same mesh liquify. 在一张脸上轻微改眼睛大小、下颌宽窄，以及鼻翼。",
            "Auto uses YuNet (five points: two eyes, nose tip, two mouth corners) via the host Python OpenCV. "
            "If that is missing, or no face is found, nothing is changed. Manual box is not a detector: it only places the same sliders on a rectangle you give. "
            "One dialog confirm is one undoable stroke (撤销上一笔液化). Slider 0 does nothing. Not verified by hand. 尚未人工验证。",
            name)
        p.set_attribution("Elysia", "Elysia", "2026")
        src = Gimp.Choice.new()
        src.add("auto", 0, "Detect / 自动认脸", "YuNet on this layer. If no face is found, nothing changes. 找不到脸就不改。")
        src.add("box", 1, "Manual box / 手动画框", "Not detection. You give a rough face rectangle; eyes, jaw and nose are placed by proportion. 不是认脸，只按你给的框估计位置。")
        p.add_choice_argument("source", "Face source / 脸的位置", "Automatic detection, or a box you place.", src, "auto", F)
        p.add_double_argument("eye", "Eye size / 眼睛大小 (-20..20)",
                              "0 = no change. Positive makes both eyes slightly larger, negative slightly smaller. 0 不动。正数两眼一起略放大。",
                              -20.0, 20.0, 0.0, F)
        p.add_double_argument("jaw", "Jaw / 下颌 (-30..30)",
                              "0 = no change. Positive narrows the jaw softly, negative widens it. 0 不动。正数把下颌往里收，负数放宽。",
                              -30.0, 30.0, 0.0, F)
        p.add_double_argument("nose", "Nose width / 鼻宽 (-20..20)",
                              "0 = no change. Positive narrows, negative widens. From the same nose point. 0 不动。正数收窄。",
                              -20.0, 20.0, 0.0, F)
        p.add_double_argument("box-x", "Manual box X / 手动画框左", "Layer pixels. Used only for manual box.", -100000.0, 1000000.0, 0.0, F)
        p.add_double_argument("box-y", "Manual box Y / 手动画框上", "Layer pixels. Used only for manual box.", -100000.0, 1000000.0, 0.0, F)
        p.add_double_argument("box-width", "Manual box width / 手动画框宽", "At least 20. Ignored when detecting.", 0.0, 1000000.0, 0.0, F)
        p.add_double_argument("box-height", "Manual box height / 手动画框高", "At least 20. Ignored when detecting.", 0.0, 1000000.0, 0.0, F)
        fr = Gimp.Choice.new()
        fr.add("none", 0, "No freeze / 不冻结", "")
        fr.add("layer", 1, "Freeze layer / 用冻结图层", "White pixels stay put. The layer is hidden after use.")
        fr.add("selection", 2, "Turn selection into freeze / 把当前选区变成冻结", "Selected pixels stay put.")
        p.add_choice_argument("freeze", "Freeze / 冻结", "Same freeze as the other liquify strokes.", fr, "none", F)
        p.add_drawable_argument("freeze-layer", "Freeze layer / 冻结图层（白=冻住）", "White = frozen. Hidden after use, not deleted.", True, F)
        p.add_double_argument("freeze-feather", "Freeze edge softness px / 冻结边缘柔化 (0=自动)", "0 = about a quarter of the brush radius.", 0.0, 400.0, 0.0, F)
        return p

    def _make_step_proc(self, name, redo):
        fn = run_redo_stroke if redo else run_undo_stroke
        label = "重做上一笔液化 / Redo Last Liquify Stroke" if redo else "撤销上一笔液化 / Undo Last Liquify Stroke"
        blurb = ("Put back the stroke that was just undone. 把刚撤掉的那一笔液化再做上。"
                 if redo else
                 "Step back one liquify stroke. The hidden group 液化状态 stays. 退回上一笔液化，不删除隐藏的「液化状态」组。")
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, fn, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label(label)
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(blurb,
            "This is not GIMP's Ctrl+Z. Each liquify stroke is kept, and this puts the picture back to the previous stroke, redrawn from the hidden original. "
            "Redo walks forward again. A new stroke clears the redo list. Up to %d strokes are remembered. Deleting the hidden group still loses the way back." % HIST_MAX,
            name)
        p.set_attribution("Elysia", "Elysia", "2026")
        return p

    def _make_stroke_proc(self, name):
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_prepare_stroke, None)
        p.set_image_types("RGB*, GRAY*")
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        p.set_menu_label("准备液化笔触 / Prepare Liquify Stroke")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation(
            "Add a transparent layer named 液化笔触. Paint on it with GIMP's brush, then run 柔和液化 and choose that layer as the stroke. 准备一张透明图层，用 GIMP 自己的画笔在上面画。",
            "Does not liquify by itself. The filter dialog cannot receive mouse drags on the photo, so the stroke is painted with GIMP's normal brush. "
            "If the layer already exists it is shown and selected instead of creating another. The hidden 液化状态 group is not touched.",
            name)
        p.set_attribution("Elysia", "Elysia", "2026")
        return p

    def _make_liquify_proc(self, name):
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
            "Near a freeze edge, free pixels ease to zero so the mesh does not tear. Frozen pixels themselves stay put. The freeze layer is hidden after use; unhide it if you want to edit the mask. "
            "A strong contrast edge is moved as one piece, so a steep displacement does not stretch it into a wide ramp. Skin away from that edge is not blurred. "
            "This dialog cannot paint on the photo. To follow a brush stroke: run '准备液化笔触', paint with GIMP's own brush on that transparent layer, then run this filter with stroke source set to that layer. "
            "The stroke is hidden afterwards (not deleted). Direction is left-to-right, or top-to-bottom for a vertical stroke, not the order the pen moved.",
            name)
        p.set_attribution("Elysia", "Elysia", "2026")
        ch = Gimp.Choice.new()
        ch.add("push", 0, "Push along stroke / 推移", "Move pixels along the stroke")
        ch.add("bloat", 1, "Bloat / 膨胀", "Push pixels outward from the center")
        ch.add("pinch", 2, "Pinch / 收缩", "Pull pixels inward")
        ch.add("restore", 3, "Restore / 还原", "Ease the mesh back toward the original")
        ch.add("twirl", 4, "Twirl / 旋转", "Rotate pixels around the center")
        p.add_choice_argument("mode", "Mode / 模式", None, ch, "push", F)
        src = Gimp.Choice.new()
        src.add("line", 0, "Coordinates / 坐标直线", "One dab or one straight stroke from the numbers. The dialog cannot drag on the photo. 对话框里不能在照片上拖。")
        src.add("layer", 1, "Painted stroke layer / 液化笔触图层", "Follow a line painted with GIMP's brush. Run 准备液化笔触 first. 先准备图层，用 GIMP 画笔画线。")
        p.add_choice_argument("path", "Stroke source / 笔触来源",
                              "Coordinates, or a layer you painted with GIMP's own brush. This dialog does not paint on the canvas.",
                              src, "line", F)
        p.add_drawable_argument("stroke-layer", "Stroke layer / 液化笔触图层",
                                "The layer you painted. Hidden after this push, not deleted. Direction follows the line from its upper-left end, not the order you painted. 用完会隐藏，不删除。方向从左往右（竖线从上往下），不是落笔先后。",
                                True, F)
        p.add_boolean_argument("reverse", "Reverse / 反向",
                               "Off: a painted stroke pushes left to right, or top to bottom if it is taller than it is wide. On: the same stroke pushes the other way (a horizontal line toward smaller x). Does not follow pen order. 不勾：横线从左往右、竖线从上往下。勾上：同一条线反过来推，横线改成往左。",
                               False, F)
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
