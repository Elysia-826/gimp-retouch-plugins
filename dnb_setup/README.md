# 一键加深减淡搭建 / One-click Dodge & Burn Setup (GIMP 3.0.4 + 3.2.6)

Menu: **Filters > 人像精修 > 一键加深减淡搭建 / One-click Dodge & Burn Setup**
PDB name: `python-fu-dnb-setup` (args: run-mode, image, drawables, blend-mode = "soft-light"|"overlay", contrast-boost bool)

Creates the following directly above the active layer (pass-through group):
- `Dodge & Burn` (pass-through)
  - `观察层 Helper` (pass-through, hidden by default)
    - `对比增强 Contrast` — desaturated (luminance) copy of the active layer with an S-curve applied (optional)
    - `黑白 Luminosity` — black fill in HSL Color mode (live desaturate of everything below)
  - `加深减淡 D&B` — 50% grey (#808080) in Soft Light (default) or Overlay mode

Sets FG to white and BG to black, and selects the D&B layer. Paint white to dodge and black to burn at low opacity.
Everything is one undo group. The Contrast layer is a snapshot: re-run the setup or delete it after big edits.
Tests: test_dnb.py (env DNB_IN, DNB_OUT, HELPER=1).
