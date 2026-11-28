'use strict';
// Core: state, routing, shell, overview, execution flow, reports and references.
let passages=null,retrieval=null,platform=null,capabilities=null,capabilitiesLoading=false,roleFilter='all',evaluation=null,driftKey=null,token='',polling=null,state=null,viewId=null,connected=false,route='/overview';
const $=id=>document.getElementById(id);
function h(tag,attrs={},...kids){
 const n=document.createElement(tag);
 for(const [k,v] of Object.entries(attrs||{})){
  if(v===null||v===undefined||v===false)continue;
  if(k==='class')n.className=v;else if(k==='text')n.textContent=v;else if(k.startsWith('on'))n[k]=v;else n.setAttribute(k,v===true?'':v);
 }
 for(const kid of kids.flat(Infinity)){if(kid===null||kid===undefined||kid===false)continue;n.append(kid instanceof Node?kid:document.createTextNode(String(kid)));}
 return n;
}
const locale=()=>language==='tr'?'tr-TR':'en-GB';
const A=value=>formatAmount(value,language),P=ratio=>percent(ratio,language),N=n=>Number(n).toLocaleString(locale());
const when=iso=>iso?new Date(iso).toLocaleString(locale(),{dateStyle:'medium',timeStyle:'short'}):'—';
const PAGES={
 '/overview':'overview','/investigations':'investigations','/sources':'sources','/activity':'activity','/history':'history','/knowledge':'knowledge','/quality':'quality','/agents':'agents','/flow':'flow','/incident':'incident','/report':'report'};
const WAITING_PLAN=[['contract_check','A09',[]],['profiling','A10',['contract_check']],['reconciliation','A19',['contract_check']],['impact','A13',['contract_check']],
 ['evidence','A26',['contract_check','profiling']],['verification','A27',['evidence']],['human_review','A33',['verification']],['root_cause','A23',['verification']],['remediation','A29',['human_review']]]
 .map(([id,role,depends_on])=>({id,role,depends_on,status:'waiting',reason:null,capability:id}));
const EXAMPLES=['clean','null_total','duplicate_order','transformation','suite'];
const SAMPLES=['duplicate_order','null_total','schema_drift','clean'];

function currentRun(){
 if(viewId){return state?.history?.find(r=>r.run_id===viewId)||(state?.run_id===viewId?state:null);}
 return state?.run_id?state:null;
}
const caseOf=run=>run?.result?.cases?.[0]||null;
const analysisOf=run=>caseOf(run)?.analysis||null;
const reviewsOf=run=>(run&&state?.reviews?.[run.run_id])||{};
const progressOf=run=>reviewProgress(analysisOf(run)?.actions,reviewsOf(run));
function originKey(run){
 const s=summarizeResult(run?.result).source;
 return s==='uploaded'?'origin.file':s==='connected'?'origin.connected':s==='sample'?'origin.sample':s==='example'?'origin.example':'origin.none';
}
function setNotice(message,error=false){const n=$('notice');n.textContent=message||'';n.classList.toggle('error',error);n.hidden=!message;}
async function request(path,method='GET',body,headers={}){
 const options={method,headers:{Authorization:'Bearer '+token,...headers},cache:'no-store'};
 if(body!==undefined)options.body=body;
 const response=await fetch(path,options);
 if(!response.ok){
  let detail='',payload=null;try{payload=await response.json();detail=payload?.message||'';}catch{}
  const error=new Error(response.status===409?t('err.busy'):response.status===413?t('err.size'):response.status===422?t('err.rejected',{reason:detail}):t('err.unavailable'));
  error.status=response.status;error.body=payload;throw error;
 }
 return response.json();
}
function navigate(path,push=true){
 if(path==='/evidence'){path='/quality';if(!push)history.replaceState({},'','/quality');}  // the earlier "Check accuracy" address
 route=PAGES[path]?path:'/overview';
 if(push)setNotice('');
 if(push&&location.pathname!==route)history.pushState({},'',route);
 render();$('main').focus({preventScroll:true});window.scrollTo({top:0});
}
function link(path,text,cls='text-link'){return h('a',{href:path,class:'route '+cls,text});}
function empty(titleKey,textKey,action){
 return h('div',{class:'empty-state'},h('strong',{text:t(titleKey)}),h('span',{text:t(textKey)}),action||null);
}
function chip(text,tone='muted'){return h('span',{class:'chip '+tone,text});}

