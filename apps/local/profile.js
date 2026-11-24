// Generic profile of any CSV: column roles, statistics and time-series checks with exact record numbers.
// Rules of thumb on the values read; nothing here names a root cause.
let profileResult=null,profileBusy=false;
async function runProfile(){
 if(!selectedFile||profileBusy||!requireSession())return;
 profileBusy=true;
 try{profileResult=await request('/api/profile','POST',await selectedFile.arrayBuffer(),{'Content-Type':'text/csv'});setNotice('');}
 catch(error){profileResult=null;setNotice(error.message,true);}
 profileBusy=false;render();
}
function profileButton(){
 return h('button',{type:'button',class:'secondary',disabled:!selectedFile||selectedFile.size>1000000||profileBusy,onclick:runProfile},t('pf.button'));
}
function pfNum(v){return v===undefined?'':N(Math.round(v*1000)/1000);}
function pfDetail(f){
 const d=f.detail||{};
 if(f.check==='empty_rate')return t('pf.d.share',{p:N(Math.round(d.share*1000)/10)});
 if(f.check==='type_mismatch')return t('pf.d.expected',{role:t('pf.role.'+d.expected)});
 if(f.check==='constant_column')return t('pf.d.value',{v:d.value});
 if(f.check==='outlier')return t('pf.d.method.'+d.method);
 if(f.check==='level_shift')return t('pf.d.shift',{v:d.shifts.map(pfNum).join(', ')});
 if(f.check==='flatline')return d.runs.map(r=>t('pf.d.run',{a:r.first,b:r.last,v:pfNum(r.value)})).join('; ');
 if(f.check==='timestamp_gap')return t('pf.d.gap',{s:pfNum(d.typical_seconds),n:d.missing_intervals.join(', ')});
 return '';
}
function profilePanel(){
 if(!profileResult)return null;
 const r=profileResult;
 return h('section',{class:'panel pf-panel'},h('div',{class:'panel-heading'},h('h3',{text:t('pf.title')}),
   chip(t(r.status==='FINDINGS'?'pf.status.FINDINGS':'pf.status.NO_FINDINGS'),r.status==='FINDINGS'?'warn':'ok')),
  h('p',{class:'hint',text:t('pf.note')}),
  h('p',{text:t('pf.summary',{n:N(r.records),c:N(r.columns.length),clock:r.time_column||t('pf.noclock')})}),
  h('div',{class:'table-wrap'},h('table',{class:'pf-columns'},h('thead',{},h('tr',{},['pf.col.name','pf.col.role','pf.col.filled','pf.col.empty','pf.col.distinct','pf.col.min','pf.col.median','pf.col.max'].map(k=>h('th',{scope:'col',text:t(k)})))),
   h('tbody',{},r.columns.map(c=>h('tr',{},h('td',{text:c.name}),h('td',{text:t('pf.role.'+c.role)}),h('td',{text:N(c.filled)}),h('td',{text:N(c.empty)}),h('td',{text:N(c.distinct)}),
    h('td',{text:pfNum(c.min)}),h('td',{text:pfNum(c.median)}),h('td',{text:pfNum(c.max)})))))),
  r.findings.length?h('ul',{class:'pf-findings'},r.findings.map(f=>h('li',{},
    h('strong',{text:t('pf.check.'+f.check)}),f.column?' · '+f.column:'',' ',chip(t('pf.count',{n:N(f.count)}),'info'),
    h('p',{class:'hint',text:t('pf.explain.'+f.check)}),
    f.records.length?h('p',{text:t('pf.records',{list:f.records.join(', ')+(f.count>f.records.length?' …':'')})}):null,
    pfDetail(f)?h('p',{class:'hint',text:pfDetail(f)}):null))):h('p',{class:'hint',text:t('pf.none')}));
}
