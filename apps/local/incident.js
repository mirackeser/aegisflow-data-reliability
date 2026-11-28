'use strict';
// Incident page (/incident?id=INC-0001): one simulated-plant incident from its detection to the human decision.
// Every number comes from GET /api/plant/incidents/<id> (readings, baseline band, evidence window, simulation ground
// truth) or from the sealed agent run record. The change onset is estimated from the data only; the injected fault's
// start is simulation ground truth, shown beside it and never used by the estimator. Candidate explanations are
// "consistent with fixed probes", never a cause. The stepper, chart, candidate and operations models are pure and
// tested in Node (test_incident.cjs).

if(typeof module!=='undefined'&&typeof ccDomain==='undefined')Object.assign(globalThis,require('./command.js'));

// ---------- pure core (also used by test_incident.cjs) ----------
// Which mechanisms each probe bears on: aegisflow_dr.hypotheses.PROBE_MECHANISMS (a test keeps the two in step).
const INC_PROBE_MECHANISMS={scale_ratio:['unit_change'],spread_ratio:['calibration_offset','noise_increase'],flat_share:['stuck_sensor'],
 interval_regularity:['sampling_config_change','partial_load'],span_ratio:['partial_load','source_outage','delivery_delay','sampling_config_change'],
 freshness_lag:['source_outage','partial_load'],duplicate_share:['duplicate_delivery'],empty_runs:['field_outage','intermittent_loss']};
const INC_OUTCOMES=['supports','refutes','neutral'];
const INC_STEPS=['detected','onset','evidence','agents','judge','human'];
const INC_CHART={w:760,h:300,l:60,r:18,t:66,b:30};
const INC_CHART_NARROW={w:380,h:290,l:48,r:10,t:66,b:28}; // phones: a smaller viewBox keeps the text at reading size
const INC_LABEL_CHAR=6.4; // average advance of a marker-label character in chart units (11 px, weight 800)
const INC_TICK_STEPS=[5,10,15,20,30,60,120,300,600,1200,1800,3600];
const INC_ID=/^INC-\d{4}$/;
// The case file: the evidence-chain links in their fixed order (aegisflow_dr.casefile.LINKS) and the decisions a
// reviewer can record (casefile.DECISIONS), with the server's field limits.
// The baseline, evidence and probe links are stamped in simulated plant time; the agent run and the decision in real
// time. At a speed above 1x the two clocks drift apart, so the simulated ones are labelled rather than mixed silently.
const INC_SIM_CLOCK_LINKS=['baseline','evidence','probes'];
function incLinkTime(link){return when(link.at)+(INC_SIM_CLOCK_LINKS.includes(link.kind)?' · '+t('chain.clock.sim'):'');}
const INC_LINKS=['baseline','evidence','probes','agent_run','decision'];
const INC_DECISIONS=['accepted','rejected','more_evidence'];
const INC_REVIEWER_MAX=60,INC_NOTE_MAX=500;

// Whether the onset estimate is clear: the statistic reaches the clear threshold. Null when it does not apply (the
// data stopped, so there is no change-point statistic) or is not known yet.
// Clear vs uncertain is decided by the server (statistic against the fixed limit); only change points have it.
function incClear(ev){
 if(!ev||ev.method!=='change_point')return null;
 return ev.clear===true;
}
// Keep polling while something on the page can still change: the incident is open, its evidence is being collected,
// or its agent run is going.
function incNeedsPoll(view){
 if(!view)return true;
 const e=ccEvidence(view.incident.evidence).state;
 return view.incident.status==='open'||e==='collecting'||e==='locating'||view.run?.state==='running';
}

// Agent operations from the sealed record, else from the live event stream (a reduced Agent-flow state), else from
// the run summary alone. Counts are over the agents the run selected.
function incOps(run,record,live){
 if(record){
  const sel=(record.agents||[]).filter(a=>a.selected),count=s=>sel.filter(a=>a.result?.status===s).length,u=record.usage?.totals||{};
  return {source:'record',state:run?.state||'finished',status:record.status,selected:sel.length,finished:sel.length,completed:count('COMPLETED'),
   needs:count('NEEDS_EVIDENCE'),failed:count('FAILED'),denied:count('POLICY_DENIED'),skipped:count('SKIPPED'),
   llm:u.llm_calls??0,tokens:(u.tokens_in??0)+(u.tokens_out??0),ms:record.duration_ms??null,events:(record.events||[]).length};
 }
 if(live&&live.count){
  const nodes=Object.values(live.nodes),sel=nodes.filter(n=>n.selected),fin=sel.filter(n=>n.finished),count=s=>fin.filter(n=>n.state===s).length;
  return {source:'live',state:'running',status:null,selected:sel.length,finished:fin.length,completed:count('completed'),needs:count('needs_evidence'),
   failed:count('failed'),denied:count('denied'),skipped:count('skipped'),llm:live.used.llm_calls,tokens:live.used.tokens,ms:live.used.elapsed_ms,events:live.count};
 }
 if(run)return {source:'summary',state:run.state,status:run.status,selected:null,finished:null,completed:null,needs:null,failed:null,denied:null,skipped:null,
  llm:null,tokens:null,ms:null,events:run.events??null};
 return null;
}

// The lifecycle: detected -> onset estimated -> evidence collected -> agents investigated -> Judge decided -> awaiting a
// human decision. Step states: done, active, pending, blocked (cannot happen any more), failed, next (the human
// decision: the next roadmap step, never shown as done). ``current`` is the first step that is not done.
function incSteps(view,detail=null,live=null){
 const inc=view.incident,ev=inc.evidence||{},e=ccEvidence(ev),run=view.run||null,record=detail?.record||null;
 const onset=ev.onset_t!==null&&ev.onset_t!==undefined,closed=e.state==='unavailable';
 const step=(key,state,variant,extra={})=>({key,state,variant,t:null,at:null,params:{},...extra});
 const steps=[step('detected','done','done',{t:inc.opened_t,params:{n:inc.findings.length}})];
 steps.push(onset?step('onset','done',ev.method==='data_stopped'?'stopped':'done',{t:ev.onset_t,params:{statistic:ev.statistic??null,clear:incClear(ev)}})
  :step('onset',closed?'blocked':'active',closed?'blocked':'active'));
 steps.push(e.ready?step('evidence','done','done',{t:ev.as_of_t,params:{records:ev.records}})
  :closed?step('evidence','blocked','blocked'):onset?step('evidence','active','active',{params:{collected:e.collected,needed:e.needed}}):step('evidence','pending','pending'));
 const ops=incOps(run,record,live);
 if(run?.state==='finished')steps.push(step('agents','done','done',{at:run.finished_at,params:{status:run.status}}));
 else if(run?.state==='error')steps.push(step('agents','failed','failed',{at:run.started_at}));
 else if(run?.state==='running')steps.push(step('agents','active','running',{at:run.started_at,params:{finished:ops?.finished??null,selected:ops?.selected??null}}));
 else if(e.ready)steps.push(step('agents','active','ready'));
 else steps.push(step('agents',closed?'blocked':'pending',closed?'blocked':'pending'));
 const judged=!!record?.judge;
 steps.push(judged?step('judge','done','done',{at:record.finished_at,params:{accepted:record.judge.accepted,advisory:record.judge.advisory,rejected:record.judge.rejected}})
  :step('judge','pending','pending'));
 const decided=incDecisionFor(view);
 steps.push(decided?step('human','done','decided',{at:decided.decided_at,params:{decision:decided.decision,candidate:decided.candidate??null,reviewer:decided.reviewer}})
  :step('human',judged?'next':'pending','next'));
 return {steps,current:steps.findIndex(s=>s.state!=='done')};
}
// The latest decision on the frozen evidence counts for the page only while it names the run shown (a new run on the
// same evidence needs a new decision). Without a run summary (dropped from the bounded history) it still applies.
function incDecisionFor(view){
 const d=view?.decision||null;
 if(!d)return null;
 return view.run&&d.run_id!==view.run.run_id?null:d;
}

