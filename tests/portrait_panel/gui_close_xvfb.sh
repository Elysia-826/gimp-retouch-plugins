#!/bin/sh
# GUI check on a private Xvfb display: open the panel, close it with the title-bar X (xfwm4),
# GIMP must keep running and the lock must be gone. Usage: sh tests/portrait_panel/gui_close_xvfb.sh [display]
D=${1:-:97}; export GIMP3_DIRECTORY=${GIMP3_DIRECTORY:-/tmp/kd-gimp}
Xvfb $D -screen 0 1600x1000x24 >/dev/null 2>&1 & XP=$!
sleep 1; DISPLAY=$D xfwm4 --replace --compositor=off >/dev/null 2>&1 & WP=$!
sleep 1
cat > /tmp/pp_open_panel.py <<PY
from gi.repository import Gimp, Gio
img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("${PP_TEST_IMAGE:-tests/data/astronaut.jpg}"))
Gimp.Display.new(img)
p = Gimp.get_pdb().lookup_procedure("python-fu-portrait-panel"); c = p.create_config()
c.set_property("run-mode", Gimp.RunMode.INTERACTIVE); c.set_property("image", img)
print("PANEL returned", p.run(c).index(0), flush=True)
PY
DISPLAY=$D gimp-3.0 --batch-interpreter=python-fu-eval -b "exec(open('/tmp/pp_open_panel.py').read())" >/tmp/pp_gui_close.log 2>&1 &
G=$!
for i in $(seq 60); do W=$(DISPLAY=$D xdotool search --name "^人像面板$" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep 1; done
[ -z "$W" ] && { echo "FAIL panel did not open"; kill $G $WP $XP; exit 1; }
sleep 3
eval $(DISPLAY=$D xdotool getwindowgeometry --shell $W)
# xfwm4 close button (client geom; offset measured on default theme), then Alt+F4
DISPLAY=$D xdotool windowactivate --sync $W
DISPLAY=$D xdotool mousemove $((X + WIDTH - 14)) $((Y - 44)) click 1
for i in $(seq 12); do
  grep -q "PANEL returned" /tmp/pp_gui_close.log && break
  sleep 1
done
if ! grep -q "PANEL returned" /tmp/pp_gui_close.log; then
  DISPLAY=$D xdotool windowactivate --sync $W 2>/dev/null
  DISPLAY=$D xdotool key --clearmodifiers alt+F4
  for i in $(seq 12); do
    grep -q "PANEL returned" /tmp/pp_gui_close.log && break
    sleep 1
  done
fi
if kill -0 $G 2>/dev/null; then echo "GIMP alive"; else echo "GIMP gone"; kill $WP $XP; exit 1; fi
if ! grep -q "PANEL returned" /tmp/pp_gui_close.log; then
  echo "panel still open"; kill $G $WP $XP 2>/dev/null; exit 1
fi
echo "panel returned: $(grep 'PANEL returned' /tmp/pp_gui_close.log)"
# wait for lock cleanup after orderly close
for i in $(seq 20); do
  ls /tmp/gimp-portrait-panel-*-$G.lock 2>/dev/null || break
  sleep 0.5
done
if ls /tmp/gimp-portrait-panel-*-$G.lock 2>/dev/null; then
  echo "lock left"; kill $G $WP $XP 2>/dev/null; exit 1
fi
echo "lock removed"
kill $G $WP $XP 2>/dev/null; echo "GUI CLOSE OK"
