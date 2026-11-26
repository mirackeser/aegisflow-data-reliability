// SPDX-License-Identifier: Apache-2.0
// The Command Center's pure core: chart geometry, axis domains, KPI tiles, the next-step guide, agent bars, findings.
const assert=require('node:assert/strict');
const fs=require('node:fs');
global.language='en';
const {STRINGS}=require('./strings.js');
const C=require('./command.js');

const band={mean:100,sd:1,low:97,high:103};
function state(extra={}){
 const t=Array.from({length:300},(_,i)=>1000+i);
 return {settings:{chart_readings:300,check_every:15,window_seconds:200,close_after:2},live_start_t:600,elapsed_s:700,now_t:1300,
  series:{t,temp_c:t.map(()=>20),pressure_kpa:t.map((x,i)=>i<200?100:1000),flow_lpm:t.map(()=>5)},
  baseline:{bands:{temp_c:{mean:20,sd:2,low:14,high:26},pressure_kpa:band,flow_lpm:{mean:5,sd:1,low:2,high:8}}},
  detections:[{t:1210,check:'level_shift',column:'pressure_kpa',severity:'high',incident:'INC-0001'},
   {t:1210,check:'flatline',column:'pressure_kpa',severity:'low',incident:'INC-0001'},
   {t:1240,check:'freshness',column:'ts',severity:'medium',incident:'INC-0002'},
   {t:1250,check:'flatline',column:'temp_c',severity:'low',incident:'INC-0003'},
   {t:500,check:'volume_change',column:null,severity:'medium',incident:'INC-0000'}],
  faults:[{id:'F1',fault:'unit_change',sensor:'pressure_kpa',started_t:1200,ended_t:null,one_shot:false},
   {id:'F2',fault:'duplicate_burst',sensor:null,started_t:1100,ended_t:1100,one_shot:true},
   {id:'F3',fault:'stuck_sensor',sensor:'temp_c',started_t:1150,ended_t:1180,one_shot:false},
   {id:'F4',fault:'ingestion_pause',sensor:null,started_t:100,ended_t:200,one_shot:false}],
  incidents:[],status:{running:true,speed:5},
  kpis:{active_incidents:0,incidents:0,detections:0,checks:46,investigations:0,investigations_from_plant:0,judge_acceptance:null,judge_accepted:0,judge_verdicts:0,median_investigation_ms:null,data_points:3900,readings:1300},
  ...extra};
}

// Nice steps and domains.
assert.equal(C.ccNiceStep(10,4),2.5);assert.equal(C.ccNiceStep(900,4),250);assert.equal(C.ccNiceStep(0.4,4),0.1);assert.equal(C.ccNiceStep(7,4),2);
let d=C.ccDomain([98,101.5],band);
assert.ok(d.min<=97&&d.max>=103&&d.ticks[0]===d.min&&d.ticks[d.ticks.length-1]===d.max,'domain covers the band and the data');
d=C.ccDomain([],null);assert.deepEqual([d.min,d.max],[0,1]);
d=C.ccDomain([5,5],null);assert.ok(d.min<5&&d.max>5,'a flat series still gets a span');
d=C.ccDomain([100,1004],band);assert.ok(d.max>=1004&&d.min<=97);

// Clock and relative times.
assert.equal(C.ccClock(0),'00:00');assert.equal(C.ccClock(75),'01:15');assert.equal(C.ccClock(3725),'1:02:05');assert.equal(C.ccClock(-30),'−00:30');
assert.equal(C.ccRel(612,600),'T+00:12');assert.equal(C.ccRel(590,600),'T−00:10');
assert.equal(C.ccSeverityMax(['low','high','medium']),'high');assert.equal(C.ccSeverityMax([]),'low');

