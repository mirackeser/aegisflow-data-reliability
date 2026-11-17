// SPDX-License-Identifier: Apache-2.0
const assert=require('node:assert/strict');
const {summarizeResult,groupFindings}=require('./presentation.js');
assert.equal(summarizeResult(null).source,'none');
assert.equal(summarizeResult(null).rows,0);
const input={source:'local-upload',cases:[{rows:3,source_report:{finding_count:3,findings_truncated:false,findings:[
 {check:'not_null',record_numbers:[1]},{check:'not_null',record_numbers:[1]},{check:'unique',record_numbers:[2,3]}]},steps:[]}]};
const value=summarizeResult(input);
assert.equal(value.rows,3);assert.equal(value.findings,3);assert.equal(value.missing,1);assert.equal(value.duplicates,2);assert.equal(value.affected,3);assert.equal(value.source,'uploaded');
input.cases[0].source_report.findings_truncated=true;
assert.equal(summarizeResult(input).truncated,true);
assert.equal(summarizeResult({cases:[{rows:24}]}).detailsAvailable,false);
input.cases[0].steps=[{tool:'run_batch',report:{reconciliation:[{passed:false},{passed:true}]}}];
assert.equal(summarizeResult(input).reconciliation,1);
assert.equal(input.cases[0].source_report.finding_count,3);
const grouped=groupFindings(input.cases[0].source_report);
assert.equal(grouped.length,2);assert.equal(grouped[0].occurrences,2);assert.deepEqual(grouped[0].record_numbers,[1]);assert.deepEqual(grouped[1].record_numbers,[2,3]);
assert.equal(value.emptyViolations,2);assert.equal(value.duplicateViolations,1);
console.log('18 presentation assertions passed: grouping, distinct rows, truncation, provenance and reconciliation.');
const {readableReport}=require('./presentation.js');
const malicious='</td><script>alert(1)</script>&"';
const run={run_id:malicious,finished_at:'2026-11-15T12:00:00Z',result:{source:'local-upload',cases:[{case:'upload',assessment:'SOURCE_QUALITY_FAILURE',rows:2,source_report:{finding_count:1,findings_truncated:true,source_sha256:malicious,findings:[{check:'not_null',column:malicious,record_numbers:[2]}]},steps:[{tool:'run_batch',report:{reconciliation:[{check:'order_count',expected:2,actual:1,passed:false}]}}]}]}};
const html=readableReport(run);
assert.ok(!html.includes('<script>'));
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(html.includes('default-src \'none\''));
assert.ok(html.includes('record lists are incomplete'));
assert.ok(html.includes('Expected 2 / Observed 1'));
assert.ok(html.includes('Uploaded file'));
assert.ok(html.includes('<td>2</td>'));
assert.ok(readableReport(run,x=>x==='Inspection report'?'İnceleme raporu':x,'tr').includes('İnceleme raporu'));
assert.ok(readableReport(run,x=>x,'tr').includes('lang="tr"'));
assert.ok(readableReport({result:{cases:[{rows:2}]}}).includes('Details unavailable'));
assert.ok(!readableReport(run,()=>malicious).includes('<script>'));
assert.ok(readableReport({result:{cases:[]}}).includes('EXAMPLE DATA'));
console.log('12 readable report assertions passed: injection safety, provenance, missing details, localization and reconciliation.');
// executive summary: real analysis figures only, escaped, with honest limits and optional drift/review context
const analysis={status:'FAIL',row_count:24,impact:{affected_records:2,affected_customers:2,valid_amount_in_affected_records:'1234.50',double_count_exposure:'99.00'},
 dimensions:{completeness:{passed:22,total:24,ratio:0.9166},uniqueness:{passed:24,total:24,ratio:1},validity:{passed:24,total:24,ratio:1},record_health:{passed:22,total:24,ratio:0.9166}},
 schema_issues:[],heatmap:[{check:'not_null',column:malicious,records:2}],actions:[{id:'ACT-01'},{id:'ACT-02'},{id:'ACT-03'}]};
const withAnalysis={...run,result:{...run.result,cases:[{...run.result.cases[0],analysis}]}};
const full=readableReport(withAnalysis,x=>x,'en',{reviews:{'ACT-01':'accepted','ACT-02':'dismissed'},drift:{status:'DEGRADED',changes:[{code:'QUALITY_DEGRADED'}]}});
assert.ok(full.includes('Executive summary')&&full.includes('Needs attention'));
assert.ok(full.includes('1,234.50')&&full.includes('99.00'));
assert.ok(full.includes('91.6%'),'ratios are floored, never rounded up');
assert.ok(full.includes('Accepted: 1 · Deferred: 0 · Dismissed: 1 · Pending: 1'));
assert.ok(full.includes('More records affected')&&full.includes('Changed for the worse'));
assert.ok(full.includes('No language model was used'));
assert.ok(!full.includes('<script>')&&full.includes('@page'));
const turkish=readableReport(withAnalysis,x=>`«${x}»`,'tr');
assert.ok(turkish.includes('1.234,50')&&turkish.includes('91,6%'));
assert.ok(!readableReport(run).includes('Executive summary'),'no summary without a retained analysis');
const clean=readableReport({...withAnalysis,result:{...withAnalysis.result,cases:[{...withAnalysis.result.cases[0],analysis:{...analysis,status:'PASS',heatmap:[],actions:[]}}]}});
assert.ok(clean.includes('No findings in the checked rows')&&!clean.includes('Where to look first')&&!clean.includes('Review decisions')&&!clean.includes('Change since'));
console.log('executive summary assertions passed.');
