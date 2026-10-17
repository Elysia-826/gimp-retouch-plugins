#!/usr/bin/env python3
# YuNet face box + 5 landmarks for mesh_liquify. Uses OpenCV (cv2) only.
# Prints one JSON object on stdout. Not a GIMP plugin.
import json
import sys

def jaw_contour(cv2, numpy, img, box, re, le, mr, ml):
    """Lower face outline as image points, from the image edges along rays out of the mouth center."""
    np = numpy
    h, w = img.shape[:2]
    sc = min(1.0, 1400.0 / max(h, w))
    view = cv2.resize(img, (max(2, int(w * sc)), max(2, int(h * sc))), interpolation=cv2.INTER_AREA) if sc < 1.0 else img
    lab = cv2.cvtColor(cv2.GaussianBlur(view, (0, 0), 2.0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ang = np.arctan2(le[1] - re[1], le[0] - re[0])
    U = np.array([np.cos(ang), np.sin(ang)]); V = np.array([-np.sin(ang), np.cos(ang)])
    C = (np.array(mr) + np.array(ml)) * 0.5 * sc
    bx, by, bw, bh = [float(v) * sc for v in box]
    corners = np.array([[bx, by], [bx + bw, by], [bx, by + bh], [bx + bw, by + bh]]) - C
    au_r = max(float((corners @ U).max()), 1.0); au_l = max(float(-(corners @ U).min()), 1.0); bv = max(float((corners @ V).max()), 1.0)
    phis = np.radians(np.arange(-20, 201, 2))
    c, s = np.cos(phis), np.sin(phis)
    R0 = 1.0 / np.sqrt((c / np.where(c >= 0, au_r, au_l)) ** 2 + (np.maximum(s, 0.0) / bv) ** 2)
    ts = np.linspace(0.6, 1.25, 66)
    D = c[:, None] * U[None, :] + s[:, None] * V[None, :]
    def samp(rr):
        q = C[None, None, :] + rr[:, :, None] * D[:, None, :]
        x = np.clip(q[..., 0], 0, lab.shape[1] - 1).astype(np.float32)
        y = np.clip(q[..., 1], 0, lab.shape[0] - 1).astype(np.float32)
        return cv2.remap(lab, x, y, cv2.INTER_LINEAR)
    rr = ts[None, :] * R0[:, None]
    g = samp(rr + 2.0) - samp(rr - 2.0)
    E = np.abs(g[..., 0]) + 1.5 * np.hypot(g[..., 1], g[..., 2])
    E = E / (E.max(axis=1, keepdims=True) + 1e-6) - 2.0 * (ts[None, :] - 0.6)
    n, m = E.shape
    idx = np.arange(m)
    pen = 0.02 * (idx[:, None] - idx[None, :]) ** 2
    cost = -E[0]; back = np.zeros((n, m), int)
    for i in range(1, n):
        t = cost[None, :] + pen
        back[i] = np.argmin(t, axis=1)
        cost = t[idx, back[i]] - E[i]
    path = [int(np.argmin(cost))]
    for i in range(n - 1, 0, -1):
        path.append(int(back[i][path[-1]]))
    path = path[::-1]
    R = np.array([ts[j] for j in path]) * R0
    R = np.convolve(np.pad(R, 2, mode="edge"), np.ones(5) / 5.0, "valid")
    pts = (C[None, :] + R[:, None] * D) / sc
    return [[float(x), float(y)] for x, y in pts]

def clothes_gate(cv2, numpy, img, box, nose, mr, ml, contour):
    """0 on clothing below the mouth outside the face outline (not skin, not the background beside the face), easing to 1 over ~6% face width."""
    np = numpy
    import base64, zlib
    h, w = img.shape[:2]
    sc = min(1.0, 1400.0 / max(h, w))
    view = cv2.resize(img, (max(2, int(w * sc)), max(2, int(h * sc))), interpolation=cv2.INTER_AREA) if sc < 1.0 else img
    lab = cv2.cvtColor(cv2.GaussianBlur(view, (0, 0), 1.5), cv2.COLOR_BGR2LAB).astype(np.float32)
    vh, vw = lab.shape[:2]
    cont = np.array(contour) * sc
    C = (np.array(mr) + np.array(ml)) * 0.5 * sc
    bx, by, bw, bh = [float(v) * sc for v in box]
    inside = np.zeros((vh, vw), np.uint8)
    cv2.fillPoly(inside, [np.vstack([cont, [[C[0], C[1] - 0.25 * bh]]]).astype(np.int32)], 1)
    ys = np.arange(vh)[:, None] + np.zeros((1, vw), int)
    ring = cv2.erode(inside, np.ones((9, 9), np.uint8)) & (1 - cv2.erode(inside, np.ones((41, 41), np.uint8))) & (ys > C[1])
    bg = np.zeros_like(inside)
    ny, hh = int(nose[1] * sc), int(0.12 * bh)
    for x0, x1 in ((int(bx - 0.25 * bw), int(bx - 0.03 * bw)), (int(bx + 1.03 * bw), int(bx + 1.25 * bw))):
        bg[max(0, ny - hh):max(0, ny + hh), max(0, x0):max(0, x1)] = 1
    def maha(m):
        smp = lab[m > 0]
        if len(smp) < 50:
            return None
        ic = np.linalg.inv(np.cov(smp.T) + np.eye(3) * 4.0)
        d = lab - smp.mean(0)
        return np.sqrt(np.einsum("...i,ij,...j->...", d, ic, d))
    ds, db = maha(ring), maha(bg)
    if ds is None:
        return None
    cloth = (ds > 4.0) & (inside == 0) & (ys > C[1])
    if db is not None:
        cloth &= db > 4.0
    cloth = cv2.morphologyEx(cloth.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    if not cloth.any():
        return None
    feat = max(2.0, 0.06 * bw)
    dist = cv2.distanceTransform((1 - cloth).astype(np.uint8), cv2.DIST_L2, 5)
    t = np.clip(dist / feat, 0.0, 1.0)
    gate = np.round(255.0 * t * t * (3.0 - 2.0 * t)).astype(np.uint8)
    x0, y0 = max(0, int(bx - 0.3 * bw)), max(0, int(C[1] - 0.4 * bh))
    x1, y1 = min(vw, int(bx + 1.3 * bw)), min(vh, int(by + 1.3 * bh))
    crop = np.ascontiguousarray(gate[y0:y1, x0:x1])
    return {"scale": sc, "x": x0, "y": y0, "w": int(x1 - x0), "h": int(y1 - y0),
            "data": base64.b64encode(zlib.compress(crop.tobytes(), 6)).decode("ascii")}

def main():
    if len(sys.argv) != 3:
        print(json.dumps({"ok": False, "error": "usage: face_detect.py model image"}))
        return 2
    model, path = sys.argv[1], sys.argv[2]
    try:
        import cv2
    except Exception as e:
        print(json.dumps({"ok": False, "error": "no-cv2", "detail": str(e)}))
        return 3
    # imdecode instead of imread: imread cannot open non-ASCII paths on Windows
    import numpy
    img = cv2.imdecode(numpy.fromfile(path, dtype=numpy.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(json.dumps({"ok": False, "error": "unreadable"}))
        return 4
    h, w = img.shape[:2]
    longside = 720
    view = img
    if max(h, w) > longside:
        scale = longside / float(max(h, w))
        nw = max(2, int(round(w * scale)) // 2 * 2)
        nh = max(2, int(round(h * scale)) // 2 * 2)
        view = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    vh, vw = view.shape[:2]
    det = cv2.FaceDetectorYN.create(model, "", (vw, vh), 0.75, 0.3, 5000)
    det.setInputSize((vw, vh))
    _ok, faces = det.detect(view)
    if faces is None or len(faces) == 0:
        print(json.dumps({"ok": False, "error": "none", "image_w": w, "image_h": h}))
        return 0
    best = max(faces, key=lambda row: float(row[-1]))
    score = float(best[-1])
    if score < 0.75:
        print(json.dumps({"ok": False, "error": "low", "score": score, "image_w": w, "image_h": h}))
        return 0
    inv = float(w) / float(vw)
    v = [float(x) * inv for x in best[:14]]
    try:
        jaw = jaw_contour(cv2, numpy, img, v[0:4], v[4:6], v[6:8], v[10:12], v[12:14])
    except Exception:
        jaw = None
    gate = None
    if jaw:
        try:
            gate = clothes_gate(cv2, numpy, img, v[0:4], v[8:10], v[10:12], v[12:14], jaw)
        except Exception:
            gate = None
    print(json.dumps({
        "ok": True,
        "jaw_contour": jaw,
        "jaw_gate": gate,
        "score": score,
        "image_w": w,
        "image_h": h,
        "box": v[0:4],
        "right_eye": v[4:6],
        "left_eye": v[6:8],
        "nose": v[8:10],
        "mouth_right": v[10:12],
        "mouth_left": v[12:14],
    }))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(json.dumps({"ok": False, "error": "crash", "detail": str(e)}))
        sys.exit(1)