// Chart model: line breaks at gaps, band, markers per sensor (stream markers on every chart), fault spans.
const s=state();
let m=C.ccChartModel(s,'pressure_kpa');
assert.equal(m.count,300);assert.equal(m.t1,1299);assert.equal(m.t0,1000);
assert.equal((m.path.match(/M/g)||[]).length,1,'a continuous series is one path');
assert.equal(m.plot.l,C.CC_CHART.l);assert.equal(m.width,C.CC_CHART.w);
assert.ok(m.band.top<m.band.bottom&&m.band.mean>m.band.top&&m.band.mean<m.band.bottom,'band geometry is ordered');
assert.equal(m.outside,true,'the latest reading (x10) is outside the band');
assert.deepEqual(m.markers.map(k=>[k.t,k.checks.join('+'),k.severity,k.stream]),[[1210,'level_shift+flatline','high',false],[1240,'freshness','medium',true]]);
assert.deepEqual(m.faults.map(f=>[f.id,f.active,f.oneShot]),[['F1',true,false],['F2',false,true]]);
assert.ok(m.faults[1].w>=2,'a one-shot fault is still visible');
assert.ok(Math.abs(m.faults[0].x+m.faults[0].w-m.plot.r)<1e-6,'an active fault extends to now');
assert.deepEqual(m.xTicks.map(x=>x.ago),[0,100,200,299]);
assert.ok(m.dot&&Math.abs(m.dot.x-m.plot.r)<1e-6);
m=C.ccChartModel(s,'temp_c');
assert.deepEqual(m.markers.map(k=>k.t),[1240,1250]);assert.deepEqual(m.faults.map(f=>f.id),['F2','F3']);assert.equal(m.outside,false);
const gappy=state();gappy.series.t=gappy.series.t.map((t,i)=>i<150?t:t+40);
m=C.ccChartModel(gappy,'flow_lpm');
assert.equal((m.path.match(/M/g)||[]).length,2,'a pause breaks the line');
assert.equal(m.t1,1339);assert.equal(m.count,260,'only the last 300 s are drawn');
const dup=state();dup.series.t=[...dup.series.t,1290];dup.series.flow_lpm=[...dup.series.flow_lpm,5];
assert.equal(C.ccChartModel(dup,'flow_lpm').t1,1299,'replayed rows are drawn at their own time');
const none=state({series:{t:[],temp_c:[],pressure_kpa:[],flow_lpm:[]},detections:[],faults:[]});
m=C.ccChartModel(none,'temp_c');
assert.equal(m.path,'');assert.equal(m.latest,null);assert.equal(m.dot,null);assert.equal(m.min,null);assert.equal(m.outside,false);
m=C.ccChartModel(s,'flow_lpm',C.CC_CHART_NARROW);assert.equal(m.width,C.CC_CHART_NARROW.w);

// KPI tiles: values, n/a and tones come from the state.
let k=C.ccKpis(s);
assert.deepEqual(k.map(x=>x.key),['active','detections','investigations','judge','median','points']);
assert.equal(k[0].tone,'ok');assert.equal(k[1].tone,'');assert.equal(k[3].na,true);assert.equal(k[4].na,true);assert.equal(k[5].value,3900);
const busy=state({incidents:[{id:'INC-0001',status:'open',severity:'medium'},{id:'INC-0002',status:'closed',severity:'high'}],
 kpis:{...s.kpis,active_incidents:1,incidents:2,detections:3,judge_acceptance:0.75,judge_accepted:3,judge_verdicts:4,median_investigation_ms:1234}});
k=C.ccKpis(busy);
assert.equal(k[0].tone,'warn','an open medium incident warns');assert.equal(k[1].tone,'warn');assert.equal(k[3].na,false);assert.equal(k[3].tone,'ok');assert.equal(k[4].value,1234);
busy.incidents[0].severity='high';assert.equal(C.ccKpis(busy)[0].tone,'bad');

