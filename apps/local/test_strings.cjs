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
const source=['app.js','workspace.js','knowledgebase.js','schemaregistry.js','profile.js','baseline.js','flow.js','command.js','incident.js'].map(f=>fs.readFileSync(__dirname+'/'+f,'utf8')).join('\n');
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
// Every baseline check, reason, state and volume direction the panel can show is translated.
for(const check of ['column_missing','column_added','role_change','sampling_interval_change','volume_change','freshness','empty_rate_change','distribution_shift'])
 assert.ok(STRINGS['bl.check.'+check],`baseline check ${check} has no label`);
for(const reason of ['no_baseline_interval','too_few_intervals','no_as_of','no_time_column','no_sla','timezone_mismatch','as_of_before_latest_record','too_few_values','too_few_values_in_baseline','constant_in_baseline','role_changed'])
 assert.ok(STRINGS['bl.reason.'+reason],`baseline reason ${reason} is not explained`);
for(const key of ['bl.asof.x.aware','bl.asof.x.local','bl.asof.x.utc','bl.asof.x.none','bl.clock.local','bl.clock.utc','bl.state.ok','bl.state.changed','bl.state.skipped','bl.d.volume.drop','bl.d.volume.increase','bl.explain.column_missing','bl.explain.column_added','bl.status.DRIFT','bl.status.NO_DRIFT','bl.tile.sampling','bl.tile.volume','bl.tile.freshness','bl.tile.distribution'])
 assert.ok(STRINGS[key],`${key} is missing`);
// The privacy note must not overclaim: medians and decile edges are values from the data.
assert.ok(STRINGS['bl.note'][0].includes('medians and decile edges are values from the data and reveal approximate ranges'),'bl.note must say decile edges reveal approximate ranges');
assert.ok(STRINGS['bl.note'][1].includes('yaklaşık aralıkları'),'bl.note (TR) must say decile edges reveal approximate ranges');
assert.ok(!/never record values|hiçbir kayıt değerini/.test(STRINGS['bl.note'].join(' ')),'bl.note must not claim that no record value is kept');
// Candidate explanations: every mechanism, probe, status, outcome, verdict and stop reason of the engine is translated,
// the fixed statement is the engine's text verbatim, and no candidate-explanation string claims a cause or a confirmation.
const engine=fs.readFileSync(__dirname+'/../../src/aegisflow_dr/hypotheses.py','utf8');
const tuple=name=>[...engine.match(new RegExp('^'+name+' = \\(([^)]*)\\)','m'))[1].matchAll(/"(\w+)"/g)].map(m=>m[1]);
const mechanisms=tuple('MECHANISMS'),probes=tuple('PROBES');
assert.equal(mechanisms.length,12,'mechanism catalog not found');assert.equal(probes.length,8,'probe list not found');
for(const m of mechanisms)assert.ok(STRINGS['hy.mech.'+m]&&STRINGS['hy.mech.'+m+'.x'],`mechanism ${m} has no name or explanation`);
for(const p of probes)assert.ok(STRINGS['hy.probe.'+p],`probe ${p} has no name`);
for(const m of ['r','sd_ratio','mean_shift_sd','share','ratio','cv','lag_ratio','longest_run_share'])assert.ok(STRINGS['hy.m.'+m],`measured value ${m} has no label`);
for(const key of ['status.supported','status.open','status.refuted','outcome.supports','outcome.refutes','outcome.neutral','ev.supports','ev.refutes','ev.neutral',
 'verdict.no_observations','verdict.none_supported','verdict.single_supported','verdict.multiple_supported',
 'stop.no_observations','stop.no_informative_probe','stop.probe_budget_exhausted','stop.resolved',
 'check.flatline','check.duplicate_rows','check.timestamp_duplicate','dir.drop','dir.increase','source.baseline','source.profile'])
 assert.ok(STRINGS['hy.'+key],`hy.${key} is missing`);
