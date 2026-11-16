// SPDX-License-Identifier: Apache-2.0
// Guards the bilingual UI: every key has both languages, placeholders match, and no code path asks for a missing key.
const assert=require('node:assert/strict');
const fs=require('node:fs');
global.language='en';
const {STRINGS}=require('./strings.js');
const placeholders=text=>[...text.matchAll(/\{(\w+)\}/g)].map(m=>m[1]).sort().join(',');
let checked=0;
for(const [key,value] of Object.entries(STRINGS)){
 assert.ok(Array.isArray(value)&&value.length===2,`${key}: needs exactly [English, Turkish]`);
 assert.ok(value[0].trim()&&value[1].trim(),`${key}: empty translation`);
 assert.equal(placeholders(value[0]),placeholders(value[1]),`${key}: placeholder mismatch between languages`);
 assert.ok(!/[<>]/.test(value[0]+value[1]),`${key}: markup is not allowed in UI strings`);
 checked++;
}
const source=['app.js','workspace.js'].map(f=>fs.readFileSync(__dirname+'/'+f,'utf8')).join('\n');
const used=new Set([...source.matchAll(/\bt{1,2}\('([A-Za-z0-9_.\-]+)'/g)].map(m=>m[1]));
const missing=[...used].filter(key=>!(key in STRINGS)&&!key.endsWith('.'));
assert.deepEqual(missing,[],'keys used by the UI but not defined');
// Parameters passed at call sites must exist in the string.
for(const m of source.matchAll(/\bt\('([A-Za-z0-9_.\-]+)',\{([^}]*)\}/g)){
 const entry=STRINGS[m[1]];if(!entry)continue;
 const passed=[...m[2].matchAll(/(\w+)\s*[:,]/g)].map(x=>x[1]);
 for(const name of placeholders(entry[0]).split(',').filter(Boolean))assert.ok(passed.includes(name)||new RegExp('\\b'+name+'\\b').test(m[2]),`${m[1]}: call site does not supply {${name}}`);
}
// Every reason code the server can emit has a short and a long explanation.
for(const code of ['NOT_EXECUTED','NO_FILE_PROFILE_FOR_EXAMPLE','SOURCE_QUALITY_FAILURE','NO_RETAINED_RUN','VERIFICATION_REJECTED','NO_VERIFICATION','NO_ACTIONS_PROPOSED','NO_MODEL_CONFIGURED','READ_ONLY_POLICY'])
 assert.ok(STRINGS['reason.'+code]&&STRINGS['short.'+code],`reason ${code} is not explained`);
console.log(`${checked} UI strings verified: both languages present, placeholders consistent, no missing keys.`);
