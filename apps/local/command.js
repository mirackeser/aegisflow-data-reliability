'use strict';
// Command Center: a live view of the simulated plant (aegisflow_dr.simulation, driven by apps/local/plant.py).
// Every number on this page comes from /api/plant/state: the simulator's readings, its baseline, the monitor's window
// checks and incidents, and aggregates over the retained agent run records. The plant is labelled as a simulation
// everywhere it appears. The chart, KPI, guide and finding helpers are pure and tested in Node (test_command.cjs).

// ---------- pure core (also used by test_command.cjs) ----------
const CC_SENSORS=['temp_c','pressure_kpa','flow_lpm'];
const CC_DIGITS={temp_c:2,pressure_kpa:2,flow_lpm:2};
const CC_CHART={w:640,h:172,l:54,r:14,t:24,b:24};
const CC_CHART_NARROW={w:360,h:156,l:46,r:10,t:24,b:22}; // phones: a smaller viewBox keeps the text at reading size
const CC_GAP_S=3; // a longer gap between readings breaks the line (ingestion pause), so gaps are never drawn over
const CC_SEVERITIES=['low','medium','high'];
const CC_OUTCOMES=['COMPLETED','NEEDS_EVIDENCE','POLICY_DENIED','SKIPPED','FAILED'];
const CC_LAYERS=['orchestration','specialists','reasoning','remediation','governance'];

