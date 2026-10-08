#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 批量导出 / Batch Export  (GIMP 3.0.x and 3.2.x)
import os, sys, time, traceback, gi
gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, GimpUi, GObject, GLib, Gegl, Gio

PROC = "python-fu-batch-export"
IN_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".xcf"}
FMT = {"jpeg": (".jpg", "file-jpeg-export"), "webp": (".webp", "file-webp-export"),
       "png": (".png", "file-png-export")}

def _pdb_run(name, **kw):
    proc = Gimp.get_pdb().lookup_procedure(name)
    if proc is None:
        raise RuntimeError("procedure not found: " + name)
    cfg = proc.create_config()
    names = {a.get_name() for a in proc.get_arguments()}
    for k, v in kw.items():
        if k in names:
            cfg.set_property(k, v)
    res = proc.run(cfg)
    if res.index(0) != Gimp.PDBStatusType.SUCCESS:
        err = res.index(1) if res.length() > 1 else ""
        raise RuntimeError("%s failed: %s" % (name, err))
    return res

def _unsharp(drawable, radius, amount, threshold=0.0):
    Gegl.init(None)
    src_buf = drawable.get_buffer(); dst_buf = drawable.get_shadow_buffer()
    g = Gegl.Node()
    s = g.create_child("gegl:buffer-source"); s.set_property("buffer", src_buf)
    u = g.create_child("gegl:unsharp-mask")
    u.set_property("std-dev", float(radius)); u.set_property("scale", float(amount))
    u.set_property("threshold", float(threshold))
    d = g.create_child("gegl:write-buffer"); d.set_property("buffer", dst_buf)
    s.link(u); u.link(d); d.process(); dst_buf.flush()
    drawable.merge_shadow(True)
    drawable.update(0, 0, drawable.get_width(), drawable.get_height())

POSITIONS = ["top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"]

def _anchor(pos, W, H, w, h, m):
    r = 0 if pos.startswith("top") else (2 if pos.startswith("bottom") else 1)
    c = 0 if pos.endswith("left") else (2 if pos.endswith("right") else 1)
    x = [m, (W - w) // 2, W - w - m][c]
    y = [m, (H - h) // 2, H - h - m][r]
    return max(0, int(x)), max(0, int(y)), r

_FONT_CACHE = {}
def _font(name, warn):
    if name not in _FONT_CACHE:
        f = Gimp.Font.get_by_name(name) if name else None
        if f is None:
            warn("WARN font '%s' not found, using Sans-serif / 字体不存在，改用 Sans-serif" % name)
            f = Gimp.Font.get_by_name("Sans-serif") or Gimp.context_get_font()
        _FONT_CACHE[name] = f
    return _FONT_CACHE[name]

def _parse_color(s):
    c = Gegl.Color.new(s or "white")
    return c

def _watermark(image, o, warn):
    """Text and/or PNG logo watermark at a 9-grid position. Returns nothing; adds layers on top."""
    W, H = image.get_width(), image.get_height()
    L = max(W, H)
    m = int(round(L * o["wm_margin"] / 100.0))
    pos = o["wm_position"] if o["wm_position"] in POSITIONS else "bottom-right"
    items = []
    if o["wm_logo"]:
        logo_img = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(o["wm_logo"]))
        if logo_img is None:
            raise RuntimeError("logo load failed: " + o["wm_logo"])
        try:
            src = logo_img.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE) if len(logo_img.get_layers()) > 1 else logo_img.get_layers()[0]
            lay = Gimp.Layer.new_from_drawable(src, image)
        finally:
            logo_img.delete()
        image.insert_layer(lay, None, 0)
        lw, lh = lay.get_width(), lay.get_height()
        k = (L * o["wm_logo_scale"] / 100.0) / float(max(lw, lh))
        Gimp.context_set_interpolation(Gimp.InterpolationType.LOHALO if k < 1 else Gimp.InterpolationType.CUBIC)
        lay.scale(max(1, round(lw * k)), max(1, round(lh * k)), False)
        items.append(lay)
    if o["wm_text"]:
        size = max(6.0, round(L * o["wm_size"] / 100.0))
        tl = Gimp.TextLayer.new(image, o["wm_text"], _font(o["wm_font"], warn), size, Gimp.Unit.pixel())
        if tl is None:
            raise RuntimeError("text layer failed")
        image.insert_layer(tl, None, 0)
        tl.set_color(_parse_color(o["wm_color"]))
        items.append(tl)
    if not items:
        return
    gap = m // 2 if len(items) > 1 else 0
    bw = max(i.get_width() for i in items)
    bh = sum(i.get_height() for i in items) + gap * (len(items) - 1)
    bx, by, _ = _anchor(pos, W, H, bw, bh, m)
    y = by
    for it in items:          # stack logo above text, aligned like the block
        iw = it.get_width()
        if pos.endswith("left"): x = bx
        elif pos.endswith("right"): x = bx + bw - iw
        else: x = bx + (bw - iw) // 2
        it.set_offsets(int(x), int(y)); it.set_opacity(float(o["wm_opacity"]))
        y += it.get_height() + gap

