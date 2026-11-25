'use strict';
// Agent flow page: start a run of the 36 agents on a file and watch it live. Every state, edge, meter and sentence on
// this page is derived from a run event (Server-Sent Events of /api/agents/stream) or from the sealed run record;
// nothing is simulated. The reducer, the SSE parser, the event sentences and the layout are pure and tested in Node.

// ---------- pure core (also used by test_flow.cjs) ----------
const FLOW_IDS=Array.from({length:36},(_,i)=>'A'+String(i+1).padStart(2,'0'));
const FLOW_LAYERS=[['orchestration',1,6],['specialists',7,22],['reasoning',23,28],['remediation',29,32],['governance',33,36]];
const FLOW_TYPES=['run_started','agent_selected','agent_skipped','agent_started','tool_call','llm_call','retrieval','cache','agent_finished','judge_verdict','approval_requested','run_finished'];
const FLOW_STATES=['idle','selected','running','completed','needs_evidence','denied','skipped','failed'];
const FLOW_STATUS_STATE={COMPLETED:'completed',NEEDS_EVIDENCE:'needs_evidence',POLICY_DENIED:'denied',SKIPPED:'skipped',FAILED:'failed'};
const FLOW_LIMITS={specialists:8,llm_calls:12,tokens:40000,elapsed_ms:90000};
const FLOW_SERVICES=['LLM','MCP','KB'];
// Edge kind -> the transport it travelled over. Dependencies (results read from earlier agents) and Judge verdicts
// stay in this process; tool calls carry their own transport in the event.
const FLOW_EDGE_TRANSPORT={dependency:'in_process',verdict:'in_process',mcp:'mcp_local',a2a:'a2a_mtls',llm:'local_llm'};
const flowLayer=id=>{const n=Number(String(id).slice(1));const l=FLOW_LAYERS.find(([,lo,hi])=>n>=lo&&n<=hi);return l?l[0]:null;};
const flowIsSpecialist=id=>flowLayer(id)==='specialists';

function flowNode(id){
 return {id,state:'idle',selected:false,reason:null,errorCode:null,unmet:[],wave:null,stage:null,attempt:0,dependsOn:[],budget:null,
  transport:null,usage:null,claims:null,evidenceRefs:null,proposals:null,certificates:null,abandoned:false,runtime:false,finished:false,
  tools:[],llm:[],retrieval:null,cache:[],verdicts:[],approval:null};
}
function flowInitial(){
 const nodes={};for(const id of FLOW_IDS)nodes[id]=flowNode(id);
 return {runId:null,status:'idle',lastSeq:0,count:0,limits:{...FLOW_LIMITS},used:{specialists:0,llm_calls:0,tokens:0,elapsed_ms:0},
  plan:null,nodes,edges:[],timeline:[],waves:[],judge:{accepted:0,advisory:0,rejected:0},approval:null,finished:null,milestone:null};
}
function flowAddEdge(s,from,to,kind,transport,seq){
 const key=`${from}>${to}:${kind}`,at=s.edges.findIndex(e=>e.key===key);
 s.edges=at===-1?[...s.edges,{key,from,to,kind,transport,count:1,seq}]:s.edges.map((e,i)=>i===at?{...e,count:e.count+1,transport}:e);
}
function flowUsage(nodes){
 let llm=0,tokens=0;
 for(const id of FLOW_IDS){const u=nodes[id].usage;if(u){llm+=u.llm_calls;tokens+=u.tokens_in+u.tokens_out;}}
 return {llm_calls:llm,tokens,specialists:FLOW_IDS.filter(id=>flowIsSpecialist(id)&&nodes[id].attempt>0).length};
}
// events -> node states, edges, budgets, timeline. Pure: returns a new state and never mutates its input.
// An event whose seq is not above the last one applied is a replay (stream reconnect) and changes nothing.
function reduceFlow(state,event){
 if(!event||typeof event!=='object'||!Number.isInteger(event.seq)||event.seq<=state.lastSeq)return state;
 const id=event.agent_id,d=event.data&&typeof event.data==='object'?event.data:{},type=event.type;
 if(!FLOW_IDS.includes(id)||!FLOW_TYPES.includes(type))return {...state,lastSeq:event.seq};
 const t_ms=Number.isFinite(event.t_ms)?event.t_ms:0;
 const s={...state,lastSeq:event.seq,count:state.count+1,nodes:{...state.nodes},used:{...state.used,elapsed_ms:Math.max(state.used.elapsed_ms,t_ms)},
  timeline:[...state.timeline,{seq:event.seq,t_ms,agent:id,type,data:d}]};
 const node=s.nodes[id]={...state.nodes[id]};
 const mark=(key,params={})=>{s.milestone={key,params,seq:event.seq};};
 switch(type){
  case 'run_started':
   s.runId=d.run_id??null;s.status='running';s.plan=d.transport_plan??null;if(d.limits)s.limits={...d.limits};mark('flow.ms.started');break;
  case 'agent_selected':
   node.selected=true;node.reason=d.reason??null;if(node.state==='idle'||node.state==='skipped')node.state='selected';break;
  case 'agent_skipped':
   node.reason=d.reason??null;node.errorCode=d.error_code??null;node.unmet=[...(d.unmet||[])];if(!node.finished&&node.state!=='running')node.state='skipped';break;
  case 'agent_started':
   node.state='running';node.wave=d.wave??null;node.stage=d.stage??null;node.attempt=d.attempt??node.attempt+1;node.finished=false;
   node.dependsOn=[...(d.depends_on||[])];node.budget=d.budget?{...d.budget}:null;
   for(const dep of node.dependsOn)if(FLOW_IDS.includes(dep))flowAddEdge(s,dep,id,'dependency','in_process',event.seq);
   if(d.wave!=null&&!s.waves.some(w=>w.wave===d.wave)){s.waves=[...s.waves,{wave:d.wave,stage:d.stage}];mark('flow.ms.wave',{wave:d.wave,stage:d.stage});}
   break;
  case 'tool_call':
   node.tools=[...node.tools,{...d,seq:event.seq,t_ms}];
   if(d.tool==='knowledge_retrieve')flowAddEdge(s,id,'KB','rag',d.transport,event.seq);
   else if(d.transport==='mcp_local')flowAddEdge(s,id,'MCP','mcp','mcp_local',event.seq);
   break;
  case 'llm_call':
   node.llm=[...node.llm,{...d,seq:event.seq,t_ms}];flowAddEdge(s,id,'LLM','llm','local_llm',event.seq);break;
  case 'retrieval':node.retrieval={...d,sources:[...(d.sources||[])]};break;
  case 'cache':node.cache=[...node.cache,{...d}];break;
  case 'agent_finished':
   node.state=FLOW_STATUS_STATE[d.status]||'failed';node.finished=true;node.errorCode=d.error_code??null;node.transport=d.transport??null;
   node.usage=d.usage?{...d.usage}:null;node.claims=d.claims??null;node.evidenceRefs=d.evidence_refs??null;node.proposals=d.proposals??null;
   node.certificates=d.certificates?{...d.certificates}:null;node.abandoned=!!d.abandoned;node.runtime=!!d.runtime;
   if(d.attempt)node.attempt=d.attempt;
   if(id==='A27'&&d.transport==='a2a_mtls')flowAddEdge(s,'A01','A27','a2a','a2a_mtls',event.seq);
   if(node.state==='failed')mark('flow.ms.failed',{agent:id});
   break;
  case 'judge_verdict':{
   const subject=d.subject,entry={pass:d.pass,accepted:d.accepted||0,advisory:d.advisory||0,rejected:d.rejected||0,verdicts:(d.verdicts||[]).map(v=>({...v}))};
   s.judge={accepted:s.judge.accepted+entry.accepted,advisory:s.judge.advisory+entry.advisory,rejected:s.judge.rejected+entry.rejected};
   if(FLOW_IDS.includes(subject)){
    const target=subject===id?node:(s.nodes[subject]={...s.nodes[subject]});
    target.verdicts=[...target.verdicts,entry];flowAddEdge(s,'A27',subject,'verdict','in_process',event.seq);
   }
   if(!state.timeline.some(e=>e.type==='judge_verdict'&&e.data.pass===d.pass))mark('flow.ms.judge',{pass:d.pass});
   break;}
  case 'approval_requested':
   s.approval={...d};node.approval={...d};mark('flow.ms.approval',{n:d.items??0});break;
  case 'run_finished':
   s.status=d.status||'completed';s.finished={...d,budget_exceeded:[...(d.budget_exceeded||[])]};
   if(Number.isFinite(d.duration_ms))s.used.elapsed_ms=d.duration_ms;mark('flow.ms.finished',{status:s.status});break;
 }
 if(type==='agent_started'||type==='agent_finished')Object.assign(s.used,flowUsage(s.nodes));
 return s;
}
const reduceAll=(events,state=flowInitial())=>events.reduce(reduceFlow,state);

