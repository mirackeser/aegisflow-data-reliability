'use strict';
// SVG builders. Every number drawn here comes from the analysis or execution plan passed in.
const SVG_NS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs={},...children){
 const n=document.createElementNS(SVG_NS,tag);
 for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));
 for(const c of children)n.append(c);
 return n;
}
function svgText(text,attrs){const n=svgEl('text',attrs);n.textContent=text;return n;}
// Column/row layout of the capability graph; dependencies come from the plan itself.
const FLOW_LAYOUT={source:[0,80],contract_check:[1,80],profiling:[2,10],reconciliation:[2,90],impact:[2,170],
 evidence:[3,10],verification:[4,10],human_review:[5,10],root_cause:[5,100],remediation:[6,10]};
const NODE_W=160,NODE_H=66,COL_GAP=179;
function flowPosition(id){const [col,row]=FLOW_LAYOUT[id]||[0,0];return {x:10+col*COL_GAP,y:row};}
// describe(step) -> {title, meta, state}; source node is described through options.source.
function flowGraph(plan,describe,options={}){
 const nodes=[{id:'source',role:options.source?.role||'',title:options.source?.title||'',meta:options.source?.meta||'',state:options.source?.state||'waiting',depends_on:[]},
  ...plan.map(step=>({id:step.id,role:step.role,...describe(step),depends_on:step.depends_on.length?step.depends_on:['source']}))];
 const LANE_H=26;
 const svg=svgEl('svg',{viewBox:'0 0 1240 276',class:'flow-svg',role:'img','aria-label':options.label||'Capability graph','preserveAspectRatio':'xMidYMid meet'});
 const defs=svgEl('defs',{},svgEl('marker',{id:'flow-arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'7',markerHeight:'7',orient:'auto-start-reverse'},svgEl('path',{d:'M0 0 10 5 0 10z',class:'flow-arrowhead'})));
 svg.append(defs);
 const byId=Object.fromEntries(nodes.map(n=>[n.id,n]));
 const edges=svgEl('g',{class:'flow-edges'});
 for(const node of nodes){
  for(const dep of node.depends_on){
   const from=flowPosition(dep),to=flowPosition(node.id);
   const x1=from.x+NODE_W,y1=from.y+LANE_H+NODE_H/2,x2=to.x,y2=to.y+LANE_H+NODE_H/2,dx=Math.max(30,(x2-x1)/2);
   const live=byId[dep].state==='completed'&&node.state==='completed';
   const muted=['skipped','unavailable','disabled','rejected'].includes(node.state);
   edges.append(svgEl('path',{d:`M${x1} ${y1} C${x1+dx} ${y1} ${x2-dx} ${y2} ${x2-2} ${y2}`,class:'flow-edge'+(live?' live':muted?' muted':''),'marker-end':'url(#flow-arrow)'}));
  }
 }
 svg.append(edges);
 (options.lanes||[]).forEach((text,col)=>{svg.append(svgText(text,{x:10+col*COL_GAP,y:14,class:'flow-lane'}));if(col)svg.append(svgEl('line',{x1:10+col*COL_GAP-9,x2:10+col*COL_GAP-9,y1:4,y2:270,class:'flow-lane-line'}));});
 for(const node of nodes){
  const {x,y}=flowPosition(node.id);
  const g=svgEl('g',{class:`flow-node ${node.state}`,transform:`translate(${x} ${y+LANE_H})`});
  g.append(svgEl('title',{}),svgEl('rect',{width:NODE_W,height:NODE_H,rx:10}));
  g.firstChild.textContent=`${node.role?node.role+' · ':''}${node.title} — ${node.statusText||node.state}`;
  if(node.role)g.append(svgText(node.role,{x:12,y:19,class:'flow-role'}));
  g.append(svgText(node.title,{x:12,y:node.role?39:30,class:'flow-title'}),svgText(node.meta||'',{x:12,y:node.role?57:50,class:'flow-meta'}));
  g.append(svgEl('circle',{cx:NODE_W-14,cy:14,r:5,class:'flow-dot'}));
  svg.append(g);
 }
 return svg;
}
function histogramSvg(bins,{amountLabel=v=>v,label=''}={}){
 const W=440,H=190,left=8,bottom=34,top=18,max=Math.max(1,...bins.map(b=>b.count));
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,class:'hist-svg',role:'img','aria-label':label});
 svg.append(svgEl('defs',{},svgEl('linearGradient',{id:'hist-gradient',x1:'0',y1:'0',x2:'0',y2:'1'},svgEl('stop',{offset:'0','stop-color':'#35f0d8'}),svgEl('stop',{offset:'1','stop-color':'#8b5cf6'}))));
 const slot=(W-left*2)/bins.length,plotH=H-bottom-top;
 for(const f of [0.5,1])svg.append(svgEl('line',{x1:left,x2:W-left,y1:top+plotH*(1-f),y2:top+plotH*(1-f),class:'grid-line'}));
 bins.forEach((b,i)=>{
  const h=b.count/max*plotH,x=left+i*slot+slot*0.14,w=slot*0.72;
  svg.append(svgEl('rect',{x,y:top+plotH-h,width:w,height:Math.max(h,b.count?2:0),rx:3,class:'hist-bar'},svgEl('title',{})));
  svg.lastChild.firstChild.textContent=`${amountLabel(b.from)} – ${amountLabel(b.to)}: ${b.count}`;
  if(b.count)svg.append(svgText(String(b.count),{x:x+w/2,y:top+plotH-h-5,class:'hist-count','text-anchor':'middle'}));
 });
 svg.append(svgText(amountLabel(bins[0].from),{x:left,y:H-10,class:'axis-label'}),svgText(amountLabel(bins[bins.length-1].to),{x:W-left,y:H-10,class:'axis-label','text-anchor':'end'}));
 return svg;
}
function trendSvg(points,{label=''}={}){
 const W=440,H=170,l=28,r=16,t=18,b=26,max=Math.max(1,...points.map(p=>p.value));
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,class:'trend-svg',role:'img','aria-label':label});
 svg.append(svgEl('defs',{},svgEl('linearGradient',{id:'trend-area',x1:'0',y1:'0',x2:'0',y2:'1'},svgEl('stop',{offset:'0','stop-color':'#35f0d8','stop-opacity':'0.35'}),svgEl('stop',{offset:'1','stop-color':'#35f0d8','stop-opacity':'0'}))));
 const px=i=>points.length===1?(l+W-r)/2:l+i*(W-l-r)/(points.length-1),py=v=>t+(1-v/max)*(H-t-b);
 for(const f of [0,0.5,1]){svg.append(svgEl('line',{x1:l,x2:W-r,y1:py(max*f),y2:py(max*f),class:'grid-line'}),svgText(String(Math.round(max*f)),{x:l-6,y:py(max*f)+4,class:'axis-label','text-anchor':'end'}));}
 const line=points.map((p,i)=>`${px(i)},${py(p.value)}`).join(' ');
 svg.append(svgEl('polygon',{points:`${px(0)},${H-b} ${line} ${px(points.length-1)},${H-b}`,fill:'url(#trend-area)'}),svgEl('polyline',{points:line,class:'trend-line',fill:'none'}));
 points.forEach((p,i)=>{svg.append(svgEl('circle',{cx:px(i),cy:py(p.value),r:4.5,class:'trend-dot'},svgEl('title',{})));svg.lastChild.firstChild.textContent=`${p.label}: ${p.value}`;});
 return svg;
}

