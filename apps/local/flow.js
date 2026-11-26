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

// Diagram geometry: five lanes side by side (wide) or stacked (narrow), plus a row for the local services. Besides the
// boxes it returns the free vertical gutters between box columns (``channels``) and the free horizontal gaps between
// box rows (``streets``): edges are routed only through those, so a line never runs across a box.
const FLOW_NODE={w:154,h:64};
function flowLayout(narrow=false){
 const w=FLOW_NODE.w,hgt=FLOW_NODE.h,gap=14,pad=12,head=30,pitch=hgt+gap,pos={},lanes=[],streets=[];
 let width,height,services;
 if(!narrow){
  const cols={orchestration:1,specialists:2,reasoning:1,remediation:1,governance:1},colGap=24,laneGap=28,rows=8;
  let x=0;const laneH=head+pad+rows*pitch;
  for(const [layer,lo,hi] of FLOW_LAYERS){
   const c=cols[layer],per=Math.ceil((hi-lo+1)/c),laneW=c*w+(c-1)*colGap+2*pad;
   lanes.push({layer,x,y:0,w:laneW,h:laneH});
   for(let n=lo;n<=hi;n++){const i=n-lo,col=Math.floor(i/per),row=i%per;pos[FLOW_IDS[n-1]]={x:x+pad+col*(w+colGap),y:head+pad+row*pitch,w,h:hgt};}
   x+=laneW+laneGap;
  }
  width=x-laneGap;const sy=laneH+24;
  for(let r=1;r<rows;r++)streets.push(head+pad+r*pitch-gap/2);
  streets.push(laneH+12);
  FLOW_SERVICES.forEach((k,i)=>{pos[k]={x:pad+i*(width-2*pad-w)/2,y:sy+head,w,h:hgt-8};});
  height=sy+head+hgt+8;services={y:sy,h:head+hgt};
 }else{
  width=2*w+20+2*pad;let y=0;
  for(const [layer,lo,hi] of FLOW_LAYERS){
   const rows=Math.ceil((hi-lo+1)/2),laneH=head+pad+rows*pitch;
   lanes.push({layer,x:0,y,w:width,h:laneH});
   for(let n=lo;n<=hi;n++){const i=n-lo;pos[FLOW_IDS[n-1]]={x:pad+(i%2)*(w+20),y:y+head+pad+Math.floor(i/2)*pitch,w,h:hgt};}
   for(let r=1;r<rows;r++)streets.push(y+head+pad+r*pitch-gap/2);
   y+=laneH+12;streets.push(y-6);
  }
  const sy=y;
  FLOW_SERVICES.forEach((k,i)=>{pos[k]={x:pad+(i%2)*(w+20),y:sy+head+Math.floor(i/2)*(hgt+gap),w,h:hgt-8};});
  streets.push(sy+head+hgt-8+(gap+8)/2);
  height=sy+head+2*(hgt+gap);services={y:sy,h:head+2*(hgt+gap)};
 }
 // Vertical gutters: the gaps between the x-intervals of the agent columns, and the two margins.
 const cols=[...new Set(FLOW_IDS.map(id=>pos[id].x))].sort((a,b)=>a-b),bounds=[0,...cols.flatMap(c=>[c,c+w]),width],channels=[];
 for(let i=0;i<bounds.length;i+=2)channels.push({id:'c'+i/2,lo:bounds[i],hi:bounds[i+1],x:(bounds[i]+bounds[i+1])/2,w:bounds[i+1]-bounds[i]});
 return {width,height,lanes,pos,services,streets:streets.sort((a,b)=>a-b),channels,gap};
}
// The gutter beside a box on one side.
function flowChannel(L,box,side){
 return side==='left'?L.channels.find(c=>Math.abs(c.hi-box.x)<0.5):L.channels.find(c=>Math.abs(c.lo-box.x-box.w)<0.5);
}
// The abstract route of one edge: exit side, gutters and street. Services are entered from the top.
function flowLeg(L,edge){
 const a=L.pos[edge.from],b=L.pos[edge.to];
 if(!a||!b||!FLOW_IDS.includes(edge.from))return null;
 const acx=a.x+a.w/2,acy=a.y+a.h/2,bcx=b.x+b.w/2,bcy=b.y+b.h/2;
 if(FLOW_SERVICES.includes(edge.to)){
  const side=bcx>=acx?'right':'left',street=Math.max(...L.streets.filter(s=>s<b.y));
  return {a,b,service:true,sideA:side,ca:flowChannel(L,a,side),street};
 }
 const same=Math.abs(acx-bcx)<1,sideA=same||bcx>acx?'right':'left',sideB=same||bcx<acx?'right':'left';
 const ca=flowChannel(L,a,sideA),cb=flowChannel(L,b,sideB);
 if(ca.id===cb.id)return {a,b,sideA,sideB,ca,cb,street:null};
 // A street between the two rows (nearest the target), or else the one nearest the source row.
 const lo=Math.min(acy,bcy),hi=Math.max(acy,bcy),between=L.streets.filter(s=>s>lo&&s<hi),aim=between.length?bcy:acy;
 const street=(between.length?between:L.streets).reduce((best,s)=>Math.abs(s-aim)<Math.abs(best-aim)?s:best);
 return {a,b,sideA,sideB,ca,cb,street};
}
// Orthogonal routes for all edges. Edges that share a gutter are bundled: legs leaving the same agent share one track,
// legs arriving at the same agent or service share one track, and distinct tracks run a few pixels apart.
function flowRoutes(L,edges){
 const legs=edges.map(e=>({e,leg:flowLeg(L,e)})).filter(x=>x.leg),use=new Map();
 const claim=(lane,key)=>{const list=use.get(lane)||[];if(!list.includes(key))list.push(key);use.set(lane,list);};
 for(const {e,leg} of legs){
  claim(leg.ca.id,'f'+e.from);
  if(leg.service)claim('s'+leg.street,'t'+e.to);
  else if(leg.street!==null){claim(leg.cb.id,'t'+e.to);claim('s'+leg.street,'f'+e.from);}
 }
 const offset=(lane,key,room)=>{
  const list=use.get(lane),n=list.length,i=list.indexOf(key),step=Math.min(4,Math.max(1.5,(room-6)/Math.max(1,n-1)));
  const max=Math.max(0,room/2-3);return Math.max(-max,Math.min(max,(i-(n-1)/2)*step));
 };
 return legs.map(({e,leg})=>{
  const {a,b}=leg,ay=a.y+a.h/2,ax=leg.sideA==='right'?a.x+a.w:a.x,xa=leg.ca.x+offset(leg.ca.id,'f'+e.from,leg.ca.w);
  let points;
  if(leg.service){
   const sy=leg.street+offset('s'+leg.street,'t'+e.to,L.gap),bx=b.x+b.w/2;
   points=[[ax,ay],[xa,ay],[xa,sy],[bx,sy],[bx,b.y]];
  }else{
   const by=b.y+b.h/2,bxe=leg.sideB==='right'?b.x+b.w:b.x;
   if(leg.street===null)points=[[ax,ay],[xa,ay],[xa,by],[bxe,by]];
   else{
    const xb=leg.cb.x+offset(leg.cb.id,'t'+e.to,leg.cb.w),sy=leg.street+offset('s'+leg.street,'f'+e.from,L.gap);
    points=[[ax,ay],[xa,ay],[xa,sy],[xb,sy],[xb,by],[bxe,by]];
   }
  }
  points=flowSimplify(points);
  return {key:e.key,from:e.from,to:e.to,points,d:flowRoundedPath(points,6)};
 });
}
// Drop repeated and collinear points of an orthogonal polyline.
function flowSimplify(points){
 const out=[];
 for(const p of points.map(([x,y])=>[+x.toFixed(2),+y.toFixed(2)])){
  const last=out[out.length-1];if(last&&last[0]===p[0]&&last[1]===p[1])continue;
  const prev=out[out.length-2];
  if(prev&&((prev[0]===last[0]&&last[0]===p[0])||(prev[1]===last[1]&&last[1]===p[1])))out.pop();
  out.push(p);
 }
 return out;
}
// An orthogonal polyline as an SVG path whose corners are rounded with radius ``r`` (less on short segments).
function flowRoundedPath(points,r=6){
 if(!points.length)return '';
 const f=v=>+v.toFixed(2);let d=`M${f(points[0][0])} ${f(points[0][1])}`;
 for(let i=1;i<points.length-1;i++){
  const [px,py]=points[i-1],[x,y]=points[i],[nx,ny]=points[i+1];
  const lin=Math.hypot(x-px,y-py),lout=Math.hypot(nx-x,ny-y),k=Math.min(r,lin/2,lout/2);
  d+=` L${f(x-(x-px)/lin*k)} ${f(y-(y-py)/lin*k)} Q${f(x)} ${f(y)} ${f(x+(nx-x)/lout*k)} ${f(y+(ny-y)/lout*k)}`;
 }
 const last=points[points.length-1];
 return d+` L${f(last[0])} ${f(last[1])}`;
}
// Greedy label placement: each label takes the first candidate spot (along each segment at 1/2, 0.3 and 0.7;
// horizontal and long segments first)
// whose box overlaps neither an obstacle (a node) nor an already placed label; a label with no free spot is left out.
function flowPlaceLabels(labels,obstacles){
 const placed=[],out=[],hit=(p,q)=>p.x<q.x+q.w&&q.x<p.x+p.w&&p.y<q.y+q.h&&q.y<p.y+p.h;
 for(const label of labels){
  const segs=[];
  for(let i=1;i<label.points.length;i++){const [x1,y1]=label.points[i-1],[x2,y2]=label.points[i];segs.push({h:y1===y2,len:Math.hypot(x2-x1,y2-y1),x1,y1,x2,y2});}
  segs.sort((p,q)=>(q.h-p.h)||(q.len-p.len));
  const spots=segs.flatMap(g=>[0.5,0.3,0.7].map(f=>({...g,x:g.x1+(g.x2-g.x1)*f,y:g.y1+(g.y2-g.y1)*f})));
  for(const s of spots){
   if(s.len<(s.h?label.w:label.h)+8)continue;
   const box={x:s.x-label.w/2,y:s.y-label.h/2,w:label.w,h:label.h};
   if(obstacles.some(o=>hit(box,o))||placed.some(o=>hit(box,o)))continue;
   placed.push(box);out.push({key:label.key,x:s.x,y:s.y});break;
  }
 }
 return out;
}