def _process_one(path, out_paths, o):
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    if image is None:
        raise RuntimeError("load failed")
    try:
        # remember whether the source is really transparent (bottom layer alpha)
        src_alpha = image.get_layers()[-1].has_alpha()
        # flatten all (XCF groups/modes preserved in composite); keep alpha for png/webp later
        if len(image.get_layers()) > 1 or image.get_layers()[0].is_group() or o["flatten"]:
            image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        # sRGB
        if o["srgb"] and image.get_base_type() == Gimp.ImageBaseType.RGB:
            prof = image.get_color_profile()
            srgb = Gimp.ColorProfile.new_rgb_srgb()
            if prof is not None and not prof.is_equal(srgb):
                if not image.convert_color_profile(srgb, Gimp.ColorRenderingIntent.PERCEPTUAL, True):
                    raise RuntimeError("sRGB conversion failed")
        # resize long side
        ls = o["long_side"]
        w, h = image.get_width(), image.get_height()
        if ls > 0 and max(w, h) != ls and (max(w, h) > ls or o.get("upscale")):
            k = ls / float(max(w, h))
            Gimp.context_set_interpolation(Gimp.InterpolationType.LOHALO if k < 1 else Gimp.InterpolationType.CUBIC)
            image.scale(max(1, round(w * k)), max(1, round(h * k)))
        layer = image.get_layers()[0]
        if o["usm_amount"] > 0 and o["usm_radius"] > 0:
            _unsharp(layer, o["usm_radius"], o["usm_amount"])
        if o["wm_text"] or o["wm_logo"]:
            _watermark(image, o, o["_warn"])
            image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        for fmt, outp in out_paths:
            exp = image.duplicate()
            try:
                if fmt == "jpeg" or not src_alpha:
                    exp.flatten()          # opaque output (white bg) unless source has alpha
                if o["bit_depth"] == "8" and fmt in ("png", "webp"):
                    if exp.get_precision() != Gimp.Precision.U8_NON_LINEAR:
                        exp.convert_precision(Gimp.Precision.U8_NON_LINEAR)
                kw = {"run-mode": Gimp.RunMode.NONINTERACTIVE, "image": exp,
                      "file": Gio.File.new_for_path(outp),
                      "include-exif": o["keep_exif"], "include-xmp": o["keep_exif"],
                      "include-iptc": o["keep_exif"], "include-thumbnail": False,
                      "include-color-profile": True}
                if fmt == "jpeg":
                    kw.update({"quality": o["jpeg_q"] / 100.0, "optimize": True, "progressive": True})
                elif fmt == "webp":
                    kw.update({"quality": float(o["webp_q"]), "lossless": False})
                else:
                    kw.update({"compression": 9})
                if not o["keep_exif"]:
                    exp.set_metadata(Gimp.Metadata.new()) if hasattr(Gimp, "Metadata") else None
                _pdb_run(FMT[fmt][1], **kw)
            finally:
                exp.delete()
    finally:
        image.delete()

def _real(p):
    return os.path.normcase(os.path.realpath(p))

