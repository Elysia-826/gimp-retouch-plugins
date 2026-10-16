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
assert "更新锐化" in pp.help_text("涂抹锐化")
assert pp.help_thumbs("牙齿美白") is None
assert "会替换照片层" not in pp.help_text("高低频")
for lab in ("手动液化", "脸型微调", "选择主体", "导出图片", "设好笔刷"):
    assert "打开对话框" in pp.help_text(lab), lab
# rename table + Elysia's overrides
assert [t for _g, t, _i in pp.GROUPS] == ["第一步", "皮肤", "五官和脸型", "小工具", "收尾"]
for keep in ("高低频", "眼部修饰", "牙齿美白", "卧蚕压色", "选择主体", "去油光", "磨皮", "一键锐化", "更新锐化"):
    assert keep in labels, keep
for old in ("开始修这张", "去除瑕疵", "加深减淡", "轻柔涂抹", "皮肤减红", "统一肤色", "按脸液化", "液化", "人像笔刷",
            "看看涂到哪了", "看涂到哪", "涂擦切换", "播放动作", "锐化", "导出", "分开颜色纹理", "亮眼", "白牙", "淡化眼下", "选出人物"):
    assert old not in labels, old
assert "显示涂抹范围" in labels and "涂/擦切换" in labels
assert [l for l, _n, _t in pp.GROUPS[-1][2]][-1] == "导出图片"
assert "“涂抹锐化”的 ⚙" in pp.help_text("一键锐化")
# help/messages must only reference button names that exist
import re as _re
allt = pp.HELP + "".join(t for t, _k in pp.BUTTON_HELP.values())
for gone in ("分开颜色纹理", "选出人物", "“亮眼”", "“白牙”", "淡化眼下", "开始修这张", "“锐化”旁边"):
    assert gone not in allt, gone
assert set(pp.BUTTON_HELP) == set(labels), set(pp.BUTTON_HELP) ^ set(labels)
for lab, (txt, _k) in pp.BUTTON_HELP.items():
    assert "「" not in txt and "」" not in txt, lab
assert "「" not in pp.HELP
# single instance: live panel answers a ping, a stale lock is ignored and overwritten
import tempfile, threading, time
lk = os.path.join(tempfile.mkdtemp(), "pp.lock")
assert not pp.ping_existing(lk)                       # no lock
srv = pp.claim_instance(lk); hits = []; res = []
th = threading.Thread(target=lambda: res.append(pp.ping_existing(lk))); th.start()
for _ in range(50):
    pp.poll_instance(srv, lambda: hits.append(1))
    if hits: break
    time.sleep(0.05)
th.join(); assert res == [True] and hits == [1], (res, hits)
pp.release_instance(srv, lk); assert not os.path.exists(lk)
open(lk, "w").write("1 999999\n")                     # stale lock (dead port)
assert not pp.ping_existing(lk)
srv = pp.claim_instance(lk); assert int(open(lk).read().split()[0]) == srv.getsockname()[1]
pp.release_instance(srv, lk)
# lock is per running GIMP: another GIMP (different parent pid) gets its own lock and is not blocked
assert pp.lock_path_for(111) != pp.lock_path_for(222)
assert pp.LOCK_PATH == pp.lock_path_for(os.getppid()) and str(os.getppid()) in pp.LOCK_PATH
lk1, lk2 = pp.lock_path_for(10 ** 9 + 1), pp.lock_path_for(10 ** 9 + 2)
srv = pp.claim_instance(lk1)
assert not pp.ping_existing(lk2)                     # panel in "other GIMP" does not block this one
pp.release_instance(srv, lk1)
print("SINGLE INSTANCE OK", flush=True)
assert "“提亮”" in pp.help_text("提亮压暗")
print("HELP ALL OK", len(labels), flush=True)
