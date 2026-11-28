// SPDX-License-Identifier: MIT
// Original vector lettering and icon motion authored for the local Canvas2D SDK.
// Ported from origin/codex/nextgen-intelligence (da3af05): the status icon only. The nine lettering and
// nine other icon studies show no digital meaning (docs/evidence/ported-motions.json).
const BG = '#08111f';
const CYAN = '#67e8f9';
const VIOLET = '#a78bfa';
const GOLD = '#fcd34d';
const GREEN = '#6ee7b7';
const SLATE = '#334b6b';
const TAU = 2 * Math.PI;
const SOURCE = 'motion-library/expansion/nextgen-motion-symbols.mjs';

const range = n => Array.from({length:n}, (_, i) => i);
const clamp = x => Math.min(1, Math.max(0,x));
const mix = (a,b,t) => a + (b-a)*t;
const circle = (n, radius=1, rotation=0) => range(n).map(i => [
  radius*Math.cos(rotation+i*TAU/n), radius*Math.sin(rotation+i*TAU/n),
]);

function draw(width,height,rtl,primitives) {
  const unit = Math.min(width,height) / 360;
  const direction = rtl ? -1 : 1;
  const point = ([x,y]) => ({x: (rtl ? 1-x : x)*width, y:y*height});
  const path = (points, stroke=CYAN, lineWidth=2.5, opacity=1, closed=false, fill) => {
    if (points.length < 2) return;
    primitives.push({type:'polyline',points:points.map(point),stroke,lineWidth:lineWidth*unit,opacity,closed,fill});
  };
  const dot = (at,r,fill=CYAN,opacity=1,stroke) => {
    primitives.push({type:'circle',...point(at),r:r*unit,fill,opacity,stroke,lineWidth:1.5*unit});
  };
  return {path,dot,direction};
}

const octagon = circle(8,1,Math.PI/8);
const icon = (shape, cx=.467, cy=.48, x=.214, y=.186)=>shape.map(([u,v])=>[cx+x*u,cy+y*v]);

function rotateShape(shape, xAngle, yAngle) {
  return shape.map(([x,y])=>{
    const side=x*Math.sin(yAngle), front=x*Math.cos(yAngle);
    const vertical=y*Math.cos(xAngle)-side*Math.sin(xAngle);
    const depth=y*Math.sin(xAngle)+side*Math.cos(xAngle);
    const factor=1/(1+depth*.33);
    return [front*factor,vertical*factor];
  });
}

function statusIcon(d,t) {
  const stage=Math.min(2,Math.floor(t*3)), face=[.463,.475];
  const spin=t*TAU;
  const appearance = [CYAN,GREEN,GOLD][stage];
  const rim=icon(rotateShape(octagon,.34,spin),...face,.234,.217);
  d.path(rim,VIOLET,2.6,1,true,'#152d4a');
  if(stage===0) {
    d.path(icon(circle(18,1,spin).slice(0,13),...face,.101,.095),appearance,3.1);
  } else if(stage===1) {
    d.path(icon([[-.8,.12],[-.19,.72],[.85,-.66]],...face,.116,.103),appearance,4);
  } else {
    d.path(icon([[0,-.86],[.93,.66],[-.91,.66]],...face,.104,.119),appearance,2.5,1,true);
    d.path([[face[0],face[1]-.043],[face[0],face[1]+.003]],appearance,2.7);
    d.dot([face[0],face[1]+.033],2.6,appearance);
  }
  for(const i of range(3)) d.dot([.402+.061*i,.779],i===stage?5.2:3.3,i===stage?appearance:SLATE);
}

const pieces = [
  ['icons-multi-state','Multi-state 3D Icon Transition','انتقال أيقونة ثلاثية الأبعاد بين الحالات','A turning projected badge displays pending, confirmed and review glyphs.',statusIcon],
];

// The digital meaning of each motion (governance/policies/motion-purpose.json), written when it was
// ported from origin/codex/nextgen-intelligence; the source branch stated none.
const meanings = {
  'icons-multi-state': {en: 'A request\'s status badge: it shows pending, then confirmed, then needs review, and a dot marks the current state.', ar: 'شارة حالة الطلب: تُظهر قيد الانتظار ثم مؤكَّد ثم يحتاج إلى مراجعة، وتحدد نقطةٌ الحالة الحالية.'},
};
if (pieces.some(([id]) => !meanings[id])) throw new Error('Every symbol motion states its digital meaning');
const renderers = new Map(pieces.map(([id,,,,render])=>[id,render]));
export const definitions=Object.freeze(pieces.map(([id,name_en,name_ar,mechanism])=>Object.freeze({
  id,name_en,name_ar,mechanism,meaning:Object.freeze({...meanings[id]}),engine:'canvas2d',duration_ms:3600,
  license:'MIT',license_file:'motion-library/expansion/LICENSE',
  implementation_status:'implemented-source',runtime_status:'requires-current-source-bound-proof',
  source:Object.freeze({module:SOURCE}),
  reduced_motion:Object.freeze({mode:'static-poster',progress:.55}),
  mobile:Object.freeze({requires_real_device_verification:true}),
  semantics:'Original procedural vector art. The illumination and fluid illustrations use analytic geometry.',
})));

const numeric = (x,min,max)=>typeof x==='number'&&Number.isFinite(x)&&x>=min&&x<=max;
export function sampleMotion(value,progress,options={}) {
  const id=typeof value==='string'?value:value?.id;
  const renderer=renderers.get(id);
  if (!renderer || !numeric(progress,-1e7,1e7)) throw new RangeError('Unknown symbol motion or invalid progress');
  const {width=640,height=360,intensity=1,rtl=false,reducedMotion=false,interaction={x:0,y:0}}=options;
  if (!numeric(width,120,4096)||!numeric(height,90,4096)||!numeric(intensity,0,1)
      || typeof rtl!=='boolean'||typeof reducedMotion!=='boolean'
      || !numeric(interaction?.x,-1,1)||!numeric(interaction?.y,-1,1)) {
    throw new RangeError('Invalid symbol motion options');
  }
  const time=reducedMotion ? .55 : clamp(progress);
  const primitives=[];
  renderer(draw(width,height,rtl,primitives),mix(.5,time,intensity),reducedMotion ? {x:0,y:0} : interaction);
  return {width,height,background:BG,primitives,meta:{id,progress:time,engine:'canvas2d',reducedMotion}};
}
