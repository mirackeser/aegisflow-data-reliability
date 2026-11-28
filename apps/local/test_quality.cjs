// SPDX-License-Identifier: Apache-2.0
// The quality page's pure core: every value is the API's (counts, interval, n/a), nothing is rounded into a better
// number, the model weakness is computed from the API's own rows, and every key the page can ask for is translated.
const assert=require('node:assert/strict');
global.language='en';
const {STRINGS}=require('./strings.js');
const Q=require('./quality.js');

const rate=(n,d)=>({numerator:n,denominator:d,value:d?n/d:null,low:d?Math.max(0,n/d-0.1):null,high:d?Math.min(1,n/d+0.1):null});
const per=(h,v,d,x)=>({development:d,validation:v,heldout:h,...x});
const metric=(key,better,splits,kind='rate')=>({key,kind,better,splits});
const summary={version:'1',splits:Q.QUA_SPLITS,evaluations:[
 {id:'plant',available:true,report:'docs/evaluation/plant.md',units:per({seeds:20},{seeds:20},{seeds:20}),
  metrics:[metric('detected','higher',per(rate(295,300),rate(300,300),rate(299,300))),metric('onset_within','higher',per(rate(267,295),rate(1,1),rate(1,1))),
   metric('sole_supported','higher',per(rate(258,295),rate(1,1),rate(1,1))),metric('wrong_supported','lower',per(rate(0,295),rate(0,1),rate(0,1))),
   metric('false_alarms','lower',per({count:1,hours:20},{count:0,hours:20},{count:2,hours:20}),'per_hours')],
  scenarios:{columns:['detected','onset_within','sole_supported','wrong_supported','step1_sole_supported'],
   rows:[{name:'unit_change/pressure_kpa',splits:per({detected:rate(20,20)},{},{})},{name:'duplicate_burst',splits:per({detected:rate(3,20)},{},{})}]}},
 {id:'agents',available:true,report:'docs/evaluation/agents.md',model:'qwen3:4b',prompt_version:'2',units:per({groups:10,cases:140},{groups:9,cases:126},{groups:21,cases:294}),
  metrics:[metric('selection_exact','higher',per(rate(140,140),rate(126,126),rate(294,294))),metric('model_json_valid','higher',per(rate(1,1),rate(1,1),rate(1,1))),
   metric('a23_any','higher',per(rate(90,110),rate(1,1),rate(1,1))),metric('a23_top1','higher',per(rate(40,110),rate(1,1),rate(1,1))),
   metric('a23_misattributed','lower',per(rate(20,20),rate(1,1),rate(1,1))),metric('loop_sole','higher',per(rate(100,110),rate(1,1),rate(1,1))),
   metric('replay_fidelity','higher',per(rate(140,140),rate(1,1),rate(1,1))),metric('run_p50_ms','lower',per(8152,null,8000),'ms')],
  scenarios:{columns:['a23_any','a23_top1','a23_echo','loop_sole','a23_misattributed','loop_misattributed'],
   rows:[{name:'unit_change',splits:per({a23_echo:rate(10,10),a23_misattributed:null},{},{})},{name:'clean',splits:per({a23_echo:rate(0,0)},{},{})},
    {name:'unmodelled_sign_flip',splits:per({a23_echo:rate(2,10)},{},{})}]}},
 {id:'hypotheses',available:true,report:'docs/evaluation/hypotheses.md',units:per({groups:12},{groups:18},{groups:30}),
  metrics:[metric('truth_sole_supported','higher',per(rate(124,132),rate(1,1),rate(1,1))),metric('misattributed','lower',per(rate(19,24),rate(1,1),rate(1,1)))]},
 {id:'baseline',available:false},
 {id:'profiling',available:true,report:'docs/evaluation/profiling.md',units:per({groups:17},{groups:12},{groups:31}),
  metrics:[metric('case_detection','higher',per(rate(149,170),rate(1,1),rate(1,1))),metric('clean_with_finding','lower',per(rate(1,17),rate(0,0),rate(0,1)))]},
 {id:'checks',available:true,report:'docs/evaluation/latest.md',units:per({groups:6},{groups:10},{groups:24}),
  metrics:[metric('diagnose_csv.precision','higher',per(rate(186,186),rate(1,1),rate(1,1)))]}]};

// Values pass through with their counts; an empty denominator and a missing split are n/a, never 100%.
const plant=Q.quaCard(summary,'plant');
assert.deepEqual(Q.quaValue(Q.quaMetric(plant,'detected'),'heldout'),{kind:'rate',...rate(295,300)});
assert.deepEqual(Q.quaValue(Q.quaMetric(Q.quaCard(summary,'profiling'),'clean_with_finding'),'validation'),{kind:'na',numerator:0,denominator:0});
assert.deepEqual(Q.quaValue(Q.quaMetric(plant,'false_alarms'),'heldout'),{kind:'per_hours',count:1,hours:20});
assert.deepEqual(Q.quaValue(Q.quaMetric(Q.quaCard(summary,'agents'),'run_p50_ms'),'heldout'),{kind:'ms',ms:8152});
assert.deepEqual(Q.quaValue(Q.quaMetric(Q.quaCard(summary,'agents'),'run_p50_ms'),'validation'),{kind:'na'});
assert.deepEqual(Q.quaValue(null,'heldout'),{kind:'na'});
assert.equal(Q.quaCard(summary,'baseline'),null,'an unavailable evaluation is not shown as measured');
assert.equal(Q.quaMetric(plant,'nope'),null);
console.log('values pass through with counts and n/a.');