// ---------- what happened / what next ----------
function happened(run){
 if(!run)return t('happened.none');
 if(run.status==='RUNNING')return t('happened.running');
 if(run.status==='FAILED'||run.status==='INTERRUPTED')return t('happened.failed');
 const a=analysisOf(run);
 if(!a)return t('happened.example');
 return a.status==='FAIL'?t('happened.fail',{rows:N(a.row_count),records:N(a.impact.affected_records)}):t('happened.pass',{rows:N(a.row_count)});
}
function nextStep(run){
 if(!connected)return {text:t('next.connect'),href:null};
 if(!run)return {text:t('next.start'),href:'/sources'};
 if(run.status==='RUNNING')return {text:t('next.wait'),href:null};
 if(run.status!=='COMPLETED')return {text:t('next.retry'),href:'/sources'};
 const a=analysisOf(run),p=progressOf(run);
 if(a&&a.status==='FAIL'&&p.pending>0)return {text:t('next.review',{n:p.pending}),href:'/investigations'};
 if(a&&a.status==='FAIL')return {text:t('next.reinspect'),href:'/sources'};
 return {text:t('next.pass'),href:'/history'};
}
// The four brief answers. "What happened" and "What next" are recomputed from the current state on every paint of
// the live pages (Command Center, Agent flow), so they never lag behind what the page shows.
function briefTexts(screen,run){
 if(screen==='overview'){const b=commandBrief();return {happened:b.happened,next:{text:b.next,href:null}};}
 if(screen==='flow'){const b=flowBriefNow();return {happened:b.happened,next:{text:b.next,href:null}};}
 if(screen==='incident'){const b=incidentBrief();return {happened:b.happened,next:{text:b.next,href:null}};}
 if(screen==='report'){const b=reportBrief();return {happened:b.happened,next:{text:b.next,href:null}};}
 const next=screen==='quality'?{text:t('next.quality'),href:null}:screen==='agents'?{text:t('next.agents'),href:null}:nextStep(run);
 return {happened:screen==='quality'?quaHappened():screen==='agents'?agentsHappened(run):happened(run),next};
}
let briefSig='';
function renderBrief(screen,run){
 const b=briefTexts(screen,run),sig=JSON.stringify([language,screen,b]);
 if(sig===briefSig&&$('page-brief').childElementCount)return;
 briefSig=sig;
 const cell=(label,body)=>h('div',{},h('b',{text:t(label)}),body);
 $('page-brief').replaceChildren(
  cell('brief.purpose',h('span',{text:t(`brief.${screen}.purpose`)})),
  cell('brief.can',h('span',{text:t(`brief.${screen}.can`)})),
  cell('brief.happened',h('span',{id:'brief-happened',text:b.happened})),
  cell('brief.next',b.next.href?link(b.next.href,b.next.text,'text-link'):h('span',{id:'brief-next',text:b.next.text})));
}
const refreshBrief=()=>renderBrief(PAGES[route]||'overview',currentRun());

