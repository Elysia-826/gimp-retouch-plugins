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


def _subject_from_face(img, face):
    import cv2
    # GrabCut samples its color model at random. Pin it so one photo stays stable.
    cv2.setRNGSeed(0)
    h, w = img.shape[:2]
    small, _ = _resize_long(img, 800)
    sh, sw = small.shape[:2]
    sx = sw / float(w)
    sy = sh / float(h)
    bx, by, bw, bh = face["box"]
    nose = face.get("nose")
    # The old rectangle ended at the chin, so everything below it was forced
    # background. Keep the frame from above the hair down to the bottom edge.
    y_top = max(2, int((by - 0.28 * bh) * sy))
    gmask = np.full((sh, sw), cv2.GC_BGD, np.uint8)
    gmask[y_top:sh - 2, 2:sw - 2] = cv2.GC_PR_BGD
    if nose is not None:
        cx = int(float(nose[0]) * sx)
        cy = int(float(nose[1]) * sy)
    else:
        cx = int((bx + 0.5 * bw) * sx)
        cy = int((by + 0.55 * bh) * sy)
    cv2.ellipse(
        gmask, (cx, cy),
        (max(3, int(bw * 0.22 * sx)), max(3, int(bh * 0.16 * sy))),
        0, 0, 360, cv2.GC_FGD, -1)
    gray_s = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hy1 = max(0, int((by + 0.02 * bh) * sy))
    hy2 = min(sh, int((by + 0.30 * bh) * sy))
    hx1 = max(0, int((bx + 0.25 * bw) * sx))
    hx2 = min(sw, int((bx + 0.75 * bw) * sx))
    hair_zone = np.zeros(gray_s.shape, bool)
    hair_zone[hy1:hy2, hx1:hx2] = True
    gmask[hair_zone & (gray_s < 62)] = cv2.GC_FGD
    tx1 = max(2, int((bx + 0.38 * bw) * sx))
    tx2 = min(sw - 2, int((bx + 0.62 * bw) * sx))
    ty1 = min(sh - 4, int((by + 0.92 * bh) * sy))
    if tx2 > tx1 and ty1 < sh - 3:
        gmask[ty1:sh - 3, tx1:tx2] = cv2.GC_FGD
    bb, gg, rr = cv2.split(small)
    yellow = (rr.astype(np.int16) > gg.astype(np.int16) + 18) & (
        rr.astype(np.int16) > bb.astype(np.int16) + 45)
    wood_zone = np.zeros(gray_s.shape, bool)
    wy1 = min(sh - 2, int((by + 0.45 * bh) * sy))
    wx1 = min(sw - 2, int((bx + 0.92 * bw) * sx))
    wood_zone[wy1:sh - 2, wx1:sw - 2] = True
    gmask[yellow & wood_zone] = cv2.GC_BGD
    gmask[0:2, :] = cv2.GC_BGD
    gmask[-2:, :] = cv2.GC_BGD
    gmask[:, 0:2] = cv2.GC_BGD
    gmask[:, -2:] = cv2.GC_BGD
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(small, gmask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    fg = np.where((gmask == cv2.GC_FGD) | (gmask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    fg = _fill_holes(fg)
    full = cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST)

    # Dark hair touching the head, within about 120 px. Not a strand matte.
    # Strong color (yellow wood, bright window) is not hair.
    y1 = max(0, int(by - 0.28 * bh))
    y2 = min(h, int(by + 0.50 * bh))
    if y2 > y1 + 4:
        crop = full[y1:y2].copy()
        bgr = img[y1:y2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        chroma = bgr.max(axis=2).astype(np.int16) - bgr.min(axis=2).astype(np.int16)
        allow = (((gray < 108) & (chroma < 58)) | (crop > 200)).astype(np.uint8) * 255
        seed = (crop > 200).astype(np.uint8) * 255
        grown = _grow(seed, allow, 120)
        inv = np.where(crop > 200, 0, 255).astype(np.uint8)
        dist = cv2.distanceTransform(inv, cv2.DIST_L2, 3)
        added = (grown > 0) & (crop < 40) & (dist > 0) & (dist <= 120)
        crop[added] = 235
        closed = cv2.morphologyEx(
            (crop > 80).astype(np.uint8) * 255, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        closed[gray > 150] = 0
        crop[(closed > 0) & (crop < 40)] = 220
        edge = cv2.GaussianBlur(crop, (0, 0), 1.1)
        crop = np.maximum(crop, edge)
        crop[crop < 16] = 0
        full[y1:y2] = np.maximum(full[y1:y2], crop)

    # Clothes below the chin. Grow through shirt-colored pixels, then close
    # thin gaps so the torso is one region instead of a field of holes.
    chin = min(h - 8, int(by + 0.90 * bh))
    if chin < h - 8 and (full[chin:] > 200).any():
        samples = []
        for fx, fy in (
            (0.50, 80), (0.42, 400), (0.58, 400), (0.36, 800), (0.64, 800),
        ):
            x = min(w - 2, max(0, int(bx + fx * bw)))
            y = min(h - 2, chin + fy)
            samples.append(img[y, x].astype(np.float32))
        samples = np.stack(samples, 0)
        wall = np.median(img[chin:h - 2, 0:max(8, w // 30)].reshape(-1, 3), 0).astype(np.float32)
        low = img[chin:].astype(np.float32)
        d_shirt = np.min(
            np.linalg.norm(low[:, :, None, :] - samples[None, None, :, :], axis=3),
            axis=2)
        d_wall = np.linalg.norm(low - wall, axis=2)
        rr = low[:, :, 2]
        gg = low[:, :, 1]
        bb = low[:, :, 0]
        yellow_full = (rr > gg + 18) & (rr > bb + 45)
        far_right = np.zeros(yellow_full.shape, bool)
        far_right[:, int(bx + 0.95 * bw):] = True
        ok = (d_shirt < 64) & (d_shirt + 6 < d_wall) & ~(yellow_full & far_right)
        allow = np.where(ok | (full[chin:] > 200), 255, 0).astype(np.uint8)
        seed = (full[chin:] > 200).astype(np.uint8) * 255
        grown = _grow(seed, allow, max(w, h - chin))
        full[chin:][(grown > 0) & (full[chin:] < 40)] = 230
        # Bridge thin holes inside the clothes. Only shirt-like pixels may fill in.
        binary = (full[chin:] > 40).astype(np.uint8) * 255
        bridged = cv2.morphologyEx(
            binary, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
        near_shirt = (d_shirt < 80) & (d_shirt < d_wall + 12) & ~(yellow_full & far_right)
        full[chin:][(bridged > 0) & (full[chin:] < 40) & near_shirt] = 230
    full = _fill_holes(full)
    # A hole-fill must not paint the yellow wood back in.
    if h > 8 and w > 8:
        bgr = img
        rr = bgr[:, :, 2].astype(np.int16)
        gg = bgr[:, :, 1].astype(np.int16)
        bb = bgr[:, :, 0].astype(np.int16)
        yellow = (rr > gg + 18) & (rr > bb + 45)
        right = np.zeros((h, w), bool)
        right[:, int(bx + 0.95 * bw):] = True
        below = np.zeros((h, w), bool)
        below[int(by + 0.45 * bh):, :] = True
        full[yellow & right & below] = 0
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
    img = cv2.imread(path, cv2.IMREAD_COLOR)
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