function ccNiceStep(span,count=4){
 const raw=span/Math.max(1,count),p=10**Math.floor(Math.log10(raw)),f=raw/p;
 return (f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10)*p;
}
// y domain over the readings and the baseline band, extended to whole tick steps.
function ccDomain(values,band){
 let lo=Math.min(...values,band?band.low:Infinity),hi=Math.max(...values,band?band.high:-Infinity);
 if(!Number.isFinite(lo)||!Number.isFinite(hi)){lo=0;hi=1;}
 if(hi-lo<1e-9){lo-=1;hi+=1;}
 const step=ccNiceStep(hi-lo),min=Math.floor(lo/step)*step,max=Math.ceil(hi/step)*step,ticks=[];
 for(let v=min;v<=max+step/2;v+=step)ticks.push(+v.toFixed(10));
 return {min,max,step,ticks};
}
// mm:ss (or h:mm:ss) of a number of seconds, signed when negative.
function ccClock(seconds){
 const s=Math.abs(Math.round(seconds)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60,pad=n=>String(n).padStart(2,'0');
 return (seconds<0?'−':'')+(h?`${h}:${pad(m)}:${pad(r)}`:`${pad(m)}:${pad(r)}`);
}
// A simulated second as time since the live start: T+04:12 (the commissioning period is T−).
const ccRel=(t,liveStart)=>'T'+(t<liveStart?'':'+')+ccClock(t-liveStart);
const ccSeverityMax=list=>list.reduce((a,b)=>CC_SEVERITIES.indexOf(b)>CC_SEVERITIES.indexOf(a)?b:a,'low');

// The "focus" axis range: the baseline band widened by half its width on each side.
function ccFocusRange(band){
 const width=band.high-band.low>0?band.high-band.low:Math.max(Math.abs(band.mean)*0.01,1);
 return {low:band.low-width/2,high:band.high+width/2};
}
const CC_SCALE_RATIO=3,CC_CLIP_SPACING=9;
// Geometry of one sensor chart: the line (broken at gaps), the baseline band, detection markers and fault spans.
// ``opts.focus`` clamps the y axis to the focus range: readings outside it are not drawn as line but marked by an
// arrow glyph at the edge they leave through (thinned to one glyph per CC_CLIP_SPACING px). Without focus the axis
// fits every reading; ``scale.changed`` says it had to grow far beyond the band (e.g. after a ×10 unit fault).
function ccChartModel(state,sensor,size={},opts={}){
 const C={...CC_CHART,...size},span=state.settings.chart_readings;
 const points=state.series.t.map((t,i)=>({t,v:state.series[sensor][i]})).sort((a,b)=>a.t-b.t);
 const t1=points.length?points[points.length-1].t:0,t0=t1-span+1;
 const visible=points.filter(p=>p.t>=t0),band=state.baseline.bands[sensor],range=ccFocusRange(band);
 const outsideFocus=visible.some(p=>p.v<range.low||p.v>range.high),focus=!!opts.focus;
 const dom=focus?ccDomain([],range):ccDomain(visible.map(p=>p.v),band);
 const x=t=>C.l+(t-t0)/Math.max(1,t1-t0)*(C.w-C.l-C.r),y=v=>C.t+(1-(v-dom.min)/(dom.max-dom.min))*(C.h-C.t-C.b);
 const out=v=>v<dom.min||v>dom.max;
 let path='',prev=null;const clipped=[],last={up:-Infinity,down:-Infinity};let clippedCount=0;
 for(const p of visible){
  if(out(p.v)){
   clippedCount++;const dir=p.v>dom.max?'up':'down',px=x(p.t);
   if(px-last[dir]>=CC_CLIP_SPACING){clipped.push({t:p.t,x:px,dir});last[dir]=px;}
   prev=null;continue;
  }
  path+=(prev===null||p.t-prev>CC_GAP_S?'M':'L')+x(p.t).toFixed(1)+' '+y(p.v).toFixed(1);prev=p.t;
 }
 const groups=new Map();
 for(const d of state.detections||[]){
  const own=d.column===sensor,stream=!CC_SENSORS.includes(d.column);
  if((!own&&!stream)||d.t<t0||d.t>t1)continue;
  const g=groups.get(d.t)||{t:d.t,x:x(d.t),checks:[],severity:'low',stream:true,incidents:[]};
  g.checks.push(d.check);g.severity=ccSeverityMax([g.severity,d.severity]);g.stream=g.stream&&stream;
  if(!g.incidents.includes(d.incident))g.incidents.push(d.incident);
  groups.set(d.t,g);
 }
 const faults=[];
 for(const f of state.faults||[]){
  if(f.sensor!==sensor&&f.sensor!==null)continue;
  const from=Math.max(f.started_t,t0),to=Math.min(f.ended_t??t1,t1);
  if(to<from)continue;
  faults.push({id:f.id,fault:f.fault,x:x(from),w:Math.max(2,x(to)-x(from)),active:f.ended_t===null,oneShot:!!f.one_shot,stream:f.sensor===null});
 }
 const latest=visible.length?visible[visible.length-1]:null,top=C.t,bottom=C.h-C.b;
 return {width:C.w,height:C.h,plot:{l:C.l,r:C.w-C.r,t:top,b:bottom},t0,t1,path,count:visible.length,domain:dom,focus,
  scale:{changed:!focus&&outsideFocus&&dom.max-dom.min>=CC_SCALE_RATIO*(range.high-range.low),available:focus||outsideFocus,range},
  clipped,clippedCount,
  band:{top:y(band.high),bottom:y(band.low),mean:y(band.mean),low:band.low,high:band.high},
  yTicks:dom.ticks.map(v=>({v,y:y(v)})),xTicks:[0,100,200,span-1].filter(a=>a<span).map(a=>({ago:a,x:x(t1-a)})),
  markers:[...groups.values()].sort((a,b)=>a.t-b.t),faults,latest,dot:latest?{x:x(latest.t),y:Math.max(top,Math.min(bottom,y(latest.v))),clipped:out(latest.v)}:null,
  min:visible.length?Math.min(...visible.map(p=>p.v)):null,max:visible.length?Math.max(...visible.map(p=>p.v)):null,
  outside:latest?latest.v<band.low||latest.v>band.high:false};
}

// KPI tiles from the state: raw values, n/a flags and tones; the page formats them.
function ccKpis(state){
 const k=state.kpis,open=state.incidents.filter(i=>i.status==='open'),high=open.some(i=>i.severity==='high');
 return [
  {key:'active',value:k.active_incidents,kind:'count',tone:k.active_incidents?(high?'bad':'warn'):'ok',params:{n:k.incidents}},
  {key:'detections',value:k.detections,kind:'count',tone:k.detections?'warn':'',params:{n:k.checks}},
  {key:'investigations',value:k.investigations,kind:'count',tone:'',params:{n:k.investigations_from_plant}},
  {key:'judge',value:k.judge_acceptance,kind:'percent',na:k.judge_acceptance===null,tone:k.judge_acceptance===null?'':'ok',params:{a:k.judge_accepted,v:k.judge_verdicts}},
  {key:'median',value:k.median_investigation_ms,kind:'ms',na:k.median_investigation_ms===null,tone:'',params:{n:k.investigations}},
  {key:'points',value:k.data_points,kind:'count',tone:'',params:{n:k.readings}}];
}

// Where the operator is in the demo loop: start -> inject -> investigate, and the one thing to do next.
function ccGuide(state,isConnected=true){
 if(!isConnected||!state)return {step:'connect',done:{start:false,inject:false,investigate:false},incident:null};
 const rank=i=>CC_SEVERITIES.indexOf(i.severity);
 const open=state.incidents.filter(i=>i.status==='open').sort((a,b)=>rank(b)-rank(a)||b.opened_t-a.opened_t);
 // An open incident whose evidence is ready comes first (only closed incidents can lack evidence for good).
 const evidence=i=>i.evidence?.state??'ready',waiting=open.filter(i=>!i.run_id);
 const pending=waiting.find(i=>evidence(i)==='ready')||waiting[0]||null,started=open.find(i=>i.run_id)||null;
 const done={start:state.status.running||state.elapsed_s>0,inject:state.faults.length>0,investigate:state.incidents.some(i=>i.run_id)};
 const active=state.faults.some(f=>f.ended_t===null);
 let step;
 if(pending)step=evidence(pending)==='ready'?'investigate':'collect';
 else if(!state.status.running)step=state.elapsed_s>0?'resume':'start';
 else if(started)step='review';
 else if(active||(state.faults.length&&!state.incidents.length))step='wait';
 else step='inject';
 return {step,done,incident:pending||started};
}

// Agent outcomes per layer from the retained-run summary, as stacked-bar segments.
function ccLayerBars(layers){
 return CC_LAYERS.map(layer=>{
  const counts=layers?.[layer]||{},total=CC_OUTCOMES.reduce((n,s)=>n+(counts[s]||0),0);
  return {layer,total,segments:CC_OUTCOMES.map(status=>({status,count:counts[status]||0,share:total?(counts[status]||0)/total:0})).filter(s=>s.count)};
 });
}

// One plain sentence per finding: a string key and its parameters.
function ccFindingText(f){
 const d=f.detail||{},first=(d.records||[])[0];
 switch(f.check){
  case 'distribution_shift':return {key:'cc.fd.distribution_shift',params:{psi:d.psi,threshold:d.threshold,before:d.baseline_mean,after:d.current_mean}};
  case 'level_shift':case 'flatline':case 'duplicate_rows':case 'timestamp_duplicate':return {key:'cc.fd.'+f.check,params:{n:d.count,record:first??'—'}};
  case 'constant_column':return {key:'cc.fd.constant_column',params:{}};
  case 'sampling_interval_change':return {key:'cc.fd.sampling_interval_change',params:{current:d.current_seconds,baseline:d.baseline_seconds}};
  case 'volume_change':return {key:'cc.fd.volume_change',params:{current:d.current,min:d.baseline_min??'—',max:d.baseline_max??'—'}};
  case 'freshness':return d.lag_seconds===undefined?{key:'cc.fd.freshness.empty',params:{sla:d.sla_seconds}}:{key:'cc.fd.freshness',params:{lag:d.lag_seconds,sla:d.sla_seconds}};
 }
 return {key:'cc.fd.other',params:{check:f.check}};
}

// The page brief's two live answers from the current state: what happened (one or more sentences) and the next step.
// ``error`` is the last poll failure, if any. Keys with raw parameters; ``state`` is running, paused or ready.
function ccBrief(state,isConnected=true,error=''){
 if(!isConnected)return {happened:[{key:'cc.brief.connect',params:{}}],next:{key:'cc.hint.connect',params:{}}};
 if(!state)return {happened:[error?{key:'cc.brief.error',params:{reason:error}}:{key:'cc.brief.loading',params:{}}],next:{key:'cc.hint.loading',params:{}}};
 const g=ccGuide(state,true),open=state.incidents.filter(i=>i.status==='open'),k=state.kpis;
 const mode=state.status.running?'running':state.elapsed_s?'paused':'ready',base={state:mode,speed:state.status.speed,detections:k.detections,checks:k.checks};
 const happened=[];
 if(mode==='ready')happened.push({key:'cc.brief.ready',params:{every:state.settings.check_every,window:state.settings.window_seconds}});
 else if(open.length)happened.push({key:'cc.brief.open',params:{...base,open:open.length,id:g.incident?.id||open[0].id}});
 else happened.push({key:k.incidents?'cc.brief.closed':'cc.brief.clean',params:{...base,n:k.incidents}});
 if(state.agents?.active)happened.push({key:'cc.brief.agents.active',params:{}});
 else if(k.investigations)happened.push({key:'cc.brief.agents.runs',params:{n:k.investigations}});
 const ev=g.incident?.evidence;
 return {happened,next:{key:'cc.hint.'+g.step,params:{every:state.settings.check_every,window:state.settings.window_seconds,id:g.incident?.id||'',
  collected:ev?.collected_s??0,needed:ev?.needed_s??state.settings.window_seconds}}};
}

// An incident's evidence for display: ``locating`` (no onset estimated yet), ``collecting`` (a full window after the
// onset has not elapsed), ``ready`` (frozen; the agents can start) or ``unavailable`` (closed before it was complete),
// with the seconds collected and needed.
function ccEvidence(ev){
 const needed=ev?.needed_s??0,collected=Math.max(0,Math.min(needed,ev?.collected_s??0)),raw=ev?.state;
 const state=raw==='ready'||raw==='unavailable'?raw:ev?.onset_t===null||ev?.onset_t===undefined?'locating':'collecting';
 return {state,collected,needed,ratio:needed?collected/needed:0,ready:state==='ready'};
}
// Why starting an investigation was refused: a string key and raw parameters, or key null to show the error message.
function ccStartError(error){
 const code=error?.body?.error;
 if(code==='EVIDENCE_NOT_READY'){const e=ccEvidence(error.body.evidence);return {key:'cc.err.notready',params:{n:e.collected,needed:e.needed}};}
 if(code==='BUSY')return {key:'cc.investigate.busy',params:{}};
 if(error?.status===404)return {key:'cc.err.notfound',params:{}};
 return {key:null,params:{}};
}

if(typeof module!=='undefined')module.exports={CC_SENSORS,CC_DIGITS,CC_GAP_S,CC_CHART,CC_CHART_NARROW,ccNiceStep,ccDomain,ccClock,ccRel,ccSeverityMax,ccChartModel,ccKpis,ccGuide,ccLayerBars,ccFindingText,ccBrief,ccFocusRange,ccEvidence,ccStartError};

// ---------- browser page ----------
let ccState=null,ccTimer=null,ccInflight=false,ccBusy=false,ccError='',ccDom=null,ccTable=false,ccSeen=null,ccStarting=null;
const ccOpenEvidence=new Set(),ccFresh=new Set(),ccFocus=new Set(),ccSensorChoice={calibration_offset:'temp_c',unit_change:'pressure_kpa',stuck_sensor:'flow_lpm',noise_increase:'pressure_kpa'};
const CC_POLL_MS=1000,CC_RETRY_MS=4000,CC_TABLE_ROWS=20;
const ccNarrow=typeof matchMedia==='function'?matchMedia('(max-width: 760px)'):null;

const ccWanted=()=>connected&&route==='/overview'&&(typeof document==='undefined'||document.visibilityState!=='hidden');
function ccStop(){clearTimeout(ccTimer);ccTimer=null;}
function ccSchedule(delay=CC_POLL_MS){ccStop();if(ccWanted())ccTimer=setTimeout(ccPoll,delay);}
async function ccFetch(){
 if(ccInflight)return;
 ccInflight=true;
 try{ccAccept(await request('/api/plant/state'));ccError='';}
 catch(error){ccError=t('cc.err.poll',{reason:error.message});}
 ccInflight=false;
}
async function ccPoll(){
 ccTimer=null;
 if(!ccWanted())return;
 await ccFetch();
 if(route==='/overview')ccPaint();
 ccSchedule(ccError?CC_RETRY_MS:CC_POLL_MS);
}
function ccAccept(next){
 const ids=next.incidents.map(i=>i.id);
 if(ccSeen===null||next.live_start_t!==ccState?.live_start_t){ccSeen=new Set(ids);}
 else{
  const added=next.incidents.filter(i=>!ccSeen.has(i.id));
  for(const i of added){ccSeen.add(i.id);ccFresh.add(i.id);setTimeout(()=>{ccFresh.delete(i.id);},4000);}
  if(added.length){const i=added[0],live=document.getElementById('cc-live');
   if(live)live.textContent=t('cc.live.incident',{id:i.id,severity:t('cc.sev.'+i.severity),sensor:t('cc.sensor.'+i.sensor)});}
 }
 ccState=next;
}
async function ccAction(path,body){
 if(!requireSession())return null;
 ccBusy=true;ccPaint();
 try{const result=await request(path,'POST',JSON.stringify(body),JSON_HEADERS);await ccFetch();return result;}
 catch(error){setNotice(error.message,true);return null;}
 finally{ccBusy=false;ccPaint();}
}
const ccControl=(action,speed)=>ccAction('/api/plant/control',speed===undefined?{action}:{action,speed});
const ccInject=(fault,sensor)=>ccAction('/api/plant/inject',sensor?{fault,sensor}:{fault});
const ccClear=id=>ccAction('/api/plant/clear',{fault_id:id});
async function ccInvestigate(incident){
 if(!requireSession()||ccStarting)return;
 ccStarting=incident.id;ccPaint();
 try{
  const started=await request(`/api/plant/incidents/${incident.id}/investigate`,'POST','{}',JSON_HEADERS);
  ccStarting=null;openFlowRun(started.run_id);
  setNotice(t('cc.investigate.started',{id:incident.id}));
  return;
 }catch(error){const x=ccStartError(error);setNotice(x.key?t(x.key,{n:N(x.params.n??0),needed:N(x.params.needed??0)}):error.message,true);}
 ccStarting=null;ccPaint();
}
function ccOpenRun(event,runId){
 if(event.metaKey||event.ctrlKey||event.shiftKey||event.button===1)return;
 event.preventDefault();openFlowRun(runId);
}

// ---------- formatting ----------
const ccNum=(v,d=2)=>v===null||v===undefined?'—':Number(v).toLocaleString(locale(),{minimumFractionDigits:d,maximumFractionDigits:d});
const ccAt=t=>ccState?ccRel(t,ccState.live_start_t):'—';
const ccSensorName=s=>t('cc.sensor.'+s);
const ccUnit=s=>ccState?.units?.[s]||'';
const ccCheckName=c=>tt('cc.check.'+c,String(c).replace(/_/g,' '));
function ccFindingSentence(f){
 const x=ccFindingText(f),p={...x.params};
 for(const k of ['psi','threshold'])if(typeof p[k]==='number')p[k]=ccNum(p[k],3);
 for(const k of ['before','after'])if(typeof p[k]==='number')p[k]=ccNum(p[k],2);
 for(const k of ['n','current','min','max','record','sla','lag','baseline'])if(typeof p[k]==='number')p[k]=N(p[k]);
 if(p.check)p.check=ccCheckName(p.check);
 return t(x.key,p);
}
function ccSevIcon(sev){
 const svg=svgEl('svg',{viewBox:'0 0 12 12',class:'cc-sev-icon','aria-hidden':'true',focusable:'false'});
 svg.append(sev==='high'?svgEl('path',{d:'M6 1.2 11 10.5H1Z'}):sev==='medium'?svgEl('path',{d:'M6 1 11 6 6 11 1 6Z'}):svgEl('circle',{cx:6,cy:6,r:4}));
 return svg;
}
const ccSev=sev=>h('span',{class:'cc-sev '+sev},ccSevIcon(sev),t('cc.sev.'+sev));
// Keep elements across repaints (a click is never lost to a re-render); create, update and reorder by key.
function ccKeyed(container,items,key,create,update){
 const old=container.ccKeys||new Map(),next=new Map();
 const nodes=items.map(item=>{const k=key(item);const n=old.get(k)||create(item);update(n,item);next.set(k,n);return n;});
 if(nodes.length!==container.children.length||nodes.some((n,i)=>container.children[i]!==n))container.replaceChildren(...nodes);
 container.ccKeys=next;
}
const ccText=(node,text)=>{if(node.textContent!==text)node.textContent=text;};

// ---------- chart ----------
function ccChartSvg(sensor){
 const m=ccChartModel(ccState,sensor,ccNarrow?.matches?CC_CHART_NARROW:{},{focus:ccFocus.has(sensor)}),unit=ccUnit(sensor),d=CC_DIGITS[sensor];
 const svg=svgEl('svg',{viewBox:`0 0 ${m.width} ${m.height}`,class:'cc-chart',role:'img','aria-label':t('cc.chart.label',{sensor:ccSensorName(sensor),unit,n:N(m.count),
  value:m.latest?ccNum(m.latest.v,d):'—',min:ccNum(m.min,d),max:ccNum(m.max,d),low:ccNum(m.band.low,d),high:ccNum(m.band.high,d),markers:N(m.markers.length),faults:N(m.faults.length)})+(m.focus&&m.clippedCount?' '+t('cc.focus.clipped',{n:N(m.clippedCount)}):m.scale.changed?' '+t('cc.scale.changed.label'):'')});
 const pat='cc-hatch-'+sensor;
 svg.append(svgEl('defs',{},svgEl('pattern',{id:pat,width:'6',height:'6',patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'},svgEl('line',{x1:'0',y1:'0',x2:'0',y2:'6',class:'cc-hatch-line'}))));
 const P=m.plot;
 for(const tick of m.yTicks){
  svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:tick.y,y2:tick.y,class:'cc-grid'}),svgText(ccNum(tick.v,m.domain.step<1?(m.domain.step<0.1?2:1):0),{x:P.l-8,y:tick.y+3.5,class:'cc-axis','text-anchor':'end'}));
 }
 for(const tick of m.xTicks)svg.append(svgText(tick.ago?t('cc.axis.ago',{n:tick.ago}):t('cc.axis.now'),{x:tick.x,y:m.height-6,class:'cc-axis','text-anchor':tick.ago?(tick.x<P.l+20?'start':'middle'):'end'}));
 svg.append(svgText(unit,{x:P.l-8,y:P.t-10,class:'cc-axis unit','text-anchor':'end'}));
 const top=Math.max(P.t,Math.min(P.b,m.band.top)),bottom=Math.max(P.t,Math.min(P.b,m.band.bottom));
 if(bottom-top>0.5)svg.append(svgEl('rect',{x:P.l,y:top,width:P.r-P.l,height:bottom-top,class:'cc-band'}));
 for(const edge of [m.band.top,m.band.bottom])if(edge>=P.t&&edge<=P.b)svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:edge,y2:edge,class:'cc-band-edge'}));
 if(m.band.mean>=P.t&&m.band.mean<=P.b)svg.append(svgEl('line',{x1:P.l,x2:P.r,y1:m.band.mean,y2:m.band.mean,class:'cc-band-mean'}));
 for(const f of m.faults){
  svg.append(svgEl('rect',{x:f.x,y:P.t,width:f.w,height:P.b-P.t,class:'cc-fault-fill'+(f.active?' active':'')}));
  const r=svgEl('rect',{x:f.x,y:P.t,width:f.w,height:P.b-P.t,class:'cc-fault-span'+(f.active?' active':''),fill:`url(#${pat})`});
  r.append(svgEl('title',{},document.createTextNode(t('cc.injected',{fault:t('cc.fault.'+f.fault)}))));
  svg.append(r,svgEl('line',{x1:f.x,x2:f.x,y1:P.t,y2:P.b,class:'cc-fault-edge'}));
  if(f.w>=40||f.active)svg.append(svgText(t('cc.injected.short'),{x:Math.min(f.x+4,P.r-4),y:P.b-6,class:'cc-fault-label','text-anchor':f.x+4>P.r-60?'end':'start'}));
 }
 svg.append(svgEl('path',{d:m.path,class:'cc-line'}));
 m.markers.forEach((mk,i)=>{
  const g=svgEl('g',{class:`cc-marker ${mk.severity}`+(mk.stream?' stream':'')});
  const label=mk.checks.map(ccCheckName).join(' + ');
  g.append(svgEl('title',{},document.createTextNode(`${label} · ${mk.incidents.join(', ')} · ${ccAt(mk.t)}`)),
   svgEl('line',{x1:mk.x,x2:mk.x,y1:P.t,y2:P.b,class:'cc-marker-halo'}),svgEl('line',{x1:mk.x,x2:mk.x,y1:P.t,y2:P.b,class:'cc-marker-line'}),
   svgEl('path',{d:`M${mk.x-6} ${P.t-11}h12l-6 10z`,class:'cc-marker-head'}));
  const right=mk.x>P.r-110,short=ccCheckName(mk.checks[0])+(mk.checks.length>1?' +'+(mk.checks.length-1):'');
  g.append(svgText(short,{x:right?mk.x-8:mk.x+8,y:P.t+10+(i%2)*12,class:'cc-marker-label','text-anchor':right?'end':'start'}));
  svg.append(g);
 });
 for(const c of m.clipped){
  const y0=c.dir==='up'?P.t+1:P.b-1,s=c.dir==='up'?1:-1;
  svg.append(svgEl('path',{d:`M${c.x.toFixed(1)} ${y0} l-4 ${7*s} h8 z`,class:'cc-clip'}));
 }
 if(m.scale.changed)svg.append(svgText(t('cc.scale.flag'),{x:P.l+6,y:P.t+11,class:'cc-scale-flag'}));
 else if(m.focus)svg.append(svgText(t('cc.focus.flag'),{x:P.l+6,y:P.t+11,class:'cc-scale-flag focus'}));
 if(m.dot)svg.append(svgEl('circle',{cx:m.dot.x,cy:m.dot.y,r:3.6,class:'cc-dot'+(m.outside?' out':'')+(m.dot.clipped?' clipped':'')}));
 return {svg,model:m};
}

