#!/bin/bash
export GIMP3_DIRECTORY=/tmp/kd-gimp
timeout 3000 gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval -b "exec(open('/workspace/retouch-plugins/mesh_liquify/test_mesh.py').read())" > /tmp/kd_mesh_test.log 2>&1
echo EXIT $? >> /tmp/kd_mesh_test.log
N=$(grep -c "undo_group_end" /tmp/kd_mesh_test.log)
echo "MESH_TEST undo_group_end_criticals=$N" >> /tmp/kd_mesh_test.log
