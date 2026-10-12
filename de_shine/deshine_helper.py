#!/usr/bin/env python3
# 去油光 helper. OpenCV runs here, not inside GIMP. Not a GIMP plugin.
# usage: deshine_helper.py MODEL|- IN.ppm SEL.pgm|- OUT.ppm OUT.pgm SENS SOFT ONLYFACE(0/1)
# OUT.ppm = photo with shine fully corrected (only the low-frequency part is
# changed, fine texture is copied from the photo). OUT.pgm = soft shine mask.
# Prints one JSON object on stdout.
import json
import sys

import numpy as np


def _read_pnm(path):
    with open(path, "rb") as f:
        magic = f.readline().strip()
        line = f.readline()
        while line.startswith(b"#"):
            line = f.readline()
        w, h = [int(x) for x in line.split()]
        f.readline()
        ch = 3 if magic == b"P6" else 1
        data = np.frombuffer(f.read(w * h * ch), np.uint8)
    return data.reshape((h, w, ch)) if ch == 3 else data.reshape((h, w))


def _write(path, arr):
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[:2]
    magic = "P6" if arr.ndim == 3 else "P5"
    with open(path, "wb") as f:
        f.write(("%s\n%d %d\n255\n" % (magic, w, h)).encode("ascii"))
        f.write(arr.tobytes())


