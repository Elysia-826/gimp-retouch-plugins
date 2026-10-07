#!/bin/bash
# usage: test_batch.sh 3.0|3.2 <test_root containing in/ allbad/ retouch_ref.png in.md5>
V=$1; B=$2; CLI=$B/cli_run.py; cp "$(dirname "$0")/cli_run.py" $CLI
run(){ if [ "$V" = 3.2 ]; then
  args=(); for e in "$@"; do args+=(--env="$e"); done
  timeout 600 flatpak run "${args[@]}" --command=gimp-console-3.2 org.gimp.GIMP -i --quit --batch-interpreter=python-fu-eval -b "exec(open('$CLI').read())"
 else env "$@" timeout 600 gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval -b "exec(open('$CLI').read())"; fi 2>&1 | grep -E "BATCH_EXPORT|\[batch-export\] (FAIL|DONE)|Traceback"; }
O=$B/out$V; rm -rf $O*
echo "== A all formats, long 1000";       run BE_INPUT_FOLDER=$B/in BE_OUTPUT_FOLDER=$O-a BE_FORMATS=jpeg,webp,png BE_LONG_SIDE=1000
echo "== B rerun (expect skips)";          run BE_INPUT_FOLDER=$B/in BE_OUTPUT_FOLDER=$O-a BE_FORMATS=jpeg,webp,png BE_LONG_SIDE=1000
echo "== C overwrite + watermark";         run BE_INPUT_FOLDER=$B/in BE_OUTPUT_FOLDER=$O-a BE_FORMATS=jpeg BE_LONG_SIDE=1000 BE_OVERWRITE=1 BE_WATERMARK=1 BE_SUFFIX=_wm
echo "== D keep size, no USM, no EXIF";    run BE_INPUT_FOLDER=$B/in BE_OUTPUT_FOLDER=$O-b BE_FORMATS=png BE_USM_AMOUNT=0 BE_KEEP_EXIF=0
echo "== E all bad (expect error)";        run BE_INPUT_FOLDER=$B/allbad BE_OUTPUT_FOLDER=$O-c
rm -rf $B/same && cp -r $B/in $B/same
echo "== F output = input dir, no suffix (copy)"; run BE_INPUT_FOLDER=$B/same BE_OUTPUT_FOLDER=$B/same BE_SUFFIX= BE_FORMATS=jpeg,png
(cd $B/same && md5sum -c --quiet ../in.md5 && echo "SAME-DIR INPUTS UNCHANGED"; ls)
(cd $B/in && md5sum -c --quiet ../in.md5 && echo "INPUTS UNCHANGED"; ls | tr '\n' ' '; echo)
python3 "$(dirname "$0")/verify.py" $B/in $O-a; python3 "$(dirname "$0")/verify.py" $B/in $O-b $B/retouch_ref.png
