#!/usr/bin/env bash
# Exploration commands for the Hinge Hexagon segment OBJ.
# Usage: bash claude_cmd.sh
set -euo pipefail
OBJ="/Users/lee/Viewer/hinge_obj/Hinge Hexagon.obj"

echo "=== Overall bounding box & centers (units = meters) ==="
awk '/^v / {n++; if(n==1){minx=maxx=$2;miny=maxy=$3;minz=maxz=$4}
     if($2<minx)minx=$2; if($2>maxx)maxx=$2;
     if($3<miny)miny=$3; if($3>maxy)maxy=$3;
     if($4<minz)minz=$4; if($4>maxz)maxz=$4}
  END{printf "  X: %.4f..%.4f  center=%.4f  range=%.4f\n",minx,maxx,(minx+maxx)/2,maxx-minx;
      printf "  Y: %.4f..%.4f  center=%.4f  range=%.4f\n",miny,maxy,(miny+maxy)/2,maxy-miny;
      printf "  Z: %.4f..%.4f  center=%.4f  range=%.4f\n",minz,maxz,(minz+maxz)/2,maxz-minz}' "$OBJ"

echo "=== Left hinge column (X < 0.09): Y/Z spread -> pivot axis ==="
awk '/^v / && $2<0.09 {n++; if(n==1){miny=maxy=$3;minz=maxz=$4}
     if($3<miny)miny=$3; if($3>maxy)maxy=$3; if($4<minz)minz=$4; if($4>maxz)maxz=$4}
  END{printf "  count=%d  Y: %.4f..%.4f (c=%.4f)  Z: %.4f..%.4f\n",n,miny,maxy,(miny+maxy)/2,minz,maxz}' "$OBJ"

echo "=== Right hinge column (X > 0.90): Y/Z spread -> pivot axis ==="
awk '/^v / && $2>0.90 {n++; if(n==1){miny=maxy=$3;minz=maxz=$4}
     if($3<miny)miny=$3; if($3>maxy)maxy=$3; if($4<minz)minz=$4; if($4>maxz)maxz=$4}
  END{printf "  count=%d  Y: %.4f..%.4f (c=%.4f)  Z: %.4f..%.4f\n",n,miny,maxy,(miny+maxy)/2,minz,maxz}' "$OBJ"

echo "=== Primitive counts ==="
printf "  v : %s\n" "$(grep -c '^v '  "$OBJ")"
printf "  vn: %s\n" "$(grep -c '^vn ' "$OBJ")"
printf "  f : %s\n" "$(grep -c '^f '  "$OBJ")"
printf "  o : %s\n" "$(grep -c '^o '  "$OBJ")"

echo
echo "=== Per-group X extents (attribute faces to their 'g' group) ==="
awk '
  /^v / { vx[++nv]=$2 }                       # store vertex X (1-indexed)
  /^g / { grp=$0; sub(/^g /,"",grp) }
  /^f / {
    for(i=2;i<=NF;i++){
      s=$i; sub(/\/.*/,"",s); idx=s+0;
      x=vx[idx];
      if(!(grp in seen)){ seen[grp]=1; mn[grp]=x; mx[grp]=x }
      if(x<mn[grp])mn[grp]=x; if(x>mx[grp])mx[grp]=x;
      cnt[grp]++
    }
  }
  END{ for(g in seen) printf "  %-20s X: %.4f .. %.4f  (center %.4f)  refs=%d\n",g,mn[g],mx[g],(mn[g]+mx[g])/2,cnt[g] }
' "$OBJ"

echo
echo "=== Grey hinge-tube material faces: X extent (usemtl grey 0.647) ==="
awk '
  /^v / { vx[++nv]=$2 }
  /^usemtl / { m=($2 ~ /^0.647/) }
  /^f / { if(m){ for(i=2;i<=NF;i++){ s=$i; sub(/\/.*/,"",s); x=vx[s+0];
           if(n++==0){mn=mx=x} if(x<mn)mn=x; if(x>mx)mx=x } } }
  END{ printf "  tube X: %.4f .. %.4f  refs=%d\n",mn,mx,n }
' "$OBJ"

echo
echo "=== Edge-knuckle centroids (pivot axis location, OBJ units) ==="
awk '/^v / {
    if($2<0.095){lx+=$2; ly+=$3; lz+=$4; ln++}
    if($2>0.90){rx+=$2; ry+=$3; rz+=$4; rn++}
  }
  END{
    lcx=lx/ln; lcy=ly/ln;
    rcx=rx/rn; rcy=ry/rn;
    printf "  LEFT  pin centroid: X=%.4f Y=%.4f  (n=%d)\n", lcx,lcy,ln;
    printf "  RIGHT pin centroid: X=%.4f Y=%.4f  (n=%d)\n", rcx,rcy,rn;
    printf "  segment center X = %.4f\n", (lcx+rcx)/2;
    printf "  pin-to-pin period = %.4f units\n", rcx-lcx;
    printf "  half-span from center = %.4f units  (= 496.213 mm real)\n", (rcx-lcx)/2;
    printf "  => scale: %.5f units per real metre;  1 unit = %.4f m\n", ((rcx-lcx)/2)/0.496213, 0.496213/((rcx-lcx)/2);
    printf "  => vertical period 1320 mm = %.4f units\n", 1.320*(((rcx-lcx)/2)/0.496213);
  }' "$OBJ"

