import sys,numpy as np;from PIL import Image
a=np.asarray(Image.open(sys.argv[2] if len(sys.argv)>2 else '/workspace/fs_test.png').convert('RGB'),int);b=np.asarray(Image.open(sys.argv[1]).convert('RGB'),int)
y,x=np.mgrid[:a.shape[0],:a.shape[1]];m=(x-315)**2+(y-265)**2>18**2   # exclude healed circle
d=abs(a-b)[m];print("outside-heal max",d.max(),"mean",round(d.mean(),4),"| inside-heal mean",round(abs(a-b)[~m].mean(),2))