// ---------- shell ----------
function renderShell(){
 document.documentElement.lang=language;
 document.querySelectorAll('[data-i18n]').forEach(n=>{n.textContent=t(n.dataset.i18n);});
 document.querySelectorAll('.lang').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.language===language)));
 document.querySelectorAll('#main-nav a').forEach(a=>{const active=a.getAttribute('href')===route||((route==='/incident'||route==='/report')&&a.getAttribute('href')==='/overview');if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 $('connection').textContent=t(connected?'conn.on':'conn.off');$('connection').classList.toggle('connected',connected);
 $('session-toggle').textContent=t(connected?'session.on':'session.open');
 const run=currentRun();
 const source=[['side.csv','side.csv.s','ok','/sources'],['side.sample','side.sample.s','ok','/sources'],['side.pg','side.pg.s','info','/sources'],['side.company','side.company.s','muted',null]];
 $('side-sources').replaceChildren(...source.map(([name,status,tone,href])=>h('li',{},href?link(href,'', 'side-item'):h('span',{class:'side-item disabled','aria-disabled':'true'}))).map((li,i)=>{
  const [name,status,tone]=source[i],target=li.firstChild;
  target.append(h('span',{class:'side-name',text:t(name)}),chip(t(status),tone));return li;}));
 const plan=run?.result?.plan||WAITING_PLAN,progress=progressOf(run);
 $('side-pipeline').replaceChildren(...plan.map(step=>{const state=stepState(step,progress);return h('li',{class:'pipe-item'},h('span',{class:'dot '+state}),h('span',{text:t('step.'+step.id)}),h('small',{text:t('status.'+state)}));}));
 const runs=[...(state?.run_id&&state.status!=='IDLE'?[state]:[]),...(state?.history||[])].slice(0,4);
 $('side-history').replaceChildren(...(runs.length?runs.map(r=>{
  const a=r.result?.cases?.[0]?.analysis,label=runLabel(r);
  return h('button',{type:'button',class:'side-run'+((run&&run.run_id===r.run_id)?' selected':''),onclick:()=>{viewId=r.run_id===state?.run_id?null:r.run_id;navigate('/investigations');}},
   h('strong',{text:label}),h('small',{text:`${when(r.finished_at||r.started_at)} · ${a?t('side.findings',{n:N(a.impact.affected_records)}):t('status.'+(r.status||'IDLE'))}`}));
 }):[h('p',{class:'side-empty',text:t('side.none')})]));
}

// ---------- shared panels ----------
function trendPanel(){
 const runs=[...(state?.history||[]).slice().reverse(),...(state?.run_id&&state.status!=='IDLE'?[state]:[])].filter(r=>r.result?.cases?.[0]?.analysis).slice(-8);
 const body=h('div',{class:'chart-area'});
 if(runs.length<2)body.append(empty('empty.trend.t','empty.trend.x'));
 else body.append(trendSvg(runs.map(r=>({value:r.result.cases[0].analysis.impact.affected_records,label:runLabel(r)})),{label:t('panel.trend')}));
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.trend')}),chip(t('badge.saved'),'muted')),body,h('p',{class:'panel-note',text:t('panel.trend.note')}));
}
function changeTone(code){return code==='RECOVERED'||code==='SCHEMA_RESTORED'?'ok':'bad';}
const checkLabel=key=>{const [check,column]=String(key).split(':');return column?`${t('check.'+check)} · ${column}`:t('check.'+check);};
function describeChange(change){
 const d=change.detail,list=values=>(values||[]).map(checkLabel).join(', ')||'—';
 const params={QUALITY_DEGRADED:()=>({before:P(d.before),after:P(d.after)}),NEW_CHECK_FAILURE:()=>({checks:list(d.checks)}),SCHEMA_CHANGED:()=>({items:list(d.after)}),
  SCHEMA_RESTORED:()=>({items:list(d.before)}),ROW_COUNT_SHIFT:()=>({before:N(d.before),after:N(d.after)}),AMOUNT_LEVEL_SHIFT:()=>({before:A(d.before),after:A(d.after)}),RECOVERED:()=>({before:N(d.before)})}[change.code]();
 return t('drift.'+change.code,params);
}
function reportExtras(run){
 const stream=(state?.monitoring?.streams||[]).find(x=>x.runs.some(p=>p.run_id===run.run_id));
 if(!stream)return {reviews:state?.reviews?.[run.run_id]};
 const index=stream.runs.findIndex(p=>p.run_id===run.run_id);
 const status=index===0?'INSUFFICIENT_HISTORY':(()=>{const codes=stream.runs[index].changes.map(c=>c.code);return codes.some(c=>c==='RECOVERED'||c==='SCHEMA_RESTORED')?'RECOVERED':codes.length?'DEGRADED':'STABLE';})();
 return {reviews:state?.reviews?.[run.run_id],drift:{status,changes:stream.runs[index].changes}};
}
function driftPanel(){
 const stream=pickStream(state?.monitoring,driftKey),streams=state?.monitoring?.streams||[];
 const tone={STABLE:'ok',RECOVERED:'ok',DEGRADED:'bad',INSUFFICIENT_HISTORY:'muted'};
 const head=h('div',{class:'panel-heading'},h('h2',{text:t('panel.drift')}),stream?chip(t('drift.status.'+stream.status),tone[stream.status]):chip(t('badge.waiting'),'muted'));
 const body=h('div',{class:'chart-area flow-scroll'});
 const extras=[];
 if(!stream)body.append(empty('empty.drift.t','empty.drift.x',link('/sources',t('cta.start'),'primary route')));
 else if(stream.runs.length<2)body.append(empty('empty.drift1.t','empty.drift1.x'));
 else{
  const runs=stream.runs.map(r=>({...r,changes:r.changes.map(c=>({...c,tone:changeTone(c.code)}))}));
  const series=driftSeries(stream).map(x=>({...x,label:t('dim.'+x.key)}));
  body.append(driftSvg(series,runs,{label:t('panel.drift'),percent:v=>P(v),changeLabel:r=>r.changes.map(describeChange).join(' ')}));
  const latest=runs[runs.length-1];
  extras.push(h('h3',{text:t('drift.latest',{n:runs.length})}),latest.changes.length
   ?h('ul',{class:'drift-changes'},latest.changes.map(c=>h('li',{},chip(t('drift.code.'+c.code),c.tone),h('span',{text:describeChange(c)}))))
   :h('p',{class:'panel-note',text:t('drift.nochange')}));
 }
 const pick=streams.length>1?h('label',{class:'drift-pick'},h('span',{text:t('drift.source')}),h('select',{id:'drift-stream',onchange:e=>{driftKey=e.target.value;render();}},streams.map(x=>h('option',{value:x.key,selected:stream?.key===x.key,text:`${x.label} (${x.runs.length})`})))):null;
 return h('section',{class:'panel drift-panel wide'},head,pick,body,...extras,h('p',{class:'panel-note',text:t('drift.note')}));
}
const msText=ms=>ms>=1000?`${(ms/1000).toFixed(2)} s`:`${ms<10?ms.toFixed(1):Math.round(ms)} ms`;
function timelinePanel(run){
 const layout=timelineRows(run.events,run.started_at,run.finished_at);
 const body=h('div',{class:'chart-area flow-scroll'});
 if(!layout||!layout.rows.length)body.append(empty('empty.gantt.t','empty.gantt.x'));
 else body.append(timelineSvg(layout,{label:t('panel.gantt'),names:eventLabel,duration:msText,pointLabel:t('gantt.point')}));
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.gantt')}),chip(layout?t('gantt.total',{t:msText(layout.total)}):t('badge.waiting'),'muted')),body,h('p',{class:'panel-note',text:t('gantt.note')}));
}
function describeStep(run,progress){
 const a=analysisOf(run),c=caseOf(run);
 return step=>{
  const s=stepState(step,progress);
  const meta={contract_check:()=>a?t('meta.findings',{n:N(c.source_report.finding_count)}):'',
   profiling:()=>a?t('meta.affected',{n:N(a.impact.affected_records)}):'',
   impact:()=>a?t('meta.downstream',{n:a.downstream.potential.length}):'',
   evidence:()=>s==='completed'?t('meta.hashed'):'',verification:()=>s==='completed'?t('meta.accepted'):'',
   human_review:()=>progress.total?t('meta.reviewed',{d:progress.decided,n:progress.total}):''}[step.id];
  const text=step.reason?t('short.'+step.reason):meta?meta():'';
  return {title:t('step.'+step.id),meta:text,state:s,statusText:t('status.'+s)};
 };
}
function flowPanel(run,wide=false){
 const plan=run?.result?.plan||WAITING_PLAN,progress=progressOf(run);
 const input=run?.result?{role:'',title:t(originKey(run)),meta:run.result.cases?.[0]?.rows!==undefined?t('meta.records',{n:N(run.result.cases[0].rows)}):'',state:'completed',statusText:t('status.completed')}:{role:'',title:t('flow.source'),meta:t('flow.waiting'),state:'waiting',statusText:t('status.waiting')};
 const svg=flowGraph(plan,describeStep(run,progress),{source:input,label:t('panel.flow'),lanes:FLOW_LANES.map(k=>t(k))});
 const list=h('ol',{class:'flow-list'},...plan.map(step=>{const s=stepState(step,progress);return h('li',{class:'flow-item '+s},h('span',{class:'dot '+s}),h('div',{},h('strong',{text:`${step.role} · ${t('step.'+step.id)}`}),h('small',{text:`${t('status.'+s)}${step.reason?' — '+t('reason.'+step.reason):''}`})));}));
 return h('section',{class:'panel flow-panel'+(wide?' wide':'')},h('div',{class:'panel-heading'},h('h2',{text:t('panel.flow')}),chip(run?.result?t('badge.real'):t('badge.waiting'),run?.result?'ok':'muted')),
  h('div',{class:'flow-scroll'},svg),list,h('p',{class:'panel-note',text:t('panel.flow.note')}),h('div',{class:'panel-bottom'},link('/activity',t('flow.more')),h('span',{text:t('flow.readonly')})));
}
// ---------- execution flow ----------
function renderActivity(){
 const run=currentRun(),root=$('screen-activity'),progress=progressOf(run);
 if(!run?.result){root.replaceChildren(flowPanel(null,true),h('section',{class:'panel'},empty('empty.activity.t','empty.activity.x',link('/sources',t('cta.start'),'primary route'))));return;}
 const plan=run.result.plan||[];
 const lanes=[['done','lane.done'],['next','lane.next'],['skipped','lane.skipped'],['unavailable','lane.unavailable']];
 const laneNodes=lanes.map(([lane,title])=>{
  const steps=plan.filter(s=>laneOf(s,progress)===lane);
  return h('section',{class:'panel lane '+lane},h('div',{class:'panel-heading'},h('h2',{text:t(title)}),chip(String(steps.length),'muted')),
   steps.length?h('ul',{class:'lane-list'},steps.map(s=>{const st=stepState(s,progress);return h('li',{},
    h('div',{class:'lane-head'},h('strong',{text:t('step.'+s.id)}),chip(`${s.role} · ${s.role_name}`,'muted')),
    h('p',{text:t('stepdesc.'+s.id)}),
    s.reason?h('p',{class:'reason'},h('b',{text:t('lane.why')+' '}),t('reason.'+s.reason)):null,
    s.depends_on.length?h('small',{text:t('lane.after',{steps:s.depends_on.map(d=>t('step.'+d)).join(', ')})}):null,
    h('small',{class:'mode',text:(st==='completed'||st==='rejected')?t('lane.deterministic'):t('lane.planned')}));})):h('p',{class:'panel-note',text:t('lane.none')}));
 });
 const events=(run.events||[]).map(e=>h('li',{class:'event '+e.state.toLowerCase()},h('time',{text:e.at?new Date(e.at).toLocaleTimeString(locale()):''}),h('span',{},h('strong',{text:eventLabel(e.agent)}),h('small',{text:eventText(e.description)})),chip(t('status.'+e.state),e.state==='COMPLETED'?'ok':'info')));
 root.replaceChildren(flowPanel(run,true),timelinePanel(run),h('div',{class:'lane-grid'},laneNodes),
  h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.events')}),chip(run.status,'muted')),events.length?h('ol',{class:'timeline'},events):empty('empty.events.t','empty.events.x'),
   h('p',{class:'panel-note',text:t('panel.events.note')})));
}
const FLOW_LANES=['flow.lane.source','flow.lane.contract','flow.lane.analysis','flow.lane.evidence','flow.lane.verify','flow.lane.decide','flow.lane.act'];
const eventLabel=value=>{const key='event.'+value.split(' / ')[0];return (STRINGS[key]?t(key):value);};
const eventText=value=>{const key='eventtext.'+value;return STRINGS[key]?t(key):value;};

