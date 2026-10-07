#!/usr/bin/env bash
# gimp-retouch-plugins one-click installer / reinstaller (Linux)
# GIMP 3.0.x (apt, ~/.config/GIMP/3.0) and GIMP 3.2.x (Flatpak org.gimp.GIMP --user, ~/.config/GIMP/3.2)
# Usage: ./install.sh [--gimp 3.0|3.2|all] [--only ours|third-party|all] [--reinstall] [--dry-run]
#                     [--with-photogimp] [--no-verify] [--backup-dir DIR]
# Never kills GIMP (and never uses pkill -f). Third-party sources are fetched at the versions pinned in bundle.lock.
set -uo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
LOCK="$REPO/bundle.lock"
GIMP_SEL=all; ONLY=all; REINSTALL=0; DRY=0; PHOTOGIMP=0; VERIFY=1
BACKUP_DIR="$HOME/gimp-bundle-backups"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/gimp-retouch-bundle"
STATE="${XDG_DATA_HOME:-$HOME/.local/share}/gimp-retouch-bundle"
LIBDIR30=/usr/lib/x86_64-linux-gnu/gimp/3.0/plug-ins

while [ $# -gt 0 ]; do
  case "$1" in
    --gimp) GIMP_SEL="$2"; shift;;
    --only) ONLY="$2"; shift;;
    --reinstall) REINSTALL=1;;
    --dry-run) DRY=1;;
    --with-photogimp) PHOTOGIMP=1;;
    --no-verify) VERIFY=0;;
    --backup-dir) BACKUP_DIR="$2"; shift;;
    -h|--help) sed -n 2,7p "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac; shift
done
case "$GIMP_SEL" in 3.0) VERS="3.0";; 3.2) VERS="3.2";; all) VERS="3.0 3.2";; *) echo "--gimp 3.0|3.2|all" >&2; exit 2;; esac
case "$ONLY" in ours|third-party|all) ;; *) echo "--only ours|third-party|all" >&2; exit 2;; esac

# ---------- helpers ----------
say(){ printf '\033[1m==>\033[0m %s\n' "$*"; }
warn(){ printf '\033[33mWARN:\033[0m %s\n' "$*" >&2; }
run(){ if [ $DRY = 1 ]; then echo "    [dry-run] $*"; else echo "    + $*"; "$@"; fi; }
declare -A ACTION VERSION_OF
ROWS=()
record(){ # gimp id action
  ACTION["$1|$2"]="$3"; ROWS+=("$1|$2")
}
lock(){ # id field(1-based: 1 id,2 gimp,3 version,4 kind,5 source,6 sha,7 license,8 notes)
  awk -F'|' -v id="$1" -v f="$2" '!/^#/ && NF>=6 { k=$1; gsub(/ /,"",k); if (k==id) { v=$f; gsub(/^ +| +$/,"",v); print v; exit } }' "$LOCK"
}
sha_of(){ sha256sum "$1" 2>/dev/null | cut -d' ' -f1; }
fetch(){ # url sha dest
  local url="$1" sha="$2" dest="$3"
  if [ -f "$dest" ] && [ "$(sha_of "$dest")" = "$sha" ]; then return 0; fi
  [ $DRY = 1 ] && { echo "    [dry-run] download $url"; return 0; }
  mkdir -p "$(dirname "$dest")"
  curl -fsSL --retry 3 -o "$dest.part" "$url" || { warn "download failed: $url"; return 1; }
  local got; got="$(sha_of "$dest.part")"
  if [ "$got" != "$sha" ]; then warn "sha256 mismatch for $url: got $got expected $sha"; rm -f "$dest.part"; return 1; fi
  mv "$dest.part" "$dest"
}
state_get(){ cat "$STATE/$1-$2" 2>/dev/null; }
state_set(){ [ $DRY = 1 ] || { mkdir -p "$STATE"; echo "$3" > "$STATE/$1-$2"; }; }
profile(){ echo "$HOME/.config/GIMP/$1"; }
plugdir(){ echo "$(profile "$1")/plug-ins"; }
fp_commit(){ flatpak info --user -c "$1" 2>/dev/null; }

