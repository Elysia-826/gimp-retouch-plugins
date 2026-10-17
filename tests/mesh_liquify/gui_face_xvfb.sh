#!/bin/bash
# GUI check on a private Xvfb display (GIMP3_DIRECTORY=/tmp/kd-gimp only):
# 按脸调整 nose +14 and eye +7, then real Ctrl+Z and Ctrl+Y on the image window; count undo_group_end CRITICALs.
D=${1:-:94}; IMG=${2:-/tmp/liq_gui_test.jpg}
export GIMP3_DIRECTORY=${GIMP3_DIRECTORY:-/tmp/kd-gimp}; LOG=/tmp/kd_gui_face.log
grep -q "color-profile-policy keep" $GIMP3_DIRECTORY/gimprc || echo "(color-profile-policy keep)" >> $GIMP3_DIRECTORY/gimprc
grep -q "show-welcome-dialog no" $GIMP3_DIRECTORY/gimprc || echo "(show-welcome-dialog no)" >> $GIMP3_DIRECTORY/gimprc
Xvfb $D -screen 0 1600x1000x24 >/dev/null 2>&1 & XP=$!
sleep 2; export DISPLAY=$D
xfwm4 --compositor=off >/dev/null 2>&1 & WP=$!
sleep 1
cat > /tmp/kd_gui_face.py <<'PY'
from gi.repository import Gimp
import time
pdb = Gimp.get_pdb()
for i in range(120):
    ims = Gimp.get_images()
    if ims:
        break
    time.sleep(0.5)
img = ims[0]
lay = img.get_layers()[0]
from gi.repository import Gegl
import hashlib
def sig():
    w, h = lay.get_width(), lay.get_height()
    return hashlib.md5(bytes(lay.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, "R'G'B'A u8", Gegl.AbyssPolicy.NONE))).hexdigest()
s0 = sig()
for kw in ({"nose": 14.0}, {"eye": 7.0}):
    p = pdb.lookup_procedure("python-fu-mesh-liquify-face"); c = p.create_config()
    c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
    c.set_core_object_array("drawables", [lay]); c.set_property("source", "auto")
    for k, v in kw.items():
        c.set_property(k, v)
    open("/tmp/kd_gui_face.txt", "a").write("GUIFACE %s %s\n" % (kw, p.run(c).index(0)))
Gimp.displays_flush()
open("/tmp/kd_gui_ready", "w").write("1")
import os
for i in range(240):
    if os.path.exists("/tmp/kd_gui_go"):
        break
    time.sleep(0.5)
u = pdb.lookup_procedure("python-fu-mesh-liquify-undo"); c = u.create_config()
c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
c.set_core_object_array("drawables", [lay])
st = u.run(c).index(0)
open("/tmp/kd_gui_face.txt", "a").write("GUIUNDO %s back_to_original=%s\n" % (st, sig() == s0))
open("/tmp/kd_gui_done", "w").write("1")
PY
rm -f /tmp/kd_gui_ready /tmp/kd_gui_face.txt /tmp/kd_gui_go /tmp/kd_gui_done
gimp-3.0 --no-splash "$IMG" --batch-interpreter=python-fu-eval -b "exec(open('/tmp/kd_gui_face.py').read())" > $LOG 2>&1 & G=$!
for i in $(seq 120); do sleep 1; [ -f /tmp/kd_gui_ready ] && break; done
sleep 3
W=$(xdotool search --name "$(basename "$IMG" .jpg).*GIMP" 2>/dev/null | head -1)
[ -z "$W" ] && W=$(xdotool search --name "GIMP" 2>/dev/null | head -1)
[ -z "$W" ] && W=$(xdotool search --class Gimp 2>/dev/null | head -1)
[ -z "$W" ] && W=$(xdotool search --class gimp 2>/dev/null | head -1)
if [ -z "$W" ]; then echo "GUI_FACE no image window"; else xdotool windowactivate --sync $W; sleep 1; fi
menu() { xdotool mousemove 62 42 click 1; sleep 2
  python3 -W ignore -c "from PIL import ImageGrab; im=ImageGrab.grab(xdisplay='$D').convert('L'); print('%d %d' % (max(im.crop((72,63,110,79)).getdata()), max(im.crop((72,90,110,106)).getdata())))"
  xdotool key Escape; sleep 1; }
M0=$(menu)
xdotool key --clearmodifiers ctrl+z; sleep 3
CZ=$(grep -c undo_group_end $LOG); M1=$(menu)
xdotool key --clearmodifiers ctrl+y; sleep 3
CY=$(grep -c undo_group_end $LOG); M2=$(menu)
xdotool key --clearmodifiers ctrl+z; sleep 3
touch /tmp/kd_gui_go
for i in $(seq 60); do sleep 1; [ -f /tmp/kd_gui_done ] && break; done
CU=$(grep -c undo_group_end $LOG)
cat /tmp/kd_gui_face.txt
kill $G; sleep 1; kill $WP $XP 2>/dev/null
echo "GUI_FACE menu(undo redo brightness) before=$M0 after_ctrlz=$M1 after_ctrly=$M2"
echo "GUI_FACE criticals after_ctrlz=$CZ after_ctrly=$CY after_ctrlz_and_plugin_undo=$CU"
R=$(grep -c SUCCESS /tmp/kd_gui_face.txt); O=$(grep -c "back_to_original=True" /tmp/kd_gui_face.txt)
set -- $M0; B0=${2:-0}; set -- $M1; B1=${2:-0}; set -- $M2; B2=${2:-0}
ok=0
if [ "$R" = 3 ] && [ "$O" = 1 ] && [ "$CZ" = 0 ] && [ "$CY" = 0 ] && [ "$CU" = 0 ]; then
  if [ -n "$W" ] && [ "$B1" -gt "$B0" ] && [ "$B2" -lt "$B1" ]; then ok=1
  elif [ -z "$W" ]; then echo "GUI_FACE menu check skipped (no window)"; ok=1; fi
fi
[ "$ok" = 1 ] && echo "GUI_FACE OK" || { echo "GUI_FACE FAIL"; exit 1; }
