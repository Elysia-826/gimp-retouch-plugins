#!/usr/bin/env python3
# Subject / skin masks for subject_mask. OpenCV runs here, not inside GIMP.
# Prints one JSON object on stdout. Not a GIMP plugin.
# The subject edge is GrabCut (or border color) plus a short dark-pixel
# expansion. That is not a hair matte.
import json
import sys

import numpy as np


def _write_pgm(path, mask):
    h, w = mask.shape[:2]
    data = np.ascontiguousarray(mask, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(("P5\n%d %d\n255\n" % (w, h)).encode("ascii"))
        f.write(data.tobytes())


def _resize_long(img, longside):
    h, w = img.shape[:2]
    if max(h, w) <= longside:
        return img, 1.0
    scale = longside / float(max(h, w))
    nw = max(2, int(round(w * scale)) // 2 * 2)
    nh = max(2, int(round(h * scale)) // 2 * 2)
    import cv2
    return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA), float(w) / float(nw)


def _detect(img, model):
    import cv2
    h, w = img.shape[:2]
    view, _inv = _resize_long(img, 720)
    vh, vw = view.shape[:2]
    det = cv2.FaceDetectorYN.create(model, "", (vw, vh), 0.75, 0.3, 5000)
    det.setInputSize((vw, vh))
    _ok, faces = det.detect(view)
    if faces is None or len(faces) == 0:
        return None
    best = max(faces, key=lambda row: float(row[-1]))
    score = float(best[-1])
    if score < 0.75:
        return None
    scale = float(w) / float(vw)
    v = [float(x) * scale for x in best[:14]]
    return {
        "score": score,
        "box": v[0:4],
        "right_eye": v[4:6],
        "left_eye": v[6:8],
        "nose": v[8:10],
        "mouth_right": v[10:12],
        "mouth_left": v[12:14],
    }


def _fill_holes(mask):
    import cv2
    inv = cv2.bitwise_not(mask)
    flood = inv.copy()
    ff = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8)
    cv2.floodFill(flood, ff, (0, 0), 0)
    holes = flood > 0
    out = mask.copy()
    out[holes] = 255
    return out


def _upscale(mask, w, h):
    import cv2
    if mask.shape[1] == w and mask.shape[0] == h:
        return mask
    return cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)