# ---------- preflight ----------
say "repo: $REPO   gimp: $VERS   only: $ONLY   reinstall: $REINSTALL   dry-run: $DRY"
[ -f "$LOCK" ] || { echo "missing $LOCK" >&2; exit 1; }
for v in $VERS; do
  if [ $v = 3.0 ] && ! command -v gimp-console-3.0 >/dev/null; then warn "gimp-console-3.0 not found (apt install gimp)"; fi
  if [ $v = 3.2 ] && ! flatpak info --user org.gimp.GIMP >/dev/null 2>&1; then warn "Flatpak org.gimp.GIMP (--user) not installed"; fi
done
if pgrep -x gimp-3.0 >/dev/null || pgrep -x gimp >/dev/null || flatpak ps 2>/dev/null | grep -q org.gimp.GIMP; then
  warn "GIMP is running ($(pgrep -a -x gimp-3.0; pgrep -a -x gimp; true | tr '\n' ' ')). Not killing it; restart GIMP afterwards to load plug-ins."
fi
if [ "$ONLY" != ours ] && [ $DRY = 0 ] && ! sudo -n true 2>/dev/null && [[ "$VERS" == *3.0* ]]; then
  warn "sudo needs a password: system-wide steps (G'MIC .deb, Resynthesizer build) will prompt"
fi