// Server-Sent Events framing: returns complete frames and the unfinished remainder of the buffer.
function parseSse(buffer){
 let rest=String(buffer).replace(/\r\n?/g,'\n');
 if(rest.endsWith('\r'))rest=rest.slice(0,-1)+'\r';
 const frames=[];let cut;
 while((cut=rest.indexOf('\n\n'))!==-1){
  const block=rest.slice(0,cut);rest=rest.slice(cut+2);
  let id=null,event='message';const data=[];
  for(const line of block.split('\n')){
   if(!line||line.startsWith(':'))continue;
   const colon=line.indexOf(':'),field=colon===-1?line:line.slice(0,colon);let value=colon===-1?'':line.slice(colon+1);
   if(value.startsWith(' '))value=value.slice(1);
   if(field==='id')id=value;else if(field==='event')event=value;else if(field==='data')data.push(value);
  }
  if(data.length||event!=='message')frames.push({id,event,data:data.join('\n')});
 }
 return {frames,rest};
}

// One plain-language sentence per event: a string key and its parameters. ``label(kind,value)`` turns codes into words.
function flowEventText(entry,label=(kind,value)=>String(value)){
 const d=entry.data||{},a=entry.agent,ms=v=>label('ms',v??0);
 switch(entry.type){
  case 'run_started':return {key:'flow.ev.run_started',params:{tools:label('transport',d.transport_plan?.tools?.mode),judge:label('transport',d.transport_plan?.judge?.mode)}};
  case 'agent_selected':return {key:'flow.ev.agent_selected',params:{agent:a,reason:label('reason',d.reason)}};
  case 'agent_skipped':return {key:d.unmet?.length?'flow.ev.agent_skipped.unmet':'flow.ev.agent_skipped',params:{agent:a,reason:label('reason',d.reason),code:label('code',d.error_code),unmet:(d.unmet||[]).join(', ')}};
  case 'agent_started':return {key:'flow.ev.agent_started',params:{agent:a,wave:d.wave,stage:label('stage',d.stage),attempt:d.attempt}};
  case 'tool_call':return {key:d.phase==='intake'?'flow.ev.tool_call.intake':'flow.ev.tool_call',params:{agent:a,tool:d.tool,transport:label('transport',d.transport),outcome:label('outcome',d.outcome),ms:ms(d.latency_ms)}};
  case 'llm_call':return {key:d.ok?'flow.ev.llm_call':'flow.ev.llm_call.failed',params:{agent:a,model:d.model,tokens:(d.tokens_in||0)+(d.tokens_out||0),ms:ms(d.latency_ms),cache:label('cache',d.cache),code:label('code',d.error_code)}};
  case 'retrieval':return {key:'flow.ev.retrieval',params:{agent:a,n:d.citations??0,sources:(d.sources||[]).join(', ')||'—'}};
  case 'cache':return {key:'flow.ev.cache',params:{agent:a,result:label('cache',d.result)}};
  case 'agent_finished':return {key:d.error_code?'flow.ev.agent_finished.code':'flow.ev.agent_finished',params:{agent:a,status:label('status',d.status),code:label('code',d.error_code),claims:d.claims??0,refs:d.evidence_refs??0,transport:label('transport',d.transport)}};
  case 'judge_verdict':return {key:'flow.ev.judge_verdict',params:{pass:label('pass',d.pass),subject:d.subject,accepted:d.accepted??0,advisory:d.advisory??0,rejected:d.rejected??0}};
  case 'approval_requested':return {key:'flow.ev.approval_requested',params:{n:d.items??0}};
  case 'run_finished':return {key:'flow.ev.run_finished',params:{status:label('runstatus',d.status),ms:ms(d.duration_ms)}};
 }
 return {key:'flow.ev.unknown',params:{type:String(entry.type)}};
}
const flowSorted=timeline=>[...timeline].sort((x,y)=>x.t_ms-y.t_ms||x.seq-y.seq);

// Diagram geometry: five lanes side by side (wide) or stacked (narrow), plus a row for the local services.
const FLOW_NODE={w:154,h:64};
function flowLayout(narrow=false){
 const w=FLOW_NODE.w,hgt=FLOW_NODE.h,gap=12,pad=12,head=30,pitch=hgt+gap,pos={},lanes=[];
 if(!narrow){
  const cols={orchestration:1,specialists:2,reasoning:1,remediation:1,governance:1};
  let x=0;const rows=8,height=head+pad+rows*pitch;
  for(const [layer,lo,hi] of FLOW_LAYERS){
   const c=cols[layer],per=Math.ceil((hi-lo+1)/c),laneW=c*w+(c-1)*gap+2*pad;
   lanes.push({layer,x,y:0,w:laneW,h:height});
   for(let n=lo;n<=hi;n++){const i=n-lo,col=Math.floor(i/per),row=i%per;pos[FLOW_IDS[n-1]]={x:x+pad+col*(w+gap),y:head+pad+row*pitch,w,h:hgt};}
   x+=laneW+16;
  }
  const width=x-16,sy=lanes[0].h+24;
  FLOW_SERVICES.forEach((k,i)=>{pos[k]={x:pad+i*(width-2*pad-w)/2,y:sy+head,w,h:hgt-8};});
  return {width,height:sy+head+hgt+8,lanes,pos,services:{y:sy,h:head+hgt}};
 }
 const width=2*w+gap+2*pad;let y=0;
 for(const [layer,lo,hi] of FLOW_LAYERS){
  const rows=Math.ceil((hi-lo+1)/2),laneH=head+pad+rows*pitch;
  lanes.push({layer,x:0,y,w:width,h:laneH});
  for(let n=lo;n<=hi;n++){const i=n-lo;pos[FLOW_IDS[n-1]]={x:pad+(i%2)*(w+gap),y:y+head+pad+Math.floor(i/2)*pitch,w,h:hgt};}
  y+=laneH+12;
 }
 const sy=y;
 FLOW_SERVICES.forEach((k,i)=>{pos[k]={x:pad+(i%2)*(w+gap),y:sy+head+Math.floor(i/2)*(hgt+gap),w,h:hgt-8};});
 return {width,height:sy+head+2*(hgt+gap),lanes,pos,services:{y:sy,h:head+2*(hgt+gap)}};
}
// A curve between two boxes, leaving and entering on the sides that face each other.
function flowEdgePath(a,b){
 const ax=a.x+a.w/2,ay=a.y+a.h/2,bx=b.x+b.w/2,by=b.y+b.h/2,dx=bx-ax,dy=by-ay;
 let x1,y1,x2,y2,c1,c2;
 if(Math.abs(dx)>=a.w*0.9){x1=dx>0?a.x+a.w:a.x;y1=ay;x2=dx>0?b.x:b.x+b.w;y2=by;const k=Math.max(24,Math.abs(x2-x1)/2)*Math.sign(dx);c1=[x1+k,y1];c2=[x2-k,y2];}
 else{x1=ax;y1=dy>0?a.y+a.h:a.y;x2=bx;y2=dy>0?b.y:b.y+b.h;const k=Math.max(18,Math.abs(y2-y1)/2)*Math.sign(dy||1);c1=[x1+(dx?0:28),y1+k];c2=[x2+(dx?0:28),y2-k];}
 return {d:`M${x1} ${y1} C${c1[0]} ${c1[1]} ${c2[0]} ${c2[1]} ${x2} ${y2}`,mid:[(x1+3*c1[0]+3*c2[0]+x2)/8,(y1+3*c1[1]+3*c2[1]+y2)/8]};
}

if(typeof module!=='undefined')module.exports={FLOW_IDS,FLOW_LAYERS,FLOW_TYPES,FLOW_STATES,FLOW_SERVICES,FLOW_EDGE_TRANSPORT,flowLayer,flowInitial,reduceFlow,reduceAll,parseSse,flowEventText,flowSorted,flowLayout,flowEdgePath};

