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
 return {...total,affected:total.affected.size,source:result?.source==='local-upload'?'uploaded':result?.source==='connected-source'?'connected':result?.source==='synthetic-sample'?'sample':result?'example':'none'};
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
// Escape every interpolated value, including translations and source-controlled columns.
function readableReport(run,translate=value=>value,locale='en',extras={}){
 const esc=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const names={'drift:SCHEMA_CHANGED':'Schema changed','drift:SCHEMA_RESTORED':'Schema restored','drift:QUALITY_DEGRADED':'More records affected','drift:NEW_CHECK_FAILURE':'New failing check','drift:ROW_COUNT_SHIFT':'Row count shifted','drift:AMOUNT_LEVEL_SHIFT':'Amount level shifted','drift:RECOVERED':'Recovered','drift:STABLE':'Stable: no rule fired against the previous inspection.','drift:DEGRADED':'Changed for the worse since the previous inspection.','drift:INSUFFICIENT_HISTORY':'No earlier inspection of this source to compare with.',upload:'Uploaded order file',clean:'Healthy source',null_total:'Missing order totals',duplicate_order:'Duplicate orders',transformation:'Transformation reconciliation',NO_FAILURE_OBSERVED:'No observed failure',SOURCE_QUALITY_FAILURE:'Source quality failure',TRANSFORMATION_RECONCILIATION_FAILURE:'Transformation mismatch',amount_cents:'Amount (minor units)',completeness:'Completeness',uniqueness:'Uniqueness',validity:'Validity',record_health:'Record health'};
 const label=value=>esc(translate(names[value]||value));
 const s=summarizeResult(run.result);
 const row=(name,value)=>`<dt>${label(name)}</dt><dd>${esc(value)}</dd>`;

 const analysis=run.result?.cases?.[0]?.analysis;
 const executive=(()=>{
  if(!analysis)return '';
  const money=value=>esc(formatAmount(value,locale)),count=value=>esc(Number(value).toLocaleString(locale==='tr'?'tr-TR':'en-GB'));
  const failed=analysis.status==='FAIL',impact=analysis.impact;
  const first=workspaceGroups(analysis).slice(0,5).map(g=>`<li>${label(g.check)}${g.kind==='records'||g.column?` · ${esc(g.column)}`:''} — ${g.kind==='records'?`${count(g.count)} ${label('records')}`:label('Schema level')}</li>`).join('');
  const bars=dimensionRows(analysis).map(d=>`<tr><th scope="row">${label(d.key)}</th><td class="bar"><span style="width:${d.ratio===null?0:Math.floor(d.ratio*1000)/10}%"></span></td><td>${esc(percent(d.ratio,locale))}</td><td>${count(d.passed)} / ${count(d.total)}</td></tr>`).join('');
  const drift=extras.drift,changes=(drift?.changes||[]).map(c=>`<li>${label('drift:'+c.code)}</li>`).join('');
  const reviews=extras.reviews||{},actions=analysis.actions||[],decided=d=>actions.filter(a=>reviews[a.id]===d).length;
  return `<section class="summary"><h2>${label('Executive summary')}</h2><p class="verdict ${failed?'bad':'ok'}">${label(failed?'Needs attention':'No findings in the checked rows')}</p><dl class="facts">${row('Records checked',analysis.row_count)}${row('Records with a finding',impact.affected_records)}${row('Customers affected',impact.affected_customers)}<dt>${label('Valid amount in affected records')}</dt><dd>${money(impact.valid_amount_in_affected_records)}</dd><dt>${label('Amount that could be counted twice')}</dt><dd>${money(impact.double_count_exposure)}</dd></dl>${first?`<h3>${label('Where to look first')}</h3><ol>${first}</ol>`:''}<h3>${label('Quality dimensions')}</h3><table class="dims"><tbody>${bars}</tbody></table>${drift?`<h3>${label('Change since the previous inspection')}</h3><p>${label('drift:'+drift.status)}</p>${changes?`<ul>${changes}</ul>`:''}`:''}${actions.length?`<h3>${label('Review decisions')}</h3><p>${label('Proposed actions')}: ${count(actions.length)} · ${label('Accepted')}: ${count(decided('accepted'))} · ${label('Deferred')}: ${count(decided('deferred'))} · ${label('Dismissed')}: ${count(decided('dismissed'))} · ${label('Pending')}: ${count(actions.length-decided('accepted')-decided('deferred')-decided('dismissed'))}</p>`:''}<p class="limits">${label('Produced by deterministic checks. No language model was used and no root cause was inferred.')}</p></section>`;
 })();
 const sections=(run.result?.cases||[]).map(item=>{
  const report=item.source_report;
  const findings=report?groupFindings(report).map(f=>`<tr><td>${label(f.check)}</td><td>${esc(f.column)}</td><td>${esc(f.record_numbers.join(', ')||translate('Schema level'))}</td></tr>`).join(''):'';
  const compare=(item.steps||[]).filter(step=>step.tool==='run_batch').flatMap(step=>step.report.reconciliation||[]).map(c=>`<li>${label(c.check)}: ${label('Expected')} ${esc(c.expected)} / ${label('Observed')} ${esc(c.actual)} — ${label(c.passed?'Passed':'Failed')}</li>`).join('');
  return `<section><h2>${label(item.case)}</h2><p>${label(item.assessment)}</p>${!report?`<p>${label('Details unavailable')}</p>`:`<p>${label('Source findings')}: ${esc(report.finding_count)}</p>${report.findings_truncated?`<p>${label('Finding details are truncated; record lists are incomplete.')}</p>`:''}<table><thead><tr><th>${label('Check')}</th><th>${label('Column')}</th><th>${label('Record numbers')}</th></tr></thead><tbody>${findings}</tbody></table><details><summary>${label('Technical evidence and content hashes')}</summary><code>${esc(report.source_sha256)}</code></details>`}${compare?`<ul>${compare}</ul>`:''}</section>`;
 }).join('');
 return `<!doctype html><html lang="${locale==='tr'?'tr':'en'}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>AegisFlow · ${label('Inspection report')}</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#152536;max-width:960px;margin:32px auto;padding:24px}h1{font-size:28px}h2{font-size:21px}section{border-top:1px solid #aab9c8;margin-top:28px;padding-top:16px}dt{font-weight:bold}dd{margin:0 0 12px;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse}td,th{text-align:left;border:1px solid #aab9c8;padding:10px;overflow-wrap:anywhere}code{overflow-wrap:anywhere}summary{cursor:pointer}h3{font-size:16px;margin:18px 0 6px}.summary{border:1px solid #aab9c8;border-radius:8px;padding:16px 20px;background:#f5f8fb}.verdict{font-weight:700;font-size:18px;margin:4px 0 12px}.verdict.bad{color:#a4212f}.verdict.ok{color:#146c43}.facts{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 24px}.facts dd{text-align:right}.dims th{width:28%;border:0;padding:6px 10px 6px 0}.dims td{border:0;padding:6px 10px 6px 0}.dims td.bar{width:34%;background:#dde5ee;border-radius:4px;padding:0;position:relative}.dims td.bar+td{padding-left:12px}.dims td.bar span{display:block;height:12px;background:#0f8f84;border-radius:4px}.limits{color:#4a5b6d;font-size:14px}@page{size:A4;margin:16mm}@media print{body{margin:0;padding:0}section{break-inside:avoid}.summary{background:#fff}}</style><h1>AegisFlow · ${label('Inspection report')}</h1><p>${label(s.source==='uploaded'?'Uploaded file':s.source==='connected'?'Connected source':s.source==='sample'?'SYNTHETIC SAMPLE':'EXAMPLE DATA')}</p>${executive}<dl>${row('Run identifier',run.run_id)}${row('Finished at',run.finished_at)}${row('Records checked',s.rows)}${row('Source findings',s.detailsAvailable?s.findings:translate('Details unavailable'))}${row('Reconciliation violations',s.detailsAvailable?s.reconciliation:translate('Details unavailable'))}</dl><p>${label('Review the indicated source records, correct the source and inspect a fresh export. No changes were applied by this inspection.')}</p>${sections}</html>`;
}
// ---- Workspace helpers: pure functions over the server analysis; nothing here invents data. ----
const DIMENSIONS=['completeness','uniqueness','validity','record_health'];
function dimensionRows(analysis){
 return DIMENSIONS.map(key=>{const d=analysis?.dimensions?.[key]||{passed:0,total:0,ratio:null};return {key,passed:d.passed,total:d.total,ratio:d.ratio};});
}
// Rule-based review order, not a model score: schema breaks everything, then revenue-affecting values, then the rest.
function priorityOf(check,column){
 if(['missing_column','unexpected_column','nonempty_dataset'].includes(check))return 1;
 if(check==='unique'||check==='amount_format'||(check==='not_null'&&column==='order_total'))return 2;
 return 3;
}
function workspaceGroups(analysis){
 const groups=[];
 for(const issue of analysis?.schema_issues||[])groups.push({id:`schema:${issue.check}:${issue.column}`,kind:'schema',check:issue.check,column:issue.column,count:1,priority:1});
 for(const cell of analysis?.heatmap||[])groups.push({id:`${cell.check}:${cell.column}`,kind:'records',check:cell.check,column:cell.column,count:cell.records,priority:priorityOf(cell.check,cell.column)});
 return groups.sort((a,b)=>a.priority-b.priority||b.count-a.count||a.id.localeCompare(b.id));
}
function recordsFor(analysis,group){
 if(!group||group.kind!=='records')return [];
 return (analysis?.affected_records||[]).filter(r=>r.issues.includes(group.id));
}
function reviewProgress(actions,reviews){
 const total=(actions||[]).length,decided=(actions||[]).filter(a=>reviews?.[a.id]).length;
 return {total,decided,pending:total-decided};
}
// Lanes group execution steps by what the person needs to know: done, needs you, skipped/blocked, not available.
function laneOf(step,progress){
 if(step.status==='completed')return 'done';
 if(step.status==='awaiting')return progress&&progress.total&&progress.pending===0?'done':'next';
 if(step.status==='unavailable'||step.status==='disabled')return 'unavailable';
 return 'skipped';
}
function stepState(step,progress){
 return step.id==='human_review'&&step.status==='awaiting'&&progress&&progress.total&&progress.pending===0?'completed':step.status;
}
function formatAmount(value,locale='en'){
 if(value===null||value===undefined||value==='')return '—';
 const [whole,fraction='00']=String(value).split('.');
 const grouped=whole.replace(/\B(?=(\d{3})+(?!\d))/g,locale==='tr'?'.':',');
 return grouped+(locale==='tr'?',':'.')+fraction.padEnd(2,'0');
}
function percent(ratio,locale='en'){
 if(ratio===null||ratio===undefined)return '—';
 const text=(Math.floor(ratio*1000)/10).toFixed(1);   // never round 99.96% up to 100%
 return (locale==='tr'?text.replace('.',','):text)+'%';
}
function runLabel(run){
 const input=run?.result?.input||run?.meta;
 if(input?.name)return input.name;
 return run?.scenario&&run.scenario!=='upload'?run.scenario:'—';
}
// Execution timeline rows from the real event timestamps; null when the run has no usable time span.
function timelineRows(events,startedAt,finishedAt){
 const t0=Date.parse(startedAt),t1=Date.parse(finishedAt);
 if(!Number.isFinite(t0)||!Number.isFinite(t1)||t1<=t0)return null;
 const rows=[],by=new Map();
 for(const e of events||[]){
  const at=Date.parse(e.at);
  if(!Number.isFinite(at))continue;
  const id=String(e.agent).split(' / ')[0];
  let row=by.get(id);
  if(!row){row={id,agent:e.agent,start:at,end:at,state:e.state};by.set(id,row);rows.push(row);}
  row.start=Math.min(row.start,at);row.end=Math.max(row.end,at);row.state=e.state;
 }
 return {total:t1-t0,rows:rows.map(r=>({id:r.id,agent:r.agent,state:r.state,offset:Math.max(0,r.start-t0),duration:r.end-r.start}))};
}
// Which stream to show: the one holding the newest run, unless a stream was chosen explicitly.
function pickStream(monitoring,chosen){
 const streams=monitoring?.streams||[];
 if(!streams.length)return null;
 const picked=streams.find(s=>s.key===chosen);
 if(picked)return picked;
 const stamp=s=>s.runs[s.runs.length-1].at||'';
 return streams.reduce((best,s)=>stamp(s)>stamp(best)?s:best,streams[0]);
}
// Chart series straight from retained ratios; a null ratio stays null and is drawn as a gap.
function driftSeries(stream){
 return ['record_health','completeness','uniqueness','validity'].map(key=>({key,values:stream.runs.map(r=>r.dimensions[key]??null)}));
}
// Per-check rows of one detector across splits; rates keep their counts and never become 100% when undefined.
function evidenceRows(report,detector){
 const splits=report?.results?.[detector];
 if(!splits)return [];
 const names=Object.keys(splits),checks=Object.keys(splits[names[0]].per_check);
 const cell=rate=>({value:rate.value,numerator:rate.numerator,denominator:rate.denominator,low:rate.interval_95?rate.interval_95[0]:null});
 return [...checks,'overall'].map(check=>({check,cells:Object.fromEntries(names.map(split=>{
  const row=check==='overall'?splits[split].overall:splits[split].per_check[check];
  return [split,{recall:cell(row.recall),precision:cell(row.precision),errors:row.false_positives+row.false_negatives}];}))}));
}
// Role cards: catalog status merged with what the current plan actually did; nothing is shown as running unless a step completed.
function roleView(map,plan,filter){
 const steps=new Map((plan||[]).map(step=>[step.role,step.status]));
 const roles=(map?.roles||[]).map(role=>({...role,current:steps.has(role.agent_id)?(steps.get(role.agent_id)==='completed'?'ran':'skipped'):null}));
 return {roles:filter&&filter!=='all'?roles.filter(role=>role.status===filter):roles,ran:roles.filter(role=>role.current==='ran').length};
}
if(typeof module!=='undefined')module.exports={roleView,evidenceRows,timelineRows,pickStream,driftSeries,summarizeResult,groupFindings,readableReport,dimensionRows,priorityOf,workspaceGroups,recordsFor,reviewProgress,laneOf,stepState,formatAmount,percent,runLabel};
