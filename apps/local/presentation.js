'use strict';
// Derive visible observations only; never infer accuracy from a finding count.
function summarizeResult(result){
 const cases=result?.cases||[];
 const total={rows:0,findings:0,affected:new Set(),missing:0,duplicates:0,format:0,emptyViolations:0,duplicateViolations:0,formatViolations:0,schema:0,reconciliation:0,truncated:false,detailsAvailable:true};
 for(const [index,item] of cases.entries()){
  const report=item.source_report;
  total.rows+=item.rows||0;
  if(!report){total.detailsAvailable=false;continue;}
  total.findings+=report.finding_count;
  total.truncated ||= report.findings_truncated;
  const missing=new Set(),duplicates=new Set(),format=new Set();
  for(const finding of report.findings){
   if(finding.check==='not_null'){total.emptyViolations++;finding.record_numbers.forEach(n=>missing.add(n));}
   if(finding.check==='unique'){total.duplicateViolations++;finding.record_numbers.forEach(n=>duplicates.add(n));}
   if(finding.check==='amount_format'){total.formatViolations++;finding.record_numbers.forEach(n=>format.add(n));}
   if(['missing_column','unexpected_column'].includes(finding.check))total.schema++;
   finding.record_numbers.forEach(n=>total.affected.add(index+':'+n));
  }
  total.missing+=missing.size;total.duplicates+=duplicates.size;total.format+=format.size;
  for(const step of item.steps||[])if(step.tool==='run_batch')total.reconciliation+=(step.report.reconciliation||[]).filter(c=>!c.passed).length;
 }
 return {...total,affected:total.affected.size,source:result?.source==='local-upload'?'uploaded':result?'example':'none'};
}
function groupFindings(report){
 const groups=new Map();
 for(const finding of report?.findings||[]){
  const key=JSON.stringify([finding.check,finding.column||'']);
  if(!groups.has(key))groups.set(key,{check:finding.check,column:finding.column||'',records:new Set(),occurrences:0});
  const group=groups.get(key);group.occurrences++;
  finding.record_numbers.forEach(n=>group.records.add(n));
 }
 return [...groups.values()].map(g=>({check:g.check,column:g.column,record_numbers:[...g.records].sort((a,b)=>a-b),occurrences:g.occurrences}));
}
if(typeof module!=='undefined')module.exports={summarizeResult,groupFindings};
