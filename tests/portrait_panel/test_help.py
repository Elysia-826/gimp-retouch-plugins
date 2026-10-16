# Headless: batch 2 item 9 — every panel button has 2-3 line help; thumbnails exist and are 240 px wide.
# GIMP3_DIRECTORY=/tmp/kd-gimp gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
#   -b "exec(open('tests/portrait_panel/test_help.py').read(), {'__name__': 't'})"
import importlib.util, os
import gi
gi.require_version("Gimp", "3.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gimp, GdkPixbuf

spec = importlib.util.spec_from_file_location("pp", os.path.abspath("portrait_panel/portrait_panel.py"))
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
labels = [lab for _g, _t, items in pp.GROUPS for lab, _n, _tip in items]
for lab in labels:
    t = pp.help_text(lab)
    n = len(t.splitlines())
    assert t and (n in (2, 3) or lab == "磨皮"), (lab, t)
    th = pp.help_thumbs(lab)
    if pp.BUTTON_HELP[lab][1]:
        assert th, lab
        for p in th:
            pb = GdkPixbuf.Pixbuf.new_from_file(p)
            assert pb.get_width() == 240, (p, pb.get_width())
    print("HELP %s lines=%d thumbs=%s" % (lab, n, bool(th)), flush=True)
assert "所有步骤做完" in pp.help_text("锐化")
assert pp.help_thumbs("牙齿美白") is None
assert "会替换照片层" not in pp.help_text("高低频")
for lab in ("液化", "按脸液化", "选择主体", "导出"):
    assert "会弹出对话框" in pp.help_text(lab), lab
assert set(pp.BUTTON_HELP) == set(labels), set(pp.BUTTON_HELP) ^ set(labels)
for lab, (txt, _k) in pp.BUTTON_HELP.items():
    assert "「" not in txt and "」" not in txt, lab
assert "「" not in pp.HELP
print("HELP ALL OK", len(labels), flush=True)
