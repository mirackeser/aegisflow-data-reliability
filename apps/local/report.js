'use strict';
// Incident report (/report?incident=INC-0001): a print-ready A4 record of one simulated-plant incident in the page
// language. It is built only from GET /api/plant/incidents/<id>, its case file (/case) and the sealed agent run record
// (/api/agents/runs/<run_id>); every number on it comes from those responses and nothing here estimates anything.
// "Save as PDF" is the browser's print dialog: every character (Turkish included), no dependency, USD 0. The section
// model is pure and tested in Node (test_report.cjs); the drawing reuses the Incident page's builders.

if(typeof module!=='undefined'&&typeof incSteps==='undefined')Object.assign(globalThis,require('./incident.js'));

// ---------- pure core (also used by test_report.cjs) ----------
const REP_ID=/^INC-\d{4}$/;
const REP_SECTIONS=['summary','timeline','chart','findings','candidates','model','decision','chain','limits'];
const REP_LIMITS=['sim','supported','decision','model','digest'];

// The summary paragraph as sentences: string keys with raw parameters (formatted on the page).
function repSummary(view,cand,decision,cf){
 const inc=view.incident,ev=inc.evidence||{},run=view.run||null,out=[],say=(key,params={})=>out.push({key,params});
 say('rep.sum.detected',{id:inc.id,sensor:inc.sensor,severity:inc.severity,n:inc.findings.length,t:inc.opened_t});
 if(ev.onset_t!==null&&ev.onset_t!==undefined)say('rep.sum.onset',{t:ev.onset_t,method:ev.method});else say('rep.sum.noonset');
 if(ev.state==='ready')say('rep.sum.evidence',{records:ev.records,from:ev.first_t,to:ev.as_of_t,digest:ev.sha256});else say('rep.sum.noevidence');
 if(!run)say('rep.sum.norun');
 else if(run.state==='running')say('rep.sum.running');
 else if(run.state==='error')say('rep.sum.runerror');
 else if(!cand)say('rep.sum.norecord');
 else say('rep.sum.agents',{status:run.status,s:cand.counts.supported,o:cand.counts.open,r:cand.counts.refuted,
  accepted:cand.judge.accepted,advisory:cand.judge.advisory,rejected:cand.judge.rejected});
 if(decision)say('rep.sum.decision.'+decision.decision,{reviewer:decision.reviewer,candidate:decision.candidate??null,at:decision.decided_at});
 else say('rep.sum.nodecision');
 const b=incChainBanner(cf);
 say('rep.sum.chain.'+b.state,{kinds:b.kinds});
 return out;
}
// Everything the report shows, in order. The run record counts only when it is the record of the run on the incident.
function repModel(view,cf,detail){
 const inc=view.incident,record=detail?.record&&detail.run_id===view.run?.run_id?detail.record:null;
 const cand=incCandidates(record,view.investigation),decision=incDecisionFor(view);
 return {id:inc.id,sensor:inc.sensor,severity:inc.severity,status:inc.status,simulation:view.simulation!==false,
  summary:repSummary(view,cand,decision,cf),timeline:incSteps(view,record?{record}:null).steps,findings:inc.findings,
  candidates:cand,decision,other:view.decision&&!decision?view.decision:null,history:cf?.decisions||[],
  chain:incChainLinks(cf).map(l=>({...l,facts:incLinkFacts(l.kind,l.link?.summary)})),banner:incChainBanner(cf),
  head:cf?.head??null,content:cf?.content_sha256??null,run:view.run||null,sections:REP_SECTIONS,limits:REP_LIMITS};
}
// The page brief's two live answers: keys and raw parameters.
function repBrief(c){
 const out=(hk,hp,nk)=>({happened:{key:hk,params:hp},next:{key:nk,params:{}}});
 if(!c.connected)return out('rep.brief.connect',{},'inc.next.connect');
 if(!c.id||c.missing)return out('rep.brief.missing',{id:c.id||'—'},'rep.next.back');
 if(!c.data)return c.error?out('rep.brief.error',{reason:c.error},'rep.next.retry'):out('rep.brief.loading',{},'rep.next.wait');
 return out('rep.brief.ready',{id:c.id},'rep.next.print');
}

if(typeof module!=='undefined')module.exports={REP_ID,REP_SECTIONS,REP_LIMITS,repSummary,repModel,repBrief};

// ---------- browser page ----------
let repId=null,repData=null,repError='',repMissing=false,repLoading=false,repPrinting=false,repGenerated=null;