// ---------- reports ----------
function runRows(){return [...(state?.run_id&&state.status!=='IDLE'?[state]:[]),...(state?.history||[])];}
function download(name,type,content){
 const url=URL.createObjectURL(new Blob([content],{type}));
 const a=h('a',{href:url,download:name});document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url);
}
function renderHistory(){
 const root=$('screen-history'),runs=runRows();
 if(!runs.length){root.replaceChildren(h('section',{class:'panel'},empty('empty.history.t','empty.history.x',link('/sources',t('cta.start'),'primary route'))));return;}
 const rows=runs.map((r,i)=>{
  const a=r.result?.cases?.[0]?.analysis,p=reviewProgress(a?.actions,state?.reviews?.[r.run_id]);
  return h('tr',{class:(currentRun()?.run_id===r.run_id)?'selected':''},
   h('th',{scope:'row'},h('strong',{text:runLabel(r)}),h('small',{text:i===0&&r.run_id===state?.run_id?t('hist.current'):t('hist.saved')})),
   h('td',{text:t(originKey(r))}),h('td',{text:when(r.finished_at||r.started_at)}),
   h('td',{text:a?N(a.row_count):'—'}),h('td',{text:a?N(a.impact.affected_records):'—'}),h('td',{text:a?P(a.dimensions.record_health.ratio):'—'}),
   h('td',{},chip(r.status==='COMPLETED'&&a?(a.status==='FAIL'?t('verdict.fail'):t('verdict.pass')):t('status.'+r.status),a&&a.status==='FAIL'?'bad':a?'ok':'muted')),
   h('td',{text:p.total?`${p.decided}/${p.total}`:'—'}),
   h('td',{class:'row-actions'},
    h('button',{type:'button',class:'secondary',onclick:()=>{viewId=r.run_id===state.run_id?null:r.run_id;navigate('/investigations');}},t('hist.open')),
    h('button',{type:'button',class:'secondary',disabled:!r.result,onclick:()=>download(`aegisflow-report-${r.run_id.slice(0,8)}.html`,'text/html',readableReport(r,translate,language,reportExtras(r)))},t('hist.html')),
    h('button',{type:'button',class:'secondary',disabled:!r.result,onclick:()=>download(`aegisflow-evidence-${r.run_id.slice(0,8)}.json`,'application/json',JSON.stringify({run:r,reviews:state.reviews?.[r.run_id]||{}},null,2))},t('hist.json'))));
 });
 root.replaceChildren(h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.runs')}),chip(t('hist.kept'),'muted')),
  h('div',{class:'table-wrap'},h('table',{class:'data-table'},h('thead',{},h('tr',{},...['hist.col.run','hist.col.source','hist.col.when','hist.col.rows','hist.col.affected','hist.col.health','hist.col.status','hist.col.review','hist.col.actions'].map(k=>h('th',{scope:'col',text:t(k)})))),h('tbody',{},rows))),
  h('p',{class:'panel-note',text:t('hist.note')})),driftPanel(),trendPanel());
}

