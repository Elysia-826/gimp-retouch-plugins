# Numbers for review: runs deshine_helper on /tmp/ds_in.ppm (before.jpg as PPM). FL=1 for 闪光灯硬光.
import cv2,numpy as np,subprocess,sys,os
FL=os.environ.get('FL','0')
_ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..'))
subprocess.run([sys.executable,os.path.join(_ROOT,'de_shine','deshine_helper.py'),os.path.join(_ROOT,'mesh_liquify','face_detection_yunet_2023mar.onnx'),'/tmp/ds_in.ppm','-','/tmp/ds_out.ppm','/tmp/ds_m.pgm','50','30','1',FL],stderr=subprocess.DEVNULL)
a=cv2.imread('/tmp/ds_in.ppm');b=cv2.imread('/tmp/ds_out.ppm');m=cv2.imread('/tmp/ds_m.pgm',0).astype(float)
L=lambda x:cv2.cvtColor(x,cv2.COLOR_BGR2LAB)[:,:,0].astype(float)*100/255
La=L(a)
def blend(k):
    mm=np.round(m*k)/255.
    return (a*(1-mm[...,None])+b*mm[...,None]+0.5).astype(np.uint8),mm
for k in (1.0,0.5):
    o,mm=blend(k); Lo=L(o)
    print('strength',int(k*100),'mask peak',int(mm.max()*255),'max drop L %.2f'%(La-Lo).max())
o,mm=blend(1.0);Lo=L(o)
print('neck mask max',int(mm[2850:3150,500:800].max()*255),'drop',round((La-Lo)[2850:3150,500:800].max(),2),'(613,2968)',round(La[2968,613]-Lo[2968,613],2))
print('below jaw any mask>0 rows>=2800:',int((m[2800:]>0).sum()))
print('cheek edge x330-420 y1500-2800 mask>10 frac %.4f max %d'%(((mm[1500:2800,330:420]*255)>10).mean(),mm[1500:2800,330:420].max()*255))
def tex(img,x,y,r=40):
    l=L(img)[y-r:y+r,x-r:x+r]; return (l-cv2.GaussianBlur(l,(0,0),3)).std()
ys,xs=np.unravel_index(np.argmax(m),m.shape)
for name,(x,y) in [('peak',(xs,ys)),('nose',(900,1900)),('mole1',(1609,2370)),('mole2',(1384,2454))]:
    print(name,(x,y),'tex %.3f -> %.3f'%(tex(a,x,y),tex(o,x,y)),'maxdiff',int(np.abs(a[y-15:y+15,x-15:x+15].astype(int)-o[y-15:y+15,x-15:x+15]).max()))
print('mask>10 frac %.4f'%(((mm*255)>10).mean()))
print('forehead/right-cheek x>964 mask>10:',int(((mm*255)>10)[:,964:].sum()))