// ---------- replay of a finished run's recorded events at readable speed ----------
const FLOW_REPLAY_SPEEDS=[0.25,0.5,1],FLOW_REPLAY_GAP_MS=60;
// The recorded events in run-clock order with their replay times: the run's own relative timing divided by ``speed``,
// and at least ``gap``/``speed`` ms after the previous event so a burst of same-millisecond events stays visible.
// Events are renumbered 1..n in that order so the reducer applies each exactly once.
function flowReplayPlan(events,speed,gap=FLOW_REPLAY_GAP_MS){
 if(!(speed>0))throw new RangeError('speed');
 const list=(events||[]).filter(e=>e&&typeof e==='object'&&Number.isFinite(e.t_ms)).sort((x,y)=>x.t_ms-y.t_ms||x.seq-y.seq);
 const t0=list.length?list[0].t_ms:0;let prev=-Infinity;
 return list.map((e,i)=>{const at=i?Math.max((e.t_ms-t0)/speed,prev+gap/speed):0;prev=at;return {at,event:{...e,seq:i+1}};});
}
// Index of the first planned event not yet due ``elapsed`` ms into the replay, starting at ``from``.
function flowReplayDue(plan,elapsed,from=0){let i=from;while(i<plan.length&&plan[i].at<=elapsed)i++;return i;}