def _collect(o, log):
    """Return list of (src_path, rel_dir) and the set of all input realpaths."""
    outdir_r = _real(o["outdir"])
    items = []
    if o["file_list"]:
        base = os.path.dirname(os.path.abspath(o["file_list"]))
        indir_r = _real(o["indir"]) if o["indir"] else None
        with open(o["file_list"], encoding="utf-8") as fh:
            for line in fh:
                p = line.strip()
                if not p or p.startswith("#"):
                    continue
                p = os.path.expanduser(p)
                if not os.path.isabs(p):
                    p = os.path.join(base, p)
                rel = ""
                if indir_r and _real(p).startswith(indir_r + os.sep):
                    rel = os.path.dirname(os.path.relpath(_real(p), indir_r))
                items.append((p, rel))
    else:
        indir = o["indir"]
        if not indir or not os.path.isdir(indir):
            raise RuntimeError("input folder not found / 输入文件夹不存在: %s" % indir)
        if o["recursive"]:
            for root, dirs, files in os.walk(indir):
                # never descend into the output folder (when it lives inside the input folder)
                dirs[:] = sorted(d for d in dirs if _real(os.path.join(root, d)) != outdir_r)
                rel = os.path.relpath(root, indir)
                for f in sorted(files):
                    items.append((os.path.join(root, f), "" if rel == "." else rel))
        else:
            for f in sorted(os.listdir(indir)):
                if os.path.isfile(os.path.join(indir, f)):
                    items.append((os.path.join(indir, f), ""))
    keep = []
    for p, rel in items:
        if os.path.splitext(p)[1].lower() in IN_EXT:
            keep.append((p, rel))
        elif o["file_list"]:
            log("SKIP %s: unsupported type / 不支持的类型" % p)
    return keep

def _plan(o, items, fmts, log):
    """Assign output paths. Pre-existing outputs are detected here, before anything is written."""
    inputs = {_real(p) for p, _ in items if os.path.exists(p)}
    def name(p, with_ext):
        stem, ext = os.path.splitext(os.path.basename(p))
        return stem + (("_" + ext[1:].lower()) if with_ext else "") + o["suffix"]
    # on-collision: find base names claimed by more than one input in the same output dir
    claims = {}
    for p, rel in items:
        for fmt in fmts:
            key = _real(os.path.join(o["outdir"], rel, name(p, False) + FMT[fmt][0]))
            claims.setdefault(key, set()).add(_real(p))
    taken = set()
    plan = []
    for p, rel in items:
        outs = []
        for fmt in fmts:
            ext = FMT[fmt][0]
            plain = os.path.join(o["outdir"], rel, name(p, False) + ext)
            with_ext = (o["naming"] == "always" or len(claims[_real(plain)]) > 1
                        or _real(plain) in inputs)          # plain name would hit an input -> add ext
            cand = os.path.join(o["outdir"], rel, name(p, with_ext) + ext)
            n = 2
            while _real(cand) in taken:            # same-run duplicates (e.g. a.JPG + a.jpg)
                cand = os.path.join(o["outdir"], rel, "%s_%d%s" % (name(p, with_ext), n, ext)); n += 1
            if _real(cand) in inputs or _real(cand) == _real(p):
                log("SKIP %s -> %s: would overwrite an input / 会覆盖输入文件" % (p, cand)); continue
            taken.add(_real(cand))
            if os.path.exists(cand) and not o["overwrite"]:
                log("SKIP %s -> %s: exists (pre-existing) / 已存在" % (p, cand)); continue
            outs.append((fmt, cand))
        plan.append((p, outs))
    return plan, inputs

