#!/bin/bash
export GIMP3_DIRECTORY=/tmp/kd-gimp
timeout 3000 gimp-console-3.0 -i --batch-interpreter=python-fu-eval -b "exec(open('/workspace/retouch-plugins/mesh_liquify/test_mesh.py').read())" -b 'pdb.gimp_quit(0)' > /tmp/kd_mesh_test.log 2>&1
echo EXIT $? >> /tmp/kd_mesh_test.log
