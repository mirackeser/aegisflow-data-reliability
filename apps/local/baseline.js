// SPDX-License-Identifier: Apache-2.0
// Baseline comparison panel: save a stored summary of earlier CSV files and compare the selected file with it.
// Every number shown comes from the compare result; PSI is a descriptive index, not a significance test, and no cause is inferred.
let blList=null,blLoading=false,blName='',blRefs=[],blSla='',blChoice='',blAsOf='',blBusy=false,blSaveError='',blCompareError='',blResult=null,blResultFile=null,blColumn=null;
const BL_MAX_REFS=5,BL_MAX_BYTES=1000000,BL_THRESHOLD=0.25;
const BL_TRANSLIT={'ı':'i','ß':'ss','ø':'o','đ':'d','ł':'l','æ':'ae','œ':'oe'};
// Mirrors baseline_store.slug so an existing name can be confirmed before it is replaced.
function blSlug(name){
 const folded=name.toLowerCase().normalize('NFKD').replace(/[ıßøđłæœ]/g,c=>BL_TRANSLIT[c]).replace(/[^\x00-\x7f]/g,'');
 return folded.replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,64).replace(/^-+|-+$/g,'');
}
function blPad(n){return String(n).padStart(2,'0');}
function blNow(){const d=new Date();return `${d.getFullYear()}-${blPad(d.getMonth()+1)}-${blPad(d.getDate())}T${blPad(d.getHours())}:${blPad(d.getMinutes())}:${blPad(d.getSeconds())}`;}
function blRound(v,digits=1){const f=10**digits;return Math.round(v*f)/f;}
function blDur(s){
 if(s===null||s===undefined)return '—';
 const a=Math.abs(s);
 if(a<120)return t('bl.unit.s',{v:N(blRound(s))});
 if(a<7200)return t('bl.unit.min',{v:N(blRound(s/60))});
 if(a<172800)return t('bl.unit.h',{v:N(blRound(s/3600))});
 return t('bl.unit.d',{v:N(blRound(s/86400))});
}
function blPsi(v){return N(blRound(v,3));}
function blShare(v){return P(v);}
function blNum(v){return v===null||v===undefined?'—':N(blRound(v,3));}

async function loadBaselines(force=false){
 if(blLoading||(!force&&blList)||!connected)return;
 blLoading=true;
 try{blList=await request('/api/baselines');}catch(error){setNotice(error.message,true);}
 blLoading=false;render();
}
async function saveBaseline(){
 if(blBusy||!requireSession())return;
 const name=blName.trim(),key=name?blSlug(name):'';
 let problem='';
 if(!key)problem=t('bl.err.name');
 else if(!blRefs.length||blRefs.length>BL_MAX_REFS)problem=t('bl.err.count',{max:BL_MAX_REFS});
 else if(blRefs.some(f=>f.size>BL_MAX_BYTES))problem=t('bl.err.filesize',{name:blRefs.find(f=>f.size>BL_MAX_BYTES).name});
 else if(blSla.trim()&&!/^[1-9]\d{0,8}$/.test(blSla.trim()))problem=t('bl.err.sla');
 if(problem){blSaveError=problem;render();return;}
 const exists=(blList?.baselines||[]).some(b=>b.name===key);
 if(exists&&!confirm(t('bl.confirm.replace',{name:key})))return;
 blBusy=true;blSaveError='';render();
 try{
  const references=await Promise.all(blRefs.map(f=>f.text()));
  const body={name,references,replace:exists};
  if(blSla.trim())body.freshness_sla_seconds=Number(blSla.trim());
  const saved=await request('/api/baselines/save','POST',JSON.stringify(body),JSON_HEADERS);
  blChoice=saved.name;blRefs=[];blName='';
  blList=await request('/api/baselines');
  setNotice(t('bl.saved',{name:saved.name}));
 }catch(error){blSaveError=error.message;}
 blBusy=false;render();
}
async function compareBaseline(){
 if(blBusy||!selectedFile||!blChoice||!requireSession())return;
 if(selectedFile.size>BL_MAX_BYTES){blCompareError=t('err.size');render();return;}
 blBusy=true;blCompareError='';render();
 const file=selectedFile;
 try{
  const body={name:blChoice,csv:await file.text()};
  if(blAsOf)body.as_of=blAsOf;
  blResult=await request('/api/baselines/compare','POST',JSON.stringify(body),JSON_HEADERS);blResultFile=file;
  const changed=blResult.findings.find(f=>f.check==='distribution_shift');
  blColumn=changed?changed.column:Object.keys(blResult.measurements.psi)[0]||null;
  setNotice('');
 }catch(error){
  blResult=null;
  if(error.status===404){blCompareError=t('bl.err.notfound');blList=null;}else blCompareError=error.message;
 }
 blBusy=false;render();
 if(blResult)document.getElementById('bl-result')?.focus({preventScroll:false});
}
async function removeBaseline(name){
 if(blBusy||!requireSession()||!confirm(t('bl.confirm.remove',{name})))return;
 blBusy=true;render();
 try{
  await request('/api/baselines/remove','POST',JSON.stringify({name}),JSON_HEADERS);
  if(blChoice===name)blChoice='';
  if(blResult?.name===name)blResult=null;
  blList=await request('/api/baselines');setNotice(t('bl.removed',{name}));
 }catch(error){setNotice(error.status===404?t('bl.err.notfound'):error.message,true);blList=null;}
 blBusy=false;render();
}