# ---------- backup ----------
TS=$(date +%Y%m%d-%H%M%S)
BK="$BACKUP_DIR/gimp-config-$TS.tgz"
paths=(); for v in $VERS; do [ -d "$(profile $v)" ] && paths+=(".config/GIMP/$v"); done
if [ ${#paths[@]} -gt 0 ]; then
  say "backup ${paths[*]} -> $BK"
  if [ $DRY = 0 ]; then mkdir -p "$BACKUP_DIR" && tar -C "$HOME" -czf "$BK" "${paths[@]}" || { echo "backup failed, aborting" >&2; exit 1; }
  else echo "    [dry-run] tar -C ~ -czf $BK ${paths[*]}"; fi
fi

# ---------- our plugins ----------
install_ours(){ # v id
  local v=$1 id=$2 src="$REPO/$(lock $2 5)" d; d="$(plugdir $v)/$id"
  local need=0 f
  local files=("$src"); [ $id = batch_export ] && files+=("$REPO/batch_export/cli_run.py")
  for f in "${files[@]}"; do [ "$(sha_of "$d/$(basename "$f")")" = "$(sha_of "$f")" ] || need=1; done
  [ $REINSTALL = 1 ] && need=1
  if [ $need = 0 ]; then record $v $id "ok (up to date)"; return; fi
  run mkdir -p "$d"
  for f in "${files[@]}"; do run install -m 644 "$f" "$d/"; done
  run chmod 755 "$d/$id.py"
  record $v $id "$([ $DRY = 1 ] && echo would-install || echo installed)"
}

# ---------- third-party ----------
tp_gmic_deb(){
  local id=gmic-qt ver; ver=$(lock $id 3)
  local cur; cur=$(dpkg-query -W -f='${Version}' gmic 2>/dev/null)
  if [ "$cur" = "$ver" ] && [ -x $LIBDIR30/gmic_gimp_qt/gmic_gimp_qt ] && [ $REINSTALL = 0 ]; then record 3.0 $id "ok ($cur)"; return; fi
  local deb="$CACHE/gmic_${ver}_debian13_trixie_amd64.deb"
  fetch "$(lock $id 5)" "$(lock $id 6)" "$deb" || { record 3.0 $id FAILED-download; return; }
  run sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall "$deb" || { record 3.0 $id FAILED; return; }
  record 3.0 $id "$([ $DRY = 1 ] && echo would-install || echo "installed $ver")"
}
tp_resynth_src(){
  local id=resynthesizer commit; commit=$(lock $id 6)
  local ok=0
  if [ -x $LIBDIR30/resynthesizer/resynthesizer ] && [ -f $LIBDIR30/plug-in-heal-selection/plug-in-heal-selection.scm ] \
     && ! grep -q "register-i18n" $LIBDIR30/plug-in-heal-selection/plug-in-heal-selection.scm; then ok=1; fi
  if [ $ok = 1 ] && [ $REINSTALL = 0 ]; then
    record 3.0 $id "ok (v3.0-compatible$( [ "$(state_get 3.0 $id)" = "$commit" ] && echo ", pinned" ))"; return; fi
  local s="$CACHE/resynthesizer"
  run sudo DEBIAN_FRONTEND=noninteractive apt-get install -y meson ninja-build libgimp-3.0-dev pkg-config build-essential gettext git || { record 3.0 $id FAILED-deps; return; }
  if [ $DRY = 0 ]; then
    [ -d "$s/.git" ] || git clone -q "$(lock $id 5)" "$s" || { record 3.0 $id FAILED-clone; return; }
    git -C "$s" fetch -q --tags origin && git -C "$s" checkout -q "$commit" || { record 3.0 $id FAILED-checkout; return; }
    [ "$(git -C "$s" rev-parse HEAD)" = "$commit" ] || { record 3.0 $id FAILED-commit; return; }
    rm -rf "$s/build"
  else echo "    [dry-run] git clone $(lock $id 5) && checkout $commit"; fi
  run meson setup "$s/build" "$s" --prefix=/usr --libdir=lib/x86_64-linux-gnu || { record 3.0 $id FAILED-meson; return; }
  run ninja -C "$s/build" || { record 3.0 $id FAILED-build; return; }
  run sudo meson install -C "$s/build" --no-rebuild || { record 3.0 $id FAILED-install; return; }
  state_set 3.0 $id "$commit"
  record 3.0 $id "$([ $DRY = 1 ] && echo would-build || echo "built v3.0 ${commit:0:7}")"
}
tp_batcher(){ # v
  local v=$1 id=batcher ver; ver=$(lock $id 3); local d; d="$(plugdir $v)/batcher"
  if grep -q "PLUGIN_VERSION = '$ver'" "$d/config/config.py" 2>/dev/null && [ -x "$d/batcher.py" ] && [ $REINSTALL = 0 ]; then
    record $v $id "ok ($ver)"; return; fi
  local z="$CACHE/batcher-$ver.zip"
  fetch "$(lock $id 5)" "$(lock $id 6)" "$z" || { record $v $id FAILED-download; return; }
  local x="$CACHE/batcher-$ver-extract"
  run rm -rf "$x"; run mkdir -p "$x"; run unzip -q "$z" -d "$x" || { record $v $id FAILED-unzip; return; }
  run rm -rf "$d"; run cp -a "$x/batcher" "$d"
  run chmod -R go-w "$d"; run chmod +x "$d/batcher.py"; run chmod -x "$d/__init__.py"
  record $v $id "$([ $DRY = 1 ] && echo would-install || echo "installed $ver")"
}
tp_adjlayer(){ # v
  local v=$1 id=adjustment-layer sha; sha=$(lock $id 6); local d; d="$(plugdir $v)/adjustment-layer"
  if [ "$(sha_of "$d/adjustment-layer.py")" = "$sha" ] && [ $REINSTALL = 0 ]; then record $v $id "ok ($(lock $id 3))"; return; fi
  local f="$CACHE/adjustment-layer-$(lock $id 3).py"
  fetch "$(lock $id 5)" "$sha" "$f" || { record $v $id FAILED-download; return; }
  run mkdir -p "$d"; run install -m 755 "$f" "$d/adjustment-layer.py"
  record $v $id "$([ $DRY = 1 ] && echo would-install || echo "installed $(lock $id 3)")"
}
tp_flatpak(){ # id
  local id=$1 ref commit; ref=$(lock $id 5); ref=${ref#flathub:}; commit=$(lock $id 6)
  local short=${ref#*/}; short=${short%%/*}; local branch=${ref##*/}
  if [ "$(fp_commit "$ref")" = "$commit" ] && [ $REINSTALL = 0 ]; then record 3.2 $id "ok (${commit:0:7})"; return; fi
  if flatpak info --user "$ref" >/dev/null 2>&1; then
    [ $REINSTALL = 1 ] && { run flatpak install --user -y --noninteractive --reinstall flathub "$ref" || { record 3.2 $id FAILED; return; }; }
  else
    run flatpak install --user -y --noninteractive flathub "$ref" || { record 3.2 $id FAILED; return; }
  fi
  if [ $DRY = 1 ] || [ "$(fp_commit "$ref")" != "$commit" ]; then
    run flatpak update --user -y --noninteractive --commit="$commit" "$ref" || { record 3.2 $id FAILED-pin; return; }
  fi
  if [ $DRY = 0 ] && [ "$(fp_commit "$ref")" != "$commit" ]; then record 3.2 $id "FAILED (commit $(fp_commit "$ref" | cut -c1-7) != pinned)"; return; fi
  record 3.2 $id "$([ $DRY = 1 ] && echo would-install || echo "installed ${commit:0:7}")"
}
tp_icu_wrapper(){
  local id=gmic_qt_icu77 W; W="$(plugdir 3.2)/gmic_qt_icu77"
  local loc; loc=$(flatpak info --user --show-location org.freedesktop.Platform//25.08 2>/dev/null)/files/lib/x86_64-linux-gnu
  local want; want='#!/bin/sh
# Wrapper: flathub org.gimp.GIMP.Plugin.GMic//3 (4.0.5) links ICU 77, but GIMP 3.2.6 runtime (GNOME 51) ships ICU 78.
# ICU 77 libs copied from org.freedesktop.Platform//25.08.
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec /app/extensions/GMic/plug-ins/gmic_gimp_qt/gmic_gimp_qt "$@"'
  local ok=1 l
  [ "$(grep -v '^# ' "$W/gmic_qt_icu77" 2>/dev/null)" = "$(grep -v '^# ' <<<"$want")" ] && [ -x "$W/gmic_qt_icu77" ] || ok=0
  for l in libicudata.so.77 libicui18n.so.77 libicuuc.so.77; do
    [ "$(sha_of "$W/lib/$l")" = "$(sha_of "$loc/$l")" ] && [ -n "$(sha_of "$loc/$l")" ] || ok=0; done
  if [ $ok = 1 ] && [ $REINSTALL = 0 ]; then record 3.2 $id "ok"; return; fi
  run mkdir -p "$W/lib"
  for l in libicudata.so.77 libicui18n.so.77 libicuuc.so.77; do run cp -L "$loc/$l" "$W/lib/"; done
  if [ $DRY = 0 ]; then printf '%s\n' "$want" > "$W/gmic_qt_icu77.new" && chmod 755 "$W/gmic_qt_icu77.new" && mv "$W/gmic_qt_icu77.new" "$W/gmic_qt_icu77"
  else echo "    [dry-run] write $W/gmic_qt_icu77"; fi
  record 3.2 $id "$([ $DRY = 1 ] && echo would-install || echo installed)"
}
tp_photogimp(){ # v
  local v=$1 id=photogimp
  if [ $PHOTOGIMP = 0 ]; then record $v $id "skipped (opt-in: --with-photogimp)"; return; fi
  if [ "$(state_get $v $id)" = "$(lock $id 6)" ] && [ $REINSTALL = 0 ]; then record $v $id "ok"; return; fi
  local t="$CACHE/photogimp-$(lock $id 3).tar.gz"
  fetch "$(lock $id 5)" "$(lock $id 6)" "$t" || { record $v $id FAILED-download; return; }
  local x="$CACHE/photogimp-x"; run rm -rf "$x"; run mkdir -p "$x"; run tar -xzf "$t" -C "$x" --strip-components=1
  run cp -a "$x/.config/GIMP/3.0/." "$(profile $v)/"
  state_set $v $id "$(lock $id 6)"
  record $v $id "$([ $DRY = 1 ] && echo would-install || echo installed)"
}

for v in $VERS; do
  [ -d "$(profile $v)" ] || run mkdir -p "$(plugdir $v)"
  if [ "$ONLY" != third-party ]; then
    say "GIMP $v: our plugins"
    for id in fsep_oneclick dnb_setup batch_export; do install_ours $v $id; done
  fi
  if [ "$ONLY" != ours ]; then
    say "GIMP $v: third-party (pinned)"
    if [ $v = 3.0 ]; then tp_gmic_deb; tp_resynth_src
    else
      if flatpak remote-list --user 2>/dev/null | grep -q '^flathub'; then :; else run flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo; fi
      tp_flatpak gmic-qt-flatpak; tp_flatpak icu77-runtime; tp_icu_wrapper; tp_flatpak resynthesizer-flatpak
    fi
    tp_batcher $v; tp_adjlayer $v; tp_photogimp $v
  fi
done

# ---------- headless registration check ----------
declare -A PROCS=(
  [fsep_oneclick]='python-fu-fsep-oneclick' [dnb_setup]='python-fu-dnb-setup' [batch_export]='python-fu-batch-export'
  [gmic-qt]='plug-in-gmic-qt' [gmic-qt-flatpak]='plug-in-gmic-qt' [gmic_qt_icu77]='plug-in-gmic-qt'
  [resynthesizer]='plug-in-resynthesizer plug-in-heal-selection' [resynthesizer-flatpak]='plug-in-resynthesizer plug-in-heal-selection'
  [batcher]='plug-in-batch-export-images plug-in-batch-convert' [adjustment-layer]='plug-in-adjustment-layer-curves plug-in-layer-effect-drop-shadow'
  [icu77-runtime]='' [photogimp]='')
declare -A DEFPATH=([gmic_qt_icu77]='gmic_qt_icu77/gmic_qt_icu77' [gmic-qt]='gmic_gimp_qt/gmic_gimp_qt')
refresh(){ # v : run gimp-console once to rebuild pluginrc, keep profile clean
  local v=$1 p; p="$(profile $v)"; local before; before=$(ls "$p")
  cp -p "$p/tags.xml" /tmp/.tags.$$ 2>/dev/null
  if [ $v = 3.0 ]; then
    timeout 300 gimp-console-3.0 -i --batch-interpreter=plug-in-script-fu-eval -b '(gimp-quit 0)' >"$CACHE/verify-$v.log" 2>&1
  else
    timeout 300 flatpak run --filesystem="$REPO" --command=gimp-console-3.2 org.gimp.GIMP -i --batch-interpreter=plug-in-script-fu-eval -b '(gimp-quit 0)' >"$CACHE/verify-$v.log" 2>&1
  fi
  for f in colorrc extensionrc parasiterc templaterc unitrc; do
    grep -qx "$f" <<<"$before" || rm -f "$p/$f"; done
  [ -f /tmp/.tags.$$ ] && mv /tmp/.tags.$$ "$p/tags.xml"
}
declare -A REG
if [ $VERIFY = 1 ]; then
  mkdir -p "$CACHE"
  for v in $VERS; do
    if [ $DRY = 1 ]; then say "GIMP $v: [dry-run] reading existing pluginrc (GIMP not started)"
    else say "GIMP $v: headless registration check"; refresh $v; fi
    rc="$(profile $v)/pluginrc"
    for row in "${ROWS[@]}"; do
      [ "${row%%|*}" = $v ] || continue; id=${row#*|}; want="${PROCS[$id]:-}"
      if [ -z "$want" ]; then REG[$row]="n/a"; continue; fi
      r=yes; for pr in $want; do grep -q "(proc-def \"$pr\"" "$rc" 2>/dev/null || r=NO; done
      if [ -n "${DEFPATH[$id]:-}" ] && ! grep -q "${DEFPATH[$id]}\"" "$rc" 2>/dev/null; then r=NO; fi
      REG[$row]=$r
    done
  done
fi

# ---------- summary ----------
echo
printf '%-5s %-22s %-10s %-40s %s\n' GIMP COMPONENT PINNED ACTION REGISTERED
printf '%.0s-' {1..95}; echo
fail=0
for row in "${ROWS[@]}"; do
  v=${row%%|*}; id=${row#*|}; a="${ACTION[$row]}"; r="${REG[$row]:-skipped}"
  printf '%-5s %-22s %-10s %-40s %s\n' "$v" "$id" "$(lock $id 3)" "$a" "$r"
  [[ "$a" == FAILED* ]] && fail=1; [ "$r" = NO ] && [ $DRY = 0 ] && fail=1
done
echo; [ -n "${paths[*]:-}" ] && echo "backup: $BK$([ $DRY = 1 ] && echo ' (not written: dry-run)')"
echo "not bundled (manual): Chuck Henrich frequency-separation-group-v3 / dodge-and-burn-soft-light-v3 (see README)"
[ $fail = 0 ] && echo "RESULT: OK" || echo "RESULT: FAILURES (see above; logs in $CACHE)"
exit $fail