// ---------- case file: evidence chain and human decision ----------
// One entry per link kind in the fixed order, with its verification status and the link itself when it exists.
function incChainLinks(cf){
 if(!cf)return [];
 const link=Object.fromEntries((cf.chain||[]).map(l=>[l.kind,l])),check=Object.fromEntries((cf.checks||[]).map(c=>[c.kind,c]));
 return INC_LINKS.map((kind,index)=>({kind,index,status:check[kind]?.status||'missing',reason:check[kind]?.reason??null,link:link[kind]||null}));
}
// The chain's one-line verdict: loading, mismatch (the kinds whose source no longer matches), broken (a link does not
// hash to its recorded value), complete (all five verified) or waiting (intact; the kinds still missing).
function incChainBanner(cf){
 if(!cf)return {state:'loading',kinds:[]};
 const links=incChainLinks(cf),of=s=>links.filter(l=>l.status===s).map(l=>l.kind);
 const mismatch=of('mismatch');
 if(mismatch.length)return {state:'mismatch',kinds:mismatch};
 if(!cf.intact)return {state:'broken',kinds:[]};
 if(cf.complete)return {state:'complete',kinds:[]};
 return {state:'waiting',kinds:of('missing')};
}
// The recorded values of a link, as raw values with a display type (formatted by incFactText on the page).
function incLinkFacts(kind,s){
 if(!s)return [];
 const f=(key,value,type)=>({key,value,type});
 switch(kind){
  case 'baseline':return [f('records',s.records,'n'),f('references',s.references,'n')];
  case 'evidence':return [f('window',[s.first_t,s.as_of_t],'span'),f('records',s.records,'n'),f('method',s.method,'method'),f('onset',s.onset_t,'t'),f('statistic',s.statistic,'stat')];
  case 'probes':return [f('verdict',s.verdict,'verdict'),f('supported',s.supported,'mechs'),f('ref',s.ref,'code')];
  case 'agent_run':return [f('run',s.run_id,'code'),f('status',s.status,'runstatus'),f('completed',s.completed,'n'),f('judge',s.judge,'judge'),f('a24',s.a24_matches_probes,'bool')];
  case 'decision':return [f('decision',s.decision,'decision'),f('candidate',s.candidate,'mech'),f('reviewer',s.reviewer,'text')];
 }
 return [];
}
// Whether a decision can be recorded now and what it may say. ``wait`` names what is missing (evidence, run, running,
// failed, record) or is null. "accepted" lists only the mechanisms the probe loop supports on the frozen evidence (the
// server refuses anything else); without one it is disabled with the reason.
function incDecisionModel(view,detail){
 const e=ccEvidence(view.incident.evidence),run=view.run||null,record=detail?.record||null;
 const wait=!e.ready?'evidence':!run?'run':run.state==='running'?'running':run.state==='error'?'failed':run.state!=='finished'||!record?'record':null;
 const by=new Map();
 for(const hp of view.investigation?.hypotheses||[]){
  if(hp.status!=='supported')continue;
  if(!by.has(hp.mechanism))by.set(hp.mechanism,[]);
  if(hp.column&&!by.get(hp.mechanism).includes(hp.column))by.get(hp.mechanism).push(hp.column);
 }
 const candidates=[...by].map(([mechanism,columns])=>({mechanism,columns}));
 const options=INC_DECISIONS.map(value=>{
  const none=value==='accepted'&&!candidates.length;
  return {value,enabled:!wait&&!none,reason:none?'none_supported':null};
 });
 return {ready:!wait,wait,candidates,options,current:incDecisionFor(view),other:view.decision&&!incDecisionFor(view)?view.decision:null};
}
// Client-side check of the form before it is sent, mirroring casefile.decision_record (the server stays the judge):
// whitespace collapsed, reviewer 1–60 printable characters, note at most 500, a supported candidate for "accepted".
const incClean=s=>String(s??'').split(/\s+/).filter(Boolean).join(' ');
function incDecisionInput(form,model){
 const errors={},decision=form.decision,reviewer=incClean(form.reviewer),note=incClean(form.note);
 const option=model.options.find(o=>o.value===decision);
 if(!option||!option.enabled)errors.decision='choose';
 const candidate=decision==='accepted'?form.candidate??null:null;
 if(decision==='accepted'&&!model.candidates.some(c=>c.mechanism===candidate))errors.candidate='choose';
 const length=s=>[...s].length,printable=s=>!/\p{C}/u.test(s);
 if(!reviewer)errors.reviewer='empty';else if(length(reviewer)>INC_REVIEWER_MAX)errors.reviewer='long';else if(!printable(reviewer))errors.reviewer='printable';
 if(length(note)>INC_NOTE_MAX)errors.note='long';else if(!printable(note))errors.note='printable';
 const ok=!Object.keys(errors).length;
 return {ok,errors,body:ok?{decision,candidate,reviewer,note}:null};
}
// Why a decision was refused: a string key and parameters (the server's own message for invalid input).
function incDecisionError(error){
 const code=error?.body?.error;
 if(code==='EVIDENCE_NOT_READY'||error?.status===404)return ccStartError(error);
 if(error?.status===422)return {key:'dec.err.rejected',params:{reason:error.body?.message||error.message||''}};
 return {key:null,params:{}};
}
// The case file is read again only when something it covers changed: the frozen evidence, the run or its state, or the
// latest decision. A page that polls every second does not refetch it every second.
const incCaseKey=view=>JSON.stringify([view.incident.evidence?.sha256??null,view.run?.run_id??null,view.run?.state??null,view.decision?.sha256??null]);

// Candidate explanations from a sealed run record: A24 hypotheses (status), A25 probes (outcome counts over the
// hypotheses each probe concerned), A28 ranking, A23's advisory model suggestion compared with the rule result, and
// the Judge's counts. A probe's outcome is attributed to one hypothesis only when it is certain: the probe concerned
// every catalog peer on that column and gave them all the same outcome, or it is the only probe that bears on a
// supported (it supported it) or refuted (it refuted it) hypothesis. Otherwise the counts are shown as they are.
// A probe bears on a hypothesis when the catalog ties the probe to its mechanism and both name the same column.
const incBears=(p,h)=>(INC_PROBE_MECHANISMS[p.probe]||[]).includes(h.mechanism)&&p.column===(h.column??null);
function incProbesFor(hp,hyps,probes){
 const related=probes.filter(p=>incBears(p,hp)),sole={supported:'supports',refuted:'refutes'}[hp.status];
 return related.map(p=>{
  const known=p.outcomes?.[hp.hypothesis]; // exact, from the verified probe-loop record
  if(known)return {...p,concerned:p.supports+p.refutes+p.neutral,outcome:known};
  const concerned=p.supports+p.refutes+p.neutral,peers=hyps.filter(o=>incBears(p,o)).length,kinds=INC_OUTCOMES.filter(k=>p[k]>0);
  const exact=concerned>0&&concerned===peers&&kinds.length===1?kinds[0]:null;
  return {...p,concerned,outcome:exact||(related.length===1&&sole&&p[sole]>0?sole:null)};
 });
}
// The page's probe-loop record (the same deterministic call on the same frozen evidence as A24) is used for measured
// values and per-candidate outcomes only when the run holds exactly that record as A24 evidence (same reference).
function incVerified(record,investigation){
 const ref=investigation?.ref;if(!record||!ref)return false;
 const a24=(record.agents||[]).find(a=>a.agent_id==='A24')?.result;
 return [...(a24?.evidence_refs||[]),...(record.evidence||[])].some(r=>r&&r.id===ref.id&&r.sha256===ref.sha256);
}
function incCandidates(record,investigation=null){
 if(!record)return null;
 const result=id=>(record.agents||[]).find(a=>a.agent_id===id)?.result||null;
 const claims=(id,key)=>(result(id)?.claims||[]).filter(c=>c.text_key===key).map(c=>c.params||{});
 const hyps=claims('A24','a24.hypothesis'),verified=incVerified(record,investigation);
 const exact=id=>verified?(investigation.probes||[]).find(q=>q.id===id)||null:null;
 const probes=claims('A25','a25.probe').map(p=>({id:p.probe_id,probe:p.probe,column:p.column??null,round:p.round??null,
  supports:p.supports||0,refutes:p.refutes||0,neutral:p.neutral||0,
  measured:exact(p.probe_id)?.measured||(p.measured&&typeof p.measured==='object'?p.measured:null),outcomes:exact(p.probe_id)?.outcomes||null}));
 const ranking=claims('A28','a28.ranking')[0]||null,summary=claims('A24','a24.summary')[0]||null,stop=claims('A25','a25.stop')[0]||null;
 const order=ranking?.ranking||[],rank=id=>{const i=order.indexOf(id);return i===-1?order.length:i;};
 const candidates=hyps.map((hp,i)=>({id:hp.hypothesis,mechanism:hp.mechanism,column:hp.column??null,status:hp.status,
  explains:hp.explains||[],competitors:hp.competitors||[],index:i,
  probes:incProbesFor(hp,hyps,probes)})).sort((a,b)=>rank(a.id)-rank(b.id)||a.index-b.index);
 const a23=result('A23'),suggested=claims('A23','a23.suggested')[0]||null,compared=claims('A23','a23.compared')[0]||null;
 const index=key=>(a23?.claims||[]).findIndex(c=>c.text_key===key);
 const verdict=key=>{const i=index(key);return i===-1?null:(record.judge?.verdicts||[]).find(v=>v.agent==='A23'&&v.claim===i)?.verdict||null;};
 const model=a23&&a23.status!=='SKIPPED'?{status:a23.status,error:a23.error_code??null,mechanisms:suggested?.mechanisms||null,
  verdict:verdict('a23.suggested'),compared:compared?{agreed:compared.agreed||[],modelOnly:compared.model_only||[],ruleSupported:compared.rule_supported||[],verdict:verdict('a23.compared')}:null}:null;
 const a24=result('A24'),judge=record.judge||{};
 return {ran:!!a24&&a24.status!=='SKIPPED',status:a24?.status??null,error:a24?.error_code??null,candidates,probes,
  verdict:ranking?.verdict??summary?.verdict??null,stop:stop?.stop_reason??null,used:stop?.used??null,max:stop?.max_probes??null,
  counts:{supported:candidates.filter(c=>c.status==='supported').length,open:candidates.filter(c=>c.status==='open').length,refuted:candidates.filter(c=>c.status==='refuted').length},
  model,judge:{accepted:judge.accepted??0,advisory:judge.advisory??0,rejected:judge.rejected??0},
  verified:verified?investigation.ref:null};
}

// x-axis ticks at whole multiples of a readable step of simulated seconds since the live start.
function incTicks(t0,t1,liveStart,max=6){
 const span=Math.max(1,t1-t0),step=INC_TICK_STEPS.find(s=>span/s<=max)||INC_TICK_STEPS[INC_TICK_STEPS.length-1],ticks=[];
 for(let a=Math.ceil((t0-liveStart)/step)*step;a+liveStart<=t1;a+=step)ticks.push(a+liveStart);
 return {step,ticks};
}
// Geometry of the incident chart. Sensor incidents plot the sensor's readings against its baseline band (mean ± 3 sd);
// stream incidents plot the gaps between arrivals (the series the onset is estimated on), which have no band here.
// The x range covers the readings and the whole evidence window, so a window still being collected shows its end.
function incChartModel(view,size={},maxTicks=6){
 const C={...INC_CHART,...size},inc=view.incident,ev=inc.evidence||{},truth=inc.truth||null,ts=view.series.t||[];
 const sensor=inc.sensor,stream=!view.bands?.[sensor];
 const points=stream?ts.slice(1).map((t,i)=>({t,v:t-ts[i]})):ts.map((t,i)=>({t,v:view.series[sensor][i]}));
 const band=stream?null:view.bands[sensor];
 const finite=v=>typeof v==='number'&&Number.isFinite(v);
 let t0=points.length?points[0].t:inc.opened_t,t1=points.length?points[points.length-1].t:inc.opened_t;
 if(finite(ev.as_of_t))t1=Math.max(t1,ev.as_of_t);
 if(t1-t0<1)t1=t0+1;
 const dom=ccDomain(stream?[0,...points.map(p=>p.v)]:points.map(p=>p.v),band); // gaps are measured from zero
 const x=t=>C.l+(t-t0)/(t1-t0)*(C.w-C.l-C.r),y=v=>C.t+(1-(v-dom.min)/(dom.max-dom.min))*(C.h-C.t-C.b);
 const inView=t=>finite(t)&&t>=t0&&t<=t1;
 let path='',prev=null;
 for(const p of points){path+=(prev===null||(!stream&&p.t-prev>CC_GAP_S)?'M':'L')+x(p.t).toFixed(1)+' '+y(p.v).toFixed(1);prev=p.t;}
 const settings=view.settings||{clear_statistic:30};
 const onset=finite(ev.onset_t)?{t:ev.onset_t,x:x(ev.onset_t),inView:inView(ev.onset_t),method:ev.method,statistic:ev.statistic??null,clear:incClear(ev)}:null;
 const injected=truth&&finite(truth.started_t)?{t:truth.started_t,x:x(truth.started_t),inView:inView(truth.started_t),fault:truth.fault,error:truth.onset_error_s??null}:null;
 const detected={t:inc.opened_t,x:x(inc.opened_t),inView:inView(inc.opened_t)};
 let win=null;
 if(finite(ev.first_t)&&finite(ev.as_of_t)){
  const ready=ev.state==='ready',reached=ready?ev.as_of_t:Math.max(ev.first_t,Math.min(ev.as_of_t,view.now_t-1));
  const lo=Math.max(t0,ev.first_t),hi=Math.min(t1,ev.as_of_t),mid=Math.max(lo,Math.min(hi,reached));
  win={first:ev.first_t,last:ev.as_of_t,ready,x0:x(lo),x1:x(hi),xReached:x(mid),inView:hi>=lo};
 }
 const ticks=incTicks(t0,t1,view.live_start_t,maxTicks);
 return {width:C.w,height:C.h,plot:{l:C.l,r:C.w-C.r,t:C.t,b:C.h-C.b},t0,t1,stream,sensor,points,path,count:points.length,domain:dom,
  band:band?{top:y(band.high),bottom:y(band.low),mean:y(band.mean),low:band.low,high:band.high,sd:band.sd,center:band.mean}:null,
  yTicks:dom.ticks.map(v=>({v,y:y(v)})),xTicks:ticks.ticks.map(t=>({t,x:x(t)})),onset,injected,detected,window:win,
  inWindow:t=>!!win&&t>=win.first&&t<=win.last,
  min:points.length?Math.min(...points.map(p=>p.v)):null,max:points.length?Math.max(...points.map(p=>p.v)):null};
}