// ---------- evidence references ----------
function referencePanel(result){
 const card=(reference,context)=>h('article',{class:'reference'},h('div',{class:'ref-head'},h('strong',{text:tt('ref.'+reference.source,reference.source)}),chip(`${reference.source} · ${reference.revision}`,'muted')),
  context?h('p',{class:'ref-context',text:context}):null,h('blockquote',{text:reference.text}),h('small',{text:t('ref.hash')}),h('code',{text:reference.citation_sha256}));
 const byFinding=Object.entries(result.finding_references||{}).map(([check,refs])=>card(refs[0],t('ref.for',{check:t('check.'+check)})));
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.refs')}),chip(t('badge.verified'),'ok')),
  h('div',{class:'ref-grid'},byFinding,(result.references||[]).map(r=>card(r,t('ref.general')))),
  h('p',{class:'panel-note',text:t('panel.refs.note')}));
}
function renderKnowledge(){
 const run=currentRun(),root=$('screen-knowledge'),result=run?.result;
 if(connected&&!kbDocs)loadKnowledgeBase();
 const refs=result?referencePanel(result):h('section',{class:'panel'},empty('empty.refs.t','empty.refs.x',link('/sources',t('cta.start'),'primary route')));
 root.replaceChildren(knowledgeBasePanel(),refs);
}

