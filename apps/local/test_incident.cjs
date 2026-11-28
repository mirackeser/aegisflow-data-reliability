// SPDX-License-Identifier: Apache-2.0
// The Incident page's pure core: lifecycle stepper, evidence state, chart geometry, candidate explanations from a run
// record, agent operations and the page brief.
const assert=require('node:assert/strict');
const fs=require('node:fs');
global.language='en';
const {STRINGS}=require('./strings.js');
const C=require('./command.js');
const I=require('./incident.js');

const ISO='2026-11-28T10:00:00Z';
function view(incident={},extra={}){
 const t=Array.from({length:263},(_,i)=>1000+i);
 const base={id:'INC-0001',sensor:'pressure_kpa',status:'open',severity:'high',opened_t:1215,opened_at:ISO,closed_t:null,closed_at:null,
  findings:[{check:'distribution_shift',column:'pressure_kpa',severity:'high',source:'baseline',detail:{psi:0.9,threshold:0.25,baseline_mean:100,current_mean:110},first_t:1215,first_at:ISO}],
  checks:['distribution_shift'],window:{records:200,first_t:1016,last_t:1215,as_of:ISO,sha256:'a'.repeat(64)},run_id:null,
  evidence:{state:'collecting',method:'change_point',onset_t:1200,onset_at:ISO,statistic:152.4,clear:true,first_t:1200,as_of_t:1399,as_of:ISO,
   needed_s:200,collected_s:63,records:null,sha256:null},
  truth:{fault_id:'F1',fault:'calibration_offset',started_t:1198,started_at:ISO,onset_error_s:2}};
 return {simulation:true,now_t:1263,live_start_t:600,units:{temp_c:'°C',pressure_kpa:'kPa',flow_lpm:'L/min'},
  bands:{temp_c:{mean:20,sd:2,low:14,high:26},pressure_kpa:{mean:100,sd:1,low:97,high:103},flow_lpm:{mean:5,sd:1,low:2,high:8}},
  baseline_digest:'b'.repeat(64),settings:{window_seconds:200,clear_statistic:30},
  series:{t,temp_c:t.map(()=>20),pressure_kpa:t.map(x=>x<1200?100:110),flow_lpm:t.map(()=>5)},
  incident:{...base,...incident,evidence:{...base.evidence,...(incident.evidence||{})}},run:null,...extra};
}
const ready={state:'ready',collected_s:200,records:200,sha256:'c'.repeat(64)};

// A hand-written record shaped like agent-run-v1 (runtime._Run.record; claims from executors/reasoning.py).
const claim=(text_key,params)=>({text_key,params,evidence_refs:[{id:'ev-1',sha256:'d'.repeat(64)}]});
const agent=(agent_id,selected,status,claims=[],extra={})=>({agent_id,name:agent_id,layer:'reasoning',kind:'deterministic',selected,wave:1,attempts:1,task:null,
 result:{agent_id,status,error_code:null,claims,evidence_refs:[],...extra}});
const record={run_id:'run-abc',status:'completed',finished_at:ISO,duration_ms:4321,
 agents:[
  agent('A01',true,'COMPLETED'),agent('A10',true,'COMPLETED'),agent('A11',true,'NEEDS_EVIDENCE'),agent('A30',false,'SKIPPED'),
  agent('A23',true,'COMPLETED',[claim('a23.suggested',{mechanisms:['calibration_offset','stuck_sensor'],explains:['obs-1']}),
   claim('a23.compared',{agreed:['calibration_offset'],model_only:['stuck_sensor'],rule_supported:['calibration_offset']})]),
  agent('A24',true,'COMPLETED',[claim('a24.summary',{hypotheses:4,with_competitors:4,verdict:'single_supported'}),
   claim('a24.hypothesis',{hypothesis:'hyp-1',mechanism:'unit_change',column:'pressure_kpa',status:'refuted',explains:['obs-1'],competitors:['hyp-2','hyp-3','hyp-4']}),
   claim('a24.hypothesis',{hypothesis:'hyp-2',mechanism:'calibration_offset',column:'pressure_kpa',status:'supported',explains:['obs-1'],competitors:['hyp-1','hyp-3','hyp-4']}),
   claim('a24.hypothesis',{hypothesis:'hyp-3',mechanism:'noise_increase',column:'pressure_kpa',status:'refuted',explains:['obs-1'],competitors:['hyp-1','hyp-2','hyp-4']}),
   claim('a24.hypothesis',{hypothesis:'hyp-4',mechanism:'genuine_change',column:'pressure_kpa',status:'open',explains:['obs-1'],competitors:['hyp-1','hyp-2','hyp-3']}),
   claim('a24.hypothesis',{hypothesis:'hyp-5',mechanism:'source_outage',column:null,status:'supported',explains:['obs-2'],competitors:['hyp-6']}),
   claim('a24.hypothesis',{hypothesis:'hyp-6',mechanism:'delivery_delay',column:null,status:'refuted',explains:['obs-2'],competitors:['hyp-5']})]),
  agent('A25',true,'COMPLETED',[claim('a25.stop',{stop_reason:'resolved',used:2,max_probes:6}),
   claim('a25.probe',{probe_id:'prb-1',probe:'spread_ratio',column:'pressure_kpa',round:1,supports:1,refutes:1,neutral:0}),
   claim('a25.probe',{probe_id:'prb-2',probe:'scale_ratio',column:'pressure_kpa',round:2,supports:0,refutes:1,neutral:0}),
   claim('a25.probe',{probe_id:'prb-3',probe:'span_ratio',column:null,round:3,supports:1,refutes:1,neutral:0}),
   claim('a25.probe',{probe_id:'prb-4',probe:'freshness_lag',column:null,round:4,supports:1,refutes:0,neutral:0})]),
  agent('A27',true,'COMPLETED'),
  agent('A28',true,'COMPLETED',[claim('a28.ranking',{ranking:['hyp-2','hyp-5','hyp-4','hyp-1','hyp-3','hyp-6'],verdict:'multiple_supported',supported:2,open:1,refuted:3})])],
 judge:{verdicts:[{agent:'A23',claim:0,verdict:'advisory',reason:'model_suggestion'},{agent:'A23',claim:1,verdict:'advisory',reason:'model_suggestion'},
  {agent:'A10',claim:0,verdict:'accepted',reason:'evidence_verified'}],accepted:5,advisory:2,rejected:1},
 usage:{totals:{tool_calls:9,llm_calls:1,tokens_in:300,tokens_out:120,latency_ms:4000}},events:[{seq:1},{seq:2},{seq:3}]};
