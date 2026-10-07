import sys,numpy as np;from PIL import Image
a=np.asarray(Image.open('/workspace/fs_test.png').convert('RGB'),int);b=np.asarray(Image.open(sys.argv[1]).convert('RGB'),int)
d=abs(a-b);print("max",d.max(),"mean",round(d.mean(),4),"pct>2",round((d>2).mean()*100,4))
