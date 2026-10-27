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
        if not info3.get("ok") or info3.get("note") != "seg-mnv3s":
            die("selfie seg failed: %s" % info3)
        w3, h3, raw3 = data3
        vals3 = memoryview(raw3)
        face = vals3[(h3 // 5) * w3 + (w3 // 2)]
        corner = vals3[4 * w3 + 4]
        frac3 = sum(1 for v in vals3 if v > 127) / float(len(vals3))
        print("SEG_HELPER selfie face=%d corner=%d frac=%.3f" % (face, corner, frac3), flush=True)
        if face < 128 or corner > 64:
            die("selfie mask not person-shaped")

    print("SEG_HELPER OK", flush=True)


if __name__ == "__main__":
    main()
