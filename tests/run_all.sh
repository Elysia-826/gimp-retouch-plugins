#!/bin/bash
# ./run_tests [plugin ...]   all plug-ins when none given
R=$(cd "$(dirname "$0")/.." && pwd); cd "$R" || exit 2
G=${KD_GIMP_DIR:-/tmp/kd-gimp}
case "$G" in /tmp/*) ;; *) echo "KD_GIMP_DIR must be under /tmp (got $G); ~/.config/GIMP is never used"; exit 2;; esac
L=$G-logs
rm -rf "$G" "$L"; mkdir -p "$G" "$L"
export GIMP3_DIRECTORY=$G
printf '(show-welcome-dialog no)\n(color-profile-policy keep)\n' > "$G/gimprc"
FACE=$R/tests/data/astronaut.jpg
ALL="fsep_oneclick dnb_setup batch_export mesh_liquify spot_heal dnb_flow subject_mask de_shine portrait_panel action_record portrait_brush"
PLUGINS=${*:-$ALL}
T0=$(date +%s)
declare -A RES NOTE
GUI=1; for c in Xvfb xdotool xfwm4 gimp-3.0; do command -v $c >/dev/null || { GUI=0; NOGUI="$NOGUI $c"; }; done

gc() {  # gc <log> <python code> [ENV=...]
    local log=$1 code=$2; shift 2
    env "$@" timeout 1800 gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval -b "$code" > "$L/$log.log" 2>&1
}
check() {  # check <plugin> <log> <marker>
    local n; n=$(grep -c CRITICAL "$L/$2.log")
    if grep -q "$3" "$L/$2.log" && [ "$n" = 0 ] && ! grep -q FAIL "$L/$2.log"; then echo "  pass $2"; else
        echo "  FAIL $2 (marker '$3' $(grep -q "$3" "$L/$2.log" && echo found || echo missing), CRITICAL $n, log $L/$2.log)"
        grep -E "FAIL|Traceback|Error|CRITICAL" "$L/$2.log" | grep -v dbind | head -5 | sed 's/^/    /'
        RES[$1]=FAIL; fi
}
smoke() { gc "$1-smoke" "exec(open('tests/smoke/common.py').read()); exec(open('tests/smoke/$1.py').read())" SMOKE_NAME=$1 "${@:2}"; check $1 "$1-smoke" "SMOKE $1 OK"; }

echo "== catalog (installer/bundle.py --check-catalog)"
python3 installer/bundle.py --check-catalog > "$L/catalog.log" 2>&1; CAT=$?
[ $CAT = 0 ] && echo "  pass" || { echo "  FAIL exit $CAT"; grep ERROR "$L/catalog.log" | sed 's/^/    /'; }
echo "== lint (tests/lint.py)"
python3 tests/lint.py > "$L/lint.log" 2>&1; LINT=$?
[ $LINT = 0 ] && echo "  pass" || { echo "  FAIL"; grep "^LINT" "$L/lint.log" | head -20 | sed 's/^/    /'; }
echo "== install into $G"
python3 tests/install_lock.py "$G" > "$L/install.log" 2>&1
for d in $KD_EXTRA_PLUGINS; do cp -r "$d" "$G/plug-ins/"; done
gc startup "print('STARTUP OK')"
check startup startup "STARTUP OK"

for p in $PLUGINS; do
    echo "== $p"
    RES[$p]=pass
    grep "^INSTALL MISSING $p " "$L/install.log" | sed 's/^/  FAIL /' | grep . && RES[$p]=FAIL
    python3 tests/check_pluginrc.py "$G" $p > "$L/$p-reg.log" 2>&1 && echo "  pass registered" || { echo "  FAIL registered"; grep FAIL "$L/$p-reg.log" | sed 's/^/    /'; RES[$p]=FAIL; }
    case $p in
    mesh_liquify)
        gc mesh_liquify-test "exec(open('mesh_liquify/test_mesh.py').read())" ${MESH_TEST_PHOTO:+MESH_TEST_PHOTO=$MESH_TEST_PHOTO}
        check $p mesh_liquify-test "MESH_TEST OK"
        if [ $GUI = 1 ]; then bash tests/mesh_liquify/gui_face_xvfb.sh :94 "$FACE" > "$L/mesh_liquify-gui.log" 2>&1; check $p mesh_liquify-gui "GUI_FACE OK"
        else NOTE[$p]="GUI skipped (missing:$NOGUI)"; fi ;;
    dnb_flow)
        gc dnb_flow-test "exec(open('dnb_flow/test_flow.py').read())"; check $p dnb_flow-test "FLOW_TEST OK" ;;
    spot_heal)
        if grep -q '(proc-def "plug-in-heal-selection"' "$G/pluginrc"; then
            gc spot_heal-test "exec(open('spot_heal/test_spot.py').read())"; check $p spot_heal-test "SPOT_TEST OK"
        else RES[$p]=skip; NOTE[$p]="needs Resynthesizer (plug-in-heal-selection); set KD_EXTRA_PLUGINS to its plug-in folders"; fi ;;
    de_shine)
        smoke $p
        gc de_shine-photo "exec(open('tests/de_shine/test_deshine.py').read())" DESHINE_TEST_IMAGE=$FACE DESHINE_NECK=
        check $p de_shine-photo "DESHINE_TEST ok"
        gc de_shine-strength "exec(open('tests/de_shine/test_strength.py').read())" DS_OUT=$L/ds; check $p de_shine-strength "DS_STRENGTH OK" ;;
    portrait_panel)
        smoke $p SMOKE_FACE=$FACE
        gc portrait_panel-help "exec(open('tests/portrait_panel/test_help.py').read(), {'__name__': 't'})"; check $p portrait_panel-help "HELP ALL OK"
        for t in step3:ST3 eye:EYE review3:R3 workspace:PP_TEST; do
            gc portrait_panel-${t%%:*} "exec(open('tests/portrait_panel/test_${t%%:*}.py').read(), {'__name__': 't'})"; check $p portrait_panel-${t%%:*} "^${t#*:} OK"
        done
        if [ $GUI = 1 ]; then PP_TEST_IMAGE=$FACE sh tests/portrait_panel/gui_close_xvfb.sh :97 > "$L/portrait_panel-gui.log" 2>&1; check $p portrait_panel-gui "GUI CLOSE OK"
            bash tests/portrait_panel/gui_undo_xvfb.sh :95 "$FACE" > "$L/portrait_panel-gui-undo.log" 2>&1; check $p portrait_panel-gui-undo "GUI_PP OK"
        else NOTE[$p]="GUI skipped (missing:$NOGUI)"; fi ;;
    subject_mask)
        smoke $p
        python3 subject_mask/test_seg_helper.py > "$L/subject_mask-seg.log" 2>&1
        check $p subject_mask-seg "SEG_HELPER OK" ;;
    fsep_oneclick)
        smoke $p
        gc fsep_oneclick-test "exec(open('fsep_oneclick/test_fsep.py').read())" FS_OUT=$L/fs; check $p fsep_oneclick-test "FSEP_TEST OK" ;;
    dnb_setup)
        smoke $p
        gc dnb_setup-test "exec(open('dnb_setup/test_dnb.py').read())" DNB_OUT=$L/dnb; check $p dnb_setup-test "DNB_TEST OK"
        gc dnb_setup-combined "exec(open('tests_combined.py').read())" T_OUT=$L/comb; check $p dnb_setup-combined "COMB_TEST OK" ;;
    *) smoke $p ;;
    esac
    case $p in batch_export|portrait_panel) ;; *)
        gc $p-errors "exec(open('tests/smoke/common.py').read()); exec(open('tests/smoke/errors.py').read())" SMOKE_NAME=$p
        check $p $p-errors "SMOKE $p errors OK" ;;
    esac
done

echo
echo "== result ($(( $(date +%s) - T0 )) s, logs in $L)"
FAILED=0
[ $CAT = 0 ] && echo "  catalog         pass" || { echo "  catalog         FAIL"; FAILED=1; }
[ $LINT = 0 ] && echo "  lint            pass" || { echo "  lint            FAIL"; FAILED=1; }
for p in $PLUGINS; do
    printf "  %-15s %s %s\n" $p ${RES[$p]} "${NOTE[$p]}"
    [ "${RES[$p]}" = FAIL ] && FAILED=1
done
exit $FAILED
