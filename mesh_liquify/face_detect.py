#!/usr/bin/env python3
# YuNet face box + 5 landmarks for mesh_liquify. Uses OpenCV (cv2) only.
# Prints one JSON object on stdout. Not a GIMP plugin.
import json
import sys

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
    img = cv2.imread(path, cv2.IMREAD_COLOR)
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
    print(json.dumps({
        "ok": True,
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
