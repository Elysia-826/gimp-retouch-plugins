# python3 verify.py <in_dir> <out_dir> [xcf_ref_png]  -- checks formats/dims/exif/icc
import sys, os, io, numpy as np
from PIL import Image, ImageCms
ind, outd = sys.argv[1], sys.argv[2]
for f in sorted(os.listdir(outd)):
    if f.endswith(".log"): continue
    im = Image.open(os.path.join(outd, f))
    icc = im.info.get("icc_profile")
    desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip() if icc else "-"
    exif = im.getexif(); make = exif.get(0x010f, "-")
    print("%-22s %-5s %4dx%-4d %-5s icc=%-28s exif_make=%s" % (f, im.format, im.width, im.height, im.mode, desc[:28], make))
if len(sys.argv) > 3:
    ref = np.asarray(Image.open(sys.argv[3]).convert("RGB"), int)
    out = np.asarray(Image.open(os.path.join(outd, "retouch_web.png")).convert("RGB"), int)
    d = abs(ref - out); print("XCF composite vs GIMP flatten: max", d.max(), "mean", round(d.mean(), 3))