// ---------- building the page (once per language) ----------
function ccBuild(root){
 const d={lang:language};
 const btn=(id,cls,onclick)=>h('button',{type:'button',id,class:cls,onclick});
 // status bar
 d.badge=h('span',{class:'cc-sim-badge'});d.badgeX=h('small',{class:'cc-sim-x'});
 d.state=h('span',{class:'cc-live'});d.run=btn('cc-run','primary',()=>ccControl(ccState?.status?.running?'pause':'start'));
 d.reset=btn('cc-reset','secondary',()=>ccControl('reset'));
 d.speeds=h('div',{class:'cc-speeds',role:'group'});d.speedLabel=h('span',{class:'cc-label',id:'cc-speed-label'});
 d.speedBtns=[1,5,20].map(n=>btn('cc-speed-'+n,'secondary cc-speed',()=>ccControl('speed',n)));d.speeds.setAttribute('aria-labelledby','cc-speed-label');d.speeds.append(...d.speedBtns);
 const stat=()=>{const label=h('span',{class:'cc-label'}),value=h('strong'),sub=h('small');return {node:h('div',{class:'cc-stat'},label,value,sub),label,value,sub};};
 d.clock=stat();d.model=stat();d.check=stat();
 d.status=h('section',{class:'panel cc-status','aria-labelledby':'cc-status-title'},
  h('h2',{id:'cc-status-title',class:'sr-only'}),
  h('div',{class:'cc-status-main'},h('div',{class:'cc-badge-wrap'},d.badge,d.badgeX),d.state,h('div',{class:'cc-controls'},d.run,d.reset),h('div',{class:'cc-speed-wrap'},d.speedLabel,d.speeds)),
  h('div',{class:'cc-status-stats'},d.clock.node,d.model.node,d.check.node));
 // guide
 d.guideTitle=h('h2',{class:'cc-guide-title'});d.guideSteps=['start','inject','investigate'].map(k=>{const n=h('li',{class:'cc-step'});n.ccKey=k;return n;});
 d.guideHint=h('p',{class:'cc-guide-hint'});
 d.guide=h('section',{class:'cc-guide','aria-label':''},d.guideTitle,h('ol',{class:'cc-steps'},d.guideSteps),d.guideHint);
 // KPIs
 d.kpis=h('div',{class:'cc-kpis'});
 // sensors
 d.sensorsTitle=h('h2',{id:'cc-sensors-title'});d.sensorsChip=h('span',{class:'chip info'});
 d.tableBtn=btn('cc-table-toggle','secondary cc-small',()=>{ccTable=!ccTable;ccPaint();});d.tableBtn.setAttribute('aria-controls','cc-table');
 d.rows=CC_SENSORS.map(s=>{
  const r={sensor:s,name:h('span',{class:'cc-sname'}),value:h('strong',{class:'cc-value'}),unit:h('span',{class:'cc-unit'}),state:h('span',{class:'cc-band-state'}),band:h('small'),chart:h('div',{class:'cc-chart-wrap'})};
  r.scaleNote=h('span',{class:'cc-scale-note',id:'cc-scale-'+s});
  r.focusBtn=btn('cc-focus-'+s,'secondary cc-small',()=>{if(ccFocus.has(s))ccFocus.delete(s);else ccFocus.add(s);ccPaint();});
  r.focusBtn.setAttribute('aria-describedby','cc-scale-'+s);
  r.scale=h('div',{class:'cc-scale'},r.scaleNote,r.focusBtn);
  r.node=h('div',{class:'cc-sensor'},h('div',{class:'cc-readout'},r.name,h('div',{class:'cc-value-line'},r.value,r.unit),r.state,r.band),h('div',{class:'cc-chart-col'},r.chart,r.scale));
  return r;});
 d.legend=h('ul',{class:'cc-legend'});d.sensorsNote=h('p',{class:'panel-note'});d.table=h('div',{id:'cc-table',class:'table-wrap cc-table'});
 d.sensors=h('section',{class:'panel cc-sensors','aria-labelledby':'cc-sensors-title'},
  h('div',{class:'panel-heading'},h('div',{class:'cc-head-left'},d.sensorsTitle,d.sensorsChip),d.tableBtn),...d.rows.map(r=>r.node),d.legend,d.table,d.sensorsNote);
 // incidents
 d.incTitle=h('h2',{id:'cc-inc-title'});d.incChip=h('span',{class:'chip'});d.incList=h('ol',{class:'cc-incidents'});d.incEmpty=h('div',{class:'empty-state'});d.incNote=h('p',{class:'panel-note'});
 d.incidents=h('section',{class:'panel cc-inc-panel','aria-labelledby':'cc-inc-title'},h('div',{class:'panel-heading'},d.incTitle,d.incChip),d.incEmpty,d.incList,d.incNote);
 // fault console
 d.conTitle=h('h2',{id:'cc-con-title'});d.conChip=h('span',{class:'chip warn'});d.conX=h('p',{class:'cc-console-x'});
 d.faultCards=(ccState?.catalog?.faults||[]).map(f=>ccFaultCard(f));
 d.activeTitle=h('h3');d.activeList=h('ul',{class:'cc-active'});d.activeEmpty=h('p',{class:'hint'});
 d.console=h('section',{class:'panel cc-console','aria-labelledby':'cc-con-title'},h('div',{class:'panel-heading'},d.conTitle,d.conChip),d.conX,
  h('ul',{class:'cc-faults'},d.faultCards.map(c=>c.node)),d.activeTitle,d.activeEmpty,d.activeList);
 // agent activity
 d.agTitle=h('h2',{id:'cc-ag-title'});d.agChip=h('span',{class:'chip'});d.agBody=h('div',{class:'cc-ag-body'});d.agNote=h('p',{class:'panel-note'});
 d.recentTitle=h('h3');d.recent=h('ol',{class:'cc-recent'});d.recentEmpty=h('div',{class:'empty-state'});
 d.agents=h('section',{class:'panel cc-agents','aria-labelledby':'cc-ag-title'},h('div',{class:'panel-heading'},d.agTitle,d.agChip),d.agBody,d.recentTitle,d.recentEmpty,d.recent,d.agNote);
 d.error=h('p',{class:'hint bad',role:'alert'});
 d.live=h('p',{id:'cc-live',class:'sr-only',role:'status','aria-atomic':'true'});
 d.root=h('div',{class:'cc'},d.live,d.status,d.error,d.guide,d.kpis,h('div',{class:'cc-main'},d.sensors,d.incidents),h('div',{class:'cc-lower'},d.console,d.agents));
 root.replaceChildren(d.root);
 ccDom=d;
}
function ccFaultCard(fault){
 const sensorFault=(ccState?.catalog?.sensor_faults||[]).includes(fault),c={fault};
 c.title=h('strong');c.text=h('small');c.inject=h('button',{type:'button',id:'cc-inj-'+fault,class:'secondary cc-inject',onclick:()=>ccInject(fault,sensorFault?c.select.value:null)});
 if(sensorFault){
  c.label=h('label',{for:'cc-sel-'+fault,class:'cc-label'});
  c.select=h('select',{id:'cc-sel-'+fault,onchange:e=>{ccSensorChoice[fault]=e.target.value;ccPaint();}},CC_SENSORS.map(s=>h('option',{value:s})));
  c.select.value=ccSensorChoice[fault]||CC_SENSORS[0];
  c.target=h('div',{class:'cc-target'},c.label,c.select);
 }else{c.stream=h('span',{class:'cc-stream'});c.target=h('div',{class:'cc-target'},c.stream);}
 c.node=h('li',{class:'cc-fault'},h('div',{class:'cc-fault-text'},c.title,c.text),h('div',{class:'cc-fault-row'},c.target,c.inject));
 return c;
}