// ---------- one live stream per run ----------
// At most one subscription is open: opening the same run again returns the open one (no abort, no duplicate
// request); opening another run aborts the previous one first. ``start(controller)`` runs the subscription and the
// entry is dropped when it settles.
function flowStreamRegistry(){
 const live=new Map();
 return {
  has:id=>live.has(id),
  get size(){return live.size;},
  open(id,start){
   if(live.has(id))return live.get(id);
   for(const [key,c] of live){c.abort();live.delete(key);}
   const control=new AbortController();live.set(id,control);
   Promise.resolve().then(()=>start(control)).catch(()=>{}).finally(()=>{if(live.get(id)===control)live.delete(id);});
   return control;
  },
  close(){for(const c of live.values())c.abort();live.clear();},
 };
}

// ---------- the page brief: what happened and what next, from the current state ----------
// ``c``: {connected, runId, runs (retained count), status, count, running, done, error, record, pending, total,
// replay:{speed,shown,total}|null, ms}. Returns string keys with parameters; ``label`` words status and duration.
function flowBrief(c,label=(kind,value)=>String(value)){
 const out=(hk,hp,nk,np={})=>({happened:{key:hk,params:hp},next:{key:nk,params:np}});
 if(!c.connected)return out('flow.brief.connect',{},'flow.next.connect');
 if(!c.runId)return out(c.runs?'flow.brief.none.runs':'flow.brief.none',{n:c.runs||0},'flow.next.start');
 if(c.error)return out('flow.brief.error',{id:c.runId},'flow.next.retry');
 if(c.replay)return out('flow.brief.replay',{speed:c.replay.speed,shown:c.replay.shown,total:c.replay.total},'flow.next.replay');
 if(c.status==='idle'||c.status==='running'){
  if(!c.count)return out('flow.brief.waiting',{id:c.runId},'flow.next.watch');
  return out('flow.brief.running',{n:c.count,running:c.running||0,done:c.done||0},'flow.next.watch');
 }
 const happened=['flow.brief.finished',{status:label('runstatus',c.status),n:c.count,ms:label('ms',c.ms??0)}];
 if(!c.record)return out(...happened,'flow.next.record');
 if(c.pending>0)return out(...happened,'flow.next.approve',{n:c.pending});
 if(c.total>0)return out(...happened,'flow.next.decided',{n:c.total});
 return out(...happened,'flow.next.story');
}

