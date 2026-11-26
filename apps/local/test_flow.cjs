// SPDX-License-Identifier: Apache-2.0
// The Agent flow page's pure core: events -> node states, edges, budgets and timeline; SSE framing; sentences; layout.
const assert=require('node:assert/strict');
global.language='en';
const {STRINGS}=require('./strings.js');
const F=require('./flow.js');
const usage=(llm=0,tin=0,tout=0)=>({tool_calls:1,llm_calls:llm,tokens_in:tin,tokens_out:tout,latency_ms:3});
const finished=(status,extra={})=>({status,error_code:status==='COMPLETED'?null:extra.code||'X',transport:'in_process',claims:1,evidence_refs:1,proposals:0,usage:usage(),attempt:1,...extra});
let seq=0;const ev=(agent,type,data,t_ms)=>({seq:++seq,t_ms:t_ms??seq*2,agent_id:agent,type,data});
// A small but complete run, in live (arrival) order, covering every event type.
const events=[
 ev('A01','run_started',{run_id:'run-x',tenant_id:'local',case_id:'c',transport_plan:{requested:'auto',tools:{mode:'mcp_local',reason:null},judge:{mode:'a2a_mtls',reason:null}},limits:{specialists:8,llm_calls:12,tokens:40000,elapsed_ms:90000}}),
 ev('A01','agent_selected',{reason:'always'}),
 ev('A10','tool_call',{tool:'profile_csv',phase:'intake',transport:'in_process',reason:'case_intake',outcome:'ok',latency_ms:1}),
 ev('A02','agent_selected',{reason:'always'}),
 ev('A02','agent_started',{wave:1,stage:'plan',attempt:1,depends_on:[],budget:{max_tool_calls:8,max_llm_calls:1,max_tokens:40000,deadline_ms:60000}}),
 ev('A02','cache',{template:'a02',result:'miss'}),
 ev('A02','llm_call',{template:'a02',model:'qwen3:4b',prompt_sha256:'a'.repeat(64),ok:false,error_code:'MODEL_UNAVAILABLE',tokens_in:0,tokens_out:0,cache:'miss',latency_ms:4}),
 ev('A02','agent_finished',finished('COMPLETED',{usage:usage(1,0,0)})),
 ev('A10','agent_selected',{reason:'first_specialist'}),
 ev('A12','agent_skipped',{reason:'no_log_source',error_code:'NOT_SELECTED',unmet:[]}),
 ev('A22','agent_selected',{reason:'knowledge_source_given'}),
 ev('A10','agent_started',{wave:2,stage:'specialists',attempt:1,depends_on:[],budget:{max_tool_calls:8,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A10','tool_call',{tool:'profile_csv',phase:'agent',transport:'in_process',reason:'tool_not_in_mcp_profile',outcome:'ok',latency_ms:1}),
 ev('A10','agent_finished',finished('COMPLETED')),
 ev('A22','agent_started',{wave:3,stage:'specialists',attempt:1,depends_on:['A10'],budget:{max_tool_calls:8,max_llm_calls:1,max_tokens:40000,deadline_ms:60000}}),
 ev('A09','agent_selected',{reason:'order_extract'}),
 ev('A09','agent_started',{wave:3,stage:'specialists',attempt:1,depends_on:['A10'],budget:{max_tool_calls:8,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 // A22 (higher id) finishes before A09 (lower id): completion order, not id order.
 ev('A22','tool_call',{tool:'knowledge_retrieve',phase:'agent',transport:'in_process',reason:'tool_not_in_mcp_profile',outcome:'ok',latency_ms:2}),
 ev('A22','retrieval',{citations:2,sources:['duplicate-guidance']}),
 ev('A22','llm_call',{template:'a22',model:'qwen3:4b',prompt_sha256:'b'.repeat(64),ok:true,error_code:null,tokens_in:40,tokens_out:12,cache:'hit',latency_ms:5}),
 ev('A22','agent_finished',finished('COMPLETED',{usage:usage(1,40,12)})),
 ev('A09','tool_call',{tool:'diagnose_csv',phase:'agent',transport:'mcp_local',reason:null,outcome:'ok',latency_ms:9},30),
 ev('A09','agent_finished',finished('NEEDS_EVIDENCE',{code:'NOT_ORDER_EXTRACT',transport:'mcp_local'}),31),
 ev('A11','agent_selected',{reason:'baseline_given'}),
 ev('A11','agent_skipped',{reason:'specialist_limit',error_code:'BUDGET_EXCEEDED',unmet:[]}),
 ev('A13','agent_selected',{reason:'order_extract'}),
 ev('A13','agent_skipped',{reason:'dependency_unmet',error_code:'DEPENDENCY_UNMET',unmet:['A09']}),
 ev('A14','agent_selected',{reason:'order_extract'}),
 ev('A14','agent_started',{wave:4,stage:'specialists',attempt:1,depends_on:['A10'],budget:{max_tool_calls:8,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A14','agent_finished',finished('FAILED',{code:'DEADLINE_EXCEEDED',abandoned:true})),
 ev('A06','agent_selected',{reason:'failed_agent'}),
 ev('A06','agent_started',{wave:5,stage:'recovery',attempt:1,depends_on:[],budget:{max_tool_calls:0,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A06','agent_finished',finished('COMPLETED')),
 ev('A14','agent_started',{wave:6,stage:'retry',attempt:2,depends_on:['A10'],budget:{max_tool_calls:8,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A14','agent_finished',finished('COMPLETED',{attempt:2})),
 ev('A34','agent_selected',{reason:'always'}),
 ev('A34','agent_started',{wave:7,stage:'governance',attempt:1,depends_on:[],budget:{max_tool_calls:0,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A34','agent_finished',finished('POLICY_DENIED',{code:'RAW_VALUE_IN_CONTEXT'})),
 ev('A27','agent_selected',{reason:'always'}),
 ev('A27','agent_started',{wave:8,stage:'judge',attempt:1,depends_on:[],budget:{max_tool_calls:0,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A27','agent_finished',finished('COMPLETED',{transport:'a2a_mtls',certificates:{ca_sha256:'c'.repeat(64),server_sha256:'d'.repeat(64),client_sha256:'e'.repeat(64)}})),
 ev('A27','judge_verdict',{subject:'A10',pass:'gate',accepted:1,advisory:0,rejected:0,verdicts:[{claim:0,verdict:'accepted',reason:'evidence_verified'}]}),
 ev('A27','judge_verdict',{subject:'A22',pass:'gate',accepted:1,advisory:1,rejected:1,verdicts:[{claim:0,verdict:'accepted',reason:'evidence_verified'},{claim:1,verdict:'advisory',reason:'model_suggestion'},{claim:null,verdict:'rejected',reason:'unverified_citation'}]}),
 ev('A27','judge_verdict',{subject:'invalid',pass:'gate',accepted:0,advisory:0,rejected:1,verdicts:[{claim:null,verdict:'rejected',reason:'invalid_result'}]}),
 ev('A33','agent_selected',{reason:'proposals_exist'}),
 ev('A33','agent_started',{wave:9,stage:'governance',attempt:1,depends_on:[],budget:{max_tool_calls:0,max_llm_calls:0,max_tokens:0,deadline_ms:60000}}),
 ev('A33','agent_finished',finished('COMPLETED')),
 ev('A33','approval_requested',{items:2,decision:'pending',executed:false}),
 ev('A27','judge_verdict',{subject:'A27',pass:'closing',accepted:1,advisory:0,rejected:0,verdicts:[{claim:0,verdict:'accepted',reason:'evidence_verified'}]}),
 ev('A01','run_finished',{status:'failed_agents',duration_ms:120,budget_exceeded:['specialists']}),
];
assert.deepEqual([...new Set(events.map(e=>e.type))].sort(),[...F.FLOW_TYPES].sort(),'the fixture covers every event type');
const initial=F.flowInitial();
assert.equal(Object.keys(initial.nodes).length,36);
assert.ok(Object.values(initial.nodes).every(n=>n.state==='idle'));
assert.deepEqual(initial.limits,{specialists:8,llm_calls:12,tokens:40000,elapsed_ms:90000});
const frozen=JSON.stringify(initial);
const s=F.reduceAll(events);
assert.equal(JSON.stringify(initial),frozen,'the reducer never mutates its input');
const n=id=>s.nodes[id];
// run-level
assert.equal(s.runId,'run-x');assert.equal(s.status,'failed_agents');assert.equal(s.plan.judge.mode,'a2a_mtls');
assert.deepEqual(s.finished.budget_exceeded,['specialists']);assert.equal(s.used.elapsed_ms,120);assert.equal(s.lastSeq,events.length);assert.equal(s.count,events.length);
// every state is reachable from events
assert.equal(n('A01').state,'selected');assert.equal(n('A02').state,'completed');assert.equal(n('A12').state,'skipped');
assert.equal(n('A09').state,'needs_evidence');assert.equal(n('A09').errorCode,'NOT_ORDER_EXTRACT');assert.equal(n('A09').transport,'mcp_local');
assert.equal(n('A11').state,'skipped');assert.equal(n('A11').errorCode,'BUDGET_EXCEEDED');assert.equal(n('A11').selected,true);
assert.deepEqual(n('A13').unmet,['A09']);assert.equal(n('A34').state,'denied');assert.equal(n('A36').state,'idle');
assert.equal(n('A14').state,'completed');assert.equal(n('A14').attempt,2);assert.equal(n('A14').wave,6);assert.equal(n('A14').abandoned,false);
{const mid=F.reduceAll(events.slice(0,events.findIndex(e=>e.agent_id==='A14'&&e.type==='agent_finished')+1));
 assert.equal(mid.nodes.A14.state,'failed');assert.equal(mid.nodes.A14.abandoned,true);assert.equal(mid.milestone.key,'flow.ms.failed');}
{const running=F.reduceAll(events.slice(0,5));assert.equal(running.nodes.A02.state,'running');assert.equal(running.nodes.A02.wave,1);assert.equal(running.milestone.key,'flow.ms.wave');}
assert.equal(n('A22').state,'completed');assert.equal(n('A22').retrieval.citations,2);
assert.equal(n('A22').llm[0].cache,'hit');assert.equal(n('A02').llm[0].error_code,'MODEL_UNAVAILABLE');assert.deepEqual(n('A02').cache,[{template:'a02',result:'miss'}]);
assert.deepEqual(n('A10').tools.map(x=>x.phase),['intake','agent']);
assert.equal(n('A27').certificates.ca_sha256,'c'.repeat(64));
assert.equal(n('A22').verdicts[0].rejected,1);assert.equal(n('A27').verdicts[0].pass,'closing');
assert.deepEqual(s.judge,{accepted:3,advisory:1,rejected:2});
assert.deepEqual(s.approval,{items:2,decision:'pending',executed:false});
assert.deepEqual(s.waves.map(w=>w.wave),[1,2,3,4,5,6,7,8,9]);
assert.equal(s.milestone.key,'flow.ms.finished');
// edges appear only for real dependencies and messages, labelled by transport
const edge=key=>s.edges.find(e=>e.key===key);
assert.equal(edge('A10>A22:dependency').transport,'in_process');assert.equal(edge('A10>A14:dependency').count,2,'the retry repeats its dependency');
assert.equal(edge('A09>MCP:mcp').transport,'mcp_local');assert.equal(edge('A22>KB:rag').transport,'in_process');
assert.equal(edge('A02>LLM:llm').transport,'local_llm');assert.equal(edge('A01>A27:a2a').transport,'a2a_mtls');
assert.equal(edge('A27>A22:verdict').transport,'in_process');assert.ok(!s.edges.some(e=>e.to==='invalid'));
assert.ok(!s.edges.some(e=>e.from==='A10'&&e.to==='MCP'),'an in-process tool call draws no MCP edge');
for(const e of s.edges)assert.ok(['in_process','mcp_local','a2a_mtls','local_llm'].includes(e.transport));
// budgets: specialists admitted, model calls and tokens from the agents' final usage (a retry is not double counted)
assert.deepEqual({sp:s.used.specialists,llm:s.used.llm_calls,tok:s.used.tokens},{sp:4,llm:2,tok:52});
// ordering: completion order differs from id order; the sealed record orders spans by agent id. Same final view.
const sealed=[...events].sort((a,b)=>a.agent_id.localeCompare(b.agent_id)).map((e,i)=>({...e,seq:i+1}));
const fromSealed=F.reduceAll(sealed);
for(const id of F.FLOW_IDS)assert.equal(fromSealed.nodes[id].state,s.nodes[id].state,id);
// reconnect replay is idempotent: anything at or below the last applied seq changes nothing
assert.equal(F.reduceFlow(s,events[3]),s);assert.equal(F.reduceAll(events,s),s);
const k=20,part=F.reduceAll(events.slice(0,k)),resumed=F.reduceAll(events.slice(k-5),part);
assert.deepEqual(resumed,s,'a resume that overlaps already-applied events ends in the same state');
// malformed and unknown events never throw
assert.equal(F.reduceFlow(s,null),s);assert.equal(F.reduceFlow(s,{seq:'9'}),s);
const odd=F.reduceFlow(initial,{seq:1,t_ms:1,agent_id:'A99',type:'agent_started',data:{}});
assert.equal(odd.lastSeq,1);assert.equal(odd.timeline.length,0);
assert.equal(F.reduceFlow(initial,{seq:1,t_ms:1,agent_id:'A01',type:'mystery',data:{}}).count,0);
// timeline: sorted by run clock, ties by seq
const sorted=F.flowSorted(s.timeline);
for(let i=1;i<sorted.length;i++)assert.ok(sorted[i-1].t_ms<sorted[i].t_ms||(sorted[i-1].t_ms===sorted[i].t_ms&&sorted[i-1].seq<sorted[i].seq));
// every event yields a defined sentence with all its placeholders supplied, in both languages
const placeholders=text=>[...text.matchAll(/\{(\w+)\}/g)].map(m=>m[1]);
for(const e of s.timeline){
 const x=F.flowEventText(e);
 assert.ok(STRINGS[x.key],`${x.key} is not defined`);
 for(const text of STRINGS[x.key])for(const p of placeholders(text))assert.ok(x.params[p]!==undefined,`${x.key}: {${p}} missing`);
}
assert.equal(F.flowEventText({type:'?',data:{}}).key,'flow.ev.unknown');
assert.equal(F.flowEventText(s.timeline.find(e=>e.type==='agent_skipped'&&e.data.unmet.length)).key,'flow.ev.agent_skipped.unmet');
assert.equal(F.flowEventText(s.timeline.find(e=>e.type==='llm_call'&&!e.data.ok)).key,'flow.ev.llm_call.failed');
// strings for every state, status, layer, kind, edge, transport, stage and the short names exist
for(const st of F.FLOW_STATES)assert.ok(STRINGS['flow.state.'+st]);
for(const st of ['idle','running','completed','completed_with_gaps','failed_agents','budget_exceeded','input_rejected','error'])assert.ok(STRINGS['flow.status.'+st],st);
for(const [l] of F.FLOW_LAYERS)assert.ok(STRINGS['flow.layer.'+l]&&STRINGS['flow.how.'+l]);
for(const k of ['control','rule','llm','hybrid'])assert.ok(STRINGS['flow.kind.'+k]&&STRINGS['flow.kind.'+k+'.x']);
for(const k of ['dependency','verdict','mcp','a2a','llm','rag'])assert.ok(STRINGS['flow.edge.'+k]);
for(const k of ['in_process','mcp_local','a2a_mtls','local_llm'])assert.ok(STRINGS['flow.tr.'+k]);
for(const k of ['plan','route','schedule','specialists','reasoning','judge','remediation','validation','governance','budget','collect','close','recovery','retry'])assert.ok(STRINGS['flow.stage.'+k],k);
for(const k of F.FLOW_SERVICES)assert.ok(STRINGS['flow.svc.'+k]&&STRINGS['flow.svc.'+k+'.x']);
for(const k of ['llm','rag','cag','tag','judge','mcp','a2a','mtls','budget'])assert.ok(STRINGS['flow.how.'+k+'.t']&&STRINGS['flow.how.'+k]&&STRINGS['flow.how.'+k+'.limit'],k);
for(const id of F.FLOW_IDS){assert.ok(STRINGS['flow.name.'+id]&&STRINGS['flow.lim.'+id],id);assert.ok(STRINGS['flow.name.'+id].every(x=>x.length<=21),`${id}: short name must fit its box`);}
for(const k of ['approved','rejected'])assert.ok(STRINGS['flow.decision.'+k]);
// honesty: no flow string claims a root cause was found or that anything was executed
for(const [key,[en]] of Object.entries(STRINGS))if(key.startsWith('flow.'))assert.ok(!/\bthe root cause is\b|(?<!nothing )\bwas applied\b|\bexecuted the\b/i.test(en),key);
// SSE framing: split frames, comments, CRLF, multi-line data, the end event and an unfinished remainder
{
 const a=F.parseSse('id: 1\nevent: agent\ndata: {"a":1}\n\n: heartbeat\n\nid: 2\r\nevent: agent\r\ndata: {"b":\r\ndata: 2}\r\n\r\nevent: end\ndata: {"error": null}\n\nid: 3\nevent: ag');
 assert.deepEqual(a.frames,[{id:'1',event:'agent',data:'{"a":1}'},{id:'2',event:'agent',data:'{"b":\n2}'},{id:null,event:'end',data:'{"error": null}'}]);
 assert.equal(a.rest,'id: 3\nevent: ag');
 const b=F.parseSse(a.rest+'ent\ndata:x\n\n');assert.deepEqual(b.frames,[{id:'3',event:'agent',data:'x'}]);assert.equal(b.rest,'');
 assert.deepEqual(F.parseSse('data\n\n').frames,[{id:null,event:'message',data:''}]);
 assert.deepEqual(F.parseSse(': only a comment\n\n').frames,[]);
}
// layout: every agent and service has a box inside the canvas; boxes never overlap; the narrow layout fits a phone
for(const narrow of [false,true]){
 const L=F.flowLayout(narrow),boxes=[...F.FLOW_IDS,...F.FLOW_SERVICES].map(id=>({id,...L.pos[id]}));
 for(const b of boxes){assert.ok(b.x>=0&&b.y>=0&&b.x+b.w<=L.width&&b.y+b.h<=L.height,`${b.id} outside (${narrow})`);}
 for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const p=boxes[i],q=boxes[j];
  assert.ok(p.x+p.w<=q.x||q.x+q.w<=p.x||p.y+p.h<=q.y||q.y+q.h<=p.y,`${p.id} overlaps ${q.id}`);}
 for(const id of F.FLOW_IDS){const lane=L.lanes.find(l=>l.layer===F.flowLayer(id)),b=L.pos[id];assert.ok(b.x>=lane.x&&b.x+b.w<=lane.x+lane.w&&b.y>=lane.y&&b.y+b.h<=lane.y+lane.h,`${id} outside its lane`);}
 if(narrow)assert.ok(L.width<=360);
 // Orthogonal routing: every possible edge runs horizontally/vertically through gutters and streets only, starts on
 // its source box and ends on its target box, and never crosses any box.
 const all=[];for(const a of F.FLOW_IDS)for(const b of [...F.FLOW_IDS,...F.FLOW_SERVICES])if(a!==b)all.push({key:`${a}>${b}`,from:a,to:b});
 const routes=F.flowRoutes(L,all);assert.equal(routes.length,all.length);
 const on=(p,b)=>p[0]>=b.x-0.01&&p[0]<=b.x+b.w+0.01&&p[1]>=b.y-0.01&&p[1]<=b.y+b.h+0.01;
 for(const r of routes){
  assert.ok(on(r.points[0],L.pos[r.from])&&on(r.points[r.points.length-1],L.pos[r.to]),`${r.key} ends on its boxes`);
  for(let i=1;i<r.points.length;i++){
   const [x1,y1]=r.points[i-1],[x2,y2]=r.points[i];
   assert.ok(x1===x2||y1===y2,`${r.key}: segment ${i} is not orthogonal`);
   for(const b of boxes){const lx=Math.min(x1,x2),hx=Math.max(x1,x2),ly=Math.min(y1,y2),hy=Math.max(y1,y2);
    assert.ok(!(lx<b.x+b.w-0.5&&hx>b.x+0.5&&ly<b.y+b.h-0.5&&hy>b.y+0.5),`${r.key} crosses ${b.id} (${narrow})`);}
  }
  assert.match(r.d,/^M[\d.]+ [\d.]+( L[\d.]+ [\d.]+ Q[\d. ]+)* L[\d.]+ [\d.]+$/,'rounded orthogonal path');
 }
 // Tracks stay inside their gutter.
 for(const r of routes)for(const [x] of r.points.slice(1,-1)){if(L.channels.some(c=>x>c.lo&&x<c.hi))continue;assert.ok(Object.values(L.pos).some(b=>x>=b.x&&x<=b.x+b.w),`${r.key}: x ${x} outside every gutter`);}
}
// Bundling: legs leaving one agent share a track; legs into one service share a track.
{
 const L=F.flowLayout(false),R=F.flowRoutes(L,[{key:'a',from:'A27',to:'A10'},{key:'b',from:'A27',to:'A08'},{key:'c',from:'A10',to:'LLM'},{key:'d',from:'A23',to:'LLM'}]);
 const r=k=>R.find(x=>x.key===k);
 assert.equal(r('a').points[1][0],r('b').points[1][0],'edges from the same agent share the source gutter track');
 assert.equal(r('c').points[r('c').points.length-2][1],r('d').points[r('d').points.length-2][1],'edges into one service share the street track');
 assert.equal(F.flowRoutes(L,[{key:'x',from:'KB',to:'A01'},{key:'y',from:'A01',to:'A99'}]).length,0,'edges from services or to unknown boxes are not drawn');
}
assert.deepEqual(F.flowSimplify([[0,0],[0,0],[5,0],[10,0],[10,5]]),[[0,0],[10,0],[10,5]]);
assert.equal(F.flowRoundedPath([[0,0],[20,0],[20,20]],6),'M0 0 L14 0 Q20 0 20 6 L20 20');
assert.equal(F.flowRoundedPath([[0,0],[4,0],[4,20]],6),'M0 0 L2 0 Q4 0 4 2 L4 20','the radius shrinks on short segments');
assert.equal(F.flowRoundedPath([]),'');
// Labels: no overlap with nodes or each other; a label with no free spot is dropped.
{
 const labels=[{key:'a',w:40,h:12,points:[[0,50],[200,50]]},{key:'b',w:40,h:12,points:[[0,52],[200,52]]},{key:'c',w:40,h:12,points:[[0,100],[0,200]]},{key:'d',w:40,h:12,points:[[0,10],[30,10]]},{key:'e',w:40,h:12,points:[[0,51],[200,51]]}];
 const placed=F.flowPlaceLabels(labels,[{x:80,y:40,w:40,h:20}]);
 assert.deepEqual(placed.map(p=>p.key),['a','b','c'],'d has no segment long enough; e finds every spot taken');
 assert.deepEqual(placed.slice(0,2).map(p=>p.x),[60,140],'labels move along their segment off the node and off each other');
}
assert.equal(F.flowLayer('A07'),'specialists');assert.equal(F.flowLayer('A99'),null);
// Replay scheduler: recorded event times -> delays, stretched by 1/speed, with a minimum spacing for bursts.
{
 const rec=[{seq:3,t_ms:100,agent_id:'A02',type:'x'},{seq:1,t_ms:0,agent_id:'A01',type:'x'},{seq:2,t_ms:0,agent_id:'A01',type:'y'},{seq:4,t_ms:1000,agent_id:'A03',type:'x'},{seq:5,agent_id:'A03'}];
 const p1=F.flowReplayPlan(rec,1,60);
 assert.deepEqual(p1.map(x=>[x.event.seq,x.at]),[[1,0],[2,60],[3,120],[4,1000]],'ordered by run clock, renumbered, bursts spaced, malformed dropped');
 assert.deepEqual(p1.map(x=>x.event.agent_id),['A01','A01','A02','A03']);
 const q=F.flowReplayPlan(rec,0.25,60);
 assert.deepEqual(q.map(x=>x.at),[0,240,480,4000],'0.25x stretches the relative timing four-fold');
 assert.deepEqual(F.flowReplayPlan(rec,0.5,0).map(x=>x.at),[0,0,200,2000]);
 for(const s of F.FLOW_REPLAY_SPEEDS){const plan=F.flowReplayPlan(events,s);for(let i=1;i<plan.length;i++)assert.ok(plan[i].at-plan[i-1].at>=F.FLOW_REPLAY_GAP_MS/s-1e-9);}
 assert.throws(()=>F.flowReplayPlan(rec,0),RangeError);assert.deepEqual(F.flowReplayPlan(null,1),[]);
 assert.equal(F.flowReplayDue(q,0),1);assert.equal(F.flowReplayDue(q,480),3);assert.equal(F.flowReplayDue(q,481,3),3);assert.equal(F.flowReplayDue(q,1e9,0),4);
 // A full replay ends in the same view as the live run (on a run clock that agrees with arrival order, as in a
 // real record; the fixture above hand-sets two A09 times).
 const timed=events.map(e=>({...e,t_ms:e.seq*2})),replayed=F.reduceAll(F.flowReplayPlan(timed,1).map(x=>x.event));
 for(const id of F.FLOW_IDS)assert.equal(replayed.nodes[id].state,s.nodes[id].state,id);
 assert.equal(replayed.count,s.count);
}
// Stream registry: one subscription per run id; re-opening the same run neither aborts nor re-subscribes.
(async()=>{
 const reg=F.flowStreamRegistry();let starts=0;const gate=[];
 const start=c=>{starts++;return new Promise(r=>gate.push(r));};
 const a=reg.open('run-a',start),again=reg.open('run-a',start);
 assert.equal(a,again);assert.equal(a.signal.aborted,false);assert.equal(reg.size,1);
 await Promise.resolve();await Promise.resolve();assert.equal(starts,1,'a duplicate subscription is never started');
 const b=reg.open('run-b',start);assert.equal(a.signal.aborted,true,'switching runs aborts the old stream');assert.ok(reg.has('run-b')&&!reg.has('run-a'));
 await new Promise(r=>setTimeout(r,0));gate.forEach(r=>r());await new Promise(r=>setTimeout(r,0));
 assert.equal(reg.size,0,'a settled subscription is dropped');assert.equal(b.signal.aborted,false);
 const c=reg.open('run-c',()=>{throw new Error('x');});reg.close();assert.equal(c.signal.aborted,true);assert.equal(reg.size,0);
 console.log('stream registry verified.');
})();
// Page brief: computed from the state on every render.
{
 const B=c=>F.flowBrief({connected:true,runs:0,status:'idle',count:0,...c});
 const keys=b=>[b.happened.key,b.next.key];
 assert.deepEqual(keys(F.flowBrief({connected:false})),['flow.brief.connect','flow.next.connect']);
 assert.deepEqual(keys(B({})),['flow.brief.none','flow.next.start']);
 assert.deepEqual(keys(B({runs:3})),['flow.brief.none.runs','flow.next.start']);
 assert.deepEqual(keys(B({runId:'run-x'})),['flow.brief.waiting','flow.next.watch']);
 const live=B({runId:'run-x',status:'running',count:40,running:2,done:9});
 assert.deepEqual(keys(live),['flow.brief.running','flow.next.watch']);assert.deepEqual(live.happened.params,{n:40,running:2,done:9});
 const done=B({runId:'run-x',status:'completed',count:121,record:false,ms:9000});
 assert.deepEqual(keys(done),['flow.brief.finished','flow.next.record']);assert.equal(done.happened.params.n,121,'a finished run reports its real event count');
 assert.deepEqual(keys(B({runId:'run-x',status:'completed',count:121,record:true,pending:2,total:2})),['flow.brief.finished','flow.next.approve']);
 assert.deepEqual(keys(B({runId:'run-x',status:'completed',count:121,record:true,pending:0,total:2})),['flow.brief.finished','flow.next.decided']);
 assert.deepEqual(keys(B({runId:'run-x',status:'completed',count:121,record:true,pending:0,total:0})),['flow.brief.finished','flow.next.story']);
 assert.deepEqual(keys(B({runId:'run-x',status:'running',count:3,error:true})),['flow.brief.error','flow.next.retry']);
 assert.deepEqual(keys(B({runId:'run-x',status:'completed',count:121,record:true,replay:{speed:0.5,shown:4,total:121}})),['flow.brief.replay','flow.next.replay']);
 const lab=F.flowBrief({connected:true,runId:'r',status:'completed',count:5,record:true,ms:1500},(k,v)=>k+':'+v);
 assert.equal(lab.happened.params.status,'runstatus:completed');assert.equal(lab.happened.params.ms,'ms:1500');
 const cases=[F.flowBrief({connected:false}),B({}),B({runs:2}),B({runId:'r'}),live,done,B({runId:'r',status:'completed',count:1,record:true,pending:1,total:1}),
  B({runId:'r',status:'completed',count:1,record:true,total:1,pending:0}),B({runId:'r',status:'completed',count:1,record:true}),B({runId:'r',error:true}),B({runId:'r',status:'completed',count:1,record:true,replay:{speed:1,shown:1,total:1}})];
 for(const b of cases)for(const part of [b.happened,b.next]){assert.ok(STRINGS[part.key],part.key);for(const text of STRINGS[part.key])for(const name of placeholders(text))assert.ok(part.params[name]!==undefined,`${part.key}: {${name}}`);}
}
// Run story: five plain sentences from a sealed record, each linking to agents; no causal wording.
{
 const agent=(id,status,claims=[],error=null)=>({agent_id:id,result:{status,claims,error_code:error}});
 const claim=(text_key,params)=>({text_key,params,evidence_refs:[]});
 const agents=F.FLOW_IDS.map(id=>agent(id,'SKIPPED'));const set=(id,...a)=>{agents[F.FLOW_IDS.indexOf(id)]=agent(id,...a);};
 set('A10','COMPLETED',[claim('a10.profile',{records:200}),claim('a10.finding',{check:'outlier',column:'p'}),claim('a10.finding',{check:'level_shift',column:'p'})]);
 set('A20','COMPLETED',[claim('a20.psi',{column:'p',shifted:true}),claim('a20.psi',{column:'t',shifted:false})]);
 set('A11','NEEDS_EVIDENCE',[claim('a11.volume',{changed:true})],'NO_BASELINE');
 set('A23','COMPLETED',[claim('a23.suggested',{mechanisms:['unit_change'],explains:['obs-1']})]);
 set('A24','COMPLETED',[claim('a24.summary',{}),claim('a24.hypothesis',{mechanism:'unit_change',column:'p',status:'supported'}),claim('a24.hypothesis',{mechanism:'noise_increase',column:'p',status:'refuted'}),claim('a24.hypothesis',{mechanism:'genuine_change',column:'p',status:'open'})]);
 set('A25','COMPLETED');set('A28','COMPLETED');
 const record={status:'completed',case_id:'case-1',intake:{signals:[{id:'sig-1',check:'distribution_shift',column:'p'}]},agents,
  judge:{verdicts:[{agent:'A10',claim:0,verdict:'accepted'},{agent:'A10',claim:1,verdict:'accepted'},{agent:'A20',claim:0,verdict:'accepted'},{agent:'A20',claim:null,verdict:'rejected'},{agent:'A23',claim:0,verdict:'advisory',reason:'model_suggestion'}]},
  approvals:[{items:[{agent:'A29'},{agent:'A30'}]}]};
 let story=F.flowStory({record,decisions:{'0':{decision:'approved'}},input:{name:'simulated-plant INC-0004 pressure_kpa'}});
 assert.deepEqual(story.map(x=>x.key),['flow.story.signal.incident','flow.story.specialists.gaps','flow.story.found','flow.story.model.advisory','flow.story.candidates.supported','flow.story.approval.pending']);
 assert.equal(story[0].params.incident,'INC-0004');assert.deepEqual(story[0].params.signals,[{check:'distribution_shift',column:'p'}]);
 assert.deepEqual([story[1].params.n,story[1].params.accepted,story[1].params.claims,story[1].params.needs],[3,3,6,['A11']]);
 assert.deepEqual(story[2].params.found,[{check:'outlier',column:'p'},{check:'level_shift',column:'p'},{check:'volume_change',column:null},{check:'distribution_shift',column:'p'}]);
 assert.deepEqual(story[2].agents,['A10','A11','A20']);
 assert.deepEqual(story[3].params.mechanisms,['unit_change']);
 assert.deepEqual(story[4].params,{survivors:[{mechanism:'unit_change',column:'p'}],refuted:1,open:1});
 assert.deepEqual(story[5].params,{pending:1,n:2});
 for(const item of story)assert.ok(item.agents.length&&item.agents.every(id=>F.FLOW_IDS.includes(id)),`${item.key} links to agents`);
 // Variants: a file input, a rejected model suggestion, only open or all refuted candidates, decided approvals.
 record.judge.verdicts[4]={agent:'A23',claim:0,verdict:'rejected',reason:'unknown_observation'};
 set('A24','COMPLETED',[claim('a24.hypothesis',{mechanism:'unit_change',column:'p',status:'open'})]);
 story=F.flowStory({record:{...record,agents},decisions:{'0':{decision:'approved'},'1':{decision:'rejected'}},input:{name:'orders.csv'}});
 assert.deepEqual(story.map(x=>x.key),['flow.story.signal.file','flow.story.specialists.gaps','flow.story.found','flow.story.model.rejected','flow.story.candidates.open','flow.story.approval.decided']);
 assert.equal(story[3].params.reason,'unknown_observation');
 set('A24','COMPLETED',[claim('a24.hypothesis',{mechanism:'unit_change',column:'p',status:'refuted'})]);
 set('A23','NEEDS_EVIDENCE',[],'MODEL_UNAVAILABLE');set('A11','SKIPPED');set('A10','COMPLETED',[claim('a10.profile',{})]);set('A20','COMPLETED',[]);
 story=F.flowStory({record:{...record,agents,intake:{signals:[]},approvals:[]},decisions:{},input:{}});
 assert.deepEqual(story.map(x=>x.key),['flow.story.signal.file.none','flow.story.specialists','flow.story.found.none','flow.story.model.unavailable','flow.story.candidates.refuted','flow.story.approval.none']);
 assert.equal(story[0].params.name,'case-1');assert.deepEqual(story[3].params.agents,['A23']);
 set('A22','COMPLETED',[claim('a22.relevance',{citations:['c']})]);
 story=F.flowStory({record:{...record,agents,judge:{verdicts:[{agent:'A22',claim:0,verdict:'advisory'}]}},input:{name:'INC-0001'}});
 assert.equal(story[3].key,'flow.story.model.other');assert.deepEqual(story[3].params,{n:1,agents:['A22'],advisory:1,rejected:0});
 assert.equal(story[0].key,'flow.story.signal.incident');
 for(const id of F.FLOW_IDS)set(id,'SKIPPED');
 story=F.flowStory({record:{...record,agents,status:'input_rejected',intake:null}});
 assert.deepEqual(story.map(x=>x.key),['flow.story.rejected','flow.story.specialists.none','flow.story.model.none','flow.story.candidates.none','flow.story.approval.pending']);
 assert.deepEqual(F.flowStory({record:null}),[]);assert.deepEqual(F.flowStory(null),[]);
 // Every story sentence exists in both languages with its placeholders, and none uses causal wording.
 const storyKeys=Object.keys(STRINGS).filter(k=>k.startsWith('flow.story.'));
 assert.ok(storyKeys.length>=25);
 for(const k of storyKeys){const [en,tr]=STRINGS[k];
  assert.ok(!/\bcaus|root.cause|\bbecause of\b|\bdue to\b/i.test(en),`${k}: causal wording`);assert.ok(!/neden|kök|yüzünden|sebep/i.test(tr),`${k} (TR): causal wording`);}
 for(const k of ['flow.story.signal.incident','flow.story.specialists.gaps','flow.story.found','flow.story.model.advisory','flow.story.model.rejected','flow.story.model.other','flow.story.model.unavailable','flow.story.candidates.supported','flow.story.candidates.open','flow.story.candidates.refuted','flow.story.approval.pending','flow.story.approval.decided','flow.story.signal.file','flow.story.signal.file.none','flow.story.signal.incident.none','flow.story.specialists','flow.story.found.none','flow.story.model.none','flow.story.candidates.none','flow.story.approval.none','flow.story.rejected','flow.story.specialists.none'])assert.ok(STRINGS[k],k);
 // The replay is labelled as a replay of recorded events in both languages.
 assert.ok(/Replay of recorded events/.test(STRINGS['flow.badge.replay'][0])&&/Kayıtlı olayların yeniden oynatımı/.test(STRINGS['flow.badge.replay'][1]));
 assert.ok(/Nothing is run again/.test(STRINGS['flow.replay.x'][0]));
}
console.log(`agent flow assertions passed: ${events.length} events of all ${F.FLOW_TYPES.length} types, ordering, replay, SSE framing, sentences and layout.`);
