#!/bin/bash
# usage: test_batch2.sh 3.0|3.2 <root (see test data layout in README)>
V=$1; T=$2; CLI=$HOME/.config/GIMP/$V/plug-ins/batch_export/cli_run.py
run(){ if [ "$V" = 3.2 ]; then args=(); for e in "$@"; do args+=(--env="$e"); done
  timeout 900 flatpak run "${args[@]}" --command=gimp-console-3.2 org.gimp.GIMP -i --quit --batch-interpreter=python-fu-eval -b "exec(open('$CLI').read())"
 else env "$@" timeout 900 gimp-console-3.0 -i --quit --batch-interpreter=python-fu-eval -b "exec(open('$CLI').read())"; fi 2>&1 | grep -E "BATCH_EXPORT|\[batch-export\]|Traceback"; }
O=$T/o$V; rm -rf $O $T/in/_out/*_web* $T/in/_out/sub; mkdir -p $O
echo "== T1 recursive, output inside input";  run BE_INPUT_FOLDER=$T/in BE_OUTPUT_FOLDER=$T/in/_out BE_RECURSIVE=1 BE_FORMATS=jpeg,png BE_LONG_SIDE=600
echo "== T2 rerun (pre-existing -> skip)";    run BE_INPUT_FOLDER=$T/in BE_OUTPUT_FOLDER=$T/in/_out BE_RECURSIVE=1 BE_FORMATS=jpeg,png BE_LONG_SIDE=600 | grep -E "DONE|STATUS"
echo "== T3 naming=on-collision";             run BE_INPUT_FOLDER=$T/in BE_OUTPUT_FOLDER=$O/t3 BE_NAMING=on-collision BE_FORMATS=jpeg BE_LONG_SIDE=600
echo "== T4 file list";                       run BE_INPUT_FOLDER=$T/in BE_FILE_LIST=$T/list.txt BE_OUTPUT_FOLDER=$O/t4 BE_FORMATS=jpeg BE_LONG_SIDE=600
echo "== T5 watermark missing font + logo";   run BE_INPUT_FOLDER=$T/in BE_OUTPUT_FOLDER=$O/t5 BE_FORMATS=png BE_WATERMARK=1 BE_WATERMARK_TEXT=WMTEST \
   BE_WATERMARK_FONT=NoSuchFont-XYZ BE_WATERMARK_COLOR=#ff0000 BE_WATERMARK_SIZE=6 BE_WATERMARK_POSITION=top-left BE_WATERMARK_OPACITY=100 \
   BE_WATERMARK_LOGO=$T/logo.png BE_WATERMARK_LOGO_SCALE=20 BE_USM_AMOUNT=0
echo "== T6 default watermark (look unchanged)"; run BE_INPUT_FOLDER=$T/in/sub BE_OUTPUT_FOLDER=$O/t6 BE_FORMATS=png BE_WATERMARK=1 | grep -E "DONE|STATUS"
echo "== T7 bit-depth 8 vs keep";             run BE_INPUT_FOLDER=$T/in/sub/deeper BE_OUTPUT_FOLDER=$O/t7a BE_FORMATS=png,webp BE_BIT_DEPTH=8 | grep -E "DONE|STATUS"
                                             run BE_INPUT_FOLDER=$T/in/sub/deeper BE_OUTPUT_FOLDER=$O/t7b BE_FORMATS=png | grep -E "DONE|STATUS"
echo "== T8 output == input folder, naming on-collision, no suffix"; rm -rf $T/same; cp -r $T/in $T/same; rm -rf $T/same/_out
   run BE_INPUT_FOLDER=$T/same BE_OUTPUT_FOLDER=$T/same BE_NAMING=on-collision BE_SUFFIX= BE_FORMATS=jpeg,png | grep -E "SKIP|DONE|STATUS"
   (cd $T/same && md5sum -c --quiet <(grep -v '_out' ../in.md5) && echo "SAME-DIR INPUTS UNCHANGED")
(cd $T/in && md5sum -c --quiet ../in.md5 && echo "INPUTS UNCHANGED")
echo "== files"; (cd $T/in/_out && find . -type f | sort | tr '\n' ' '); echo; for d in t3 t4; do echo "$d: $(cd $O/$d && find . -type f | sort | tr '\n' ' ')"; done
python3 - "$T" "$O" <<'PY'
import sys, numpy as np; from PIL import Image
T,O=sys.argv[1:]
def bd(p): d=open(p,'rb').read(32); return d[24]
print("T7 png bitdepth: 8-mode", bd(O+"/t7a/c16_png_web.png"), " keep-mode", bd(O+"/t7b/c16_png_web.png"),
      " webp(8) mode", Image.open(O+"/t7a/c16_png_web.webp").mode)
a=np.asarray(Image.open(O+"/t5/a_jpg_web.png").convert("RGB"),int); H,W,_=a.shape
L=max(W,H); m=round(L*0.025)
red=(a[...,0]>200)&(a[...,1]<60)&(a[...,2]<60); blue=(a[...,2]>200)&(a[...,0]<60)&(a[...,1]<60)
ys,xs=np.nonzero(red); yb,xb=np.nonzero(blue)
print("T5 %dx%d margin=%d red text bbox x%d-%d y%d-%d | blue logo bbox x%d-%d y%d-%d (logo width expect ~%d)"%(W,H,m,xs.min(),xs.max(),ys.min(),ys.max(),xb.min(),xb.max(),yb.min(),yb.max(),round(L*0.2*300/400)))
b=np.asarray(Image.open(O+"/t6/b_jpg_web.png").convert("RGB"),int); w=(b.min(-1)>200); ys,xs=np.nonzero(w[b.shape[0]//2:,b.shape[1]//2:])
print("T6 default white text in bottom-right quadrant:", len(xs)>50)
PY