// ---------- browser page ----------
let flowRoles=null,flowRolesLoading=false,flowRuns=null,flowRunsLoading=false,flowRunId=null,flowState=flowInitial(),flowDetail=null,flowAbort=null,
 flowEnd=null,flowBusy=false,flowError='',flowOpen=null,flowOpener=null,flowFocus='A01',flowAll=false,flowFrame=0,flowAnnounced=0,flowCtl=null,flowDyn=null,
 flowBaseline='',flowAsOf='',flowOwnFile=null,flowSecond=null;
const flowOpenDetails=new Set(),flowSeenEdges=new Set();
const FLOW_MAX_BYTES=1000000,FLOW_TIMELINE_ROWS=300;
const flowNarrowQuery=typeof matchMedia==='function'?matchMedia('(max-width: 900px)'):null;

const flowLabel=(kind,value)=>{
 if(value===null||value===undefined||value==='')return '—';
 if(kind==='ms')return msText(Number(value));
 const prefix={transport:'flow.tr.',reason:'flow.why.',code:'flow.code.',stage:'flow.stage.',outcome:'flow.outcome.',cache:'flow.cache.',status:'flow.state.',pass:'flow.pass.',runstatus:'flow.status.'}[kind];
 if(kind==='status')return tt(prefix+(FLOW_STATUS_STATE[value]||value),String(value));
 return prefix?tt(prefix+value,String(value).replace(/_/g,' ')):String(value);
};
const flowName=id=>tt('flow.name.'+id,id);
const flowRole=id=>flowRoles?.roles?.find(r=>r.agent_id===id)||null;
const flowRecordAgent=id=>flowDetail?.record?.agents?.find(a=>a.agent_id===id)||null;
function flowSchedule(){
 if(flowFrame||typeof requestAnimationFrame!=='function')return;
 flowFrame=requestAnimationFrame(()=>{flowFrame=0;if(route==='/flow')flowPaint($('screen-flow'));});
}
async function loadFlowRoles(){
 if(flowRoles||flowRolesLoading||!connected)return;
 flowRolesLoading=true;
 try{flowRoles=await request('/api/agents/roles');}catch(error){setNotice(error.message,true);}
 flowRolesLoading=false;flowSchedule();
}
async function loadFlowRuns(force=false){
 if(flowRunsLoading||(flowRuns&&!force)||!connected)return;
 flowRunsLoading=true;
 try{flowRuns=await request('/api/agents/runs');}catch(error){setNotice(error.message,true);}
 flowRunsLoading=false;flowSchedule();
}
async function loadFlowDetail(runId){
 try{const detail=await request('/api/agents/runs/'+runId);if(flowRunId===runId)flowDetail=detail;}
 catch(error){if(flowRunId===runId)flowError=error.status===404?t('flow.err.gone'):error.message;}
 flowSchedule();
}
// Fetch-based SSE: the session token travels in the Authorization header, never in the URL. A dropped connection
// resumes with Last-Event-ID; the reducer ignores anything it already applied.
async function streamFlow(runId){
 flowAbort?.abort();
 const control=new AbortController();flowAbort=control;
 let tries=0,ended=false;
 while(!ended&&!control.signal.aborted&&tries<6){
  try{
   const headers={Authorization:'Bearer '+token};
   if(flowState.lastSeq)headers['Last-Event-ID']=String(flowState.lastSeq);
   const response=await fetch('/api/agents/stream?run='+encodeURIComponent(runId),{headers,cache:'no-store',signal:control.signal});
   if(response.status===404){flowError=t('flow.err.gone');break;}
   if(!response.ok||!response.body)throw new Error('stream');
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
   for(;;){
    const {value,done}=await reader.read();
    if(done)break;
    const parsed=parseSse(buffer+decoder.decode(value,{stream:true}));buffer=parsed.rest;
    for(const frame of parsed.frames){
     if(frame.event==='agent'){try{flowState=reduceFlow(flowState,JSON.parse(frame.data));tries=0;}catch{}}
     else if(frame.event==='end'){ended=true;try{flowEnd=JSON.parse(frame.data);}catch{flowEnd={error:'RUN_FAILED'};}}
    }
    flowSchedule();
   }
  }catch{if(control.signal.aborted)return;}
  if(!ended&&!control.signal.aborted){tries++;await new Promise(r=>setTimeout(r,Math.min(5000,400*2**tries)));}
 }
 if(control.signal.aborted||flowAbort!==control)return;
 flowAbort=null;
 if(ended)await loadFlowDetail(runId);else if(!flowError)flowError=t('flow.err.stream');
 loadFlowRuns(true);flowSchedule();
}
function viewFlowRun(runId){
 flowAbort?.abort();flowAbort=null;
 if(route==='/flow'&&typeof history!=='undefined')history.replaceState({},'',runId?'/flow?run='+encodeURIComponent(runId):'/flow');
 flowRunId=runId||null;flowState=flowInitial();flowDetail=null;flowEnd=null;flowError='';flowOpen=null;flowSeenEdges.clear();flowAnnounced=0;
 if(flowRunId)streamFlow(flowRunId);
 flowSchedule();
}
function flowFile(){return flowOwnFile||selectedFile||null;}
function flowAsOfValue(){
 const entry=(blList?.baselines||[]).find(b=>b.name===flowBaseline);
 if(!flowAsOf||entry?.time_aware!==true)return flowAsOf||undefined;
 const instant=new Date(flowAsOf);
 return Number.isNaN(instant.getTime())?flowAsOf:instant.toISOString().replace(/\.\d{3}Z$/,'Z');
}
async function startFlowRun(){
 const file=flowFile();
 if(flowBusy||!file||!requireSession())return;
 if(file.size>FLOW_MAX_BYTES||(flowSecond&&flowSecond.size>FLOW_MAX_BYTES)){flowError=t('err.size');flowSchedule();return;}
 flowBusy=true;flowError='';flowSchedule();
 try{
  const body={csv_b64:await blBase64(file),name:file.name};
  if(flowSecond)body.second_csv_b64=await blBase64(flowSecond);
  if(flowBaseline)body.baseline=flowBaseline;
  const asOf=flowAsOfValue();if(asOf)body.as_of=asOf;
  const started=await request('/api/agents/run','POST',JSON.stringify(body),JSON_HEADERS);
  flowBusy=false;viewFlowRun(started.run_id);loadFlowRuns(true);
  return;
 }catch(error){flowError=error.status===404?t('bl.err.notfound'):error.message;}
 flowBusy=false;flowSchedule();
 document.getElementById('flow-start')?.focus();
}
// Start an agent run on ``file`` from another page (Data sources, baseline panel) and open its live flow.
async function investigateWithAgents(file,options={}){
 if(!file||!requireSession())return null;
 if(file.size>FLOW_MAX_BYTES){setNotice(t('err.size'),true);return null;}
 try{
  const body={csv_b64:await blBase64(file),name:file.name};
  if(options.mapping&&Object.keys(options.mapping).length)body.mapping=options.mapping;
  if(options.baseline){body.baseline=options.baseline;if(options.asOf)body.as_of=options.asOf;}
  const started=await request('/api/agents/run','POST',JSON.stringify(body),JSON_HEADERS);
  openFlowRun(started.run_id);
  if(options.note)setNotice(options.note);
  return started.run_id;
 }catch(error){setNotice(t('flow.err.start',{reason:error.message}),true);return null;}
}
function openFlowRun(runId){
 viewFlowRun(runId);loadFlowRuns(true);navigate('/flow');
 history.replaceState({},'','/flow?run='+encodeURIComponent(runId));
}
async function decideFlow(item,decision){
 if(!flowDetail||!requireSession())return;
 try{
  const result=await request('/api/agents/approval','POST',JSON.stringify({run_id:flowDetail.run_id,item,decision}),JSON_HEADERS);
  flowDetail={...flowDetail,decisions:result.decisions};
  document.getElementById('flow-live').textContent=t('flow.approval.recorded',{n:item+1,decision:t('flow.decision.'+decision)});
 }catch(error){setNotice(error.message,true);}
 flowSchedule();
}

