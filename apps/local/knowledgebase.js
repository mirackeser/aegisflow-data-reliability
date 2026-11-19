// Knowledge base: documents the operator adds, with provenance, and a cited search over them and the built-ins.
let kbDocs=null,kbLoading=false,kbResults=null,kbQuery='',kbDraft={name:'',text:''};
async function loadKnowledgeBase(){
 if(kbLoading||kbDocs||!connected)return;
 kbLoading=true;
 try{kbDocs=await request('/api/knowledge');}catch(error){setNotice(error.message,true);}
 kbLoading=false;render();
}
async function addDocument(){
 if(!requireSession())return;
 try{
  const result=await request('/api/knowledge/add','POST',JSON.stringify({name:kbDraft.name,text:kbDraft.text}),JSON_HEADERS);
  kbDraft={name:'',text:''};kbDocs=await request('/api/knowledge');kbResults=null;setNotice(t('kb.added.'+result.status));
 }catch(error){setNotice(error.message,true);}
 render();
}
async function removeDocument(source){
 if(!requireSession())return;
 try{await request('/api/knowledge/remove','POST',JSON.stringify({source}),JSON_HEADERS);kbDocs=await request('/api/knowledge');kbResults=null;setNotice(t('kb.removed'));}
 catch(error){setNotice(error.message,true);}
 render();
}
async function searchKnowledge(){
 if(!requireSession())return;
 try{kbResults=(await request('/api/knowledge/search','POST',JSON.stringify({query:kbQuery}),JSON_HEADERS)).results;setNotice('');}
 catch(error){kbResults=null;setNotice(error.message,true);}
 render();
}
function kbResultCard(r){
 return h('article',{class:'reference'},
  h('div',{class:'ref-head'},h('strong',{text:tt('ref.'+r.source,r.source)}),chip(r.builtin?t('kb.origin.built-in'):t('kb.origin.added'),r.builtin?'muted':'info'),chip(r.verified?t('badge.verified'):t('kb.unverified'),r.verified?'ok':'warn')),
  h('small',{text:t('kb.terms',{n:N(r.matching_terms)})+' · '+r.source+' · '+r.revision}),h('small',{class:'block',text:t('kb.span',{n:N(r.chunk+1),start:N(r.start+1),end:N(r.end)})}),
  h('blockquote',{text:r.text}),h('small',{text:t('kb.hash.passage')}),h('code',{text:r.citation_sha256}));
}
function knowledgeBasePanel(){
 if(!kbDocs)return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('kb.title')})),empty('evidence.loading.t','evidence.loading.x'));
 const added=kbDocs.documents.filter(d=>!d.builtin),max=kbDocs.limits.documents;
 const rows=kbDocs.documents.map(d=>h('tr',{},
  h('th',{scope:'row',text:d.name||tt('ref.'+d.source,d.source)},h('small',{class:'block',text:d.source})),
  h('td',{},chip(d.builtin?t('kb.origin.built-in'):t('kb.origin.added'),d.builtin?'muted':'info')),
  h('td',{class:'hide-sm'},h('code',{text:d.revision})),h('td',{class:'hide-sm',text:t('kb.bytes',{n:N(d.bytes)})}),h('td',{class:'hide-sm',text:d.added_at?when(d.added_at):'—'}),
  h('td',{},d.builtin?null:h('button',{type:'button',class:'secondary',onclick:()=>removeDocument(d.source)},t('kb.remove')))));
 const list=h('div',{class:'table-wrap'},h('table',{class:'data-table'},h('thead',{},h('tr',{},['kb.col.name','kb.col.origin','kb.col.revision','kb.col.size','kb.col.added','kb.col.actions'].map(k=>h('th',{scope:'col',class:/revision|size|added/.test(k)?'hide-sm':null,text:t(k)})))),h('tbody',{},rows)));
 const form=h('form',{class:'stack kb-form',onsubmit:e=>{e.preventDefault();addDocument();}},h('h3',{text:t('kb.add.title')}),
  h('label',{for:'kb-name',text:t('kb.name')}),h('input',{id:'kb-name',type:'text',maxlength:'80',value:kbDraft.name,oninput:e=>{kbDraft.name=e.target.value;}}),
  h('label',{for:'kb-text',text:t('kb.text',{max:N(kbDocs.limits.bytes)})}),h('textarea',{id:'kb-text',rows:'6',value:kbDraft.text,oninput:e=>{kbDraft.text=e.target.value;}}),
  h('p',{class:'hint',text:t('kb.untrusted')}),h('button',{type:'submit',class:'primary'},t('kb.add.button')));
 const search=h('form',{class:'stack kb-form',onsubmit:e=>{e.preventDefault();searchKnowledge();}},h('h3',{text:t('kb.search.title')}),
  h('label',{for:'kb-query',text:t('kb.search.label')}),h('input',{id:'kb-query',type:'search',maxlength:'256',value:kbQuery,oninput:e=>{kbQuery=e.target.value;}}),
  h('button',{type:'submit',class:'secondary'},t('kb.search.button')),
  kbResults===null?null:kbResults.length?h('div',{class:'ref-grid'},kbResults.map(kbResultCard)):h('p',{class:'panel-note',text:t('kb.search.none')}));
 return h('section',{class:'panel'},h('div',{class:'panel-heading'},h('h2',{text:t('kb.title')}),chip(t('kb.count',{n:N(added.length),max:N(max)}),'muted')),
  h('p',{class:'panel-note',text:t('kb.intro')}),list,h('div',{class:'grid-2'},form,search),
  kbDocs.rejected_on_load?h('p',{class:'hint bad',text:t('kb.rejected',{n:N(kbDocs.rejected_on_load)})}):null);
}