def batch(o, log):
    if not o["outdir"]:
        raise RuntimeError("output folder not set / 未设置输出文件夹")
    os.makedirs(o["outdir"], exist_ok=True)
    fmts = []
    for f in o["formats"].split(","):
        f = f.strip().lower().replace("jpg", "jpeg")
        if f and f not in fmts:
            fmts.append(f)
    bad = [f for f in fmts if f not in FMT]
    if not fmts or bad:
        raise RuntimeError("bad formats / 格式错误: %s (use jpeg,webp,png)" % o["formats"])
    if o["wm_logo"] and not os.path.isfile(o["wm_logo"]):
        raise RuntimeError("logo file not found / 水印 logo 不存在: %s" % o["wm_logo"])
    items = _collect(o, log)
    plan, inputs = _plan(o, items, fmts, log)
    ok = fail = skip = 0
    for src, outs in plan:
        f = src
        if not outs:
            skip += 1; continue
        if not os.path.isfile(src):
            fail += 1; log("FAIL %s: not found / 文件不存在" % src); continue
        try:
            t = time.time()
            for _, p in outs:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                if _real(p) in inputs:                       # hard check (belt and braces)
                    raise RuntimeError("refusing to overwrite input " + p)
            _process_one(src, outs, o)
            ok += 1
            log("OK   %s -> %s (%.1fs)" % (f, ", ".join(os.path.relpath(p, o["outdir"]) for _, p in outs), time.time() - t))
        except Exception as e:
            fail += 1
            log("FAIL %s: %s" % (f, e))
    log("DONE ok=%d failed=%d skipped=%d total=%d" % (ok, fail, skip, len(plan)))
    return ok, fail, skip, len(plan)

def _opts(config):
    g = config.get_property
    def path(name):
        f = g(name); return f.get_path() if f is not None and f.get_path() else ""
    return dict(indir=path("input-folder"), outdir=path("output-folder"), file_list=path("file-list"),
                recursive=g("recursive"), naming=g("naming"), formats=g("formats"),
                long_side=g("long-side"), upscale=g("upscale"), usm_amount=g("usm-amount"), usm_radius=g("usm-radius"),
                jpeg_q=g("jpeg-quality"), webp_q=g("webp-quality"),
                wm_text=g("watermark-text") if g("watermark") else "", wm_logo=path("watermark-logo"),
                wm_opacity=g("watermark-opacity"), wm_font=g("watermark-font"), wm_size=g("watermark-size"),
                wm_color=g("watermark-color"), wm_position=g("watermark-position"), wm_margin=g("watermark-margin"),
                wm_logo_scale=g("watermark-logo-scale"), bit_depth=g("bit-depth"),
                flatten=True, srgb=g("convert-srgb"),
                keep_exif=g("keep-exif"), suffix=g("suffix"), overwrite=g("overwrite"))

def run(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "批量导出 / Batch Export")
        dlg.fill(None)          # all arguments (incl. new watermark/naming/recursive options)
        ok = dlg.run(); dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    o = _opts(config)
    lines = []
    def log(msg):
        lines.append(msg); print("[batch-export] " + msg, file=sys.stderr, flush=True)
    o["_warn"] = log
    _FONT_CACHE.clear()
    Gimp.context_push()
    try:
        Gimp.context_set_background(Gegl.Color.new("white"))
        ok, fail, skip, total = batch(o, log)
    except Exception as e:
        Gimp.context_pop()
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    Gimp.context_pop()
    try:
        if not o["outdir"]:
            raise OSError
        with open(os.path.join(o["outdir"], "batch_export.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("# %Y-%m-%d %H:%M:%S\n") + "\n".join(lines) + "\n")
    except OSError:
        pass
    if run_mode == Gimp.RunMode.INTERACTIVE:
        Gimp.message("批量导出完成 / Batch export: ok=%d failed=%d skipped=%d" % (ok, fail, skip))
    if total == 0:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error("no input files / 没有可处理的文件"))
    if fail > 0 and fail == total:          # every input failed (skips are not failures)
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error("all files failed / 全部失败 (%d)" % fail))
    rv = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    return rv

