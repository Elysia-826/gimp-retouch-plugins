# run via python-fu-eval; env FS_OUT sets output prefix
import os
from gi.repository import Gimp, Gio
out=os.environ.get("FS_OUT","/tmp/fs")
pdb=Gimp.get_pdb()
g=None
print("GAUSS", pdb.lookup_procedure("plug-in-gauss"))
img=Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path("/workspace/fs_test.png"))
lay=img.get_layers()[0]
p=pdb.lookup_procedure("python-fu-fsep-oneclick")
c=p.create_config()
c.set_property("run-mode",Gimp.RunMode.NONINTERACTIVE); c.set_property("image",img)
c.set_core_object_array("drawables",[lay]) if hasattr(c,"set_core_object_array") else c.set_property("drawables",Gimp.ObjectArray.new(Gimp.Drawable,[lay],False))
c.set_property("radius",4.0)
r=p.run(c); print("STATUS", r.index(0), r.index(1) if r.length()>1 else "")
def dump(ls,d=0):
    for l in ls:
        print("LAYER","  "*d+l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden")
        if l.is_group(): dump(l.get_children(),d+1)
dump(img.get_layers())
low=[l for l in img.get_layers()[0].get_children() if l.get_name().startswith("Low")][0]
d2=img.duplicate(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE,d2,Gio.File.new_for_path(out+"_low.png"))
img.flatten(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE,img,Gio.File.new_for_path(out+"_flat.png"))