// Several quality ratios across the retained runs of one source; marks runs where a rule found a change.
function driftSvg(series,runs,{label='',changeLabel=()=>'',percent=v=>v}={}){
 const W=760,H=250,l=40,r=16,t=16,b=44,n=runs.length;
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,class:'drift-svg',role:'img','aria-label':label});
 const px=i=>n===1?(l+W-r)/2:l+i*(W-l-r)/(n-1),py=v=>t+(1-v)*(H-t-b);
 for(const f of [0,0.25,0.5,0.75,1]){svg.append(svgEl('line',{x1:l,x2:W-r,y1:py(f),y2:py(f),class:'grid-line'}),svgText(percent(f),{x:l-6,y:py(f)+4,class:'axis-label','text-anchor':'end'}));}
 runs.forEach((run,i)=>{
  const bad=run.changes.some(c=>c.tone==='bad'),good=run.changes.length&&!bad&&run.changes.some(c=>c.tone==='ok');
  if(run.changes.length){
   const band=svgEl('rect',{x:px(i)-9,y:t,width:18,height:H-t-b,class:'drift-band '+(bad?'bad':good?'ok':'info')},svgEl('title',{}));
   band.firstChild.textContent=changeLabel(run);svg.append(band);
  }
  if(n<=10||i%Math.ceil(n/10)===0||i===n-1)svg.append(svgText(String(i+1),{x:px(i),y:H-b+16,class:'axis-label','text-anchor':'middle'}));
 });
 series.forEach((s,k)=>{
  let segment=[];
  const flush=()=>{if(segment.length>1)svg.append(svgEl('polyline',{points:segment.join(' '),class:`drift-line s${k}`,fill:'none'}));segment=[];};
  s.values.forEach((v,i)=>{
   if(v===null){flush();return;}
   segment.push(`${px(i)},${py(v)}`);
   svg.append(svgEl('circle',{cx:px(i),cy:py(v),r:3.6,class:`drift-dot s${k}`},svgEl('title',{})));svg.lastChild.firstChild.textContent=`${s.label} · #${i+1}: ${percent(v)}`;
  });
  flush();
 });
 series.forEach((s,k)=>{const x=l+k*172;svg.append(svgEl('rect',{x,y:H-14,width:10,height:10,rx:2,class:`drift-key s${k}`}),svgText(s.label,{x:x+16,y:H-5,class:'axis-label'}));});
 return svg;
}
// Horizontal bars from real event timestamps; a bar's width is that step's measured span, never an estimate.
function timelineSvg(layout,{label='',names=a=>a,duration=ms=>ms+' ms',pointLabel='event'}={}){
 const W=760,rowH=30,l=170,r=70,t=22,H=t+layout.rows.length*rowH+24,span=layout.total;
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${H}`,class:'gantt-svg',role:'img','aria-label':label});
 const px=ms=>l+(ms/span)*(W-l-r);
 for(const f of [0,0.25,0.5,0.75,1]){svg.append(svgEl('line',{x1:px(span*f),x2:px(span*f),y1:t-6,y2:H-20,class:'grid-line'}),svgText(duration(span*f),{x:px(span*f),y:H-6,class:'axis-label','text-anchor':f===0?'start':f===1?'end':'middle'}));}
 layout.rows.forEach((row,i)=>{
  const y=t+i*rowH,w=Math.max(4,px(row.offset+row.duration)-px(row.offset));
  svg.append(svgText(names(row.agent),{x:l-10,y:y+15,class:'gantt-label','text-anchor':'end'}),
   svgEl('rect',{x:px(row.offset),y:y+3,width:w,height:16,rx:4,class:'gantt-bar '+row.state.toLowerCase()},svgEl('title',{})));
  svg.lastChild.firstChild.textContent=`${names(row.agent)}: +${duration(row.offset)}, ${row.duration?duration(row.duration):pointLabel}`;
  svg.append(svgText(row.duration?duration(row.duration):pointLabel,{x:Math.min(px(row.offset)+w+6,W-r+4),y:y+15,class:'gantt-value'}));
 });
 return svg;
}
if(typeof module!=='undefined')module.exports={FLOW_LAYOUT,flowPosition};