// ---------- small building blocks ----------
function blIcon(kind){
 const svg=svgEl('svg',{viewBox:'0 0 16 16',class:'bl-icon','aria-hidden':'true',focusable:'false'});
 if(kind==='ok')svg.append(svgEl('circle',{cx:8,cy:8,r:6.5}),svgEl('path',{d:'M5 8.2 7.1 10.3 11 6'}));
 else if(kind==='changed')svg.append(svgEl('path',{d:'M8 1.8 14.6 13.6H1.4Z'}),svgEl('path',{d:'M8 6v3.6M8 11.4v.3'}));
 else svg.append(svgEl('circle',{cx:8,cy:8,r:6.5,'stroke-dasharray':'2.4 2'}),svgEl('path',{d:'M5 8h6'}));
 return svg;
}
function blState(kind){return h('span',{class:'bl-state '+kind},blIcon(kind),t('bl.state.'+kind));}
function blCheckState(r,check){
 if(r.findings.some(f=>f.check===check))return 'changed';
 if(r.not_evaluated.some(n=>n.check===check))return 'skipped';
 return 'ok';
}
function blReason(entry){return t('bl.reason.'+entry.reason);}
function blTile(labelKey,kind,value,note){
 return h('div',{class:'bl-tile '+kind},h('span',{class:'bl-tile-label',text:t(labelKey)}),blState(kind),
  h('strong',{class:'bl-tile-value',text:value}),note?h('small',{text:note}):null);
}
function blTiles(r){
 const m=r.measurements,skipped=check=>r.not_evaluated.find(n=>n.check===check);
 const sampling=blCheckState(r,'sampling_interval_change'),fresh=blCheckState(r,'freshness');
 const psiCols=Object.keys(m.psi),shifted=r.findings.filter(f=>f.check==='distribution_shift').length;
 const distSkipped=r.not_evaluated.filter(n=>n.check==='distribution_shift');
 const dist=shifted?'changed':psiCols.length?'ok':'skipped';
 const v=m.volume,band=v.baseline_min===v.baseline_max?N(v.baseline_min):`${N(v.baseline_min)}–${N(v.baseline_max)}`;
 return h('div',{class:'bl-tiles'},
  blTile('bl.tile.sampling',sampling,`${blDur(m.sampling_interval.baseline_seconds)} → ${blDur(m.sampling_interval.current_seconds)}`,
   sampling==='skipped'?blReason(skipped('sampling_interval_change')):t('bl.tile.sampling.x')),
  blTile('bl.tile.volume',blCheckState(r,'volume_change'),`${band} → ${N(v.current)}`,t('bl.tile.volume.x')),
  blTile('bl.tile.freshness',fresh,t('bl.tile.freshness.v',{sla:blDur(m.freshness.sla_seconds),lag:blDur(m.freshness.lag_seconds)}),
   fresh==='skipped'?blReason(skipped('freshness')):m.freshness.latest?t('bl.tile.freshness.latest',{latest:m.freshness.latest}):null),
  blTile('bl.tile.distribution',dist,psiCols.length?t('bl.tile.distribution.v',{k:shifted,n:psiCols.length}):'—',
   distSkipped.length?t('bl.tile.distribution.skipped',{n:distSkipped.length}):t('bl.tile.distribution.x')));
}
function blNumbers(captionKey,head,rows){
 return h('details',{class:'bl-numbers'},h('summary',{text:t('bl.numbers')}),
  h('div',{class:'table-wrap'},h('table',{class:'data-table compact'},h('caption',{class:'sr-only',text:t(captionKey)}),
   h('thead',{},h('tr',{},head.map(k=>h('th',{scope:'col',text:t(k)})))),
   h('tbody',{},rows.map(([first,...rest])=>h('tr',{},h('th',{scope:'row',text:first}),rest.map(x=>h('td',{text:x}))))))));
}

