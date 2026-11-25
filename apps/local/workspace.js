'use strict';
// Investigation workspace and source workflow.
let selectedGroupId=null,showAllRecords=false,sourceMode='file',selectedFile=null,discovery=null,mappingOn={},awaiting=false,folder=null,folderSource=null,folderTables=null,folderTable=null,cmpSource=null,cmpTables=null,cmpTable=null,cmpResult=null;
const RECORD_PAGE=25;

// ---------- starting work ----------
function requireSession(){
 if(connected)return true;
 setNotice(t('next.connect'),true);$('access').hidden=false;$('session-toggle').setAttribute('aria-expanded','true');$('token').focus();return false;
}
async function begin(path,body,headers){
 if(!requireSession())return;
 try{await request(path,'POST',body,headers);awaiting=true;setNotice(t('notice.running'));await refresh();}
 catch(error){setNotice(error.message,true);}
}
const JSON_HEADERS={'Content-Type':'application/json'};
const folderChoice=()=>JSON.stringify({source:folderSource.id,table:folderTable||undefined,mapping:Object.keys(mappingOn).length?mappingOn:undefined});
const folderReady=()=>!!folderSource&&(folderSource.kind==='csv'||!!folderTable);
async function loadFolder(){
 if(!connected){folder=null;return;}
 try{folder=await request('/api/sources');}catch(error){folder=null;setNotice(error.message,true);}
 render();
}
async function chooseFolderSource(id){
 folderSource=(folder?.sources||[]).find(x=>x.id===id)||null;folderTables=null;folderTable=null;discovery=null;mappingOn={};cmpResult=null;
 if(folderSource?.kind==='sqlite'){
  try{folderTables=(await request('/api/source/tables','POST',JSON.stringify({source:id}),JSON_HEADERS)).tables;setNotice('');}
  catch(error){folderSource=null;setNotice(error.message,true);}
 }
 render();
}
async function discoverFolder(){
 if(!folderReady()||!requireSession())return;
 try{discovery=await request('/api/source/discover','POST',JSON.stringify({source:folderSource.id,table:folderTable||undefined}),JSON_HEADERS);mappingOn={};setNotice('');}
 catch(error){discovery=null;setNotice(error.message,true);}
 render();
}
async function chooseCompare(id){
 cmpSource=(folder?.sources||[]).find(x=>x.id===id)||null;cmpTables=null;cmpTable=null;cmpResult=null;
 if(cmpSource?.kind==='sqlite'){
  try{cmpTables=(await request('/api/source/tables','POST',JSON.stringify({source:id}),JSON_HEADERS)).tables;setNotice('');}
  catch(error){cmpSource=null;setNotice(error.message,true);}
 }
 render();
}
const cmpReady=()=>folderReady()&&!!cmpSource&&(cmpSource.kind==='csv'||!!cmpTable);
async function runCompare(){
 if(!cmpReady()||!requireSession())return;
 const side=(source,table)=>({source:source.id,table:table||undefined});
 try{cmpResult=await request('/api/source/compare','POST',JSON.stringify({first:side(folderSource,folderTable),second:side(cmpSource,cmpTable)}),JSON_HEADERS);setNotice('');}
 catch(error){cmpResult=null;setNotice(error.message,true);}
 render();
}
function joinPanel(c){
 if(!c)return null;
 const sideName=k=>t('join.side.'+k),rel=c.relationship;
 return h('div',{class:'stack join-panel'},h('h3',{text:t('join.title')}),h('p',{class:'hint',text:t('join.intro')}),
  h('p',{class:c.fan_out?'hint bad':'hint',text:c.fan_out?t('join.fanout',{extra:N(c.extra_rows_from_join),rows:N(c.join_rows),shared:N(c.shared_keys)}):t('join.safe')}),
  h('p',{text:t('join.rel')+': '+Object.keys(rel).map(k=>`${t('join.rel.'+k)}: ${N(rel[k])}`).join(' · ')}),
  h('p',{class:'hint',text:t('join.amount')}),
  h('ul',{class:'dup-list'},['first','second'].map(k=>{const a=c.amount_inflation[k];return h('li',{text:t('join.inflation',{side:sideName(k),before:a.before,after:a.after_join,inflation:a.inflation})});})),
  h('ul',{class:'dup-list'},['first','second'].map(k=>{const p=c[k];return h('li',{text:t('join.keys',{side:sideName(k),rows:N(p.rows),distinct:N(p.distinct_keys),blank:N(p.blank_keys),max:N(p.max_multiplicity)})});})));
}
function comparePanel(){
 const sources=folder?.sources||[];
 const pick=h('select',{id:'cmp-source',onchange:e=>chooseCompare(e.target.value)},h('option',{value:'',text:t('folder.source.choose')}),sources.map(x=>h('option',{value:x.id,selected:cmpSource?.id===x.id,text:`${x.id} · ${t('folder.kind.'+x.kind)}`})));
 const tablePick=cmpTables?h('select',{id:'cmp-table',onchange:e=>{cmpTable=e.target.value||null;cmpResult=null;render();}},h('option',{value:'',text:t('folder.table.choose')}),cmpTables.map(x=>h('option',{value:x.name,selected:cmpTable===x.name,text:t('folder.table.opt',{name:x.name,rows:N(x.rows)})}))):null;
 const r=cmpResult,tile=(key,value,tone='')=>h('div',{class:'kpi '+tone},h('span',{text:t('cmp.k.'+key)}),h('strong',{text:N(value)}),h('small',{text:t('cmp.k.'+key+'.x')}));
 const result=!r?null:h('div',{class:'stack'},
  h('div',{class:'kpi-grid'},tile('identical',r.identical,'ok'),tile('differing',r.differing,r.differing?'bad':''),tile('first',r.only_in_first,r.only_in_first?'bad':''),tile('second',r.only_in_second,r.only_in_second?'bad':'')),
  h('p',{class:'hint',text:t('cmp.total',{a:N(r.first.rows),b:N(r.second.rows)})}),
  r.complete?null:h('p',{class:'hint bad',text:t('cmp.incomplete')}),
  r.first.ambiguous_rows||r.second.ambiguous_rows?h('p',{class:'hint',text:t('cmp.ambiguous',{a:N(r.first.ambiguous_rows),b:N(r.second.ambiguous_rows)})}):null,
  r.not_compared.length?h('p',{class:'hint',text:t('cmp.notcompared',{cols:r.not_compared.map(c=>t('cmp.col.'+c)).join(', ')})}):null,
  r.differing?h('div',{},h('h3',{text:t('cmp.columns')}),h('p',{text:r.compared_columns.map(c=>`${t('cmp.col.'+c)}: ${N(r.differing_by_column[c])}`).join(' · ')}),
   h('h3',{text:t('cmp.samples')}),h('div',{class:'table-wrap'},h('table',{class:'data-table'},h('thead',{},h('tr',{},h('th',{scope:'col',text:t('cmp.sample.id')}),h('th',{scope:'col',text:t('cmp.sample.first')}),h('th',{scope:'col',text:t('cmp.sample.second')}))),
    h('tbody',{},r.samples.differing.map(x=>h('tr',{},h('th',{scope:'row',text:x.id}),h('td',{text:x.columns.map(c=>`${t('cmp.col.'+c)}: ${x.first[c]||'—'}`).join(' · ')}),h('td',{text:x.columns.map(c=>`${t('cmp.col.'+c)}: ${x.second[c]||'—'}`).join(' · ')}))))))):null,
  r.only_in_first?h('p',{},h('strong',{text:t('cmp.only.first')+': '}),h('span',{text:r.samples.only_in_first.join(', ')})):null,
  r.only_in_second?h('p',{},h('strong',{text:t('cmp.only.second')+': '}),h('span',{text:r.samples.only_in_second.join(', ')})):null,
  joinPanel(r.cardinality));
 return h('section',{class:'panel compare-panel'},h('div',{class:'panel-heading'},h('h2',{text:t('cmp.title')}),chip('A21','info'),chip('A18','info')),h('p',{text:t('cmp.intro')}),
  h('div',{class:'stack'},h('label',{for:'cmp-source',text:t('cmp.pick')}),pick,tablePick?h('label',{for:'cmp-table',text:t('folder.table')}):null,tablePick),
  h('p',{class:'hint',text:t('cmp.rules')}),h('div',{class:'button-row'},h('button',{type:'button',class:'primary',disabled:!cmpReady(),onclick:runCompare},t('cmp.run'))),result);
}
const startFolder=()=>folderReady()&&begin('/api/source/inspect',folderChoice(),JSON_HEADERS);
const startSample=fault=>begin(`/api/sample/${fault}`);
const startExample=scenario=>begin(scenario==='suite'?'/api/run':`/api/run/${scenario}`);
// The deterministic inspection runs as before, and the same bytes (with the same confirmed mapping, the selected
// baseline and "as of") start a 36-agent investigation whose live flow opens next.
const confirmedMapping=()=>Object.fromEntries(Object.entries(mappingOn).filter(([,on])=>on).map(([source,on])=>[source,on]));
function agentBaseline(){
 const name=(blList?.baselines||[]).some(b=>b.name===blChoice)?blChoice:'';
 return {baseline:name||undefined,asOf:name&&blAsOf?blAsOfForRequest(blEntry(name)):undefined};
}
async function startFile(){
 if(!selectedFile||!requireSession())return;
 const file=selectedFile,headers={'Content-Type':'text/csv','X-Source-Name':file.name.replace(/[^\x20-\x7e]/g,'_').slice(0,80)};
 const mapping=confirmedMapping();
 if(Object.keys(mapping).length)headers['X-Column-Mapping']=JSON.stringify(mapping);
 let note=t('flow.inspect.started');
 try{await request('/api/inspect','POST',await file.arrayBuffer(),headers);refresh();}
 catch(error){note=t('flow.inspect.failed',{reason:error.message});}
 await investigateWithAgents(file,{mapping,...agentBaseline(),note});
}
async function discover(){
 if(!selectedFile||!requireSession())return;
 try{
  discovery=await request('/api/discover','POST',await selectedFile.arrayBuffer(),{'Content-Type':'text/csv'});
  mappingOn={};setNotice('');
 }catch(error){discovery=null;setNotice(error.message,true);}
 render();
}
async function decide(run,action,decision){
 try{await request('/api/review','POST',JSON.stringify({run_id:run.run_id,action_id:action.id,decision}),{'Content-Type':'application/json'});await refresh();}
 catch(error){setNotice(error.message,true);}
}

