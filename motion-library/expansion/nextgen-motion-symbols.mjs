// SPDX-License-Identifier: MIT
// Original vector lettering and icon motion authored for the local Canvas2D SDK.
const BG = '#08111f';
const CYAN = '#67e8f9';
const VIOLET = '#a78bfa';
const WHITE = '#dbeafe';
const GOLD = '#fcd34d';
const GREEN = '#6ee7b7';
const SLATE = '#334b6b';
const TAU = 2 * Math.PI;
const SOURCE = 'motion-library/expansion/nextgen-motion-symbols.mjs';

const range = n => Array.from({length:n}, (_, i) => i);
const clamp = x => Math.min(1, Math.max(0,x));
const smooth = x => clamp(x) ** 2 * (3 - 2 * clamp(x));
const mix = (a,b,t) => a + (b-a)*t;
const tween = ([a,b],[c,d],t) => [mix(a,c,t),mix(b,d,t)];
const circle = (n, radius=1, rotation=0) => range(n).map(i => [
  radius*Math.cos(rotation+i*TAU/n), radius*Math.sin(rotation+i*TAU/n),
]);
const polarShape = (n, radius, rotation=0) => circle(n,1,rotation).map(([x,y],i)=>[x*radius(i),y*radius(i)]);

const glyphs = {
  F: [[[0,1],[0,0],[1,0]],[[0,.45],[.74,.45]]],
  L: [[[0,0],[0,1],[1,1]]],
  O: [[[.26,0],[.74,0],[1,.26],[1,.74],[.74,1],[.26,1],[0,.74],[0,.26],[.26,0]]],
  W: [[[0,0],[.2,1],[.5,.55],[.8,1],[1,0]]],
  G: [[[.96,.18],[.72,0],[.25,0],[0,.28],[0,.74],[.26,1],[.8,1],[.99,.74],[.99,.54],[.54,.54]]],
  A: [[[0,1],[.51,0],[1,1]],[[.23,.59],[.77,.59]]],
  I: [[[.5,0],[.5,1]],[[.1,0],[.9,0]],[[.1,1],[.9,1]]],
  E: [[[1,0],[0,0],[0,1],[1,1]],[[0,.5],[.82,.5]]],
};

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

function transforms(index, word, d, x=.48, y=.5, width=.124, height=.195) {
  const center = x+d.direction*(index-(word.length-1)/2)*width*1.39;
  return ([a,b])=>[center+d.direction*width*(a-.5),y+height*(b-.5)];
}

function letters(d,word,callback) {
  for (const [index,symbol] of [...word].entries()) callback(glyphs[symbol],index,word);
}

function prefix(points, fraction) {
  const n = clamp(fraction) * (points.length - 1);
  if (n <= 0) return [];
  const whole = Math.floor(n);
  const result = points.slice(0, whole+1);
  if (whole+1 < points.length && n > whole) result.push(tween(points[whole],points[whole+1],n-whole));
  return result;
}

function samplePath(path,count) {
  const lens = path.slice(1).map(([x,y],i)=>Math.hypot(x-path[i][0],y-path[i][1]));
  const length = lens.reduce((sum,len)=>sum+len,0);
  return range(count).map(index=>{
    let remaining = length*index/(count-1);
    let edge=0;
    while (edge<lens.length-1 && remaining>lens[edge]) remaining-=lens[edge++];
    return tween(path[edge],path[edge+1],remaining/lens[edge]);
  });
}

function assembly(d,t) {
  letters(d,'GAIE',(strokes,i,word)=>{
    const phase = smooth(t*1.26-i*.075), angle = (1-phase)*(i%2 ? 1:-1)*.72;
    const place = transforms(i,word,d,.465+(1-phase)*.07,.5+(1-phase)*(i%2 ? .27:-.27));
    for (const path of strokes) d.path(path.map(([x,y])=>{
      const a=x-.5,b=y-.5;
      return place([.5+a*Math.cos(angle)-b*Math.sin(angle),.5+a*Math.sin(angle)+b*Math.cos(angle)]);
    }),i%2 ? CYAN:VIOLET,3.4, .6+.4*phase);
  });
}