// ---------- the run story: five plain sentences computed from a sealed record ----------
const FLOW_MODEL_CLAIMS=['a23.suggested','a02.worded','a22.relevance','a23.compared','a29.options','a30.proposal'];
const FLOW_MODEL_CODES=['MODEL_UNAVAILABLE','INVALID_OUTPUT','TIMEOUT','LLM_BUDGET_EXHAUSTED','TOKEN_BUDGET_EXCEEDED'];
// ``detail``: {record, decisions, input}. Each item: {key, params (raw codes; lists stay arrays), agents (drawer links)}.
function flowStory(detail){
 const record=detail?.record;if(!record)return [];
 const result=id=>(record.agents||[]).find(a=>a.agent_id===id)?.result||null;
 const ran=id=>{const r=result(id);return !!r&&r.status!=='SKIPPED';};
 const verdicts=record.judge?.verdicts||[],story=[];
 // 1. the signal that started it
 const name=detail.input?.name||null,incident=name?.match(/\bINC-\d+\b/)?.[0]||null;
 const signals=(record.intake?.signals||[]).map(s=>({check:s.check,column:s.column??null}));
 if(record.status==='input_rejected')story.push({key:'flow.story.rejected',params:{},agents:['A01']});
 else if(incident)story.push({key:signals.length?'flow.story.signal.incident':'flow.story.signal.incident.none',params:{incident,signals},agents:['A01','A02']});
 else story.push({key:signals.length?'flow.story.signal.file':'flow.story.signal.file.none',params:{name:name||record.case_id,signals},agents:['A01','A02']});
 // 2. the specialists that ran and what they found
 const specialists=FLOW_IDS.filter(id=>flowIsSpecialist(id)&&ran(id));
 if(!specialists.length)story.push({key:'flow.story.specialists.none',params:{},agents:[]});
 else{
  const claims=specialists.reduce((n,id)=>n+result(id).claims.length,0);
  const accepted=verdicts.filter(v=>specialists.includes(v.agent)&&v.verdict==='accepted'&&v.claim!==null).length;
  const needs=specialists.filter(id=>result(id).status!=='COMPLETED');
  story.push({key:needs.length?'flow.story.specialists.gaps':'flow.story.specialists',params:{n:specialists.length,agents:specialists,accepted,claims,needs},agents:specialists});
  const found=[],by=[];
  for(const id of specialists)for(const c of result(id).claims){
   const p=c.params||{};let item=null;
   if(p.check&&p.column&&c.text_key.endsWith('.finding'))item={check:p.check,column:p.column};
   else if(p.shifted===true&&p.column)item={check:'distribution_shift',column:p.column};
   else if(c.text_key==='a11.volume'&&p.changed===true)item={check:'volume_change',column:null};
   else if(c.text_key==='a11.freshness'&&p.stale===true)item={check:'freshness',column:null};
   if(item&&!found.some(f=>f.check===item.check&&f.column===item.column)){found.push(item);if(!by.includes(id))by.push(id);}
  }
  story.push(found.length?{key:'flow.story.found',params:{found},agents:by}:{key:'flow.story.found.none',params:{},agents:specialists});
 }
 // 3. what the model suggested and what the Judge did with it
 const modelClaims=[];
 for(const a of record.agents||[])(a.result?.claims||[]).forEach((c,i)=>{if(FLOW_MODEL_CLAIMS.includes(c.text_key))modelClaims.push({agent:a.agent_id,claim:c,verdict:verdicts.find(v=>v.agent===a.agent_id&&v.claim===i)||null});});
 const a23=modelClaims.find(m=>m.claim.text_key==='a23.suggested');
 if(a23)story.push(a23.verdict?.verdict==='rejected'?{key:'flow.story.model.rejected',params:{mechanisms:a23.claim.params?.mechanisms||[],reason:a23.verdict.reason},agents:['A23','A27']}
  :{key:'flow.story.model.advisory',params:{mechanisms:a23.claim.params?.mechanisms||[]},agents:['A23','A27']});
 else if(modelClaims.length){
  const agents=[...new Set(modelClaims.map(m=>m.agent))];
  story.push({key:'flow.story.model.other',params:{n:modelClaims.length,agents,advisory:modelClaims.filter(m=>m.verdict?.verdict==='advisory').length,rejected:modelClaims.filter(m=>m.verdict?.verdict==='rejected').length},agents:[...agents,'A27']});
 }else{
  const silent=['A02','A22','A23','A29','A30'].filter(id=>FLOW_MODEL_CODES.includes(result(id)?.error_code));
  story.push(silent.length?{key:'flow.story.model.unavailable',params:{agents:silent},agents:silent}:{key:'flow.story.model.none',params:{},agents:[]});
 }
 // 4. which candidate explanation survived the probes
 const hyps=ran('A24')?result('A24').claims.filter(c=>c.text_key==='a24.hypothesis').map(c=>c.params):[];
 if(!hyps.length)story.push({key:'flow.story.candidates.none',params:{},agents:['A24']});
 else{
  const pick=status=>hyps.filter(x=>x.status===status).map(x=>({mechanism:x.mechanism,column:x.column??null}));
  const supported=pick('supported'),open=pick('open'),refuted=pick('refuted').length,agents=['A24','A25','A28'].filter(ran);
  if(supported.length)story.push({key:'flow.story.candidates.supported',params:{survivors:supported,refuted,open:open.length},agents});
  else if(open.length)story.push({key:'flow.story.candidates.open',params:{survivors:open,refuted},agents});
  else story.push({key:'flow.story.candidates.refuted',params:{n:refuted},agents});
 }
 // 5. what awaits a human decision
 const items=record.approvals?.[0]?.items||[],decided=items.filter((_,i)=>detail.decisions?.[String(i)]?.decision).length;
 if(!items.length)story.push({key:'flow.story.approval.none',params:{},agents:['A33']});
 else story.push(decided<items.length?{key:'flow.story.approval.pending',params:{pending:items.length-decided,n:items.length},agents:['A33']}
  :{key:'flow.story.approval.decided',params:{n:items.length},agents:['A33']});
 return story;
}

if(typeof module!=='undefined')module.exports={FLOW_IDS,FLOW_LAYERS,FLOW_TYPES,FLOW_STATES,FLOW_SERVICES,FLOW_EDGE_TRANSPORT,FLOW_REPLAY_SPEEDS,FLOW_REPLAY_GAP_MS,
 flowLayer,flowInitial,reduceFlow,reduceAll,parseSse,flowEventText,flowSorted,flowLayout,flowChannel,flowRoutes,flowSimplify,flowRoundedPath,flowPlaceLabels,
 flowReplayPlan,flowReplayDue,flowStreamRegistry,flowBrief,flowStory};

// ---------- browser page ----------
let flowRoles=null,flowRolesLoading=false,flowRuns=null,flowRunsLoading=false,flowRunId=null,flowState=flowInitial(),flowDetail=null,flowReplay=null,flowPointed=null,
 flowEnd=null,flowBusy=false,flowError='',flowOpen=null,flowOpener=null,flowFocus='A01',flowAll=false,flowFrame=0,flowAnnounced=0,flowCtl=null,flowDyn=null,
 flowBaseline='',flowAsOf='',flowOwnFile=null,flowSecond=null;
