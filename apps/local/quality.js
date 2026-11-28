'use strict';
// Measured quality (/quality): every committed evaluation on one page, read from GET /api/quality (and the existing
// /api/evaluation, /api/retrieval and /api/passages for the per-check and retrieval detail). Nothing here measures or
// estimates anything: every number is the API's, with its counts and Wilson 95% interval; "n/a" when nothing was
// measured. The model is pure and tested in Node (test_quality.cjs); the drawing below uses the page helpers of app.js.

// ---------- pure core (also used by test_quality.cjs) ----------
const QUA_SPLITS=['development','validation','heldout'];
const QUA_ORDER=['plant','agents','agents_v1','hypotheses','baseline','profiling','checks'];
// Held-out headline tiles: the decision each part of the system makes, and the model's weakest number next to them.
const QUA_HEADLINE=[['plant','sole_supported'],['plant','wrong_supported'],['agents','selection_exact'],['agents','a23_any'],
 ['agents','a23_top1'],['hypotheses','truth_sole_supported'],['baseline','case_detection'],['profiling','case_detection']];
const QUA_LIMITS=['synthetic','authors','pooled','heldout','model','cause'];

function quaCard(summary,id){return (summary?.evaluations||[]).find(c=>c.id===id&&c.available)||null;}
// String family of a card: the previous agents evaluation shares the agents labels.
const quaFamily=card=>card.family||card.id;
function quaMetric(card,key){return card?.metrics.find(m=>m.key===key)||null;}
// One metric on one split, as a display model: a rate keeps its counts and interval, a count per hours and a time stay
// as they are, and anything not measured on that split is n/a.
function quaValue(metric,split){
 const v=metric?.splits?.[split];
 if(v===undefined||v===null)return {kind:'na'};
 if(metric.kind==='rate')return v.value===null?{kind:'na',numerator:v.numerator,denominator:v.denominator}:{kind:'rate',...v};
 if(metric.kind==='per_hours')return {kind:'per_hours',count:v.count,hours:v.hours};
 return {kind:'ms',ms:v};
}
function quaHeadline(summary,split){
 return QUA_HEADLINE.map(([id,key])=>{const card=quaCard(summary,id),metric=quaMetric(card,key);
  return metric?{id,key,better:metric.better,value:quaValue(metric,split)}:null;}).filter(Boolean);
}
// Cases pooled over the rows of a scenario table for one column (a column that does not apply to a row is skipped).
function quaPoolColumn(card,column,split){
 let numerator=0,denominator=0;
 for(const row of card?.scenarios?.rows||[]){const r=row.splits?.[split]?.[column];if(r){numerator+=r.numerator;denominator+=r.denominator;}}
 return {numerator,denominator,value:denominator?numerator/denominator:null};
}
// The previous prompt's weakness in numbers from the API: how often A23's first mechanism is the injected one, how often
// the injected one is anywhere in its list, and how often the list is the catalog order of the explaining mechanisms.
function quaWeakness(summary,split){
 const card=quaCard(summary,'agents_v1');
 if(!card)return null;
 const top1=quaValue(quaMetric(card,'a23_top1'),split),any=quaValue(quaMetric(card,'a23_any'),split),echo=quaPoolColumn(card,'a23_echo',split);
 if(top1.kind!=='rate'||any.kind!=='rate'||echo.value===null)return null;
 return {top1,any,echo};
}
// The same three numbers for the previous and the latest agents evaluation, both from the API; null when either is
// missing or not measured on this split.
function quaChange(summary,split){
 const read=id=>{const card=quaCard(summary,id);if(!card)return null;
  const top1=quaValue(quaMetric(card,'a23_top1'),split),echo=quaPoolColumn(card,'a23_echo',split);
  return top1.kind==='rate'&&echo.value!==null?{top1,echo}:null;};
 const before=read('agents_v1'),after=read('agents');
 return before&&after?{before,after}:null;
}
function quaUnits(card,split){
 const u=card?.units?.[split];
 if(!u)return null;
 return u.seeds!==undefined?{key:'qua.units.seeds',n:u.seeds}:u.cases!==undefined?{key:'qua.units.cases',n:u.groups,c:u.cases}:{key:'qua.units.groups',n:u.groups};
}
function quaScenarioLabel(card,name){
 if(card.id==='plant'){const [fault,sensor]=name.split('/');return sensor?[ 'cc.fault.'+fault,'cc.sensor.'+sensor]:['cc.fault.'+fault];}
 return ['qua.scn.'+name];
}
function quaBrief(summary,split){
 const cards=QUA_ORDER.map(id=>quaCard(summary,id)).filter(Boolean);
 return {evaluations:cards.length,missing:QUA_ORDER.filter(id=>!quaCard(summary,id)),split};
}

if(typeof module!=='undefined')module.exports={QUA_SPLITS,QUA_ORDER,QUA_HEADLINE,QUA_LIMITS,quaCard,quaFamily,quaMetric,quaValue,
 quaHeadline,quaPoolColumn,quaWeakness,quaChange,quaUnits,quaScenarioLabel,quaBrief};