function materialize(d,t) {
  letters(d,'FLOW',(strokes,i,word)=>{
    const reveal = clamp(t*3.7-i*.6+.37);
    const place = transforms(i,word,d,.465,.485);
    for (const stroke of strokes) {
      const path = stroke.map(place);
      d.path(path,SLATE,2,.62);
      const active = prefix(path,reveal);
      d.path(active,CYAN,3.8);
      if (active.length) d.dot(active.at(-1),4+Math.sin(t*Math.PI)*1.3,GOLD,.82);
    }
  });
  const x=.15+.65*t;
  d.path([[x,.34],[x,.67]],VIOLET,1,.65);
}

function depth(d,t) {
  const angle = .25+t*1.2;
  letters(d,'GAIE',(strokes,i,word)=>{
    const place=transforms(i,word,d,.453,.45,.115,.2);
    const offset=[d.direction*.045*Math.cos(angle),.048*Math.sin(angle)];
    for(const path of strokes) {
      const front=path.map(place);
      for (let layer=6;layer>0;layer--) {
        const u=layer/6;
        d.path(front.map(([x,y])=>[x+offset[0]*u,y+offset[1]*u]),VIOLET,4,.16);
      }
      for(const [x,y] of front) d.path([[x,y],[x+offset[0],y+offset[1]]],VIOLET,1.8,.8);
      d.path(front,CYAN,3.4);
    }
  });
}

function flattenGlyph(symbol) {
  const sides = glyphs[symbol].flatMap(stroke=>samplePath(stroke,8));
  return samplePath(sides,20);
}

const fromWord='FLOW';
const toWord='GAIE';
const morphFrom=[...fromWord].map(flattenGlyph);
const morphTo=[...toWord].map(flattenGlyph);
function wordMorph(d,t) {
  for(const [i,a] of morphFrom.entries()) {
    const local=smooth(t*1.22-i*.06);
    const place=transforms(i,fromWord,d,.467,.51,.12,.19);
    const next=morphTo[i];
    const moving=a.map((p,j)=>place(tween(p,next[j],local)));
    d.path(moving,CYAN,3.2,.84);
    d.dot(moving[(i+3)*3],3.7,GOLD);
  }
}

function variable(d,t) {
  // Scope is a procedural vector font with two true outline axes. No external font.
  const weight = 1.4+5.2*t;
  const width = .107 + .042*Math.sin(t*Math.PI*.92);
  letters(d,'FLOW',(strokes,i,word)=>{
    const place=transforms(i,word,d,.46,.48,width,.2);
    for(const path of strokes) {
      d.path(path.map(place),WHITE,weight);
    }
  });
  d.path([[.22,.72],[.22+.47*t,.72]],VIOLET,2.6);
  d.dot([.22+.47*t,.72],4,GOLD);
}

const dust='GAIE'.split('').map(symbol=>glyphs[symbol].flatMap(path=>samplePath(path,12)));
function dissolve(d,t) {
  for(const [i,points] of dust.entries()) {
    const place=transforms(i,'GAIE',d,.47,.51,.123,.20);
    for(const [j,p] of points.entries()) {
      const [x,y]=place(p);
      const s=smooth((t-.16*j/points.length)*1.11);
      const angle=j*2.3999632297+i*.75;
      const velocity=.024+((j*7+i*3)%19)/165;
      d.dot([x+d.direction*Math.cos(angle)*s*velocity,y+Math.sin(angle)*s*velocity+.045*s*s],
            2.6-1.25*s,j%3 ? CYAN:VIOLET,1-.51*s);
    }
  }
}

const arabic = [
  [[.77,.455],[.75,.52],[.71,.56],[.63,.57],[.58,.55],[.55,.49],[.53,.44],[.49,.43],[.459,.475],[.475,.53],
   [.52,.56],[.57,.55],[.54,.62],[.49,.683],[.433,.703]],
  [[.364,.506],[.373,.552],[.351,.622],[.305,.68],[.238,.702]],
].map(stroke=>samplePath(stroke,36));
function calligraphy(d,t) {
  // Authored curves sketch the Arabic word نور. The stroke stays right-to-left in both layout directions.
  const adjust = ([x,y])=>[d.direction === -1 ? .965-x : x-.025,y];
  for(const [i,stroke] of arabic.entries()) {
    const outline=stroke.map(adjust);
    d.path(outline,SLATE,2,.6);
    const path=prefix(outline,t*1.35-i*.69+.125);
    for(let j=1;j<path.length;j++) {
      const width=2+.9*Math.sin(j*.33)+.057*j;
      d.path([path[j-1],path[j]],CYAN,width);
    }
    if(path.length) d.dot(path.at(-1),3.3,GOLD,.9);
  }
  d.dot(adjust([.73,.398]),3.8,GOLD,smooth(t*4));
}

