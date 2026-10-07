import os
from gi.repository import Gimp, Gio
src=os.environ.get("DNB_IN","/workspace/fs_test.png"); out=os.environ.get("DNB_OUT","/tmp/dnb")
pdb=Gimp.get_pdb()
for blend in ("soft-light","overlay"):
    img=Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
    lay=img.get_layers()[0]
    p=pdb.lookup_procedure("python-fu-dnb-setup"); c=p.create_config()
    c.set_property("run-mode",Gimp.RunMode.NONINTERACTIVE); c.set_property("image",img)
    c.set_core_object_array("drawables",[lay])
    c.set_property("blend-mode",blend); c.set_property("contrast-boost",True)
    r=p.run(c); print("STATUS",blend,r.index(0))
    def dump(ls,d=0):
        for l in ls:
            print("LAYER","  "*d+l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden", "%.0f"%l.get_opacity())
            if l.is_group(): dump(l.get_children(),d+1)
    dump(img.get_layers())
    print("SEL",[l.get_name() for l in img.get_selected_layers()])
    print("FG",Gimp.context_get_foreground().get_rgba(),"BG",Gimp.context_get_background().get_rgba())
    if os.environ.get("HELPER"): img.get_layers()[0].get_children()[0].set_visible(True)
    img.flatten(); Gimp.file_save(Gimp.RunMode.NONINTERACTIVE,img,Gio.File.new_for_path(out+"_"+blend+".png"))
