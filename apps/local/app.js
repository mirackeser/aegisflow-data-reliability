'use strict';
let token='',polling,state=null,view=null,selected=0;
const el=id=>document.getElementById(id);
const node=(tag,value,cls)=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;};
const names={suite:'Source quality suite',clean:'Healthy source',null_total:'Missing order totals',duplicate_order:'Duplicate orders',transformation:'Transformation reconciliation',upload:'Uploaded CSV'};
async function request(path,method='GET',body=undefined){
 const response=await fetch(path,{method,headers:{Authorization:'Bearer '+token,...(body!==undefined?{'Content-Type':'text/csv'}:{})},body,cache:'no-store'});
 if(!response.ok)throw new Error(response.status===409?'An investigation is already running.':'Workspace unavailable. Check your token and connection.');
 return response.json();
}
function details(item){
 el('detail-title').textContent=names[item.case]||item.case;
 const target=el('detail');target.replaceChildren();
 target.append(node('p',item.assessment.replaceAll('_',' ').toLowerCase(),'detail-summary'));
 const report=item.source_report;
 if(report){target.append(node('p',`${report.row_count} records inspected · ${report.finding_count} source findings`,'detail-summary'));
 for(const f of report.findings){const box=node('div','','finding');box.append(node('strong',f.check.replaceAll('_',' ')+' · '+f.column),node('p',f.message),node('p','Logical records: '+f.record_numbers.join(', ')));target.append(box);}
 target.append(node('p','Exact source evidence','eyebrow'),node('code',report.source_sha256));}
 for(const step of item.steps||[]){if(step.tool==='run_batch'){for(const check of step.report.reconciliation||[]){const box=node('div','','finding');box.append(node('strong',check.check.replaceAll('_',' ')),node('p',`Expected ${check.expected} · Observed ${check.actual} · ${check.passed?'Matched':'Mismatch'}`));target.append(box);}}}
 if(!report)target.append(node('p','This older run contains summary results only. Run a new investigation to capture finding details.','detail-summary'));
}
function render(){
 if(!state)return;const current=view===null?state:state.history.find(x=>x.run_id===view)||state;
 const cases=current.result?.cases||[];el('source-badge').textContent=current.result?.source==='local-upload'?'CSV':'PostgreSQL';
 el('status').textContent=current.status.replaceAll('_',' ');el('run-id').textContent=current.run_id?'Run '+current.run_id.slice(0,8):'No run selected';
 el('count').textContent=current.result?cases.length:'—';el('issues').textContent=current.result?cases.filter(c=>c.assessment!=='NO_FAILURE_OBSERVED').length:'—';el('denials').textContent=current.result?(current.result.write_denials??'Not applicable'):'—';
 el('notice').textContent=(view?'Saved run · ':'Current run · ')+current.status+(current.error?' · '+current.error:'')+(current.finished_at?' · Finished '+new Date(current.finished_at).toLocaleTimeString():'');
 el('run').disabled=state.status==='RUNNING';el('inspect').disabled=state.status==='RUNNING';el('download').disabled=!current.result;
 el('events').replaceChildren(...(current.events||[]).map(e=>{const li=node('li','');li.append(node('span',e.state,'state'),node('strong',e.agent),node('small',e.description));return li;}));
 const results=el('results');results.replaceChildren();results.className='case-list';
 cases.forEach((item,i)=>{const b=node('button','','case-button'+(selected===i?' selected':''));b.setAttribute('aria-pressed',String(selected===i));const label=node('span','');label.append(node('strong',names[item.case]||item.case),node('small',item.rows+' records · source_orders'));const good=item.assessment==='NO_FAILURE_OBSERVED';b.append(node('span',String(i+1).padStart(2,'0'),'number'),label,node('span',good?'Healthy':'Finding',good?'state ok':'state'));b.onclick=()=>{selected=i;render();};results.append(b);});
 if(cases.length){selected=Math.min(selected,cases.length-1);details(cases[selected]);}else{results.append(node('p','No source results yet.','empty'));el('detail').replaceChildren(node('p','Select a completed scenario to inspect its evidence.'));el('detail-title').textContent='Select a scenario';}
 el('references').replaceChildren(...(current.result?.references||[]).map(r=>{const d=node('div','','reference');d.append(node('strong',r.source+' / '+r.revision),node('p',r.text),node('code',r.citation_sha256));return d;}));
 el('history').replaceChildren(...(state.history||[]).map(run=>{const b=node('button',names[run.scenario]||run.scenario);b.append(node('small',run.status+' · '+(run.started_at?new Date(run.started_at).toLocaleString():run.run_id.slice(0,8))));b.onclick=()=>{view=run.run_id;selected=0;navigate('/investigations');render();};return b;}));
 const historyList=el('history-list');historyList.replaceChildren(...(state.history||[]).map(run=>{const b=node('button',names[run.scenario]||run.scenario);b.append(node('small',run.status+' · '+run.run_id));b.onclick=()=>{view=run.run_id;selected=0;navigate('/investigations');render();};return b;}));
 if(!state.history?.length)historyList.append(node('p','No saved investigations.','empty'));
 renderOverview(current);translatePage();
}
async function refresh(){try{const next=await request('/api/state');const changed=JSON.stringify(next)!==JSON.stringify(state);state=next;el('connection').textContent='Connected';if(changed)render();translatePage();}catch(e){el('notice').textContent=e.message;el('connection').textContent='Disconnected';el('run').disabled=true;clearInterval(polling);translatePage();}}
el('connect').onclick=async()=>{token=el('token').value;el('token').value='';clearInterval(polling);await refresh();if(state){el('access').open=false;polling=setInterval(()=>{if(!document.hidden)refresh();},1500);}};
el('current').onclick=()=>{view=null;selected=0;render();};
el('run').onclick=async()=>{el('run').disabled=true;view=null;selected=0;try{await request('/api/run'+(el('scenario').value==='suite'?'':'/'+el('scenario').value),'POST');await refresh();}catch(e){el('notice').textContent=e.message;}};

