#!/bin/bash
# GUI check on a private Xvfb display: run 按脸调整 (dialog OK'd by xdotool, then non-interactive) and the
# liquify undo, capture GIMP stderr, fail on any undo_group_end CRITICAL.
D=${1:-:93}; export GIMP3_DIRECTORY=/tmp/kd-gimp
IMG=${2:-/tmp/liq_gui_test.jpg}
LOG=/tmp/kd_gui_face.log
Xvfb $D -screen 0 1600x1000x24 >/dev/null 2>&1 & XP=$!
sleep 2; export DISPLAY=$D
xfwm4 --compositor=off >/dev/null 2>&1 & WP=$!
sleep 1
cat > /tmp/kd_gui_face.py <<PY
from gi.repository import Gimp, Gio
pdb = Gimp.get_pdb()
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("$IMG"))
Gimp.Display.new(img)
lay = img.get_layers()[0]
def face(mode, **kw):
    p = pdb.lookup_procedure("python-fu-mesh-liquify-face"); c = p.create_config()
    c.set_property("run-mode", mode); c.set_property("image", img)
    c.set_core_object_array("drawables", [lay]); c.set_property("source", "auto")
    for k, v in kw.items(): c.set_property(k, v)
    print("GUIFACE", kw, p.run(c).index(0), flush=True)
face(Gimp.RunMode.INTERACTIVE, nose=14.0)
for kw in ({"nose": 14.0}, {"eye": 14.0}, {"jaw": 21.0}):
    face(Gimp.RunMode.NONINTERACTIVE, **kw)
u = pdb.lookup_procedure("python-fu-mesh-liquify-undo"); c = u.create_config()
c.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE); c.set_property("image", img)
c.set_core_object_array("drawables", [lay])
print("GUIUNDO", u.run(c).index(0), flush=True)
PY
( for i in $(seq 60); do sleep 2; w=$(xdotool search --name "^按脸调整 / Face Adjust$" 2>/dev/null | head -1)
  [ -n "$w" ] && { xdotool windowactivate --sync $w 2>/dev/null; sleep 1; xdotool key Return; }; done ) & KP=$!
timeout 300 gimp-3.0 --no-splash --quit --batch-interpreter=python-fu-eval -b "exec(open('/tmp/kd_gui_face.py').read())" > $LOG 2>&1
kill $KP $WP $XP 2>/dev/null
grep -E "GUIFACE|GUIUNDO" $LOG
N=$(grep -c "undo_group_end" $LOG)
R=$(grep -c "PDB_SUCCESS" $LOG)
echo "GUI_FACE undo_group_end_criticals=$N successes=$R"
[ "$N" = 0 ] && [ "$R" = 5 ] && echo "GUI_FACE OK" || { echo "GUI_FACE FAIL"; exit 1; }
