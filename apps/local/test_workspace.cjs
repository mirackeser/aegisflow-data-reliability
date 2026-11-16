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