// ---------- charts ----------
// Styles go through the CSSOM: the page's Content-Security-Policy blocks inline style attributes.
function blAt(el,prop,value){el.style[prop]=value;return el;}
// PSI per compared numeric column as horizontal bars with the fixed threshold marked; "changed" comes from the findings.
function blPsiChart(r){
 const psi=r.measurements.psi,cols=Object.keys(psi);
 if(!cols.length)return h('p',{class:'hint',text:t('bl.psi.none')});
 const changed=new Set(r.findings.filter(f=>f.check==='distribution_shift').map(f=>f.column));
 const max=Math.max(...cols.map(c=>psi[c])),domain=Math.max(0.5,max*1.05),at=v=>Math.min(100,v/domain*100)+'%';
 const chart=h('div',{class:'bl-psi',role:'img','aria-label':t('bl.psi.aria',{n:cols.length,k:changed.size,max:blPsi(max)})},
  h('div',{class:'bl-psi-row bl-psi-axis','aria-hidden':'true'},h('span'),h('span',{class:'bl-psi-track bare'},blAt(h('span',{class:'bl-threshold-label',text:t('bl.psi.threshold',{v:N(BL_THRESHOLD)})}),'left',at(BL_THRESHOLD))),h('span')),
  cols.map(c=>h('div',{class:'bl-psi-row'+(changed.has(c)?' changed':'')},h('span',{class:'bl-psi-name',text:c}),
   h('span',{class:'bl-psi-track'},blAt(h('span',{class:'bl-psi-fill'}),'width',at(psi[c])),blAt(h('span',{class:'bl-threshold'}),'left',at(BL_THRESHOLD))),
   h('span',{class:'bl-psi-value'},blPsi(psi[c]),changed.has(c)?h('span',{class:'bl-state changed'},blIcon('changed'),t('bl.state.changed')):null))));
 return h('div',{},chart,h('p',{class:'hint',text:t('bl.psi.legend',{v:N(BL_THRESHOLD)})}),
  blNumbers('bl.psi.title',['bl.col.column','bl.col.psi','bl.col.state'],cols.map(c=>[c,blPsi(psi[c]),t(changed.has(c)?'bl.state.changed':'bl.state.ok')])));
}
function blBinLabel(edges,i){
 if(!edges.length)return t('bl.bin.all');
 if(i===0)return '< '+blNum(edges[0]);
 if(i===edges.length)return '≥ '+blNum(edges[edges.length-1]);
 return `${blNum(edges[i-1])} – ${blNum(edges[i])}`;
}
// Paired bars per bin: baseline hatched with an outline, current solid; both named in the legend and the table.
function blBinChart(column,bins){
 const n=bins.baseline.length,W=440,H=200,l=40,r=8,top=12,bottom=30,plotH=H-top-bottom,slot=(W-l-r)/n;
 const peak=Math.max(0.1,...bins.baseline,...bins.current),max=Math.ceil(peak*10)/10;
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,class:'bl-bins-svg',role:'img','aria-label':t('bl.bins.aria',{column,n,psi:blPsi(bins.psi)})});
 svg.append(svgEl('defs',{},svgEl('pattern',{id:'bl-hatch',patternUnits:'userSpaceOnUse',width:5,height:5,patternTransform:'rotate(45)'},
  svgEl('rect',{width:5,height:5,class:'bl-hatch-bg'}),svgEl('line',{x1:0,y1:0,x2:0,y2:5,class:'bl-hatch-line'}))));
 const py=v=>top+plotH*(1-v/max);
 for(const f of [0,0.5,1]){svg.append(svgEl('line',{x1:l,x2:W-r,y1:py(max*f),y2:py(max*f),class:'grid-line'}),svgText(blShare(max*f),{x:l-5,y:py(max*f)+3,class:'axis-label','text-anchor':'end'}));}
 const bar=(x,w,v,cls,label)=>{
  const ht=Math.max(v>0?1.5:0,plotH*v/max),rect=svgEl('rect',{x,y:top+plotH-ht,width:w,height:ht,rx:1.5,class:cls},svgEl('title',{}));
  rect.firstChild.textContent=label;svg.append(rect);
 };
 for(let i=0;i<n;i++){
  const x=l+i*slot,w=slot*0.36,range=blBinLabel(bins.edges,i);
  bar(x+slot*0.12,w,bins.baseline[i],'bl-bar-base',`${t('bl.series.baseline')} · ${range}: ${blShare(bins.baseline[i])}`);
  bar(x+slot*0.12+w,w,bins.current[i],'bl-bar-current',`${t('bl.series.current')} · ${range}: ${blShare(bins.current[i])}`);
  svg.append(svgText(String(i+1),{x:x+slot/2,y:H-14,class:'axis-label','text-anchor':'middle'}));
 }
 svg.append(svgText(t('bl.bins.axis'),{x:(l+W-r)/2,y:H-2,class:'axis-label','text-anchor':'middle'}));
 const key=(cls,text)=>h('span',{class:'bl-key'},(()=>{const s=svgEl('svg',{viewBox:'0 0 14 14','aria-hidden':'true',focusable:'false'},svgEl('rect',{x:1,y:1,width:12,height:12,rx:2,class:cls}));return s;})(),text);
 return h('div',{class:'bl-bins'},h('div',{class:'chart-area'},svg),
  h('p',{class:'bl-legend'},key('bl-bar-base',t('bl.series.baseline')),key('bl-bar-current',t('bl.series.current'))),
  blNumbers('bl.bins.title',['bl.col.bin','bl.series.baseline','bl.series.current'],
   bins.baseline.map((b,i)=>[`${i+1} · ${blBinLabel(bins.edges,i)}`,blShare(b),blShare(bins.current[i])])));
}

