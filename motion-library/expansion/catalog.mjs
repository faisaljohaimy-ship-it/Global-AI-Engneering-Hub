/**
 * Additive original motion recipes: 200 independent base mechanisms and 200
 * coupled compositions. Runtime: portable Canvas2D reference scenes only.
 * Browser verification is an external receipt, never a prefilled catalog claim.
 */
import {families} from './families.mjs';
import {systems} from './systems.mjs';
import {TAU,clamp,ease,mix,wave,noise,range,color,point,circle,line,rect,polyline,curve,transform} from './geometry.mjs';

export const VERSION = '1.0.0';
export const MAX_PRIMITIVES = 256;
export const MAX_POINTS = 160;
const allFamilies = [...families,...systems];
const familyById = new Map(allFamilies.map(f=>[f.id,f]));
const finite = value => typeof value==='number' && Number.isFinite(value);
const own = (value,key) => Object.prototype.hasOwnProperty.call(value,key);

// Every advanced recipe has two separately authored source mechanisms and one
// explicit geometric coupling. Distinct IDs never depend on color or speed.
const couplers = [
  {key:'focus-handoff',en:'Focus handoff',ar:'تبادل البؤرة',
   mechanism:'Two independent source scenes exchange foreground scale and horizontal anchor through a shared focus bridge.',
   apply:(a,b,t)=>[...transform(a,{scale:.45+.23*(1-t),dx:-.2+.12*t,dy:-.04*t}),...transform(b,{scale:.45+.23*t,dx:.2-.12*(1-t),dy:.04*(1-t)}),line(.4,.5,.6,.5,color(2,.6),.003)]},
  {key:'counter-orbit',en:'Counter-orbit coupling',ar:'اقتران المدارين المتعاكسين',
   mechanism:'Independent source formations orbit a common hub with opposite angular travel while their internal geometry continues to evolve.',
   apply:(a,b,t)=>[...transform(a,{scale:.4,dx:.2*Math.cos(t*TAU),dy:.12*Math.sin(t*TAU),angle:t*.4}),...transform(b,{scale:.4,dx:-.2*Math.cos(t*TAU),dy:-.12*Math.sin(t*TAU),angle:-t*.4}),circle(.5,.5,.012,color(2))]},
  {key:'depth-cascade',en:'Depth cascade',ar:'تتابع العمق',
   mechanism:'A source scene occupies two depth-separated planes while a different mechanism rises into the foreground plane.',
   apply:(a,b,t)=>[...transform(a,{scale:.25,dx:-.24,dy:-.14,opacity:.3}),...transform(a,{scale:.4,dx:-.1,dy:-.03,opacity:.55}),...transform(b,{scale:.55,dx:.16*ease(t),dy:.1*ease(t)})]},
  {key:'cross-axis',en:'Cross-axis passage',ar:'العبور عبر المحورين',
   mechanism:'Two source systems traverse perpendicular axes and exchange framing at their intersection rather than merely crossfading.',
   apply:(a,b,t)=>[...transform(a,{scale:.46,dx:mix(-.26,.26,ease(t)),dy:-.12}),...transform(b,{scale:.46,dx:.12,dy:mix(.26,-.26,ease(t))}),polyline([point(.18,.5),point(.5,.5),point(.5,.18)],color(2,.35),.002)]},
  {key:'signal-transfer',en:'Signal-transfer composition',ar:'تركيب نقل الإشارة',
   mechanism:'Two source scenes remain spatially separated while a packet train transfers ownership between their center anchors.',
   apply:(a,b,t)=>[...transform(a,{scale:.43,dx:-.23}),...transform(b,{scale:.43,dx:.23}),...range(7,i=>{const q=clamp(t*1.6-i*.1);return circle(mix(.3,.7,q),.5+.05*Math.sin(q*Math.PI)*wave(t,i/7),.006,color(i));})]},
  {key:'radial-triptych',en:'Radial triptych',ar:'الثلاثية الشعاعية',
   mechanism:'Two instances of one source and one different source occupy three rotating radial sectors with explicit inter-sector links.',
   apply:(a,b,t)=>{const p=range(3,i=>point(.5+.22*Math.cos(i*TAU/3+t*.3),.5+.22*Math.sin(i*TAU/3+t*.3)));return [...p.flatMap((v,i)=>transform(i===1?b:a,{scale:.29,dx:v.x-.5,dy:v.y-.5,angle:i*.1})),polyline(p,color(2,.4),.002,{closed:true})];}},
  {key:'folded-dialogue',en:'Folded dialogue',ar:'حوار اللوحتين المطويتين',
   mechanism:'Two different source scenes tilt around a shared central hinge as the open-angle resolves into a reading plane.',
   apply:(a,b,t)=>[...transform(a,{scale:.42,dx:-.2,angle:-(1-ease(t))*.45}),...transform(b,{scale:.42,dx:.2,angle:(1-ease(t))*.45}),line(.5,.24,.5,.76,color(2,.5),.002)]},
  {key:'temporal-braid',en:'Temporal braid',ar:'التضفير الزمني',
   mechanism:'Independent source scenes weave around one another with oppositely signed vertical displacement and linked centroid trajectories.',
   apply:(a,b,t)=>[...transform(a,{scale:.43,dx:-.17,dy:.17*Math.sin(t*TAU)}),...transform(b,{scale:.43,dx:.17,dy:-.17*Math.sin(t*TAU)}),polyline(curve(q=>point(.27+.46*q,.5+.17*Math.sin(t*TAU)*(1-2*q))),color(2,.4),.002)]},
  {key:'editorial-panels',en:'Editorial panels',ar:'ألواح التحرير المتتابعة',
   mechanism:'Two source systems and a smaller callback panel share a three-column editorial grid with distinct geometric framing changes.',
   apply:(a,b,t)=>[...transform(a,{scale:.3,dx:-.28,dy:.08*(1-ease(t))}),...transform(b,{scale:.3,dy:-.08*Math.sin(t*Math.PI)}),...transform(a,{scale:.2,dx:.28,dy:.08*ease(t)}),...range(3,i=>rect(.08+i*.29,.22,.25,.56,null,{stroke:color(i,.35),lineWidth:.0015}))]},
  {key:'convergent-proof',en:'Convergent proof composition',ar:'تركيب تقارب الأدلة',
   mechanism:'Two independently animated systems converge on a shared evidence spine while their internal geometries retain separate phases.',
   apply:(a,b,t)=>[...transform(a,{scale:mix(.38,.3,ease(t)),dx:mix(-.24,-.14,ease(t)),dy:-.05}),...transform(b,{scale:mix(.38,.3,ease(t)),dx:mix(.24,.14,ease(t)),dy:.05}),line(.25,.8,.75,.8,color(2),.004),...range(5,i=>line(.25+i*.125,.77,.25+i*.125,.83,color(i),.002))]}
];