def _grow(seed, allow, radius):
    """Dilate seed, but never step outside allow. radius is in pixels."""
    import cv2
    if radius <= 0:
        return seed
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    grown = seed
    for _ in range(int(radius // 2) + 1):
        nxt = cv2.bitwise_and(cv2.dilate(grown, k), allow)
        if (nxt == grown).all():
            break
        grown = nxt
    return grown


def _fill_enclosed(mask):
    """Fill background pockets that do not reach any image border."""
    import cv2
    bg = (mask < 128).astype(np.uint8)
    n, labels = cv2.connectedComponents(bg, connectivity=4)
    if n <= 1:
        return mask
    border = np.unique(np.concatenate(
        [labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]))
    reach = np.isin(labels, border[border > 0])
    out = mask.copy()
    out[(bg > 0) & ~reach] = 255
    return out


def _person_grabcut(small, face, sx, sy):
    """GrabCut seeded from the face. Returns a 0/255 mask at the small size.

    Nothing is forced to background except the top rows above the hair and
    narrow side strips at cheek height, so a shoulder that touches the frame
    edge or clothes in shadow are not thrown away by a fixed box.
    """
    import cv2
    sh, sw = small.shape[:2]
    bx, by, bw, bh = face["box"]
    nose = face.get("nose") or [bx + 0.5 * bw, by + 0.55 * bh]
    g = np.full((sh, sw), cv2.GC_PR_BGD, np.uint8)
    cxf = bx + 0.5 * bw
    px1 = max(0, int((cxf - 0.85 * bw) * sx))
    px2 = min(sw, int((cxf + 0.85 * bw) * sx))
    py1 = max(0, int((by - 0.25 * bh) * sy))
    g[py1:, px1:px2] = cv2.GC_PR_FGD
    g[min(sh, int((by + bh) * sy)):, :] = cv2.GC_PR_FGD
    top = int((by - 0.30 * bh) * sy)
    if top > 0:
        g[:top, :] = cv2.GC_BGD
    ey = int((by + 0.35 * bh) * sy)
    cy2 = int((by + 0.85 * bh) * sy)
    strip = max(2, int(0.03 * sw))
    if (bx - 0.08 * bw) * sx > strip:
        g[ey:cy2, :strip] = cv2.GC_BGD
    if (bx + 1.08 * bw) * sx < sw - strip:
        g[ey:cy2, sw - strip:] = cv2.GC_BGD
    cx = int(float(nose[0]) * sx)
    cy = int(float(nose[1]) * sy)
    cv2.ellipse(g, (cx, cy),
                (max(3, int(bw * 0.28 * sx)), max(3, int(bh * 0.22 * sy))),
                0, 0, 360, cv2.GC_FGD, -1)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    chroma = small.max(axis=2).astype(np.int16) - small.min(axis=2).astype(np.int16)
    hz = np.zeros(gray.shape, bool)
    hz[max(0, int((by + 0.02 * bh) * sy)):max(0, int((by + 0.28 * bh) * sy)),
       max(0, int((bx + 0.25 * bw) * sx)):min(sw, int((bx + 0.75 * bw) * sx))] = True
    g[hz & (gray < 70) & (chroma < 35)] = cv2.GC_FGD
    tx1 = max(0, int((bx + 0.40 * bw) * sx))
    tx2 = min(sw, int((bx + 0.60 * bw) * sx))
    ty1 = int((by + 1.02 * bh) * sy)
    if tx2 > tx1 and ty1 < sh - 1:
        g[ty1:sh - 1, tx1:tx2] = cv2.GC_FGD
    # A tight crop can leave no background label at all; GrabCut needs some.
    if int(((g == cv2.GC_BGD) | (g == cv2.GC_PR_BGD)).sum()) < 50:
        edge_rows = max(2, int(0.02 * sh))
        cut = max(edge_rows, min(sh, int((by + 0.35 * bh) * sy)))
        for rows, cols in ((slice(0, edge_rows), slice(0, sw)),
                           (slice(0, cut), slice(0, 2)),
                           (slice(0, cut), slice(sw - 2, sw))):
            sub = g[rows, cols]
            sub[sub != cv2.GC_FGD] = cv2.GC_PR_BGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(small, g, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    fg = np.where((g == cv2.GC_FGD) | (g == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    n, labels = cv2.connectedComponents(fg)
    cy = min(sh - 1, max(0, cy))
    cx = min(sw - 1, max(0, cx))
    keep = labels[cy, cx]
    if keep == 0:
        return fg
    return np.where(labels == keep, 255, 0).astype(np.uint8)


def _face_yellow_limit(mid, face, s):
    """LAB b above this is yellower than the face, so it is not skin and not an ear.

    Taken from the inner face (cheeks and nose), ignoring the dark hair. One
    step of slack covers rounding. A surface yellower than the face, such as
    wood, stays out even where a shadow makes it as dark as hair.
    """
    import cv2
    bx, by, bw, bh = face["box"]
    lab = cv2.cvtColor(mid, cv2.COLOR_BGR2LAB)
    x0 = max(0, int((bx + 0.28 * bw) * s))
    x1 = min(lab.shape[1], int((bx + 0.72 * bw) * s))
    y0 = max(0, int((by + 0.38 * bh) * s))
    y1 = min(lab.shape[0], int((by + 0.62 * bh) * s))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 255.0
    patch = lab[y0:y1, x0:x1]
    # Hair is much darker than skin. A fixed 50 keeps darker skin in the sample.
    keep = patch[:, :, 0] > 50
    if int(keep.sum()) < 40:
        return 255.0
    return float(np.percentile(patch[:, :, 2][keep], 99)) + 1.0


def _ear_zones(mid, fg, face, s):
    """Ears sit just outside the face box. Add pixels there that touch the
    head, differ in hue from the background in the same rows, and are not
    yellower than the face. Returns the added mask (0/255)."""
    import cv2
    mh, mw = fg.shape
    bx, by, bw, bh = face["box"]
    re = face.get("right_eye")
    le = face.get("left_eye")
    mr = face.get("mouth_right")
    ml = face.get("mouth_left")
    if not (re and le and mr and ml):
        return np.zeros_like(fg)
    lab = cv2.cvtColor(mid, cv2.COLOR_BGR2LAB).astype(np.float32)
    yellow_limit = _face_yellow_limit(mid, face, s)
    ey = min(re[1], le[1])
    my = max(mr[1], ml[1])
    zy1 = max(0, int(ey * s))
    zy2 = min(mh, int((my + 0.05 * bh) * s))
    step = max(4, int(0.05 * bh * s))
    added = np.zeros_like(fg)
    touch = cv2.dilate(fg, np.ones((3, 3), np.uint8))
    for side in (0, 1):
        if side == 0:
            zx1, zx2 = bx - 0.16 * bw, bx + 0.04 * bw
        else:
            zx1, zx2 = bx + bw - 0.04 * bw, bx + bw + 0.16 * bw
        zx1 = max(0, int(zx1 * s))
        zx2 = min(mw, int(zx2 * s))
        if zx2 - zx1 < 4 or zy2 - zy1 < 4:
            continue
        cols = slice(0, (zx1 + zx2) // 2) if side == 0 else slice((zx1 + zx2) // 2, mw)
        cand = np.zeros(fg.shape, bool)
        for y0 in range(zy1, zy2, step):
            y1 = min(zy2, y0 + step)
            rows = slice(max(0, y0 - step), min(mh, y1 + step))
            bgpx = lab[rows, cols][fg[rows, cols] == 0]
            if len(bgpx) < 20:
                continue
            ref = np.median(bgpx, axis=0)
            spread = np.median(np.abs(bgpx - ref), axis=0)
            dl = lab[y0:y1, zx1:zx2] - ref
            # Ignore lightness. A shadow on the same surface differs from the
            # lit part mostly in L (wood beside the hair); an ear differs in hue.
            d = np.sqrt(dl[:, :, 1] ** 2 + dl[:, :, 2] ** 2)
            thr = max(8.0, 3.0 * float(np.hypot(spread[1], spread[2])))
            not_wood = lab[y0:y1, zx1:zx2, 2] <= yellow_limit
            cand[y0:y1, zx1:zx2] = (d > thr) & not_wood
        cand = (cand & (fg == 0)).astype(np.uint8) * 255
        cand = cv2.morphologyEx(
            cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        n, labels = cv2.connectedComponents(cand)
        for i in range(1, n):
            comp = labels == i
            if (touch[comp] > 0).any():
                added[comp] = 255
    return added


def _subject_from_face(img, face):
    import cv2
    # GrabCut samples its color model at random. Pin it so one photo stays stable.
    cv2.setRNGSeed(0)
    h, w = img.shape[:2]
    small, _ = _resize_long(img, 800)
    sh, sw = small.shape[:2]
    fg_small = _person_grabcut(small, face, sw / float(w), sh / float(h))

    # Refine at a larger working size so edges are not 6 px stairs.
    mid, _ = _resize_long(img, 1600)
    mh, mw = mid.shape[:2]
    s = mw / float(w)
    fg = (cv2.resize(fg_small, (mw, mh), interpolation=cv2.INTER_LINEAR) > 127).astype(np.uint8) * 255
    bx, by, bw, bh = face["box"]

    # Hair: dark, nearly neutral pixels connected to the head, above the
    # mouth line. Lit gray hair against a bright wall is included; wood in
    # shadow is too colored to pass. This is a color fill, not a strand matte.
    gray = cv2.cvtColor(mid, cv2.COLOR_BGR2GRAY)
    chroma = mid.max(axis=2).astype(np.int16) - mid.min(axis=2).astype(np.int16)
    band = np.zeros(fg.shape, bool)
    band[:max(0, min(mh, int((by + 0.55 * bh) * s))), :] = True
    allow = (((gray < 135) & (chroma < 38) & band) | (fg > 0)).astype(np.uint8) * 255
    fg = _grow(fg, allow, 160)

    ears = _ear_zones(mid, fg, face, s)
    fg = np.maximum(fg, ears)

    # Snap the boundary to the strongest nearby color edge.
    r = max(2, int(0.0025 * max(mh, mw)))
    ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    sure_fg = cv2.erode(fg, ke)
    sure_fg = np.maximum(sure_fg, cv2.erode(ears, np.ones((3, 3), np.uint8)))
    sure_bg = cv2.erode(255 - fg, ke)
    markers = np.zeros((mh, mw), np.int32)
    markers[sure_bg > 0] = 1
    markers[sure_fg > 0] = 2
    cv2.watershed(mid, markers)
    out = np.where(markers == 2, 255, 0).astype(np.uint8)
    edge = markers == -1
    out[edge] = fg[edge]
    out = cv2.medianBlur(out, 5)
    out = _fill_enclosed(out)
    # Smooth upscale; the plugin adds its own small feather on top.
    full = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
    full = cv2.GaussianBlur(full, (0, 0), 0.8)
    return full


def _subject_from_border(img):
    import cv2
    h, w = img.shape[:2]
    small, _ = _resize_long(img, 800)
    sh, sw = small.shape[:2]
    b = max(2, min(8, sh // 40, sw // 40))
    strips = [
        small[:b, :, :].reshape(-1, 3),
        small[-b:, :, :].reshape(-1, 3),
        small[:, :b, :].reshape(-1, 3),
        small[:, -b:, :].reshape(-1, 3),
    ]
    bg = np.median(np.concatenate(strips, axis=0), axis=0).astype(np.float32)
    dist = np.linalg.norm(small.astype(np.float32) - bg, axis=2)
    fg = np.where(dist > 34.0, 255, 0).astype(np.uint8)
    n, labels, stats, _cent = cv2.connectedComponentsWithStats((fg > 0).astype(np.uint8), 8)
    if n <= 1:
        return np.zeros((h, w), np.uint8), 0.0
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = 1 + int(np.argmax(areas))
    mask = np.where(labels == keep, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    near = cv2.dilate(mask, kernel)
    # Thin dark bits next to the body (a stray hair) stay partly selected.
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    extra = (fg > 0) & (mask == 0) & (near > 0) & (gray < 90)
    mask[extra] = 150
    mask = _fill_holes(mask)
    mask[extra] = np.minimum(mask[extra], 170)
    mask = cv2.GaussianBlur(mask, (0, 0), 0.8)
    frac = float((mask > 40).mean())
    return _upscale(mask, w, h), frac


def _skin(img, face):
    import cv2
    h, w = img.shape[:2]
    small, _ = _resize_long(img, 900)
    sh, sw = small.shape[:2]
    s = sw / float(w)

    def sc(pt):
        return np.array(pt, np.float32) * s

    re = sc(face["right_eye"])
    le = sc(face["left_eye"])
    nose = sc(face["nose"])
    mr = sc(face["mouth_right"])
    ml = sc(face["mouth_left"])
    iod = float(np.linalg.norm(le - re))
    if iod < 4.0:
        return np.zeros((h, w), np.uint8)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)

    def samp(pt, rad=6):
        x, y = int(pt[0]), int(pt[1])
        y0, y1 = max(0, y - rad), min(sh, y + rad)
        x0, x1 = max(0, x - rad), min(sw, x + rad)
        patch = lab[y0:y1, x0:x1]
        if patch.size == 0:
            return np.array([150.0, 128.0, 128.0], np.float32)
        return np.median(patch.reshape(-1, 3), axis=0)

    cheek_r = (re + nose) / 2.0 + np.array([-iod * 0.28, iod * 0.18], np.float32)
    cheek_l = (le + nose) / 2.0 + np.array([iod * 0.28, iod * 0.18], np.float32)
    cr, cl = samp(cheek_r), samp(cheek_l)
    # L is weighted down so a bright window on one cheek does not drop out.
    wt = np.array([0.35, 1.15, 1.15], np.float32)
    d1 = np.sqrt(((lab - cr) ** 2 * wt).sum(axis=2))
    d2 = np.sqrt(((lab - cl) ** 2 * wt).sum(axis=2))
    dist = np.minimum(d1, d2)
    yy, xx = np.mgrid[0:sh, 0:sw]
    cx = (re[0] + le[0]) / 2.0
    eye_y = (re[1] + le[1]) / 2.0
    mouth_y = (mr[1] + ml[1]) / 2.0
    top = eye_y - iod * 0.55
    bot = mouth_y + iod * 0.70
    cy = (top + bot) / 2.0
    ry = max(2.0, (bot - top) / 2.0)
    rx = max(2.0, iod * 0.95)
    ell = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    skin = np.where((dist < 28.0) & ell, 255, 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, kernel)
    skin[~ell] = 0
    # Fill enclosed holes (nose shadow) when they are not hair-dark.
    inv = cv2.bitwise_not(skin)
    flood = inv.copy()
    ff = np.zeros((sh + 2, sw + 2), np.uint8)
    cv2.floodFill(flood, ff, (0, 0), 0)
    holes = (flood > 0) & ell & (lab[:, :, 0] >= 88)
    skin[holes] = 255
    er = max(2, int(round(0.16 * iod)))
    cv2.circle(skin, (int(re[0]), int(re[1])), er, 0, -1)
    cv2.circle(skin, (int(le[0]), int(le[1])), er, 0, -1)
    mx = int((mr[0] + ml[0]) / 2.0)
    my = int((mr[1] + ml[1]) / 2.0)
    mw = max(2, int(abs(ml[0] - mr[0]) * 0.46))
    mh = max(2, int(iod * 0.11))
    cv2.ellipse(skin, (mx, my), (mw, mh), 0, 0, 360, 0, -1)
    skin[lab[:, :, 0] < 72] = 0
    skin = cv2.GaussianBlur(skin, (0, 0), 0.8)
    skin[skin < 24] = 0
    return _upscale(skin, w, h)


def main():
    if len(sys.argv) != 5:
        print(json.dumps({"ok": False, "error": "usage: subject_select.py model image out.pgm subject|skin"}))
        return 2
    model, path, out_path, mode = sys.argv[1:]
    if mode not in ("subject", "skin"):
        print(json.dumps({"ok": False, "error": "mode"}))
        return 2
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
    face = None
    if model and model != "-":
        try:
            face = _detect(img, model)
        except Exception as e:
            print(json.dumps({"ok": False, "error": "detect", "detail": str(e)}))
            return 5
    note = "not-a-hair-matte"
    if mode == "skin":
        if face is None:
            print(json.dumps({"ok": False, "error": "no-face", "note": note}))
            return 0
        mask = _skin(img, face)
    elif face is not None:
        mask = _subject_from_face(img, face)
        note = "grabcut-plus-dark-edge"
    else:
        mask, frac = _subject_from_border(img)
        note = "border-color"
        if frac < 0.01 or frac > 0.92:
            print(json.dumps({"ok": False, "error": "no-subject", "fg": frac, "note": note}))
            return 0
    _write_pgm(out_path, mask)
    payload = {
        "ok": True,
        "mode": mode,
        "face": face is not None,
        "note": note,
        "w": int(img.shape[1]),
        "h": int(img.shape[0]),
    }
    if face is not None:
        payload["score"] = face["score"]
        payload["box"] = face["box"]
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(json.dumps({"ok": False, "error": "crash", "detail": str(e)}))
        sys.exit(1)