function openReport(id){
 setNotice('');
 if(typeof history!=='undefined')history.pushState({},'','/report?incident='+encodeURIComponent(id));
 navigate('/report',false);
}
// A plain click opens the report in place; a modified click (new tab or window) keeps the browser's default.
function repOpenLink(event,id){
 if(event.metaKey||event.ctrlKey||event.shiftKey||event.button===1)return;
 event.preventDefault();openReport(id);
}
async function repLoad(){
 const id=repId,base='/api/plant/incidents/'+encodeURIComponent(id);
 repLoading=true;repError='';
 try{
  const [view,cf]=await Promise.all([request(base),request(base+'/case')]);
  let detail=null;
  if(view.run?.state==='finished'){try{detail=await request('/api/agents/runs/'+encodeURIComponent(view.run.run_id));}catch{detail=null;}}
  if(id===repId){repData={view,cf,detail};repGenerated=new Date().toISOString();}
 }catch(error){if(id===repId){if(error.status===404)repMissing=true;else repError=error.message;}}
 repLoading=false;
 if(route==='/report')repPaint();
}

// ---------- formatting ----------
const repLower=s=>String(s).toLocaleLowerCase(locale());
const repMech=m=>m?tt('hy.mech.'+m,m):'—';
// The simulated wall-clock time of a lifecycle step that has a simulated second.
function repWall(s,view){
 const inc=view.incident,ev=inc.evidence||{};
 return {detected:inc.opened_at,onset:ev.onset_at,evidence:ev.as_of}[s.key]||null;
}
function repSentence(x,view){
 const p=x.params,at=sec=>incAt(sec,view);
 switch(x.key){
  case 'rep.sum.detected':return t(x.key,{id:p.id,sensor:ccSensorName(p.sensor),severity:repLower(t('cc.sev.'+p.severity)),n:N(p.n),at:at(p.t)});
  case 'rep.sum.onset':return t(x.key,{at:at(p.t),method:repLower(t(incMethodKey(view,{method:p.method})))});
  case 'rep.sum.evidence':return t(x.key,{records:N(p.records),from:at(p.from),to:at(p.to),digest:String(p.digest||'').slice(0,12)});
  case 'rep.sum.agents':return t(x.key,{status:repLower(flowLabel('runstatus',p.status)),s:N(p.s),o:N(p.o),r:N(p.r),accepted:N(p.accepted),advisory:N(p.advisory),rejected:N(p.rejected)});
  case 'rep.sum.decision.accepted':case 'rep.sum.decision.rejected':case 'rep.sum.decision.more_evidence':
   return t(x.key,{reviewer:p.reviewer,candidate:repMech(p.candidate),at:when(p.at)});
  case 'rep.sum.chain.waiting':case 'rep.sum.chain.mismatch':return t(x.key,{steps:p.kinds.map(k=>repLower(t('chain.kind.'+k))).join(', ')});
 }
 return t(x.key);
}
const repTable=(cls,head,rows,caption)=>h('div',{class:'table-wrap rep-table-wrap'},h('table',{class:'rep-table '+cls},caption?h('caption',{class:'sr-only',text:caption}):null,
 h('thead',{},h('tr',{},head.map(k=>h('th',{scope:'col',text:t(k)})))),h('tbody',{},rows)));
const repHash=hex=>hex?h('code',{class:'rep-hash',text:hex}):h('span',{text:'—'});
const repDl=(cls,pairs)=>h('dl',{class:'rep-dl '+cls},pairs.filter(Boolean).map(([k,v])=>h('div',{},h('dt',{text:t(k)}),h('dd',{},v))));