// Headline tiles follow the fixed order and skip what is not available.
const tiles=Q.quaHeadline(summary,'heldout');
assert.deepEqual(tiles.map(t=>t.id+'.'+t.key),['plant.sole_supported','plant.wrong_supported','agents.selection_exact','agents.a23_any','agents.a23_top1',
 'hypotheses.truth_sole_supported','profiling.case_detection']);
assert.equal(tiles[1].better,'lower');assert.deepEqual(tiles[0].value,{kind:'rate',...rate(258,295)});
console.log('headline tiles verified.');

// The model weakness comes from the API's own numbers; the echo pools the scenario rows that apply.
const weak=Q.quaWeakness(summary,'heldout');
assert.equal(weak.top1.numerator,40);assert.equal(weak.any.numerator,90);
assert.deepEqual(Q.quaPoolColumn(Q.quaCard(summary,'agents'),'a23_echo','heldout'),{numerator:12,denominator:20,value:0.6});
assert.deepEqual(Q.quaPoolColumn(null,'a23_echo','heldout'),{numerator:0,denominator:0,value:null});
assert.equal(Q.quaWeakness(summary,'validation'),null,'no echo rows on this split: no claim');
assert.equal(Q.quaWeakness({evaluations:[]},'heldout'),null);
const noTop={evaluations:[{...Q.quaCard(summary,'agents'),metrics:[metric('a23_top1','higher',per(rate(0,0),null,null)),metric('a23_any','higher',per(rate(1,2),null,null))]}]};
assert.equal(Q.quaWeakness(noTop,'heldout'),null,'an n/a rate makes no claim');
console.log('model weakness verified.');

// Units, scenario labels and the brief.
assert.deepEqual(Q.quaUnits(plant,'heldout'),{key:'qua.units.seeds',n:20});
assert.deepEqual(Q.quaUnits(Q.quaCard(summary,'agents'),'heldout'),{key:'qua.units.cases',n:10,c:140});
assert.deepEqual(Q.quaUnits(Q.quaCard(summary,'hypotheses'),'heldout'),{key:'qua.units.groups',n:12});
assert.equal(Q.quaUnits({units:{}},'heldout'),null);
assert.deepEqual(Q.quaScenarioLabel(plant,'unit_change/pressure_kpa'),['cc.fault.unit_change','cc.sensor.pressure_kpa']);
assert.deepEqual(Q.quaScenarioLabel(plant,'duplicate_burst'),['cc.fault.duplicate_burst']);
assert.deepEqual(Q.quaScenarioLabel(Q.quaCard(summary,'agents'),'clean'),['qua.scn.clean']);
assert.deepEqual(Q.quaBrief(summary,'heldout'),{evaluations:5,missing:['baseline'],split:'heldout'});
console.log('units, labels and brief verified.');

// Every key the page can build at run time is translated in both languages.
const has=key=>assert.ok(STRINGS[key]&&STRINGS[key][0]&&STRINGS[key][1],`${key} is missing`);
for(const id of Q.QUA_ORDER)for(const k of ['qua.card.'+id,'qua.card.'+id+'.x','qua.card.'+id+'.limit'])has(k);
for(const k of Q.QUA_LIMITS)has('qua.lim.'+k);
for(const [id,key] of Q.QUA_HEADLINE)for(const k of ['qua.m.'+id+'.'+key,'qua.m.'+id+'.'+key+'.x'])has(k);
for(const s of Q.QUA_SPLITS)has('split.'+s);
for(const b of ['higher','lower'])has('qua.better.'+b);
for(const card of summary.evaluations.filter(c=>c.available)){
 for(const m of card.metrics)for(const k of ['qua.m.'+card.id+'.'+m.key,'qua.m.'+card.id+'.'+m.key+'.x'])has(k);
 for(const c of card.scenarios?.columns||[])has('qua.c.'+card.id+'.'+c);
 for(const r of card.scenarios?.rows||[])Q.quaScenarioLabel(card,r.name).forEach(has);
}
for(const k of ['unit_change','calibration_offset','noise_increase','stuck_sensor','sampling_config_change','partial_load','duplicate_delivery','delivery_delay',
 'source_outage','field_outage','intermittent_loss','clean','unmodelled_sign_flip','unmodelled_amplitude'])has('qua.scn.'+k);
for(const k of ['qua.weak.t','qua.weak.x','qua.of','qua.ci','qua.bar.aria','qua.perhours','qua.ms','page.quality.title','page.quality.eyebrow','brief.quality.purpose','brief.quality.can','next.quality','nav.quality'])has(k);
// The wording never claims accuracy on real data or a cause.
for(const [key,[en]] of Object.entries(STRINGS))if(key.startsWith('qua.'))
 assert.ok(!/\bcaused?\b|root.cause|accurate on real|proves?\b/i.test(en.replace('not a confirmed cause','').replace('not diagnostic accuracy','')),`${key}: overclaims`);
console.log('quality strings verified.');