const finishedRun={run_id:'run-abc',state:'finished',status:'completed',started_at:ISO,finished_at:ISO,events:3,input:{name:'plant INC-0001 pressure_kpa'}};

// Evidence state and the reason a start was refused.
assert.deepEqual(C.ccEvidence({state:'collecting',onset_t:1200,needed_s:200,collected_s:63}),{state:'collecting',collected:63,needed:200,ratio:0.315,ready:false});
assert.equal(C.ccEvidence({state:'collecting',onset_t:null,needed_s:200,collected_s:0}).state,'locating');
assert.equal(C.ccEvidence({state:'collecting',onset_t:5,needed_s:200,collected_s:250}).collected,200,'collected seconds never exceed the window');
assert.equal(C.ccEvidence({state:'ready',onset_t:5,needed_s:200,collected_s:200}).ready,true);
assert.equal(C.ccEvidence({state:'unavailable',onset_t:null,needed_s:200,collected_s:12}).state,'unavailable');
assert.equal(C.ccEvidence(undefined).state,'locating');
assert.deepEqual(C.ccStartError({status:409,body:{error:'EVIDENCE_NOT_READY',evidence:{state:'collecting',onset_t:1,needed_s:200,collected_s:63}}}),{key:'cc.err.notready',params:{n:63,needed:200}});
assert.equal(C.ccStartError({status:409,body:{error:'BUSY'}}).key,'cc.investigate.busy');
assert.equal(C.ccStartError({status:404,body:{error:'NOT_FOUND'}}).key,'cc.err.notfound');
assert.equal(C.ccStartError({status:500,body:null}).key,null);

// Clear versus uncertain onset estimates.

assert.equal(I.incClear({method:'change_point',statistic:30,clear:true}),true);
assert.equal(I.incClear({method:'change_point',statistic:29.9,clear:false}),false);
assert.equal(I.incClear({method:'data_stopped',statistic:null,clear:true}),null);
assert.equal(I.incClear({method:null,statistic:null}),null);
{const v={incident:{sensor:'temp_c'},bands:{temp_c:{}},seasonality:{temp_c:{period:100}}};
 assert.equal(I.incMethodKey(v,{method:'change_point'}),'inc.method.change_point.seasonal');
 assert.equal(I.incMethodKey({...v,seasonality:{temp_c:{period:null}}},{method:'change_point'}),'inc.method.change_point');
 assert.equal(I.incMethodKey({incident:{sensor:'stream'},bands:{}},{method:'change_point'}),'inc.method.change_point.gaps');
 assert.equal(I.incMethodKey(v,{method:'data_stopped'}),'inc.method.data_stopped');assert.equal(I.incMethodKey(v,{method:null}),'inc.method.none');}

// Polling only while something can still change.
assert.equal(I.incNeedsPoll(view()),true);
assert.equal(I.incNeedsPoll(view({status:'closed',evidence:ready})),false);
assert.equal(I.incNeedsPoll(view({status:'closed',evidence:ready},{run:{...finishedRun,state:'running'}})),true);
assert.equal(I.incNeedsPoll(view({status:'closed',evidence:{state:'unavailable'}})),false);
assert.equal(I.incNeedsPoll(null),true);