// ---------- findings ----------
function blDetail(f){
 const d=f.detail||{};
 switch(f.check){
  case 'role_change':return t('bl.d.role',{a:t('pf.role.'+d.baseline),b:t('pf.role.'+d.current)});
  case 'sampling_interval_change':return t('bl.d.sampling',{a:blDur(d.baseline_seconds),b:blDur(d.current_seconds),r:N(d.ratio)});
  case 'volume_change':return t('bl.d.volume.'+d.direction,{min:N(d.baseline_min),max:N(d.baseline_max),n:N(d.current)});
  case 'freshness':return t('bl.d.freshness',{lag:blDur(d.lag_seconds),sla:blDur(d.sla_seconds),latest:d.latest});
  case 'empty_rate_change':return t('bl.d.empty',{a:blShare(d.baseline),b:blShare(d.current)});
  case 'distribution_shift':return t('bl.d.shift',{psi:blPsi(d.psi),v:N(d.threshold),ma:blNum(d.baseline_mean),mb:blNum(d.current_mean),sa:blNum(d.baseline_sd),sb:blNum(d.current_sd)});
  default:return t('bl.explain.'+f.check);
 }
}
function blFindingList(r){
 if(!r.findings.length)return h('p',{class:'hint',text:t('bl.findings.none')});
 return h('ul',{class:'bl-list found'},r.findings.map(f=>h('li',{},blIcon('changed'),
  h('div',{},h('strong',{text:t('bl.check.'+f.check)}),f.column?h('code',{text:f.column}):null,h('p',{class:'hint',text:blDetail(f)})))));
}
function blSkippedList(r){
 if(!r.not_evaluated.length)return h('p',{class:'hint',text:t('bl.skipped.none')});
 return h('ul',{class:'bl-list'},r.not_evaluated.map(n=>h('li',{},blIcon('skipped'),
  h('div',{},h('strong',{text:t('bl.check.'+n.check)}),n.column?h('code',{text:n.column}):null,h('p',{class:'hint',text:blReason(n)})))));
}
function blResultView(r){
 const cols=Object.keys(r.measurements.bin_shares),column=cols.includes(blColumn)?blColumn:cols[0];
 const drift=r.status==='DRIFT';
 return h('div',{class:'bl-result',id:'bl-result',tabindex:'-1','aria-labelledby':'bl-result-title'},
  h('div',{class:'panel-heading'},h('h4',{id:'bl-result-title',text:t('bl.result.title',{name:r.name})}),
   h('span',{class:'chip '+(drift?'warn':'ok')},blIcon(drift?'changed':'ok'),t(drift?'bl.status.DRIFT':'bl.status.NO_DRIFT'))),
  h('p',{class:'hint',text:t('bl.result.summary',{file:blResultFile?.name||'',n:N(r.records),asof:r.as_of||t('bl.asof.none')})}),
  blTiles(r),
  h('h4',{text:t('bl.psi.title')}),blPsiChart(r),
  cols.length?h('div',{},h('h4',{text:t('bl.bins.title')}),
   h('div',{class:'bl-field'},h('label',{for:'bl-column',text:t('bl.bins.column')}),
    h('select',{id:'bl-column',onchange:e=>{blColumn=e.target.value;render();document.getElementById('bl-column')?.focus();}},cols.map(c=>h('option',{value:c,selected:c===column,text:c})))),
   blBinChart(column,r.measurements.bin_shares[column])):null,
  h('div',{class:'grid-2 bl-lists'},h('div',{},h('h4',{text:t('bl.findings.title')}),blFindingList(r)),
   h('div',{},h('h4',{text:t('bl.skipped.title')}),blSkippedList(r))));
}