// ---------- small pieces ----------
function flowIcon(state){
 const svg=svgEl('svg',{viewBox:'0 0 16 16',class:'fl-icon '+state,'aria-hidden':'true',focusable:'false'});
 flowIconShapes(svg,state);return svg;
}
function flowIconShapes(g,state){
 const add=(tag,attrs)=>g.append(svgEl(tag,attrs));
 if(state==='completed'){add('circle',{cx:8,cy:8,r:6.5});add('path',{d:'M5 8.3 7.1 10.4 11 6.2'});}
 else if(state==='running'){add('circle',{cx:8,cy:8,r:6.5,class:'fl-faint'});add('path',{d:'M8 1.5A6.5 6.5 0 0 1 14.5 8'});}
 else if(state==='selected'){add('circle',{cx:8,cy:8,r:6.5});add('circle',{cx:8,cy:8,r:2.4,class:'fl-solid'});}
 else if(state==='needs_evidence'){add('path',{d:'M8 1.8 14.6 13.6H1.4Z'});add('path',{d:'M8 6v3.6M8 11.4v.3'});}
 else if(state==='denied'){add('circle',{cx:8,cy:8,r:6.5});add('path',{d:'M3.6 12.4 12.4 3.6'});}
 else if(state==='failed'){add('circle',{cx:8,cy:8,r:6.5});add('path',{d:'M5.5 5.5l5 5M10.5 5.5l-5 5'});}
 else if(state==='skipped'){add('circle',{cx:8,cy:8,r:6.5,'stroke-dasharray':'2.4 2'});add('path',{d:'M5 8h6'});}
 else add('circle',{cx:8,cy:8,r:6.5,'stroke-dasharray':'1 2.2'});
}
const flowStateChip=state=>h('span',{class:'fl-state '+state},flowIcon(state),t('flow.state.'+state));
function flowPre(key,label,value){
 const details=h('details',{class:'fl-json','data-key':key,open:flowOpenDetails.has(key),ontoggle:e=>{if(e.target.open)flowOpenDetails.add(key);else flowOpenDetails.delete(key);}},
  h('summary',{id:'fl-sum-'+key.replace(/[^a-z0-9]/gi,'-'),text:label}),h('pre',{text:JSON.stringify(value,null,2)}));
 return details;
}
const flowParams=params=>Object.entries(params||{}).map(([k,v])=>`${k}: ${Array.isArray(v)?v.join(', '):v}`).join(' · ');
const flowKv=(label,value)=>h('div',{class:'fl-kv'},h('dt',{text:label}),h('dd',{},value));
function flowCode(text,short=0){return h('code',{title:short?text:null,text:short&&text.length>short?text.slice(0,short)+'…':text});}

// ---------- controls (built once, updated in place so a live run never closes an open select or drops a file) ----------
function flowControls(){
 if(!flowCtl){
  const c=flowCtl={};
  c.title=h('h2',{id:'flow-run-title'});c.intro=h('p',{class:'hint'});
  c.fileLabel=h('label',{for:'flow-file'});c.file=h('input',{id:'flow-file',type:'file',accept:'.csv,text/csv','aria-describedby':'flow-file-state'});
  c.fileState=h('small',{id:'flow-file-state','aria-live':'polite'});
  c.file.onchange=e=>{flowOwnFile=e.target.files[0]||null;flowError='';flowSchedule();};
  c.secondLabel=h('label',{for:'flow-second'});c.second=h('input',{id:'flow-second',type:'file',accept:'.csv,text/csv','aria-describedby':'flow-second-x'});
  c.secondHint=h('small',{id:'flow-second-x'});c.second.onchange=e=>{flowSecond=e.target.files[0]||null;flowSchedule();};
  c.baselineLabel=h('label',{for:'flow-baseline'});c.baseline=h('select',{id:'flow-baseline','aria-describedby':'flow-baseline-x'});c.baselineHint=h('small',{id:'flow-baseline-x'});
  c.baseline.onchange=e=>{flowBaseline=e.target.value;flowSchedule();};
  c.asOfLabel=h('label',{for:'flow-asof'});c.asOf=h('input',{id:'flow-asof',type:'datetime-local',step:'1','aria-describedby':'flow-asof-x'});c.asOfHint=h('small',{id:'flow-asof-x'});
  c.asOf.oninput=e=>{flowAsOf=e.target.value;};
  c.start=h('button',{id:'flow-start',type:'submit',class:'primary'});
  c.error=h('p',{class:'hint bad',role:'alert'});c.store=h('p',{class:'hint'});
  c.runLabel=h('label',{for:'flow-run'});c.run=h('select',{id:'flow-run'});c.run.onchange=e=>viewFlowRun(e.target.value);
  c.runSig=null;c.baseSig=null;
  const field=(...kids)=>h('div',{class:'fl-field'},...kids);
  c.section=h('section',{class:'panel fl-controls','aria-labelledby':'flow-run-title'},
   h('div',{class:'panel-heading'},c.title),c.intro,
   h('form',{class:'fl-form',novalidate:true,onsubmit:e=>{e.preventDefault();startFlowRun();}},
    field(c.fileLabel,c.file,c.fileState),field(c.secondLabel,c.second,c.secondHint),field(c.baselineLabel,c.baseline,c.baselineHint),
    field(c.asOfLabel,c.asOf,c.asOfHint),h('div',{class:'fl-field fl-submit'},c.start)),
   c.error,h('div',{class:'fl-field fl-runpick'},c.runLabel,c.run),c.store);
 }
 const c=flowCtl,file=flowFile(),running=!!flowRuns?.active||flowState.status==='running';
 c.title.textContent=t('flow.run.title');c.intro.textContent=t('flow.run.intro');
 c.fileLabel.textContent=t('flow.file');c.secondLabel.textContent=t('flow.second');c.secondHint.textContent=t('flow.second.x');
 c.fileState.textContent=file?t('flow.file.using',{name:file.name,source:t(flowOwnFile?'flow.file.here':'flow.file.sources')}):t('flow.file.none');
 c.baselineLabel.textContent=t('flow.baseline');c.baselineHint.textContent=t('flow.baseline.x');c.asOfLabel.textContent=t('flow.asof');c.asOfHint.textContent=t('flow.asof.x');
 const names=(blList?.baselines||[]).map(b=>b.name),baseSig=language+'|'+names.join('|');
 if(flowBaseline&&!names.includes(flowBaseline))flowBaseline='';
 if(c.baseSig!==baseSig){c.baseSig=baseSig;c.baseline.replaceChildren(h('option',{value:'',text:t('flow.baseline.none')}),...names.map(n=>h('option',{value:n,text:n})));}
 c.baseline.value=flowBaseline;c.asOf.disabled=!flowBaseline;
 c.start.textContent=t(flowBusy?'flow.starting':'flow.start');
 c.start.disabled=flowBusy||!file||running||!connected;
 c.error.textContent=flowError;c.error.hidden=!flowError;
 c.runLabel.textContent=t('flow.pick');
 const runs=flowRuns?.runs||[],runSig=language+'|'+(flowRunId||'')+'|'+runs.map(r=>r.run_id+r.state+r.status).join('|');
 if(c.runSig!==runSig){
  c.runSig=runSig;
  c.run.replaceChildren(h('option',{value:'',text:runs.length?t('flow.pick.none'):t('flow.pick.empty')}),...runs.map(r=>h('option',{value:r.run_id,
   text:`${when(r.started_at)} · ${r.input?.name||r.input?.sha256?.slice(0,8)||r.run_id} · ${r.state==='running'?t('flow.status.running'):r.state==='error'?t('flow.status.error'):flowLabel('runstatus',r.status)}`})));
 }
 c.run.value=flowRunId||'';c.run.disabled=!runs.length;
 const store=flowRuns?.rejected_on_load?'flow.store.rejected':flowRuns?.store_error?'flow.store.error':flowRuns?.retained?'flow.store.kept':null;
 c.store.textContent=store?t(store):'';c.store.hidden=!store;c.store.classList.toggle('bad',store==='flow.store.rejected'||store==='flow.store.error');
 return c.section;
}