const flowOpenDetails=new Set(),flowSeenEdges=new Set(),flowStreams=flowStreamRegistry();
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
// resumes with Last-Event-ID; the reducer ignores anything it already applied. ``control`` belongs to the stream
// registry, which keeps exactly one subscription per run id and never aborts it on a re-render.
async function streamFlow(runId,control){
 let tries=0,ended=false;
 const current=()=>!control.signal.aborted&&flowRunId===runId;
 while(!ended&&current()&&tries<6){
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
  if(!ended&&current()){tries++;await new Promise(r=>setTimeout(r,Math.min(5000,400*2**tries)));}
 }
 if(!current())return;
 if(ended)await loadFlowDetail(runId);else if(!flowError)flowError=t('flow.err.stream');
 loadFlowRuns(true);flowSchedule();
}
// A finished run is drawn from its sealed record (its events, in recorded order); a run that is still going, or whose
// state is not known yet, is followed live over the stream.
async function loadFlowSealed(runId){
 let detail=null;
 try{detail=await request('/api/agents/runs/'+runId);}
 catch(error){if(flowRunId===runId){flowError=error.status===404?t('flow.err.gone'):error.message;flowSchedule();}return;}
 if(flowRunId!==runId)return;
 if(detail.state!=='finished'||!detail.record){flowStreams.open(runId,control=>streamFlow(runId,control));return;}
 flowDetail=detail;flowEnd={error:null};
 if(!flowState.count)flowState=reduceAll(detail.record.events||[]);
 flowSchedule();
}
// A run known to be running is subscribed to at once; otherwise its detail decides (sealed record if finished,
// the live stream if it is still going or ended without a record).
function flowFollow(runId){
 const summary=(flowRuns?.runs||[]).find(r=>r.run_id===runId);
 if(summary?.state==='running')flowStreams.open(runId,control=>streamFlow(runId,control));
 else loadFlowSealed(runId);
}
function flowSyncUrl(){
 if(route==='/flow'&&typeof history!=='undefined'){
  const want=flowRunId?'/flow?run='+encodeURIComponent(flowRunId):'/flow';
  if(location.pathname+location.search!==want)history.replaceState({},'',want);
 }
}
// Show ``runId``. Selecting the run already shown keeps its subscription and state (a re-render or a second link to
// the same run never aborts the live stream); another run closes the old subscription first.
function viewFlowRun(runId){
 runId=runId||null;
 if(runId&&runId===flowRunId){
  flowSyncUrl();
  if(!flowStreams.has(runId)&&!flowDetail&&!flowEnd&&!flowError)flowFollow(runId);
  flowSchedule();return;
 }
 flowStreams.close();flowReplayStop(false);
 flowRunId=runId;flowState=flowInitial();flowDetail=null;flowEnd=null;flowError='';flowOpen=null;flowSeenEdges.clear();flowAnnounced=0;
 flowSyncUrl();
 if(flowRunId)flowFollow(flowRunId);
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
 viewFlowRun(runId);loadFlowRuns(true);navigate('/flow');flowSyncUrl();
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
// The agent whose links are emphasised: the one under the pointer or keyboard focus, else the one whose drawer is open.
const flowActive=()=>flowPointed||flowOpen||null;
// Emphasise the active agent's links (others drop to 15%) and label their transports where a label fits. Runs on
// hover and focus without rebuilding the diagram.
function flowHighlight(svg){
 if(!svg?.flowGeo)return;
 const id=flowActive(),{routes,obstacles,edges}=svg.flowGeo,linked=new Set();
 svg.classList.toggle('has-active',!!id);
 svg.querySelectorAll('.fe').forEach(p=>{const on=!!id&&(p.dataset.from===id||p.dataset.to===id);p.classList.toggle('hl',on);if(on)linked.add(p.dataset.from===id?p.dataset.to:p.dataset.from);});
 svg.querySelectorAll('.fn,.fs').forEach(g=>{g.classList.toggle('linked',linked.has(g.dataset.id));g.classList.toggle('active',!!id&&g.dataset.id===id);});
 const layer=svg.querySelector('.fl-labels');layer.replaceChildren();
 if(!id)return;
 const labels=routes.filter(r=>(r.from===id||r.to===id)&&edges[r.key].transport!=='in_process').map(r=>{const text=flowLabel('transport',edges[r.key].transport);return {key:r.key,text,points:r.points,w:text.length*5.6+10,h:12};});
 for(const spot of flowPlaceLabels(labels,obstacles)){
  const label=labels.find(l=>l.key===spot.key);
  layer.append(svgEl('rect',{x:spot.x-label.w/2,y:spot.y-label.h/2,width:label.w,height:label.h,rx:4,class:'fe-label-bg'}),svgText(label.text,{x:spot.x,y:spot.y+3.3,class:'fe-label','text-anchor':'middle'}));
 }
}
function flowPoint(svg,id){if(flowPointed===id)return;flowPointed=id;flowHighlight(svg);}
function flowSvg(){
 const narrow=!!flowNarrowQuery?.matches,L=flowLayout(narrow),st=flowState;
 const svg=svgEl('svg',{id:'flow-svg',viewBox:`0 0 ${L.width} ${L.height}`,class:'fl-svg'+(narrow?' narrow':''),role:'group','aria-label':t('flow.diagram.label'),'aria-describedby':'flow-legend'});
 svg.addEventListener('keydown',flowKeys);
 svg.addEventListener('mouseleave',()=>flowPoint(svg,null));
 svg.append(svgEl('defs',{},...['dep','tool','a2a','llm','verdict'].map(k=>svgEl('marker',{id:'fa-'+k,viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'5.5',markerHeight:'5.5',orient:'auto-start-reverse'},svgEl('path',{d:'M0 0 10 5 0 10z',class:'fa fa-'+k})))));
 for(const lane of L.lanes)svg.append(svgEl('rect',{x:lane.x,y:lane.y,width:lane.w,height:lane.h,rx:12,class:'fl-lane'}));
 svg.append(svgEl('rect',{x:0,y:L.services.y,width:L.width,height:L.services.h,rx:12,class:'fl-lane services'}));
 // Edges run in the gutters, under the lane titles and the boxes.
 const edges=svgEl('g',{class:'fl-edges','aria-hidden':'true'}),byKey={};
 const marker={dependency:'dep',mcp:'tool',rag:'tool',a2a:'a2a',llm:'llm',verdict:'verdict'};
 for(const e of st.edges)byKey[e.key]=e;
 const routes=flowRoutes(L,st.edges);
 for(const r of routes){
  const e=byKey[r.key],fresh=!flowSeenEdges.has(e.key);
  const path=svgEl('path',{d:r.d,class:`fe ${e.kind} t-${e.transport}`+(fresh?' fresh':''),'data-from':e.from,'data-to':e.to,'marker-end':`url(#fa-${marker[e.kind]})`});
  path.append(svgEl('title',{},document.createTextNode(t('flow.edge.title',{from:e.from,to:e.to,kind:t('flow.edge.'+e.kind),transport:flowLabel('transport',e.transport),n:e.count}))));
  edges.append(path);
 }
 svg.append(edges);
 for(const lane of L.lanes)svg.append(svgText(t('flow.layer.'+lane.layer),{x:lane.x+12,y:lane.y+20,class:'fl-lane-title'}));
 svg.append(svgText(t('flow.layer.services'),{x:12,y:L.services.y+20,class:'fl-lane-title'}));
 for(const k of FLOW_SERVICES){
  const p=L.pos[k],used=st.edges.some(e=>e.to===k);
  svg.append(svgEl('g',{class:'fs'+(used?' used':''),'data-id':k},svgEl('rect',{x:p.x,y:p.y,width:p.w,height:p.h,rx:9}),
   svgText(t('flow.svc.'+k),{x:p.x+10,y:p.y+22,class:'fs-title'}),svgText(t('flow.svc.'+k+'.x'),{x:p.x+10,y:p.y+40,class:'fs-meta'})));
 }
 if(!FLOW_IDS.includes(flowFocus))flowFocus='A01';
 for(const id of FLOW_IDS){
  const p=L.pos[id],n=st.nodes[id],kind=flowRole(id)?.kind;
  const g=svgEl('g',{id:'fn-'+id,class:`fn ${n.state}`+(flowOpen===id?' open':''),'data-id':id,role:'button',tabindex:id===flowFocus?'0':'-1','aria-label':flowNodeLabel(id),'aria-haspopup':'dialog'});
  g.addEventListener('click',()=>{flowFocus=id;openFlowAgent(id);});
  g.addEventListener('focus',()=>{if(flowFocus!==id){flowFocus=id;svg.querySelectorAll('.fn').forEach(x=>x.setAttribute('tabindex',x.dataset.id===id?'0':'-1'));}flowPoint(svg,id);});
  g.addEventListener('blur',()=>flowPoint(svg,null));
  g.addEventListener('mouseenter',()=>flowPoint(svg,id));
  const icon=svgEl('g',{class:'fl-icon '+n.state,transform:`translate(${p.x+8} ${p.y+42}) scale(.8)`});flowIconShapes(icon,n.state);
  g.append(...[svgEl('rect',{x:p.x,y:p.y,width:p.w,height:p.h,rx:9,class:'fn-box'}),svgEl('rect',{x:p.x,y:p.y+8,width:3,height:p.h-16,rx:1.5,class:'fn-bar'}),
   svgText(id,{x:p.x+10,y:p.y+17,class:'fn-id'}),kind?svgText(t('flow.kind.'+kind),{x:p.x+p.w-8,y:p.y+17,class:'fn-kind','text-anchor':'end'}):null,
   svgText(flowName(id),{x:p.x+10,y:p.y+35,class:'fn-name'}),icon,
   svgText(t('flow.state.'+n.state)+(n.wave?' · '+t('flow.wave.short',{n:n.wave}):''),{x:p.x+24,y:p.y+53,class:'fn-state'})].filter(Boolean));
  svg.append(g);
 }
 svg.append(svgEl('g',{class:'fl-labels','aria-hidden':'true'}));
 for(const e of st.edges)flowSeenEdges.add(e.key);
 // Labels may graze a box edge by up to 3 px (the gaps between rows are only 14 px tall), never cover its text.
 svg.flowGeo={routes,edges:byKey,obstacles:[...FLOW_IDS,...FLOW_SERVICES].map(id=>{const b=L.pos[id];return {x:b.x+3,y:b.y+3,w:b.w-6,h:b.h-6};})};
 flowHighlight(svg);
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
  h('div',{class:'panel-heading'},h('h2',{id:'flow-diagram-title',text:t('flow.diagram')}),flowReplay?chip(t('flow.badge.replay'),'info'):chip(flowRunId?t('flow.badge.events'):t('flow.badge.idle'),flowRunId?'ok':'muted')),
  h('p',{class:'hint',text:t('flow.diagram.x')}),flowReplayPanel(),h('div',{class:'fl-svg-wrap'},flowSvg()),flowLegend(),flowTable());
}

