# 批量导出 / Batch Export (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 修图工具 > 批量导出 / Batch Export** (works with no image open)
PDB name: `python-fu-batch-export`

Input: every `.jpg/.jpeg/.png/.tif/.tiff/.xcf` in the input folder (optionally recursive), or the files listed in a file list.
For each file: load → merge visible layers (XCF groups, FS/D&B blend modes and masks are composited like GIMP's own flatten) →
convert to sRGB if the embedded profile isn't sRGB → resize long side → unsharp mask → optional text and/or logo watermark → export.

| Argument (`BE_*` env in CLI) | Default | Notes |
|---|---|---|
| `input-folder` (`BE_INPUT_FOLDER`) | — | folder to scan; with a file list it is only the base for mirroring subfolders |
| `output-folder` (`BE_OUTPUT_FOLDER`) | — | created by the CLI driver if missing |
| `recursive` (`BE_RECURSIVE`) | off | scan subfolders and mirror them in the output (`in/a/b.jpg` → `out/a/b_jpg_web.jpg`). If the output folder is inside the input folder it is excluded automatically |
| `file-list` (`BE_FILE_LIST`) | — | text file, one path per line (`#` comments, blank lines ok; relative paths are relative to the list file). Replaces the folder scan. Files under `input-folder` keep their relative subfolder, others go to the output root. Missing files = FAIL, unsupported types = SKIP |
| `formats` | `jpeg` | comma list of `jpeg,webp,png` |
| `naming` (`BE_NAMING`) | `always` | `always`: `<stem>_<ext><suffix>.<fmt>` e.g. `a.jpg` → `a_jpg_web.jpg`, so `a.jpg` + `a.png` never collide. `on-collision`: `a_web.jpg`, and the extension is only added when two inputs (or an input file itself) would get the same name |
| `suffix` | `_web` | |
| `overwrite` | off | **pre-existing** outputs (there before the run started) are skipped unless this is on. Files written earlier in the same run never block each other (names are planned up front; true duplicates get `_2`, `_3`) |
| `long-side` | 0 | px, 0 = keep; LoHalo for downscale, cubic for upscale |
| `usm-amount` / `usm-radius` | 0.3 / 0.8 | gentle GEGL `gegl:unsharp-mask` (keeps skin texture); amount 0 = off |
| `jpeg-quality` / `webp-quality` | 92 / 90 | JPEG progressive + optimized; WebP lossy |
| `bit-depth` (`BE_BIT_DEPTH`) | `keep` | `keep` or `8`: converts 16/32-bit images to 8-bit for PNG/WebP. JPEG and WebP files are 8-bit anyway, so this mainly affects PNG |
| `convert-srgb` | on | perceptual intent + BPC |
| `keep-exif` | on | EXIF/XMP/IPTC; off strips all metadata. ICC (sRGB) is always embedded |
| `watermark` / `watermark-text` | off / `© Elysia` | text watermark |
| `watermark-font` | `Sans-serif` | missing font → Sans-serif + `WARN` line in the log |
| `watermark-size` | 2.5 | text size, % of long side |
| `watermark-color` | `white` | CSS colour (`#ff0000`, `rgb(…)`, names) |
| `watermark-position` | `bottom-right` | 9-grid: `top-left top top-right left center right bottom-left bottom bottom-right` |
| `watermark-margin` | 2.5 | % of long side |
| `watermark-opacity` | 50 | applies to text and logo |
| `watermark-logo` (`BE_WATERMARK_LOGO`) | — | optional PNG logo (alpha kept). Works without the text watermark. Uses the same position/margin/opacity. With text, the logo is stacked above the text |
| `watermark-logo-scale` | 15 | logo's long side, % of the image's long side |

The defaults keep the previous look (white Sans, 2.5 %, 50 %, bottom-right, margin 2.5 %). Tested pixel-identical to the previous version.

Safety and errors:
- **Inputs are never overwritten.** Output paths are checked against every input path at planning time and again just before writing. If a plain name would hit an input, the extension is added instead.
- Each file is handled on its own. Failures are logged and the batch continues. Log: stderr lines `[batch-export] ...` and `<output>/batch_export.log`.
- Returns **EXECUTION_ERROR** if there are no input files, or if every input failed. Skips don't count as failures.
- PNG/WebP keep alpha only if the source (bottom layer) has alpha. Otherwise, and always for JPEG, the image is flattened onto white.
- Breaking change vs the first version: the default output name now includes the source extension (`a_jpg_web.jpg`). Use `naming=on-collision` for the old `a_web.jpg` style.

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
Other options: `BE_RECURSIVE=1`, `BE_FILE_LIST=list.txt`, `BE_NAMING=on-collision`, `BE_BIT_DEPTH=8`,
`BE_WATERMARK_LOGO=logo.png BE_WATERMARK_POSITION=top-left BE_WATERMARK_COLOR=#ffcc00`, `BE_USM_AMOUNT=0`, `BE_JPEG_QUALITY=95`, `BE_WATERMARK=1 BE_WATERMARK_TEXT="© me"`, `BE_KEEP_EXIF=0`,
`BE_SUFFIX=` (empty), `BE_OVERWRITE=1`.

Tests: `test_batch.sh 3.0|3.2 <root>` (needs `in/`, `allbad/`, `in.md5`, `retouch_ref.png`) + `verify.py`;
`test_batch2.sh 3.0|3.2 <root>` (recursive, file list, collisions, rerun skip, watermark/logo, bit depth; needs `in/` tree, `list.txt`, `logo.png`, `in.md5`).