// ---------- header strip: status, elapsed time and budget meters ----------
function flowMeter(id,key,used,limit,format){
 const over=limit>0&&used>=limit,ratio=limit>0?Math.min(1,used/limit):0,text=t('flow.meter.of',{used:format(used),limit:format(limit)});
 const fill=h('div',{class:'fm-fill'+(over?' over':'')});fill.style.width=(ratio*100).toFixed(1)+'%';
 return h('div',{class:'fm'+(over?' over':'')},
  h('span',{class:'fm-label',id:'fm-'+id,text:t(key)}),h('strong',{text}),
  h('div',{class:'fm-track',role:'meter','aria-labelledby':'fm-'+id,'aria-valuemin':'0','aria-valuemax':String(limit),'aria-valuenow':String(Math.min(used,limit)),'aria-valuetext':text},fill),
  over?h('small',{class:'fm-note',text:t('flow.meter.reached')}):null);
}
function flowStatus(){
 if(flowEnd?.error)return ['error','bad'];
 const s=flowState.status;
 return [s,{idle:'muted',running:'info',completed:'ok',completed_with_gaps:'warn',failed_agents:'bad',budget_exceeded:'warn',input_rejected:'bad'}[s]||'muted'];
}
function flowHeader(){
 const st=flowState,[status,tone]=flowStatus(),u=st.used,l=st.limits,n=v=>N(v);
 return h('section',{class:'panel fl-strip','aria-label':t('flow.strip')},
  h('div',{class:'fl-strip-status'},h('span',{class:'fl-strip-label',text:t('flow.status')}),chip(t('flow.status.'+status),tone),
   h('span',{class:'fl-strip-label',text:t('flow.elapsed')}),h('strong',{text:msText(u.elapsed_ms)}),
   h('small',{text:flowRunId?t('flow.events',{n:N(st.count),id:flowRunId}):t('flow.norun')})),
  h('div',{class:'fm-grid'},flowMeter('spec','flow.meter.specialists',u.specialists,l.specialists,n),flowMeter('llm','flow.meter.llm',u.llm_calls,l.llm_calls,n),
   flowMeter('tok','flow.meter.tokens',u.tokens,l.tokens,n),flowMeter('time','flow.meter.time',u.elapsed_ms,l.elapsed_ms,v=>msText(v))),
  st.finished?.budget_exceeded?.length?h('p',{class:'hint bad',text:t('flow.exceeded',{limits:st.finished.budget_exceeded.map(k=>t('flow.limit.'+k)).join(', ')})}):null,
  flowEnd?.error?h('p',{class:'hint bad',text:t('flow.err.run')}):null);
}

// ---------- the diagram ----------
function flowNodeLabel(id){
 const n=flowState.nodes[id];
 return t('flow.node.label',{id,name:flowName(id),state:t('flow.state.'+n.state),wave:n.wave?t('flow.wave',{n:n.wave}):t('flow.nowave')});
}
function flowMoveFocus(id){flowFocus=id;document.querySelectorAll('#flow-svg .fn').forEach(g=>g.setAttribute('tabindex',g.dataset.id===id?'0':'-1'));document.getElementById('fn-'+id)?.focus();}
function flowKeys(event){
 const g=event.target.closest?.('.fn');if(!g)return;
 const i=FLOW_IDS.indexOf(g.dataset.id);let next=null;
 if(event.key==='ArrowRight'||event.key==='ArrowDown')next=FLOW_IDS[Math.min(35,i+1)];
 else if(event.key==='ArrowLeft'||event.key==='ArrowUp')next=FLOW_IDS[Math.max(0,i-1)];
 else if(event.key==='Home')next=FLOW_IDS[0];else if(event.key==='End')next=FLOW_IDS[35];
 else if(event.key==='Enter'||event.key===' '){event.preventDefault();openFlowAgent(g.dataset.id);return;}
 if(next){event.preventDefault();flowMoveFocus(next);}
}
function openFlowAgent(id,opener){
 flowOpen=id;flowFocus=FLOW_IDS.includes(id)?id:flowFocus;flowOpener=opener||'fn-'+id;
 flowPaint($('screen-flow'));
 document.getElementById('flow-drawer-close')?.focus();
}
function closeFlowAgent(){
 if(!flowOpen)return;
 const back=flowOpener;flowOpen=null;flowPaint($('screen-flow'));
 (document.getElementById(back)||document.getElementById('fn-'+flowFocus))?.focus();
}
function flowSvg(){
 const narrow=!!flowNarrowQuery?.matches,L=flowLayout(narrow),st=flowState;
 const svg=svgEl('svg',{id:'flow-svg',viewBox:`0 0 ${L.width} ${L.height}`,class:'fl-svg'+(narrow?' narrow':''),role:'group','aria-label':t('flow.diagram.label'),'aria-describedby':'flow-legend'});
 svg.addEventListener('keydown',flowKeys);
 svg.append(svgEl('defs',{},...['dep','tool','a2a','llm','verdict'].map(k=>svgEl('marker',{id:'fa-'+k,viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'6',markerHeight:'6',orient:'auto-start-reverse'},svgEl('path',{d:'M0 0 10 5 0 10z',class:'fa fa-'+k})))));
 for(const lane of L.lanes){
  svg.append(svgEl('rect',{x:lane.x,y:lane.y,width:lane.w,height:lane.h,rx:12,class:'fl-lane'}),
   svgText(t('flow.layer.'+lane.layer),{x:lane.x+12,y:lane.y+20,class:'fl-lane-title'}));
 }
 svg.append(svgEl('rect',{x:0,y:L.services.y,width:L.width,height:L.services.h,rx:12,class:'fl-lane services'}),svgText(t('flow.layer.services'),{x:12,y:L.services.y+20,class:'fl-lane-title'}));
 const edges=svgEl('g',{class:'fl-edges','aria-hidden':'true'});
 const marker={dependency:'dep',mcp:'tool',rag:'tool',a2a:'a2a',llm:'llm',verdict:'verdict'};
 for(const e of st.edges){
  const a=L.pos[e.from],b=L.pos[e.to];if(!a||!b)continue;
  const p=flowEdgePath(a,b),fresh=!flowSeenEdges.has(e.key);
  const path=svgEl('path',{d:p.d,class:`fe ${e.kind} t-${e.transport}`+(fresh?' fresh':''),'marker-end':`url(#fa-${marker[e.kind]})`});
  path.append(svgEl('title',{},document.createTextNode(t('flow.edge.title',{from:e.from,to:e.to,kind:t('flow.edge.'+e.kind),transport:flowLabel('transport',e.transport),n:e.count}))));
  edges.append(path);
  if(e.transport!=='in_process')edges.append(svgText(flowLabel('transport',e.transport),{x:p.mid[0],y:p.mid[1]-3,class:'fe-label','text-anchor':'middle'}));
 }
 svg.append(edges);
 for(const k of FLOW_SERVICES){
  const p=L.pos[k],used=st.edges.some(e=>e.to===k);
  svg.append(svgEl('g',{class:'fs'+(used?' used':'')},svgEl('rect',{x:p.x,y:p.y,width:p.w,height:p.h,rx:9}),
   svgText(t('flow.svc.'+k),{x:p.x+10,y:p.y+22,class:'fs-title'}),svgText(t('flow.svc.'+k+'.x'),{x:p.x+10,y:p.y+40,class:'fs-meta'})));
 }
 if(!FLOW_IDS.includes(flowFocus))flowFocus='A01';
 for(const id of FLOW_IDS){
  const p=L.pos[id],n=st.nodes[id],kind=flowRole(id)?.kind;
  const g=svgEl('g',{id:'fn-'+id,class:`fn ${n.state}`+(flowOpen===id?' open':''),'data-id':id,role:'button',tabindex:id===flowFocus?'0':'-1','aria-label':flowNodeLabel(id),'aria-haspopup':'dialog'});
  g.addEventListener('click',()=>{flowFocus=id;openFlowAgent(id);});
  g.addEventListener('focus',()=>{if(flowFocus!==id){flowFocus=id;svg.querySelectorAll('.fn').forEach(x=>x.setAttribute('tabindex',x.dataset.id===id?'0':'-1'));}});
  const icon=svgEl('g',{class:'fl-icon '+n.state,transform:`translate(${p.x+8} ${p.y+42}) scale(.8)`});flowIconShapes(icon,n.state);
  g.append(...[svgEl('rect',{x:p.x,y:p.y,width:p.w,height:p.h,rx:9,class:'fn-box'}),svgEl('rect',{x:p.x,y:p.y+8,width:3,height:p.h-16,rx:1.5,class:'fn-bar'}),
   svgText(id,{x:p.x+10,y:p.y+17,class:'fn-id'}),kind?svgText(t('flow.kind.'+kind),{x:p.x+p.w-8,y:p.y+17,class:'fn-kind','text-anchor':'end'}):null,
   svgText(flowName(id),{x:p.x+10,y:p.y+35,class:'fn-name'}),icon,
   svgText(t('flow.state.'+n.state)+(n.wave?' · '+t('flow.wave.short',{n:n.wave}):''),{x:p.x+24,y:p.y+53,class:'fn-state'})].filter(Boolean));
  svg.append(g);
 }
 for(const e of st.edges)flowSeenEdges.add(e.key);
 return svg;
}
function flowLegend(){
 const item=(cls,key)=>h('li',{},h('span',{class:'lg '+cls,'aria-hidden':'true'}),t(key));
 return h('div',{id:'flow-legend',class:'fl-legend'},
  h('ul',{class:'fl-legend-states','aria-label':t('flow.legend.states')},FLOW_STATES.map(s=>h('li',{},flowStateChip(s)))),
  h('ul',{class:'fl-legend-edges','aria-label':t('flow.legend.edges')},item('dependency','flow.legend.dep'),item('verdict','flow.legend.verdict'),item('mcp','flow.legend.mcp'),
   item('a2a','flow.legend.a2a'),item('llm','flow.legend.llm'),item('rag','flow.legend.rag')),
  h('p',{class:'panel-note',text:t('flow.legend.note')}));
}
function flowTable(){
 const st=flowState;
 const rows=FLOW_IDS.map(id=>{const n=st.nodes[id];return h('tr',{class:flowOpen===id?'selected':''},
  h('th',{scope:'row'},h('button',{type:'button',class:'fl-link',id:'ft-'+id,onclick:()=>openFlowAgent(id,'ft-'+id)},`${id} · ${flowName(id)}`)),
  h('td',{text:t('flow.layer.'+flowLayer(id))}),h('td',{},flowStateChip(n.state)),h('td',{text:n.wave?String(n.wave):'—'}),
  h('td',{text:n.reason?flowLabel('reason',n.reason)+(n.errorCode&&n.errorCode!=='NOT_SELECTED'?' · '+flowLabel('code',n.errorCode):''):'—'}),
  h('td',{text:n.transport?flowLabel('transport',n.transport):'—'}));});
 const links=st.edges.map(e=>h('tr',{},h('td',{text:`${e.from} → ${e.to}`}),h('td',{text:t('flow.edge.'+e.kind)}),h('td',{text:flowLabel('transport',e.transport)}),h('td',{text:N(e.count)})));
 return h('details',{class:'fl-tables','data-key':'tables',open:flowOpenDetails.has('tables'),ontoggle:e=>{if(e.target.open)flowOpenDetails.add('tables');else flowOpenDetails.delete('tables');}},
  h('summary',{id:'fl-sum-tables',text:t('flow.table')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table compact fl-table'},h('caption',{text:t('flow.table.agents')}),
   h('thead',{},h('tr',{},...['flow.col.agent','flow.col.layer','flow.col.state','flow.col.wave','flow.col.why','flow.col.transport'].map(k=>h('th',{scope:'col',text:t(k)})))),h('tbody',{},rows))),
  h('div',{class:'table-wrap'},h('table',{class:'data-table compact fl-table'},h('caption',{text:t('flow.table.edges')}),
   h('thead',{},h('tr',{},...['flow.col.link','flow.col.kind','flow.col.transport','flow.col.count'].map(k=>h('th',{scope:'col',text:t(k)})))),
   h('tbody',{},links.length?links:h('tr',{},h('td',{colspan:'4',text:t('flow.table.noedges')}))))));
}
function flowDiagramPanel(){
 return h('section',{class:'panel fl-diagram','aria-labelledby':'flow-diagram-title'},
  h('div',{class:'panel-heading'},h('h2',{id:'flow-diagram-title',text:t('flow.diagram')}),chip(flowRunId?t('flow.badge.events'):t('flow.badge.idle'),flowRunId?'ok':'muted')),
  h('p',{class:'hint',text:t('flow.diagram.x')}),h('div',{class:'fl-svg-wrap'},flowSvg()),flowLegend(),flowTable());
}