// ---------- updating in place ----------
function ccUpdateStatus(d,s){
 ccText(d.badge,t('cc.badge'));ccText(d.badgeX,t('cc.badge.x'));
 d.state.className='cc-live '+(s.status.running?'running':'paused');
 d.state.replaceChildren(h('span',{class:'cc-pulse','aria-hidden':'true'}),t(s.status.running?'cc.state.running':s.elapsed_s?'cc.state.paused':'cc.state.ready'));
 ccText(d.run,t(s.status.running?'cc.pause':s.elapsed_s?'cc.resume':'cc.start'));d.run.disabled=ccBusy;
 d.run.className=s.status.running?'secondary':'primary';
 ccText(d.reset,t('cc.reset'));d.reset.disabled=ccBusy;d.reset.title=t('cc.reset.x');
 ccText(d.speedLabel,t('cc.speed'));
 d.speedBtns.forEach((b,i)=>{const n=[1,5,20][i];ccText(b,t('cc.speed.n',{n}));b.setAttribute('aria-pressed',String(s.status.speed===n));b.setAttribute('aria-label',t('cc.speed.label',{n}));b.disabled=ccBusy;});
 ccText(d.clock.label,t('cc.clock'));ccText(d.clock.value,ccRel(s.now_t,s.live_start_t));ccText(d.clock.sub,t('cc.clock.x',{speed:s.status.speed}));
 const m=s.model;
 ccText(d.model.label,t('cc.model'));
 ccText(d.model.value,m?t(m.reachable?'cc.model.on':'cc.model.off',{model:m.model}):t('cc.model.unknown'));
 d.model.value.className=m?.reachable?'ok':'warn';ccText(d.model.sub,t(m?.reachable?'cc.model.x.on':'cc.model.x'));
 ccText(d.check.label,t('cc.check'));
 const c=s.last_check;
 ccText(d.check.value,c?ccRel(c.t,s.live_start_t):'—');
 ccText(d.check.sub,c?t('cc.check.v',{records:N(c.records),findings:N(c.findings),every:s.settings.check_every}):t('cc.check.none',{n:s.settings.check_every,window:s.settings.window_seconds}));
 ccText(d.status.firstChild,t('cc.status'));
}
function ccUpdateGuide(d,s){
 const g=ccGuide(s,connected);
 ccText(d.guideTitle,t('cc.guide'));d.guide.setAttribute('aria-label',t('cc.guide'));
 const current={start:['start','resume'],inject:['inject','wait'],investigate:['collect','investigate','review']};
 d.guideSteps.forEach((li,i)=>{
  const k=li.ccKey,state=current[k].includes(g.step)?'current':g.done[k]?'done':'todo';
  li.className='cc-step '+state;
  if(li.ccState!==state+language){li.ccState=state+language;li.replaceChildren(h('b',{text:state==='done'?'✓':String(i+1),'aria-hidden':'true'}),h('span',{text:t('cc.guide.'+k)}),h('small',{class:'sr-only',text:t('cc.step.'+state)}));}
  if(state==='current')li.setAttribute('aria-current','step');else li.removeAttribute('aria-current');
 });
 ccText(d.guideHint,ccHint(g,s));
}
function ccHint(g,s){
 const ev=g.incident?.evidence,window=s?.settings?.window_seconds??200;
 const p={every:s?.settings?.check_every??15,window,id:g.incident?.id||'',collected:N(ev?.collected_s??0),needed:N(ev?.needed_s??window)};
 return t('cc.hint.'+g.step,p);
}
function ccUpdateKpis(d,s){
 const fmt=k=>k.na?t('cc.na'):k.kind==='percent'?P(k.value):k.kind==='ms'?msText(k.value):N(k.value);
 ccKeyed(d.kpis,ccKpis(s),k=>k.key,k=>{const n=h('article',{class:'kpi cc-kpi'});n.ccR={label:h('span'),value:h('strong'),sub:h('small')};n.append(n.ccR.label,n.ccR.value,n.ccR.sub);return n;},
  (n,k)=>{n.className='kpi cc-kpi '+(k.tone||'')+(k.na?' na':'');ccText(n.ccR.label,t('cc.k.'+k.key));ccText(n.ccR.value,fmt(k));
   const params=Object.fromEntries(Object.entries(k.params).map(([a,v])=>[a,N(v)]));
   ccText(n.ccR.sub,k.na?t('cc.k.'+k.key+'.na'):t('cc.k.'+k.key+'.x',params));});
}
function ccUpdateSensors(d,s){
 ccText(d.sensorsTitle,t('cc.sensors'));ccText(d.sensorsChip,t('cc.sensors.chip',{n:N(s.settings.chart_readings)}));
 ccText(d.tableBtn,t(ccTable?'cc.table.hide':'cc.table.show'));d.tableBtn.setAttribute('aria-expanded',String(ccTable));
 for(const r of d.rows){
  const sensor=r.sensor,band=s.baseline.bands[sensor],{svg,model}=ccChartSvg(sensor),dg=CC_DIGITS[sensor];
  ccText(r.name,ccSensorName(sensor));
  const value=ccNum(s.current[sensor],dg);
  if(r.value.textContent!==value){r.value.textContent=value;r.value.classList.remove('tick');void r.value.offsetWidth;r.value.classList.add('tick');}
  ccText(r.unit,ccUnit(sensor));
  r.state.className='cc-band-state '+(model.outside?'out':'in');ccText(r.state,t(model.outside?'cc.outband':'cc.inband'));
  ccText(r.band,t('cc.band.x',{low:ccNum(band.low,dg),high:ccNum(band.high,dg),unit:ccUnit(sensor)}));
  r.node.classList.toggle('alert',model.outside);
  r.chart.replaceChildren(svg);
  r.scale.hidden=!model.scale.available;
  if(model.scale.available){
   const f=v=>ccNum(v,model.domain.step<1?(model.domain.step<0.1?2:1):0);
   ccText(r.scaleNote,model.focus?t('cc.focus.note',{n:N(model.clippedCount),low:f(model.domain.min),high:f(model.domain.max),unit:ccUnit(sensor)})
    :t('cc.scale.note',{low:f(model.domain.min),high:f(model.domain.max),unit:ccUnit(sensor)}));
   r.scaleNote.className='cc-scale-note'+(model.scale.changed?' changed':'');
   ccText(r.focusBtn,t('cc.focus'));r.focusBtn.setAttribute('aria-pressed',String(model.focus));
  }
 }
 if(!d.legend.ccLang||d.legend.ccLang!==language){
  d.legend.ccLang=language;
  const item=(cls,key)=>h('li',{},h('span',{class:'cc-key '+cls,'aria-hidden':'true'}),t(key));
  d.legend.replaceChildren(item('line','cc.legend.line'),item('band','cc.legend.band'),item('marker','cc.legend.marker'),item('fault','cc.legend.fault'),item('clip','cc.legend.clip'));
 }
 ccText(d.sensorsNote,t('cc.sensors.note',{records:N(s.baseline.records),every:s.settings.check_every,window:s.settings.window_seconds}));
 d.table.hidden=!ccTable;
 if(ccTable){
  const n=s.series.t.length,rows=[];
  for(let i=n-1;i>=Math.max(0,n-CC_TABLE_ROWS);i--)rows.push(h('tr',{},h('th',{scope:'row',text:ccRel(s.series.t[i],s.live_start_t)}),...CC_SENSORS.map(x=>h('td',{text:ccNum(s.series[x][i],CC_DIGITS[x])}))));
  d.table.replaceChildren(h('table',{class:'data-table compact'},h('caption',{text:t('cc.table.caption',{n:N(rows.length)})}),
   h('thead',{},h('tr',{},h('th',{scope:'col',text:t('cc.col.time')}),...CC_SENSORS.map(x=>h('th',{scope:'col',text:`${ccSensorName(x)} (${ccUnit(x)})`})))),h('tbody',{},rows)));
 }else if(d.table.firstChild)d.table.replaceChildren();
}
function ccIncidentCard(){
 const c={};
 c.sev=h('span');c.title=h('strong',{class:'cc-inc-title'});c.status=h('span',{class:'chip'});c.meta=h('p',{class:'cc-inc-meta'});c.checks=h('ul',{class:'cc-checks'});
 c.go=h('button',{type:'button',class:'primary cc-go'});c.run=h('a',{class:'cc-run-link'});c.busy=h('small',{class:'hint cc-go-why'});
 c.open=h('a',{class:'cc-run-link cc-open-inc'});
 c.evText=h('span',{class:'cc-evstate-text'});c.evBar=h('progress',{class:'cc-evbar',max:'1',value:'0'});c.ev=h('div',{class:'cc-evstate'},c.evText,c.evBar);
 c.sum=h('summary');c.evBody=h('div',{class:'cc-ev'});c.details=h('details',{class:'cc-evidence'},c.sum,c.evBody);
 c.node=h('li',{class:'cc-inc'},h('div',{class:'cc-inc-head'},c.sev,c.title,c.status),c.meta,c.checks,c.ev,h('div',{class:'cc-inc-actions'},c.go,c.open,c.run),c.busy,c.details);
 c.node.ccC=c;return c.node;
}
function ccUpdateIncident(node,inc){
 const c=node.ccC,s=ccState,active=s.agents.active;
 node.className=`cc-inc ${inc.severity} ${inc.status}`+(ccFresh.has(inc.id)?' fresh':'');
 c.sev.replaceChildren(ccSev(inc.severity));
 ccText(c.title,`${inc.id} · ${ccSensorName(inc.sensor)}`);
 c.status.className='chip '+(inc.status==='open'?'bad':'muted');ccText(c.status,t('cc.status.'+inc.status));
 ccText(c.meta,inc.status==='open'?t('cc.inc.meta',{at:ccAt(inc.opened_t),n:N(inc.findings.length),records:N(inc.window.records)})
  :t('cc.inc.closed',{at:ccAt(inc.closed_t),opened:ccAt(inc.opened_t)}));
 const sig=inc.checks.join('|')+language;
 if(c.checks.ccSig!==sig){c.checks.ccSig=sig;c.checks.replaceChildren(...inc.checks.map(k=>h('li',{},chip(ccCheckName(k),{high:'bad',medium:'warn',low:'muted'}[inc.findings.find(f=>f.check===k)?.severity]||'muted'))));}
 // Evidence: the agents start only on the frozen window after the estimated onset, never on the detection window.
 const ev=ccEvidence(inc.evidence);
 c.ev.className='cc-evstate '+ev.state;
 ccText(c.evText,ev.state==='collecting'?t('cc.evs.collecting',{n:N(ev.collected),needed:N(ev.needed)}):t('cc.evs.'+ev.state));
 c.evBar.hidden=ev.state!=='collecting';c.evBar.max=ev.needed||1;c.evBar.value=ev.collected;c.evBar.setAttribute('aria-label',t('inc.progress.label'));
 c.go.id='cc-inv-'+inc.id;c.go.onclick=()=>ccInvestigate(inc);c.busy.id='cc-why-'+inc.id;c.go.setAttribute('aria-describedby',c.busy.id);
 ccText(c.go,t(ccStarting===inc.id?'cc.investigating':'cc.investigate'));
 c.go.disabled=!!active||!!ccStarting||!ev.ready;
 const why=!ev.ready?t('cc.go.why.'+ev.state):active?t('cc.investigate.busy'):'';
 c.busy.hidden=!why;ccText(c.busy,why);
 c.open.href='/incident?id='+encodeURIComponent(inc.id);c.open.id='cc-openinc-'+inc.id;c.open.onclick=e=>incOpenLink(e,inc.id);
 ccText(c.open,t('cc.openinc'));c.open.setAttribute('aria-label',t('cc.openinc.label',{id:inc.id}));
 c.run.hidden=!inc.run_id;
 if(inc.run_id){c.run.href='/flow?run='+encodeURIComponent(inc.run_id);c.run.id='cc-run-'+inc.id;c.run.onclick=e=>ccOpenRun(e,inc.run_id);ccText(c.run,t('cc.viewrun'));}
 c.details.id='cc-ev-'+inc.id;
 if(c.details.ccFor!==inc.id){c.details.ccFor=inc.id;c.details.open=ccOpenEvidence.has(inc.id);} // never fight the user's own toggle
 c.details.ontoggle=e=>{if(e.target.open)ccOpenEvidence.add(inc.id);else ccOpenEvidence.delete(inc.id);};
 c.sum.id='cc-evs-'+inc.id;ccText(c.sum,t('cc.evidence'));
 const evSig=JSON.stringify([inc.window.sha256,inc.findings.length,language,s.baseline.digest]);
 if(c.evBody.ccSig!==evSig){
  c.evBody.ccSig=evSig;const w=inc.window;
  c.evBody.replaceChildren(
   h('ul',{class:'cc-findings'},inc.findings.map(f=>h('li',{},h('div',{},ccSev(f.severity),h('strong',{text:ccCheckName(f.check)}),f.column?h('code',{text:f.column}):null),
    h('span',{text:ccFindingSentence(f)}),h('small',{text:t('cc.ev.first',{at:ccAt(f.first_t)})+' · '+t('cc.ev.source.'+f.source)})))),
   h('dl',{class:'cc-dl'},
    h('dt',{text:t('cc.ev.window')}),h('dd',{text:t('cc.ev.window.v',{records:N(w.records),from:w.first_t===null?'—':ccAt(w.first_t),to:ccAt(w.last_t),asof:w.as_of})}),
    h('dt',{text:t('cc.ev.digest')}),h('dd',{},h('code',{title:w.sha256,text:w.sha256.slice(0,16)+'…'})),
    h('dt',{text:t('cc.ev.baseline')}),h('dd',{},h('code',{title:s.baseline.digest,text:s.baseline.digest.slice(0,16)+'…'}))),
   h('p',{class:'hint',text:t('cc.ev.note')}));
 }
}
function ccUpdateIncidents(d,s){
 const open=s.incidents.filter(i=>i.status==='open').length;
 ccText(d.incTitle,t('cc.incidents'));d.incChip.className='chip '+(open?'bad':'ok');ccText(d.incChip,t('cc.incidents.open',{n:N(open)}));
 d.incEmpty.hidden=s.incidents.length>0;
 if(!s.incidents.length&&d.incEmpty.ccLang!==language){d.incEmpty.ccLang=language;d.incEmpty.replaceChildren(h('strong',{text:t('cc.incidents.none.t')}),h('span',{text:t('cc.incidents.none.x',{every:s.settings.check_every})}));}
 ccKeyed(d.incList,s.incidents,i=>i.id,ccIncidentCard,ccUpdateIncident);
 ccText(d.incNote,t('cc.incidents.note',{n:s.settings.close_after}));
}
function ccUpdateConsole(d,s){
 ccText(d.conTitle,t('cc.console'));ccText(d.conChip,t('cc.console.chip'));ccText(d.conX,t('cc.console.x'));
 const active=s.faults.filter(f=>f.ended_t===null);
 for(const c of d.faultCards){
  const sensorFault=!!c.select;
  ccText(c.title,t('cc.fault.'+c.fault));ccText(c.text,t('cc.fault.'+c.fault+'.x'));
  if(sensorFault){ccText(c.label,t('cc.sensor'));[...c.select.options].forEach(o=>ccText(o,ccSensorName(o.value)));}
  else ccText(c.stream,t('cc.sensor.stream'));
  const target=sensorFault?c.select.value:null,taken=active.some(f=>f.fault===c.fault&&f.sensor===target);
  ccText(c.inject,t(taken?'cc.inject.active':'cc.inject'));
  c.inject.setAttribute('aria-label',t('cc.inject.label',{fault:t('cc.fault.'+c.fault),sensor:ccSensorName(target||'stream')}));
  c.inject.disabled=ccBusy||taken||active.length>=4;
 }
 ccText(d.activeTitle,t('cc.active'));
 d.activeEmpty.hidden=s.faults.length>0;ccText(d.activeEmpty,t('cc.active.none'));
 ccKeyed(d.activeList,s.faults,f=>f.id,()=>{const n=h('li');n.ccR={text:h('div'),clear:h('button',{type:'button',class:'secondary cc-small'})};n.append(n.ccR.text,n.ccR.clear);return n;},(n,f)=>{
  const state=f.one_shot?'once':f.ended_t===null?'active':'ended',sensor=ccSensorName(f.sensor||'stream');
  n.className='cc-af '+state;
  const sig=JSON.stringify([f.ended_t,language,state]);
  if(n.ccSig!==sig){n.ccSig=sig;n.ccR.text.replaceChildren(h('strong',{text:`${f.id} · ${t('cc.fault.'+f.fault)}`}),h('small',{text:`${sensor} · ${f.one_shot?t('cc.active.once',{at:ccAt(f.started_t)}):f.ended_t===null?t('cc.active.since',{at:ccAt(f.started_t)}):t('cc.active.ended',{from:ccAt(f.started_t),to:ccAt(f.ended_t)})}`}),
   chip(t('cc.fault.state.'+state),state==='active'?'warn':'muted'));}
  n.ccR.clear.id='cc-clear-'+f.id;n.ccR.clear.hidden=state!=='active';n.ccR.clear.disabled=ccBusy;
  ccText(n.ccR.clear,t('cc.clear'));n.ccR.clear.setAttribute('aria-label',t('cc.clear.label',{fault:t('cc.fault.'+f.fault),sensor}));n.ccR.clear.onclick=()=>ccClear(f.id);
 });
}
function ccUpdateAgents(d,s){
 const a=s.agents;
 ccText(d.agTitle,t('cc.agents'));ccText(d.agChip,t('cc.agents.chip',{n:N(a.runs)}));ccText(d.agNote,t('cc.agents.note'));
 const sig=JSON.stringify([a.layers,language]);
 if(d.agBody.ccSig!==sig){
  d.agBody.ccSig=sig;
  const bars=ccLayerBars(a.layers),any=bars.some(b=>b.total);
  d.agBody.replaceChildren(...[h('h3',{text:t('cc.agents.layers')}),
   any?h('div',{class:'cc-bars','aria-hidden':'true'},bars.map(b=>h('div',{class:'cc-bar-row'},h('span',{class:'cc-bar-name',text:t('flow.layer.'+b.layer)}),
    h('div',{class:'cc-bar'},b.segments.map(sg=>{const n=h('span',{class:'cc-seg '+sg.status,title:`${t('cc.outcome.'+sg.status)}: ${sg.count}`});n.style.width=(sg.share*100).toFixed(2)+'%';return n;})),
    h('span',{class:'cc-bar-n',text:N(b.total)})))):h('p',{class:'hint',text:t('cc.agents.layers.none')}),
   any?h('ul',{class:'cc-legend outcomes','aria-hidden':'true'},CC_OUTCOMES.map(o=>h('li',{},h('span',{class:'cc-key seg '+o}),t('cc.outcome.'+o)))):null,
   any?h('div',{class:'sr-only'},h('table',{},h('caption',{text:t('cc.agents.layers')}),h('thead',{},h('tr',{},h('th',{scope:'col',text:t('cc.col.layer')}),...CC_OUTCOMES.map(o=>h('th',{scope:'col',text:t('cc.outcome.'+o)})))),
    h('tbody',{},bars.map(b=>h('tr',{},h('th',{scope:'row',text:t('flow.layer.'+b.layer)}),...CC_OUTCOMES.map(o=>h('td',{text:N(b.segments.find(x=>x.status===o)?.count||0)}))))))):null].filter(Boolean));
 }
 ccText(d.recentTitle,t('cc.recent'));
 d.recentEmpty.hidden=a.recent.length>0;
 if(!a.recent.length&&d.recentEmpty.ccLang!==language){d.recentEmpty.ccLang=language;d.recentEmpty.replaceChildren(h('strong',{text:t('cc.agents.none.t')}),h('span',{text:t('cc.agents.none.x')}));}
 ccKeyed(d.recent,a.recent,r=>r.run_id,()=>{const n=h('li');n.ccR={when:h('time'),name:h('span',{class:'cc-recent-name'}),state:h('span'),link:h('a',{class:'cc-run-link'})};
  n.append(h('div',{class:'cc-recent-main'},n.ccR.name,n.ccR.when),n.ccR.state,n.ccR.link);return n;},(n,r)=>{
  ccText(n.ccR.when,when(r.started_at)+(r.from_plant?' · '+t('cc.run.plant'):''));ccText(n.ccR.name,r.name||r.run_id);
  const [label,tone]=r.state==='running'?[t('cc.run.running'),'info']:r.state==='error'?[t('cc.run.error'),'bad']:[flowLabel('runstatus',r.status),r.status==='completed'?'ok':'warn'];
  const sig=label+tone;if(n.ccR.state.ccSig!==sig){n.ccR.state.ccSig=sig;n.ccR.state.replaceChildren(chip(label,tone));}
  n.ccR.link.href='/flow?run='+encodeURIComponent(r.run_id);n.ccR.link.id='cc-open-'+r.run_id;n.ccR.link.onclick=e=>ccOpenRun(e,r.run_id);
  ccText(n.ccR.link,t('cc.run.open'));n.ccR.link.setAttribute('aria-label',t('cc.run.open.label',{name:r.name||r.run_id}));
 });
}
function ccPaint(){
 const root=typeof document!=='undefined'?$('screen-overview'):null;
 if(!root||route!=='/overview')return;
 if(typeof refreshBrief==='function')refreshBrief();
 if(!connected){ccDom=null;root.replaceChildren(h('section',{class:'panel'},empty('cc.connect.t','cc.connect.x')));return;}
 if(!ccState){ccDom=null;root.replaceChildren(h('section',{class:'panel'},ccError?h('p',{class:'hint bad',text:ccError}):empty('cc.loading.t','cc.loading.x')));return;}
 const active=document.activeElement,activeId=active&&root.contains(active)?active.id:null;
 if(!ccDom||ccDom.lang!==language||!root.contains(ccDom.root)||ccDom.faultCards.length!==ccState.catalog.faults.length)ccBuild(root);
 const d=ccDom,s=ccState;
 ccUpdateStatus(d,s);ccUpdateGuide(d,s);ccUpdateKpis(d,s);ccUpdateSensors(d,s);ccUpdateIncidents(d,s);ccUpdateConsole(d,s);ccUpdateAgents(d,s);
 ccText(d.error,ccError);d.error.hidden=!ccError;
 if(activeId&&document.activeElement!==document.getElementById(activeId))document.getElementById(activeId)?.focus({preventScroll:true});
}
// Called by the router for /overview: paints and keeps the once-per-second poll running while the page is visible.
function commandRender(){
 ccPaint();
 if(connected&&!ccTimer&&!ccInflight)ccSchedule(0);
}
function commandBrief(){
 const b=ccBrief(ccState,connected,ccError),fmt=p=>Object.fromEntries(Object.entries(p).map(([k,v])=>[k,k==='state'?t('cc.state.'+v):typeof v==='number'?N(v):v]));
 return {happened:b.happened.map(x=>t(x.key,fmt(x.params))).join(' '),next:t(b.next.key,fmt(b.next.params))};
}
if(typeof document!=='undefined'){
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')ccStop();else if(ccWanted())ccSchedule(0);});
 ccNarrow?.addEventListener?.('change',()=>{if(route==='/overview')ccPaint();});
}