// The page brief's two live answers: keys and raw parameters.
function incBrief(c){
 const out=(hk,hp,nk,np={})=>({happened:{key:hk,params:hp},next:{key:nk,params:np}});
 if(!c.connected)return out('inc.brief.connect',{},'inc.next.connect');
 if(!c.id||c.missing)return out('inc.brief.missing',{id:c.id||'—'},'inc.next.back');
 if(!c.view)return out(c.error?'inc.brief.error':'inc.brief.loading',{reason:c.error||''},'inc.next.wait');
 const inc=c.view.incident,e=ccEvidence(inc.evidence),{steps,current}=incSteps(c.view,c.detail,c.live);
 const decided=incDecisionFor(c.view);
 const happened=decided?['inc.brief.decided',{id:inc.id,status:inc.status,decision:decided.decision}]
  :['inc.brief.'+e.state,{id:inc.id,status:inc.status,n:e.collected,needed:e.needed,records:inc.evidence?.records??0}];
 if(current===-1)return out(...happened,'inc.next.report');
 const s=steps[current];
 const next={onset:'inc.next.onset',evidence:'inc.next.collect',agents:{ready:'inc.next.investigate',running:'inc.next.watch',failed:'inc.next.retry',blocked:'inc.next.closed',pending:'inc.next.collect'}[s.variant],
  judge:'inc.next.watch',human:'inc.next.decide'}[s.key];
 if(s.state==='blocked')return out(...happened,'inc.next.closed');
 return out(...happened,next||'inc.next.wait',{left:Math.max(0,e.needed-e.collected)});
}

if(typeof module!=='undefined')module.exports={INC_SIM_CLOCK_LINKS,INC_PROBE_MECHANISMS,INC_STEPS,INC_CHART,INC_CHART_NARROW,INC_LINKS,INC_DECISIONS,incClear,incMethodKey,incNeedsPoll,incOps,incSteps,
 incVerified,incCandidates,incTicks,incChartModel,incBrief,incDecisionFor,incChainLinks,incChainBanner,incLinkFacts,incDecisionModel,incDecisionInput,incDecisionError,incCaseKey};

// ---------- browser page ----------
let incId=null,incView=null,incDetail=null,incDetailLoading=null,incError='',incMissing=false,incTimer=null,incInflight=false,incStarting=false,
 incDom=null,incLive=null,incLiveRun=null,incStreamCtl=null,incActive=null,incTableOpen=false,incLastStep=null,incFrame=0,
 incCase=null,incCaseSig=null,incCaseError='',incLastBanner=null,incSubmitting=false,incDecErrors={},incDecError='',incHistoryOpen=false;
// The decision form's values live here, so a repaint never loses what the reviewer typed.
const incForm={decision:null,candidate:null,reviewer:'',note:''};
const INC_POLL_MS=1000,INC_RETRY_MS=4000;
const incNarrow=typeof matchMedia==='function'?matchMedia('(max-width: 760px)'):null;

const incWanted=()=>connected&&route==='/incident'&&!!incId&&!incMissing&&(typeof document==='undefined'||document.visibilityState!=='hidden');
function incStreamStop(){incStreamCtl?.abort();incStreamCtl=null;}
function incStop(){clearTimeout(incTimer);incTimer=null;incStreamStop();}
function incSchedule(delay=INC_POLL_MS){clearTimeout(incTimer);incTimer=null;if(incWanted())incTimer=setTimeout(incPoll,delay);}
function incPaintSoon(){
 if(incFrame||typeof requestAnimationFrame!=='function')return;
 incFrame=requestAnimationFrame(()=>{incFrame=0;incPaint();});
}
async function incFetch(){
 if(incInflight||!incId)return;
 incInflight=true;const id=incId;
 try{
  const view=await request('/api/plant/incidents/'+encodeURIComponent(id));
  if(id===incId){
   incView=view;incError='';incMissing=false;
   const e=ccEvidence(view.incident.evidence);
   if(view.run?.state==='running')incActive=view.run.run_id;
   else incActive=e.ready?view.runs_active||null:null;
   incFollowRun(view.run);
   if(incCaseKey(view)!==incCaseSig)incLoadCase(incCaseKey(view));
  }
 }catch(error){
  if(id===incId){if(error.status===404){incMissing=true;incView=null;}else incError=t('inc.err.poll',{reason:error.message});}
 }finally{incInflight=false;}
}
async function incPoll(){
 incTimer=null;
 if(!incWanted())return;
 await incFetch();
 incPaint();
 if(incError||incStarting||incNeedsPoll(incView))incSchedule(incError?INC_RETRY_MS:INC_POLL_MS);
}
// A running investigation is followed over the run's event stream (agents finished / selected); a finished one is
// read once from its sealed record.
function incFollowRun(run){
 if(!run)return;
 if(run.state==='running'&&!(incLiveRun===run.run_id&&incStreamCtl))incStream(run.run_id);
 if(run.state==='finished'&&incDetail?.run_id!==run.run_id&&incDetailLoading!==run.run_id)incLoadDetail(run.run_id);
}
async function incLoadDetail(runId){
 incDetailLoading=runId;
 try{const detail=await request('/api/agents/runs/'+encodeURIComponent(runId));if(detail.record&&incView?.run?.run_id===runId)incDetail=detail;}catch{}
 incDetailLoading=null;incPaintSoon();
}
async function incStream(runId){
 incStreamStop();
 const control=new AbortController();incStreamCtl=control;
 if(incLiveRun!==runId){incLiveRun=runId;incLive=flowInitial();}
 try{
  const headers={Authorization:'Bearer '+token};
  if(incLive.lastSeq)headers['Last-Event-ID']=String(incLive.lastSeq);
  const response=await fetch('/api/agents/stream?run='+encodeURIComponent(runId),{headers,cache:'no-store',signal:control.signal});
  if(!response.ok||!response.body)throw new Error('stream');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  for(;;){
   const {value,done}=await reader.read();
   if(done)break;
   const parsed=parseSse(buffer+decoder.decode(value,{stream:true}));buffer=parsed.rest;
   for(const frame of parsed.frames)if(frame.event==='agent'){try{incLive=reduceFlow(incLive,JSON.parse(frame.data));}catch{}}
   incPaintSoon();
  }
 }catch{if(control.signal.aborted)return;}
 if(incStreamCtl===control){incStreamCtl=null;if(incWanted()&&!incInflight)incSchedule(0);}
}
async function incInvestigate(){
 if(!incView||incStarting||!requireSession())return;
 incStarting=true;incPaint();
 try{
  const started=await request(`/api/plant/incidents/${encodeURIComponent(incId)}/investigate`,'POST','{}',JSON_HEADERS);
  setNotice(t('inc.started',{id:incId}));incAnnounce(t('inc.live.started',{id:incId}));
  incActive=started.run_id;
 }catch(error){setNotice(incErrorText(error),true);}
 incStarting=false;
 await incFetch();incPaint();incSchedule();
}
function incErrorText(error){const x=ccStartError(error);return x.key?t(x.key,{n:N(x.params.n??0),needed:N(x.params.needed??0)}):error.message;}
// The evidence CSV needs the session header, so it is fetched and handed to the browser as a Blob download.
async function incDownload(){
 if(!incView||!requireSession())return;
 const id=incId;
 try{
  const response=await fetch(`/api/plant/incidents/${encodeURIComponent(id)}/evidence.csv`,{headers:{Authorization:'Bearer '+token},cache:'no-store'});
  if(!response.ok){let body=null;try{body=await response.json();}catch{}const error=new Error(t('err.unavailable'));error.status=response.status;error.body=body;throw error;}
  const url=URL.createObjectURL(await response.blob()),a=h('a',{href:url,download:`${id}-evidence.csv`});
  document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),0);
  setNotice(t('inc.csv.done',{id}));
 }catch(error){setNotice(incErrorText(error),true);}
}
function openIncident(id){
 setNotice('');
 if(typeof history!=='undefined')history.pushState({},'','/incident?id='+encodeURIComponent(id));
 navigate('/incident',false);
}
// A plain click opens the page in place; a modified click (new tab or window) keeps the browser's default.
function incOpenLink(event,id){
 if(event.metaKey||event.ctrlKey||event.shiftKey||event.button===1)return;
 event.preventDefault();openIncident(id);
}
function incAnnounce(text){const live=document.getElementById('inc-live');if(live)live.textContent=text;}