// ---------- live timeline ----------
function flowTimelinePanel(){
 const sorted=flowSorted(flowState.timeline),shown=flowAll?sorted:sorted.slice(-FLOW_TIMELINE_ROWS);
 const rows=shown.map(e=>{const x=flowEventText(e,flowLabel);return h('li',{class:'fl-ev '+e.type},
  h('time',{text:'+'+msText(e.t_ms)}),h('span',{class:'fl-ev-agent',text:e.agent}),h('span',{class:'fl-ev-text',text:t(x.key,x.params)}));});
 return h('section',{class:'panel fl-timeline','aria-labelledby':'flow-tl-title'},
  h('div',{class:'panel-heading'},h('h2',{id:'flow-tl-title',text:t('flow.timeline')}),chip(t('flow.timeline.n',{n:N(sorted.length)}),'muted')),
  sorted.length?h('ol',{id:'flow-timeline-list',class:'fl-ev-list',tabindex:'0','aria-label':t('flow.timeline')},rows):empty('flow.timeline.none.t','flow.timeline.none.x'),
  sorted.length>FLOW_TIMELINE_ROWS?h('button',{type:'button',id:'flow-all',class:'secondary',onclick:()=>{flowAll=!flowAll;flowSchedule();}},t(flowAll?'flow.timeline.less':'flow.timeline.all',{n:N(sorted.length)})):null,
  h('p',{class:'panel-note',text:t('flow.timeline.note')}));
}

// ---------- results (from the sealed record) ----------
function flowVerdictsOf(record,agent){return (record?.judge?.verdicts||[]).filter(v=>v.agent===agent);}
function flowVerdictChip(v){
 if(!v)return chip(t('flow.verdict.none'),'muted');
 return h('span',{class:'fl-verdict '+v.verdict},chip(t('flow.verdict.'+v.verdict),{accepted:'ok',advisory:'info',rejected:'bad'}[v.verdict]),h('small',{text:tt('flow.jr.'+v.reason,String(v.reason).replace(/_/g,' '))}));
}
function flowClaim(record,agent,index){
 const result=record?.agents?.find(a=>a.agent_id===agent)?.result,claim=result?.claims?.[index];
 const verdict=flowVerdictsOf(record,agent).find(v=>v.claim===index);
 return h('li',{class:'fl-claim'},h('div',{},h('strong',{text:`${agent} · ${flowName(agent)}`}),h('code',{text:claim?claim.text_key:t('flow.claim.missing')})),
  claim&&Object.keys(claim.params||{}).length?h('small',{text:flowParams(claim.params)}):null,flowVerdictChip(verdict));
}
function flowResultsPanel(){
 const record=flowDetail?.record,head=h('div',{class:'panel-heading'},h('h2',{id:'flow-res-title',text:t('flow.results')}),chip(record?t('flow.results.sealed'):t('flow.results.waiting'),record?'ok':'muted'));
 if(!record)return h('section',{class:'panel fl-results','aria-labelledby':'flow-res-title'},head,
  h('p',{class:'hint',text:flowRunId?t('flow.results.live',{a:N(flowState.judge.accepted),v:N(flowState.judge.advisory),r:N(flowState.judge.rejected)}):t('flow.results.none')}));
 const accepted=record.judge.accepted_findings||[];
 const candidates=['A24','A25','A28'].map(a=>({a,r:record.agents.find(x=>x.agent_id===a)})).filter(x=>x.r.result.status!=='SKIPPED');
 const models=['A02','A22','A23','A29','A30'].map(a=>record.agents.find(x=>x.agent_id===a)).filter(x=>x.result.llm||x.result.advisory_text||flowState.nodes[x.agent_id].llm.length);
 const items=record.approvals?.[0]?.items||[],decisions=flowDetail.decisions||{};
 const totals=record.usage.totals,rows=FLOW_IDS.map(id=>[id,record.usage.agents[id]]).filter(([,u])=>u.tool_calls||u.llm_calls||u.latency_ms);
 const sub=(key,...kids)=>h('div',{class:'fl-res-block'},h('h3',{text:t(key)}),...kids);
 return h('section',{class:'panel fl-results','aria-labelledby':'flow-res-title'},head,
  h('p',{class:'hint',text:t('flow.results.x',{status:flowLabel('runstatus',record.status),digest:record.trace_sha256.slice(0,12)})}),
  sub('flow.res.accepted',accepted.length?h('ul',{class:'fl-claims'},accepted.map(f=>flowClaim(record,f.agent,f.claim))):h('p',{class:'hint',text:t('flow.res.accepted.none')})),
  sub('flow.res.candidates',h('p',{class:'hint',text:t('flow.res.candidates.x')}),candidates.length?h('ul',{class:'fl-claims'},candidates.flatMap(({a,r})=>r.result.claims.length
   ?r.result.claims.map((_,i)=>flowClaim(record,a,i)):[h('li',{class:'fl-claim'},h('strong',{text:`${a} · ${flowName(a)}`}),flowStateChip(FLOW_STATUS_STATE[r.result.status]),h('small',{text:flowLabel('code',r.result.error_code)}))])):h('p',{class:'hint',text:t('flow.res.candidates.none')})),
  sub('flow.res.models',h('p',{class:'hint',text:t('flow.res.models.x')}),models.length?h('ul',{class:'fl-claims'},models.map(x=>{
   const own=flowVerdictsOf(record,x.agent_id).filter(v=>v.verdict!=='accepted'||v.reason!=='evidence_verified');
   return h('li',{class:'fl-claim'},h('div',{},h('strong',{text:`${x.agent_id} · ${flowName(x.agent_id)}`}),chip(t('flow.advisory'),'info')),
    x.result.advisory_text?h('blockquote',{class:'fl-advice',text:x.result.advisory_text}):h('small',{text:t('flow.res.models.notext',{code:flowLabel('code',x.result.error_code)})}),
    x.result.llm?h('small',{},t('flow.llm.model')+' '+x.result.llm.model+' · '+t('flow.llm.hash')+' ',flowCode(x.result.llm.prompt_sha256,16)):null,
    own.length?h('div',{class:'fl-verdicts'},own.map(flowVerdictChip)):h('div',{class:'fl-verdicts'},flowVerdictChip(null)));
  })):h('p',{class:'hint',text:t('flow.res.models.none')})),
  sub('flow.res.approval',h('p',{class:'hint',text:t('flow.res.approval.x')}),items.length?h('ol',{class:'fl-approvals'},items.map((item,i)=>{
   const decided=decisions[String(i)]?.decision;
   return h('li',{class:'fl-claim'},h('div',{},h('strong',{text:`${item.agent} · ${flowName(item.agent)}`}),h('code',{text:item.text_key})),
    h('small',{text:flowParams(item.params)}),
    h('div',{class:'button-row',role:'group','aria-label':t('flow.decide.label',{n:i+1})},
     h('button',{type:'button',id:`fa-approve-${i}`,class:'secondary','aria-pressed':String(decided==='approved'),onclick:()=>decideFlow(i,'approved')},t('flow.decide.approve')),
     h('button',{type:'button',id:`fa-reject-${i}`,class:'secondary','aria-pressed':String(decided==='rejected'),onclick:()=>decideFlow(i,'rejected')},t('flow.decide.reject'))),
    h('small',{text:decided?t('flow.decided',{decision:t('flow.decision.'+decided)}):t('flow.pending')}));
  })):h('p',{class:'hint',text:t('flow.res.approval.none')})),
  sub('flow.res.usage',h('p',{class:'hint',text:t('flow.res.usage.x',{tools:N(totals.tool_calls),llm:N(totals.llm_calls),tin:N(totals.tokens_in),tout:N(totals.tokens_out),ms:msText(totals.latency_ms),usd:N(record.usage.external_spend_usd)})}),
   h('div',{class:'table-wrap'},h('table',{class:'data-table compact'},h('thead',{},h('tr',{},...['flow.col.agent','flow.col.tools','flow.col.llm','flow.col.tokens','flow.col.latency'].map(k=>h('th',{scope:'col',text:t(k)})))),
    h('tbody',{},rows.map(([id,u])=>h('tr',{},h('th',{scope:'row',text:`${id} · ${flowName(id)}`}),h('td',{text:N(u.tool_calls)}),h('td',{text:N(u.llm_calls)}),h('td',{text:N(u.tokens_in+u.tokens_out)}),h('td',{text:msText(u.latency_ms)}))))))));
}