// ---------- sections ----------
function repHeader(m,view){
 const inc=view.incident;
 return h('header',{class:'rep-top'},
  h('div',{class:'rep-brandline'},
   h('span',{class:'rep-brand'},svgEl('svg',{viewBox:'0 0 28 28',class:'rep-logo','aria-hidden':'true',focusable:'false'},svgEl('path',{d:'M3 24 14 3l11 21-11-7-11 7Z M10 18l4-8 4 8'})),
    h('span',{text:'AegisFlow'})),
   h('span',{class:'rep-doc',text:t('rep.doc')})),
  h('h2',{class:'rep-title'},h('span',{class:'rep-title-id',text:m.id}),h('span',{class:'rep-title-sensor',text:ccSensorName(m.sensor)})),
  repDl('rep-meta',[
   ['rep.m.severity',ccSev(m.severity)],
   ['rep.m.status',h('span',{text:t('cc.status.'+m.status)})],
   ['rep.m.opened',h('span',{},h('span',{text:incAt(inc.opened_t,view)}),h('small',{text:when(inc.opened_at)}))],
   inc.status==='closed'?['rep.m.closed',h('span',{},h('span',{text:incAt(inc.closed_t,view)}),h('small',{text:when(inc.closed_at)}))]:null,
   ['rep.m.chain',repBannerChip(m.banner)],
   ['rep.m.generated',h('span',{text:when(repGenerated)})]]),
  m.simulation?h('p',{class:'rep-sim'},h('strong',{text:t('cc.badge')}),h('span',{text:t('rep.sim')})):null);
}
function repBannerChip(b){
 const tone={complete:'ok',waiting:'muted',mismatch:'bad',broken:'bad',loading:'muted'}[b.state];
 return h('span',{class:'rep-badge '+tone},hyIcon(INC_BANNER_SHAPE[b.state]),t('rep.chain.'+b.state));
}
function repTimeline(m,view){
 return repTable('rep-timeline',['rep.col.step','rep.col.state','rep.col.time','rep.col.detail'],m.timeline.map(s=>{
  const wall=repWall(s,view);
  return h('tr',{class:'rep-step '+s.state},h('th',{scope:'row',text:incStepName(s)}),h('td',{text:t('inc.state.'+s.state)}),
   h('td',{},s.t!==null?h('span',{text:incAt(s.t,view)}):h('span',{text:s.at?when(s.at):'—'}),s.t!==null&&wall?h('small',{text:when(wall)}):null),
   h('td',{text:incStepMeaning(s,view)}));
 }),t('rep.s.timeline'));
}
function repChart(view){
 const narrow=!repPrinting&&!!incNarrow?.matches,{svg,model}=incChartSvg(view,{narrow,hatch:'rep-hatch'});
 return h('figure',{class:'rep-figure'},h('div',{class:'rep-chart'},svg),
  h('figcaption',{},h('ul',{class:'rep-legend'},incMarkerText(model,view).map(x=>h('li',{text:x}))),
   h('p',{class:'rep-note',text:t(model.stream?'inc.chart.note.stream':'inc.chart.note',{window:N(view.settings.window_seconds),limit:N(view.settings.clear_statistic)})})));
}
function repFindings(view){
 return repTable('rep-findings',['inc.col.check','inc.col.column','inc.col.severity','inc.col.measured','inc.col.first'],view.incident.findings.map(f=>h('tr',{},
  h('th',{scope:'row',text:ccCheckName(f.check)}),h('td',{},f.column?h('code',{text:f.column}):'—'),h('td',{},ccSev(f.severity)),h('td',{text:ccFindingSentence(f)}),
  h('td',{},h('span',{text:incAt(f.first_t,view)}),h('small',{text:t('cc.ev.source.'+f.source)})))),t('rep.s.findings'));
}
function repCandidates(m){
 const c=m.candidates;
 if(!c)return h('p',{class:'rep-muted',text:t('rep.cand.none')});
 const parts=[h('p',{class:'rep-statement',text:t('hy.statement')})];
 if(!c.ran||!c.candidates.length){parts.push(h('p',{class:'rep-muted',text:c.error?t('inc.cand.a24',{code:flowLabel('code',c.error)}):t('flow.story.candidates.none')}));return parts;}
 parts.push(h('p',{class:'rep-cand-sum'},c.verdict?h('strong',{text:t('hy.verdict.'+c.verdict)}):null,
  h('span',{text:t('inc.cand.counts',{s:N(c.counts.supported),o:N(c.counts.open),r:N(c.counts.refuted)})}),
  c.used!==null?h('span',{text:t('hy.budget',{used:N(c.used),max:N(c.max)})}):null));
 const ruled=new Set();
 parts.push(h('ol',{class:'rep-cands'},c.candidates.map(x=>h('li',{class:'rep-cand '+x.status},
  h('div',{class:'rep-cand-head'},h('strong',{text:incMech(x)}),hyStatus(x.status)),
  h('p',{text:t('inc.cand.plain.'+x.status,{mech:incMech(x)})}),
  x.probes.length?h('ul',{class:'inc-probes rep-probes'},x.probes.map(p=>incProbeLine(p,ruled)))
   :h('p',{class:'rep-muted',text:t(x.mechanism==='genuine_change'?'hy.ev.untestable':'hy.ev.none')})))));
 if(c.stop)parts.push(h('p',{class:'rep-muted',text:t('hy.stop.'+c.stop)}));
 parts.push(h('p',{class:'rep-muted',text:t('hy.hyp.legend')}),
  h('p',{class:'rep-muted',text:c.verified?t('inc.verified',{ref:c.verified.sha256.slice(0,12)}):t('inc.unverified')}));
 return parts;
}
function repModelJudge(m){
 const c=m.candidates;
 if(!c)return h('p',{class:'rep-muted',text:t('rep.cand.none')});
 const mdl=c.model;
 return [h('h4',{text:t('inc.model')+' · '+t('inc.advisory')}),
  !mdl?h('p',{class:'rep-muted',text:t('flow.story.model.none')})
  :mdl.mechanisms===null?h('p',{text:t('inc.model.none',{code:flowLabel('code',mdl.error)})})
  :[h('p',{text:t('inc.model.suggested',{list:incList(mdl.mechanisms)})}),
   mdl.compared?repDl('rep-agree',[['inc.model.agreed',h('span',{text:incList(mdl.compared.agreed)})],['inc.model.only',h('span',{text:incList(mdl.compared.modelOnly)})],
    ['inc.model.rule',h('span',{text:incList(mdl.compared.ruleSupported)})]]):h('p',{class:'rep-muted',text:t('inc.model.nocompare')}),
   h('p',{class:'rep-muted',text:t('inc.model.judge',{verdict:mdl.verdict?t('flow.verdict.'+mdl.verdict):t('flow.verdict.none')})})],
  h('h4',{text:t('inc.judge')}),
  h('ul',{class:'rep-judge'},['accepted','advisory','rejected'].map(k=>h('li',{class:k},h('strong',{text:N(c.judge[k])}),h('span',{text:t('flow.verdict.'+k)})))),
  h('p',{class:'rep-muted',text:t('inc.judge.x')})];
}
function repDecision(m){
 const d=m.decision,parts=[];
 if(d)parts.push(repDl('rep-decision',[
  ['chain.f.decision',h('strong',{class:'rep-dec '+d.decision,text:t('dec.d.'+d.decision)})],
  d.candidate?['dec.f.candidate',h('span',{text:repMech(d.candidate)})]:null,
  ['dec.f.reviewer',h('span',{text:d.reviewer})],
  ['dec.f.at',h('span',{text:when(d.decided_at)})],
  d.note?['dec.f.note',h('span',{class:'rep-note-text',text:d.note})]:null,
  ['dec.f.run',h('code',{text:d.run_id})],
  ['dec.f.executed',h('span',{text:t('dec.executed.no')})],
  ['dec.f.digest',repHash(d.sha256)]]));
 else parts.push(h('p',{text:t('rep.sum.nodecision')}));
 if(m.other)parts.push(h('p',{class:'rep-muted',text:t('dec.other.run',{decision:t('dec.d.'+m.other.decision),run:m.other.run_id})}));
 parts.push(h('p',{class:'rep-muted',text:t('dec.accept.meaning')}));
 if(m.history.length)parts.push(h('h4',{text:t('rep.dec.history')}),
  repTable('rep-history',['rep.col.version','chain.f.decision','dec.f.candidate','dec.f.reviewer','dec.f.at','dec.f.digest'],m.history.map((v,i)=>h('tr',{},
   h('th',{scope:'row',text:N(i+1)}),h('td',{text:t('dec.d.'+v.decision)}),h('td',{text:repMech(v.candidate)}),h('td',{text:v.reviewer}),h('td',{text:when(v.decided_at)}),
   h('td',{},repHash(v.sha256)))),t('rep.dec.history')));
 return parts;
}
function repChain(m,view){
 return [incChainBannerEl(m.banner),h('p',{class:'rep-muted',text:t('chain.x')}),
  repTable('rep-chain',['rep.col.n','rep.col.link','chain.f.status','rep.col.time','rep.col.values','rep.col.hashes'],m.chain.map(l=>h('tr',{class:'rep-link '+l.status},
   h('td',{text:N(l.index+1)}),h('th',{scope:'row',text:t('chain.kind.'+l.kind)}),
   h('td',{},incChainStatus(l.status),l.status==='mismatch'?h('small',{text:tt('chain.reason.'+l.reason,t('chain.reason.unknown'))}):null),
   h('td',{text:l.link?incLinkTime(l.link):'—'}),
   h('td',{},l.link?h('ul',{class:'rep-facts'},l.facts.map(f=>h('li',{},h('span',{text:t('chain.f.'+f.key)+': '}),h('strong',{text:incFactText(f,view)})))):h('span',{text:t('chain.missing.x')})),
   h('td',{},l.link?[h('small',{text:t('chain.digest')}),repHash(l.link.digest),h('small',{text:t('chain.link')}),repHash(l.link.link_sha256)]:'—'))),t('rep.s.chain'))];
}
function repSheet(m,view){
 const sec=(key,...kids)=>h('section',{class:'rep-sec rep-'+key,'aria-labelledby':'rep-h-'+key},
  h('h3',{id:'rep-h-'+key},h('span',{class:'rep-num',text:String(REP_SECTIONS.indexOf(key)+1)}),h('span',{text:t('rep.s.'+key)})),...kids);
 return h('article',{class:'rep-sheet','aria-labelledby':'rep-title'},
  h('span',{id:'rep-title',class:'sr-only',text:t('rep.doc')+' '+m.id}),
  repHeader(m,view),
  sec('summary',h('p',{class:'rep-summary',text:m.summary.map(x=>repSentence(x,view)).join(' ')})),
  sec('timeline',repTimeline(m,view)),
  sec('chart',repChart(view)),
  sec('findings',repFindings(view)),
  sec('candidates',repCandidates(m)),
  sec('model',repModelJudge(m)),
  sec('decision',repDecision(m)),
  sec('chain',repChain(m,view)),
  sec('limits',h('ul',{class:'rep-limits'},m.limits.map(k=>h('li',{text:t('rep.limit.'+k)})))),
  h('footer',{class:'rep-foot'},
   repDl('rep-foot-dl',[['chain.head',repHash(m.head)],['chain.content',repHash(m.content)]]),
   h('p',{text:t('rep.footer',{at:when(repGenerated)})})));
}