// ---------- formatting ----------
const incAt=(sec,view=incView)=>view&&typeof sec==='number'?ccRel(sec,view.live_start_t):'—';
const incSigned=n=>n===null||n===undefined?'—':(n>0?'+':n<0?'−':'±')+N(Math.abs(n));
const incShort=(hex,n=12)=>hex?h('code',{title:hex,text:hex.slice(0,n)+'…'}):h('span',{text:'—'});
const incUnit=view=>incIsStream(view)?'s':view.units?.[view.incident.sensor]||'';
const incIsStream=view=>!view.bands?.[view.incident.sensor];
// The method label names what the change point was fitted on: arrival gaps, a seasonal sensor, or a plain sensor.
function incMethodKey(view,ev){
 if(!ev?.method)return 'inc.method.none';
 if(ev.method!=='change_point')return 'inc.method.'+ev.method;
 return incIsStream(view)?'inc.method.change_point.gaps':view.seasonality?.[view.incident.sensor]?.period?'inc.method.change_point.seasonal':'inc.method.change_point';
}
const incDigits=view=>incIsStream(view)?0:CC_DIGITS[view.incident.sensor]??2;
const incDuration=inc=>ccClock((inc.status==='open'?incView.now_t:inc.closed_t)-inc.opened_t);
const incMech=c=>t('hy.mech.'+c.mechanism)+(c.column?' · '+c.column:'');
const incList=list=>(list&&list.length?list.map(m=>tt('hy.mech.'+m,m)).join(', '):t('inc.none'));
function incStatistic(ev,view=incView){
 if(ev.method==='data_stopped')return t('inc.stat.stopped');
 if(ev.statistic===null||ev.statistic===undefined)return '—';
 const clear=incClear(ev);
 return t(clear?'inc.stat.clear':'inc.stat.uncertain',{stat:ccNum(ev.statistic,1),limit:N(view.settings.clear_statistic)});
}
function incSection(node,sig,build){if(node.incSig===sig)return;node.incSig=sig;node.replaceChildren(...[build()].flat().filter(Boolean));}
const incPanel=(cls,titleId,title,...kids)=>h('section',{class:'panel '+cls,'aria-labelledby':titleId},h('div',{class:'panel-heading'},h('h2',{id:titleId,text:title})),...kids);

// ---------- chart ----------
// ``opts.narrow`` picks the phone geometry; ``opts.hatch`` names the pattern id (the report draws its own copy).
function incChartSvg(view,opts={}){
 const narrow=opts.narrow??!!incNarrow?.matches,hatch=opts.hatch||'inc-hatch',at=sec=>incAt(sec,view);
 const m=incChartModel(view,narrow?INC_CHART_NARROW:{},narrow?4:6),P=m.plot,unit=incUnit(view),d=incDigits(view);
 const label=t(m.stream?'inc.chart.label.stream':'inc.chart.label',{sensor:ccSensorName(view.incident.sensor),unit,n:N(m.count),from:at(m.t0),to:at(m.t1),
  min:ccNum(m.min,d),max:ccNum(m.max,d)})+' '+incMarkerText(m,view).join(' ');
 const svg=svgEl('svg',{viewBox:`0 0 ${m.width} ${m.height}`,class:'inc-chart',role:'img','aria-label':label});
 svg.append(svgEl('title',{},document.createTextNode(label)));
 svg.append(svgEl('defs',{},svgEl('pattern',{id:hatch,width:'6',height:'6',patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'},svgEl('line',{x1:'0',y1:'0',x2:'0',y2:'6',class:'inc-hatch-line'}))));
 const yDigits=m.domain.step<1?(m.domain.step<0.1?2:1):0;
 for(const tick of m.yTicks)svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:tick.y,y2:tick.y,class:'cc-grid'}),svgText(ccNum(tick.v,yDigits),{x:P.l-8,y:tick.y+3.5,class:'cc-axis','text-anchor':'end'}));
 for(const tick of m.xTicks)svg.append(svgEl('line',{x1:tick.x,x2:tick.x,y1:P.b,y2:P.b+4,class:'inc-tick'}),svgText(at(tick.t),{x:tick.x,y:m.height-8,class:'cc-axis','text-anchor':tick.x<P.l+24?'start':tick.x>P.r-24?'end':'middle'}));
 svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:P.b,y2:P.b,class:'inc-axis-line'}),svgText(unit,{x:P.l-8,y:P.t-16,class:'cc-axis unit','text-anchor':'end'}));
 if(m.window?.inView){
  const W=m.window;
  if(W.xReached>W.x0)svg.append(svgEl('rect',{x:W.x0,y:P.t,width:W.xReached-W.x0,height:P.b-P.t,class:'inc-win'}));
  if(W.x1>W.xReached)svg.append(svgEl('rect',{x:W.xReached,y:P.t,width:W.x1-W.xReached,height:P.b-P.t,class:'inc-win-pending',fill:`url(#${hatch})`}));
  svg.append(svgEl('line',{x1:W.x0,x2:W.x0,y1:P.t,y2:P.b,class:'inc-win-edge'}),svgEl('line',{x1:W.x1,x2:W.x1,y1:P.t,y2:P.b,class:'inc-win-edge'}));
  if(W.x1-W.x0>=70)svg.append(svgText(t(W.ready?'inc.chart.window':'inc.chart.window.collecting'),{x:W.x0+5,y:P.b-6,class:'inc-win-label'}));
 }
 if(m.band){
  const top=Math.max(P.t,Math.min(P.b,m.band.top)),bottom=Math.max(P.t,Math.min(P.b,m.band.bottom));
  if(bottom-top>0.5)svg.append(svgEl('rect',{x:P.l,y:top,width:P.r-P.l,height:bottom-top,class:'cc-band'}));
  for(const edge of [m.band.top,m.band.bottom])if(edge>=P.t&&edge<=P.b)svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:edge,y2:edge,class:'cc-band-edge'}));
  if(m.band.mean>=P.t&&m.band.mean<=P.b)svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:m.band.mean,y2:m.band.mean,class:'cc-band-mean'}));
 }
 svg.append(svgEl('path',{d:m.path,class:'cc-line'+(m.stream?' inc-gaps':'')}));
 // Markers: one label row each above the plot, so their labels never overlap. A label sits right of its line unless
 // its estimated width would cross the chart edge; then it ends at the line, kept inside the left edge.
 const marker=(mk,cls,row,text)=>{
  if(!mk?.inView)return;
  const ly=14+row*16,width=text.length*INC_LABEL_CHAR,right=mk.x+5+width>m.width-4,g=svgEl('g',{class:'inc-mark '+cls});
  g.append(svgEl('line',{x1:mk.x,x2:mk.x,y1:ly+4,y2:P.b,class:'inc-mark-line'}),
   svgText(text,{x:right?Math.max(width+4,mk.x-5):mk.x+5,y:ly,class:'inc-mark-label','text-anchor':right?'end':'start'}));
  svg.append(g);
 };
 const o=m.onset;
 marker(o,'onset'+(o&&o.clear===false?' uncertain':''),0,narrow?t('inc.chart.onset.short'):o?.method==='data_stopped'?t('inc.chart.onset.stopped')
  :t('inc.chart.onset',{stat:ccNum(o?.statistic,1),clarity:t(o?.clear?'inc.clear':'inc.uncertain')}));
 marker(m.injected,'injected',1,narrow?t('inc.chart.injected.short'):t('inc.chart.injected',{error:incSigned(m.injected?.error)}));
 marker(m.detected,'detected '+view.incident.severity,2,t('inc.chart.detected'));
 return {svg,model:m};
}
// One sentence per marker for the legend and the chart's text alternative.
function incMarkerText(m,view=incView){
 const out=[],d=incDigits(view),unit=incUnit(view),at=sec=>incAt(sec,view);
 if(m.onset)out.push(m.onset.method==='data_stopped'?t('inc.legend.onset.stopped',{at:at(m.onset.t)})
  :t('inc.legend.onset',{at:at(m.onset.t),stat:incStatistic(view.incident.evidence,view)}));
 else out.push(t('inc.legend.onset.none'));
 if(m.injected)out.push(t('inc.legend.injected',{at:at(m.injected.t),fault:t('cc.fault.'+m.injected.fault),error:incSigned(m.injected.error)})+(m.injected.inView?'':' '+t('inc.legend.outside')));
 else out.push(t('inc.legend.injected.none'));
 out.push(t('inc.legend.detected',{at:at(m.detected.t)}));
 if(m.window)out.push(t(m.window.ready?'inc.legend.window':'inc.legend.window.collecting',{from:at(m.window.first),to:at(m.window.last)}));
 if(m.band)out.push(t('inc.legend.band',{low:ccNum(m.band.low,d),high:ccNum(m.band.high,d),mean:ccNum(m.band.center,d),sd:ccNum(m.band.sd,d),unit}));
 else out.push(t('inc.legend.gaps'));
 return out;
}

// ---------- building the page (once per language and incident) ----------
function incBuild(root){
 const d={lang:language,id:incId};
 d.live=h('p',{id:'inc-live',class:'sr-only',role:'status','aria-live':'polite','aria-atomic':'true'});
 d.head=h('section',{class:'panel inc-head','aria-label':t('inc.head.label')});
 d.steps=h('div',{class:'inc-steps-body'});
 d.stepsPanel=incPanel('inc-steps-panel','inc-steps-title',t('inc.steps'),d.steps,h('p',{class:'panel-note',text:t('inc.steps.note')}));
 d.chart=h('div',{class:'inc-chart-wrap'});d.legend=h('ul',{class:'inc-legend'});d.chartNote=h('p',{class:'panel-note'});
 d.tableBody=h('div',{class:'table-wrap inc-table-wrap'});d.tableSum=h('summary',{id:'inc-table-sum',text:t('inc.table.show')});
 d.table=h('details',{class:'inc-table',id:'inc-table',ontoggle:e=>{incTableOpen=e.target.open;d.tableBody.incSig=null;incPaint();}},d.tableSum,d.tableBody);
 d.table.open=incTableOpen;
 d.chartPanel=incPanel('inc-chart-panel','inc-chart-title',t('inc.chart'),d.chart,d.legend,d.chartNote,d.table);
 d.go=h('button',{type:'button',id:'inc-investigate',class:'primary inc-go','aria-describedby':'inc-go-why',onclick:incInvestigate});
 d.csv=h('button',{type:'button',id:'inc-csv',class:'secondary inc-csv','aria-describedby':'inc-csv-why',onclick:incDownload});
 d.goWhy=h('p',{id:'inc-go-why',class:'inc-why'});d.csvWhy=h('p',{id:'inc-csv-why',class:'hint'});d.runLink=h('p',{class:'inc-runlink'});
 d.evidence=h('div',{class:'inc-ev-body'});d.truth=h('div',{class:'inc-truth'});
 d.side=h('section',{class:'panel inc-side','aria-labelledby':'inc-ev-title'},h('div',{class:'panel-heading'},h('h2',{id:'inc-ev-title',text:t('inc.ev')})),
  d.evidence,h('div',{class:'inc-actions'},d.go,d.goWhy,d.runLink),h('div',{class:'inc-csv-row'},d.csv,d.csvWhy),d.truth);
 d.findings=h('div',{class:'table-wrap'});
 d.findingsPanel=incPanel('inc-findings','inc-fd-title',t('inc.fd'),d.findings,h('p',{class:'panel-note',text:t('cc.ev.note')}));
 d.cands=h('div',{class:'inc-cands-body'});
 d.candsPanel=incPanel('inc-cands','inc-cand-title',t('inc.cand'),d.cands);
 d.ops=h('div',{class:'inc-ops-body'});
 d.opsPanel=incPanel('inc-ops','inc-ops-title',t('inc.ops'),d.ops);
 d.dec=h('div',{class:'inc-dec-body'});
 d.decPanel=h('section',{class:'panel inc-dec','aria-labelledby':'inc-dec-title'},h('div',{class:'panel-heading'},h('h2',{id:'inc-dec-title',text:t('dec.title')}),
  h('span',{class:'chip info inc-dec-badge',text:t('dec.badge')})),d.dec);
 d.chain=h('div',{class:'inc-chain-body'});
 d.chainPanel=h('section',{class:'panel inc-chain-panel','aria-labelledby':'inc-chain-title'},h('div',{class:'panel-heading'},h('h2',{id:'inc-chain-title',text:t('chain.title')}),
  h('a',{href:'/report?incident='+encodeURIComponent(incId),id:'inc-chain-report',class:'text-link inc-chain-report',onclick:e=>repOpenLink(e,incId)},t('rep.open'))),d.chain);
 d.error=h('p',{class:'hint bad',role:'alert'});
 d.root=h('div',{class:'inc'},d.live,d.head,d.error,d.stepsPanel,h('div',{class:'inc-main'},d.chartPanel,d.side),d.findingsPanel,h('div',{class:'inc-lower'},d.candsPanel,d.opsPanel),
  h('div',{class:'inc-case'},d.decPanel,d.chainPanel));
 root.replaceChildren(d.root);
 incDom=d;
}

