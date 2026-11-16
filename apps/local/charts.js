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
 const svg=svgEl('svg',{viewBox:'0 0 1240 250',class:'flow-svg',role:'img','aria-label':options.label||'Capability graph','preserveAspectRatio':'xMidYMid meet'});
 const defs=svgEl('defs',{},svgEl('marker',{id:'flow-arrow',viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'7',markerHeight:'7',orient:'auto-start-reverse'},svgEl('path',{d:'M0 0 10 5 0 10z',class:'flow-arrowhead'})));
 svg.append(defs);
 const byId=Object.fromEntries(nodes.map(n=>[n.id,n]));
 const edges=svgEl('g',{class:'flow-edges'});
 for(const node of nodes){
  for(const dep of node.depends_on){
   const from=flowPosition(dep),to=flowPosition(node.id);
   const x1=from.x+NODE_W,y1=from.y+NODE_H/2,x2=to.x,y2=to.y+NODE_H/2,dx=Math.max(30,(x2-x1)/2);
   const live=byId[dep].state==='completed'&&node.state==='completed';
   const muted=['skipped','unavailable','disabled','rejected'].includes(node.state);
   edges.append(svgEl('path',{d:`M${x1} ${y1} C${x1+dx} ${y1} ${x2-dx} ${y2} ${x2-2} ${y2}`,class:'flow-edge'+(live?' live':muted?' muted':''),'marker-end':'url(#flow-arrow)'}));
  }
 }
 svg.append(edges);
 for(const node of nodes){
  const {x,y}=flowPosition(node.id);
  const g=svgEl('g',{class:`flow-node ${node.state}`,transform:`translate(${x} ${y})`});
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
if(typeof module!=='undefined')module.exports={FLOW_LAYOUT,flowPosition};
