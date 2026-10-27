#!/usr/bin/env python3
# No GIMP. Prove subject_select.py subject mode uses seg_mnv3s.onnx via cv2.dnn.
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "subject_select.py")
SEG = os.path.join(HERE, "seg_mnv3s.onnx")
YUNET = os.path.join(ROOT, "mesh_liquify", "face_detection_yunet_2023mar.onnx")
PHOTO = os.path.join(ROOT, "tests", "data", "astronaut.jpg")


def die(msg):
    print("SEG_HELPER FAIL " + msg, flush=True)
    sys.exit(1)


def run_subject(photo, seg_present=True):
    fd, out = tempfile.mkstemp(prefix="seg-helper-", suffix=".pgm")
    os.close(fd)
    bak = None
    try:
        if not seg_present:
            bak = SEG + ".bak-test"
            os.rename(SEG, bak)
        cmd = [sys.executable, SCRIPT, YUNET if os.path.isfile(YUNET) else "-", photo, out, "subject"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        line = ""
        for part in (r.stdout or "").splitlines():
            if part.startswith("{"):
                line = part
        if not line:
            die("no json: rc=%s stderr=%s" % (r.returncode, (r.stderr or "")[-400:]))
        info = json.loads(line)
        data = None
        if info.get("ok") and os.path.isfile(out):
            with open(out, "rb") as f:
                magic = f.readline().strip()
                dims = f.readline()
                while dims.startswith(b"#"):
                    dims = f.readline()
                w, h = [int(x) for x in dims.split()]
                f.readline()
                raw = f.read()
            if magic != b"P5" or len(raw) != w * h:
                die("bad pgm")
            data = (w, h, raw)
        return info, data
    finally:
        if bak is not None and os.path.isfile(bak):
            os.rename(bak, SEG)
        try:
            os.remove(out)
        except OSError:
            pass


def main():
    if not os.path.isfile(SEG):
        die("seg_mnv3s.onnx missing")
    if not os.path.isfile(PHOTO):
        die("astronaut.jpg missing")
    info, data = run_subject(PHOTO, True)
    if not info.get("ok"):
        die("helper not ok: %s" % info)
    if info.get("note") != "seg-mnv3s":
        die("expected note seg-mnv3s, got %s" % info.get("note"))
    w, h, raw = data
    vals = memoryview(raw)
    cx, cy = w // 2, h // 2
    center = vals[cy * w + cx]
    # astronaut: person touches some borders; require a clear bg patch at top-right
    bg = vals[8 * w + (w - 9)]
    frac = sum(1 for v in vals if v > 127) / float(len(vals))
    print("SEG_HELPER center=%d bg=%d frac=%.3f %dx%d note=%s" % (
        center, bg, frac, w, h, info["note"]), flush=True)
    if center < 128:
        die("center not person")
    if bg > 64:
        die("expected background patch selected")
    if frac < 0.2 or frac > 0.92:
        die("person frac out of range: %.3f" % frac)

    info2, _ = run_subject(PHOTO, False)
    note2 = info2.get("note")
    print("SEG_HELPER fallback note=%s ok=%s" % (note2, info2.get("ok")), flush=True)
    if note2 == "seg-mnv3s":
        die("fallback still used seg")
    if info2.get("ok"):
        pass
    elif info2.get("error") != "no-subject":
        die("fallback unexpected %s" % info2)

    selfie = "/workspace/retouch-trial/before.jpg"
    if os.path.isfile(selfie):
        info3, data3 = run_subject(selfie, True)
        if not info3.get("ok"):
            die("selfie not ok: %s" % info3)
        note3 = info3.get("note")
        # Half-body selfie: shoulder-cut seg must fall back; good seg may stay.
        if note3 not in ("seg-mnv3s", "grabcut-plus-dark-edge"):
            die("selfie unexpected note: %s" % info3)
        if not info3.get("face"):
            die("selfie needs face for cover check: %s" % info3)
        w3, h3, raw3 = data3
        mask = memoryview(raw3)
        mid = mask[(h3 // 5) * w3 + (w3 // 2)]
        corner = mask[4 * w3 + 4]
        frac3 = sum(1 for v in mask if v > 127) / float(len(mask))
        if mid < 128 or corner > 64:
            die("selfie mask not person-shaped")
        if not info3.get("face") or "box" not in info3:
            die("selfie needs face box for cover check")
        bx, by, bw, bh = info3["box"]
        x0 = max(0, int(bx - 0.8 * bw))
        x1 = min(w3, int(bx + bw + 0.8 * bw))
        y0 = max(0, int(by))
        y1 = min(h3, int(by + bh + 1.75 * bh))
        cx = int(bx + 0.5 * bw)
        mid_y0 = min(h3 - 1, max(0, int(by + bh)))
        mid_y1 = min(h3, int(by + bh + 1.5 * bh))

        def band_cover(y_a, y_b, x_a, x_b):
            if y_b <= y_a or x_b <= x_a:
                return 0.0
            total = 0
            hit = 0
            for y in range(y_a, y_b):
                row = y * w3
                for x in range(x_a, x_b):
                    total += 1
                    if mask[row + x] > 127:
                        hit += 1
            return hit / float(total) if total else 0.0

        torso = band_cover(y0, y1, x0, x1)
        left = band_cover(mid_y0, mid_y1, x0, cx)
        right = band_cover(mid_y0, mid_y1, cx, x1)
        print(
            "SEG_HELPER selfie note=%s face=%d corner=%d frac=%.3f "
            "torso=%.3f L=%.3f R=%.3f" % (
                note3, mid, corner, frac3, torso, left, right),
            flush=True)
        if torso < 0.70:
            die("selfie torso cover too low: %.3f" % torso)
        if min(left, right) < 0.70:
            die("selfie shoulder imbalance L=%.3f R=%.3f" % (left, right))
        if abs(left - right) > 0.25:
            die("selfie L/R gap too big: %.3f" % abs(left - right))

        # Both ears: skin-like pixels just outside the face box (eye to lobe)
        # must be mostly selected; wood further out must stay out.
        import numpy as np
        try:
            import cv2
        except ImportError:
            die("cv2 required for ear check")
        img = cv2.imread(selfie)
        if img is None:
            die("selfie unreadable for ear check")
        sys.path.insert(0, HERE)
        import subject_select as ss
        if not os.path.isfile(YUNET):
            die("yunet missing for ear check")
        face = ss._detect(img, YUNET)
        if face is None:
            die("selfie ear check needs face landmarks")
        fbx, fby, fbw, fbh = face["box"]
        fre, fle = face["right_eye"], face["left_eye"]
        fnose = face.get("nose") or [fbx + 0.5 * fbw, fby + 0.55 * fbh]
        zy1 = int(min(fre[1], fle[1]))
        zy2 = int(fnose[1] + 0.08 * fbh)
        mid_img, _ = ss._resize_long(img, 1600)
        yl = ss._face_yellow_limit(mid_img, face, mid_img.shape[1] / float(w3)) + 14.0
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        mask_arr = np.frombuffer(bytes(raw3), dtype=np.uint8).reshape(h3, w3)

        def ear_recall(x0, x1):
            x0 = max(0, int(x0))
            x1 = min(w3, int(x1))
            if x1 <= x0 or zy2 <= zy1:
                return 1.0, 0.0
            zone = lab[zy1:zy2, x0:x1]
            skin = (
                (zone[:, :, 1] > 134)
                & (zone[:, :, 2] <= yl)
                & (zone[:, :, 0] > 35)
                & (zone[:, :, 0] < 210)
            )
            sel = mask_arr[zy1:zy2, x0:x1] > 127
            nskin = int(skin.sum())
            if nskin < 50:
                return 1.0, 0.0
            rec = float((skin & sel).sum()) / float(nskin)
            woodish = float((sel & (zone[:, :, 2] > 160)).sum()) / max(
                1, int(sel.sum()))
            return rec, woodish

        face_r = fbx + fbw
        rr, rw = ear_recall(face_r, face_r + 0.12 * fbw)
        lr, lw = ear_recall(fbx - 0.12 * fbw, fbx)
        print(
            "SEG_HELPER selfie ears R_rec=%.3f L_rec=%.3f "
            "R_woodish=%.3f L_woodish=%.3f" % (rr, lr, rw, lw),
            flush=True,
        )
        if rr < 0.90:
            die("selfie right ear recall too low: %.3f" % rr)
        if lr < 0.90:
            die("selfie left ear recall too low: %.3f" % lr)
        if rw > 0.15:
            die("selfie right ear hang took too much wood: %.3f" % rw)

    print("SEG_HELPER OK", flush=True)


if __name__ == "__main__":
    main()
