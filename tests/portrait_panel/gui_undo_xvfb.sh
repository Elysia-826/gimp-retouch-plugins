#!/bin/bash
# GUI check on a private Xvfb display: build 人像面板 workspaces (role tags), rename them, build again,
# then real Ctrl+Z / Ctrl+Y on the image window; 0 CRITICAL and the image comes back.
D=${1:-:95}; IMG=${2:-$(dirname "$0")/../data/astronaut.jpg}
export GIMP3_DIRECTORY=${GIMP3_DIRECTORY:-/tmp/kd-gimp}; LOG=/tmp/kd_gui_pp_undo.log
Xvfb $D -screen 0 1600x1000x24 >/dev/null 2>&1 & XP=$!
sleep 2; export DISPLAY=$D
xfwm4 --replace --compositor=off >/dev/null 2>&1 & WP=$!
sleep 1
cat > /tmp/kd_gui_pp_undo.py <<'PY'
from gi.repository import Gimp
import importlib.util, os, sys, time
for i in range(120):
    ims = Gimp.get_images()
    if ims:
        break
    time.sleep(0.5)
img = ims[0]
d = os.path.join(os.environ["GIMP3_DIRECTORY"], "plug-ins", "portrait_panel")
sys.path.insert(0, d)
spec = importlib.util.spec_from_file_location("pp", os.path.join(d, "portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
def names():
    out = []
    def walk(items):
        for l in items:
            out.append(l.get_name())
            if l.is_group():
                walk(l.get_children())
    walk(img.get_layers())
    return out
n0 = names()
pp.build_workspace(img, "ws:dnb")
pp.build_workspace(img, "ws:heal")
n1 = names()
for l in img.get_layers():
    if l.is_group():
        l.set_name("改名组")
pp.build_workspace(img, "ws:dnb")
Gimp.displays_flush()
open("/tmp/kd_gui_pp.txt", "w").write("BUILT %d -> %d again_same=%s\n" % (len(n0), len(n1), len(names()) == len(n1)))
open("/tmp/kd_gui_pp_ready", "w").write("1")
for i in range(240):
    if os.path.exists("/tmp/kd_gui_pp_go"):
        break
    time.sleep(0.5)
open("/tmp/kd_gui_pp.txt", "a").write("AFTER layers=%d back_to_start=%s\n" % (len(names()), names() == n0))
open("/tmp/kd_gui_pp_done", "w").write("1")
PY
rm -f /tmp/kd_gui_pp_ready /tmp/kd_gui_pp.txt /tmp/kd_gui_pp_go /tmp/kd_gui_pp_done
gimp-3.0 --no-splash "$IMG" --batch-interpreter=python-fu-eval -b "exec(open('/tmp/kd_gui_pp_undo.py').read())" > $LOG 2>&1 & G=$!
for i in $(seq 120); do sleep 1; [ -f /tmp/kd_gui_pp_ready ] && break; done
sleep 3
W=$(xdotool search --name "$(basename "$IMG" .jpg).*GIMP" | head -1)
xdotool windowactivate --sync $W; sleep 1
for k in z z z z z z; do xdotool key --clearmodifiers ctrl+$k; sleep 1; done
CZ=$(grep -c CRITICAL $LOG)
for k in y y y y y y; do xdotool key --clearmodifiers ctrl+$k; sleep 1; done
CY=$(grep -c CRITICAL $LOG)
for k in z z z z z z z z; do xdotool key --clearmodifiers ctrl+$k; sleep 1; done
touch /tmp/kd_gui_pp_go
for i in $(seq 60); do sleep 1; [ -f /tmp/kd_gui_pp_done ] && break; done
C=$(grep -c CRITICAL $LOG)
cat /tmp/kd_gui_pp.txt
kill $G; sleep 1; kill $WP $XP 2>/dev/null
echo "GUI_PP criticals after_ctrlz=$CZ after_ctrly=$CY end=$C"
grep -q "again_same=True" /tmp/kd_gui_pp.txt && grep -q "back_to_start=True" /tmp/kd_gui_pp.txt && [ "$C" = 0 ] && echo "GUI_PP OK" || { echo "GUI_PP FAIL"; exit 1; }