def _faces(bgr, model):
    import cv2
    h, w = bgr.shape[:2]
    s = min(1.0, 720.0 / max(h, w))
    view = cv2.resize(bgr, (max(2, int(w * s)), max(2, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else bgr
    vh, vw = view.shape[:2]
    det = cv2.FaceDetectorYN.create(model, "", (vw, vh), 0.7, 0.3, 5000)
    det.setInputSize((vw, vh))
    _ok, faces = det.detect(view)
    out = []
    for row in (faces if faces is not None else []):
        out.append([float(v) / s for v in row[:14]])
    return out


def _blur(x, sigma):
    import cv2
    sigma = max(0.5, float(sigma))
    return cv2.GaussianBlur(x, (0, 0), sigma)


def main(argv):
    try:
        import cv2
    except Exception:
        print(json.dumps({"ok": False, "error": "no-cv2"}))
        return 0
    model, inp, selp, outp, maskp = argv[1:6]
    sens = float(argv[6])
    soft = float(argv[7])
    only_face = argv[8] == "1"
    rgb = _read_pnm(inp)
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    faces = _faces(bgr, model) if model != "-" else []
    if only_face and not faces:
        print(json.dumps({"ok": False, "error": "no-face"}))
        return 0

    lab = cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)  # L 0..100
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    cr, cb = ycc[:, :, 1], ycc[:, :, 2]
    # Skin chroma, wide on purpose: shiny skin is paler than normal skin.
    skin = ((cr > 133) & (cr < 180) & (cb > 75) & (cb < 135)).astype(np.float32)
    shine_color = ((lab[:, :, 0] > 55) & (np.abs(cr - 128) < 30) & (np.abs(cb - 128) < 25)).astype(np.float32)

    scale = max(h, w) / 100.0
    region = np.zeros((h, w), np.float32)
    protect = np.zeros((h, w), np.float32)
    if faces:
        for f in faces:
            bx, by, bw, bh = f[:4]
            cx, cy = bx + bw / 2, by + bh * 0.48
            cv2.ellipse(region, (int(cx), int(cy)), (int(bw * 0.56), int(bh * 0.68)), 0, 0, 360, 1.0, -1)
            scale = min(scale, bw / 20.0) if scale else bw / 20.0
            # eyes (catchlights) and mouth (teeth, lip gloss) are not oil
            r_eye = max(3, int(bw * 0.11))
            for k in (4, 6):
                cv2.circle(protect, (int(f[k]), int(f[k + 1])), r_eye, 1.0, -1)
            mx = (f[10] + f[12]) / 2
            my = (f[11] + f[13]) / 2
            mw = abs(f[10] - f[12])
            cv2.ellipse(protect, (int(mx), int(my)), (int(mw * 0.75 + 4), int(bh * 0.11 + 3)), 0, 0, 360, 1.0, -1)
    if not only_face:
        region[:] = 1.0
    scale = max(2.0, scale)
    # allowed area: skin or pale shine inside a closed skin neighbourhood
    skin_near = cv2.dilate(skin, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(scale) | 1, int(scale) | 1)))
    allow = region * np.clip(skin + shine_color * skin_near, 0, 1)
    # stay off the face outline: rim light against the background is not oil
    er = int(scale * 0.8) | 1
    allow = cv2.erode(allow, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (er, er)))
    allow = np.clip(_blur(allow, scale * 0.3), 0, 1)
    allow *= 1.0 - _blur(protect, scale * 0.3).clip(0, 1) * 1.0
    if selp != "-":
        allow *= _read_pnm(selp).astype(np.float32) / 255.0

    # low frequency base: texture (pores) lives above this scale
    sig_base = scale * 0.6
    base = np.dstack([_blur(lab[:, :, c], sig_base) for c in range(3)])
    # reference skin tone around each point, ignoring the bright spots
    L = base[:, :, 0]
    skin_w = (allow > 0.3).astype(np.float32)
    med = float(np.median(L[skin_w > 0])) if skin_w.sum() > 50 else float(np.median(L))
    sig_ref = scale * 1.2
    # two passes: local mean, then again without the spots that stick out of it
    normal_w = skin_w
    for _ in range(2):
        den = _blur(normal_w, sig_ref) + 1e-4
        ref = np.dstack([_blur(base[:, :, c] * normal_w, sig_ref) / den for c in range(3)])
        normal_w = skin_w * (L < ref[:, :, 0] + 2.0).astype(np.float32)
    far = den < 0.02
    for c in range(3):
        fallback = float(np.median(base[:, :, c][normal_w > 0])) if normal_w.sum() > 50 else float(np.median(base[:, :, c]))
        ref[:, :, c][far] = fallback

    # shine score: brighter than the surroundings AND less colourful
    dl = L - ref[:, :, 0]
    chroma = np.hypot(base[:, :, 1], base[:, :, 2])
    rchroma = np.hypot(ref[:, :, 1], ref[:, :, 2]) + 1e-3
    pale = np.clip(1.0 - chroma / rchroma, 0, 1)            # 0 = as colourful as skin
    t = 9.0 - 6.0 * (sens / 100.0)                            # sensitivity 0..100 -> 9..3 L units
    bright = np.clip((dl - t) / (t + 4.0), 0, 1)
    # and bright in absolute terms: the lit half of a face is not oil
    bright *= np.clip((L - med - 0.5 * t) / 6.0, 0, 1)
    score = bright * np.clip(0.2 + 1.5 * pale, 0, 1)
    score *= allow
    soft_sigma = max(0.5, scale * (0.1 + soft / 100.0 * 0.9))
    mask = np.clip(_blur(score, soft_sigma) * 1.25, 0, 1)

    # corrected low-frequency: pull L and colour toward the local skin tone.
    # Keep a little of the highlight (85% removed) so the face keeps its shape.
    new = base.copy()
    excess = np.maximum(dl, 0)
    # cap: oil sits on top of the lighting, it never needs a huge drop
    new[:, :, 0] = L - np.minimum(0.85 * excess, 14.0)
    for c in (1, 2):
        new[:, :, c] = base[:, :, c] + 0.85 * (ref[:, :, c] - base[:, :, c])
    # texture: highlights flatten pores, so give back a touch of contrast there
    detail = lab - base
    detail[:, :, 0] *= 1.0 + 0.25 * mask
    # where correction applies at all: wide, soft, so painting never shows a seam
    reach = np.clip(_blur((score > 0.02).astype(np.float32), scale * 0.5) * 3.0, 0, 1)[..., None]
    out_lab = base + (new - base) * reach + detail
    out_lab[:, :, 0] = np.clip(out_lab[:, :, 0], 0, 100)
    out_bgr = cv2.cvtColor(out_lab.astype(np.float32), cv2.COLOR_LAB2BGR)
    out_rgb = np.clip(out_bgr[:, :, ::-1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    # nothing moves where the correction does not reach (avoids Lab round-trip drift)
    keep = reach[..., 0] < 1.0 / 255.0
    out_rgb[keep] = rgb[keep]
    _write(outp, out_rgb)
    _write(maskp, np.clip(mask * 255.0 + 0.5, 0, 255).astype(np.uint8))
    print(json.dumps({"ok": True, "faces": len(faces), "shine_px": int((mask > 0.25).sum()),
                      "scale": scale}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