// The guide: start -> inject -> wait -> investigate -> review, and resume after a pause.
const g=x=>C.ccGuide(x).step;
assert.equal(C.ccGuide(null).step,'connect');assert.equal(C.ccGuide(s,false).step,'connect');
assert.equal(g(state({status:{running:false,speed:5},elapsed_s:0,faults:[]})),'start');
assert.equal(g(state({status:{running:false,speed:5},elapsed_s:30,faults:[]})),'resume');
assert.equal(g(state({faults:[]})),'inject');
assert.equal(g(state()),'wait');
assert.equal(g(state({faults:[{id:'F1',ended_t:5}]})),'wait','a cleared fault before any incident still waits for the checks');
assert.equal(g(state({faults:[{id:'F1',ended_t:5}],incidents:[{id:'INC-0001',status:'closed',run_id:null}]})),'inject');
const open={id:'INC-0001',status:'open',run_id:null};
let guide=C.ccGuide(state({incidents:[open]}));
assert.deepEqual([guide.step,guide.incident.id,guide.done.start,guide.done.inject,guide.done.investigate],['investigate','INC-0001',true,true,false]);
guide=C.ccGuide(state({incidents:[{...open,run_id:'run-x'}]}));
assert.deepEqual([guide.step,guide.done.investigate],['review',true]);
assert.equal(g(state({incidents:[{...open,run_id:'run-x'}],status:{running:false,speed:5}})),'resume');
assert.equal(g(state({incidents:[open],status:{running:false,speed:5}})),'investigate','an open incident can be investigated while paused');
guide=C.ccGuide(state({incidents:[{id:'INC-0003',status:'open',severity:'low',opened_t:9,run_id:null},{id:'INC-0002',status:'open',severity:'high',opened_t:5,run_id:null},{id:'INC-0001',status:'open',severity:'high',opened_t:2,run_id:null}]}));
assert.equal(guide.incident.id,'INC-0002','the guide points at the most severe, newest open incident');

// Agent outcome bars per layer.
const bars=C.ccLayerBars({specialists:{COMPLETED:3,NEEDS_EVIDENCE:1,POLICY_DENIED:0,SKIPPED:4,FAILED:0}});
assert.deepEqual(bars.map(b=>b.layer),['orchestration','specialists','reasoning','remediation','governance']);
assert.equal(bars[0].total,0);assert.deepEqual(bars[0].segments,[]);
assert.equal(bars[1].total,8);assert.deepEqual(bars[1].segments.map(x=>[x.status,x.share]),[['COMPLETED',0.375],['NEEDS_EVIDENCE',0.125],['SKIPPED',0.5]]);
assert.equal(C.ccLayerBars(undefined).every(b=>b.total===0),true);

// Finding sentences: every check the monitor can report has a sentence whose parameters are supplied.
const findings=[
 {check:'distribution_shift',detail:{psi:1.2,threshold:0.25,baseline_mean:100,current_mean:550}},
 {check:'level_shift',detail:{count:1,records:[12]}},{check:'flatline',detail:{count:9,records:[3,4]}},
 {check:'duplicate_rows',detail:{count:30,records:[171]}},{check:'timestamp_duplicate',detail:{count:30,records:[]}},
 {check:'constant_column',detail:{count:0,records:[]}},
 {check:'sampling_interval_change',detail:{current_seconds:2,baseline_seconds:1}},
 {check:'volume_change',detail:{current:120,baseline_min:200,baseline_max:200}},{check:'volume_change',detail:{current:0,direction:'drop'}},
 {check:'freshness',detail:{lag_seconds:12,sla_seconds:3}},{check:'freshness',detail:{latest:null,sla_seconds:3}},
 {check:'role_change',detail:{}}];
const placeholders=text=>[...text.matchAll(/\{(\w+)\}/g)].map(x=>x[1]);
for(const f of findings){
 const x=C.ccFindingText(f);
 assert.ok(STRINGS[x.key],`${x.key} is defined`);
 for(const name of placeholders(STRINGS[x.key][0]))assert.ok(name in x.params&&x.params[name]!==undefined,`${x.key}: {${name}} supplied`);
}
assert.equal(C.ccFindingText(findings[4]).params.record,'—');
assert.equal(C.ccFindingText(findings[8]).params.min,'—');
assert.equal(C.ccFindingText(findings[10]).key,'cc.fd.freshness.empty');
assert.equal(C.ccFindingText({check:'role_change'}).key,'cc.fd.other');

