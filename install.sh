#!/usr/bin/env bash
# gimp-retouch-plugins selectable installer (Linux) — GIMP 3.0 (apt) and GIMP 3.2 (Flatpak --user).
# Logic lives in installer/bundle.py (python3 is already required by GIMP 3 Python plug-ins).
# Data: components.txt, bundle.lock, presets/*.txt.   ./install.sh --help   for all options.
# Exit codes: 0 ok, 1 partial, 2 failed, 64 usage. Last line: STATUS=ok|partial|failed installed=N skipped=N failed=N
# Never kills GIMP (and never uses pkill -f).
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
command -v python3 >/dev/null || { echo "python3 is required" >&2; echo "STATUS=failed installed=0 skipped=0 failed=0"; exit 64; }
exec python3 "$HERE/installer/bundle.py" "$@"