// Lifecycle stepper.
const states=m=>m.steps.map(s=>s.state);
let m=I.incSteps(view());
assert.deepEqual(m.steps.map(s=>s.key),I.INC_STEPS);
assert.deepEqual(states(m),['done','done','active','pending','pending','pending']);
assert.equal(m.current,2);assert.deepEqual(m.steps[2].params,{collected:63,needed:200});
assert.equal(m.steps[0].t,1215);assert.equal(m.steps[1].t,1200);assert.equal(m.steps[1].params.clear,true);
m=I.incSteps(view({evidence:{onset_t:null,method:null,statistic:null,first_t:null,as_of_t:null,collected_s:0}}));
assert.deepEqual(states(m),['done','active','pending','pending','pending','pending']);assert.equal(m.current,1);
m=I.incSteps(view({evidence:ready}));
assert.deepEqual(states(m),['done','done','done','active','pending','pending']);
assert.equal(m.steps[3].variant,'ready');assert.equal(m.steps[2].t,1399);assert.equal(m.steps[2].params.records,200);
const live={count:12,nodes:{A01:{selected:true,finished:true,state:'completed'},A10:{selected:true,finished:false,state:'running'},A11:{selected:true,finished:true,state:'needs_evidence'},A30:{selected:false,finished:false,state:'idle'}},
 used:{llm_calls:1,tokens:420,elapsed_ms:1500}};
m=I.incSteps(view({evidence:ready},{run:{...finishedRun,state:'running',status:null}}),null,live);
assert.equal(m.steps[3].variant,'running');assert.deepEqual(m.steps[3].params,{finished:2,selected:3});assert.equal(m.current,3);
m=I.incSteps(view({evidence:ready},{run:finishedRun}),{record});
assert.deepEqual(states(m),['done','done','done','done','done','next']);
assert.equal(m.current,5,'the human decision is the current step and never done');
assert.deepEqual(m.steps[4].params,{accepted:5,advisory:2,rejected:1});
m=I.incSteps(view({evidence:ready},{run:{...finishedRun,state:'error',status:null}}));
assert.equal(m.steps[3].state,'failed');assert.equal(m.current,3);
m=I.incSteps(view({status:'closed',evidence:{state:'unavailable'}}));
assert.deepEqual(states(m),['done','done','blocked','blocked','pending','pending']);
m=I.incSteps(view({status:'closed',evidence:{state:'unavailable',onset_t:null}}));
assert.deepEqual(states(m),['done','blocked','blocked','blocked','pending','pending']);
m=I.incSteps(view({evidence:{method:'data_stopped',statistic:null}}));
assert.equal(m.steps[1].variant,'stopped');assert.equal(m.steps[1].params.clear,null);

// Chart geometry: the x range covers the readings and the whole evidence window; markers sit at their seconds.
let v=view(),c=I.incChartModel(v);
const P=c.plot,X=t=>P.l+(t-c.t0)/(c.t1-c.t0)*(P.r-P.l);
assert.equal(c.t0,1000);assert.equal(c.t1,1399,'the evidence window still being collected extends the x range');
assert.ok(Math.abs(c.onset.x-X(1200))<1e-9&&c.onset.inView&&c.onset.clear===true&&c.onset.statistic===152.4);
assert.ok(Math.abs(c.injected.x-X(1198))<1e-9&&c.injected.error===2&&c.injected.x<c.onset.x);
assert.ok(Math.abs(c.detected.x-X(1215))<1e-9);
assert.ok(Math.abs(c.window.x0-X(1200))<1e-9&&Math.abs(c.window.x1-X(1399))<1e-9&&Math.abs(c.window.xReached-X(1262))<1e-9&&!c.window.ready);
assert.ok(c.inWindow(1250)&&!c.inWindow(1199));
assert.ok(c.band&&c.band.low===97&&c.band.high===103&&c.domain.max>=110,'band and readings both fit the y axis');
assert.equal(c.path.split('M').length-1,1,'one unbroken line');
assert.ok(c.xTicks.length>=2&&c.xTicks.every(k=>k.x>=P.l-1e-9&&k.x<=P.r+1e-9),'x ticks lie on the plot');
c=I.incChartModel(view({evidence:{statistic:12.5,clear:false}}));
assert.equal(c.onset.clear,false,'a statistic below the clear threshold is uncertain');
c=I.incChartModel(view({evidence:{...ready,as_of_t:1262}},{now_t:1300}));
assert.ok(c.window.ready&&c.window.xReached===c.window.x1);
c=I.incChartModel(view({truth:{fault_id:'F2',fault:'calibration_offset',started_t:500,started_at:ISO,onset_error_s:700}}));
assert.equal(c.injected.inView,false,'an injection before the plotted range is flagged, not drawn at the edge');
c=I.incChartModel(view({truth:null}));assert.equal(c.injected,null);
// Stream incidents plot the gaps between arrivals and have no band.
const gaps=view({sensor:'stream'});gaps.series.t=[1000,1001,1002,1005,1006];
c=I.incChartModel(gaps);
assert.equal(c.stream,true);assert.equal(c.band,null);assert.deepEqual(c.points.map(p=>p.v),[1,1,3,1]);
assert.equal(c.path.split('M').length-1,1,'gap series are never broken');
// Sensor lines break at ingestion gaps.
const paused=view();paused.series.t=[1000,1001,1002,1010,1011];paused.series.pressure_kpa=[100,100,100,100,100];
assert.equal(I.incChartModel(paused).path.split('M').length-1,2);
c=I.incChartModel(view(),I.INC_CHART_NARROW,4);
assert.equal(c.width,I.INC_CHART_NARROW.w);assert.ok(c.xTicks.length<=5);