function navigate(path, push=true){
 const pages={'/overview':['overview','Overview'],'/investigations':['investigations','Investigation workspace'],'/activity':['activity','Execution flow'],'/knowledge':['knowledge','Knowledge sources'],'/history':['history','History']};
 if(path==='/')path='/overview';
 const entry=pages[path]||pages['/overview'];
 if(push)history.pushState({},'',path);
 document.body.dataset.page=entry[0];el('page-title').textContent=entry[1];el('breadcrumb-page').textContent=entry[1];
 document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.getAttribute('href')===path);if(a.getAttribute('href')===path)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 document.title=(language==='tr'?'AegisFlow · ':'AegisFlow · ')+translate(entry[1]);translatePage();window.scrollTo(0,0);
}
document.querySelectorAll('nav a,.brand,.action-link').forEach(a=>a.onclick=e=>{e.preventDefault();navigate(a.getAttribute('href'));});
window.addEventListener('popstate',()=>navigate(location.pathname,false));
document.querySelectorAll('.lang').forEach(b=>b.onclick=()=>{language=b.dataset.language;localStorage.setItem('aegis-language',language);navigate(location.pathname,false);if(state)render();else translatePage();});
el('inspect').onclick=async()=>{
 const file=el('csv-file').files[0];
 if(!file||file.size<1||file.size>1000000){el('notice').textContent=translate('Choose a CSV file up to 1 MB.');return;}
 el('inspect').disabled=true;view=null;selected=0;
 try{await request('/api/inspect','POST',await file.arrayBuffer());await refresh();}catch(e){el('notice').textContent=translate(e.message);el('inspect').disabled=false;}
};
el('download').onclick=()=>{const current=view===null?state:state.history.find(x=>x.run_id===view)||state;if(!current?.result)return;const data={run_id:current.run_id,status:current.status,scenario:current.scenario,result:current.result};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='aegisflow-report.json';a.click();URL.revokeObjectURL(url);};
navigate(location.pathname,false);

function renderOverview(current){
 const cases=current.result?.cases||[];
 document.querySelectorAll('[data-agent]').forEach(n=>{const event=(current.events||[]).filter(e=>e.agent.startsWith(n.dataset.agent)).at(-1);n.dataset.state=event?.state||'IDLE';});
 el('overview-note').textContent=cases.length?'Actual source checks · '+cases.reduce((n,c)=>n+c.rows,0)+' records inspected':'Connect and inspect a file to populate actual results.';
 const counts=cases.map(c=>({name:names[c.case]||c.case,count:c.source_report?.finding_count??0}));
 const max=Math.max(1,...counts.map(c=>c.count));el('finding-bars').replaceChildren(...counts.map(c=>{const row=node('div','','bar-row');const title=node('div','','bar-label');title.append(node('span',c.name),node('strong',String(c.count)));const track=node('div','','bar-track');const bar=node('div','','bar-fill');bar.style.width=(100*c.count/max)+'%';track.append(bar);row.append(title,track);return row;}));
 if(!counts.length)el('finding-bars').append(node('p','No source results yet.','muted'));
 el('outcome-chart').replaceChildren(...[current,...(state.history||[])].filter(r=>r.result).slice(0,6).map(r=>{const row=node('div','','outcome');const count=r.result.cases.filter(c=>c.assessment!=='NO_FAILURE_OBSERVED').length;row.append(node('span',names[r.scenario]||r.scenario),node('strong',String(count)+' / '+r.result.cases.length),node('small','Scenarios with findings'));return row;}));
}
