# 一键频率分离 / One-click Frequency Separation (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 人像精修 > 一键频率分离 / One-click Frequency Separation**
PDB name: `python-fu-fsep-oneclick` (args: run-mode, image, drawables, radius; radius 0 = auto)

Result (top -> bottom):
- Group `Frequency Separation`
  - `High (高频)` — GRAIN_MERGE texture layer (retouch texture here)
  - `Low (低频)` — gaussian-blurred colour/tone layer (retouch colour/tone here)
- original layer, hidden and unchanged

Auto radius: 4 px per 2000 px short side, clamped to 2..30 px. Can be changed in the dialog.
Everything runs inside one undo group.

Notes:
- Neither 3.0.4 nor 3.2.6 has `plug-in-gauss` in the PDB (the old compat procedures were removed). The plug-in
  tries it first; if it's missing, it runs `gegl:gaussian-blur` inside the plug-in (Gegl buffer -> shadow -> merge_shadow),
  so it doesn't need Gimp.DrawableFilter.
- GIMP's GRAIN_EXTRACT = lower - upper + 0.5, so High is built as Low-copy(GRAIN_EXTRACT) over an original copy,
  then merge_down. This gives the same result as "New from Visible", but doesn't depend on the projection being refreshed in batch mode.
- Reconstruction error is at most 1/255 (from 8-bit 0.5 offset rounding). Clipping can occur where texture is above +-127 levels.

Install: copy fsep_oneclick.py to ~/.config/GIMP/{3.0,3.2}/plug-ins/fsep_oneclick/ and chmod +x.
Tests: test_fsep.py (python-fu-eval batch), cmp.py (compare flattened vs original).
