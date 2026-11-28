// SPDX-License-Identifier: Apache-2.0
// The incident report's pure core: the section model built from the incident view, its case file and the sealed run
// record, the summary sentences and the page brief. Every value checked here is passed through from the fixture.
const assert=require('node:assert/strict');
const fs=require('node:fs');
global.language='en';
const {STRINGS}=require('./strings.js');
const R=require('./report.js');

const ISO='2026-11-28T10:00:00Z',SHA=c=>c.repeat(64);
const t=Array.from({length:400},(_,i)=>1000+i);
const evidence={state:'ready',method:'change_point',onset_t:1200,onset_at:ISO,statistic:152.4,clear:true,first_t:1200,as_of_t:1399,as_of:ISO,
 needed_s:200,collected_s:200,records:200,sha256:SHA('c')};
const run={run_id:'run-abc',state:'finished',status:'completed',started_at:ISO,finished_at:'2026-11-28T10:05:00Z',events:3};
const decision={incident_id:'INC-0001',evidence_sha256:SHA('c'),run_id:'run-abc',decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser',
 note:'Matches the calibration log.',decided_at:'2026-11-28T11:00:00Z',executed:false,sha256:SHA('e')};
const investigation={ref:{id:'investigation:x',sha256:SHA('a')},verdict:'single_supported',probes:[{id:'prb-1',measured:{r:1.0,sd_ratio:1.02,mean_shift_sd:1.6},outcomes:{'hyp-1':'supports','hyp-2':'refutes'}}],
 trace_sha256:SHA('f'),hypotheses:[{id:'hyp-1',mechanism:'calibration_offset',column:'pressure_kpa',status:'supported'},{id:'hyp-2',mechanism:'noise_increase',column:'pressure_kpa',status:'refuted'}]};
function view(extra={},incident={}){
 return {simulation:true,now_t:1400,live_start_t:600,units:{pressure_kpa:'kPa'},bands:{pressure_kpa:{mean:100,sd:1,low:97,high:103}},
  baseline_digest:SHA('b'),settings:{window_seconds:200,clear_statistic:30},series:{t,pressure_kpa:t.map(x=>x<1200?100:101.6)},
  incident:{id:'INC-0001',sensor:'pressure_kpa',status:'closed',severity:'high',opened_t:1215,opened_at:ISO,closed_t:1380,closed_at:ISO,
   findings:[{check:'distribution_shift',column:'pressure_kpa',severity:'high',source:'baseline',detail:{psi:0.9,threshold:0.25,baseline_mean:100,current_mean:101.6},first_t:1215,first_at:ISO}],
   checks:['distribution_shift'],window:{records:200,first_t:1016,last_t:1215,as_of:ISO,sha256:SHA('a')},run_id:'run-abc',evidence,
   truth:{fault_id:'F1',fault:'calibration_offset',started_t:1198,started_at:ISO,onset_error_s:2},...incident},
  run,runs_active:null,investigation,decision,...extra};
}
const claim=(text_key,params)=>({text_key,params,evidence_refs:[]});
const record={run_id:'run-abc',status:'completed',finished_at:'2026-11-28T10:05:00Z',
 agents:[
  {agent_id:'A23',selected:true,result:{agent_id:'A23',status:'COMPLETED',error_code:null,evidence_refs:[],
   claims:[claim('a23.suggested',{mechanisms:['calibration_offset']}),claim('a23.compared',{agreed:['calibration_offset'],model_only:[],rule_supported:['calibration_offset']})]}},
  {agent_id:'A24',selected:true,result:{agent_id:'A24',status:'COMPLETED',error_code:null,evidence_refs:[investigation.ref],
   claims:[claim('a24.summary',{verdict:'single_supported'}),
    claim('a24.hypothesis',{hypothesis:'hyp-1',mechanism:'calibration_offset',column:'pressure_kpa',status:'supported'}),
    claim('a24.hypothesis',{hypothesis:'hyp-2',mechanism:'noise_increase',column:'pressure_kpa',status:'refuted'})]}},
  {agent_id:'A25',selected:true,result:{agent_id:'A25',status:'COMPLETED',error_code:null,evidence_refs:[],
   claims:[claim('a25.stop',{stop_reason:'resolved',used:1,max_probes:6}),claim('a25.probe',{probe_id:'prb-1',probe:'spread_ratio',column:'pressure_kpa',round:1,supports:1,refutes:1,neutral:0})]}}],
 judge:{verdicts:[{agent:'A23',claim:0,verdict:'advisory'},{agent:'A23',claim:1,verdict:'advisory'}],accepted:6,advisory:2,rejected:0}};
const detail={run_id:'run-abc',record};
const LINKS=['baseline','evidence','probes','agent_run','decision'];
const link=(kind,i,summary)=>({kind,digest:SHA(String(i)),at:ISO,summary,prev:i?SHA(String(i-1)):null,link_sha256:SHA(String(i+1))});
const summaries={baseline:{records:600,references:3},evidence:{first_t:1200,as_of_t:1399,records:200,method:'change_point',onset_t:1200,statistic:152.4},
 probes:{verdict:'single_supported',supported:['calibration_offset'],ref:'investigation:x'},
 agent_run:{run_id:'run-abc',status:'completed',completed:3,judge:{accepted:6,advisory:2,rejected:0},a24_matches_probes:true},
 decision:{decision:'accepted',candidate:'calibration_offset',reviewer:'M. Keser'}};
