# 批量导出 / Batch Export (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 修图工具 > 批量导出 / Batch Export** (works with no image open)
PDB name: `python-fu-batch-export`

Takes every `.jpg/.jpeg/.png/.tif/.tiff/.xcf` in the input folder (not recursive; other files are ignored). For each file:
load → merge visible layers (XCF groups, FS/D&B blend modes and masks are composited like GIMP's own flatten) →
convert to sRGB if the embedded profile isn't sRGB → resize long side → unsharp mask → optional text watermark → export.

| Argument | Default | Notes |
|---|---|---|
| `input-folder` (GFile) | — | |
| `output-folder` (GFile) | — | must exist (CLI driver creates it) |
| `formats` | `jpeg` | comma list of `jpeg,webp,png` |
| `long-side` | 0 | px, 0 = keep size; LoHalo for downscale, cubic for upscale |
| `usm-amount` / `usm-radius` | 0.3 / 0.8 | gentle GEGL `gegl:unsharp-mask` (keeps skin texture); amount 0 = off |
| `jpeg-quality` | 92 | progressive + optimized |
| `webp-quality` | 90 | lossy |
| `watermark` / `watermark-text` / `watermark-opacity` | off / `© Elysia` / 50 | white Sans text, bottom-right, 2.5% of long side |
| `convert-srgb` | on | perceptual intent + BPC |
| `keep-exif` | on | EXIF/XMP/IPTC; off strips all metadata. ICC (sRGB) is always embedded |
| `suffix` | `_web` | `name<suffix>.<ext>` |
| `overwrite` | off | existing outputs are skipped unless this is on |

Safety and errors:
- **Inputs are never overwritten.** An output path that matches any input file is always skipped, even with `overwrite`.
- If two inputs share a stem (`a.jpg` and `a.png`), the second one's outputs are skipped as "exists" unless overwrite is on.
- Each file is handled on its own. Failures are logged and the batch continues. Log: stderr lines `[batch-export] ...` and `<output>/batch_export.log`.
- Returns **EXECUTION_ERROR** if there are no input files, or if every input file failed. Skips don't count as failures.
- PNG/WebP keep alpha only if the source (bottom layer) has alpha. Otherwise, and always for JPEG, the image is flattened onto white.

## Headless CLI (for bots)
`cli_run.py` maps env vars `BE_<ARG>` (upper case, `-`→`_`) onto the procedure arguments and prints
`BATCH_EXPORT_STATUS=success|execution-error|calling-error` (plus `BATCH_EXPORT_ERROR=...`).

GIMP 3.0 (apt):
```bash
BE_INPUT_FOLDER=~/photos/in BE_OUTPUT_FOLDER=~/photos/out BE_FORMATS=jpeg,webp BE_LONG_SIDE=2048 \
gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
  -b "exec(open('$HOME/.config/GIMP/3.0/plug-ins/batch_export/cli_run.py').read())"
```
GIMP 3.2 (Flatpak — paths must be inside $HOME; `/tmp` and `/workspace` aren't visible in the sandbox):
```bash
flatpak run --env=BE_INPUT_FOLDER=$HOME/photos/in --env=BE_OUTPUT_FOLDER=$HOME/photos/out \
  --env=BE_FORMATS=jpeg,webp --env=BE_LONG_SIDE=2048 \
  --command=gimp-console-3.2 org.gimp.GIMP -i --quit --batch-interpreter=python-fu-eval \
  -b "exec(open('$HOME/.config/GIMP/3.2/plug-ins/batch_export/cli_run.py').read())"
```
Check the `BATCH_EXPORT_STATUS=` line (gimp-console's own exit code doesn't reflect the procedure status).
Other options: `BE_USM_AMOUNT=0`, `BE_JPEG_QUALITY=95`, `BE_WATERMARK=1 BE_WATERMARK_TEXT="© me"`, `BE_KEEP_EXIF=0`,
`BE_SUFFIX=` (empty), `BE_OVERWRITE=1`.

Tests: `test_batch.sh 3.0|3.2 <root>` (needs `in/`, `allbad/`, `in.md5`, `retouch_ref.png`) + `verify.py`.
