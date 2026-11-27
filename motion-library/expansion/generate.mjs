// Generate machine-readable metadata from authored executable source. No network.
import {writeFileSync,readFileSync} from 'node:fs';
import {definitions,VERSION,getCapabilities} from './catalog.mjs';

const path=new URL('./definitions.json',import.meta.url);
const text=JSON.stringify({schema_version:1,version:VERSION,
  notes:'Original additive source recipes. Browser/performance verification is recorded separately; this file does not assert current operational evidence.',
  capabilities:getCapabilities(),definitions},null,2)+'\n';
if(process.argv.includes('--check')) {
  if(readFileSync(path,'utf8')!==text) throw new Error('Generated definitions are stale');
}else writeFileSync(path,text);