// ---------- updating in place ----------
function incUpdateHead(d,view){
 const inc=view.incident;
 incSection(d.head,JSON.stringify([language,inc.status,inc.severity,inc.opened_t,inc.closed_t,inc.status==='open'?view.now_t:0]),()=>[
  h('div',{class:'inc-head-top'},link('/overview','← '+t('inc.back'),'text-link inc-back'),
   h('div',{class:'inc-head-tools'},h('a',{href:'/report?incident='+encodeURIComponent(inc.id),id:'inc-report-link',class:'secondary inc-report',
    onclick:e=>repOpenLink(e,inc.id)},t('rep.open')),h('span',{class:'cc-sim-badge',title:t('cc.badge.x'),text:t('cc.badge')}))),
  h('div',{class:'inc-head-main'},
   h('div',{class:'inc-title'},h('strong',{class:'inc-id',text:inc.id}),h('span',{class:'inc-sensor',text:ccSensorName(inc.sensor)}),ccSev(inc.severity),
    chip(t('cc.status.'+inc.status),inc.status==='open'?'bad':'muted')),
   h('dl',{class:'inc-facts'},
    h('div',{},h('dt',{text:t('inc.opened')}),h('dd',{},h('span',{text:incAt(inc.opened_t)}),h('small',{text:when(inc.opened_at)}))),
    inc.status==='closed'?h('div',{},h('dt',{text:t('inc.closed')}),h('dd',{},h('span',{text:incAt(inc.closed_t)}),h('small',{text:when(inc.closed_at)}))):null,
    h('div',{},h('dt',{text:t('inc.duration')}),h('dd',{},h('span',{text:incDuration(inc)}),h('small',{text:t(inc.status==='open'?'inc.duration.open':'inc.duration.closed')}))),
    h('div',{},h('dt',{text:t('inc.findings')}),h('dd',{},h('span',{text:N(inc.findings.length)}),h('small',{text:inc.checks.map(ccCheckName).join(', ')}))))),
  h('p',{class:'inc-sim-note',text:t('cc.badge.x')})]);
}
const incStepName=s=>t(s.variant==='decided'?'inc.step.human.recorded':'inc.step.'+s.key);
function incStepMeaning(s,view=incView){
 const p=s.params,key=`inc.step.${s.key}.${s.variant}`;
 if(s.key==='detected')return t(key,{n:N(p.n)});
 if(s.key==='onset'&&s.variant==='done')return t(key,{at:incAt(s.t,view),stat:incStatistic(view.incident.evidence,view)});
 if(s.key==='onset'&&s.variant==='stopped')return t(key,{at:incAt(s.t,view)});
 if(s.key==='evidence')return t(key,{records:N(p.records??0),at:incAt(s.t,view),n:N(p.collected??0),needed:N(p.needed??0)});
 if(s.key==='human'&&s.variant==='decided')return t(key,{decision:t('dec.d.'+p.decision),candidate:p.candidate?' · '+tt('hy.mech.'+p.candidate,p.candidate):'',reviewer:p.reviewer});
 if(s.key==='agents')return t(key,{status:flowLabel('runstatus',p.status),finished:p.finished===null||p.finished===undefined?'—':N(p.finished),selected:p.selected===null||p.selected===undefined?'—':N(p.selected)});
 if(s.key==='judge'&&s.variant==='done')return t(key,{accepted:N(p.accepted),advisory:N(p.advisory),rejected:N(p.rejected)});
 return t(key);
}
function incUpdateSteps(d,view,model){
 incSection(d.steps,JSON.stringify([language,model,view.incident.evidence,view.run?.state]),()=>h('ol',{class:'inc-steps'},model.steps.map((s,i)=>{
  const current=i===model.current,mark=s.state==='done'?'✓':s.state==='blocked'?'–':s.state==='failed'?'!':String(i+1);
  const time=s.t!==null?incAt(s.t):s.at?when(s.at):'';
  const progress=s.key==='evidence'&&s.state==='active'?h('progress',{class:'inc-progress',max:String(s.params.needed||1),value:String(s.params.collected||0),'aria-label':t('inc.progress.label')}):null;
  return h('li',{class:`inc-step ${s.state}`,'aria-current':current?'step':null},
   h('span',{class:'inc-step-mark','aria-hidden':'true',text:mark}),
   h('div',{class:'inc-step-text'},
    h('strong',{text:incStepName(s)}),
    h('span',{class:'inc-step-state',text:t('inc.state.'+s.state)+(time?' · '+time:'')}),
    progress,h('small',{text:incStepMeaning(s)})));
 })));
}
function incUpdateChart(d,view){
 const narrow=!!incNarrow?.matches,s=view.series.t,ev=view.incident.evidence||{};
 const sig=JSON.stringify([language,narrow,s.length,s[0],s[s.length-1],ev,view.incident.truth,view.incident.opened_t,view.now_t]);
 if(d.chart.incSig!==sig){
  d.chart.incSig=sig;
  const {svg,model}=incChartSvg(view);
  d.chart.replaceChildren(svg);d.model=model;
  const key=(cls,text)=>h('li',{},h('span',{class:'inc-key '+cls,'aria-hidden':'true'}),h('span',{text}));
  const texts=incMarkerText(model);
  d.legend.replaceChildren(key('line',t(model.stream?'inc.key.gaps':'inc.key.line',{sensor:ccSensorName(view.incident.sensor)})),
   key('onset',texts[0]),key('injected',texts[1]),key('detected '+view.incident.severity,texts[2]),
   ...(model.window?[key('window',texts[3])]:[]),key(model.band?'band':'none',texts[texts.length-1]));
  ccText(d.chartNote,t(model.stream?'inc.chart.note.stream':'inc.chart.note',{window:N(view.settings.window_seconds),limit:N(view.settings.clear_statistic)}));
 }
 ccText(d.tableSum,t(incTableOpen?'inc.table.hide':'inc.table.show'));
 if(!incTableOpen){if(d.tableBody.firstChild){d.tableBody.replaceChildren();d.tableBody.incSig=null;}return;}
 const m=d.model,dg=incDigits(view);
 incSection(d.tableBody,sig,()=>h('table',{class:'data-table compact inc-data'},
  h('caption',{text:t(m.stream?'inc.table.caption.stream':'inc.table.caption',{n:N(m.count),unit:incUnit(view)})}),
  h('thead',{},h('tr',{},h('th',{scope:'col',text:t('cc.col.time')}),h('th',{scope:'col',text:`${t(m.stream?'inc.col.gap':'inc.col.value')} (${incUnit(view)})`}),h('th',{scope:'col',text:t('inc.col.window')}),h('th',{scope:'col',text:t('inc.col.mark')}))),
  h('tbody',{},m.points.map(p=>{
   const marks=[m.onset?.t===p.t?t('inc.chart.onset.short'):null,m.injected?.t===p.t?t('inc.chart.injected.short'):null,m.detected.t===p.t?t('inc.chart.detected'):null].filter(Boolean);
   return h('tr',{class:m.inWindow(p.t)?'in-window':null},h('th',{scope:'row',text:incAt(p.t)}),h('td',{text:ccNum(p.v,dg)}),h('td',{text:m.inWindow(p.t)?t('inc.yes'):'—'}),h('td',{text:marks.join(', ')||'—'}));
  }))));
}
function incUpdateSide(d,view){
 const inc=view.incident,ev=inc.evidence||{},e=ccEvidence(ev),run=view.run,running=run?.state==='running';
 incSection(d.evidence,JSON.stringify([language,ev,view.baseline_digest]),()=>[
  h('div',{class:'inc-ev-state'},chip(t('inc.ev.state.'+e.state),{ready:'ok',collecting:'info',locating:'info',unavailable:'muted'}[e.state]),
   e.state==='collecting'||e.state==='locating'?h('span',{class:'inc-ev-count',text:t('inc.ev.count',{n:N(e.collected),needed:N(e.needed)})}):null),
  e.state==='collecting'?h('progress',{class:'inc-progress',max:String(e.needed||1),value:String(e.collected),'aria-label':t('inc.progress.label')}):null,
  e.state==='collecting'||e.state==='locating'?h('p',{class:'hint',text:t('inc.ev.why',{window:N(view.settings.window_seconds)})}):null,
  e.state==='unavailable'?h('p',{class:'hint',text:t('inc.ev.unavailable.x')}):null,
  h('dl',{class:'cc-dl inc-dl'},
   h('dt',{text:t('inc.ev.method')}),h('dd',{text:t(incMethodKey(view,ev))}),
   h('dt',{text:t('inc.ev.onset')}),h('dd',{text:ev.onset_t===null||ev.onset_t===undefined?'—':`${incAt(ev.onset_t)} · ${ev.onset_at}`}),
   h('dt',{text:t('inc.ev.statistic')}),h('dd',{text:incStatistic(ev)}),
   h('dt',{text:t('inc.ev.window')}),h('dd',{text:ev.first_t===null||ev.first_t===undefined?'—':t('inc.ev.window.v',{from:incAt(ev.first_t),to:incAt(ev.as_of_t),n:N(e.needed)})}),
   h('dt',{text:t('inc.ev.asof')}),h('dd',{text:ev.as_of||'—'}),
   h('dt',{text:t('inc.ev.records')}),h('dd',{text:ev.records===null||ev.records===undefined?t('inc.ev.notyet'):N(ev.records)}),
   h('dt',{text:t('cc.ev.digest')}),h('dd',{},ev.sha256?incShort(ev.sha256,16):h('span',{text:t('inc.ev.notyet')})),
   h('dt',{text:t('cc.ev.baseline')}),h('dd',{},incShort(view.baseline_digest,16)))]);
 const busy=!!incActive&&!running;
 const goKey=incStarting?'cc.investigating':running?'inc.go.running':'cc.investigate';
 ccText(d.go,t(goKey));
 d.go.disabled=!e.ready||running||busy||incStarting;
 ccText(d.goWhy,e.state==='collecting'?t('inc.go.why.collecting',{n:N(e.collected),needed:N(e.needed)}):e.state==='locating'?t('inc.go.why.locating')
  :e.state==='unavailable'?t('inc.go.why.unavailable'):running?t('inc.go.why.running'):busy?t('cc.investigate.busy'):run?t('inc.go.why.again'):t('inc.go.why.ready'));
 d.goWhy.className='inc-why'+(e.ready&&!running&&!busy?' ok':'');
 incSection(d.runLink,JSON.stringify([language,run?.run_id,run?.state]),()=>run?h('a',{href:'/flow?run='+encodeURIComponent(run.run_id),id:'inc-flow-link',class:'cc-run-link',
  onclick:e2=>ccOpenRun(e2,run.run_id)},t(running?'inc.flow.watch':'inc.flow.open')):null);
 ccText(d.csv,t('inc.csv'));d.csv.disabled=!e.ready;
 ccText(d.csvWhy,e.ready?t('inc.csv.x',{records:N(ev.records),id:inc.id}):t('inc.csv.wait'));
 incSection(d.truth,JSON.stringify([language,inc.truth]),()=>[h('h3',{text:t('inc.truth')}),
  inc.truth?h('dl',{class:'cc-dl inc-dl'},
   h('dt',{text:t('inc.truth.fault')}),h('dd',{text:`${inc.truth.fault_id} · ${t('cc.fault.'+inc.truth.fault)}`}),
   h('dt',{text:t('inc.truth.started')}),h('dd',{text:`${incAt(inc.truth.started_t)} · ${inc.truth.started_at}`}),
   h('dt',{text:t('inc.truth.error')}),h('dd',{text:inc.truth.onset_error_s===null?'—':t('inc.truth.error.v',{n:incSigned(inc.truth.onset_error_s)})}))
   :h('p',{class:'hint',text:t('inc.truth.none')}),
  h('p',{class:'hint',text:t('inc.truth.x')})]);
}
function incUpdateFindings(d,view){
 const inc=view.incident;
 incSection(d.findings,JSON.stringify([language,inc.findings.map(f=>[f.check,f.column,f.first_t])]),()=>h('table',{class:'data-table inc-fd-table'},
  h('caption',{class:'sr-only',text:t('inc.fd.caption',{id:inc.id})}),
  h('thead',{},h('tr',{},...['inc.col.check','inc.col.column','inc.col.severity','inc.col.measured','inc.col.first'].map(k=>h('th',{scope:'col',text:t(k)})))),
  h('tbody',{},inc.findings.map(f=>h('tr',{},h('th',{scope:'row',text:ccCheckName(f.check)}),h('td',{},f.column?h('code',{text:f.column}):'—'),h('td',{},ccSev(f.severity)),
   h('td',{text:ccFindingSentence(f)}),h('td',{},h('span',{text:incAt(f.first_t)}),h('small',{text:t('cc.ev.source.'+f.source)})))))));
}
function incProbeLine(p,ruled){
 const values=p.measured?Object.entries(p.measured).map(([k,v])=>`${tt('hy.m.'+k,k)} ${v===null?t('hy.m.undefined'):ccNum(v,3)}`).join(', '):null;
 const head=t('hy.probe.'+p.probe)+(p.column?' · '+p.column:'');
 const text=p.outcome?t('inc.probe.'+p.outcome,{probe:head}):t('inc.probe.mixed',{probe:head,n:N(p.concerned),s:N(p.supports),r:N(p.refutes),u:N(p.neutral)});
 return h('li',{class:'inc-probe '+(p.outcome?HY_OUTCOME_STATUS[p.outcome]:'mixed')},p.outcome?hyIcon(HY_OUTCOME_STATUS[p.outcome]):null,
  h('div',{},h('span',{text:text}),h('small',{text:values?t('inc.probe.values',{values}):t('inc.probe.novalues')}),ruled.has(p.probe)?null:(ruled.add(p.probe),h('small',{class:'inc-rule',text:t('inc.rule.'+p.probe)}))));
}
function incUpdateCands(d,view,detail,live){
 const run=view.run,c=incCandidates(detail?.record,view.investigation),ops=incOps(run,detail?.record,live);
 incSection(d.cands,JSON.stringify([language,run?.run_id,run?.state,!!detail?.record,ops?.finished,ops?.selected,view.investigation?.ref?.id]),()=>{
  if(!run)return h('div',{class:'empty-state'},h('strong',{text:t('inc.cand.none.t')}),h('span',{text:t('inc.cand.none.x')}));
  if(run.state==='running')return h('div',{class:'inc-cand-live'},h('p',{class:'inc-live-line',text:ops?.selected?t('inc.cand.running',{finished:N(ops.finished),selected:N(ops.selected)}):t('inc.cand.starting')}),
   h('a',{href:'/flow?run='+encodeURIComponent(run.run_id),id:'inc-cand-flow',class:'cc-run-link',onclick:e=>ccOpenRun(e,run.run_id)},t('inc.flow.watch')));
  if(run.state==='error')return h('p',{class:'hint bad',text:t('inc.cand.error')});
  if(!c)return h('p',{class:'hint',text:t('inc.cand.loading')});
  const parts=[h('p',{class:'inc-statement',text:t('hy.statement')})];
  if(!c.ran||!c.candidates.length)parts.push(h('p',{class:'hint',text:c.error?t('inc.cand.a24',{code:flowLabel('code',c.error)}):t('flow.story.candidates.none')}));
  else{
   const ruled=new Set();
   parts.push(h('div',{class:'inc-cand-sum'},c.verdict?chip(t('hy.verdict.'+c.verdict),'info'):null,
    h('span',{text:t('inc.cand.counts',{s:N(c.counts.supported),o:N(c.counts.open),r:N(c.counts.refuted)})}),
    c.used!==null?h('span',{text:t('hy.budget',{used:N(c.used),max:N(c.max)})}):null),
    h('ol',{class:'inc-cand-list'},c.candidates.map(x=>h('li',{class:'inc-cand '+x.status},
     h('div',{class:'inc-cand-head'},h('strong',{text:incMech(x)}),hyStatus(x.status)),
     h('p',{class:'inc-cand-plain',text:t('inc.cand.plain.'+x.status,{mech:incMech(x)})}),
     h('p',{class:'hint',text:t('hy.mech.'+x.mechanism+'.x')}),
     x.probes.length?h('ul',{class:'inc-probes'},x.probes.map(p=>incProbeLine(p,ruled))):h('p',{class:'hint',text:t(x.mechanism==='genuine_change'?'hy.ev.untestable':'hy.ev.none')})))),
    c.stop?h('p',{class:'hint',text:t('hy.stop.'+c.stop)}):null,h('p',{class:'hint',text:t('hy.hyp.legend')}),
    c.verified?h('p',{class:'inc-verified'},hyIcon('supported'),h('span',{text:t('inc.verified',{ref:c.verified.sha256.slice(0,12)})}))
     :h('p',{class:'hint',text:t('inc.unverified')}));
  }
  const mdl=c.model;
  parts.push(h('div',{class:'inc-model'},h('div',{class:'inc-model-head'},h('h3',{text:t('inc.model')}),chip(t('inc.advisory'),'info')),
   !mdl?h('p',{class:'hint',text:t('flow.story.model.none')})
   :mdl.mechanisms===null?h('p',{class:'hint',text:t('inc.model.none',{code:flowLabel('code',mdl.error)})})
   :[h('p',{text:t('inc.model.suggested',{list:incList(mdl.mechanisms)})}),
    mdl.compared?h('ul',{class:'inc-agree'},
     h('li',{class:'agreed'},h('b',{text:t('inc.model.agreed')}),h('span',{text:incList(mdl.compared.agreed)})),
     h('li',{class:'model_only'},h('b',{text:t('inc.model.only')}),h('span',{text:incList(mdl.compared.modelOnly)})),
     h('li',{class:'rule'},h('b',{text:t('inc.model.rule')}),h('span',{text:incList(mdl.compared.ruleSupported)})))
     :h('p',{class:'hint',text:t('inc.model.nocompare')}),
    h('p',{class:'hint',text:t('inc.model.judge',{verdict:mdl.verdict?t('flow.verdict.'+mdl.verdict):t('flow.verdict.none')})})]));
  parts.push(h('div',{class:'inc-judge'},h('h3',{text:t('inc.judge')}),
   h('ul',{class:'inc-judge-counts'},['accepted','advisory','rejected'].map(k=>h('li',{class:k},h('strong',{text:N(c.judge[k])}),h('span',{text:t('flow.verdict.'+k)})))),
   h('p',{class:'hint',text:t('inc.judge.x')})));
  return parts;
 });
}
function incUpdateOps(d,view,detail,live){
 const run=view.run,ops=incOps(run,detail?.record,live);
 incSection(d.ops,JSON.stringify([language,run,ops]),()=>{
  if(!run)return h('p',{class:'hint',text:t('inc.ops.none')});
  const state=run.state==='running'?[t('cc.run.running'),'info']:run.state==='error'?[t('cc.run.error'),'bad']:[flowLabel('runstatus',run.status),run.status==='completed'?'ok':'warn'];
  const tile=(key,value,sub)=>h('div',{class:'inc-op'},h('span',{text:t('inc.op.'+key)}),h('strong',{text:value}),sub?h('small',{text:sub}):null);
  const n=v=>v===null||v===undefined?'—':N(v);
  return [h('div',{class:'inc-ops-head'},chip(state[0],state[1]),h('code',{title:run.run_id,text:run.run_id}),h('small',{text:when(run.started_at)})),
   h('div',{class:'inc-op-grid'},
    tile('agents',ops?.selected===null||!ops?`${n(ops?.finished)}`:`${n(ops.finished)} / ${n(ops.selected)}`,t('inc.op.agents.x')),
    tile('completed',n(ops?.completed),t('inc.op.completed.x',{needs:n(ops?.needs),failed:n(ops?.failed)})),
    tile('llm',n(ops?.llm),ops?.tokens!==null&&ops?.tokens!==undefined?t('inc.op.tokens',{n:N(ops.tokens)}):null),
    tile('duration',ops?.ms===null||ops?.ms===undefined?'—':msText(ops.ms),t('inc.op.events',{n:n(ops?.events)}))),
   h('a',{href:'/flow?run='+encodeURIComponent(run.run_id),id:'inc-ops-flow',class:'cc-run-link',onclick:e=>ccOpenRun(e,run.run_id)},t(run.state==='running'?'inc.flow.watch':'inc.flow.open')),
   h('p',{class:'panel-note',text:t('inc.ops.note')})];
 });
}
// ---------- case file: evidence chain ----------
async function incLoadCase(sig){
 const id=incId;incCaseSig=sig;
 try{
  const cf=await request(`/api/plant/incidents/${encodeURIComponent(id)}/case`);
  if(id===incId){incCase=cf;incCaseError='';}
 }catch(error){if(id===incId){incCaseError=error.message;incCaseSig=null;}}
 incPaintSoon();
}
const INC_KIND_ICON={baseline:'M2.5 4.5h11M2.5 8h11M2.5 11.5h11',evidence:'M5.5 2.5h-3v11h3M10.5 2.5h3v11h-3M6 8h4',
 probes:'M7 2.8a4.2 4.2 0 1 0 0 8.4a4.2 4.2 0 1 0 0-8.4M10 10l3.5 3.5',
 agent_run:'M4 3a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M12 3a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M8 10.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3M5.5 4.5h5M4.8 5.8 7.3 10.6M11.2 5.8 8.7 10.6',
 decision:'M8 2.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5M3 13.5c.4-2.8 2.4-4.2 5-4.2s4.6 1.4 5 4.2'};