// ---------- agent detail drawer ----------
function flowDrawer(){
 if(!flowOpen)return null;
 const id=flowOpen,n=flowState.nodes[id],role=flowRole(id),rec=flowRecordAgent(id),result=rec?.result,record=flowDetail?.record;
 const block=(key,...kids)=>h('section',{class:'fl-block'},h('h3',{text:t(key)}),...kids);
 const none=key=>h('p',{class:'hint',text:t(key)});
 const tools=n.tools.length?h('div',{class:'table-wrap'},h('table',{class:'data-table compact'},h('thead',{},h('tr',{},...['flow.col.tool','flow.col.phase','flow.col.transport','flow.col.outcome','flow.col.latency'].map(k=>h('th',{scope:'col',text:t(k)})))),
  h('tbody',{},n.tools.map(c=>h('tr',{},h('td',{},h('code',{text:c.tool})),h('td',{text:t('flow.phase.'+c.phase)}),h('td',{text:flowLabel('transport',c.transport)}),h('td',{text:flowLabel('outcome',c.outcome)}),h('td',{text:msText(c.latency_ms)}))))))
  :none('flow.d.tools.none');
 const verdicts=n.verdicts.flatMap(v=>v.verdicts.map(x=>({...x,pass:v.pass})));
 const claims=result?.claims?.length?h('ol',{class:'fl-claims',start:'0'},result.claims.map((c,i)=>{
   const v=flowVerdictsOf(record,id).find(x=>x.claim===i);
   return h('li',{class:'fl-claim'},h('code',{text:c.text_key}),Object.keys(c.params||{}).length?h('small',{text:flowParams(c.params)}):null,
    h('small',{text:t('flow.d.claim.refs',{refs:c.evidence_refs.map(r=>r.id).join(', ')||'—'})}),flowVerdictChip(v));}))
  :verdicts.length?h('ul',{class:'fl-claims'},verdicts.map(v=>h('li',{class:'fl-claim'},h('span',{text:t('flow.d.claim.n',{n:v.claim===null?'—':v.claim,pass:flowLabel('pass',v.pass)})}),flowVerdictChip(v))))
  :none(record?'flow.d.claims.none':'flow.d.claims.wait');
 const llm=n.llm.length?h('div',{class:'fl-llm'},chip(t('flow.advisory'),'info'),...n.llm.map(c=>h('dl',{class:'fl-dl'},
   flowKv(t('flow.llm.model'),c.model),flowKv(t('flow.llm.template'),c.template),flowKv(t('flow.llm.outcome'),c.ok?t('flow.llm.ok'):flowLabel('code',c.error_code)),
   flowKv(t('flow.llm.hash'),flowCode(c.prompt_sha256)),flowKv(t('flow.llm.tokens'),t('flow.llm.tokens.v',{tin:N(c.tokens_in),tout:N(c.tokens_out)})),
   flowKv(t('flow.llm.latency'),msText(c.latency_ms)),flowKv(t('flow.llm.cache'),flowLabel('cache',c.cache)))),
   result?.llm?h('p',{class:'hint',text:t('flow.llm.settings',{provider:result.llm.provider,temperature:result.llm.temperature,seed:result.llm.seed})}):null)
  :none(role&&role.allowed_tools.includes('local_llm')?'flow.d.llm.none':'flow.d.llm.never');
 const unverified=flowVerdictsOf(record,id).some(v=>v.reason==='unverified_citation'),judged=flowVerdictsOf(record,id).length>0;
 const rag=result?.retrieval?.citations?.length?h('ul',{class:'fl-cites'},result.retrieval.citations.map(c=>h('li',{},h('strong',{text:c.source}),h('small',{text:t('flow.d.rev',{rev:c.revision})}),flowCode(c.citation,24))))
  :n.retrieval?h('p',{class:'hint',text:t('flow.d.rag.live',{n:N(n.retrieval.citations),sources:n.retrieval.sources.join(', ')||'—'})}):none('flow.d.rag.none');
 const certs=n.certificates||(id==='A27'&&record?.judge?.transport?.ca_sha256?record.judge.transport:null);
 const plan=flowState.plan;
 return h('aside',{id:'flow-drawer',class:'fl-drawer',role:'dialog','aria-modal':'false','aria-labelledby':'flow-drawer-title'},
  h('div',{class:'fl-drawer-head'},h('div',{},h('p',{class:'eyebrow',text:`${id} · ${t('flow.layer.'+flowLayer(id))}`}),h('h2',{id:'flow-drawer-title',tabindex:'-1',text:role?.name||flowName(id)})),
   h('button',{type:'button',id:'flow-drawer-close',class:'secondary','aria-label':t('flow.d.close.label',{id}),onclick:closeFlowAgent},t('flow.d.close'))),
  h('div',{id:'flow-drawer-body',class:'fl-drawer-body'},
   h('div',{class:'fl-chips'},flowStateChip(n.state),role?chip(t('flow.kind.'+role.kind)+' · '+t('flow.kind.'+role.kind+'.x'),'muted'):null,n.wave?chip(t('flow.wave',{n:n.wave})+(n.stage?' · '+flowLabel('stage',n.stage):''),'muted'):null,n.attempt>1?chip(t('flow.d.retry',{n:n.attempt}),'warn'):null),
   block('flow.d.role',h('p',{text:tt('role.'+id+'.does',flowName(id))}),h('p',{class:'hint',text:t('flow.d.limit')+' '+tt('flow.lim.'+id,'—')}),
    role?h('p',{class:'hint'},t('flow.d.trigger')+' ',h('code',{text:role.trigger_summary})):null,
    role?h('p',{class:'hint'},t('flow.d.tools.allowed')+' ',h('code',{text:role.allowed_tools.join(', ')||t('flow.d.tools.noneallowed')})):null),
   block('flow.d.why',h('p',{text:n.reason?t(n.selected?'flow.d.why.selected':'flow.d.why.skipped',{reason:flowLabel('reason',n.reason)}):t('flow.d.why.none')}),
    n.unmet.length?h('p',{class:'hint',text:t('flow.d.unmet',{agents:n.unmet.join(', ')})}):null,
    n.dependsOn.length?h('p',{class:'hint',text:t('flow.d.depends',{agents:n.dependsOn.join(', ')})}):null,
    n.errorCode?h('p',{class:'fl-code'},h('code',{text:n.errorCode}),' ',tt('flow.code.'+n.errorCode+'.x',flowLabel('code',n.errorCode))):null,
    n.abandoned?h('p',{class:'hint bad',text:t('flow.d.abandoned')}):null,n.runtime?h('p',{class:'hint',text:t('flow.d.runtime')}):null),
   block('flow.d.contract',record?null:none('flow.d.contract.wait'),rec?.task?flowPre('task-'+id,t('flow.d.input'),rec.task):record?none('flow.d.contract.notask'):null,result?flowPre('result-'+id,t('flow.d.output'),result):null,
    n.budget?h('p',{class:'hint',text:t('flow.d.budget',{tools:n.budget.max_tool_calls,llm:n.budget.max_llm_calls,tokens:N(n.budget.max_tokens),ms:msText(n.budget.deadline_ms)})}):null,
    n.usage?h('p',{class:'hint',text:t('flow.d.usage',{tools:n.usage.tool_calls,llm:n.usage.llm_calls,tokens:N(n.usage.tokens_in+n.usage.tokens_out),ms:msText(n.usage.latency_ms)})}):null),
   block('flow.d.tools',tools),
   block('flow.d.evidence',result?.evidence_refs?.length?h('ul',{class:'fl-refs'},result.evidence_refs.map(r=>h('li',{},h('code',{text:r.id}),h('small',{},t('flow.d.digest')+' ',flowCode(r.sha256,20))))):
    n.evidenceRefs!==null?none(record?'flow.d.evidence.none':'flow.d.evidence.wait'):none('flow.d.evidence.none')),
   block('flow.d.claims',claims),
   block('flow.d.llm',llm),
   block('flow.d.rag',rag,result?.retrieval?.citations?.length&&judged?h('p',{class:unverified?'hint bad':'hint',text:t(unverified?'flow.d.rag.unverified':'flow.d.rag.verified')}):null,
    n.cache.length?h('p',{class:'hint',text:t('flow.d.cag',{list:n.cache.map(c=>`${c.template}: ${flowLabel('cache',c.result)}`).join(', ')})}):null),
   block('flow.d.transport',h('p',{text:n.transport?t('flow.d.transport.v',{transport:flowLabel('transport',n.transport)}):t('flow.d.transport.none')}),
    plan?h('p',{class:'hint',text:t('flow.d.plan',{tools:flowLabel('transport',plan.tools.mode),why:flowLabel('reason',plan.tools.reason||'none'),judge:flowLabel('transport',plan.judge.mode),jwhy:flowLabel('reason',plan.judge.reason||'none')})}):null,
    certs?h('dl',{class:'fl-dl'},flowKv(t('flow.d.cert.ca'),flowCode(certs.ca_sha256)),flowKv(t('flow.d.cert.server'),flowCode(certs.server_sha256)),flowKv(t('flow.d.cert.client'),flowCode(certs.client_sha256))):null,
    certs?h('p',{class:'hint',text:t('flow.d.cert.x')}):null)));
}

