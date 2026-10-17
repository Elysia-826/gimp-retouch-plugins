#!/bin/bash
D=$(cd "$(dirname "$0")" && pwd)
export GIMP3_DIRECTORY=${GIMP3_DIRECTORY:-/tmp/kd-gimp}
LOG=${MESH_TEST_LOG:-/tmp/kd_mesh_test.log}
timeout 3000 gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval -b "exec(open('$D/test_mesh.py').read())" > "$LOG" 2>&1
echo EXIT $? >> "$LOG"
N=$(grep -c "undo_group_end" "$LOG")
C=$(grep -c "CRITICAL" "$LOG")
echo "MESH_TEST undo_group_end_criticals=$N criticals=$C" >> "$LOG"
grep -q "^MESH_TEST OK" "$LOG" && [ "$C" = 0 ]
