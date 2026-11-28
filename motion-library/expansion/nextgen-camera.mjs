// SPDX-License-Identifier: MIT
// Original perspective-camera scenes; CPU projection drawn by the existing SDK.
// No Three.js/WebGL/WebGPU or measured digital-twin connection is implied.
const specs = [
  ['camera-infinite-flythrough','Infinite Camera Flythrough','تحليق كاميرا مستمر','Repeated 3D portal planes pass the near clip plane under forward camera travel.'],
  ['camera-drone-approach','Cinematic Drone Approach','اقتراب سينمائي جوي','A descending forward camera projects a fixed city grid and its roof geometry.'],
  ['camera-macro-to-micro','Macro-to-Micro Transition','انتقال من الكبير إلى الدقيق','A perspective dolly crosses scales while nested structure replaces the outer subject.'],
];
export const definitions = Object.freeze(specs.map(([id,name_en,name_ar,mechanism]) => Object.freeze({
  id,name_en,name_ar,mechanism,engine:'canvas2d',duration_ms:3600,
  license:'MIT',license_file:'motion-library/expansion/LICENSE',
  implementation_status:'implemented-source',runtime_status:'requires-current-source-bound-proof',
  source:{module:'motion-library/expansion/nextgen-camera.mjs'},
  reduced_motion:{mode:'static-poster',progress:.55},
  mobile:{requires_real_device_verification:true},
  semantics:'Illustrative original 3D geometry projected on the CPU into Canvas2D. No physical or live-data claim.',
})));
const ids = new Set(definitions.map(d=>d.id));
const num=(v,min,max)=>typeof v==='number'&&Number.isFinite(v)&&v>=min&&v<=max;
const clamp=v=>Math.max(0,Math.min(1,v));
const edgePairs=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
export function sampleMotion(value,progress,options={}) {
  const id=typeof value==='string'?value:value?.id;
  if(!ids.has(id)||!num(progress,-1e7,1e7)) throw new RangeError('Unknown camera or invalid progress');
  const {width=640,height=360,intensity=1,rtl=false,reducedMotion=false}=options;
  if(!num(width,120,4096)||!num(height,90,4096)||!num(intensity,0,1)||typeof rtl!=='boolean'||typeof reducedMotion!=='boolean') throw new RangeError('Invalid camera options');
  const p=reducedMotion?.55:clamp(progress), t=.5+(p-.5)*intensity;
  const primitives=[];
  let camera;
  if(id==='camera-infinite-flythrough') camera={x:.22*Math.sin(t*6),y:.15*Math.sin(t*4),z:t*8,pitch:0};
  else if(id==='camera-drone-approach') camera={x:1.2-1.1*t,y:5.5-4.2*t,z:-9+6*t,pitch:-.3+.18*t};
  else camera={x:0,y:0,z:-8+7.65*t,pitch:0};
  const unit=Math.min(width,height)*.85;
  const project=([x,y,z])=>{
    const dy=y-camera.y,dz=z-camera.z;
    const cy=dy*Math.cos(camera.pitch)-dz*Math.sin(camera.pitch);
    const cz=dy*Math.sin(camera.pitch)+dz*Math.cos(camera.pitch);
    return {cx:x-camera.x,cy,cz};
  };
  const screen=a=>({x:width*.5+(rtl?-1:1)*a.cx/a.cz*unit,y:height*.5-a.cy/a.cz*unit});
  const line=(a,b,color='#67e8f9',opacity=1)=>{
    a=project(a); b=project(b);
    const near=.12;
    if(a.cz<near&&b.cz<near) return;
    if(a.cz<near||b.cz<near){
      const [behind,front]=a.cz<near?[a,b]:[b,a], u=(near-behind.cz)/(front.cz-behind.cz);
      const clipped={cx:behind.cx+(front.cx-behind.cx)*u,cy:behind.cy+(front.cy-behind.cy)*u,cz:near};
      if(a.cz<near)a=clipped;else b=clipped;
    }
    const aa=screen(a),bb=screen(b);
    // Clip projected lines to the viewport (Liang-Barsky), bounding exported geometry.
    let lo=0,hi=1;const dx=bb.x-aa.x,dy=bb.y-aa.y;
    for(const [q,r] of [[-dx,aa.x],[dx,width-aa.x],[-dy,aa.y],[dy,height-aa.y]]){
      if(q===0){if(r<0)return;continue;}const u=r/q;
      if(q<0)lo=Math.max(lo,u);else hi=Math.min(hi,u);
      if(lo>hi)return;
    }
    primitives.push({type:'line',x1:aa.x+lo*dx,y1:aa.y+lo*dy,x2:aa.x+hi*dx,y2:aa.y+hi*dy,stroke:color,lineWidth:1.5,opacity});
  };
  const box=(x,y,z,sx,sy,sz,color)=>{
    const v=[[x,y,z],[x+sx,y,z],[x+sx,y+sy,z],[x,y+sy,z],[x,y,z+sz],[x+sx,y,z+sz],[x+sx,y+sy,z+sz],[x,y+sy,z+sz]];
    edgePairs.forEach(([a,b])=>line(v[a],v[b],color));
  };
  if(id==='camera-infinite-flythrough'){
    for(let n=0;n<18;n++){
      const z=n*1.2;
      const ring=[[-1.8,-1.2,z],[1.8,-1.2,z],[1.8,1.2,z],[-1.8,1.2,z]];
      for(let k=0;k<4;k++)line(ring[k],ring[(k+1)%4],n%2?'#a78bfa':'#67e8f9',.85);
    }
    for(const x of [-1.8,1.8])for(const y of [-1.2,1.2])line([x,y,0],[x,y,22],'#64748b',.6);
  }else if(id==='camera-drone-approach'){
    for(let x=-4;x<=4;x++)for(let z=0;z<8;z++){
      const h=.3+((x*x+z*7)%9)*.13;
      box(x*1.1,-1,z*1.3,.65,h,.65,z%2?'#a78bfa':'#67e8f9');
    }
    for(let x=-5;x<=5;x++)line([x,-1,0],[x,-1,12],'#334155');
  }else{
    // Nested cages retain world-space coordinates as camera depth closes in;
    // smaller cages emerge naturally under perspective instead of opacity swaps.
    for(let layer=0;layer<6;layer++){
      const s=1.5*Math.pow(.33,layer);
      box(-s,-s,0,s*2,s*2,s*2,layer%2?'#a78bfa':'#67e8f9');
      for(let i=-2;i<=2;i++)line([i*s*.4,-s,0],[i*s*.4,s,0],'#334155');
    }
  }
  return {width,height,background:'#08111f',primitives,
    meta:{id,progress:p,engine:'canvas2d',projection:'CPU perspective with near-plane and viewport clipping',camera,reducedMotion}};
}
