"""Interactive selection for install.sh (phase 3).

whiptail (radiolist -> checklist -> GIMP target) when available, otherwise a numbered text prompt
with multi-select. The selection is always written to a TOML config file first; bundle.py then
executes that file. Never used with --yes or without a terminal (bundle.py enforces that).
Set BUNDLE_MENU=text to force the text prompt.
"""
import os, shutil, subprocess, unicodedata

TITLE = "gimp-retouch-plugins 安装 / Install"

class Abort(Exception):
    pass

def _ui():
    if os.environ.get("BUNDLE_MENU", "").lower() == "text":
        return "text"
    return "whiptail" if shutil.which("whiptail") else "text"

def _w(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)

def _cut(s, n):
    out = ""
    for c in s:
        if _w(out + c) > n - 1:
            return out + "…"
        out += c
    return out

def effective(cfg, presets, comps):
    """Component set a config (preset + add - remove + photogimp) stands for."""
    sel = list(presets.get(cfg.get("preset") or "", []))
    sel += [i for i in cfg.get("add", []) if i not in sel]
    if cfg.get("photogimp") and "photogimp" in comps and "photogimp" not in sel:
        sel.append("photogimp")
    return [i for i in sel if i not in cfg.get("remove", []) and i in comps]

def to_config(preset, chosen, presets, gimp):
    base = presets.get(preset, []) if preset else []
    cfg = {}
    if gimp: cfg["gimp"] = gimp
    if preset: cfg["preset"] = preset
    cfg["add"] = [i for i in chosen if i not in base and i != "photogimp"]
    cfg["remove"] = [i for i in base if i not in chosen]
    cfg["photogimp"] = "photogimp" in chosen
    return cfg

def toml_text(cfg, ui):
    q = lambda l: "[" + ", ".join('"%s"' % x for x in l) + "]"
    lines = ["# written by install.sh interactive menu (%s); rerun with: ./install.sh --config <this file>" % ui]
    if cfg.get("gimp"): lines.append('gimp = "%s"' % cfg["gimp"])
    if cfg.get("preset"): lines.append('preset = "%s"' % cfg["preset"])
    lines += ["add = " + q(cfg["add"]), "remove = " + q(cfg["remove"]), "photogimp = " + ("true" if cfg["photogimp"] else "false")]
    return "\n".join(lines) + "\n"

