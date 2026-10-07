# Headless driver for python-fu-batch-export (exec via python-fu-eval).
# Every procedure argument can be set with env BE_<NAME> (dashes -> underscores, upper case),
# e.g. BE_INPUT_FOLDER, BE_OUTPUT_FOLDER, BE_FORMATS=jpeg,webp, BE_LONG_SIDE=2048, BE_OVERWRITE=1.
# Prints "BATCH_EXPORT_STATUS=<success|execution-error|...>" and exits GIMP with code 0/1.
import os, sys
from gi.repository import Gimp, Gio, GObject
pdb = Gimp.get_pdb()
proc = pdb.lookup_procedure("python-fu-batch-export")
cfg = proc.create_config()
cfg.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
for spec in proc.get_arguments():
    n = spec.get_name(); v = os.environ.get("BE_" + n.upper().replace("-", "_"))
    if v is None or n in ("run-mode", "image", "drawables"):
        continue
    t = spec.value_type
    if t == Gio.File.__gtype__:
        if n == "output-folder": os.makedirs(os.path.abspath(v), exist_ok=True)  # GFile folder args must exist
        val = Gio.File.new_for_path(os.path.abspath(v))
    elif t == GObject.TYPE_BOOLEAN: val = v.lower() in ("1", "true", "yes", "on")
    elif t == GObject.TYPE_INT: val = int(v)
    elif t == GObject.TYPE_DOUBLE: val = float(v)
    else: val = v
    cfg.set_property(n, val)
res = proc.run(cfg)
st = res.index(0); nick = getattr(st, "value_nick", None) or Gimp.PDBStatusType(st).value_nick
print("BATCH_EXPORT_STATUS=" + nick, flush=True)
if nick != "success" and res.length() > 1: print("BATCH_EXPORT_ERROR=" + str(res.index(1)), flush=True)
