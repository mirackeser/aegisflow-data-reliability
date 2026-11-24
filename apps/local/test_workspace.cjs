// SPDX-License-Identifier: Apache-2.0
const assert=require('node:assert/strict');
const P=require('./presentation.js');
const analysis={dimensions:{completeness:{passed:19,total:21,ratio:0.9048},uniqueness:{passed:5,total:7,ratio:0.7143},validity:{passed:0,total:0,ratio:null},record_health:{passed:1,total:7,ratio:0.1429}},
 schema_issues:[{check:'missing_column',column:'order_total'}],
 heatmap:[{column:'customer_id',check:'not_null',records:1},{column:'order_id',check:'unique',records:4},{column:'order_total',check:'not_null',records:9}],
 affected_records:[{record:1,issues:['unique:order_id']},{record:2,issues:['not_null:order_total','unique:order_id']},{record:3,issues:['not_null:customer_id']}]};
// dimensions keep exact counts and never fabricate a ratio
const rows=P.dimensionRows(analysis);
assert.deepEqual(rows.map(r=>r.key),['completeness','uniqueness','validity','record_health']);
assert.equal(rows[2].ratio,null);assert.equal(P.dimensionRows(null).length,4);
// review order is rule based: schema first, revenue-affecting next, then larger groups
const groups=P.workspaceGroups(analysis);
assert.deepEqual(groups.map(g=>g.id),['schema:missing_column:order_total','not_null:order_total','unique:order_id','not_null:customer_id']);
assert.equal(P.priorityOf('not_null','customer_id'),3);assert.equal(P.priorityOf('amount_format','order_total'),2);
// records are filtered by check AND column, so a blank customer is not shown under a blank amount
assert.deepEqual(P.recordsFor(analysis,groups[1]).map(r=>r.record),[2]);
assert.deepEqual(P.recordsFor(analysis,groups[2]).map(r=>r.record),[1,2]);
assert.deepEqual(P.recordsFor(analysis,groups[0]),[]);
// human review progress drives the lane of the review step
const actions=[{id:'ACT-01'},{id:'ACT-02'}];
assert.deepEqual(P.reviewProgress(actions,{'ACT-01':{decision:'accepted'}}),{total:2,decided:1,pending:1});
const review={id:'human_review',status:'awaiting'};
assert.equal(P.laneOf(review,P.reviewProgress(actions,{})),'next');
assert.equal(P.laneOf(review,P.reviewProgress(actions,{'ACT-01':{},'ACT-02':{}})),'done');
assert.equal(P.stepState(review,P.reviewProgress(actions,{'ACT-01':{},'ACT-02':{}})),'completed');
assert.equal(P.laneOf({status:'unavailable'}),'unavailable');assert.equal(P.laneOf({status:'disabled'}),'unavailable');
assert.equal(P.laneOf({status:'skipped'}),'skipped');assert.equal(P.laneOf({status:'rejected'}),'skipped');
// number formatting never rounds a near-miss up to 100% and keeps exact decimals
assert.equal(P.percent(0.9996),'99.9%');assert.equal(P.percent(1),'100.0%');assert.equal(P.percent(null),'—');assert.equal(P.percent(0.9048,'tr'),'90,4%');
assert.equal(P.formatAmount('1234567.5'),'1,234,567.50');assert.equal(P.formatAmount('1234567.50','tr'),'1.234.567,50');assert.equal(P.formatAmount(null),'—');
// source classes
assert.equal(P.summarizeResult({source:'synthetic-sample',cases:[]}).source,'sample');
assert.equal(P.runLabel({result:{input:{name:'q3.csv'}}}),'q3.csv');assert.equal(P.runLabel({scenario:'null_total'}),'null_total');
console.log('workspace assertions passed: exact dimensions, rule-based order, column-aware records, review lanes and number formatting.');
// A synthetic sample must never be reported as an uploaded file or as the PostgreSQL example.
{
 const run={run_id:'r1',finished_at:'2026-01-01T00:00:00Z',status:'COMPLETED',scenario:'upload',events:[],result:{source:'synthetic-sample',status:'PASS',judge:{decision:'ACCEPT'},cases:[]}};
 const html=P.readableReport(run);
 assert.ok(html.includes('SYNTHETIC SAMPLE')&&!html.includes('Uploaded file')&&!html.includes('EXAMPLE DATA'));
 assert.ok(require('node:fs').readFileSync(__dirname+'/i18n.js','utf8').includes('"SYNTHETIC SAMPLE": "SENTETİK ÖRNEK"'),'Turkish report label missing');
}
console.log('synthetic sample labelling verified.');
// a connected source is classified on its own, never as an upload or a sample
assert.equal(P.summarizeResult({source:'connected-source',cases:[]}).source,'connected');
assert.equal(P.summarizeResult({source:'local-upload',cases:[]}).source,'uploaded');
// execution timeline: measured spans only, one row per step, null when the run has no usable time span
const events=[{agent:'A09 / Contract check',state:'RUNNING',at:'2026-01-01T00:00:00.010Z'},{agent:'A09 / Contract check',state:'COMPLETED',at:'2026-01-01T00:00:00.030Z'},{agent:'A10 / Data profiling',state:'COMPLETED',at:'2026-01-01T00:00:00.040Z'},{agent:'A26 / x',state:'COMPLETED',at:'bad'}];
const gantt=P.timelineRows(events,'2026-01-01T00:00:00.000Z','2026-01-01T00:00:00.100Z');
assert.equal(gantt.total,100);assert.deepEqual(gantt.rows.map(r=>[r.id,r.offset,r.duration,r.state]),[['A09',10,20,'COMPLETED'],['A10',40,0,'COMPLETED']]);
assert.equal(P.timelineRows(events,'2026-01-01T00:00:00.100Z','2026-01-01T00:00:00.100Z'),null);
assert.equal(P.timelineRows(events,'nope','2026-01-01T00:00:00.100Z'),null);
assert.deepEqual(P.timelineRows(undefined,'2026-01-01T00:00:00Z','2026-01-01T00:00:01Z').rows,[]);
// drift stream choice and series never invent a value
const mk=(key,at,v)=>({key,label:key,runs:[{at,dimensions:{record_health:v,completeness:1,uniqueness:null,validity:1}}]});
const monitoring={streams:[mk('a','2026-01-01',0.5),mk('b','2026-02-01',1),mk('c',undefined,1)]};
assert.equal(P.pickStream(monitoring).key,'b');assert.equal(P.pickStream(monitoring,'a').key,'a');assert.equal(P.pickStream(monitoring,'zzz').key,'b');
assert.equal(P.pickStream({streams:[]}),null);assert.equal(P.pickStream(undefined),null);
const series=P.driftSeries(monitoring.streams[0]);
assert.deepEqual(series.map(s=>s.key),['record_health','completeness','uniqueness','validity']);assert.deepEqual(series[2].values,[null]);
console.log('timeline and drift helpers verified.');
// evidence rows keep counts, and an undefined rate stays null
const rate=(value,numerator,denominator,interval)=>({value,numerator,denominator,interval_95:interval});
const split=()=>({per_check:{unique:{recall:rate(1,4,4,[0.51,1]),precision:rate(null,0,0,null),false_positives:0,false_negatives:0}},overall:{recall:rate(0.5,2,4,[0.1,0.9]),precision:rate(1,2,2,[0.34,1]),false_positives:1,false_negatives:2}});
const report={results:{diagnose_csv:{development:split(),heldout:split()}}};
const evidence=P.evidenceRows(report,'diagnose_csv');
assert.deepEqual(evidence.map(r=>r.check),['unique','overall']);
assert.deepEqual(evidence[0].cells.development.precision,{value:null,numerator:0,denominator:0,low:null});
assert.equal(evidence[0].cells.heldout.recall.low,0.51);assert.equal(evidence[1].cells.development.errors,3);
assert.deepEqual(P.evidenceRows(report,'missing'),[]);assert.deepEqual(P.evidenceRows(undefined,'x'),[]);
console.log('evidence rows verified.');
// role cards never show a role as running unless a plan step for it completed
const map={roles:[{agent_id:'A09',status:'implemented'},{agent_id:'A23',status:'unavailable'},{agent_id:'A01',status:'planned'}]};
const planned=[{role:'A09',status:'completed'},{role:'A23',status:'unavailable'}];
const rv=P.roleView(map,planned);
assert.deepEqual(rv.roles.map(r=>r.current),['ran','skipped',null]);assert.equal(rv.ran,1);
assert.deepEqual(P.roleView(map,undefined).roles.map(r=>r.current),[null,null,null]);
assert.deepEqual(P.roleView(map,planned,'planned').roles.map(r=>r.agent_id),['A01']);
assert.equal(P.roleView(map,planned,'all').roles.length,3);assert.equal(P.roleView(undefined,undefined).roles.length,0);
console.log('role view verified.');
// Baseline panel helpers: exact file bytes as base64, and the "as of" clock follows the baseline's timestamps.
{
 process.env.TZ='Europe/Istanbul';
 const vm=require('node:vm'),fs=require('node:fs');
 const context=vm.createContext({btoa,Uint8Array,String,Number,Date,Math,Promise,console});
 vm.runInContext(fs.readFileSync(__dirname+'/baseline.js','utf8'),context);
 const run=code=>vm.runInContext(code,context);
 const file=bytes=>({arrayBuffer:async()=>Uint8Array.from(bytes).buffer});
 const big=Array.from({length:100003},(_,i)=>(i*37)%256);
 Promise.all([context.blBase64(file([0xef,0xbb,0xbf,0xff])),context.blBase64(file(big)),context.blBase64(file([]))]).then(([bom,large,empty])=>{
  assert.equal(bom,'77u//w==');
  assert.equal(large,Buffer.from(big).toString('base64'));
  assert.equal(empty,'');
  console.log('baseline file bytes verified.');
 });
 run("blAsOf='2026-11-24T10:00:00'");
 assert.equal(context.blAsOfForRequest({time_aware:true}),'2026-11-24T07:00:00Z');
 run("blAsOf='2026-11-24T10:00'");
 assert.equal(context.blAsOfForRequest({time_aware:true}),'2026-11-24T07:00:00Z');
 assert.equal(context.blAsOfForRequest({time_aware:false}),'2026-11-24T10:00');
 assert.equal(context.blAsOfForRequest({time_aware:null}),'2026-11-24T10:00');
 assert.equal(context.blAsOfForRequest(null),'2026-11-24T10:00');
 run("blAsOf=''");
 assert.equal(context.blAsOfForRequest({time_aware:true}),'');
 const pattern=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/;
 const local=context.blNow(),utc=context.blNow(true);
 assert.match(local,pattern);assert.match(utc,pattern);
 // Istanbul is UTC+3 all year: the local wall clock is three hours ahead of UTC.
 const gap=(Date.parse(local+'Z')-Date.parse(utc+'Z'))/1000;
 assert.ok(Math.abs(gap-10800)<=2,`local minus UTC is ${gap} s`);
 run("blList={baselines:[{name:'a',time_aware:true},{name:'b',time_aware:false},{name:'c',time_aware:null}]}");
 assert.equal(context.blAsOfHint(context.blEntry('a')),'bl.asof.x.aware');
 assert.equal(context.blAsOfHint(context.blEntry('b')),'bl.asof.x.local');
 assert.equal(context.blAsOfHint(context.blEntry('c')),'bl.asof.x.none');
 assert.equal(context.blAsOfHint(context.blEntry('missing')),'bl.asof.x.none');
 run("blClock='utc'");
 assert.equal(context.blAsOfHint(context.blEntry('b')),'bl.asof.x.utc');
 assert.equal(context.blClockField(context.blEntry('a')),null);
 assert.equal(context.blClockField(context.blEntry('c')),null);
 console.log('baseline as-of clock verified.');
 // Candidate explanations are shown only when they describe the baseline, file and "as of" time of the shown comparison.
 const shown={baseline_digest:'b'.repeat(64),source_sha256:'c'.repeat(64),as_of:null};
 assert.equal(context.hyMatches({...shown,trace_sha256:'x'},shown),true);
 assert.equal(context.hyMatches({...shown,baseline_digest:'d'.repeat(64)},shown),false);
 assert.equal(context.hyMatches({...shown,source_sha256:'d'.repeat(64)},shown),false);
 assert.equal(context.hyMatches({...shown,as_of:'2026-01-01T00:00:00'},shown),false);
 assert.equal(context.hyMatches(undefined,shown),false);assert.equal(context.hyMatches(shown,null),false);
 const notices=[];let answer=null;
 Object.assign(context,{t:k=>k,render:()=>{},setNotice:m=>notices.push(m),requireSession:()=>true,JSON_HEADERS:{},
  document:{getElementById:()=>null},request:async()=>answer,__shown:shown});
 (async()=>{
  run("blBusy=false;blHy=null;blResult=__shown;blResultRequest={name:'p',csv_b64:''}");
  answer={name:'p',investigation:{...shown,trace_sha256:'x'}};
  await context.explainBaseline();
  assert.equal(run('blHy.record.trace_sha256'),'x');assert.equal(run('blHy.error'),'');
  // The baseline was replaced between Compare and Explain: the answer names another baseline and is not shown.
  run("blHy=null");
  answer={name:'p',investigation:{...shown,baseline_digest:'d'.repeat(64),trace_sha256:'y'}};
  await context.explainBaseline();
  assert.equal(run('blHy.record'),null);assert.equal(run('blHy.error'),'hy.err.changed');assert.equal(run('blBusy'),false);
  run("blHy=null");answer={name:'p'};
  await context.explainBaseline();
  assert.equal(run('blHy.record'),null);assert.equal(run('blHy.error'),'hy.err.changed');
  assert.deepEqual(notices,[]);
  console.log('candidate explanations bound to their comparison verified.');
 })().catch(error=>{console.error(error);process.exitCode=1;});
}