// Tick steps.
assert.deepEqual(I.incTicks(1000,1399,600,6),{step:120,ticks:[1080,1200,1320]});
let tk=I.incTicks(1000,1399,600,6);assert.ok(tk.ticks.length<=6&&tk.ticks.every(x=>(x-600)%tk.step===0));
tk=I.incTicks(0,10,0,6);assert.equal(tk.step,5);assert.deepEqual(tk.ticks,[0,5,10]);

// Candidate explanations from the record.
assert.equal(I.incCandidates(null),null);
const cand=I.incCandidates(record);
assert.equal(cand.ran,true);assert.equal(cand.verdict,'multiple_supported');assert.equal(cand.stop,'resolved');assert.deepEqual([cand.used,cand.max],[2,6]);
assert.deepEqual(cand.candidates.map(x=>x.id),['hyp-2','hyp-5','hyp-4','hyp-1','hyp-3','hyp-6'],'ordered as A28 ranked them');
assert.deepEqual(cand.counts,{supported:2,open:1,refuted:3});
const byId=Object.fromEntries(cand.candidates.map(x=>[x.id,x]));
assert.deepEqual(byId['hyp-1'].probes.map(p=>[p.id,p.outcome]),[['prb-2','refutes']],'a probe with one concerned candidate is attributed exactly');
assert.deepEqual(byId['hyp-2'].probes.map(p=>[p.id,p.outcome,p.concerned,p.supports,p.refutes]),[['prb-1','supports',2,1,1]],'the only probe bearing on a supported hypothesis supported it');
assert.deepEqual(byId['hyp-3'].probes.map(p=>[p.id,p.outcome]),[['prb-1','refutes']],'the only probe bearing on a refuted hypothesis refuted it');
assert.deepEqual(byId['hyp-5'].probes.map(p=>[p.id,p.outcome]),[['prb-3',null],['prb-4','supports']],'mixed outcomes over several probes stay counts, never guessed');
assert.deepEqual(byId['hyp-6'].probes.map(p=>[p.id,p.outcome]),[['prb-3','refutes']]);
assert.deepEqual(byId['hyp-4'].probes,[],'no probe bears on a real process change');
assert.equal(byId['hyp-2'].probes[0].measured,null);
assert.deepEqual(cand.model,{status:'COMPLETED',error:null,mechanisms:['calibration_offset','stuck_sensor'],verdict:'advisory',
 compared:{agreed:['calibration_offset'],modelOnly:['stuck_sensor'],ruleSupported:['calibration_offset'],verdict:'advisory'}});
assert.deepEqual(cand.judge,{accepted:5,advisory:2,rejected:1});
// A measured-values map on a probe claim is passed through when a record carries one.
const withValues=JSON.parse(JSON.stringify(record));withValues.agents.find(a=>a.agent_id==='A25').result.claims[2].params.measured={r:1.1,sd_ratio:1};
assert.deepEqual(I.incCandidates(withValues).candidates.find(x=>x.id==='hyp-1').probes[0].measured,{r:1.1,sd_ratio:1});
// A23 without a model, A24 not run.
const bare=JSON.parse(JSON.stringify(record));
Object.assign(bare.agents.find(a=>a.agent_id==='A23').result,{status:'NEEDS_EVIDENCE',error_code:'MODEL_UNAVAILABLE',claims:[]});
Object.assign(bare.agents.find(a=>a.agent_id==='A24').result,{status:'SKIPPED',claims:[]});
const bc=I.incCandidates(bare);
assert.equal(bc.ran,false);assert.equal(bc.candidates.length,0);
assert.deepEqual([bc.model.mechanisms,bc.model.error,bc.model.compared],[null,'MODEL_UNAVAILABLE',null]);

// The probe catalog mirrors the engine's PROBE_MECHANISMS exactly.
const engine=fs.readFileSync(__dirname+'/../../src/aegisflow_dr/hypotheses.py','utf8');
const block=engine.match(/^PROBE_MECHANISMS = \{([\s\S]*?)^\}/m)[1];
const parsed=Object.fromEntries([...block.matchAll(/"(\w+)": \(([^)]*)\)/g)].map(m=>[m[1],[...m[2].matchAll(/"(\w+)"/g)].map(x=>x[1])]));
assert.deepEqual(I.INC_PROBE_MECHANISMS,parsed);
for(const probe of Object.keys(parsed))assert.ok(STRINGS['inc.rule.'+probe],`probe ${probe} has no fixed-rule sentence`);

// Agent operations: sealed record, live stream, run summary.
assert.deepEqual(I.incOps(finishedRun,record,null),{source:'record',state:'finished',status:'completed',selected:8,finished:8,completed:7,needs:1,failed:0,denied:0,skipped:0,
 llm:1,tokens:420,ms:4321,events:3});