function incKindIcon(kind){
 const svg=svgEl('svg',{viewBox:'0 0 16 16',class:'bl-icon inc-kind-icon','aria-hidden':'true',focusable:'false'});
 svg.append(svgEl('path',{d:INC_KIND_ICON[kind]}));return svg;
}
// Status is text plus a shape: check (verified), cross (mismatch), dashed circle (missing).
const INC_CHAIN_SHAPE={verified:'supported',mismatch:'refuted',missing:'open'};
const incChainStatus=status=>h('span',{class:'inc-chain-status '+status},hyIcon(INC_CHAIN_SHAPE[status]),t('chain.status.'+status));
// One recorded value of a link, formatted for the page language.
function incFactText(f,view){
 const v=f.value;
 if(v===null||v===undefined)return '—';
 switch(f.type){
  case 'n':return N(v);
  case 'span':return t('chain.window.v',{from:incAt(v[0],view),to:incAt(v[1],view)});
  case 't':return incAt(v,view);
  case 'stat':return ccNum(v,1);
  case 'method':return t(incMethodKey(view,{method:v}));
  case 'verdict':return tt('hy.verdict.'+v,v);
  case 'mechs':return incList(v);
  case 'mech':return tt('hy.mech.'+v,v);
  case 'runstatus':return flowLabel('runstatus',v);
  case 'judge':return t('chain.judge.v',{accepted:N(v.accepted),advisory:N(v.advisory),rejected:N(v.rejected)});
  case 'bool':return t(v?'chain.yes':'chain.no');
  case 'decision':return t('dec.d.'+v);
 }
 return String(v);
}
function incChainBannerText(b){
 const steps=b.kinds.map(k=>t('chain.kind.'+k)).join(', ');
 if(b.state==='waiting')return t('chain.banner.waiting',{steps});
 if(b.state==='mismatch')return t('chain.banner.mismatch',{steps});
 return t('chain.banner.'+b.state);
}
const INC_BANNER_SHAPE={complete:'supported',waiting:'open',mismatch:'refuted',broken:'refuted',loading:'open'};
const incChainBannerEl=b=>h('p',{class:'inc-chain-banner '+b.state},hyIcon(INC_BANNER_SHAPE[b.state]),h('strong',{text:incChainBannerText(b)}));
function incChainList(cf,view){
 const links=incChainLinks(cf);
 return h('ol',{class:'inc-chain','aria-label':t('chain.list.label',{n:N(links.length)})},links.map(l=>{
  const facts=incLinkFacts(l.kind,l.link?.summary);
  return h('li',{class:'inc-link '+l.status},
   h('span',{class:'inc-link-icon'},incKindIcon(l.kind)),
   h('div',{class:'inc-link-body'},
    h('div',{class:'inc-link-head'},h('strong',{text:t('chain.step.n',{n:N(l.index+1)})+' · '+t('chain.kind.'+l.kind)}),incChainStatus(l.status),
     l.link?h('time',{datetime:l.link.at,text:incLinkTime(l.link)}):null),
    l.link?h('dl',{class:'inc-link-facts'},facts.map(f=>h('div',{},h('dt',{text:t('chain.f.'+f.key)}),h('dd',{text:incFactText(f,view)}))))
     :h('p',{class:'hint',text:t('chain.missing.x')}),
    l.status==='mismatch'?h('p',{class:'inc-link-reason',text:tt('chain.reason.'+l.reason,t('chain.reason.unknown'))}):null,
    l.link?h('p',{class:'inc-link-hash'},h('span',{text:t('chain.digest')}),incShort(l.link.digest),h('span',{text:t('chain.link')}),incShort(l.link.link_sha256)):null));
 }));
}
function incUpdateChain(d,view){
 const banner=incChainBanner(incCase);
 incSection(d.chain,JSON.stringify([language,incCase?.content_sha256??null,incCase?.head??null,incCaseError,banner,view.live_start_t]),()=>[
  incCaseError&&!incCase?h('div',{class:'inc-chain-error'},h('p',{class:'hint bad',role:'alert',text:t('chain.banner.error',{reason:incCaseError})}),
   h('button',{type:'button',class:'secondary',id:'inc-chain-retry',onclick:()=>{incCaseError='';if(incView)incLoadCase(incCaseKey(incView));incPaint();}},t('chain.retry'))):null,
  incChainBannerEl(banner),
  h('p',{class:'inc-chain-x',text:t('chain.x')}),
  incCase?incChainList(incCase,view):null,
  incCase?h('p',{class:'inc-chain-foot'},h('span',{text:t('chain.head')}),incShort(incCase.head,16),h('span',{text:t('chain.content')}),incShort(incCase.content_sha256,16)):null]);
 const sig=banner.state+':'+banner.kinds.join(',');
 if(incCase&&incLastBanner!==null&&incLastBanner!==sig)incAnnounce(incChainBannerText(banner));
 if(incCase)incLastBanner=sig;
}

