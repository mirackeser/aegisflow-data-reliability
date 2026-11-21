// Schema registry panel: versioned schema snapshots, a diff against the previous version and drift from a pinned contract.
// The types are inferred from the sample that was read; nothing here is a declaration by the data owner.
let srOverview=null,srLoading=false,srSubject='orders',srResult=null;
async function loadSchemaRegistry(){
 if(srLoading||srOverview||!connected)return;
 srLoading=true;
 try{srOverview=await request('/api/schemas');}catch(error){setNotice(error.message,true);}
 srLoading=false;render();
}
function srColumns(d){return d.columns.map(c=>({name:c.name,type:c.inferred_type}));}
async function registerSchema(d){
 if(!requireSession())return;
 try{
  srResult=await request('/api/schemas/register','POST',JSON.stringify({subject:srSubject,columns:srColumns(d)}),JSON_HEADERS);
  srOverview=await request('/api/schemas');setNotice(t(srResult.created?'sr.created':'sr.unchanged',{version:srResult.version}));
 }catch(error){srResult=null;setNotice(error.message,true);}
 render();
}
async function pinContract(version){
 if(!requireSession())return;
 try{
  await request('/api/schemas/contract','POST',JSON.stringify({subject:srSubject,version}),JSON_HEADERS);
  srOverview=await request('/api/schemas');
  if(srResult)srResult={...srResult,drift:{...srResult.drift,status:'CONFORMS',contract_version:version}};
  setNotice(t('sr.pinned',{version}));
 }catch(error){setNotice(error.message,true);}
 render();
}
function srDiffList(diff){
 if(!diff)return null;
 const rows=[];
 if(diff.added.length)rows.push(['sr.added',diff.added.join(', ')]);
 if(diff.removed.length)rows.push(['sr.removed',diff.removed.join(', ')]);
 if(diff.widened.length)rows.push(['sr.widened',diff.widened.map(x=>`${x.name}: ${t('type.'+x.from)} → ${t('type.'+x.to)}`).join('; ')]);
 if(diff.narrowed.length)rows.push(['sr.narrowed',diff.narrowed.map(x=>`${x.name}: ${t('type.'+x.from)} → ${t('type.'+x.to)}`).join('; ')]);
 if(diff.uninformative.length)rows.push(['sr.uninformative',diff.uninformative.map(x=>x.name).join(', ')]);
 if(diff.reordered)rows.push(['sr.reordered',t('sr.reordered.x')]);
 if(diff.possible_renames.length)rows.push(['sr.renames',diff.possible_renames.map(x=>`${x.from} → ${x.to}`).join('; ')]);
 if(!rows.length)return h('p',{class:'hint',text:t('sr.nochange')});
 return h('dl',{class:'sr-diff'},rows.flatMap(([key,text])=>[h('dt',{text:t(key)}),h('dd',{text})]));
}
function schemaRegistryPanel(d){
 if(!d||!d.columns)return null;
 loadSchemaRegistry();
 const subject=(srOverview?.subjects||[]).find(x=>x.subject===srSubject);
 const drift=srResult?.drift,tone={CONFORMS:'ok',DRIFT_COMPATIBLE:'warn',DRIFT_BREAKING:'bad',NO_CONTRACT:'muted'};
 return h('section',{class:'panel sr-panel'},h('div',{class:'panel-heading'},h('h3',{text:t('sr.title')}),chip(t('sr.sample'),'info')),
  h('p',{class:'hint',text:t('sr.note')}),
  srOverview?.rejected_on_load?h('p',{class:'hint bad',text:t('sr.rejected')}):null,
  h('div',{class:'kb-form'},h('label',{for:'sr-subject',text:t('sr.subject')}),
   h('input',{id:'sr-subject',type:'text',maxlength:'64',value:srSubject,oninput:e=>{srSubject=e.target.value;}}),
   h('button',{type:'button',class:'secondary',onclick:()=>registerSchema(d)},t('sr.register'))),
  srResult?h('div',{class:'sr-result'},
   h('p',{},h('strong',{text:t('sr.version',{version:srResult.version})}),' ',chip(t(srResult.created?'sr.new':'sr.same'),srResult.created?'info':'muted'),
    ' ',srResult.diff?chip(t('sr.diff.'+srResult.diff.status),{IDENTICAL:'muted',COMPATIBLE:'ok',BREAKING:'bad'}[srResult.diff.status]):null),
   srDiffList(srResult.diff),
   drift?h('p',{},t('sr.drift'),' ',chip(t('sr.drift.'+drift.status),tone[drift.status]),drift.contract_version?' '+t('sr.contractVersion',{version:drift.contract_version}):''):null,
   drift&&drift.diff&&drift.status!=='CONFORMS'&&JSON.stringify(drift.diff)!==JSON.stringify(srResult.diff)?srDiffList(drift.diff):null,
   h('button',{type:'button',class:'secondary',onclick:()=>pinContract(srResult.version)},t('sr.pin',{version:srResult.version}))):null,
  subject?h('div',{},h('h4',{text:t('sr.history')}),
   h('ul',{class:'sr-history'},subject.history.map(v=>h('li',{},h('strong',{text:'v'+v.version}),' ',h('small',{text:t('sr.cols',{count:v.columns})+' · '+v.schema_sha256.slice(0,12)}),
    subject.contract===v.version?' '+'':'',subject.contract===v.version?chip(t('sr.contract'),'ok'):null)))):null);
}
