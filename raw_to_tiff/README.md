# raw2tiff — RAW → 16-bit TIFF（尚未人工验证 / not manually verified）

`raw2tiff.sh` batch-converts CR3/CR2/NEF/ARW/RAF/DNG/ORF/RW2 (case-insensitive, non-recursive) with **rawtherapee-cli**
(RawTherapee 5.11, Debian package `rawtherapee=5.11-2+b2`). `./install.sh --add raw2tiff` (= `--with-raw`) installs this script as
`~/.local/bin/raw2tiff` and pulls in RawTherapee automatically.

```bash
raw_to_tiff/raw2tiff.sh -i ~/photos/raw -o ~/photos/tiff [-p my.pp3] [-z] [-b 16|16f|32] [--suffix S] [--overwrite]
```
- No `-p`: uses RawTherapee's default raw profile (`-d`, from `~/.config/RawTherapee/options`). `-z` = compressed TIFF.
- Output is `<stem><suffix>.tif`, 16-bit RGB with an embedded ICC profile. Each file is written to a temp file and renamed, so a crash doesn't leave a half-written TIFF.
- Inputs are never modified (no sidecar `.pp3` is written). Existing outputs are skipped (`--overwrite` replaces them, but never inside the input folder).
  If two inputs share a stem (`a.CR3` and `a.NEF`), the second one is skipped as a name collision.
- Failures are logged to `OUT/raw2tiff.log` and the batch continues. Exit code 1 if every file failed or no RAW was found.
- Why not GIMP's built-in `file-rawtherapee` loader: on 3.0 it runs `rawtherapee -gimp`, which always opens a window and so blocks
  headless runs. The GIMP 3.2 Flatpak has no RawTherapee inside its sandbox. The Flathub RawTherapee is untested and not used.

## RAW → TIFF → batch_export chain (both GIMP versions)
Keep folders under `$HOME` so the GIMP 3.2 Flatpak can see them.
```bash
raw_to_tiff/raw2tiff.sh -i ~/shoot/raw -o ~/shoot/tiff
# GIMP 3.0
BE_INPUT_FOLDER=~/shoot/tiff BE_OUTPUT_FOLDER=~/shoot/web BE_FORMATS=jpeg BE_LONG_SIDE=2048 \
  gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval \
  -b "exec(open('$HOME/.config/GIMP/3.0/plug-ins/batch_export/cli_run.py').read())"
# GIMP 3.2 (Flatpak)
flatpak run --env=BE_INPUT_FOLDER=$HOME/shoot/tiff --env=BE_OUTPUT_FOLDER=$HOME/shoot/web --env=BE_FORMATS=jpeg \
  --env=BE_LONG_SIDE=2048 --command=gimp-console-3.2 org.gimp.GIMP -i --quit --batch-interpreter=python-fu-eval \
  -b "exec(open('$HOME/.config/GIMP/3.2/plug-ins/batch_export/cli_run.py').read())"
```
Tested on a Canon CR3 (6016×4012 → 16-bit TIFF, about 2.7 s per file). batch_export at long side 2048 gives 2048×1366: JPEG 8-bit,
PNG 16-bit, sRGB ICC. 3.0 and 3.2 outputs were identical (max diff 0).
