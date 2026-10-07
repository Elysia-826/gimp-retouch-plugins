# python-fu-eval combined test. env: T_IN (png), T_OUT (prefix)
import os
from gi.repository import Gimp, Gio
src=os.environ.get("T_IN","/workspace/fs_test.png"); out=os.environ.get("T_OUT","/tmp/comb")
pdb=Gimp.get_pdb()
def st(r):
    v=r.index(0); return getattr(v,"value_nick",v)
def call(name, img, drs, **kw):
    p=pdb.lookup_procedure(name); c=p.create_config()
    c.set_property("run-mode",Gimp.RunMode.NONINTERACTIVE); c.set_property("image",img)
    c.set_core_object_array("drawables",drs)
    for k,v in kw.items(): c.set_property(k,v)
    return p.run(c)
def dump(ls,d=0):
    for l in ls:
        print("LAYER","  "*d+l.get_name(), l.get_mode().value_nick, "vis" if l.get_visible() else "hidden",
              "alpha" if l.has_alpha() else "noalpha", "group" if l.is_group() else "")
        if l.is_group(): dump(l.get_children(),d+1)
def load():
    return Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(src))
for alpha in (False, True):
    img=load(); lay=img.get_layers()[0]
    if alpha: lay.add_alpha()
    print("=== source alpha", alpha, "auto-radius case")
    print("FSEP", st(call("python-fu-fsep-oneclick", img, [lay], radius=0.0)))
    grp=img.get_layers()[0]; high,low=grp.get_children()
    print("ALPHA high/low", high.has_alpha(), low.has_alpha())
    img.select_ellipse(Gimp.ChannelOps.REPLACE, 300, 250, 30, 30)
    print("HEAL", st(call("plug-in-heal-selection", img, [high])))
    Gimp.Selection.none(img)
    img.set_selected_layers([grp])
    print("DNB_on_group", st(call("python-fu-dnb-setup", img, [grp], **{"contrast-boost":True})))
    print("DNB_on_top", st(call("python-fu-dnb-setup", img, [img.get_layers()[-1]], **{"place-on-top":True,"contrast-boost":True})))
    dump(img.get_layers())
    if not alpha:
        d=img.duplicate(); d.flatten()
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE,d,Gio.File.new_for_path(out+"_flat.png"))
# error path
img=load()
r=call("python-fu-dnb-setup", img, []); print("DNB_empty", st(r))
print("FSEP_empty", st(call("python-fu-fsep-oneclick", img, [])))
img2=Gimp.Image.new(1000,4608,Gimp.ImageBaseType.RGB); print("AUTO_R_4608 expect", round(6*4608/4000,1))
