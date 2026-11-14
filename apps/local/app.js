'use strict';
let token = ''; let polling;
const el = id => document.getElementById(id);
const text = (tag, value) => { const node = document.createElement(tag); node.textContent = value; return node; };
async function request(path, method='GET') {
 const response = await fetch(path, {method, headers:{Authorization:'Bearer '+token}, cache:'no-store'});
 if (!response.ok) throw new Error(response.status===409?'An investigation is already running.':'Connection denied or unavailable.');
 return response.json();
}
async function refresh(){
 try {
  const state = await request('/api/state');
  el('notice').textContent = 'Investigation: '+state.status+(state.error?' · '+state.error:'');
  el('run').disabled = state.status==='RUNNING';
  el('events').replaceChildren(...state.events.map(event => text('li',event.agent+' · '+event.state+' — '+event.description)));
  el('results').replaceChildren(...(state.result?.cases||[]).map(item=>{const node=text('div',item.case+' · '+item.assessment);node.className='case';return node;}));
  el('references').replaceChildren(...(state.result?.references||[]).map(item=>{const box=document.createElement('div');box.append(text('p',item.text),text('code',item.source+' / '+item.revision+' / '+item.citation_sha256));return box;}));
 } catch(error){el('notice').textContent=error.message;el('run').disabled=true;clearInterval(polling);}
}
el('connect').onclick=()=>{token=el('token').value;el('token').value='';clearInterval(polling);refresh();polling=setInterval(()=>{if(!document.hidden)refresh();},1000);};
el('run').onclick=async()=>{el('run').disabled=true;try{await request('/api/run','POST');await refresh();}catch(error){el('notice').textContent=error.message;}};