function caseFile(n=5,statuses=null){
 const chain=LINKS.slice(0,n).map((k,i)=>link(k,i,summaries[k]));
 const checks=LINKS.map((kind,i)=>({kind,status:statuses?.[i]??(i<n?'verified':'missing'),reason:statuses?.[i]==='mismatch'?'decision_digest':null}));
 return {incident_id:'INC-0001',simulation:true,chain,checks,intact:true,complete:checks.every(c=>c.status==='verified'),head:chain.length?chain[chain.length-1].link_sha256:null,
  decisions:n===5?[{...decision,decision:'more_evidence',candidate:null,sha256:SHA('d'),decided_at:'2026-11-28T10:30:00Z'},decision]:[],content_sha256:SHA('9')};
}

// The full model: every section in order, values passed through from the fixture.
let m=R.repModel(view(),caseFile(),detail);
assert.deepEqual(R.REP_SECTIONS,['summary','timeline','chart','findings','candidates','model','decision','chain','limits']);
assert.deepEqual([m.id,m.sensor,m.severity,m.status,m.simulation],['INC-0001','pressure_kpa','high','closed',true]);
assert.deepEqual(m.timeline.map(s=>[s.key,s.state]),[['detected','done'],['onset','done'],['evidence','done'],['agents','done'],['judge','done'],['human','done']]);
assert.equal(m.timeline[5].at,'2026-11-28T11:00:00Z');
assert.deepEqual(m.findings,view().incident.findings);
assert.equal(m.findings[0].detail.psi,0.9);
assert.deepEqual(m.candidates.candidates.map(c=>[c.mechanism,c.status]),[['calibration_offset','supported'],['noise_increase','refuted']]);
assert.deepEqual(m.candidates.verified,investigation.ref,'measured values come from the probe-loop record the run holds as A24 evidence');
assert.deepEqual(m.candidates.candidates[0].probes[0].measured,{r:1.0,sd_ratio:1.02,mean_shift_sd:1.6});
assert.deepEqual(m.candidates.judge,{accepted:6,advisory:2,rejected:0});
assert.deepEqual(m.candidates.model.mechanisms,['calibration_offset']);
assert.equal(m.decision,decision);assert.equal(m.other,null);
assert.deepEqual(m.history.map(d=>d.decision),['more_evidence','accepted'],'every version, oldest first');
assert.deepEqual(m.chain.map(l=>[l.kind,l.status,l.link.digest]),LINKS.map((k,i)=>[k,'verified',SHA(String(i))]));
assert.deepEqual(m.chain[3].facts.find(f=>f.key==='judge').value,{accepted:6,advisory:2,rejected:0});
assert.deepEqual(m.banner,{state:'complete',kinds:[]});
assert.deepEqual([m.head,m.content],[SHA('5'),SHA('9')]);
assert.deepEqual(m.limits,['sim','supported','decision','model','digest']);

// Summary sentences: keys with raw parameters, in reading order.
assert.deepEqual(m.summary.map(x=>x.key),['rep.sum.detected','rep.sum.onset','rep.sum.evidence','rep.sum.agents','rep.sum.decision.accepted','rep.sum.chain.complete']);
assert.deepEqual(m.summary[0].params,{id:'INC-0001',sensor:'pressure_kpa',severity:'high',n:1,t:1215});
assert.deepEqual(m.summary[2].params,{records:200,from:1200,to:1399,digest:SHA('c')});
assert.deepEqual(m.summary[3].params,{status:'completed',s:1,o:0,r:1,accepted:6,advisory:2,rejected:0});
assert.deepEqual(m.summary[4].params,{reviewer:'M. Keser',candidate:'calibration_offset',at:'2026-11-28T11:00:00Z'});