// ---------- page ----------
let quaData=null,quaLoading=false,quaSplit='heldout',quaError=null;

async function quaLoad(){
 if(quaLoading||!connected)return;
 quaLoading=true;quaError=null;
 try{[quaData,evaluation,retrieval,passages]=await Promise.all([request('/api/quality'),evaluation||request('/api/evaluation'),
  retrieval||request('/api/retrieval'),passages||request('/api/passages')]);}catch(error){quaError=error.message;}
 quaLoading=false;render();
}
function quaHappened(){
 if(!connected)return t('evidence.connect');
 if(!quaData)return t('evidence.loading');
 const b=quaBrief(quaData,quaSplit);
 return t('qua.happened',{n:N(b.evaluations),split:t('split.'+quaSplit)});
}
function quaPct(value){return P(value);}
// A rate as text plus a 0-100% track with the Wilson interval shaded and the measured value marked.
function quaRate(v,better,{large=false}={}){
 if(v.kind==='na')return h('div',{class:'qua-rate na'},h('strong',{text:t('evidence.na')}),
  v.denominator!==undefined?h('small',{text:t('qua.of',{n:N(v.numerator),d:N(v.denominator)})}):null);
 if(v.kind==='per_hours')return h('div',{class:'qua-rate'},h('strong',{text:t('qua.perhours',{n:N(v.count),h:N(v.hours)})}),h('small',{text:t('qua.perhours.x')}));
 if(v.kind==='ms')return h('div',{class:'qua-rate'},h('strong',{text:t('qua.ms',{ms:N(v.ms)})}),h('small',{text:t('qua.ms.x')}));
 const label=t('qua.bar.aria',{p:quaPct(v.value),low:quaPct(v.low),high:quaPct(v.high)});
 // Positions go through the CSSOM: the page's CSP (style-src 'self') refuses inline style attributes.
 const ci=h('span',{class:'qua-ci'}),dot=h('span',{class:'qua-dot'});
 ci.style.left=v.low*100+'%';ci.style.width=Math.max(0.5,(v.high-v.low)*100)+'%';dot.style.left=v.value*100+'%';
 return h('div',{class:'qua-rate'+(large?' large':'')},
  h('strong',{text:quaPct(v.value)}),
  h('div',{class:'qua-bar '+better,role:'img','aria-label':label},ci,dot),
  h('small',{text:t('qua.of',{n:N(v.numerator),d:N(v.denominator)})+' · '+t('qua.ci',{low:quaPct(v.low),high:quaPct(v.high)})}));
}
function quaSplitPicker(){
 return h('div',{class:'qua-splits',role:'group','aria-label':t('qua.split.label')},QUA_SPLITS.map(s=>h('button',{type:'button',class:'secondary filter','aria-pressed':String(quaSplit===s),
  onclick:()=>{quaSplit=s;render();}},t('split.'+s))));
}
function quaTile(tile){
 return h('div',{class:'kpi qua-tile'},h('span',{text:t('qua.card.'+tile.id)}),h('b',{class:'qua-tile-key',text:t('qua.m.'+tile.id+'.'+tile.key)}),
  quaRate(tile.value,tile.better,{large:true}),h('small',{class:'qua-better',text:t('qua.better.'+tile.better)}));
}
function quaMetricsTable(card){
 const units=quaUnits(card,quaSplit);
 return h('div',{class:'table-wrap'},h('table',{class:'data-table qua-table'},
  h('caption',{class:'sr-only',text:t('qua.card.'+card.id)+' · '+t('split.'+quaSplit)}),
  h('thead',{},h('tr',{},h('th',{scope:'col',text:t('qua.col.metric')}),h('th',{scope:'col',text:units?t(units.key,units):t('split.'+quaSplit)}),h('th',{scope:'col',class:'qua-dir',text:t('qua.col.better')}))),
  h('tbody',{},card.metrics.map(m=>h('tr',{},h('th',{scope:'row'},h('span',{text:t('qua.m.'+quaFamily(card)+'.'+m.key)}),h('small',{text:t('qua.m.'+quaFamily(card)+'.'+m.key+'.x')}),
    h('small',{class:'qua-dir-inline',text:t('qua.better.'+m.better)})),
   h('td',{},quaRate(quaValue(m,quaSplit),m.better)),h('td',{class:'qua-dir',text:t('qua.better.'+m.better)}))))));
}
function quaScenarioTable(card){
 const cols=card.scenarios.columns,cell=r=>{
  if(!r||r.value===null)return h('td',{class:'rate na',text:t('evidence.na')});
  return h('td',{class:'rate'},h('strong',{text:quaPct(r.value)}),h('small',{text:`${N(r.numerator)}/${N(r.denominator)}`}));};
 return h('details',{class:'qua-details'},h('summary',{text:t('qua.scenarios',{n:N(card.scenarios.rows.length)})}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table rate-table qua-scn'},
   h('thead',{},h('tr',{},h('th',{scope:'col',text:t('qua.col.scenario')}),cols.map(c=>h('th',{scope:'col',text:t('qua.c.'+quaFamily(card)+'.'+c)})))),
   h('tbody',{},card.scenarios.rows.map(row=>h('tr',{},h('th',{scope:'row',text:quaScenarioLabel(card,row.name).map(k=>t(k)).join(' · ')}),
    cols.map(c=>cell(row.splits?.[quaSplit]?.[c]))))))));
}
function quaChangeNote(){
 const c=quaChange(quaData,quaSplit);
 if(!c)return null;
 return h('div',{class:'qua-callout good',role:'note'},h('strong',{text:t('qua.change.t')}),
  h('p',{text:t('qua.change.x',{b1:quaPct(c.before.top1.value),a1:quaPct(c.after.top1.value),be:quaPct(c.before.echo.value),ae:quaPct(c.after.echo.value)})}));
}
function quaWeaknessNote(){
 const w=quaWeakness(quaData,quaSplit);
 if(!w)return null;
 return h('div',{class:'qua-callout',role:'note'},h('strong',{text:t('qua.weak.t')}),
  h('p',{text:t('qua.weak.x',{top1:quaPct(w.top1.value),any:quaPct(w.any.value),echo:quaPct(w.echo.value)})}));
}
function quaSection(card){
 const model=()=>h('p',{class:'panel-note',text:t('qua.agents.model',{model:card.model,v:card.prompt_version})});
 const extra=card.id==='agents'?[model(),quaChangeNote()]:card.id==='agents_v1'?[model(),quaWeaknessNote()]:
  card.id==='checks'&&evaluation?[h('details',{class:'qua-details'},h('summary',{text:t('qua.checks.detail')}),detectorPanel('diagnose_csv'),detectorPanel('record_issues'))]:[];
 return h('section',{class:'panel qua-section',id:'qua-'+card.id,'aria-labelledby':'qua-h-'+card.id},
  h('div',{class:'panel-heading'},h('h2',{id:'qua-h-'+card.id,text:t('qua.card.'+card.id)}),h('code',{class:'qua-report',text:card.report})),
  h('p',{class:'panel-note',text:t('qua.card.'+card.id+'.x')}),...extra,quaMetricsTable(card),
  card.scenarios?quaScenarioTable(card):null,
  h('p',{class:'qua-limit'},h('b',{text:t('qua.limit')+' '}),h('span',{text:t('qua.card.'+card.id+'.limit')})));
}
function renderQuality(){
 const root=$('screen-quality');
 if(!connected){root.replaceChildren(h('section',{class:'panel'},empty('evidence.connect.t','evidence.connect.x')));return;}
 if(quaError){root.replaceChildren(h('section',{class:'panel'},empty('qua.error.t','qua.error.x',h('button',{type:'button',class:'primary',onclick:()=>{quaError=null;quaLoad();}},t('qua.retry')))));return;}
 if(!quaData){quaLoad();root.replaceChildren(h('section',{class:'panel',role:'status'},empty('qua.loading.t','qua.loading.x')));return;}
 const cards=QUA_ORDER.map(id=>quaCard(quaData,id)).filter(Boolean),missing=quaBrief(quaData,quaSplit).missing;
 root.replaceChildren(
  h('section',{class:'panel qua-intro'},
   h('div',{class:'panel-heading'},h('h2',{text:t('qua.title')}),quaSplitPicker()),
   h('p',{class:'panel-note',text:t('qua.intro')}),
   h('div',{class:'role-chips'},chip(t('qua.chip.sim'),'info'),chip(t('qua.chip.once'),'ok'),chip(t('qua.chip.wilson'),'muted'),chip(t('qua.chip.na'),'muted'))),
  h('div',{class:'kpi-grid qua-grid'},quaHeadline(quaData,quaSplit).map(quaTile)),
  h('nav',{class:'qua-toc','aria-label':t('qua.toc')},cards.map(c=>h('a',{href:'#qua-'+c.id,text:t('qua.card.'+c.id)}))),
  ...cards.map(quaSection),
  missing.length?h('p',{class:'panel-note',text:t('qua.missing',{list:missing.map(id=>t('qua.card.'+id)).join(', ')})}):null,
  retrieval?retrievalPanel():null,passages?passagePanel():null,
  h('section',{class:'panel not-shown'},h('div',{class:'panel-heading'},h('h2',{text:t('evidence.not')}),chip(t('evidence.limits'),'warn')),
   h('ul',{class:'plain-list'},QUA_LIMITS.map(k=>h('li',{text:t('qua.lim.'+k)})))));
 root.querySelectorAll('.qua-toc a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();document.querySelector(a.getAttribute('href'))?.scrollIntoView({behavior:'smooth',block:'start'});}));
}