echo
echo "=== Precise pin X via bbox-center of outer knuckle slabs ==="
awk '/^v / {
    if(nv++==0){minx=maxx=$2}
    if($2<minx)minx=$2; if($2>maxx)maxx=$2; X[nv]=$2
  }
  END{
    # tight slab = outer 15 mm of each end
    lo0=minx; lo1=minx+0.015; hi1=maxx; hi0=maxx-0.015;
    for(i=1;i<=nv;i++){
      if(X[i]<=lo1){ if(lc++==0){lmn=lmx=X[i]} if(X[i]<lmn)lmn=X[i]; if(X[i]>lmx)lmx=X[i] }
      if(X[i]>=hi0){ if(rc++==0){rmn=rmx=X[i]} if(X[i]<rmn)rmn=X[i]; if(X[i]>rmx)rmx=X[i] }
    }
    lpin=(lmn+lmx)/2; rpin=(rmn+rmx)/2; ctr=(lpin+rpin)/2;
    printf "  left  slab X %.4f..%.4f  pin=%.4f\n", lmn,lmx,lpin;
    printf "  right slab X %.4f..%.4f  pin=%.4f\n", rmn,rmx,rpin;
    printf "  center=%.4f  period(pin-to-pin)=%.4f  halfspan=%.4f\n", ctr, rpin-lpin, (rpin-lpin)/2;
  }' "$OBJ"

echo
echo "=== Matched symmetric knuckle windows (precise pin centers) ==="
awk '/^v / { n++; X[n]=$2; Y[n]=$3
    if(n==1){mnx=mxx=$2}
    if($2<mnx)mnx=$2; if($2>mxx)mxx=$2 }
  END{
    w=0.020;                       # 20 mm window at each outer edge
    lLo=mnx; lHi=mnx+w; rHi=mxx; rLo=mxx-w;
    for(i=1;i<=n;i++){
      if(X[i]>=lLo && X[i]<=lHi){ lsx+=X[i]; lsy+=Y[i]; lc++ }
      if(X[i]>=rLo && X[i]<=rHi){ rsx+=X[i]; rsy+=Y[i]; rc++ }
    }
    lpx=lsx/lc; rpx=rsx/rc; ctr=(lpx+rpx)/2; per=rpx-lpx;
    printf "  window w=%.3f  (left n=%d, right n=%d)\n", w, lc, rc;
    printf "  LEFT  pin X=%.5f  Y=%.5f\n", lpx, lsy/lc;
    printf "  RIGHT pin X=%.5f  Y=%.5f\n", rpx, rsy/rc;
    printf "  center=%.5f   period=%.5f   half=%.5f units\n", ctr, per, per/2;
    printf "  => 1 unit = %.4f mm ;  period in mm = %.2f (target 992.426)\n", 496.213/(per/2), per*496.213/(per/2);
  }' "$OBJ"

echo
echo "=== Segment center from highest-Z points ==="
awk '/^v / { n++; X[n]=$2; Y[n]=$3; Z[n]=$4; if(n==1||$4>mz) mz=$4 }
  END{
    tol=0.002;                       # points within 2 mm of the top
    for(i=1;i<=n;i++) if(Z[i] >= mz-tol){ sx+=X[i]; sy+=Y[i]; c++;
        if(c==1){mnx=mxx=X[i]} if(X[i]<mnx)mnx=X[i]; if(X[i]>mxx)mxx=X[i] }
    printf "  maxZ=%.5f   top-point count=%d\n", mz, c;
    printf "  top X range %.5f..%.5f\n", mnx, mxx;
    printf "  CENTER  X=%.5f  Y=%.5f  (mean of top points)\n", sx/c, sy/c;
    printf "  => LEFT pin X=%.5f   RIGHT pin X=%.5f\n", sx/c-0.496213, sx/c+0.496213;
  }' "$OBJ"

echo
echo "=== glTF inspection ==="
GLTF="/Users/lee/Viewer/hinge_obj/Hinge Hexagon.gltf"
python3 - "$GLTF" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print("asset:", d.get("asset"))
print("scenes:", len(d.get("scenes",[])), " nodes:", len(d.get("nodes",[])),
      " meshes:", len(d.get("meshes",[])), " materials:", len(d.get("materials",[])),
      " accessors:", len(d.get("accessors",[])), " buffers:", len(d.get("buffers",[])))
# buffer embedded?
for i,b in enumerate(d.get("buffers",[])):
    uri=b.get("uri","")
    print(f"  buffer{i}: len={b.get('byteLength')} uri={'<embedded base64>' if uri.startswith('data:') else uri[:40]}")
# materials
for i,m in enumerate(d.get("materials",[])[:8]):
    pbr=m.get("pbrMetallicRoughness",{})
    print(f"  mat{i}: name={m.get('name')!r} baseColor={pbr.get('baseColorFactor')}")
# overall position bbox from accessors that have min/max of len 3
xs=[];ys=[];zs=[]
for a in d.get("accessors",[]):
    mn,mx=a.get("min"),a.get("max")
    if mn and mx and len(mn)==3:
        xs+= [mn[0],mx[0]]; ys+=[mn[1],mx[1]]; zs+=[mn[2],mx[2]]
if xs:
    print("POS bbox  X:%.4f..%.4f  Y:%.4f..%.4f  Z:%.4f..%.4f"%(min(xs),max(xs),min(ys),max(ys),min(zs),max(zs)))
    print("ranges    X:%.4f  Y:%.4f  Z:%.4f"%(max(xs)-min(xs),max(ys)-min(ys),max(zs)-min(zs)))
# node transforms (scale?)
for i,n in enumerate(d.get("nodes",[])[:5]):
    print(f"  node{i}: name={n.get('name')!r} scale={n.get('scale')} matrix={'yes' if 'matrix' in n else None} mesh={n.get('mesh')}")
PY