// Before a decision: the chain waits for it, the summary says none was recorded, the stepper's human step is next.
m=R.repModel(view({decision:null}),caseFile(4),detail);
assert.deepEqual(m.banner,{state:'waiting',kinds:['decision']});
assert.deepEqual(m.summary.slice(-2).map(x=>[x.key,x.params]),[['rep.sum.nodecision',{}],['rep.sum.chain.waiting',{kinds:['decision']}]]);
assert.equal(m.timeline[5].state,'next');assert.deepEqual(m.history,[]);
// A mismatch is named.
m=R.repModel(view(),caseFile(5,['verified','verified','verified','verified','mismatch']),detail);
assert.deepEqual(m.banner,{state:'mismatch',kinds:['decision']});assert.equal(m.chain[4].reason,'decision_digest');
// A record of another run is not used; a decision on an earlier run is shown as such.
m=R.repModel(view({run:{...run,run_id:'run-new'}}),caseFile(4),detail);
assert.equal(m.candidates,null);assert.equal(m.decision,null);assert.equal(m.other,decision);
assert.equal(m.summary[3].key,'rep.sum.norecord');
// Earlier stages: no run, a run still working or stopped, no evidence, no onset, no case file.
const keyAt=(v,i)=>R.repModel(v,null,null).summary[i].key;
assert.equal(keyAt(view({run:null,decision:null}),3),'rep.sum.norun');
assert.equal(keyAt(view({run:{...run,state:'running',status:null},decision:null}),3),'rep.sum.running');
assert.equal(keyAt(view({run:{...run,state:'error',status:null},decision:null}),3),'rep.sum.runerror');
const open={state:'unavailable',onset_t:null,method:null,statistic:null,first_t:null,as_of_t:null,records:null,sha256:null,needed_s:200,collected_s:0};
m=R.repModel(view({run:null,decision:null,investigation:null},{evidence:open}),null,null);
assert.deepEqual(m.summary.map(x=>x.key),['rep.sum.detected','rep.sum.noonset','rep.sum.noevidence','rep.sum.norun','rep.sum.nodecision','rep.sum.chain.loading']);
assert.deepEqual([m.head,m.content,m.chain,m.history],[null,null,[],[]]);
assert.equal(R.repModel(view({simulation:false}),null,null).simulation,false);

// Every summary key, section, limit and brief key has both languages.
for(const k of ['rep.sum.detected','rep.sum.onset','rep.sum.noonset','rep.sum.evidence','rep.sum.noevidence','rep.sum.norun','rep.sum.running','rep.sum.runerror',
 'rep.sum.norecord','rep.sum.agents','rep.sum.decision.accepted','rep.sum.decision.rejected','rep.sum.decision.more_evidence','rep.sum.nodecision',
 'rep.sum.chain.complete','rep.sum.chain.waiting','rep.sum.chain.mismatch','rep.sum.chain.broken','rep.sum.chain.loading'])assert.ok(STRINGS[k],k);
for(const s of R.REP_SECTIONS)assert.ok(STRINGS['rep.s.'+s],s);
for(const l of R.REP_LIMITS)assert.ok(STRINGS['rep.limit.'+l],l);
// The limits say what the report must never be read as.
assert.match(STRINGS['rep.limit.supported'][0],/It is not a root cause\./);assert.match(STRINGS['rep.limit.supported'][1],/Kök neden değildir\./);
assert.match(STRINGS['rep.limit.decision'][0],/never executed/);assert.match(STRINGS['rep.limit.decision'][1],/asla uygulanmaz/);
assert.match(STRINGS['rep.limit.sim'][0],/Simulation only/);assert.match(STRINGS['rep.print'][1],/PDF olarak kaydet/);

// Page brief.
let b=R.repBrief({connected:false});assert.deepEqual([b.happened.key,b.next.key],['rep.brief.connect','inc.next.connect']);
b=R.repBrief({connected:true,id:null});assert.deepEqual([b.happened.key,b.happened.params.id,b.next.key],['rep.brief.missing','—','rep.next.back']);
b=R.repBrief({connected:true,id:'INC-0001',missing:true});assert.equal(b.happened.key,'rep.brief.missing');
b=R.repBrief({connected:true,id:'INC-0001',data:null,error:'down'});assert.deepEqual([b.happened.key,b.happened.params.reason,b.next.key],['rep.brief.error','down','rep.next.retry']);
b=R.repBrief({connected:true,id:'INC-0001',data:null});assert.deepEqual([b.happened.key,b.next.key],['rep.brief.loading','rep.next.wait']);
b=R.repBrief({connected:true,id:'INC-0001',data:{}});assert.deepEqual([b.happened.key,b.happened.params.id,b.next.key],['rep.brief.ready','INC-0001','rep.next.print']);
for(const k of ['rep.brief.connect','rep.brief.missing','rep.brief.error','rep.brief.loading','rep.brief.ready','rep.next.back','rep.next.retry','rep.next.wait','rep.next.print'])assert.ok(STRINGS[k],k);
assert.ok(R.REP_ID.test('INC-0001')&&!R.REP_ID.test('INC-1')&&!R.REP_ID.test('../x'));

// The page is wired: index.html loads report.js before app.js and has the report screen; app.js routes /report; the print
// stylesheet hides the app around the sheet and sets A4 margins.
const html=fs.readFileSync(__dirname+'/index.html','utf8'),app=fs.readFileSync(__dirname+'/app.js','utf8'),css=fs.readFileSync(__dirname+'/style.css','utf8');
assert.ok(html.indexOf('/report.js')>html.indexOf('/incident.js')&&html.indexOf('/report.js')<html.indexOf('/app.js'),'report.js loads after incident.js and before app.js');
assert.match(html,/data-screen="report"[^>]*><div id="screen-report">/);
assert.match(app,/'\/report':'report'/);assert.match(app,/report:renderReport/);
assert.match(css,/@page\{size:A4;margin:16mm\}/);
assert.match(css,/@media print\{[\s\S]*\.app-header,\.sidebar,\.page-brief,\.notice[\s\S]*\.rep-actions\{display:none!important\}/);
console.log('report: section model, summary, brief and print wiring verified.');