// ---------- explainer ----------
function flowExplainer(){
 const layer=([key,lo,hi])=>h('li',{},h('strong',{text:t('flow.layer.'+key)}),h('span',{text:t('flow.how.'+key)}),
  connected?h('div',{class:'fl-agent-links'},FLOW_IDS.slice(lo-1,hi).map(id=>h('button',{type:'button',class:'fl-link','aria-label':t('flow.how.open',{id,name:flowName(id)}),id:'fx-'+id,onclick:()=>openFlowAgent(id,'fx-'+id)},id))):null);
 const concept=key=>h('li',{},h('strong',{text:t('flow.how.'+key+'.t')}),h('span',{text:t('flow.how.'+key)}),h('small',{text:t('flow.how.limit')+' '+t('flow.how.'+key+'.limit')}));
 return h('section',{class:'panel fl-how','aria-labelledby':'flow-how-title'},h('div',{class:'panel-heading'},h('h2',{id:'flow-how-title',text:t('flow.how')})),
  h('p',{class:'hint',text:t('flow.how.x')}),
  h('div',{class:'grid-2 fl-how-grid'},h('div',{},h('h3',{text:t('flow.how.layers')}),h('ol',{class:'fl-how-list'},FLOW_LAYERS.map(layer))),
   h('div',{},h('h3',{text:t('flow.how.terms')}),h('ul',{class:'fl-how-list'},['llm','rag','cag','tag','judge','mcp','a2a','mtls','budget'].map(concept)))),
  h('p',{class:'panel-note',text:t('flow.how.note')}));
}

// ---------- page ----------
function flowAnnounce(){
 const m=flowState.milestone,live=document.getElementById('flow-live');
 if(!live||!m||m.seq===flowAnnounced)return;
 flowAnnounced=m.seq;
 const params={...m.params};if(params.stage)params.stage=flowLabel('stage',params.stage);if(params.status)params.status=flowLabel('runstatus',params.status);if(params.pass)params.pass=flowLabel('pass',params.pass);
 live.textContent=t(m.key,params);
}
function flowPaint(root){
 if(!root||!connected)return;
 const active=document.activeElement,activeId=active&&root.contains(active)?active.id:null;
 const scroll={};for(const id of ['flow-timeline-list','flow-drawer-body']){const n=document.getElementById(id);if(n)scroll[id]=n.scrollTop;}
 const controls=flowControls();
 if(!flowDyn)flowDyn=h('div',{class:'fl-dyn'});
 if(root.firstChild!==controls||root.lastChild!==flowDyn)root.replaceChildren(controls,flowDyn);
 flowDyn.replaceChildren(flowHeader(),flowDiagramPanel(),h('div',{class:'fl-grid'},flowTimelinePanel(),flowResultsPanel()),flowExplainer(),flowDrawer()||'');
 for(const [id,top] of Object.entries(scroll)){const n=document.getElementById(id);if(n)n.scrollTop=top;}
 if(activeId&&document.activeElement!==document.getElementById(activeId))document.getElementById(activeId)?.focus({preventScroll:true});
 flowAnnounce();
}
function renderFlow(){
 const root=$('screen-flow');
 if(!connected){flowAbort?.abort();flowAbort=null;flowOpen=null;root.replaceChildren(h('section',{class:'panel'},empty('flow.connect.t','flow.connect.x')),flowExplainer());flowCtl=null;flowDyn=null;flowOwnFile=null;flowSecond=null;return;}
 loadFlowRoles();loadFlowRuns();loadBaselines();
 if(!flowRunId&&!flowAbort){
  const linked=typeof location!=='undefined'?new URLSearchParams(location.search).get('run'):null;
  if(linked)viewFlowRun(linked);else if(flowRuns?.active)viewFlowRun(flowRuns.active);
 }
 flowPaint(root);
}
function flowHappened(){
 if(!connected)return t('flow.happened.connect');
 if(!flowRunId)return t('flow.happened.none');
 return t('flow.happened',{status:t('flow.status.'+flowStatus()[0]),n:N(flowState.count)});
}
if(typeof document!=='undefined'){
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&flowOpen&&route==='/flow'){e.preventDefault();closeFlowAgent();}});
 flowNarrowQuery?.addEventListener?.('change',()=>{if(route==='/flow')flowSchedule();});
}
