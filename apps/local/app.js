'use strict';
let token='',polling,state=null,view='none',selected=0,connected=false,pendingRun=false;
const el=id=>document.getElementById(id);
const t=value=>translate(value);
const sentence=(en,tr)=>language==='tr'?tr:en;
const node=(tag,value='',cls='')=>{const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;};
const names={suite:'Source quality suite',clean:'Healthy source',null_total:'Missing order totals',duplicate_order:'Duplicate orders',transformation:'Transformation reconciliation',upload:'Uploaded order file'};
const pages={
 '/overview':['overview','Data reliability overview','Find what is wrong in your order data, where it happened and which evidence supports it.'],
 '/investigations':['investigations','Inspect order data','Choose a source, run read-only checks and review the exact findings.'],
 '/sources':['sources','Data sources','See which sources are available and which connections are examples.'],
 '/activity':['activity','Inspection activity','Follow what actually ran and why a step was completed or skipped.'],
 '/history':['history','Investigation reports','Reopen saved findings and evidence without running another inspection.'],
 '/knowledge':['knowledge','Evidence references','Read the original reference text and its verified content hash.']
};
function currentRun(){return view==='none'?null:view===null?state:state?.history?.find(r=>r.run_id===view)||state;}
function origin(run){return run?.result?.source==='local-upload'||run?.scenario==='upload'?'Uploaded file':run?.run_id?'EXAMPLE DATA':'No data selected';}
function setNotice(message,error=false){el('notice').textContent=t(message);el('notice').classList.toggle('error',error);}
function empty(title,description,link=false){const box=node('div','','empty-state');box.append(node('strong',t(title)),node('span',t(description)));if(link){const a=node('a',t('Start an investigation →'));a.href='/investigations';a.onclick=e=>{e.preventDefault();navigate(a.pathname);};box.append(a);}return box;}
async function request(path,method='GET',body){
 const response=await fetch(path,{method,headers:{Authorization:'Bearer '+token,...(body!==undefined?{'Content-Type':'text/csv'}:{})},body,cache:'no-store'});
 if(!response.ok)throw new Error(response.status===409?'An investigation is already running.':response.status===413?'The file exceeds the 1 MB limit.':'Workspace unavailable. Check your token and connection.');
 return response.json();
}
function controls(){document.body.classList.toggle('connected-state',connected);const busy=state?.status==='RUNNING';el('run').disabled=!connected||busy;el('inspect').disabled=!connected||busy||!el('csv-file').files.length;el('download').disabled=!currentRun()?.result;el('download-json').disabled=!currentRun()?.result;el('connection').textContent=t(connected?'Connected':'Disconnected');el('connection').classList.toggle('connected',connected);el('session-toggle').textContent=t(connected?'Session connected':'Open local session');}
function chooseMode(mode){el('file-controls').hidden=mode!=='file';el('example-controls').hidden=mode!=='example';for(const [id,name] of [['choose-file','file'],['choose-example','example']]){el(id).classList.toggle('selected',mode===name);el(id).setAttribute('aria-pressed',String(mode===name));}translatePage();}
function renderOverview(run){
 const result=run?.result,summary=summarizeResult(result),cases=result?.cases||[];
 el('metric-rows').textContent=result?String(summary.rows):'—';
 el('metric-findings').textContent=result?(summary.detailsAvailable?String(summary.findings+summary.reconciliation):'—'):'—';
 el('metric-source').textContent=t(origin(run));
 el('source-context').textContent=t(run?.run_id?'Selected saved investigation':'No automatic upload or demo run');
 el('metric-status').textContent=t(run?.status||'Not started');
 el('last-run').textContent=run?.finished_at?new Date(run.finished_at).toLocaleString(language==='tr'?'tr-TR':'en-GB'):t('Start one to see actual results');
 el('map-source').textContent=t(result?.source==='local-upload'?'Order CSV':result?'PostgreSQL example':'Order data');
 el('pipeline-status').textContent=t(result?'Checks completed':run?.status==='RUNNING'?'RUNNING':'Waiting for data');
 document.querySelectorAll('[data-stage]').forEach(n=>{
  const stage=n.dataset.stage;
  const executed=stage==='verification'?!!result:cases.some(c=>(c.steps||[]).some(s=>s.tool===stage));
  n.dataset.status=executed?'complete':result?'skipped':'waiting';
 });
 el('pipeline-explanation').textContent=t(result&&cases.every(c=>c.assessment==='SOURCE_QUALITY_FAILURE')?'Source violations were found. Batch execution was skipped to avoid processing invalid input.':'The diagram shows the actual inspection path. A source quality failure stops batch execution.');
 const quality=el('quality-chart');quality.replaceChildren();
 if(!result||!summary.detailsAvailable){quality.append(empty('No measured quality data yet','Run an inspection to see counts for empty values, duplicate records, amount format and schema issues.',true));}
 else{
  const values=[['Empty-value violations',summary.emptyViolations],['Duplicate violations',summary.duplicateViolations],['Amount-format violations',summary.formatViolations],['Schema violations',summary.schema]];
  const max=Math.max(1,...values.map(v=>v[1]));
  values.forEach(([label,value])=>{const c=node('div','','quality-column'),track=node('div','','column-track'),fill=node('div','','column-fill');fill.style.height=(value/max*100)+'%';track.append(fill);c.append(node('strong',String(value)),track,node('span',t(label)));quality.append(c);});
 }
 el('quality-note').textContent=t(summary.truncated?'Finding details were truncated. These category counts are lower bounds, not complete rates.':'Counts come from diagnostic evidence. No quality percentage is invented.');
 const attention=el('attention');attention.replaceChildren();
 if(!result)attention.append(empty('What will this tell me?','You will see the failed check, the affected record numbers and a linked evidence report.',true));
 else if(!summary.detailsAvailable){attention.append(empty('Details were not retained','Open a newer report or run an inspection to see evidence-derived counts.',true));}
 else{
  const problems=summary.findings+summary.reconciliation;
  attention.append(node('h3',!problems&&summary.detailsAvailable?t('No violations observed in the performed checks'):sentence(`${problems} check violations need review`,`${problems} kontrol ihlali incelenmeli`),'attention-title'));
  attention.append(node('p',summary.schema?t('The input schema differs from the order contract. Check missing or unexpected columns first.'):summary.affected?sentence(`${summary.affected} distinct records are referenced in the available findings.`, `Mevcut bulgularda ${summary.affected} farklı kayda işaret ediliyor.`):summary.reconciliation?t('The transformation output does not match the source totals. Inspect expected and observed values.'):t('This describes performed checks, not a guarantee about every possible data issue.')));
  const a=node('a',t('Open evidence and review suggestions →'),'text-link');a.href='/investigations';a.onclick=e=>{e.preventDefault();navigate(a.pathname);};attention.append(a);
 }
 renderRunChart();
}
function renderRunChart(){
 const target=el('run-chart');target.replaceChildren();
 const records=[...(state?.history||[]).slice().reverse(),...(state?.run_id?[state]:[])].filter(r=>r.result).slice(-8);
 if(records.length<2){target.append(empty('A trend needs at least two saved inspections','No throughput or trend data is simulated. Run inspections to build this history.'));return;}
 const values=records.map(r=>{const s=summarizeResult(r.result);return s.detailsAvailable?s.findings+s.reconciliation:null;});
 if(values.includes(null)){target.append(empty('Older reports have summary-only data','New inspections retain the diagnostic details needed for this chart.'));return;}
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 400 150');svg.setAttribute('role','img');svg.setAttribute('aria-label',t('Finding counts in saved investigation order')+': '+values.join(', '));
 const max=Math.max(1,...values),points=values.map((v,i)=>[20+i*360/(values.length-1),125-v/max*95]);
 for(const y of [30,78,125]){const l=document.createElementNS(ns,'line');for(const [k,v]of Object.entries({x1:20,x2:380,y1:y,y2:y,stroke:'#32485c'}))l.setAttribute(k,v);svg.append(l);}
 const path=document.createElementNS(ns,'polyline');path.setAttribute('points',points.map(p=>p.join(',')).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#52e4d4');path.setAttribute('stroke-width','3');svg.append(path);
 points.forEach(([x,y],i)=>{const c=document.createElementNS(ns,'circle');for(const [k,v]of Object.entries({cx:x,cy:y,r:4,fill:'#c299ff'}))c.setAttribute(k,v);const title=document.createElementNS(ns,'title');title.textContent=String(values[i]);c.append(title);svg.append(c);});
 target.append(svg,node('p',sentence('Stored counts: ','Kayıtlı bulgu sayıları: ')+values.join(' → '),'subtext'));
}
function findingCopy(check){const copy={
 not_null:['A required value is empty','Fill the missing value from the source system, then rerun the inspection.'],
 unique:['An order identifier is repeated','Check whether these records represent the same order before removing duplicates.'],
 amount_format:['An amount has an invalid format','Check decimal format and use no more than two fractional digits.'],
 missing_column:['A required column is missing','Compare the export columns with order_id, customer_id and order_total.'],
 unexpected_column:['A column is outside the contract','Review the export schema before changing the contract.'],
 nonempty_dataset:['The source has no data records','Verify that the export or query returned actual order records.']};return copy[check]||['A data check failed','Review the linked source evidence before making a change.'];}
function renderDetail(item){
 const target=el('detail');target.replaceChildren();target.append(node('h3',t(names[item.case]||item.case)));
 const report=item.source_report;
 if(!report){target.append(empty('Older report','This report contains summary data only. A new inspection will capture detailed findings.'));return;}
 target.append(node('p',sentence(`${report.row_count} records checked · ${report.finding_count} source findings`,`${report.row_count} kayıt kontrol edildi · ${report.finding_count} kaynak bulgusu`)));
 if(report.findings_truncated)target.append(node('p',t('Only the first findings are shown; the total finding count may be larger.')));
 for(const f of groupFindings(report)){const [what,next]=findingCopy(f.check),box=node('article','','finding');box.append(node('h3',t(what)));const dl=node('dl');for(const [label,value]of [['Column',f.column||'—'],['Record numbers',f.record_numbers.join(', ')||t('Schema level')],['Suggested review',t(next)]])dl.append(node('dt',t(label)),node('dd',value));box.append(dl);target.append(box);}
 for(const step of item.steps||[])if(step.tool==='run_batch')for(const c of step.report.reconciliation||[]){const box=node('article','','finding');box.append(node('h3',t(c.check==='order_count'?'Order count reconciliation':'Amount reconciliation')),node('p',sentence(`Expected ${c.expected} · Observed ${c.actual} · ${c.passed?'Matched':'Mismatch'}`,`Beklenen ${c.expected} · Gözlenen ${c.actual} · ${c.passed?'Eşleşti':'Uyuşmazlık'}`)));target.append(box);}
 if(!report.findings.length)target.append(node('p',t('No source contract violations were observed. Check reconciliation results if present.')));
 const advanced=node('details','','evidence-advanced');advanced.append(node('summary',t('Technical evidence and content hashes')),node('code',report.source_sha256));for(const s of item.steps||[])advanced.append(node('p',s.tool),node('code',s.report_sha256));target.append(advanced);
}
function renderResults(run){
 const result=run?.result,cases=result?.cases||[],summary=summarizeResult(result);
 el('result-origin').textContent=run?.run_id?t(origin(run))+' · '+run.run_id.slice(0,8):t('No inspection result selected.');
 const box=el('result-summary');box.textContent=result&&!summary.detailsAvailable?t('This older report does not retain detailed violation counts.'):result?sentence(`${summary.rows} record checks · ${summary.findings+summary.reconciliation} observed violations · Changes applied: 0`,`${summary.rows} kayıt kontrolü · ${summary.findings+summary.reconciliation} gözlenen ihlal · Uygulanan değişiklik: 0`):t('Your results will appear here after you explicitly start an inspection.');
 const target=el('results');target.replaceChildren();
 cases.forEach((item,i)=>{const b=node('button','','case-button'+(selected===i?' selected':''));b.setAttribute('aria-pressed',String(selected===i));b.append(node('strong',t(names[item.case]||item.case)),node('small',t(item.assessment==='NO_FAILURE_OBSERVED'?'No observed failure':item.assessment==='SOURCE_QUALITY_FAILURE'?'Source data issue':'Transformation mismatch')));b.onclick=()=>{selected=i;render();};target.append(b);});
 if(cases.length){selected=Math.min(selected,cases.length-1);renderDetail(cases[selected]);}
 else{el('detail').replaceChildren(empty('No findings yet','Choose a file and run an inspection. Each finding will explain what failed, where and what to check next.'));}
}
function openRun(id){view=id;selected=0;navigate('/investigations');render();}
function render(){
 const run=currentRun();controls();renderOverview(run);renderResults(run);
 const events=el('events');events.replaceChildren(...(run?.events||[]).map(e=>{const li=node('li');li.append(node('strong',t(e.agent)),node('span',t(e.state)),node('p',t(e.description)));return li;}));
 if(!run?.events?.length)events.append(empty('No execution events','Events appear only after an inspection is explicitly started.'));
 el('activity-origin').textContent=t(origin(run));
 el('references').replaceChildren(...(run?.result?.references||[]).map(r=>{const box=node('article','','reference');box.append(node('h3',r.source+' / '+r.revision),node('p',r.text),node('code',r.citation_sha256));return box;}));
 if(!run?.result?.references?.length)el('references').append(empty('No references used yet','Completed investigations show their original source text and content hash here.'));
 const saved=[...(state?.run_id&&state.status!=='RUNNING'?[state]:[]),...(state?.history||[])];
 el('history').replaceChildren(...saved.slice(0,4).map(r=>{const b=node('button',t(names[r.scenario]||r.scenario));b.append(node('small',t(origin(r))+' · '+t(r.status)));b.onclick=()=>openRun(r.run_id);return b;}));
 if(!saved.length)el('history').append(node('p',t('No saved investigations.')));
 el('history-list').replaceChildren(...saved.map(r=>{const b=node('button');const label=node('span',t(names[r.scenario]||r.scenario));label.append(node('small',t(origin(r))+' · '+(r.started_at?new Date(r.started_at).toLocaleString(language==='tr'?'tr-TR':'en-GB'):r.run_id.slice(0,8))));b.append(label,node('span',t(r.status)));b.onclick=()=>openRun(r.run_id);return b;}));
 if(!saved.length)el('history-list').append(empty('No saved investigations.','Completed inspections can be reopened here without running them again.'));
 if(run?.status==='RUNNING')setNotice('Inspection is running. Results will appear when checks finish.');
 else if(run?.error)setNotice(run.error,true);
 else if(run?.result)setNotice(sentence((view?'Saved report':'Latest stored report')+' · '+t(origin(run))+' · '+t(run.status),(view?'Kayıtlı rapor':'Son kayıtlı rapor')+' · '+t(origin(run))+' · '+t(run.status)));
 else setNotice('Choose your data or explicitly run an example. Nothing starts automatically.');
 translatePage();
}
async function refresh(){try{const next=await request('/api/state');const changed=JSON.stringify(next)!==JSON.stringify(state);state=next;connected=true;if(view==='none'&&next.status==='RUNNING')view=null;if(changed)render();else controls();if(pendingRun&&next.status!=='RUNNING'){pendingRun=false;if(location.pathname==='/investigations'){const target=el(next.status==='COMPLETED'?'result-summary':'notice');target.setAttribute('tabindex','-1');target.style.scrollMarginTop=(document.querySelector('.app-header').getBoundingClientRect().height+16)+'px';target.focus({preventScroll:true});target.scrollIntoView({block:'start'});}}}catch(error){connected=false;clearInterval(polling);controls();setNotice(error.message,true);}}
function navigate(path,push=true){if(path==='/')path='/overview';const page=pages[path]||pages['/overview'];if(push)history.pushState({},'',path);document.querySelectorAll('[data-screen]').forEach(s=>s.classList.toggle('active',s.dataset.screen===page[0]));el('page-title').textContent=t(page[1]);el('page-description').textContent=t(page[2]);document.querySelectorAll('nav .route').forEach(a=>{const active=a.pathname===path;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});document.title='AegisFlow · '+t(page[1]);translatePage();window.scrollTo(0,0);}
document.querySelectorAll('.route').forEach(a=>a.onclick=e=>{e.preventDefault();navigate(a.pathname);});
window.addEventListener('popstate',()=>navigate(location.pathname,false));
el('session-toggle').onclick=()=>{el('access').open=!el('access').open;if(el('access').open)el('token').focus();};
el('connect').onclick=async()=>{token=el('token').value;el('token').value='';clearInterval(polling);await refresh();if(connected){el('access').open=false;polling=setInterval(()=>{if(!document.hidden)refresh();},1500);}};
document.querySelectorAll('.lang').forEach(b=>b.onclick=()=>{language=b.dataset.language;localStorage.setItem('aegis-language',language);navigate(location.pathname,false);render();updateFilePreview();});
el('choose-file').onclick=()=>chooseMode('file');el('choose-example').onclick=()=>chooseMode('example');
el('open-example').onclick=()=>{navigate('/investigations');chooseMode('example');};
el('current').onclick=()=>{view=null;selected=0;render();navigate('/investigations');};
function updateFilePreview(){const file=el('csv-file').files[0];el('file-preview').textContent=file?file.name+' · '+(file.size/1024).toFixed(1)+' KB · '+t('Not sent yet'):t(el('file-preview').dataset.phase==='submitted'?'File submitted. Findings will appear below.':'No file chosen. No data has been sent.');controls();}
el('csv-file').onchange=()=>{el('file-preview').dataset.phase='selected';updateFilePreview();};
el('inspect').onclick=async()=>{const file=el('csv-file').files[0];if(!file||file.size<1||file.size>1000000){setNotice('Choose a CSV file up to 1 MB.',true);return;}el('inspect').disabled=true;view=null;selected=0;pendingRun=true;try{await request('/api/inspect','POST',await file.arrayBuffer());el('csv-file').value='';el('file-preview').dataset.phase='submitted';updateFilePreview();await refresh();}catch(error){pendingRun=false;setNotice(error.message,true);controls();}};
el('run').onclick=async()=>{el('run').disabled=true;view=null;selected=0;pendingRun=true;try{const key=el('scenario').value;await request('/api/run'+(key==='suite'?'':'/'+key),'POST');await refresh();}catch(error){pendingRun=false;setNotice(error.message,true);controls();}};
el('download-json').onclick=()=>{const run=currentRun();if(!run?.result)return;const data={run_id:run.run_id,status:run.status,scenario:run.scenario,result:run.result};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download='aegisflow-report.json';a.click();URL.revokeObjectURL(url);};
function downloadFile(content,type,name){const url=URL.createObjectURL(new Blob([content],{type}));const a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
el('template').onclick=()=>downloadFile('order_id,customer_id,order_total\nSAMPLE-001,CUSTOMER-001,125.50\nSAMPLE-002,CUSTOMER-002,80.00\nSAMPLE-003,CUSTOMER-003,42.25\n','text/csv;charset=utf-8','aegisflow-synthetic-orders-template.csv');
el('download').onclick=()=>{const run=currentRun();if(run?.result)downloadFile(readableReport(run,t,language),'text/html;charset=utf-8','aegisflow-inspection-report.html');};
navigate(location.pathname,false);render();