function perspective(d,t) {
  const angle = -1.08+t*1.7;
  letters(d,'FLOW',(strokes,i,word)=>{
    const place=transforms(i,word,d,.46,.5,.12,.19);
    for(const stroke of strokes) {
      const projected=stroke.map(place).map(([x,y])=>{
        const rx=x-.46, scale=1/(1+rx*Math.sin(angle)*1.16);
        return [.46+rx*Math.cos(angle)*scale,.5+(y-.5)*scale];
      });
      d.path(projected,CYAN,3.6);
      d.path(projected.map(([x,y])=>[x,.65+(y-.5)*.33]),VIOLET,1.5,.46);
    }
  });
}

function fluid(d,t) {
  const frequency=1.15+t*2.52, amplitude=.058*Math.sin(Math.PI*t);
  letters(d,'GAIE',(strokes,i,word)=>{
    for(const stroke of strokes) {
      const place=transforms(i,word,d,.467,.48,.127,.186);
      const line=samplePath(stroke,16).map(place).map(([x,y],n)=>[
        x+d.direction*amplitude*.57*Math.sin(n*.36+t*TAU*frequency+i),
        y+amplitude*Math.cos(x*11+t*TAU*frequency)+.023*Math.sin(t*TAU+i),
      ]);
      d.path(line,CYAN,3.1);
      d.path(line.map(([x,y])=>[x,y+.028]),VIOLET,2,.36);
    }
  });
}

const shield = [[0,-1],[.83,-.59],[.71,.36],[.37,.74],[0,1],[-.43,.69],[-.8,.35],[-.87,-.56]];
const bolt = [[.22,-1],[-.71,.17],[-.15,.17],[-.34,1],[.7,-.22],[.12,-.22]];
const diamond = [[0,-1],[1,0],[0,1],[-1,0]];
const octagon = circle(8,1,Math.PI/8);
const icon = (shape, cx=.467, cy=.48, x=.214, y=.186)=>shape.map(([u,v])=>[cx+x*u,cy+y*v]);
const STAR = polarShape(20, i=>i%4 === 0 ? 1 : i%2 ? .54 : .59,-Math.PI/2);

function extrusion(d,t) {
  const front=icon(shield,.441,.447,.19,.18);
  const dx=.023+.047*Math.cos(t*Math.PI),dy=.027+.044*Math.sin(t*Math.PI);
  const back=front.map(([x,y])=>[x+dx,y+dy]);
  d.path(back,VIOLET,3,1,true,'#273354');
  for(const [i,p] of front.entries()) {
    const j=(i+1)%front.length;
    d.path([p,front[j],back[j],back[i]],VIOLET,1.25,.8,true,i%2 ? '#23325a':'#182746');
  }
  d.path(front,CYAN,3,1,true,'#12314c');
}

function rotateShape(shape, xAngle, yAngle) {
  return shape.map(([x,y])=>{
    const side=x*Math.sin(yAngle), front=x*Math.cos(yAngle);
    const vertical=y*Math.cos(xAngle)-side*Math.sin(xAngle);
    const depth=y*Math.sin(xAngle)+side*Math.cos(xAngle);
    const factor=1/(1+depth*.33);
    return [front*factor,vertical*factor];
  });
}
function reactive(d,t,pointer) {
  const yaw=(t-.5)*1.6+pointer.x*.61, pitch=.25+pointer.y*.64;
  const outer=icon(rotateShape(octagon,pitch,yaw),.463,.49,.241,.203);
  const inner=icon(rotateShape(bolt,pitch,yaw),.463,.49,.133,.124);
  d.path(outer,VIOLET,3,1,true,'#172b4b');
  d.path(inner,CYAN,3.6,1,true,'#125472');
  const orbit=.53+t*TAU*.84;
  d.dot([.463+Math.cos(orbit)*.252,.49+Math.sin(orbit)*.215],4.6,GOLD);
}

const iconPoints=samplePath([...shield,shield[0]],82);
function reconstruct(d,t) {
  for(const [i,[x,y]] of iconPoints.entries()) {
    const phase=smooth(t*1.14-i*.106/iconPoints.length);
    const seed=i*2.3999632297;
    const loose=[.467+Math.cos(seed)*(.22+i%19*.01),.49+Math.sin(seed)*(.18+i%11*.01)];
    const point=tween(loose,[.467+x*.18,.49+y*.16],phase);
    d.dot(point,2.3+phase*.9,i%5===0 ? GOLD:CYAN,.38+.62*phase);
  }
}

