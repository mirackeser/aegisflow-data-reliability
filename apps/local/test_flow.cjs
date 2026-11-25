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
 const p=F.flowEdgePath(L.pos.A10,L.pos.A22);assert.match(p.d,/^M[\d.]+ [\d.]+ C/);assert.equal(p.mid.length,2);
}
assert.equal(F.flowLayer('A07'),'specialists');assert.equal(F.flowLayer('A99'),null);
console.log(`agent flow assertions passed: ${events.length} events of all ${F.FLOW_TYPES.length} types, ordering, replay, SSE framing, sentences and layout.`);