// ---------- check accuracy ----------
const SPLIT_ORDER=['development','validation','heldout'];
function rateCell(rate){
 if(rate.value===null)return h('td',{class:'rate na',text:t('evidence.na')});
 return h('td',{class:'rate'},h('strong',{text:P(rate.value)}),h('small',{text:`${N(rate.numerator)}/${N(rate.denominator)}`}),h('small',{text:t('evidence.low',{p:P(rate.low)})}));
}
function detectorPanel(name){
 const rows=evidenceRows(evaluation,name),splits=SPLIT_ORDER.filter(s=>evaluation.results[name][s]);
 const head=h('tr',{},h('th',{scope:'col',text:t('evidence.check')}),...splits.flatMap(s=>[h('th',{scope:'colgroup',colspan:'2',text:t('split.'+s)})]));
 const sub=h('tr',{},h('td'),...splits.flatMap(()=>[h('th',{scope:'col',text:t('evidence.recall')}),h('th',{scope:'col',text:t('evidence.precision')})]));
 const body=rows.map(r=>h('tr',{class:r.check==='overall'?'overall':''},h('th',{scope:'row',text:r.check==='overall'?t('evidence.overall'):t('check.'+r.check)}),...splits.flatMap(s=>[rateCell(r.cells[s].recall),rateCell(r.cells[s].precision)])));
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('evidence.detector.'+name)}),chip(t('evidence.synthetic'),'info')),
  h('p',{class:'panel-note',text:t('evidence.detector.'+name+'.x')}),h('div',{class:'table-wrap'},h('table',{class:'data-table rate-table'},h('thead',{},head,sub),h('tbody',{},body))));
}
function retrievalPanel(){
 const cell=r=>rateCell({value:r.value,numerator:r.numerator,denominator:r.denominator,low:r.wilson95[0]});
 const rows=['keyword','paraphrase','out_of_scope'].map(g=>{
  const x=retrieval.groups[g],head=h('th',{scope:'row',text:t('ret.group.'+g)}),n=h('td',{text:N(x.queries)});
  if(g==='out_of_scope')return h('tr',{},head,n,h('td',{colspan:'3',class:'rate'},h('strong',{text:t('ret.empty',{rate:P(x.correctly_empty.value)})}),h('small',{text:`${N(x.correctly_empty.numerator)}/${N(x.correctly_empty.denominator)}`}),h('small',{text:t('evidence.low',{p:P(x.correctly_empty.wilson95[0])})})));
  return h('tr',{},head,n,cell(x.recall_at_1),cell(x.recall_at_3),h('td',{class:'rate'},h('strong',{text:x.mrr.toFixed(2)})));
 });
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ret.title')}),chip('A22 · RAG','info')),h('p',{class:'panel-note',text:t('ret.intro')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table evidence-table'},h('thead',{},h('tr',{},['ret.col.group','ret.col.n','ret.col.first','ret.col.top3','ret.col.mrr'].map(k=>h('th',{scope:'col',text:t(k)})))),h('tbody',{},rows))),
  h('p',{class:'panel-note',text:t('ret.note')}));
}
function passagePanel(){
 const cell=r=>rateCell({value:r.value,numerator:r.numerator,denominator:r.denominator,low:r.wilson95[0]});
 const rows=Object.entries(passages.groups).flatMap(([group,g])=>[
  h('tr',{},h('th',{scope:'row',text:t('psg.group.'+group)}),h('td',{text:t('psg.method.document')}),cell(g.document_level.right_document_first),h('td',{class:'rate na',text:'—'}),h('td',{class:'rate'},h('strong',{text:N(g.document_level.mean_returned_bytes)}))),
  h('tr',{},h('th',{scope:'row',text:t('psg.group.'+group)}),h('td',{text:t('psg.method.passage')}),cell(g.passage_level.right_document_first),cell(g.passage_level.right_passage_first),h('td',{class:'rate'},h('strong',{text:N(g.passage_level.mean_returned_bytes)})))]);
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('psg.title')}),chip('RAG','info')),h('p',{class:'panel-note',text:t('psg.intro')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table evidence-table'},h('thead',{},h('tr',{},['psg.col.group','psg.col.method','psg.col.doc','psg.col.passage','psg.col.bytes'].map(k=>h('th',{scope:'col',text:t(k)})))),h('tbody',{},rows))),
  h('p',{class:'panel-note',text:t('psg.note')}));
}
// ---------- capability map ----------
function agentsHappened(run){
 const implemented=capabilities?.counts?.implemented??7;
 const ran=roleView(capabilities,run?.result?.plan).ran;
 return run?.result?.plan?t('agents.happened',{ran:N(ran),impl:N(implemented)}):t('agents.happened.none',{impl:N(implemented)});
}
async function loadCapabilities(){
 if(capabilitiesLoading||(capabilities&&platform)||!connected)return;
 capabilitiesLoading=true;
 try{[capabilities,platform]=await Promise.all([request('/api/capabilities'),request('/api/platform')]);}catch(error){setNotice(error.message,true);}
 capabilitiesLoading=false;render();
}
const ROLE_TONE={implemented:'ok',partial:'info',unavailable:'warn',disabled:'warn',planned:'muted'};
function roleCard(role){
 const limit=role.status==='planned'?t('agents.planned.limit'):t('role.'+role.agent_id+'.limit');
 const field=(label,value)=>h('div',{class:'role-field'},h('b',{text:t(label)}),h('span',{text:value}));
 return h('article',{class:'role-card '+role.status},
  h('div',{class:'role-head'},h('span',{class:'role-id',text:role.agent_id}),h('strong',{text:role.name}),chip(role.priority,'muted')),
  h('div',{class:'role-chips'},chip(t('agents.status.'+role.status),ROLE_TONE[role.status]),role.current?chip(t(role.current==='ran'?'agents.ran':'agents.skipped'),role.current==='ran'?'ok':'muted'):null),
  field('agents.does',t('role.'+role.agent_id+'.does')),field('agents.when',t('role.'+role.agent_id+'.when')),field('agents.limit',limit),
  role.implemented_by.length?h('div',{class:'role-field'},h('b',{text:t('agents.code')}),h('code',{text:role.implemented_by.join('  ·  ')})):null);
}
function platformPanel(){
 const tone={partial:'info',not_implemented:'muted',implemented:'ok'};
 const card=c=>h('article',{class:'role-card '+(c.status==='partial'?'partial':'planned')},
  h('div',{class:'role-head'},h('span',{class:'role-id',text:c.id}),h('strong',{text:t('plat.'+c.id+'.name')})),
  h('div',{class:'role-chips'},chip(t('plat.status.'+c.status),tone[c.status])),
  h('div',{class:'role-field'},h('b',{text:t('plat.exists')}),h('span',{text:t('plat.'+c.id+'.does')})),
  h('div',{class:'role-field'},h('b',{text:t('plat.missing')}),h('span',{text:t('plat.'+c.id+'.missing')})),
  c.implemented_by.length?h('div',{class:'role-field'},h('b',{text:t('agents.code')}),h('code',{text:c.implemented_by.join('  ·  ')})):null,
  c.tests.length?h('div',{class:'role-field'},h('b',{text:t('plat.tests')}),h('code',{text:c.tests.join('  ·  ')})):null);
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('plat.title')}),chip(t('plat.counts',{partial:N(platform.counts.partial),none:N(platform.counts.not_implemented)}),'muted')),
  h('p',{class:'panel-note',text:t('plat.intro')}),h('div',{class:'role-grid'},platform.components.map(card)),
  h('p',{class:'panel-note',text:t('plat.live',{n:N(platform.live),total:N(platform.total)})}));
}
function renderAgents(){
 const root=$('screen-agents');
 if(!connected){root.replaceChildren(h('section',{class:'panel'},empty('evidence.connect.t','evidence.connect.x')));return;}
 if(!capabilities||!platform){loadCapabilities();root.replaceChildren(h('section',{class:'panel'},empty('evidence.loading.t','evidence.loading.x')));return;}
 const view=roleView(capabilities,currentRun()?.result?.plan,roleFilter),c=capabilities.counts;
 const tile=(key,value,tone='')=>h('div',{class:'kpi '+tone},h('span',{text:t('agents.k.'+key)}),h('strong',{text:N(value)}),h('small',{text:t('agents.k.'+key+'.x')}));
 const filters=['all','implemented','partial','unavailable','disabled','planned'];
 root.replaceChildren(
  platformPanel(),
  h('div',{class:'kpi-grid'},tile('total',capabilities.total),tile('implemented',c.implemented,'ok'),tile('partial',c.partial),tile('blocked',c.unavailable+c.disabled),tile('planned',c.planned)),
  h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('agents.filter')}),chip(t('agents.count',{n:N(view.roles.length)}),'muted')),
   h('div',{class:'filter-row',role:'group','aria-label':t('agents.filter')},filters.map(f=>h('button',{type:'button',class:'secondary filter','aria-pressed':String(roleFilter===f),onclick:()=>{roleFilter=f;render();}},f==='all'?t('agents.filter.all'):t('agents.status.'+f)))),
   h('div',{class:'role-grid'},view.roles.map(roleCard)),
   h('p',{class:'panel-note',text:t('agents.note')})));
}