// ---------- page ----------
function repPaint(){
 const root=typeof document!=='undefined'?$('screen-report'):null;
 if(!root||route!=='/report')return;
 if(typeof refreshBrief==='function')refreshBrief();
 if(!connected){root.replaceChildren(h('section',{class:'panel'},empty('rep.connect.t','rep.connect.x')));return;}
 if(!repId||repMissing){root.replaceChildren(h('section',{class:'panel'},h('div',{class:'empty-state'},h('strong',{text:t('rep.missing.t',{id:repId||'—'})}),
  h('span',{text:t('rep.missing.x')}),link('/overview',t('inc.back'),'secondary route'))));return;}
 if(!repData){root.replaceChildren(h('section',{class:'panel'},repError?[h('p',{class:'hint bad',role:'alert',text:t('rep.brief.error',{reason:repError})}),
  h('button',{type:'button',id:'rep-retry',class:'secondary',onclick:()=>{repError='';repPaint();repLoad();}},t('chain.retry'))]:empty('rep.loading.t','rep.loading.x')));return;}
 const {view,cf,detail}=repData,m=repModel(view,cf,detail);
 document.title=`${m.id} · ${t('page.report.title')} · AegisFlow`;
 const active=document.activeElement?.id;
 root.replaceChildren(h('div',{class:'rep'},
  h('div',{class:'rep-actions'},
   h('a',{href:'/incident?id='+encodeURIComponent(m.id),id:'rep-back',class:'secondary rep-back',onclick:e=>incOpenLink(e,m.id)},'← '+t('rep.back')),
   h('button',{type:'button',id:'rep-print',class:'primary rep-print','aria-describedby':'rep-print-x',onclick:()=>window.print()},t('rep.print')),
   h('p',{id:'rep-print-x',class:'hint',text:t('rep.print.x')})),
  repSheet(m,view)));
 if(active&&document.getElementById(active))document.getElementById(active).focus({preventScroll:true});
}
// Called by the router for /report: reads ?incident=, paints, and reads the data once per incident.
function renderReport(){
 const raw=typeof location!=='undefined'?new URLSearchParams(location.search).get('incident'):null,id=raw&&REP_ID.test(raw)?raw:null;
 if(id!==repId||!id){repId=id;repData=null;repError='';repMissing=!id;}
 repPaint();
 if(connected&&repId&&!repMissing&&!repData&&!repLoading&&!repError)repLoad();
}
// Leaving the page forgets the data, so coming back (after a decision, say) reads the incident again.
function repLeave(){repId=null;repData=null;repError='';repMissing=false;}
function reportBrief(){
 const b=repBrief({connected,id:repId,missing:repMissing,data:repData,error:repError});
 return {happened:t(b.happened.key,b.happened.params),next:t(b.next.key)};
}
if(typeof window!=='undefined'){
 // The chart is drawn at full width for paper, whatever the screen width.
 addEventListener('beforeprint',()=>{repPrinting=true;if(route==='/report'&&repData)repPaint();});
 addEventListener('afterprint',()=>{repPrinting=false;if(route==='/report'&&repData)repPaint();});
 incNarrow?.addEventListener?.('change',()=>{if(route==='/report'&&repData)repPaint();});
}