function deepFreeze(value) {
  if(value && typeof value==='object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

const parameters = {
  duration_ms:{type:'number',minimum:100,maximum:10000,default:2400},
  intensity:{type:'number',minimum:0,maximum:1,default:1},
  detail:{type:'integer',minimum:6,maximum:24,default:18},
  seed:{type:'integer',minimum:0,maximum:2147483647,default:1,semantics:'Deterministic bounded composition offset, not a physical randomness or model-inference claim.'},
  interaction:{type:'object',properties:{x:{minimum:-1,maximum:1},y:{minimum:-1,maximum:1}},default:{x:0,y:0}}
};
const makeDefinition = (family,index,tier) => {
  const source = family.recipes[index];
  const coupler = couplers[index];
  const otherFamily = allFamilies[(allFamilies.indexOf(family)+index+1)%allFamilies.length];
  const otherIndex = (index*3+2)%10;
  const secondary = otherFamily.recipes[otherIndex];
  const id = `os-${family.id}-${tier==='basic'?'b':'a'}${String(index+1).padStart(2,'0')}`;
  return {
    id,name_en:tier==='basic'?source.name_en:`${source.name_en} / ${coupler.en} / ${secondary.name_en}`,
    name_ar:tier==='basic'?source.name_ar:`${source.name_ar} — ${coupler.ar} — ${secondary.name_ar}`,
    category:family.id,category_id:family.id,category_name_en:family.name_en,category_name_ar:family.name_ar,
    tier,duration_ms:tier==='basic'?2400:3600,engine:'canvas2d',rendering_engine:'Canvas2D portable reference',
    mechanism:tier==='basic'?source.mechanism:coupler.mechanism,
    algorithm:source.key,
    source:{module:`motion-library/expansion/${families.includes(family)?'families':'systems'}.mjs`,export:'families/systems',family:family.id,recipe:source.key},
    composition:tier==='advanced'?{coupling:coupler.key,secondary_family:otherFamily.id,secondary_recipe:secondary.key,secondary_index:otherIndex,secondary_phase:'ease(0.15 + 0.7 * progress)',source_count:2}:null,
    parameters,
    mobile:{compatible:true,maximum_detail:18,device_pixel_ratio_cap:2,requires_real_device_verification:true},
    direction:{rtl:'mirror all geometry and swap text alignment without reversing content',ltr:'authored logical geometry'},
    gpu:{required:false,api:'none',note:'CPU-computed Canvas2D scene. Optional browser acceleration is not an engine availability claim.'},
    reduced_motion:{mode:'static-poster',progress:.65,alternative:'Render one stable representative scene, independent of requested time.'},
    license:'MIT',license_file:'motion-library/expansion/LICENSE',
    source_provenance:'Original additive implementation, not recovered legacy source or private media.',
    implementation_status:'implemented-source',runtime_status:'pending-browser-evidence',
    automated_test:'tests/test_motion_expansion.mjs',
    performance_benchmark:'tests/test_motion_studio_browser.mjs',
    operational_evidence:{path:'motion-library/expansion/evidence/browser.json',entry:id,status:'requires-current-receipt'},
    interactive_preview:`motion-studio/index.html?motion=${id}`,
    integration_example:`motion-library/expansion/examples.mjs#${id}`,
    variant_policy:'Color, duration, intensity, detail and seed settings are parameters, not additional component IDs.',
    data_semantics:'Illustrative visual model. No real model inference, live sensor connection, measured business result or physical simulation is claimed.'
  };
};

export const definitions = deepFreeze(allFamilies.flatMap(f=>[
  ...f.recipes.map((_,i)=>makeDefinition(f,i,'basic')),
  ...f.recipes.map((_,i)=>makeDefinition(f,i,'advanced'))
]));
const definitionById = new Map(definitions.map(d=>[d.id,d]));

export function getDefinition(id) {
  if(typeof id!=='string' || !definitionById.has(id)) throw new RangeError('Unknown motion ID');
  return definitionById.get(id);
}

function optionsFor(options) {
  if(!options || typeof options!=='object' || Array.isArray(options)) throw new TypeError('Options must be an object');
  const number = (key,defaultValue,min,max,integer=false) => {
    const v=own(options,key)?options[key]:defaultValue;
    if(!finite(v) || v<min || v>max || (integer && !Number.isInteger(v))) throw new RangeError(`Invalid ${key}`);
    return v;
  };
  const width=number('width',640,120,4096),height=number('height',360,90,4096);
  const interaction=options.interaction??{x:0,y:0};
  if(!interaction || typeof interaction!=='object' || Array.isArray(interaction)) throw new TypeError('Invalid interaction');
  const x=interaction.x??0,y=interaction.y??0;
  if(!finite(x)||!finite(y)||Math.abs(x)>1||Math.abs(y)>1) throw new RangeError('Invalid interaction coordinates');
  for(const key of ['rtl','reducedMotion']) if(own(options,key)&&typeof options[key]!=='boolean') throw new TypeError(`Invalid ${key}`);
  return {width,height,intensity:number('intensity',1,0,1),detail:number('detail',18,6,24,true),
          seed:number('seed',1,0,2147483647,true),interaction:{x,y},rtl:options.rtl??false,reducedMotion:options.reducedMotion??false};
}

function project(primitives,options) {
  if(!Array.isArray(primitives)||primitives.length>MAX_PRIMITIVES) throw new RangeError('Primitive budget exceeded');
  const {width,height,rtl}=options,unit=Math.min(width,height);
  const x=value=>(rtl?1-value:value)*width,y=value=>value*height;
  const scale=value=>value*unit;
  return primitives.map(original=>{
    const p={...original};
    if(p.type==='line') {p.x1=x(original.x1);p.x2=x(original.x2);p.y1=y(original.y1);p.y2=y(original.y2);}
    else if(p.type==='polyline') {
      if(!Array.isArray(original.points)||original.points.length>MAX_POINTS) throw new RangeError('Point budget exceeded');
      p.points=original.points.map(v=>point(x(v.x),y(v.y)));
    } else {
      p.x=p.type==='rect'&&rtl?(1-original.x-original.width)*width:x(original.x);
      p.y=y(original.y);
    }
    for(const key of ['r','radius','size','lineWidth']) if(own(original,key)) p[key]=scale(original[key]);
    if(own(original,'width')) p.width=original.width*width;
    if(own(original,'height')) p.height=original.height*height;
    if(p.type==='rect'&&rtl&&own(original,'rotation')) p.rotation=-original.rotation;
    if(p.type==='text'&&rtl) p.align=original.align==='left'?'right':original.align==='right'?'left':original.align??'center';
    return p;
  });
}

export function sampleMotion(idOrDefinition,progress,options={}) {
  const supplied=typeof idOrDefinition==='string'?getDefinition(idOrDefinition):idOrDefinition;
  if(!supplied || typeof supplied!=='object') throw new TypeError('A registered motion is required');
  const definition=getDefinition(supplied.id);
  // Resolve by canonical ID: callers cannot inject their own source or mechanism.
  if(!finite(progress)) throw new RangeError('Progress must be finite');
  const o=optionsFor(options),t=o.reducedMotion?.65:clamp(progress);
  const family=familyById.get(definition.category_id),index=Number(definition.id.slice(-2))-1;
  const source=family.recipes[index];
  const buildOptions={...o,detail:definition.tier==='advanced'||o.width<=480?Math.min(o.detail,18):o.detail};
  let primitives=source.build(t,buildOptions);
  if(definition.tier==='advanced') {
    const comp=definition.composition,secondary=familyById.get(comp.secondary_family).recipes[comp.secondary_index];
    const secondaryScene=secondary.build(ease(.15+.7*t),buildOptions);
    primitives=couplers[index].apply(primitives,secondaryScene,t);
  }
  if(o.intensity!==1) primitives=transform(primitives,{scale:.7+.3*o.intensity});
  if(o.seed!==1) primitives=transform(primitives,{dx:(noise(0,o.seed)-.5)*.015,dy:(noise(1,o.seed)-.5)*.015});
  return {width:o.width,height:o.height,background:'#08111f',primitives:project(primitives,o),
          meta:{id:definition.id,progress:t,reducedMotion:o.reducedMotion,rtl:o.rtl,engine:'canvas2d',
                tier:definition.tier,category:definition.category_id,source_version:VERSION,
                implementation_status:'sampled-reference-scene',gpu_required:false}};
}
export const sampleScene=sampleMotion;

export function getCapabilities() {
  return {version:VERSION,components:definitions.length,basic:definitions.filter(x=>x.tier==='basic').length,
          advanced:definitions.filter(x=>x.tier==='advanced').length,categories:allFamilies.length,
          engine:'canvas2d',source_modules:['geometry.mjs','families.mjs','systems.mjs','catalog.mjs'],
          deterministic:true,rtl:true,reduced_motion:'stable-poster',gpu_required:false,
          optional_engines:{webgpu:'not-implemented',webgl:'not-used',three:'not-used',remotion:'not-used'},
          runtime_verification:'Read current browser receipts; source presence is not browser evidence.'};
}

// Semantic review signatures derive from executable source selections and
// coupling operators. Timing/color options cannot affect component identity.
export function structuralSignature(id) {
  const d=getDefinition(id);
  return JSON.stringify({source:[d.source.family,d.source.recipe],
    composition:d.composition?{source:[d.composition.secondary_family,d.composition.secondary_recipe],coupling:d.composition.coupling}:null});
}