// ---------- investigation workspace ----------
function explanation(group,a){
 const out=[];
 if(group.check==='unique'){
  const identical=a.duplicate_groups.filter(g=>g.pattern==='IDENTICAL_REPEAT').length,conflicting=a.duplicate_groups.length-identical;
  if(identical)out.push(h('p',{text:t('explain.dup.identical',{n:identical})}));
  if(conflicting)out.push(h('p',{text:t('explain.dup.conflict',{n:conflicting})}));
  out.push(h('ul',{class:'dup-list'},a.duplicate_groups.slice(0,5).map(g=>h('li',{},h('code',{text:g.order_id_masked}),' ',t('explain.dup.records',{records:g.records.join(', ')}),' ',
   chip(t('pattern.'+g.pattern),g.pattern==='IDENTICAL_REPEAT'?'info':'warn'),g.differing_columns.length?h('small',{text:' '+t('explain.dup.differs',{columns:g.differing_columns.join(', ')})}):null))));
 }else if(group.kind==='schema'&&group.check==='missing_column'){
  const action=a.actions.find(x=>x.code==='map_column'&&x.column===group.column);
  out.push(h('p',{text:action?t('explain.schema.candidate',{column:group.column,candidate:action.candidate}):t('explain.schema.none',{column:group.column})}));
 }else if(group.check==='not_null'&&group.column==='order_total')out.push(h('p',{text:t('explain.null.amount',{n:N(group.count)})}));
 else if(group.check==='amount_format')out.push(h('p',{text:t('explain.format')}));
 else out.push(h('p',{text:t('explain.none')}));
 out.push(h('p',{class:'hint',text:t('explain.notproof')}));
 return out;
}
function recordsTable(a,group){
 const records=recordsFor(a,group);
 if(!records.length)return h('p',{class:'panel-note',text:t('records.none')});
 const shown=showAllRecords?records:records.slice(0,RECORD_PAGE);
 const wrap=h('div',{},h('div',{class:'table-wrap'},h('table',{class:'data-table compact'},
  h('caption',{class:'sr-only',text:t('records.caption')}),
  h('thead',{},h('tr',{},...['records.col.n','records.col.id','records.col.issues','records.col.amount'].map(k=>h('th',{scope:'col',text:t(k)})))),
  h('tbody',{},shown.map(r=>h('tr',{},h('th',{scope:'row',text:'#'+r.record}),h('td',{},h('code',{text:r.order_id_masked||'—'})),
   h('td',{},r.issues.map(i=>{const [check,column]=i.split(':');return chip(`${t('check.'+check)} · ${column}`,i===group.id?'warn':'muted');})),
   h('td',{},chip(t('amount.'+r.amount_state),r.amount_state==='valid'?'ok':r.amount_state==='not_available'?'muted':'bad'))))))));
 if(records.length>RECORD_PAGE)wrap.append(h('button',{type:'button',class:'secondary',onclick:()=>{showAllRecords=!showAllRecords;render();}},showAllRecords?t('records.less'):t('records.more',{n:records.length-RECORD_PAGE})));
 if(a.affected_records_truncated)wrap.append(h('p',{class:'panel-note',text:t('records.truncated',{n:200})}));
 return wrap;
}
function actionCard(run,action,decision){
 const params={n:N(action.count),column:action.column||'',candidate:action.candidate||''};
 const decided=decision?.decision;
 return h('article',{class:'action'+(decided?' decided':'')},
  h('div',{class:'action-head'},h('strong',{text:t(`action.${action.code}.t`,params)}),decided?chip(t('decision.'+decided),decided==='accepted'?'ok':'muted'):chip(t('decision.proposed'),'info')),
  h('p',{text:t(`action.${action.code}.x`,params)}),
  action.code==='map_column'||action.code==='reinspect'?link('/sources',t('action.open.sources')):null,
  h('div',{class:'action-meta'},chip(t('action.requires'),'muted'),chip(t('action.noapply'),'muted')),
  h('div',{class:'decision-row',role:'group','aria-label':t(`action.${action.code}.t`,params)},
   ...['accepted','deferred','dismissed'].map(d=>h('button',{type:'button',class:'secondary',
    'aria-pressed':String(decided===d),onclick:()=>decide(run,action,d)},t('decide.'+d)))));
}
const tokenLabel=token=>{const [, check, column]=token.split(':');return `${t('check.'+check)} · ${column}`;};
function similarPanel(run,a){
 const matches=state?.similar?.matches?.[run.run_id]||[];
 const clean=a.status!=='FAIL'&&!a.heatmap.some(x=>x.records)&&!a.schema_issues.length;
 const list=!matches.length?h('p',{class:'panel-note',text:clean?t('sim.clean'):t('sim.none')}):h('ul',{class:'similar-list'},matches.map(m=>h('li',{},
  h('div',{class:'similar-head'},h('strong',{text:`${m.source} · ${when(m.at)}`}),chip(t('sim.score',{p:Math.round(m.score*100)}),m.score===1?'warn':'info')),
  h('small',{text:t('sim.affected',{n:N(m.affected_records),rows:N(m.row_count)})}),
  h('p',{},h('strong',{text:t('sim.shared')+': '}),h('span',{text:m.shared.map(tokenLabel).join(', ')})),
  m.only_here.length?h('p',{class:'hint'},h('strong',{text:t('sim.here')+': '}),h('span',{text:m.only_here.map(tokenLabel).join(', ')})):null,
  m.only_there.length?h('p',{class:'hint'},h('strong',{text:t('sim.there')+': '}),h('span',{text:m.only_there.map(tokenLabel).join(', ')})):null,
  h('button',{type:'button',class:'secondary',onclick:()=>{viewId=m.run_id===state.run_id?null:m.run_id;navigate('/investigations');}},t('sim.open')))));
 return h('section',{class:'panel similar-panel'},h('div',{class:'panel-heading'},h('h2',{text:t('sim.title')}),chip('A22','info')),list,h('p',{class:'panel-note',text:t('sim.note')}));
}
function renderWorkspace(){
 const run=currentRun(),root=$('screen-investigations');
 if(!run?.result){root.replaceChildren(h('section',{class:'panel'},empty('empty.ws.t','empty.ws.x',link('/sources',t('cta.start'),'primary route'))));return;}
 const c=caseOf(run),a=c?.analysis;
 if(!a){renderExampleDetail(run,root);return;}
 const groups=workspaceGroups(a);
 if(!groups.some(g=>g.id===selectedGroupId)){selectedGroupId=groups[0]?.id||null;showAllRecords=false;}
 const group=groups.find(g=>g.id===selectedGroupId),reviews=reviewsOf(run),progress=progressOf(run),failed=a.status==='FAIL';
 const stat=(label,value,tone='')=>h('div',{class:'stat '+tone},h('span',{text:t(label)}),h('strong',{text:value}));
 const banner=h('section',{class:'verdict '+(failed?'bad':'ok')},
  h('div',{},h('p',{class:'eyebrow',text:`${t(originKey(run))} · ${runLabel(run)} · ${when(run.finished_at)}`}),
   h('h2',{text:failed?t('ws.fail',{n:N(a.impact.affected_records),rows:N(a.row_count)}):t('ws.pass',{rows:N(a.row_count)})}),
   h('p',{text:failed?t('ws.fail.x'):t('ws.pass.x')})),
  h('div',{class:'stats'},stat('stat.affected',N(a.impact.affected_records),failed?'bad':''),stat('stat.customers',N(a.impact.affected_customers)),
   stat('stat.double',A(a.impact.double_count_exposure),a.impact.repeat_records?'warn':''),stat('stat.noamount',N(a.impact.records_without_amount),a.impact.records_without_amount?'warn':'')));
 const findings=h('section',{class:'panel findings-panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ws.findings')}),chip(String(groups.length),'muted')),
  groups.length?h('ul',{class:'finding-list'},groups.map(g=>h('li',{},h('button',{type:'button',class:'finding-item'+(g.id===selectedGroupId?' selected':''),'aria-pressed':String(g.id===selectedGroupId),
   onclick:()=>{selectedGroupId=g.id;showAllRecords=false;render();}},
   chip(t('prio.'+g.priority),g.priority===1?'bad':g.priority===2?'warn':'muted'),h('strong',{text:t('group.title.'+g.check,{column:g.column,n:N(g.count)})}),
   h('small',{text:g.kind==='schema'?t('group.schema'):t('group.records',{n:N(g.count)})}))))):h('p',{class:'panel-note',text:t('ws.nofindings')}),
  h('p',{class:'panel-note',text:t('ws.prio.note')}));
 const reference=group&&run.result.finding_references?.[group.check]?.[0];
 const detail=h('section',{class:'panel detail-panel'},
  group?[h('div',{class:'panel-heading'},h('h2',{text:t('group.title.'+group.check,{column:group.column,n:N(group.count)})}),chip(t('prio.'+group.priority),group.priority===1?'bad':group.priority===2?'warn':'muted')),
   h('p',{class:'observation',text:t('group.what.'+group.check,{column:group.column,n:N(group.count)})}),
   h('h3',{text:t('ws.records')}),group.kind==='records'?recordsTable(a,group):h('p',{class:'panel-note',text:t('ws.schemalevel')}),
   h('h3',{text:t('ws.explain')}),...explanation(group,a),
   h('h3',{text:t('ws.evidence')}),
   h('dl',{class:'evidence-dl'},h('dt',{text:t('ev.sha')}),h('dd',{},h('code',{text:c.source_report.source_sha256})),h('dt',{text:t('ev.run')}),h('dd',{},h('code',{text:c.retained_run_id})),
    h('dt',{text:t('ev.verify')}),h('dd',{text:run.result.judge?.decision==='ACCEPT'?t('ev.accepted'):t('ev.notaccepted')}),
    run.result.input?.mapping?[h('dt',{text:t('ev.mapping')}),h('dd',{text:Object.entries(run.result.input.mapping).map(([s,d])=>`${s} → ${d}`).join(', ')})]:null),
   reference?h('blockquote',{class:'reference-quote'},h('small',{text:`${t('ref.'+reference.source)} · ${reference.source} ${reference.revision}`}),h('p',{text:reference.text}),h('code',{text:reference.citation_sha256})):null]
  :[h('p',{class:'panel-note',text:t('ws.nofindings')}),h('p',{text:t('ws.pass.x')})]);
 const chain=['source_orders','staging_orders','customer_sales','sales_dashboard'];
 const impact=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ws.downstream')}),chip(t('badge.declared'),'info')),
  h('ol',{class:'chain'},chain.map((d,i)=>h('li',{class:(i===0?'origin ':'')+(a.downstream.blocked_by_source&&i>0?'blocked':'')},h('strong',{text:t('ds.'+d)}),h('small',{text:i===0?(failed?t('ds.fail'):t('ds.ok')):(a.downstream.blocked_by_source?t('ds.blocked'):t('ds.clear'))})))),
  h('p',{class:'panel-note',text:t('ws.downstream.note')}));
 const exposure=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ws.exposure')}),chip(t('badge.exact'),'info')),
  h('dl',{class:'money'},h('dt',{text:t('money.total')}),h('dd',{text:A(a.impact.valid_amount_total)}),h('dt',{text:t('money.affected')}),h('dd',{text:A(a.impact.valid_amount_in_affected_records)}),
   h('dt',{text:t('money.double')}),h('dd',{class:a.impact.repeat_records?'warn':'',text:A(a.impact.double_count_exposure)})),
  h('p',{class:'panel-note',text:t('ws.exposure.note')}));
 const actions=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ws.actions')}),chip(progress.total?t('ws.reviewed',{d:progress.decided,n:progress.total}):t('decision.none'),progress.total&&!progress.pending?'ok':'muted')),
  a.actions.length?a.actions.map(x=>actionCard(run,x,reviews[x.id])):h('p',{class:'panel-note',text:t('ws.noactions')}),h('p',{class:'panel-note',text:t('ws.actions.note')}));
 root.replaceChildren(banner,h('div',{class:'ws-layout'},findings,detail,h('div',{class:'ws-side'},impact,exposure,actions,similarPanel(run,a))));
}
function renderExampleDetail(run,root){
 const cases=run.result.cases||[],s=summarizeResult(run.result);
 root.replaceChildren(h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('ex.title')}),chip(t('origin.example'),'info')),h('p',{text:t('ex.text')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table'},h('thead',{},h('tr',{},...['ex.case','ex.assessment','ex.rows','ex.findings'].map(k=>h('th',{scope:'col',text:t(k)})))),
   h('tbody',{},cases.map(item=>h('tr',{},h('th',{scope:'row',text:tt('ex.case.'+item.case,item.case)}),h('td',{text:tt('assessment.'+item.assessment,item.assessment)}),h('td',{text:N(item.rows??0)}),h('td',{text:item.source_report?N(item.source_report.finding_count):'—'})))))),
  h('p',{class:'panel-note',text:t('ex.note',{n:s.reconciliation})})));
}