// ---------- replay at readable speed (recorded events only) ----------
const flowNow=()=>typeof performance!=='undefined'?performance.now():Date.now();
function startFlowReplay(speed){
 const events=flowDetail?.record?.events;
 if(!events?.length||flowStreams.has(flowRunId))return;
 flowReplayStop(false);
 flowReplay={speed,plan:flowReplayPlan(events,speed),index:0,started:flowNow(),timer:0};
 flowState=flowInitial();flowSeenEdges.clear();flowAnnounced=0;
 const live=document.getElementById('flow-live');if(live)live.textContent=t('flow.replay.started',{speed:N(speed)});
 flowReplayTick();
}
function flowReplayTick(){
 const r=flowReplay;if(!r)return;
 const elapsed=flowNow()-r.started,next=flowReplayDue(r.plan,elapsed,r.index);
 for(let i=r.index;i<next;i++)flowState=reduceFlow(flowState,r.plan[i].event);
 r.index=next;
 if(next>=r.plan.length){
  flowReplay=null;
  const live=document.getElementById('flow-live');if(live)live.textContent=t('flow.replay.done');
 }else r.timer=setTimeout(flowReplayTick,Math.max(0,r.plan[next].at-elapsed));
 flowSchedule();
}
// Stop a replay; with ``restore`` the diagram returns to the complete recorded run.
function flowReplayStop(restore=true){
 if(!flowReplay)return;
 clearTimeout(flowReplay.timer);flowReplay=null;
 if(restore&&flowDetail?.record){flowState=reduceAll(flowDetail.record.events||[]);flowSeenEdges.clear();}
 flowSchedule();
}
function flowReplayPanel(){
 const record=flowDetail?.record,r=flowReplay;
 if(!record||!record.events?.length)return null;
 const speeds=FLOW_REPLAY_SPEEDS.map(s=>h('button',{type:'button',id:'flow-replay-'+String(s).replace('.','-'),class:'secondary fl-speed','aria-pressed':String(r?.speed===s),
  'aria-label':t('flow.replay.speed.label',{speed:N(s)}),onclick:()=>startFlowReplay(s)},t('flow.replay.speed',{speed:N(s)})));
 const total=r?r.plan.length:record.events.length,shown=r?r.index:total;
 const bar=h('div',{class:'fl-replay-fill'});bar.style.width=(total?shown/total*100:0).toFixed(1)+'%';
 return h('div',{class:'fl-replay'+(r?' on':''),role:'group','aria-labelledby':'flow-replay-title'},
  h('div',{class:'fl-replay-head'},h('strong',{id:'flow-replay-title',text:t('flow.replay')}),
   r?chip(t('flow.replay.badge',{speed:N(r.speed)}),'info'):null),
  h('div',{class:'fl-replay-row'},h('div',{class:'cc-speeds fl-speeds'},speeds),
   r?h('button',{type:'button',id:'flow-replay-stop',class:'secondary',onclick:()=>flowReplayStop(true)},t('flow.replay.stop')):null,
   h('div',{class:'fl-replay-track','aria-hidden':'true'},bar),
   h('small',{class:'fl-replay-n',text:r?t('flow.replay.progress',{shown:N(shown),total:N(total)}):t('flow.replay.recorded',{n:N(total),ms:msText(record.duration_ms??flowState.used.elapsed_ms)})})),
  h('p',{class:'hint',text:t('flow.replay.x',{gap:msText(FLOW_REPLAY_GAP_MS)})}));
}

