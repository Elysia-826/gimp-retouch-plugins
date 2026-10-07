#!/usr/bin/env bash
# raw2tiff.sh — batch RAW -> 16-bit TIFF with rawtherapee-cli (尚未人工验证 / not manually verified)
# Usage: raw2tiff.sh -i IN_DIR -o OUT_DIR [-p profile.pp3] [-z] [-b 16|16f|32] [--overwrite] [--suffix S]
#   RAW types: CR3 CR2 NEF ARW RAF DNG ORF RW2 (case-insensitive), non-recursive.
#   No -p: uses RawTherapee's default raw profile from ~/.config/RawTherapee/options (-d).
#   Never touches inputs; existing outputs are skipped unless --overwrite (never inside the input folder).
#   Per-file failures are logged to OUT_DIR/raw2tiff.log; the batch continues. Exit 1 if every file failed.
#   Put OUT_DIR under $HOME so GIMP 3.2 (Flatpak) can read it afterwards.
set -uo pipefail
IN= OUT= PROFILE= COMPRESS= BITS=16 OVERWRITE=0 SUFFIX=
while [ $# -gt 0 ]; do case "$1" in
  -i) IN="$2"; shift;; -o) OUT="$2"; shift;; -p) PROFILE="$2"; shift;;
  -z) COMPRESS=z;; -b) BITS="$2"; shift;; --overwrite) OVERWRITE=1;; --suffix) SUFFIX="$2"; shift;;
  -h|--help) sed -n 2,9p "$0"; exit 0;; *) echo "unknown option $1" >&2; exit 2;; esac; shift; done
[ -d "$IN" ] && [ -n "$OUT" ] || { echo "usage: $0 -i IN_DIR -o OUT_DIR [-p x.pp3]" >&2; exit 2; }
command -v rawtherapee-cli >/dev/null || { echo "rawtherapee-cli not found (./install.sh --with-raw)" >&2; exit 2; }
[ -z "$PROFILE" ] || [ -f "$PROFILE" ] || { echo "profile not found: $PROFILE" >&2; exit 2; }
case "$BITS" in 16|16f|32) ;; *) echo "-b 16|16f|32" >&2; exit 2;; esac
mkdir -p "$OUT" || exit 2
INR=$(readlink -f "$IN"); OUTR=$(readlink -f "$OUT")
LOG="$OUTR/raw2tiff.log"; echo "# $(date '+%F %T') in=$INR out=$OUTR profile=${PROFILE:-default(-d)}" >> "$LOG"
log(){ echo "$*"; echo "$*" >> "$LOG"; }
prof=(-d); [ -n "$PROFILE" ] && prof=(-p "$(readlink -f "$PROFILE")")
ok=0 fail=0 skip=0 total=0; declare -A SEEN
shopt -s nullglob nocaseglob
for f in "$INR"/*.{cr3,cr2,nef,arw,raf,dng,orf,rw2}; do
  [ -f "$f" ] || continue; total=$((total+1))
  b=$(basename "$f"); dst="$OUTR/${b%.*}$SUFFIX.tif"
  if [ -n "${SEEN[$dst]:-}" ]; then log "SKIP $b -> $(basename "$dst"): name collision with ${SEEN[$dst]} (use a different folder)"; skip=$((skip+1)); continue; fi
  SEEN[$dst]=$b
  if [ -e "$dst" ]; then
    if [ $OVERWRITE = 0 ] || [ "$OUTR" = "$INR" ]; then log "SKIP $b -> $(basename "$dst"): exists"; skip=$((skip+1)); continue; fi
  fi
  tmp="$OUTR/.${b%.*}.$$.tmp.tif"
  if out=$(rawtherapee-cli -q -o "$tmp" "${prof[@]}" -t$COMPRESS -b$BITS -Y -c "$f" 2>&1) && [ -s "$tmp" ]; then
    mv -f "$tmp" "$dst"; ok=$((ok+1)); log "OK   $b -> $(basename "$dst")"
  else
    rm -f "$tmp"; fail=$((fail+1)); log "FAIL $b: $(echo "$out" | grep -viE '^(RawTherapee|Output is|Processing:)' | tail -2 | tr '\n' ' ')"
  fi
done
log "DONE ok=$ok failed=$fail skipped=$skip total=$total"
[ $total -gt 0 ] && [ $fail -eq $total ] && exit 1
[ $total -eq 0 ] && { echo "no RAW files in $INR" >&2; exit 1; }
exit 0