function metallic(d,t) {
  const at=[.458,.48], shape=icon(diamond,...at,.207,.193), scan=(t*.88+.05);
  d.path(shape,VIOLET,2.5,1,true,'#152840');
  for(let i=1;i<18;i++) {
    const y=i/18, width=.207*(1-Math.abs(y-.5)*2), gleam=Math.exp(-(((y-scan)*7)**2));
    const shade=gleam>.6 ? WHITE : gleam>.25 ? CYAN : SLATE;
    d.path([[at[0]-width,at[1]+(y-.5)*.386],[at[0]+width,at[1]+(y-.5)*.386]],shade,1.1+gleam*3,.58+gleam*.42);
  }
  d.dot([at[0]+.08*Math.sin(t*TAU),at[1]+(scan-.5)*.282],4.8,WHITE,.85);
}

function expansion(d,t) {
  const cluster=icon(octagon,.465,.48,.146,.134);
  d.path(cluster,CYAN,2.4,1,true,'#12314c');
  for(const [i,angle] of range(5).map(i=>.22+i*TAU/5).entries()) {
    const outward=.072+.186*smooth((t+i*.029)*1.07);
    const offset=[.465+Math.cos(angle)*outward,.48+Math.sin(angle)*outward*.9];
    d.path([[.465,.48],offset],VIOLET,1.6,.72);
    d.path(icon(diamond,...offset,.029+.017*t,.025+.014*t),i%2?VIOLET:CYAN,2,1,true,'#1a2e4c');
  }
}

function objectTransform(d,t) {
  const corners=[[-.6,-.65,-.55],[.6,-.65,-.55],[.6,.65,-.55],[-.6,.65,-.55],
                 [-.6,-.65,.55],[.6,-.65,.55],[.6,.65,.55],[-.6,.65,.55]];
  const angle=.35+t*1.4, fold=smooth(t);
  const projected=corners.map(([x,y,z])=>{
    const u=x*Math.cos(angle)-z*fold*Math.sin(angle);
    const v=x*Math.sin(angle)+z*fold*Math.cos(angle);
    return [.45+.234*u/(1+.29*v),.5-.193*(y+.45*v)/(1+.29*v)];
  });
  for (const [i,face] of [[0,1,2,3],[4,5,6,7],[0,4,7,3],[0,1,5,4]].entries()) {
    d.path(face.map(id=>projected[id]),i%2?VIOLET:CYAN,2,.7,true,i%2?'#1d354e':'#152543');
  }
}

function bounce(d,t) {
  // Integrate the closed-form trajectory between contacts with a constant restitution.
  const gravity=10, restitution=.68, ground=.756;
  let time=t*1.14, velocity=2.4;
  while(time>2*velocity/gravity && velocity>.2) {
    time-=2*velocity/gravity;
    velocity*=restitution;
  }
  const displacement = Math.max(0,velocity*time-gravity*time*time/2);
  const squash=.033*Math.exp(-displacement*17);
  const x=.248+t*.403, y=ground-.137-displacement*.67;
  d.path([[.165,ground],[.813,ground]],SLATE,2.2);
  d.path(icon(bolt,x,y,.102+squash,.131-squash),CYAN,2.6,1,true,'#1b3b5c');
  d.path([[x-.08+displacement*.04,ground+.02],[x+.08-displacement*.04,ground+.02]],VIOLET,2,.8);
}

function illumination(d,t) {
  const shieldFace=icon(shield,.596,.48,.145,.18);
  const light=[.19,.19+.534*t];
  const hits = shieldFace.filter((_,i)=>i>4 || i===0);
  for (const [i,target] of hits.entries()) {
    const mid=tween(light,target,.6);
    d.path([light,[target[0],target[1]-.051],target,[target[0],target[1]+.05]],undefined,0,.16,true,i%2?VIOLET:CYAN);
    d.dot(mid,3.2,CYAN,.5);
  }
  d.dot(light,24,'#215078',.6);
  d.dot(light,12,CYAN,.76);
  d.dot(light,4.5,WHITE);
  d.path(shieldFace,CYAN,2.8,1,true,'#1a354c');
  d.path(icon(diamond,.596,.48,.076,.081),VIOLET,2.4,.9,true);
}

