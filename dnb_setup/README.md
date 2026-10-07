# 一键加深减淡搭建 / One-click Dodge & Burn Setup (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 修图工具 > 一键加深减淡搭建 / One-click Dodge & Burn Setup**
PDB name: `python-fu-dnb-setup` (args: run-mode, image, drawables, blend-mode = "soft-light"|"overlay", contrast-boost bool (default on), place-on-top bool (default off))

Creates the following directly above the active layer or layer group (or at the top of the image stack when `place-on-top` is on):
- `Dodge & Burn` (pass-through)
  - `观察层 Helper` (pass-through, hidden by default)
    - `对比增强 Contrast` — snapshot of the **visible composite** (`Gimp.Layer.new_from_visible`), desaturated (luminance) with an S-curve (optional). Works when a group is selected
    - `黑白 Luminosity` — black fill in HSL Color mode (live desaturate of everything below)
  - `加深减淡 D&B` — 50% grey (#808080) in Soft Light (default) or Overlay mode

**Intentionally** sets the context FG to white and BG to black for painting (white = dodge, black = burn); this persists after the run. Selects the D&B layer.
Any failure (fill/desaturate/curves etc.) returns EXECUTION_ERROR; bad input returns CALLING_ERROR — never SUCCESS. Paint white to dodge and black to burn at low opacity.
Everything is one undo group. The Contrast layer is a snapshot: re-run the setup or delete it after big edits.
Tests: test_dnb.py (env DNB_IN, DNB_OUT, HELPER=1).
Localization: `set_i18n` returns False, so there's no missing-catalog warning.