// ---------- sources ----------
const CONTRACT=[['order_id','contract.order_id'],['customer_id','contract.customer_id'],['order_total','contract.order_total']];
function sourceCard(mode,titleKey,textKey,tone,stateKey){
 return h('button',{type:'button',class:'source-card'+(sourceMode===mode?' selected':''),'aria-pressed':String(sourceMode===mode),onclick:()=>{sourceMode=mode;discovery=null;mappingOn={};if(mode==='folder')loadFolder();else render();}},
  h('strong',{text:t(titleKey)}),h('span',{text:t(textKey)}),chip(t(stateKey),tone));
}
function futureCard(titleKey,textKey){
 return h('div',{class:'source-card disabled','aria-disabled':'true'},h('strong',{text:t(titleKey)}),h('span',{text:t(textKey)}),chip(t('state.muted'),'muted'));
}
function discoveryPanel(){
 if(!discovery)return null;
 const d=discovery,tone={COMPATIBLE:'ok',MAPPING_NEEDED:'warn',EXTRA_COLUMNS:'warn',INCOMPATIBLE:'bad'}[d.status];
 const candidates=d.contract.filter(x=>x.status==='candidate');
 return h('div',{class:'discovery'},
  h('div',{class:'verdict compact '+tone},h('div',{},h('h3',{text:t('disc.'+d.status)}),h('p',{text:t('disc.'+d.status+'.x')})),
   h('div',{class:'stats'},h('div',{class:'stat'},h('span',{text:t('disc.rows')}),h('strong',{text:N(d.row_count)})),h('div',{class:'stat'},h('span',{text:t('disc.cols')}),h('strong',{text:N(d.columns.length)})))),
  h('h3',{text:t('disc.contract')}),
  h('ul',{class:'contract-list'},d.contract.map(item=>h('li',{class:item.status},
   h('span',{class:'mark','aria-hidden':'true',text:item.status==='matched'?'✓':item.status==='candidate'?'?':'✕'}),
   h('div',{},h('strong',{text:item.name}),
    item.status==='matched'?h('small',{text:t('disc.matched')}):item.status==='missing'?h('small',{text:t('disc.missing')}):
    h('label',{class:'map-choice'},h('input',{type:'checkbox',checked:!!mappingOn[item.candidate.column],onchange:e=>{mappingOn[item.candidate.column]=item.name;if(!e.target.checked)delete mappingOn[item.candidate.column];render();}}),
     ' ',t('disc.use',{column:item.candidate.column,target:item.name}),' ',chip(t('basis.'+item.candidate.basis),'info')))))),
  candidates.length?h('p',{class:'hint',text:t('disc.confirm')}):null,
  d.provenance?.sampled?h('p',{class:'hint bad',text:t('folder.sampled',{limit:N(d.row_count),total:N(d.provenance.total_rows)})}):null,
  h('h3',{text:t('disc.columns')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table compact'},h('thead',{},h('tr',{},...['disc.col.name','disc.col.type','disc.col.filled','disc.col.empty','disc.col.distinct','disc.col.role'].map(k=>h('th',{scope:'col',text:t(k)})))),
   h('tbody',{},d.columns.map(col=>h('tr',{},h('th',{scope:'row',text:col.name}),h('td',{text:t('type.'+col.inferred_type)}),h('td',{text:N(col.non_empty)}),h('td',{text:N(col.empty)}),h('td',{text:N(col.distinct)}),
    h('td',{},col.contract_role?chip(t('disc.role.contract'),'ok'):col.suggested_role?chip(t('disc.role.suggested',{target:col.suggested_role}),'warn'):chip(t('disc.role.extra'),'muted'))))))),
  schemaRegistryPanel(d));
}
function renderSources(){
 const root=$('screen-sources'),chosen=Object.keys(mappingOn).length;
 const cards=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:'1 · '+t('src.step1')})),
  h('div',{class:'source-cards',role:'group','aria-label':t('src.step1')},
   sourceCard('file','src.csv','src.csv.x','ok','state.ok'),sourceCard('sample','src.sample','src.sample.x','ok','state.ok'),sourceCard('folder','src.folder','src.folder.x','ok','state.ok'),sourceCard('example','src.pg','src.pg.x','info','state.info'),
   futureCard('src.company','src.company.x'),futureCard('src.warehouse','src.warehouse.x')));
 let config;
 if(sourceMode==='sample'){
  config=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:'2 · '+t('src.step2.sample')}),chip(t('origin.sample'),'info')),h('p',{text:t('sample.intro')}),
   h('div',{class:'sample-grid'},SAMPLES.map(f=>h('article',{class:'sample'},h('strong',{text:t('sample.'+f)}),h('p',{text:t('sample.'+f+'.x')}),h('button',{type:'button',class:'secondary',onclick:()=>startSample(f)},t('sample.run'))))));
 }else if(sourceMode==='folder'){
  const sources=folder?.sources||[],note=!connected?'folder.needsSession':!folder?null:!folder.configured?'folder.unconfigured':!sources.length?'folder.empty':null;
  const pick=h('select',{id:'folder-source',onchange:e=>chooseFolderSource(e.target.value)},h('option',{value:'',text:t('folder.source.choose')}),sources.map(x=>h('option',{value:x.id,selected:folderSource?.id===x.id,text:`${x.id} · ${t('folder.kind.'+x.kind)}`})));
  const tablePick=folderTables?h('select',{id:'folder-table',onchange:e=>{folderTable=e.target.value||null;discovery=null;mappingOn={};render();}},h('option',{value:'',text:t('folder.table.choose')}),folderTables.map(x=>h('option',{value:x.name,selected:folderTable===x.name,text:t('folder.table.opt',{name:x.name,rows:N(x.rows)})}))):null;
  const chosenCount=Object.keys(mappingOn).length;
  config=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:'2 · '+t('src.step2.folder')}),chip(t('origin.connected'),'ok')),h('p',{text:t('folder.intro')}),
   note?h('p',{class:'hint',text:t(note)}):null,
   sources.length?h('div',{class:'stack'},h('label',{for:'folder-source',text:t('folder.source')}),pick,tablePick?h('label',{for:'folder-table',text:t('folder.table')}):null,tablePick):null,
   h('p',{class:'hint',text:t('folder.limits')}),
   h('div',{class:'button-row'},h('button',{type:'button',class:'secondary',disabled:!folderReady(),onclick:discoverFolder},t('folder.validate')),
    h('button',{type:'button',class:'primary',disabled:!folderReady()||state?.status==='RUNNING',onclick:startFolder},chosenCount?t('file.inspect.mapped',{n:chosenCount}):t('folder.inspect'))),
   discoveryPanel(),h('p',{class:'panel-note',text:t('folder.privacy')}),folderReady()?comparePanel():null);
 }else if(sourceMode==='example'){
  const select=h('select',{id:'scenario'},EXAMPLES.map(s=>h('option',{value:s,text:t('ex.case.'+s)})));
  config=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:'2 · '+t('src.step2.example')}),chip(t('origin.example'),'info')),h('p',{text:t('example.intro')}),
   h('label',{for:'scenario',text:t('example.choose')}),select,h('p',{class:'hint',text:t('example.needs')}),h('button',{type:'button',class:'secondary',onclick:()=>startExample(select.value)},t('example.run')));
 }else{
  const input=h('input',{id:'csv-file',type:'file',accept:'.csv,text/csv',onchange:e=>{selectedFile=e.target.files[0]||null;discovery=null;mappingOn={};profileResult=null;render();}});
  config=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:'2 · '+t('src.step2.file')}),chip(t('origin.file'),'ok')),
   h('p',{text:t('file.intro')}),
   h('table',{class:'data-table compact contract-table'},h('caption',{class:'sr-only',text:t('disc.contract')}),h('thead',{},h('tr',{},h('th',{scope:'col',text:t('disc.col.name')}),h('th',{scope:'col',text:t('contract.rule')}))),
    h('tbody',{},CONTRACT.map(([name,key])=>h('tr',{},h('th',{scope:'row',text:name}),h('td',{text:t(key)}))))),
   h('p',{class:'hint',text:t('file.limits')}),
   h('div',{class:'file-row'},h('label',{for:'csv-file',class:'file-label',text:t('file.choose')}),input,
    h('button',{type:'button',class:'secondary',onclick:()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['order_id,customer_id,order_total\nORD-0001,CUS-001,125.50\nORD-0002,CUS-002,89.90\nORD-0003,CUS-001,240.00\n'],{type:'text/csv'}));a.download='aegisflow-order-template.csv';a.click();URL.revokeObjectURL(a.href);}},t('file.template'))),
   h('p',{class:'file-state',text:selectedFile?t('file.chosen',{name:selectedFile.name,kb:N(Math.max(1,Math.round(selectedFile.size/1024)))}):t('file.none')}),
   h('div',{class:'button-row'},h('button',{type:'button',class:'secondary',disabled:!selectedFile||selectedFile.size>1000000,onclick:discover},t('file.validate')),
    typeof profileButton==='function'?profileButton():null,
    h('button',{type:'button',class:'primary',disabled:!selectedFile||selectedFile.size>1000000||state?.status==='RUNNING',onclick:startFile},chosen?t('file.inspect.mapped',{n:chosen}):t('file.inspect'))),
   h('p',{class:'hint',text:t('file.agents.x')}),
   selectedFile&&selectedFile.size>1000000?h('p',{class:'hint bad',text:t('err.size')}):null,
   discoveryPanel(),typeof profilePanel==='function'?profilePanel():null,typeof baselinePanel==='function'?baselinePanel():null,h('p',{class:'panel-note',text:t('file.privacy')}));
 }
 const conn=[['conn.session',connected?'ok':'warn',connected?'conn.on':'conn.off','conn.session.x'],['src.csv','ok','state.ok','conn.csv.x'],['src.folder',folder?.configured?'ok':'muted',folder?.configured?'state.ok':'state.muted','conn.folder.x'],['src.pg','info','state.info','conn.pg.x'],['src.company','muted','state.muted','conn.company.x']];
 const side=h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('panel.connections')})),
  h('ul',{class:'ready-list'},conn.map(([name,tone,stateKey,text])=>h('li',{},h('div',{},h('strong',{text:t(name)}),h('small',{text:t(text)})),chip(t(stateKey),tone)))),
  h('p',{class:'panel-note',text:t('conn.note')}));
 root.replaceChildren(h('div',{class:'sources-layout'},h('div',{class:'stack'},cards,config),side));
}