class BatchExport(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False
    def do_query_procedures(self):
        return [PROC]
    def do_create_procedure(self, name):
        F = GObject.ParamFlags.READWRITE
        p = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        p.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS | Gimp.ProcedureSensitivityMask.NO_IMAGE)
        p.set_menu_label("批量导出 / Batch Export")
        p.add_menu_path("<Image>/Filters/修图工具/")
        p.set_documentation("Batch export a folder (jpg/png/tif/xcf) to JPEG/WebP/PNG with resize, gentle sharpening, sRGB, watermark. 批量导出。",
                            "Never overwrites inputs; existing outputs are skipped unless overwrite is on. Log: <output>/batch_export.log", name)
        p.set_attribution("Elysia", "Elysia", "2026")
        p.add_file_argument("input-folder", "Input folder / 输入文件夹", None,
                            Gimp.FileChooserAction.SELECT_FOLDER, True, None, F)
        p.add_file_argument("output-folder", "Output folder / 输出文件夹", None,
                            Gimp.FileChooserAction.CREATE_FOLDER, True, None, F)
        p.add_boolean_argument("recursive", "Include subfolders / 包含子文件夹", "Mirror subfolders into the output folder", False, F)
        p.add_file_argument("file-list", "File list (optional) / 文件清单", "Text file, one path per line; overrides folder scan",
                            Gimp.FileChooserAction.OPEN, True, None, F)
        p.add_string_argument("formats", "Formats / 格式 (jpeg,webp,png)", "Comma-separated", "jpeg", F)
        nm = Gimp.Choice.new()
        nm.add("always", 0, "Always include source extension / 总是包含原扩展名 (a_jpg_web.jpg)", "")
        nm.add("on-collision", 1, "Only on name collision / 仅在重名时 (a_web.jpg)", "")
        p.add_choice_argument("naming", "Naming / 命名", None, nm, "always", F)
        p.add_string_argument("suffix", "Filename suffix / 文件名后缀", None, "_web", F)
        p.add_boolean_argument("overwrite", "Overwrite pre-existing outputs / 覆盖已有输出", None, False, F)
        p.add_int_argument("long-side", "Long side px / 长边 (0=keep)", "Only shrinks larger images unless 'upscale' is on", 0, 30000, 0, F)
        p.add_boolean_argument("upscale", "Enlarge smaller images / 放大较小图片", "Off: images smaller than long-side keep their size", False, F)
        p.add_double_argument("usm-amount", "Sharpen amount / 锐化量 (0=off)", "Unsharp mask scale", 0.0, 5.0, 0.3, F)
        p.add_double_argument("usm-radius", "Sharpen radius / 锐化半径", "Unsharp mask std-dev px", 0.0, 10.0, 0.8, F)
        p.add_int_argument("jpeg-quality", "JPEG quality / 质量", None, 1, 100, 92, F)
        p.add_int_argument("webp-quality", "WebP quality / 质量", None, 1, 100, 90, F)
        bd = Gimp.Choice.new()
        bd.add("keep", 0, "Keep / 保持", "")
        bd.add("8", 1, "8-bit", "")
        p.add_choice_argument("bit-depth", "PNG/WebP bit depth / 位深", "JPEG is always 8-bit", bd, "keep", F)
        p.add_boolean_argument("convert-srgb", "Convert to sRGB / 转换为sRGB", None, True, F)
        p.add_boolean_argument("keep-exif", "Keep EXIF/XMP / 保留元数据", None, True, F)
        p.add_boolean_argument("watermark", "Text watermark / 文字水印", None, False, F)
        p.add_string_argument("watermark-text", "Watermark text / 水印文字", None, "© Elysia", F)
        p.add_string_argument("watermark-font", "Watermark font / 字体", "Missing font -> Sans-serif + warning", "Sans-serif", F)
        p.add_double_argument("watermark-size", "Text size % of long side / 字号(长边%)", None, 0.2, 30.0, 2.5, F)
        p.add_string_argument("watermark-color", "Text color / 颜色", "CSS color, e.g. white or #ffcc00", "white", F)
        ps = Gimp.Choice.new()
        for i, k in enumerate(POSITIONS):
            ps.add(k, i, k, "")
        p.add_choice_argument("watermark-position", "Position / 位置 (9-grid)", None, ps, "bottom-right", F)
        p.add_double_argument("watermark-margin", "Margin % of long side / 边距(长边%)", None, 0.0, 30.0, 2.5, F)
        p.add_double_argument("watermark-opacity", "Watermark opacity / 水印不透明度", None, 0.0, 100.0, 50.0, F)
        p.add_file_argument("watermark-logo", "Logo PNG (optional) / 水印 Logo", "Uses position/opacity/margin; independent of text watermark",
                            Gimp.FileChooserAction.OPEN, True, None, F)
        p.add_double_argument("watermark-logo-scale", "Logo size % of long side / Logo 大小(长边%)", None, 0.5, 100.0, 15.0, F)
        return p

Gimp.main(BatchExport.__gtype__, sys.argv)