// ---------- forms ----------
function blSaveForm(){
 const names=blList?.baselines||[];
 const refsState=h('p',{class:'file-state',id:'bl-refs-state','aria-live':'polite',text:blRefs.length?t('bl.refs.chosen',{n:blRefs.length,names:blRefs.map(f=>f.name).join(', ')}):t('bl.refs.none')});
 const saveButton=h('button',{type:'submit',class:'secondary',disabled:blBusy||!blRefs.length},t(blBusy?'bl.busy':'bl.save'));
 const files=h('input',{id:'bl-refs',type:'file',multiple:true,accept:'.csv,text/csv','aria-describedby':'bl-refs-hint bl-refs-state'+(blSaveError?' bl-save-error':''),
  onchange:e=>{blRefs=[...e.target.files];blSaveError='';refsState.textContent=blRefs.length?t('bl.refs.chosen',{n:blRefs.length,names:blRefs.map(f=>f.name).join(', ')}):t('bl.refs.none');saveButton.disabled=blBusy||!blRefs.length;}});
 return h('form',{class:'bl-form','aria-labelledby':'bl-save-title',novalidate:true,onsubmit:e=>{e.preventDefault();saveBaseline();}},
  h('h4',{id:'bl-save-title',text:t('bl.save.title')}),
  h('div',{class:'bl-field'},h('label',{for:'bl-name',text:t('bl.name')}),
   h('input',{id:'bl-name',type:'text',maxlength:'80',autocomplete:'off',value:blName,'aria-describedby':'bl-name-hint'+(blSaveError?' bl-save-error':''),oninput:e=>{blName=e.target.value;}}),
   h('small',{id:'bl-name-hint',text:t('bl.name.x')})),
  h('div',{class:'bl-field'},h('label',{for:'bl-refs',text:t('bl.refs')}),files,h('small',{id:'bl-refs-hint',text:t('bl.refs.x',{max:BL_MAX_REFS})}),refsState),
  h('div',{class:'bl-field'},h('label',{for:'bl-sla',text:t('bl.sla')}),
   h('input',{id:'bl-sla',type:'number',min:'1',step:'1',inputmode:'numeric',value:blSla,'aria-describedby':'bl-sla-hint',oninput:e=>{blSla=e.target.value;}}),
   h('small',{id:'bl-sla-hint',text:t('bl.sla.x')})),
  blSaveError?h('p',{class:'hint bad',id:'bl-save-error',role:'alert',text:blSaveError}):null,
  h('div',{class:'button-row'},saveButton),
  names.length?h('div',{},h('h4',{text:t('bl.saved.title')}),h('ul',{class:'bl-saved'},names.map(b=>h('li',{},
   h('div',{},h('strong',{text:b.name}),h('small',{text:t('bl.saved.meta',{refs:N(b.references),n:N(b.records),clock:b.time_column||t('pf.noclock'),when:when(b.created)})}),h('code',{text:b.digest.slice(0,12)})),
   h('button',{type:'button',class:'secondary','aria-label':t('bl.remove.label',{name:b.name}),disabled:blBusy,onclick:()=>removeBaseline(b.name)},t('bl.remove'))))))
   :h('p',{class:'hint',text:t('bl.saved.none')}));
}
function blCompareForm(){
 const names=blList?.baselines||[];
 if(blList&&blChoice&&!names.some(b=>b.name===blChoice))blChoice='';
 if(!blChoice&&names.length)blChoice=names[0].name;
 const tooBig=selectedFile&&selectedFile.size>BL_MAX_BYTES;
 const compareButton=h('button',{type:'submit',class:'primary',disabled:blBusy||!selectedFile||!blChoice||tooBig},t(blBusy?'bl.busy':'bl.compare'));
 return h('form',{class:'bl-form','aria-labelledby':'bl-compare-title',novalidate:true,onsubmit:e=>{e.preventDefault();compareBaseline();}},
  h('h4',{id:'bl-compare-title',text:t('bl.compare.title')}),
  h('div',{class:'bl-field'},h('label',{for:'bl-choice',text:t('bl.choice')}),
   h('select',{id:'bl-choice',disabled:!names.length,onchange:e=>{blChoice=e.target.value;compareButton.disabled=blBusy||!selectedFile||!blChoice||tooBig;}},
    names.length?names.map(b=>h('option',{value:b.name,selected:b.name===blChoice,text:b.name})):h('option',{value:'',text:t('bl.saved.none')}))),
  h('div',{class:'bl-field'},h('span',{class:'bl-label',text:t('bl.current')}),
   h('p',{class:'file-state',text:selectedFile?selectedFile.name:t('bl.current.none')})),
  h('div',{class:'bl-field'},h('label',{for:'bl-asof',text:t('bl.asof')}),
   h('div',{class:'bl-inline'},h('input',{id:'bl-asof',type:'datetime-local',step:'1',value:blAsOf,'aria-describedby':'bl-asof-hint',oninput:e=>{blAsOf=e.target.value;}}),
    h('button',{type:'button',class:'secondary',onclick:()=>{blAsOf=blNow();const input=document.getElementById('bl-asof');if(input)input.value=blAsOf;}},t('bl.now'))),
   h('small',{id:'bl-asof-hint',text:t('bl.asof.x')})),
  tooBig?h('p',{class:'hint bad',text:t('err.size')}):null,
  blCompareError?h('p',{class:'hint bad',role:'alert',text:blCompareError}):null,
  h('div',{class:'button-row'},compareButton));
}
function baselinePanel(){
 if(!connected)return null;
 loadBaselines();
 const showResult=blResult&&blResultFile===selectedFile;
 return h('section',{class:'panel bl-panel','aria-labelledby':'bl-title'},
  h('div',{class:'panel-heading'},h('h3',{id:'bl-title',text:t('bl.title')}),chip(t('bl.chip'),'info')),
  h('p',{class:'hint',text:t('bl.note')}),
  blList?.rejected_on_load?h('p',{class:'hint bad',text:t('bl.rejected')}):null,
  h('div',{class:'grid-2 bl-forms'},blSaveForm(),blCompareForm()),
  showResult?blResultView(blResult):null);
}