const lo=I.incOps({...finishedRun,state:'running'},null,live);
assert.deepEqual([lo.source,lo.selected,lo.finished,lo.completed,lo.needs,lo.llm,lo.ms,lo.events],['live',3,2,1,1,1,1500,12]);
assert.equal(I.incOps({...finishedRun,state:'running'},null,{count:0,nodes:{},used:{}}).source,'summary');
assert.equal(I.incOps(null,null,null),null);

// Page brief.
let b=I.incBrief({connected:false});assert.deepEqual([b.happened.key,b.next.key],['inc.brief.connect','inc.next.connect']);
b=I.incBrief({connected:true,id:null});assert.equal(b.happened.key,'inc.brief.missing');
b=I.incBrief({connected:true,id:'INC-0001',view:null,error:'x'});assert.equal(b.happened.key,'inc.brief.error');
b=I.incBrief({connected:true,id:'INC-0001',view:view()});
assert.deepEqual([b.happened.key,b.next.key,b.next.params.left],['inc.brief.collecting','inc.next.collect',137]);
b=I.incBrief({connected:true,id:'INC-0001',view:view({evidence:ready})});assert.equal(b.next.key,'inc.next.investigate');
b=I.incBrief({connected:true,id:'INC-0001',view:view({evidence:ready},{run:finishedRun}),detail:{record}});assert.equal(b.next.key,'inc.next.decide');
b=I.incBrief({connected:true,id:'INC-0001',view:view({status:'closed',evidence:{state:'unavailable'}})});
assert.deepEqual([b.happened.key,b.next.key],['inc.brief.unavailable','inc.next.closed']);
for(const x of [b.happened.key,b.next.key,'inc.brief.locating','inc.brief.ready','inc.next.onset','inc.next.watch','inc.next.retry'])assert.ok(STRINGS[x],x);

// Wording: candidate explanations never claim a cause; ground truth is always labelled as simulation.
for(const [key,[en,tr]] of Object.entries(STRINGS)){
 if(!key.startsWith('inc.'))continue;
 assert.ok(!/\bcauses?\b|\bcaused\b|root.cause|confirm/i.test(en),`${key}: must not claim a cause or a confirmation`);
 assert.ok(!/\bneden|doğrulan|kesinleş|teyit/i.test(tr),`${key} (TR): must not claim a cause or a confirmation`);
}
assert.ok(/simulation ground truth/.test(STRINGS['inc.chart.injected'][0])&&/simülasyon gerçeği/.test(STRINGS['inc.chart.injected'][1]));

// A verified probe-loop record supplies measured values and exact per-candidate outcomes; an unmatched one is ignored.
{
 const ref={id:'investigation:'+'a'.repeat(32),sha256:'a'.repeat(64)};
 const inv={ref,probes:[{id:'prb-1',measured:{r:9.98,sd_ratio:10.1},outcomes:{'hyp-2':'supports','hyp-3':'neutral'}}]};
 assert.equal(I.incCandidates(record,inv).verified,null,'not in the run evidence: not used');
 assert.equal(I.incCandidates(record,inv).candidates.find(x=>x.id==='hyp-3').probes[0].measured,null);
 const linked=JSON.parse(JSON.stringify(record));
 linked.agents.find(a=>a.agent_id==='A24').result.evidence_refs=[ref];
 const v=I.incCandidates(linked,inv);
 assert.deepEqual(v.verified,ref);
 const probe=v.candidates.find(x=>x.id==='hyp-3').probes.find(p=>p.id==='prb-1');
 assert.deepEqual(probe.measured,{r:9.98,sd_ratio:10.1});
 assert.equal(probe.outcome,'neutral','the verified record gives the exact outcome, not an inference');
 assert.equal(I.incVerified(null,inv),false);assert.equal(I.incVerified(linked,null),false);
 assert.equal(I.incVerified({agents:[],evidence:[{...ref,sha256:'b'.repeat(64)}]},inv),false);
}

// ---------- case file: human decision and evidence chain ----------
const SHA=c=>c.repeat(64);
const decision={incident_id:'INC-0001',evidence_sha256:SHA('c'),run_id:'run-abc',decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser',note:'',
 decided_at:'2026-11-28T11:00:00Z',executed:false,sha256:SHA('e')};
const investigation={ref:{id:'investigation:x',sha256:SHA('a')},verdict:'multiple_supported',probes:[],trace_sha256:SHA('f'),
 hypotheses:[{id:'hyp-1',mechanism:'unit_change',column:'pressure_kpa',status:'refuted'},{id:'hyp-2',mechanism:'calibration_offset',column:'pressure_kpa',status:'supported'},
  {id:'hyp-5',mechanism:'source_outage',column:null,status:'supported'},{id:'hyp-7',mechanism:'calibration_offset',column:'temp_c',status:'supported'},
  {id:'hyp-4',mechanism:'genuine_change',column:'pressure_kpa',status:'open'}]};