// Scale change and focus on the baseline range: a x10 reading stretches the axis; focus clamps it to the band +- 50%
// of its width, drops the off-axis readings from the line and marks them with thinned arrow glyphs.
{
 const r=C.ccFocusRange(band);assert.deepEqual(r,{low:94,high:106});
 assert.deepEqual(C.ccFocusRange({mean:50,low:50,high:50}),{low:49.5,high:50.5},'a zero-width band still gets a range');
 let m=C.ccChartModel(s,'pressure_kpa');
 assert.equal(m.focus,false);assert.equal(m.scale.changed,true,'the x10 readings blow the axis up');assert.equal(m.scale.available,true);
 assert.ok(m.domain.max>=1000);assert.deepEqual(m.clipped,[]);assert.equal(m.clippedCount,0);
 const f=C.ccChartModel(s,'pressure_kpa',{},{focus:true});
 assert.equal(f.focus,true);assert.equal(f.scale.changed,false);assert.equal(f.scale.available,true);
 assert.ok(f.domain.min<=94&&f.domain.max>=106&&f.domain.max<120,'the focused axis hugs the band');
 assert.equal(f.clippedCount,100,'every x10 reading is outside the focused axis');
 assert.ok(f.clipped.length>0&&f.clipped.length<100&&f.clipped.every(c=>c.dir==='up'),'glyphs are thinned and point up');
 for(let i=1;i<f.clipped.length;i++)assert.ok(f.clipped[i].x-f.clipped[i-1].x>=9);
 assert.equal((f.path.match(/M/g)||[]).length,1,'the line stops where readings leave the axis');
 assert.ok(f.band.bottom-f.band.top>(f.plot.b-f.plot.t)/4,'the band is readable again');
 assert.equal(f.dot.clipped,true);assert.ok(f.dot.y>=f.plot.t&&f.dot.y<=f.plot.b,'the latest dot stays on the plot');
 const low=state();low.series.pressure_kpa=low.series.pressure_kpa.map((v,i)=>i<200?100:10);
 assert.ok(C.ccChartModel(low,'pressure_kpa',{},{focus:true}).clipped.every(c=>c.dir==='down'));
 m=C.ccChartModel(s,'temp_c');assert.equal(m.scale.changed,false);assert.equal(m.scale.available,false,'no toggle when everything fits the band');
 const near=state();near.series.pressure_kpa=near.series.pressure_kpa.map((v,i)=>i<200?100:108);
 m=C.ccChartModel(near,'pressure_kpa');assert.equal(m.scale.available,true);assert.equal(m.scale.changed,false,'a modest excursion is not flagged as a scale change');
}

