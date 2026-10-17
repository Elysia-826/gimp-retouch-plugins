#!/bin/sh
# GUI check on a private Xvfb display: open the panel, close it via delete-event path
# (Panel.on_close), GIMP must keep running and the lock must be gone.
# Avoids xdotool windowactivate (broken under CI xfwm4 without _NET_ACTIVE_WINDOW).
D=${1:-:97}; export GIMP3_DIRECTORY=${GIMP3_DIRECTORY:-/tmp/kd-gimp}
IMG=${PP_TEST_IMAGE:-tests/data/astronaut.jpg}
case "$IMG" in /*) ;; *) IMG="$(cd "$(dirname "$0")/../.." && pwd)/$IMG" ;; esac
Xvfb $D -screen 0 1600x1000x24 >/dev/null 2>&1 & XP=$!
sleep 1; DISPLAY=$D xfwm4 --replace --compositor=off >/dev/null 2>&1 & WP=$!
sleep 1
cat > /tmp/pp_open_panel.py <<PY
import importlib.util, os, sys
from gi.repository import Gimp, Gio, GLib, Gtk, GimpUi
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("$IMG"))
Gimp.Display.new(img)
d = os.path.join(os.environ["GIMP3_DIRECTORY"], "plug-ins", "portrait_panel")
sys.path.insert(0, d)
spec = importlib.util.spec_from_file_location("pp", os.path.join(d, "portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
GimpUi.init(pp.PROC)
srv = pp.claim_instance()
panel = pp.Panel(img)
GLib.timeout_add(300, lambda: (pp.poll_instance(srv, panel._raise_panel), True)[1])
def _close():
    panel.on_close()
    return False
GLib.timeout_add(2500, _close)
try:
    Gtk.main()
    print("PANEL returned SUCCESS", flush=True)
except Exception as e:
    print("PANEL returned ERROR", e, flush=True)
finally:
    if srv is not None:
        pp.release_instance(srv)
PY
rm -f /tmp/pp_gui_close.log
DISPLAY=$D gimp-3.0 --batch-interpreter=python-fu-eval -b "exec(open('/tmp/pp_open_panel.py').read())" >/tmp/pp_gui_close.log 2>&1 &
G=$!
for i in $(seq 90); do
  grep -q "PANEL returned" /tmp/pp_gui_close.log && break
  sleep 1
done
if kill -0 $G 2>/dev/null; then echo "GIMP alive"; else echo "GIMP gone"; kill $WP $XP 2>/dev/null; exit 1; fi
if ! grep -q "PANEL returned SUCCESS" /tmp/pp_gui_close.log; then
  echo "panel close did not finish cleanly"
  grep -E "PANEL returned|Error|Traceback" /tmp/pp_gui_close.log | head -5
  kill $G $WP $XP 2>/dev/null; exit 1
fi
echo "panel returned: $(grep 'PANEL returned' /tmp/pp_gui_close.log | head -1)"
for i in $(seq 20); do
  ls /tmp/gimp-portrait-panel-*-$G.lock 2>/dev/null || break
  sleep 0.5
done
if ls /tmp/gimp-portrait-panel-*-$G.lock 2>/dev/null; then
  echo "lock left"; kill $G $WP $XP 2>/dev/null; exit 1
fi
echo "lock removed"
kill $G $WP $XP 2>/dev/null; echo "GUI CLOSE OK"