# ---------------------------------------------------------------- whiptail
def _wt(args):
    cols, rows = shutil.get_terminal_size((100, 30))
    r = subprocess.run(["whiptail", "--title", TITLE] + args, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise Abort("cancelled")
    return r.stderr.decode("utf-8", "replace").strip()

def _size(n):
    cols, rows = shutil.get_terminal_size((100, 30))
    h = max(12, min(rows - 2, n + 9))
    return [str(h), str(max(60, min(cols - 2, 110))), str(max(3, min(n, h - 8)))]

def wt_radiolist(text, options, default):
    """options: [(tag, desc)]"""
    cols = max(60, min(shutil.get_terminal_size((100, 30)).columns - 2, 110))
    args = ["--radiolist", text] + _size(len(options))
    for t, d in options:
        args += [t, _cut(d, cols - len(t) - 26), "ON" if t == default else "OFF"]
    return _wt(args)

def wt_checklist(text, options, on):
    cols = max(60, min(shutil.get_terminal_size((100, 30)).columns - 2, 110))
    args = ["--separate-output", "--checklist", text] + _size(len(options))
    for t, d in options:
        args += [t, _cut(d, cols - len(t) - 26), "ON" if t in on else "OFF"]
    out = _wt(args)
    return [l.strip().strip('"') for l in out.splitlines() if l.strip()]

def wt_yesno(text):
    cols, rows = shutil.get_terminal_size((100, 30))
    h = max(10, min(rows - 2, text.count("\n") + 8))
    r = subprocess.run(["whiptail", "--title", TITLE, "--scrolltext", "--yes-button", "安装 Install", "--no-button", "取消 Cancel",
                        "--yesno", text, str(h), str(max(60, min(cols - 2, 110)))])
    return r.returncode == 0

# ---------------------------------------------------------------- text fallback
def _ask(q):
    try:
        return input(q).strip()
    except EOFError:
        raise Abort("no input")

def txt_radiolist(text, options, default):
    print(text)
    for n, (t, d) in enumerate(options, 1):
        print("  %s%d) %-10s %s" % ("*" if t == default else " ", n, t, d))
    while True:
        a = _ask("Choose number/name [Enter = %s]: " % default)
        if not a: return default
        if a.isdigit() and 1 <= int(a) <= len(options): return options[int(a) - 1][0]
        if a in [t for t, _ in options]: return a
        print("  ? '%s' is not a choice" % a)

def txt_checklist(text, options, on):
    tags = [t for t, _ in options]
    cur = [t for t in tags if t in on]
    while True:
        print(text)
        for n, (t, d) in enumerate(options, 1):
            print("  [%s] %2d) %-17s %s" % ("x" if t in cur else " ", n, t, d))
        a = _ask("Toggle numbers/ids (comma/space separated; 'all', 'none'); Enter = done: ")
        if not a: return [t for t in tags if t in cur]
        for x in a.replace(",", " ").split():
            if x == "all": cur = list(tags); continue
            if x == "none": cur = []; continue
            if x.isdigit() and 1 <= int(x) <= len(tags): x = tags[int(x) - 1]
            if x not in tags:
                print("  ? unknown '%s'" % x); continue
            cur.remove(x) if x in cur else cur.append(x)

def txt_yesno(text):
    print(text)
    return _ask("Proceed? [y/N] ").lower() in ("y", "yes")

# ---------------------------------------------------------------- flow
def run_menu(cfg, last, comps, order, builds, presets, present, out_path):
    """cfg: selection from CLI/--config (may be empty); last: parsed last.toml or {}.
    Returns (ui, path) after writing the chosen config to out_path."""
    ui = _ui()
    radio, check = (wt_radiolist, wt_checklist) if ui == "whiptail" else (txt_radiolist, txt_checklist)
    has_cli = bool(cfg.get("preset") or cfg.get("add") or cfg.get("remove") or cfg.get("photogimp"))
    opts = [(p, "预设: " + " ".join(l)) for p, l in sorted(presets.items(), key=lambda kv: len(kv[1]))]
    if last and effective(last, presets, comps):
        opts.append(("last", "上次的选择 last.toml: " + " ".join(effective(last, presets, comps))))
    if has_cli:
        opts.append(("given", "命令行/配置给定的选择: " + " ".join(effective(cfg, presets, comps))))
    opts.append(("custom", "不用预设，自己勾选 / start from nothing"))
    default = "given" if has_cli else ("last" if any(t == "last" for t, _ in opts) else ("portrait" if "portrait" in presets else opts[0][0]))
    p = radio("1/3 选择预设（下一步可增删组件） / Pick a preset (adjust next):", opts, default)
    src = {"given": cfg, "last": last}.get(p, {"preset": p} if p in presets else {})
    pre = effective(src, presets, comps)
    preset = src.get("preset") if src.get("preset") in presets else None

    def label(i):
        c = comps[i]
        extra = []
        if c["requires"]: extra.append("需要 " + ",".join(c["requires"]))
        if c["overwrites"]: extra.append("覆盖配置")
        return "[%s] %s%s" % (c["category"], c["desc"], " (" + "; ".join(extra) + ")" if extra else "")
    hdr = "2/3 勾选组件（空格切换，回车确认） / Components (space toggles, Enter = OK):" if ui == "whiptail" else \
          "2/3 勾选组件（输入编号切换，直接回车完成） / Components (type numbers to toggle, Enter = done):"
    chosen = check(hdr, [(i, label(i)) for i in order], pre)
    if not chosen:
        raise Abort("nothing selected")

    gimp = cfg.get("gimp") or None
    needs_gimp = any(g in ("3.0", "3.2") for i in chosen for b in builds if b["component"] == i for g in b["gimp"])
    if needs_gimp and len(present) > 1:
        gopts = [("all", "3.0 和 3.2 都装 / both")] + [(g, "GIMP %s (%s)" % (g, present[g])) for g in sorted(present)]
        gimp = radio("3/3 安装到哪个 GIMP / Install for which GIMP:", gopts, gimp or last.get("gimp") or "all")
    elif needs_gimp and present and not gimp:
        gimp = next(iter(present))

    final = to_config(preset, chosen, presets, gimp)
    text = toml_text(final, ui)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("==> selection written to %s:\n%s" % (out_path, "\n".join("    " + l for l in text.splitlines())), flush=True)
    return ui, out_path

def confirm(ui, cfg_path, n_actions, sudo_lines, notes):
    text = ["配置文件 / config: " + cfg_path, open(cfg_path, encoding="utf-8").read().strip(), "",
            "将执行 %d 个操作 / %d action(s) will run." % (n_actions, n_actions)]
    if sudo_lines:
        text += ["", "需要 sudo 的步骤 / sudo steps (one confirmation):"] + ["  - " + s for s in sudo_lines]
    if notes:
        text += ["", "提示 / hints:"] + ["  - " + n for n in notes]
    text = "\n".join(text)
    return wt_yesno(text) if ui == "whiptail" else txt_yesno(text)