// ---------- router / lifecycle ----------
function render(){
 const screen=PAGES[route]||'overview',run=currentRun();
 document.querySelectorAll('.screen').forEach(s=>{s.hidden=s.dataset.screen!==screen;});
 $('page-eyebrow').textContent=t(`page.${screen}.eyebrow`);$('page-title').textContent=t(`page.${screen}.title`);
 document.title=`${t(`page.${screen}.title`)} · AegisFlow`;
 if(screen!=='overview')ccStop();
 if(screen!=='incident')incStop();
 if(screen!=='report')repLeave();
 $('page-actions').replaceChildren(...(screen==='history'?[link('/sources',t('cta.new')+' ↗','primary route')]:[]));
 renderShell();renderBrief(screen,run);
 ({overview:commandRender,investigations:()=>renderWorkspace(),sources:()=>renderSources(),activity:renderActivity,history:renderHistory,knowledge:renderKnowledge,quality:renderQuality,agents:renderAgents,flow:renderFlow,incident:renderIncident,report:renderReport})[screen]();
 $('notice').hidden=!$('notice').textContent;
}
async function refresh(){
 try{state=await request('/api/state');connected=true;}catch(error){connected=false;setNotice(error.message,true);return;}
 if(state.status==='RUNNING'){clearTimeout(polling);polling=setTimeout(refresh,700);setNotice(t('notice.running'));}
 else if(awaiting&&(state.status==='COMPLETED'||state.status==='FAILED')){
  const done=state.status==='COMPLETED';awaiting=false;
  if(done){viewId=null;navigate('/investigations');setNotice(t('notice.done'));return;}
  setNotice(t('notice.failed'),true);
 }
 render();
}
async function connect(){
 token=$('token').value.trim();
 if(!token){setNotice(t('notice.token'),true);return;}
 try{await refresh();if(connected){$('token').value='';$('access').hidden=true;$('session-toggle').setAttribute('aria-expanded','false');setNotice(t('notice.connected'));}}catch{}
 render();
}
function setLanguage(value){language=value;localStorage.setItem('aegis-language',value);render();}
document.addEventListener('click',event=>{
 const a=event.target.closest('a.route');
 if(a&&a.origin===location.origin&&!event.metaKey&&!event.ctrlKey){event.preventDefault();navigate(a.pathname);}
});
addEventListener('popstate',()=>navigate(location.pathname,false));
addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('.lang').forEach(b=>b.addEventListener('click',()=>setLanguage(b.dataset.language)));
 $('session-toggle').addEventListener('click',()=>{const open=$('access').hidden;$('access').hidden=!open;$('session-toggle').setAttribute('aria-expanded',String(open));if(open)$('token').focus();});
 $('connect').addEventListener('click',connect);
 $('token').addEventListener('keydown',e=>{if(e.key==='Enter')connect();});
 setNotice('');navigate(location.pathname,false);
});
