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

def _watermark(image, text, opacity):
    long_side = max(image.get_width(), image.get_height())
    size = max(10.0, round(long_side * 0.025))
    font = Gimp.Font.get_by_name("Sans-serif") or Gimp.context_get_font()
    tl = Gimp.TextLayer.new(image, text, font, size, Gimp.Unit.pixel())
    if tl is None:
        raise RuntimeError("text layer failed")
    image.insert_layer(tl, None, 0)
    tl.set_color(Gegl.Color.new("white"))
    tl.set_opacity(float(opacity))
    m = int(size)
    tl.set_offsets(max(0, image.get_width() - tl.get_width() - m),
                   max(0, image.get_height() - tl.get_height() - m))

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
        if ls > 0 and max(w, h) != ls:
            k = ls / float(max(w, h))
            Gimp.context_set_interpolation(Gimp.InterpolationType.LOHALO if k < 1 else Gimp.InterpolationType.CUBIC)
            image.scale(max(1, round(w * k)), max(1, round(h * k)))
        layer = image.get_layers()[0]
        if o["usm_amount"] > 0 and o["usm_radius"] > 0:
            _unsharp(layer, o["usm_radius"], o["usm_amount"])
        if o["wm_text"]:
            _watermark(image, o["wm_text"], o["wm_opacity"])
            image.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        for fmt, outp in out_paths:
            exp = image.duplicate()
            try:
                if fmt == "jpeg" or not src_alpha:
                    exp.flatten()          # opaque output (white bg) unless source has alpha
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

def batch(o, log):
    indir, outdir = o["indir"], o["outdir"]
    if not indir or not os.path.isdir(indir):
        raise RuntimeError("input folder not found / 输入文件夹不存在: %s" % indir)
    os.makedirs(outdir, exist_ok=True)
    fmts = [f.strip().lower().replace("jpg", "jpeg") for f in o["formats"].split(",") if f.strip()]
    bad = [f for f in fmts if f not in FMT]
    if not fmts or bad:
        raise RuntimeError("bad formats / 格式错误: %s (use jpeg,webp,png)" % o["formats"])
    files = sorted(f for f in os.listdir(indir)
                   if os.path.isfile(os.path.join(indir, f)) and os.path.splitext(f)[1].lower() in IN_EXT)
    inputs = {os.path.realpath(os.path.join(indir, f)) for f in files}
    ok = fail = skip = 0
    for f in files:
        src = os.path.join(indir, f)
        base = os.path.splitext(f)[0] + o["suffix"]
        outs = []
        for fmt in fmts:
            p = os.path.join(outdir, base + FMT[fmt][0])
            if os.path.realpath(p) in inputs:
                log("SKIP %s -> %s: would overwrite an input / 会覆盖输入文件" % (f, p)); continue
            if os.path.exists(p) and not o["overwrite"]:
                log("SKIP %s -> %s: exists / 已存在" % (f, p)); continue
            outs.append((fmt, p))
        if not outs:
            skip += 1; continue
        try:
            t = time.time()
            _process_one(src, outs, o)
            ok += 1
            log("OK   %s -> %s (%.1fs)" % (f, ", ".join(os.path.basename(p) for _, p in outs), time.time() - t))
        except Exception as e:
            fail += 1
            log("FAIL %s: %s" % (f, e))
    log("DONE ok=%d failed=%d skipped=%d total=%d" % (ok, fail, skip, len(files)))
    return ok, fail, skip, len(files)

def _opts(config):
    g = config.get_property
    def path(name):
        f = g(name); return f.get_path() if f is not None else ""
    return dict(indir=path("input-folder"), outdir=path("output-folder"), formats=g("formats"),
                long_side=g("long-side"), usm_amount=g("usm-amount"), usm_radius=g("usm-radius"),
                jpeg_q=g("jpeg-quality"), webp_q=g("webp-quality"), wm_text=g("watermark-text") if g("watermark") else "",
                wm_opacity=g("watermark-opacity"), flatten=True, srgb=g("convert-srgb"),
                keep_exif=g("keep-exif"), suffix=g("suffix"), overwrite=g("overwrite"))

def run(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        GimpUi.init(PROC)
        dlg = GimpUi.ProcedureDialog.new(procedure, config, "批量导出 / Batch Export")
        dlg.fill(None)
        ok = dlg.run(); dlg.destroy()
        if not ok:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    o = _opts(config)
    lines = []
    def log(msg):
        lines.append(msg); print("[batch-export] " + msg, file=sys.stderr, flush=True)
    Gimp.context_push()
    try:
        Gimp.context_set_background(Gegl.Color.new("white"))
        ok, fail, skip, total = batch(o, log)
    except Exception as e:
        Gimp.context_pop()
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))
    Gimp.context_pop()
    try:
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
        p.add_string_argument("formats", "Formats / 格式 (jpeg,webp,png)", "Comma-separated", "jpeg", F)
        p.add_int_argument("long-side", "Long side px / 长边 (0=keep)", None, 0, 30000, 0, F)
        p.add_double_argument("usm-amount", "Sharpen amount / 锐化量 (0=off)", "Unsharp mask scale", 0.0, 5.0, 0.3, F)
        p.add_double_argument("usm-radius", "Sharpen radius / 锐化半径", "Unsharp mask std-dev px", 0.0, 10.0, 0.8, F)
        p.add_int_argument("jpeg-quality", "JPEG quality / 质量", None, 1, 100, 92, F)
        p.add_int_argument("webp-quality", "WebP quality / 质量", None, 1, 100, 90, F)
        p.add_boolean_argument("watermark", "Watermark / 水印", None, False, F)
        p.add_string_argument("watermark-text", "Watermark text / 水印文字", None, "© Elysia", F)
        p.add_double_argument("watermark-opacity", "Watermark opacity / 水印不透明度", None, 0.0, 100.0, 50.0, F)
        p.add_boolean_argument("convert-srgb", "Convert to sRGB / 转换为sRGB", None, True, F)
        p.add_boolean_argument("keep-exif", "Keep EXIF/XMP / 保留元数据", None, True, F)
        p.add_string_argument("suffix", "Filename suffix / 文件名后缀", None, "_web", F)
        p.add_boolean_argument("overwrite", "Overwrite outputs / 覆盖已有输出", None, False, F)
        return p

Gimp.main(BatchExport.__gtype__, sys.argv)
