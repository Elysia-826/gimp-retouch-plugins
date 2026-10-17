import hashlib, tempfile
root = tempfile.mkdtemp(prefix="kd-batch-")
os.makedirs(root + "/in")
for i, (w, h) in enumerate(((360, 480), (640, 400))):
    img, _ = portrait(w, h)
    save_png(img, "%s/in/p%d.png" % (root, i))
md5 = {f: hashlib.md5(open(root + "/in/" + f, "rb").read()).hexdigest() for f in os.listdir(root + "/in")}
os.makedirs(root + "/out")
call("python-fu-batch-export", input_folder=Gio.File.new_for_path(root + "/in"), output_folder=Gio.File.new_for_path(root + "/out"),
     formats="jpeg,png", long_side=300)
outs = sorted(os.listdir(root + "/out"))
ok("outputs %s" % outs)
if outs != ["batch_export.log", "p0_png_web.jpg", "p0_png_web.png", "p1_png_web.jpg", "p1_png_web.png"]:
    die("unexpected output files")
for f in outs[1:]:
    im = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(root + "/out/" + f))
    if max(im.get_width(), im.get_height()) != 300:
        die("%s long side %d" % (f, max(im.get_width(), im.get_height())))
    im.delete()
if md5 != {f: hashlib.md5(open(root + "/in/" + f, "rb").read()).hexdigest() for f in os.listdir(root + "/in")}:
    die("input files changed")
ok("OK")
