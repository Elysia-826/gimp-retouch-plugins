# 一键频率分离 / One-click Frequency Separation (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 修图工具 > 一键频率分离 / One-click Frequency Separation**
PDB name: `python-fu-fsep-oneclick` (args: run-mode, image, drawables, radius; radius 0 = auto)

Result (top -> bottom):
- Group `Frequency Separation`
  - `High (高频)` — GRAIN_MERGE texture layer (retouch texture here)
  - `Low (低频)` — gaussian-blurred colour/tone layer (retouch colour/tone here)
- original layer, hidden and unchanged

Auto radius (radius = 0): `radius = 6 * long_side / 4000`, clamped to 2..30 px (e.g. 2076x4608 -> 6.9 px). Can be changed in the dialog.

Channels: High and Low always have the same alpha state as the source layer (alpha is removed from High after merge_down when the source has none), so Resynthesizer `plug-in-heal-selection` works on High.
Everything runs inside one undo group.

Notes:
- **`plug-in-gauss` is absent from the PDB in GIMP 3.0 and 3.2** (neither 3.0.4 nor 3.2.6 has it, in the PDB since the old compat procedures were removed). The plug-in blurs with GEGL `gegl:gaussian-blur`. The plug-in
  tries it first; if it's missing, it runs `gegl:gaussian-blur` inside the plug-in (Gegl buffer -> shadow -> merge_shadow),
  so it doesn't need Gimp.DrawableFilter.
- GIMP's GRAIN_EXTRACT = lower - upper + 0.5, so High is built as Low-copy(GRAIN_EXTRACT) over an original copy,
  then merge_down. This gives the same result as "New from Visible", but doesn't depend on the projection being refreshed in batch mode.
- Reconstruction error is at most 1/255 (from 8-bit 0.5 offset rounding). Clipping can occur where texture is above +-127 levels.

Install: copy fsep_oneclick.py to ~/.config/GIMP/{3.0,3.2}/plug-ins/fsep_oneclick/ and chmod +x.
Tests: test_fsep.py (python-fu-eval batch), cmp.py (compare flattened vs original).
- Localization: `set_i18n` is overridden to return False (no catalog), so there's no 'catalog directory does not exist' warning.

## Workflow notes
- **Heal-select (Resynthesizer) on `High (高频)` BEFORE adding layer masks or extra masked/alpha layers inside the
  Frequency Separation group**. Resynthesizer needs the target and the surrounding layers to have the same channels, so
  doing it later can fail with a channel-mismatch error.

## Tolerance (8-bit)
Flattened result vs **GIMP's own decode** of the source: max 1/255 on both versions. On a 2076x4608 JPEG,
3.0.4 averages +0.99 and 3.2.6 averages -0.35 (the grain extract/merge rounding differs between versions).
Comparing against a *different* JPEG decoder (e.g. PIL/libjpeg-turbo) adds up to about 3/255 more decoder difference
(GIMP vs PIL decode of the same JPEG differs by max 3 even with no plug-in), which explains reports of max 4/255.
Setting blend/composite space to perceptual changes nothing. Linear makes it much worse. At 16-bit or 32-bit
precision (Image > Precision, before running) reconstruction is exact (max 0), but the plug-in doesn't convert
precision automatically, to keep 8-bit Resynthesizer workflows unchanged.
