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
