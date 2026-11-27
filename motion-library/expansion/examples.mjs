import {definitions,getDefinition,sampleMotion} from './catalog.mjs';

/** Every example is executable. Pass the shared SDK or render the sampled scene. */
export const examples=Object.freeze(Object.fromEntries(definitions.map(definition=>[definition.id,
  Object.freeze({id:definition.id,
    sample:(progress=.5,options={})=>sampleMotion(getDefinition(definition.id),progress,options),
    create:(motionSDK,options={})=>motionSDK.create(definition.id,options),
    usage:`import * as catalog from './motion-library/expansion/catalog.mjs';\nimport {motion} from './packages/motion-sdk/index.mjs';\nmotion.registerCatalog(catalog);\nconst player = motion.create('${definition.id}', {container: document.querySelector('#preview')});\nplayer.play();\n// player.destroy() when unmounting.`})
])));

export function exampleFor(id) {
  if(!Object.prototype.hasOwnProperty.call(examples,id)) throw new RangeError('Unknown motion example');
  return examples[id];
}