const decidedView=(extra={})=>view({status:'closed',evidence:ready},{run:finishedRun,investigation,decision,...extra});

// Stepper: the human decision is done once a reviewer recorded one for the run shown; a decision on an earlier run is not.
m=I.incSteps(decidedView(),{record});
assert.deepEqual(states(m),['done','done','done','done','done','done']);
assert.equal(m.current,-1,'every step is done');
assert.deepEqual([m.steps[5].variant,m.steps[5].at,m.steps[5].params],['decided','2026-11-28T11:00:00Z',{decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser'}]);
m=I.incSteps(decidedView({run:{...finishedRun,run_id:'run-new'}}),{record:{...record,run_id:'run-new'}});
assert.equal(m.steps[5].state,'next','a decision on an earlier run does not decide the new one');
m=I.incSteps(decidedView({run:{...finishedRun,run_id:'run-new',state:'running',status:null}}));
assert.equal(m.steps[5].state,'pending');
m=I.incSteps(decidedView({decision:{...decision,decision:'rejected',candidate:null}}),{record});
assert.deepEqual(m.steps[5].params,{decision:'rejected',candidate:null,reviewer:'M. Keser'});
assert.equal(I.incDecisionFor(decidedView({run:null})),decision,'without a run summary the latest decision on the evidence still applies');
assert.equal(I.incDecisionFor(view()),null);
b=I.incBrief({connected:true,id:'INC-0001',view:decidedView(),detail:{record}});
assert.deepEqual([b.happened.key,b.happened.params.decision,b.next.key],['inc.brief.decided','accepted','inc.next.report']);
for(const x of ['inc.brief.decided','inc.next.report','inc.step.human.decided'])assert.ok(STRINGS[x],x);

// Chain banner: complete, waiting for the missing links, mismatch names the links, broken links, nothing yet.
const lk=(kind,i)=>({kind,digest:SHA(String(i)),at:ISO,summary:{},prev:i?SHA(String(i-1)):null,link_sha256:SHA('9')});
const caseFile=(statuses,extra={})=>({incident_id:'INC-0001',simulation:true,chain:I.INC_LINKS.filter((k,i)=>statuses[i]!=='missing').map(lk),
 checks:I.INC_LINKS.map((kind,i)=>({kind,status:statuses[i],reason:statuses[i]==='mismatch'?'evidence_bytes':null})),
 intact:true,complete:statuses.every(x=>x==='verified'),head:SHA('9'),decisions:[],content_sha256:SHA('8'),...extra});
const V='verified',MM='mismatch',M='missing';
assert.deepEqual(I.incChainBanner(caseFile([V,V,V,V,V])),{state:'complete',kinds:[]});
assert.deepEqual(I.incChainBanner(caseFile([V,V,V,V,M])),{state:'waiting',kinds:['decision']});
assert.deepEqual(I.incChainBanner(caseFile([V,V,V,M,M])),{state:'waiting',kinds:['agent_run','decision']});
assert.deepEqual(I.incChainBanner(caseFile([V,MM,V,V,M])),{state:'mismatch',kinds:['evidence']},'a mismatch wins over missing links');
assert.deepEqual(I.incChainBanner(caseFile([MM,V,V,MM,V],{complete:false})),{state:'mismatch',kinds:['baseline','agent_run']});
assert.deepEqual(I.incChainBanner(caseFile([V,V,V,V,V],{intact:false,complete:false})),{state:'broken',kinds:[]});
assert.deepEqual(I.incChainBanner(null),{state:'loading',kinds:[]});
let links=I.incChainLinks(caseFile([V,MM,V,M,M]));
assert.deepEqual(links.map(l=>[l.kind,l.index,l.status,!!l.link]),[['baseline',0,V,true],['evidence',1,MM,true],['probes',2,V,true],['agent_run',3,M,false],['decision',4,M,false]]);
assert.equal(links[1].reason,'evidence_bytes');
assert.deepEqual(I.incChainLinks(null),[]);
assert.deepEqual(I.incChainLinks({chain:[],checks:[]}).map(l=>l.status),[M,M,M,M,M],'a link with no check is missing');
// The links' recorded values, in the server's summary shapes (plant.case_file).
assert.deepEqual(I.incLinkFacts('baseline',{records:600,references:3}).map(f=>[f.key,f.value,f.type]),[['records',600,'n'],['references',3,'n']]);
assert.deepEqual(I.incLinkFacts('evidence',{first_t:1200,as_of_t:1399,records:200,method:'change_point',onset_t:1200,statistic:152.4}).map(f=>f.key),['window','records','method','onset','statistic']);
assert.deepEqual(I.incLinkFacts('evidence',{first_t:1200,as_of_t:1399})[0].value,[1200,1399]);
assert.deepEqual(I.incLinkFacts('probes',{verdict:'single_supported',supported:['calibration_offset'],ref:'investigation:x'}).map(f=>f.type),['verdict','mechs','code']);
assert.deepEqual(I.incLinkFacts('agent_run',{run_id:'run-abc',status:'completed',completed:7,judge:{accepted:5,advisory:2,rejected:1},a24_matches_probes:true}).map(f=>[f.key,f.type]),
 [['run','code'],['status','runstatus'],['completed','n'],['judge','judge'],['a24','bool']]);
assert.deepEqual(I.incLinkFacts('decision',{decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser'}).map(f=>f.value),['accepted','calibration_offset','M. Keser']);
assert.deepEqual(I.incLinkFacts('decision',null),[]);assert.deepEqual(I.incLinkFacts('other',{}),[]);
for(const kind of I.INC_LINKS){
 assert.ok(STRINGS['chain.kind.'+kind],kind);
 for(const f of I.incLinkFacts(kind,{judge:{}}))assert.ok(STRINGS['chain.f.'+f.key],`chain.f.${f.key}`);
}
for(const reason of ['baseline_digest','evidence_bytes','probe_trace','run_trace_or_a24_evidence','decision_digest','unknown'])assert.ok(STRINGS['chain.reason.'+reason],reason);
for(const st of ['verified','mismatch','missing'])assert.ok(STRINGS['chain.status.'+st]);
for(const st of ['complete','waiting','mismatch','broken','loading'])assert.ok(STRINGS['chain.banner.'+st]&&STRINGS['rep.chain.'+st]&&STRINGS['rep.sum.chain.'+st],st);
// The chain's link order and decisions mirror the engine (aegisflow_dr.casefile).
{const casefile=fs.readFileSync(__dirname+'/../../src/aegisflow_dr/casefile.py','utf8'),tup=name=>[...casefile.match(new RegExp('^'+name+' = \\(([^)]*)\\)','m'))[1].matchAll(/"(\w+)"/g)].map(x=>x[1]);
 assert.deepEqual(I.INC_LINKS,tup('LINKS'));assert.deepEqual(I.INC_DECISIONS,tup('DECISIONS'));
 assert.match(casefile,/^MAX_REVIEWER, MAX_NOTE = 60, 500$/m);}

// The case file is read again only when the evidence, the run, its state or the decision changed.
const k0=I.incCaseKey(decidedView());
assert.equal(I.incCaseKey(decidedView()),k0);
assert.notEqual(I.incCaseKey(decidedView({decision:{...decision,sha256:SHA('d')}})),k0);
assert.notEqual(I.incCaseKey(decidedView({run:{...finishedRun,state:'running'}})),k0);
assert.notEqual(I.incCaseKey(view()),k0);

// Decision form: what may be decided and with which candidate.
let dm=I.incDecisionModel(decidedView({decision:null}),{record});
assert.equal(dm.ready,true);assert.equal(dm.wait,null);
assert.deepEqual(dm.candidates,[{mechanism:'calibration_offset',columns:['pressure_kpa','temp_c']},{mechanism:'source_outage',columns:[]}],'supported mechanisms only, once each');
assert.deepEqual(dm.options.map(o=>[o.value,o.enabled,o.reason]),[['accepted',true,null],['rejected',true,null],['more_evidence',true,null]]);
const none={...investigation,hypotheses:investigation.hypotheses.map(x=>({...x,status:x.status==='supported'?'open':x.status}))};
dm=I.incDecisionModel(decidedView({decision:null,investigation:none}),{record});
assert.deepEqual(dm.options.map(o=>[o.value,o.enabled,o.reason]),[['accepted',false,'none_supported'],['rejected',true,null],['more_evidence',true,null]],'nothing supported: accepting is disabled with the reason');
assert.deepEqual(I.incDecisionModel(decidedView({decision:null,investigation:null}),{record}).candidates,[]);
const wait=(v,d)=>I.incDecisionModel(v,d).wait;
assert.equal(wait(view(),null),'evidence');
assert.equal(wait(view({evidence:ready}),null),'run');
assert.equal(wait(view({evidence:ready},{run:{...finishedRun,state:'running'}}),null),'running');
assert.equal(wait(view({evidence:ready},{run:{...finishedRun,state:'error'}}),null),'failed');
assert.equal(wait(view({evidence:ready},{run:finishedRun}),null),'record','a finished run is decided on only with its sealed record');
dm=I.incDecisionModel(view(),null);
assert.ok(dm.options.every(o=>!o.enabled),'nothing can be chosen before the run finished');
for(const w of ['evidence','run','running','failed','record'])assert.ok(STRINGS['dec.wait.'+w],w);
dm=I.incDecisionModel(decidedView(),{record});
assert.equal(dm.current,decision);assert.equal(dm.other,null);
dm=I.incDecisionModel(decidedView({run:{...finishedRun,run_id:'run-new'}}),{record});
assert.equal(dm.current,null);assert.equal(dm.other,decision,'a decision on an earlier run is shown as such');

// Client-side input check before sending (the server stays the judge).
dm=I.incDecisionModel(decidedView({decision:null}),{record});
let input=I.incDecisionInput({decision:'accepted',candidate:'calibration_offset',reviewer:'  M.   Keser ',note:' first\n\nline '},dm);
assert.deepEqual(input,{ok:true,errors:{},body:{decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser',note:'first line'}});
input=I.incDecisionInput({decision:'rejected',candidate:'calibration_offset',reviewer:'Ada',note:''},dm);
assert.deepEqual(input.body,{decision:'rejected',candidate:null,reviewer:'Ada',note:''},'only an accepted decision names a candidate');
assert.deepEqual(I.incDecisionInput({decision:'accepted',candidate:'unit_change',reviewer:'Ada'},dm).errors,{candidate:'choose'},'a refuted candidate cannot be accepted');
assert.deepEqual(I.incDecisionInput({decision:'accepted',candidate:null,reviewer:'Ada'},dm).errors,{candidate:'choose'});
assert.deepEqual(I.incDecisionInput({decision:null,reviewer:''},dm).errors,{decision:'choose',reviewer:'empty'});
assert.deepEqual(I.incDecisionInput({decision:'more_evidence',reviewer:'x'.repeat(61)},dm).errors,{reviewer:'long'});
assert.equal(I.incDecisionInput({decision:'more_evidence',reviewer:'ş'.repeat(60)},dm).ok,true,'60 characters, counted as characters');
assert.deepEqual(I.incDecisionInput({decision:'more_evidence',reviewer:'A​da'},dm).errors,{reviewer:'printable'});
assert.deepEqual(I.incDecisionInput({decision:'more_evidence',reviewer:'Ada',note:'n'.repeat(501)},dm).errors,{note:'long'});
assert.deepEqual(I.incDecisionInput({decision:'more_evidence',reviewer:'Ada',note:'a\u0007b'},dm).errors,{note:'printable'});
const off=I.incDecisionModel(decidedView({decision:null,investigation:none}),{record});
assert.deepEqual(I.incDecisionInput({decision:'accepted',candidate:'calibration_offset',reviewer:'Ada'},off).errors,{decision:'choose',candidate:'choose'});
assert.deepEqual(I.incDecisionInput({decision:'rejected',reviewer:'Ada'},I.incDecisionModel(view(),null)).errors,{decision:'choose'},'nothing is sent before the run finished');
for(const [field,codes] of Object.entries({decision:['choose'],candidate:['choose'],reviewer:['empty','long','printable'],note:['long','printable']}))
 for(const code of codes)assert.ok(STRINGS[`dec.err.${field}.${code}`],`dec.err.${field}.${code}`);
for(const d of I.INC_DECISIONS)assert.ok(STRINGS['dec.d.'+d]&&STRINGS['dec.d.'+d+'.x'],d);
// Refusals: the server's message for invalid input, the evidence state for 409, gone for 404.
assert.deepEqual(I.incDecisionError({status:422,body:{error:'INPUT_REJECTED',message:'Only a candidate the probes support on the frozen evidence can be accepted'}}),
 {key:'dec.err.rejected',params:{reason:'Only a candidate the probes support on the frozen evidence can be accepted'}});
assert.deepEqual(I.incDecisionError({status:409,body:{error:'EVIDENCE_NOT_READY',evidence:{state:'collecting',onset_t:1,needed_s:200,collected_s:63}}}),{key:'cc.err.notready',params:{n:63,needed:200}});
assert.equal(I.incDecisionError({status:404,body:null}).key,'cc.err.notfound');
assert.equal(I.incDecisionError({status:422,body:null,message:'x'}).params.reason,'x');
assert.equal(I.incDecisionError({status:500,body:null}).key,null);

// Wording: the decision, chain and report strings say a decision is recorded and never executed, keep "accepted" a
// working explanation, mention a root cause only to deny it, and name the digest an integrity check, not a signature.
assert.match(STRINGS['dec.badge'][1],/Karar kaydedilir, asla uygulanmaz/);
assert.match(STRINGS['dec.accept.meaning'][0],/working explanation.*It is not a root cause\./);
assert.match(STRINGS['dec.accept.meaning'][1],/çalışma açıklaması.*Kök neden değildir\./);
assert.match(STRINGS['chain.x'][0],/integrity check, not a signature/);assert.match(STRINGS['chain.x'][1],/bütünlük denetimidir, imza değildir/);
for(const [key,[en,tr]] of Object.entries(STRINGS)){
 if(!/^(dec|chain|rep)\./.test(key))continue;
 const denied=en.replace(/not a root cause/gi,''),deniedTr=tr.replace(/kök neden değil(dir)?/gi,'');
 assert.ok(!/\bcause[sd]?\b|confirm/i.test(denied),`${key}: a cause appears only as "not a root cause"; no confirmation`);
 assert.ok(!/\bneden\b|\bteyit|kesinleş/i.test(deniedTr),`${key} (TR): a cause appears only as "kök neden değil"; no confirmation`);
 assert.ok(!/\bexecuted\b/i.test(en)||/never executed|nothing (is|was) executed|^executed$/i.test(en),`${key}: a decision is never executed`);
}

console.log('incident: stepper, evidence, chart, candidates, operations, brief, evidence chain and decision form verified.');