// ---------- run story (finished runs, from the sealed record) ----------
const flowCheckLabel=c=>tt('pf.check.'+c,tt('bl.check.'+c,tt('cc.check.'+c,String(c).replace(/_/g,' '))));
const flowList=items=>items.length<2?items.join(''):items.slice(0,-1).join(', ')+' '+t('flow.story.and')+' '+items[items.length-1];
// A code label in the middle of a sentence: lower-case unless it starts with an acronym ("PSI distribution shift").
const flowMid=text=>/^\p{Lu}\p{Ll}/u.test(text)?text[0].toLocaleLowerCase(language==='tr'?'tr':'en')+text.slice(1):text;
// "level shift and isolated jump on pressure_kpa, freshness": items grouped by column, in first-seen order.
function flowGrouped(items,word){
 const groups=[];
 for(const x of items){const g=groups.find(y=>y.column===x.column);if(g)g.what.push(word(x));else groups.push({column:x.column,what:[word(x)]});}
 return groups.map(g=>g.column?t('flow.story.on',{what:flowList(g.what),column:g.column}):flowList(g.what)).join('; ');
}
function flowStoryParams(item){
 const p={...item.params},check=x=>flowMid(flowCheckLabel(x.check)),mech=m=>flowMid(tt('hy.mech.'+m,String(m).replace(/_/g,' ')));
 if(p.signals)p.signals=flowGrouped(p.signals,check);
 if(p.found)p.found=flowGrouped(p.found,check);
 if(p.survivors)p.survivors=flowGrouped(p.survivors,x=>mech(x.mechanism));
 if(p.mechanisms)p.mechanisms=p.mechanisms.length?flowList(p.mechanisms.map(mech)):t('flow.story.nothing');
 for(const k of ['agents','needs'])if(Array.isArray(p[k]))p[k]=flowList(p[k]);
 if(p.reason)p.reason=tt('flow.jr.'+p.reason,String(p.reason).replace(/_/g,' '));
 for(const k of ['n','accepted','claims','refuted','open','pending','advisory','rejected'])if(typeof p[k]==='number')p[k]=N(p[k]);
 return p;
}
function flowStoryPanel(){
 if(!flowDetail?.record)return null;
 const items=flowStory(flowDetail);
 return h('section',{class:'panel fl-story','aria-labelledby':'flow-story-title'},
  h('div',{class:'panel-heading'},h('h2',{id:'flow-story-title',text:t('flow.story')}),chip(t('flow.story.chip'),'ok')),
  h('ol',{class:'fl-story-list'},items.map((item,i)=>h('li',{class:'fl-story-item'},
   h('span',{class:'fl-story-n','aria-hidden':'true',text:String(i+1)}),
   h('div',{},h('p',{text:t(item.key,flowStoryParams(item))}),
    item.agents.length?h('div',{class:'fl-story-links'},item.agents.map(id=>h('button',{type:'button',class:'fl-link fl-chiplink',id:`fs-${i}-${id}`,
     'aria-label':t('flow.how.open',{id,name:flowName(id)}),onclick:()=>openFlowAgent(id,`fs-${i}-${id}`)},`${id} · ${flowName(id)}`))):null)))),
  h('p',{class:'panel-note',text:t('flow.story.note')}));
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
 live.textContent=(flowReplay?t('flow.replay.prefix')+' ':'')+t(m.key,params);
}
function flowPaint(root){
 if(!root||!connected)return;
 const active=document.activeElement,activeId=active&&root.contains(active)?active.id:null;
 const scroll={};for(const id of ['flow-timeline-list','flow-drawer-body']){const n=document.getElementById(id);if(n)scroll[id]=n.scrollTop;}
 const controls=flowControls();
 if(!flowDyn)flowDyn=h('div',{class:'fl-dyn'});
 if(root.firstChild!==controls||root.lastChild!==flowDyn)root.replaceChildren(controls,flowDyn);
 flowDyn.replaceChildren(flowHeader(),flowStoryPanel()||'',flowDiagramPanel(),h('div',{class:'fl-grid'},flowTimelinePanel(),flowResultsPanel()),flowExplainer(),flowDrawer()||'');
 for(const [id,top] of Object.entries(scroll)){const n=document.getElementById(id);if(n)n.scrollTop=top;}
 if(activeId&&document.activeElement!==document.getElementById(activeId))document.getElementById(activeId)?.focus({preventScroll:true});
 flowAnnounce();
 if(typeof refreshBrief==='function'&&route==='/flow')refreshBrief();
}
function renderFlow(){
 const root=$('screen-flow');
 if(!connected){flowStreams.close();flowReplayStop(false);flowOpen=null;root.replaceChildren(h('section',{class:'panel'},empty('flow.connect.t','flow.connect.x')),flowExplainer());flowCtl=null;flowDyn=null;flowOwnFile=null;flowSecond=null;return;}
 loadFlowRoles();loadFlowRuns();loadBaselines();
 if(!flowRunId&&!flowStreams.size){
  const linked=typeof location!=='undefined'?new URLSearchParams(location.search).get('run'):null;
  if(linked)viewFlowRun(linked);else if(flowRuns?.active)viewFlowRun(flowRuns.active);
 }
 flowPaint(root);
}
// The page brief's two live answers, recomputed from the current state on every paint.
function flowBriefNow(){
 const record=flowDetail?.record,items=record?.approvals?.[0]?.items||[],decided=items.filter((_,i)=>flowDetail?.decisions?.[String(i)]?.decision).length;
 const nodes=Object.values(flowState.nodes);
 const b=flowBrief({connected,runId:flowRunId,runs:flowRuns?.runs?.length||0,status:flowState.status,count:flowState.count,
  running:nodes.filter(n=>n.state==='running').length,done:nodes.filter(n=>n.finished).length,error:!!flowEnd?.error||(!!flowError&&!flowState.count),record:!!record,
  pending:items.length-decided,total:items.length,ms:flowState.used.elapsed_ms,
  replay:flowReplay?{speed:N(flowReplay.speed),shown:N(flowReplay.index),total:N(flowReplay.plan.length)}:null},flowLabel);
 const num=p=>Object.fromEntries(Object.entries(p).map(([k,v])=>[k,typeof v==='number'?N(v):v]));
 return {happened:t(b.happened.key,num(b.happened.params)),next:t(b.next.key,num(b.next.params))};
}
if(typeof document!=='undefined'){
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&flowOpen&&route==='/flow'){e.preventDefault();closeFlowAgent();}});
 flowNarrowQuery?.addEventListener?.('change',()=>{if(route==='/flow')flowSchedule();});
}