function morphIcon(d,t,pointer) {
  const base=circle(20,1,-Math.PI/2);
  const phase=smooth(t+pointer.x*.21+pointer.y*.16);
  const shape=base.map((p,i)=>tween(p,STAR[i],phase));
  d.path(icon(shape,.453,.481,.204,.195),CYAN,3.6,1,true,'#152e4c');
  d.path(icon(shape,.453,.481,.14,.136),VIOLET,2,.62,true);
  d.dot([.453+.2*Math.cos(t*TAU),.481+.153*Math.sin(t*TAU)],4.6,GOLD);
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
  ['typography-kinetic-assembly','Kinetic Typography Assembly','تجميع الحروف الحركي','Vector letters converge from independent rotations and offsets.',assembly],
  ['typography-letter-materialization','Letter-by-Letter Materialization','ظهور الحروف بالتتابع','A timed reveal traces each letter against its ghost outline.',materialize],
  ['typography-depth-extrusion','Typography Depth Extrusion','بثق الحروف','Repeated depth slices and connected edges produce dimensional lettering.',depth],
  ['typography-word-morph','Cinematic Word Morph','تحوّل كلمة سينمائي','Equal arc-length samples interpolate between two words locally.',wordMorph],
  ['typography-variable-font','Variable Font Transformation','تحوّل خط متغيّر','A procedural vector alphabet changes stroke weight and width continuously.',variable],
  ['typography-particle-dissolve','Typography Particle Dissolve','تلاشي الحروف بالجسيمات','Seeded stroke samples separate under a staged particle trajectory.',dissolve],
  ['typography-calligraphy-path','Arabic Calligraphy Path Reveal','رسم مسار الخط العربي','An original Arabic path traces the word نور with a varying stroke.',calligraphy],
  ['typography-perspective-projection','Perspective Text Projection','إسقاط الحروف المنظوري','A yawing plane projects letters and a foreshortened reflection.',perspective],
  ['typography-fluid-reformation','Fluid Text Reformation','إعادة تشكيل الحروف بانسياب','Analytic wave deformation displaces vector strokes and relaxes as the timeline ends.',fluid],
  ['icons-extrusion','Three-dimensional Icon Extrusion','بثق أيقونة ثلاثية الأبعاد','Connected front and back silhouettes reveal an extruded shield.',extrusion],
  ['icons-reactive-rotation','Reactive Icon Rotation','دوران أيقونة تفاعلي','Pointer position adjusts the yaw and pitch of projected icon planes.',reactive],
  ['icons-particle-reconstruction','Icon Particle Reconstruction','إعادة بناء الأيقونة بالجسيمات','Distributed particles gather on arc-length samples of an icon perimeter.',reconstruct],
  ['icons-metallic','Animated Metallic Icon','أيقونة معدنية متحركة','A moving analytic highlight models a metallic reflection within a clipped diamond.',metallic],
  ['icons-spatial-expansion','Spatial Icon Expansion','توسّع الأيقونة مكانيًا','Nested satellite icons expand radially along structural connectors.',expansion],
  ['icons-object-transformation','Icon-to-Object Transformation','تحويل الأيقونة إلى جسم','Flat geometry gains depth and unfolds into projected box faces.',objectTransform],
  ['icons-physics-bounce','Physics-based Icon Bounce','ارتداد أيقونة فيزيائي','A ballistic trajectory conserves time between contacts and loses energy at each bounce.',bounce],
  ['icons-volumetric-illumination','Volumetric Icon Illumination','إضاءة الأيقونة الحجمية','Schematic widening beam volumes radiate from a moving source to the shield silhouette.',illumination],
  ['icons-morphing','Interactive Icon Morphing','تحوّل الأيقونة التفاعلي','An equally sampled contour morph responds to pointer position and timeline.',morphIcon],
  ['icons-multi-state','Multi-state 3D Icon Transition','انتقال أيقونة ثلاثية الأبعاد بين الحالات','A turning projected badge displays pending, confirmed and review glyphs.',statusIcon],
];

const renderers = new Map(pieces.map(([id,,,,render])=>[id,render]));
export const definitions=Object.freeze(pieces.map(([id,name_en,name_ar,mechanism])=>Object.freeze({
  id,name_en,name_ar,mechanism,engine:'canvas2d',duration_ms:3600,
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
