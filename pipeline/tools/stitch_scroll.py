"""stitch_scroll.py <video> <from_s> <to_s> <out.png> [x0 x1 y0 y1] — turn a scroll through a page in the screen
recording (a Google Doc, a website) into ONE tall image: template-matches each frame's offset, median-merges the
overlaps (removes the cursor). Default crop = a Google Docs page column on a 2356x1410 screen recording (even numbers; pass your own).
Deps: uv run --with "opencv-python-headless<4.12" --with numpy python …
Check the result: crop away the tail if the window changes at the end."""
import cv2, numpy as np, subprocess, sys
src, a, b, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
X0,X1,Y0,Y1 = [int(v) for v in sys.argv[5:9]] if len(sys.argv) > 8 else (318,1746,312,1320)
W,H=X1-X0,Y1-Y0
raw = subprocess.run(["ffmpeg","-v","error","-ss",str(a),"-t",str(b-a),"-i",src,"-vf",f"fps=15,crop={W}:{H}:{X0}:{Y0}","-f","rawvideo","-pix_fmt","bgr24","-"],capture_output=True).stdout
fr = np.frombuffer(raw,np.uint8).reshape(-1,H,W,3)
print(len(fr),'frames')
g=[cv2.cvtColor(f,cv2.COLOR_BGR2GRAY).astype(np.float32) for f in fr]
y=[0]
for k in range(1,len(fr)):
    # template: middle band of previous frame, search in current
    best=(-1,0)
    for b0 in (760,100,430):
        t=g[k-1][b0:b0+180, 100:W-100]
        if t.std()<8: continue
        r=cv2.matchTemplate(g[k][:, 100:W-100], t, cv2.TM_CCOEFF_NORMED)
        _,mx,_,loc=cv2.minMaxLoc(r)
        if mx>best[0]: best=(mx,b0-loc[1])
    if best[0]<0.85: print('weak',k,best)
    y.append(y[-1]+best[1])
y=np.array(y); y-=y.min(); Ht=int(y.max())+H
print('offsets',[int(v) for v in y[::15]]); print('height',Ht)
canvas=np.zeros((Ht,W,3),np.uint8)
for r0 in range(0,Ht,40):
    r1=min(Ht,r0+40); cov=[k for k in range(len(fr)) if y[k]<=r0 and y[k]+H>=r1]
    if not cov: continue
    sel=cov[::max(1,len(cov)//7)][:9]
    canvas[r0:r1]=np.median(np.stack([fr[k][r0-y[k]:r1-y[k]] for k in sel]),axis=0).astype(np.uint8)
cv2.imwrite(out,canvas)