// Page brief: computed from the current state on every paint (never "open the session" once connected and running).
{
 const keys=b=>[b.happened.map(x=>x.key),b.next.key];
 assert.deepEqual(keys(C.ccBrief(s,false)),[['cc.brief.connect'],'cc.hint.connect']);
 assert.deepEqual(keys(C.ccBrief(null,true)),[['cc.brief.loading'],'cc.hint.loading']);
 const err=C.ccBrief(null,true,'offline');assert.deepEqual(keys(err),[['cc.brief.error'],'cc.hint.loading']);assert.equal(err.happened[0].params.reason,'offline');
 const ready=state({status:{running:false,speed:5},elapsed_s:0,faults:[]});
 assert.deepEqual(keys(C.ccBrief(ready)),[['cc.brief.ready'],'cc.hint.start']);
 const clean=C.ccBrief(state({faults:[],agents:{active:null}}));
 assert.deepEqual(keys(clean),[['cc.brief.clean'],'cc.hint.inject']);assert.equal(clean.happened[0].params.state,'running');
 const paused=C.ccBrief(state({status:{running:false,speed:1},faults:[],kpis:{...s.kpis,incidents:2,investigations:3},agents:{active:null}}));
 assert.deepEqual(keys(paused),[['cc.brief.closed','cc.brief.agents.runs'],'cc.hint.resume']);assert.equal(paused.happened[0].params.state,'paused');
 const inc={id:'INC-0007',status:'open',severity:'high',opened_t:5,run_id:null};
 const open=C.ccBrief(state({incidents:[inc],kpis:{...s.kpis,active_incidents:1,incidents:1},agents:{active:null}}));
 assert.deepEqual(keys(open),[['cc.brief.open'],'cc.hint.investigate']);assert.equal(open.happened[0].params.id,'INC-0007');assert.equal(open.next.params.id,'INC-0007');
 const busy=C.ccBrief(state({incidents:[{...inc,run_id:'run-1'}],agents:{active:'run-1'}}));
 assert.deepEqual(keys(busy),[['cc.brief.open','cc.brief.agents.active'],'cc.hint.review']);
 for(const b of [C.ccBrief(s,false),C.ccBrief(null),err,C.ccBrief(ready),clean,paused,open,busy])
  for(const part of [...b.happened,b.next]){assert.ok(STRINGS[part.key],part.key);for(const text of STRINGS[part.key])for(const name of placeholders(text))assert.ok(part.params[name]!==undefined,`${part.key}: {${name}}`);}
 for(const x of ['running','paused','ready'])assert.ok(STRINGS['cc.state.'+x]);
 for(const k of ['cc.scale.note','cc.focus.note','cc.focus','cc.scale.flag','cc.focus.flag','cc.legend.clip','cc.focus.clipped','cc.scale.changed.label'])assert.ok(STRINGS[k],k);
}
// Every dynamic key the page builds exists in both languages.
const sim=fs.readFileSync(__dirname+'/../../src/aegisflow_dr/simulation.py','utf8');
const tuple=name=>[...sim.match(new RegExp('^'+name+' = \\(([^)]*)\\)','m'))[1].matchAll(/"(\w+)"/g)].map(x=>x[1]);
const faults=[...tuple('SENSOR_FAULTS'),...tuple('STREAM_FAULTS')],sensors=tuple('SENSORS');
assert.equal(faults.length,7,'fault catalog found');assert.deepEqual(sensors,C.CC_SENSORS);
for(const f of faults)assert.ok(STRINGS['cc.fault.'+f]&&STRINGS['cc.fault.'+f+'.x'],`fault ${f} has a name and a one-line explanation`);
for(const x of [...sensors,'stream'])assert.ok(STRINGS['cc.sensor.'+x],`sensor ${x} has a name`);
for(const c of [...tuple('PROFILE_CHECKS'),...tuple('MEDIUM'),'distribution_shift'])assert.ok(STRINGS['cc.check.'+c],`check ${c} has a label`);
for(const x of ['high','medium','low'])assert.ok(STRINGS['cc.sev.'+x]);
for(const x of ['connect','start','resume','inject','wait','investigate','review'])assert.ok(STRINGS['cc.hint.'+x],`hint ${x}`);
for(const x of ['start','inject','investigate'])assert.ok(STRINGS['cc.guide.'+x]);
for(const x of ['done','current','todo'])assert.ok(STRINGS['cc.step.'+x]);
for(const x of ['active','detections','investigations','judge','median','points'])assert.ok(STRINGS['cc.k.'+x]&&STRINGS['cc.k.'+x+'.x']);
for(const x of ['judge','median'])assert.ok(STRINGS['cc.k.'+x+'.na']);
for(const x of ['COMPLETED','NEEDS_EVIDENCE','POLICY_DENIED','SKIPPED','FAILED'])assert.ok(STRINGS['cc.outcome.'+x]);
for(const x of ['active','ended','once'])assert.ok(STRINGS['cc.fault.state.'+x]);
for(const x of ['baseline','profile'])assert.ok(STRINGS['cc.ev.source.'+x]);
// Honesty: the plant is always called a simulation, and the console says the fault is simulated.
assert.ok(/simulat/i.test(STRINGS['cc.badge'][0])&&/simüle/i.test(STRINGS['cc.badge'][1]));
assert.ok(STRINGS['cc.console.x'][0].includes('simulated fault')&&STRINGS['cc.console.x'][1].includes('simüle bir hata'));
assert.ok(/not a real plant/.test(STRINGS['cc.badge.x'][0]));
assert.deepEqual(STRINGS['nav.overview'],['Command Center','Komuta Merkezi']);
console.log('Command Center helpers verified: chart geometry, domains, KPIs, guide, agent bars and finding sentences.');