// ---------- case file: human decision ----------
const incDetailNow=()=>incDetail?.run_id===incView?.run?.run_id?incDetail:null;
const INC_DECISION_TONE={accepted:'ok',rejected:'bad',more_evidence:'warn'};
async function incDecide(event){
 event?.preventDefault();
 if(!incView||incSubmitting||!requireSession())return;
 const id=incId,model=incDecisionModel(incView,incDetailNow()),input=incDecisionInput(incForm,model);
 incDecErrors=input.errors;incDecError='';
 if(!input.ok){incPaint();incFocusInvalid();return;}
 incSubmitting=true;incPaint();
 try{
  const cf=await request(`/api/plant/incidents/${encodeURIComponent(id)}/decision`,'POST',JSON.stringify(input.body),JSON_HEADERS);
  if(id===incId){
   incCase=cf;incForm.note='';
   const text=t('dec.saved',{id,decision:t('dec.d.'+input.body.decision)});
   setNotice(text);incAnnounce(text);
  }
 }catch(error){
  const x=incDecisionError(error);
  incDecError=x.key==='cc.err.notready'?t(x.key,{n:N(x.params.n??0),needed:N(x.params.needed??0)}):x.key?t(x.key,x.params):error.message;
  setNotice(incDecError,true);
 }
 incSubmitting=false;
 while(incInflight)await new Promise(resolve=>setTimeout(resolve,50)); // a poll already in flight may predate the decision
 await incFetch();incPaint();
 if(incDecError)document.getElementById('inc-dec-submit')?.focus({preventScroll:true});
 if(incNeedsPoll(incView))incSchedule();
}
function incFocusInvalid(){
 const e=incDecErrors,first=e.decision?document.querySelector('input[name="inc-dec-decision"]:not(:disabled)')
  :e.candidate?document.querySelector('input[name="inc-dec-candidate"]'):e.reviewer?$('inc-dec-reviewer'):e.note?$('inc-dec-note'):null;
 first?.focus();
}
function incDecisionCard(dec){
 return h('div',{class:'inc-dec-card '+dec.decision},
  h('div',{class:'inc-dec-card-head'},h('span',{class:'inc-dec-label',text:t('dec.current')}),chip(t('dec.d.'+dec.decision),INC_DECISION_TONE[dec.decision])),
  dec.candidate?h('p',{class:'inc-dec-cand'},h('span',{text:t('dec.f.candidate')}),h('strong',{text:tt('hy.mech.'+dec.candidate,dec.candidate)})):null,
  h('dl',{class:'cc-dl inc-dl'},
   h('dt',{text:t('dec.f.reviewer')}),h('dd',{text:dec.reviewer}),
   h('dt',{text:t('dec.f.at')}),h('dd',{},h('time',{datetime:dec.decided_at,text:when(dec.decided_at)})),
   dec.note?[h('dt',{text:t('dec.f.note')}),h('dd',{class:'inc-dec-note-text',text:dec.note})]:null,
   h('dt',{text:t('dec.f.run')}),h('dd',{},h('code',{text:dec.run_id})),
   h('dt',{text:t('dec.f.executed')}),h('dd',{text:t('dec.executed.no')}),
   h('dt',{text:t('dec.f.digest')}),h('dd',{},incShort(dec.sha256,16))));
}
function incDecisionHistory(list){
 const box=h('details',{class:'inc-dec-history',ontoggle:e=>{incHistoryOpen=e.target.open;}},h('summary',{id:'inc-dec-hist-sum',text:t('dec.history',{n:N(list.length)})}),
  h('ol',{class:'inc-dec-versions'},[...list].reverse().map((v,i)=>h('li',{},
   h('div',{class:'inc-dec-v-head'},h('strong',{text:t('dec.history.v',{n:N(list.length-i)})}),chip(t('dec.d.'+v.decision),INC_DECISION_TONE[v.decision]),
    i===0?h('small',{text:t('dec.history.latest')}):null),
   h('span',{text:[v.candidate?tt('hy.mech.'+v.candidate,v.candidate):null,v.reviewer,when(v.decided_at)].filter(Boolean).join(' · ')}),
   v.note?h('small',{class:'inc-dec-note-text',text:v.note}):null,
   h('small',{},h('span',{text:t('dec.f.digest')+' '}),incShort(v.sha256,16))))));
 box.open=incHistoryOpen;
 return box;
}
function incDecisionForm(model){
 if(incForm.decision&&!model.options.find(o=>o.value===incForm.decision)?.enabled)incForm.decision=null;
 if(incForm.candidate&&!model.candidates.some(c=>c.mechanism===incForm.candidate))incForm.candidate=null;
 if(model.candidates.length===1&&!incForm.candidate)incForm.candidate=model.candidates[0].mechanism;
 const E=incDecErrors;
 const err=field=>E[field]?h('p',{id:`inc-dec-${field}-err`,class:'inc-dec-err',text:t(`dec.err.${field}.${E[field]}`)}):null;
 const describe=(field,...ids)=>[...ids,E[field]?`inc-dec-${field}-err`:null].filter(Boolean).join(' ')||null;
 const cands=h('fieldset',{class:'inc-dec-cands',id:'inc-dec-cands',hidden:incForm.decision!=='accepted','aria-describedby':describe('candidate','inc-dec-cands-x')},
  h('legend',{text:t('dec.cand.legend')}),h('p',{id:'inc-dec-cands-x',class:'hint',text:t('dec.cand.x')}),
  model.candidates.map((c,i)=>h('label',{class:'inc-dec-choice'},
   h('input',{type:'radio',name:'inc-dec-candidate',id:'inc-dec-c-'+i,value:c.mechanism,checked:incForm.candidate===c.mechanism,onchange:()=>{incForm.candidate=c.mechanism;}}),
   h('span',{},h('strong',{text:tt('hy.mech.'+c.mechanism,c.mechanism)}),c.columns.length?h('small',{text:t('dec.cand.columns',{columns:c.columns.join(', ')})}):null))),
  err('candidate'));
 const choices=h('fieldset',{class:'inc-dec-choices','aria-describedby':describe('decision')},h('legend',{text:t('dec.legend')}),
  model.options.map(o=>h('label',{class:'inc-dec-choice '+o.value+(o.enabled?'':' disabled')},
   h('input',{type:'radio',name:'inc-dec-decision',id:'inc-dec-d-'+o.value,value:o.value,checked:incForm.decision===o.value,disabled:!o.enabled,
    'aria-describedby':`inc-dec-d-${o.value}-x`,onchange:()=>{incForm.decision=o.value;cands.hidden=o.value!=='accepted';}}),
   h('span',{},h('strong',{text:t('dec.d.'+o.value)}),h('small',{id:`inc-dec-d-${o.value}-x`,text:o.reason?t('dec.accepted.none'):t(`dec.d.${o.value}.x`)})))),
  err('decision'));
 const note=h('textarea',{id:'inc-dec-note',name:'note',rows:'3',maxlength:String(INC_NOTE_MAX),'aria-invalid':E.note?'true':null,'aria-describedby':describe('note','inc-dec-note-count'),
  oninput:e=>{incForm.note=e.target.value;ccText(count,t('dec.note.count',{n:N([...incForm.note].length),max:N(INC_NOTE_MAX)}));}});
 note.value=incForm.note;
 const count=h('p',{id:'inc-dec-note-count',class:'inc-dec-count',text:t('dec.note.count',{n:N([...incForm.note].length),max:N(INC_NOTE_MAX)})});
 return h('form',{class:'inc-dec-form',novalidate:true,onsubmit:incDecide},choices,cands,
  h('div',{class:'inc-dec-field'},h('label',{for:'inc-dec-reviewer',text:t('dec.reviewer')}),
   h('input',{type:'text',id:'inc-dec-reviewer',name:'reviewer',maxlength:String(INC_REVIEWER_MAX),autocomplete:'name',required:true,value:incForm.reviewer,
    'aria-invalid':E.reviewer?'true':null,'aria-describedby':describe('reviewer','inc-dec-reviewer-x'),oninput:e=>{incForm.reviewer=e.target.value;}}),
   h('p',{id:'inc-dec-reviewer-x',class:'hint',text:t('dec.reviewer.x')}),err('reviewer')),
  h('div',{class:'inc-dec-field'},h('label',{for:'inc-dec-note',text:t('dec.note')}),note,count,err('note')),
  h('div',{class:'inc-dec-actions'},
   h('button',{type:'submit',id:'inc-dec-submit',class:'primary inc-dec-submit',disabled:incSubmitting,'aria-describedby':'inc-dec-submit-x'},
    t(incSubmitting?'dec.submitting':model.current?'dec.submit.again':'dec.submit')),
   h('p',{id:'inc-dec-submit-x',class:'hint',text:t('dec.submit.x')})),
  incDecError?h('p',{class:'hint bad inc-dec-status',role:'alert',text:incDecError}):null);
}
function incUpdateDecision(d,view,detail){
 const model=incDecisionModel(view,detail),history=incCase?.decisions||[];
 incSection(d.dec,JSON.stringify([language,model,history.map(x=>x.sha256),incSubmitting,incDecErrors,incDecError]),()=>[
  h('p',{class:'inc-dec-intro',text:t('dec.intro')}),
  h('p',{class:'inc-dec-meaning',text:t('dec.accept.meaning')}),
  model.current?incDecisionCard(model.current):h('p',{class:'hint inc-dec-none',text:t('dec.current.none')}),
  model.other?h('p',{class:'hint inc-dec-other',text:t('dec.other.run',{decision:t('dec.d.'+model.other.decision),run:model.other.run_id})}):null,
  model.ready?incDecisionForm(model):h('div',{class:'empty-state inc-dec-wait'},h('strong',{text:t('dec.wait.t')}),h('span',{text:t('dec.wait.'+model.wait)})),
  history.length?incDecisionHistory(history):null]);
}
function incPaint(){
 const root=typeof document!=='undefined'?$('screen-incident'):null;
 if(!root||route!=='/incident')return;
 if(typeof refreshBrief==='function')refreshBrief();
 const back=()=>link('/overview',t('inc.back'),'secondary route');
 if(!connected){incDom=null;root.replaceChildren(h('section',{class:'panel'},empty('inc.connect.t','inc.connect.x')));return;}
 if(!incId||incMissing){incDom=null;root.replaceChildren(h('section',{class:'panel'},h('div',{class:'empty-state'},h('strong',{text:t('inc.missing.t',{id:incId||'—'})}),h('span',{text:t('inc.missing.x')}),back())));return;}
 if(!incView){incDom=null;root.replaceChildren(h('section',{class:'panel'},incError?h('p',{class:'hint bad',role:'alert',text:incError}):empty('inc.loading.t','inc.loading.x')));return;}
 const active=document.activeElement,activeId=active&&root.contains(active)?active.id:null;
 if(!incDom||incDom.lang!==language||incDom.id!==incId||!root.contains(incDom.root))incBuild(root);
 const d=incDom,view=incView,detail=incDetail?.run_id===view.run?.run_id?incDetail:null,live=incLiveRun===view.run?.run_id?incLive:null;
 const model=incSteps(view,detail,live);
 incUpdateHead(d,view);incUpdateSteps(d,view,model);incUpdateChart(d,view);incUpdateSide(d,view);incUpdateFindings(d,view);
 incUpdateCands(d,view,detail,live);incUpdateOps(d,view,detail,live);incUpdateDecision(d,view,detail);incUpdateChain(d,view);
 ccText(d.error,incError);d.error.hidden=!incError;
 const step=model.steps[model.current];
 const sig=view.incident.id+':'+(step?step.key+step.state:'');
 if(incLastStep!==null&&incLastStep!==sig&&step)incAnnounce(t('inc.live.step',{id:view.incident.id,step:t('inc.step.'+step.key),state:t('inc.state.'+step.state)}));
 incLastStep=sig;
 if(activeId&&document.activeElement!==document.getElementById(activeId))document.getElementById(activeId)?.focus({preventScroll:true});
}
// Called by the router for /incident: reads ?id=, paints, and keeps the once-per-second poll running while needed.
function renderIncident(){
 const raw=typeof location!=='undefined'?new URLSearchParams(location.search).get('id'):null,id=raw&&INC_ID.test(raw)?raw:null;
 if(id!==incId||(raw&&!id)){
  incStop();incId=id;incView=null;incDetail=null;incLive=null;incLiveRun=null;incError='';incMissing=!!raw&&!id;incActive=null;incDom=null;incLastStep=null;
  incCase=null;incCaseSig=null;incCaseError='';incLastBanner=null;incSubmitting=false;incDecErrors={};incDecError='';
  Object.assign(incForm,{decision:null,candidate:null,note:''}); // the reviewer name is kept: the same person reviews the next incident
 }
 incPaint();
 if(connected&&incId&&!incTimer&&!incInflight)incSchedule(0);
}
function incidentBrief(){
 const detail=incDetailNow(),live=incLiveRun===incView?.run?.run_id?incLive:null;
 const b=incBrief({connected,id:incId,missing:incMissing,view:incView,error:incError,detail,live});
 const fmt=p=>Object.fromEntries(Object.entries(p).map(([k,v])=>[k,k==='status'?t('cc.status.'+v):k==='decision'?t('dec.d.'+v):typeof v==='number'?N(v):v]));
 return {happened:t(b.happened.key,fmt(b.happened.params)),next:t(b.next.key,fmt(b.next.params))};
}
if(typeof document!=='undefined'){
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')incStop();else if(incWanted())incSchedule(0);});
 incNarrow?.addEventListener?.('change',()=>{if(route==='/incident')incPaint();});
}