assert.equal(STRINGS['hy.statement'][0],engine.match(/^STATEMENT = "([^"]+)"/m)[1],'hy.statement must be the engine statement verbatim');
for(const [key,[en,tr]] of Object.entries(STRINGS)){
 if(!key.startsWith('hy.')||key==='hy.statement')continue;
 assert.ok(!/\bcauses?\b|\bcaused\b|root.cause|confirm/i.test(en),`${key}: candidate explanations must not claim a cause or a confirmation`);
 assert.ok(!/\bneden|doğrulan|kesinleş|teyit/i.test(tr),`${key} (TR): candidate explanations must not claim a cause or a confirmation`);
}
// The single-mechanism assumption behind "Refuted" is disclosed in the note and in the legend (final review I3).
assert.ok(STRINGS['hy.note'][0].includes('Probes assume one mechanism acts on a column at a time')&&STRINGS['hy.note'][0].includes('every candidate can be refuted, the true ones included'),'hy.note must disclose the one-mechanism assumption');
assert.ok(STRINGS['hy.note'][1].includes('aynı anda tek bir mekanizmanın etkili olduğunu varsayar'),'hy.note (TR) must disclose the one-mechanism assumption');
assert.ok(/Refuted: .*assuming one mechanism acts on the column at a time/.test(STRINGS['hy.hyp.legend'][0]),'hy.hyp.legend must qualify Refuted');
assert.ok(/Çürütüldü: .*tek bir mekanizmanın etkili olduğu varsayımıyla/.test(STRINGS['hy.hyp.legend'][1]),'hy.hyp.legend (TR) must qualify Refuted');
// Mechanism descriptions are hypothetical: they say what the mechanism would look like, never that it happened (final
// review I2). Turkish must not use the reported-fact -mış/-miş/-muş/-müş forms the first draft used.
const reportedFact=['ölçeklenmiş','kaymış','büyümüş','bırakmış','değişmiş','yüklenmiş','teslim edilmiş','geç gelmiş','dağılmış'];
for(const m of mechanisms){
 const [en,tr]=STRINGS['hy.mech.'+m+'.x'];
 assert.ok(en.startsWith('If this were the change: '),`hy.mech.${m}.x must start with the conditional prefix`);
 assert.ok(tr.startsWith('Bu değişiklik olsaydı: '),`hy.mech.${m}.x (TR) must start with the conditional prefix`);
 assert.ok(!/\p{L}(mış|miş|muş|müş)(?!\p{L})/u.test(tr),`hy.mech.${m}.x (TR) must not state the mechanism as a reported fact`);
}
for(const [key,[,tr]] of Object.entries(STRINGS))
 if(key.startsWith('hy.'))for(const word of reportedFact)assert.ok(!tr.toLocaleLowerCase('tr').includes(word),`${key} (TR): "${word}" states a mechanism as a reported fact`);
assert.ok(!('hy.explain' in STRINGS)&&!('hy.explain.x' in STRINGS),'the button no longer says "Explain"');
assert.deepEqual(STRINGS['hy.list'],['List candidate explanations','Aday açıklamaları listele']);
// Turkish wording of the budget and evidence lines (final review triage).
assert.equal(STRINGS['hy.budget'][1],'Kullanılan sınama: {used} / {max}');
assert.equal(STRINGS['hy.ev.supports'][1],'{probe}: destekliyor ({values})');
assert.equal(STRINGS['hy.ev.refutes'][1],'{probe}: çürütüyor ({values})');
assert.equal(STRINGS['hy.ev.neutral'][1],'{probe}: karar yok ({values})');
// Probe budget numbers in the UI follow the engine's constants.
const [maxDefault,maxLimit]=engine.match(/^MAX_PROBES_DEFAULT, MAX_PROBES_LIMIT = (\d+), (\d+)$/m).slice(1);
for(const text of STRINGS['hy.list.x'])assert.deepEqual(text.match(/\d+/g),[maxDefault],`hy.list.x must name the default budget ${maxDefault}: ${text}`);
for(const text of STRINGS['role.A25.limit'])assert.deepEqual(text.match(/\d+/g),[maxLimit,maxDefault],`role.A25.limit must name the budget limit and default: ${text}`);
for(const role of ['A24','A25','A28'])assert.ok(/simulated mechanisms, deterministic probes with fixed thresholds, no model/.test(STRINGS['role.'+role+'.limit'][0]),`role.${role}.limit must state its limits`);
assert.ok(/fixed catalog of candidate mechanisms exists \(F04\), but naming a root cause needs a model and real labelled data/.test(STRINGS['role.A23.limit'][0]),'role.A23.limit must keep root cause out of reach');
console.log(`${checked} UI strings verified: both languages present, placeholders consistent, no missing keys.`);
