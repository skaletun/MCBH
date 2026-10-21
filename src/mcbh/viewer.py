"""Standalone dependency-free interactive isometric builder guide export.

Visual output approximates voxel colors and is not a true Minecraft renderer.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from .structures import _runs, _root_dir, NBTError, materials


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MCBH • Independent Interactive Build Guide</title>
<style>
:root{font-family:Inter,Arial,sans-serif; color-scheme:dark;background:#111820;color:#eaf0ed}
*{box-sizing:border-box}body{margin:0}header{display:flex;justify-content:space-between;align-items:center;padding:12px 20px;background:#192631;border-bottom:1px solid #34434f;gap:14px;flex-wrap:wrap}
h1{font-size:19px;margin:0}small,.muted{color:#9eb0b6}button,input,select{font:inherit}button,select{background:#253540;color:#f3f6f3;border:1px solid #4b626e;padding:8px 12px;border-radius:8px;cursor:pointer}button:hover{background:#344854}button:focus-visible,input:focus-visible{outline:2px solid #e0a76c}
main{display:grid;grid-template-columns:minmax(0,1fr) 340px;min-height:calc(100vh - 61px)}.display{min-width:0;display:flex;flex-direction:column}canvas{display:block;width:100%;height:calc(100vh - 231px);min-height:350px;cursor:grab;touch-action:none;background:#0d1420}canvas:active{cursor:grabbing}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 16px;border-top:1px solid #31414b;background:#19242f}.controls label{display:inline-flex;align-items:center;gap:6px;font-size:13px}.controls input[type=range]{width:120px}.controls input[type=color]{border:0;width:28px;height:30px;padding:0;background:none}
.sidebar{border-left:1px solid #344450;background:#18232d;padding:16px;overflow:auto;max-height:calc(100vh - 62px)}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px}.tabs button{padding:8px;flex:1}section{padding:15px 0;border-bottom:1px solid #35444e}h2{font-size:15px;margin:0 0 10px}p{font-size:13px;line-height:1.55}#stepText{font-size:15px;min-height:68px;white-space:pre-line}#stepSelect{width:100%}#layerSlider{width:100%}.mat{display:flex;gap:10px;padding:8px 0;align-items:center;border-bottom:1px solid #253742}.mat input{width:18px;height:18px}.mat .sw{width:17px;height:17px;border-radius:4px;flex:none}.mat strong{display:block;font-size:12px;overflow-wrap:anywhere}.mat small{font-size:11px}.info{font-size:12px;color:#9bb2b2}.chip{padding:3px 7px;border:1px solid #526777;border-radius:10px;font-size:12px}
@media(max-width:850px){main{grid-template-columns:1fr}.sidebar{max-height:none;border-left:0;border-top:1px solid #344450}canvas{height:55vh;min-height:320px}}
</style></head><body>
<header><div><h1>MCBH / GUIDED BUILD</h1><small id="filename"></small></div><div><span class="chip" id="dims"></span> <span class="chip" id="percent"></span></div></header>
<main><div class="display"><canvas id="canvas" aria-label="Interactive isometric voxel model"></canvas>
<div class="controls"><button id="rotL" title="Rotate left">↶ Rotate</button><button id="rotR" title="Rotate right">Rotate ↷</button>
<button id="fit">Reset view</button><button id="focus">Focus step</button>
<label><input id="grid" type="checkbox" checked> Grid</label><label><input id="wire" type="checkbox" checked> Wireframe</label>
<label>Wire <input id="wireColor" type="color" value="#ffd36b"></label><label>Canvas <input id="bgColor" type="color" value="#0d1420"></label>
<label><input id="all" type="checkbox" checked> Ghost upcoming</label><label><input id="measure" type="checkbox"> Measure</label>
<label>Zoom <input id="zoom" type="range" min="5" max="32" value="14"></label></div>
<div class="controls"><button id="prev">← Previous</button><input id="stepSelect" type="range" min="0" max="0" value="0" style="flex:1;width:100px"><button id="next">Next →</button><button id="preview">Toggle preview</button></div>
</div><aside class="sidebar"><div class="tabs"><button id="survival">Survival</button><button id="creative">Creative</button></div>
<section><h2>Build instruction</h2><div id="stepText"></div><p class="info">One adjacent X-run of the same block is one step, ordered bottom-up. Validate falling blocks and wall attachments.</p></section>
<section><h2>Layers</h2><label>Maximum shown Y <strong id="layerLabel"></strong><input type="range" id="layerSlider" min="0" value="0"></label><p class="info">Move slider to isolate a floor or inspect roof stages. The world uses X→east, Z→south, Y→up.</p></section>
<section><h2>Materials checklist</h2><div id="materials"></div></section>
<section><h2>Measure</h2><div id="dist" class="info">Enable Measure and click two visible top faces for ΔX, ΔY, ΔZ and straight-line distance.</div></section>
<section><h2>Important limitations</h2><p class="info">Independently authored MCBH tool inspired by public construction-guide workflows. Schematic states are exact, but colors and geometry drawn by this compact isometric canvas are approximate, not Minecraft textures. Entities/block-entity NBT are not reconstructed. Local progress is stored in your browser when available. No connection to Brictora.</p></section>
</aside></main>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
"use strict";
const model=JSON.parse(document.getElementById('payload').textContent);
const voxels=model.voxels, runs=model.runs, size=model.size;
const $=id=>document.getElementById(id);
const canvas=$('canvas'),ctx=canvas.getContext('2d');
let yaw=0,zoom=14,step=0,maxLayer=size[1]-1,ghost=true,measure=false,grid=true,wire=true,preview=false,mode='survival',pan=[0,0];
let drag=null, picks=[],hitRegions=[];
let completed=new Set();
try{const saved=JSON.parse(localStorage.getItem('mcbh:'+model.digest)||'{}');step=Math.max(0,Math.min(runs.length,saved.step||0));completed=new Set(saved.checked||[])}catch(e){}
function persist(){try{localStorage.setItem('mcbh:'+model.digest,JSON.stringify({step,checked:[...completed]}))}catch(e){}}
function color(s){let h=2166136261;for(const ch of s)h=Math.imul(h^ch.charCodeAt(0),16777619);h=h>>>0;const hue=h%360;const sat=22+(h>>8)%22;const light=38+(h>>16)%22;return `hsl(${hue},${sat}%,${light}%)`}
function bodyColors(id){if(id.includes('oak')||id.includes('spruce')||id.includes('planks')||id.includes('wood'))return ['#76543c','#a4774f','#4d352b'];if(id.includes('stone')||id.includes('tuff')||id.includes('andesite')||id.includes('deepslate'))return ['#777e7c','#a2a7a0','#535956'];if(id.includes('grass')||id.includes('leaves')||id.includes('moss'))return ['#5b8749','#8aa666','#3f6039'];if(id.includes('sand'))return ['#c7b58a','#e5d4a6','#9b896c'];if(id.includes('glass'))return ['#578899','#8cb7c0','#3d6474'];const c=color(id);return [c,c,c]}
function rotate(x,z){switch(yaw){case 1:return [size[2]-1-z,x];case 2:return [size[0]-1-x,size[2]-1-z];case 3:return [z,size[0]-1-x];default:return [x,z]}}
function path(points,fill,stroke){ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);for(let i=1;i<points.length;i++)ctx.lineTo(points[i][0],points[i][1]);ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.7;ctx.stroke()}}
function project(x,y,z,ox,oy){const w=zoom,depth=zoom*.45,h=zoom*.9;return [ox+(x-z)*w,oy+(x+z)*depth-y*h]}
function polyHit(poly,x,y){let yes=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>y)!=(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])yes=!yes}return yes}
function render(){const dpr=window.devicePixelRatio||1;const W=canvas.clientWidth,H=canvas.clientHeight;
if(canvas.width!=Math.floor(W*dpr)||canvas.height!=Math.floor(H*dpr)){canvas.width=Math.floor(W*dpr);canvas.height=Math.floor(H*dpr)}
ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle=$('bgColor').value;ctx.fillRect(0,0,W,H);
const halfX=(yaw%2?size[2]:size[0])/2,halfZ=(yaw%2?size[0]:size[2])/2;
let ox=W/2+(halfZ-halfX)*zoom+pan[0],oy=H/2-(halfX+halfZ)*zoom*.45+Math.floor(size[1]*.5)*zoom*.85+pan[1];
if(grid){ctx.strokeStyle='#586d7a55';ctx.lineWidth=.7;const a=0,b=(yaw%2?size[2]:size[0]),c=(yaw%2?size[0]:size[2]);for(let x=0;x<=b;x++){let p=project(x,0,0,ox,oy),q=project(x,0,c,ox,oy);ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.stroke()}for(let z=0;z<=c;z++){let p=project(0,0,z,ox,oy),q=project(b,0,z,ox,oy);ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.stroke()}}
let visible=voxels.filter(v=>v[1]<=maxLayer&&(ghost||v[4]<=step));let dropped=0;if(visible.length>20000){dropped=visible.length-20000;visible=visible.slice(0,20000)}
visible.sort((a,b)=>{let A=rotate(a[0],a[2]),B=rotate(b[0],b[2]);return (A[0]+A[1]+a[1])-(B[0]+B[1]+b[1])});
hitRegions=[];for(const v of visible){const [x,y,z,state,rank]=v,[rx,rz]=rotate(x,z);const [px,py]=project(rx,y,rz,ox,oy),w=zoom,h=zoom*.9,d=zoom*.45;let top=[[px,py],[px+w,py+d],[px,py+2*d],[px-w,py+d]];
let left=[[px-w,py+d],[px,py+2*d],[px,py+2*d+h],[px-w,py+d+h]],right=[[px+w,py+d],[px,py+2*d],[px,py+2*d+h],[px+w,py+d+h]];
const colors=bodyColors(state),opacity=rank>step?.19:1;ctx.globalAlpha=opacity;
const line=wire?$('wireColor').value+'88':null;path(left,colors[2],line);path(right,colors[0],line);path(top,rank==step?'#f3c474':colors[1],rank==step?'#ffe6a8':line);ctx.globalAlpha=1;
if(measure)hitRegions.push({poly:top,at:[x,y,z]});}
if(dropped){ctx.fillStyle='#f4c785';ctx.font='13px Arial';ctx.fillText('Display cap: '+dropped+' blocks omitted (export and totals remain exact)',15,H-20)}
$('percent').textContent=(runs.length?Math.round(step/runs.length*100):0)+'% complete';$('dims').textContent=size.join(' × ')+' blocks';
}
function update(){step=Math.max(0,Math.min(runs.length,step));$('stepSelect').max=runs.length;$('stepSelect').value=step;$('layerSlider').max=size[1]-1;$('layerSlider').value=maxLayer;$('layerLabel').textContent=maxLayer;
let r=runs[Math.max(0,step-1)];$('stepText').textContent=step===0?'Ready to begin. Navigate forward to the first group.':r?`Step ${step} / ${runs.length}\n${r.block} × ${r.count}\nFrom (${r.x_from},${r.y},${r.z}) to (${r.x_to},${r.y},${r.z})`:'Empty structure';
persist();render()}
$('filename').textContent=model.filename+' — '+model.format;
$('rotL').onclick=()=>{yaw=(yaw+3)%4;render()};$('rotR').onclick=()=>{yaw=(yaw+1)%4;render()};
$('fit').onclick=()=>{zoom=14;pan=[0,0];$('zoom').value=zoom;render()};
$('focus').onclick=()=>{const r=runs[Math.max(0,step-1)];if(r){let mid=rotate((r.x_from+r.x_to)/2,r.z);pan=[(size[0]/2-mid[0]+mid[1]-size[2]/2)*zoom,(mid[0]+mid[1]-size[0]/2-size[2]/2)*zoom*.4+(r.y-size[1]/2)*zoom*.85];render()}};
$('prev').onclick=()=>{step--;update()};$('next').onclick=()=>{step++;update()};$('stepSelect').oninput=e=>{step=+e.target.value;update()};
$('layerSlider').oninput=e=>{maxLayer=+e.target.value;update()};
$('all').onchange=e=>{ghost=e.target.checked;render()};$('grid').onchange=e=>{grid=e.target.checked;render()};$('wire').onchange=e=>{wire=e.target.checked;render()};$('measure').onchange=e=>{measure=e.target.checked;picks=[];render()};
$('wireColor').oninput=render;$('bgColor').oninput=render;$('zoom').oninput=e=>{zoom=+e.target.value;render()};
$('preview').onclick=()=>{preview=!preview;ghost=preview;$('all').checked=ghost;render()};
$('survival').onclick=()=>{mode='survival';$('survival').style.borderColor='#edbb78';$('creative').style.borderColor='';};$('creative').onclick=()=>{mode='creative';$('creative').style.borderColor='#edbb78';$('survival').style.borderColor='';};$('survival').click();
for(const entry of model.materials){const row=document.createElement('label');row.className='mat';const check=document.createElement('input');check.type='checkbox';check.checked=completed.has(entry.block);check.onchange=()=>{check.checked?completed.add(entry.block):completed.delete(entry.block);persist()};
const sw=document.createElement('span');sw.className='sw';sw.style.background=bodyColors(entry.block)[0];const box=document.createElement('span');const title=document.createElement('strong');title.textContent=entry.block;const sub=document.createElement('small');sub.textContent=`${entry.count} blocks = ${entry.stacks} stacks + ${entry.remainder}`;box.append(title,sub);row.append(check,sw,box);$('materials').append(row)}
canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,pan:[...pan],moved:false};canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>5)drag.moved=true;pan=[drag.pan[0]+dx,drag.pan[1]+dy];render()}};
canvas.onpointerup=e=>{if(drag&&!drag.moved&&measure){const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;for(let k=hitRegions.length-1;k>=0;k--){if(polyHit(hitRegions[k].poly,x,y)){picks.push(hitRegions[k].at);if(picks.length>2)picks.shift();if(picks.length===2){const d=picks[0].map((v,i)=>Math.abs(v-picks[1][i]));$('dist').textContent=`Point A: ${picks[0]} / Point B: ${picks[1]} • ΔX=${d[0]} ΔY=${d[1]} ΔZ=${d[2]} • distance=${Math.hypot(...d).toFixed(2)}`;}else $('dist').textContent='First point: '+picks[0]+'. Select second top face.';break}}}drag=null};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.min(32,Math.max(5,zoom-(e.deltaY>0?1:-1)));$('zoom').value=zoom;render()},{passive:false});window.addEventListener('resize',render);update();
</script></body></html>'''


def export_viewer(structure:dict, filename:str='mcbh-guide.html')->dict:
    if not isinstance(filename,str) or not re.fullmatch(r'[a-z0-9_-]{1,90}\.html',filename):
        raise NBTError('Viewer filename must be a simple .html basename')
    root=_root_dir('MCBH_EXPORT_DIR','exports');root.mkdir(parents=True,exist_ok=True)
    dst=(root/filename).resolve()
    if not dst.is_relative_to(root):
        raise NBTError('Invalid viewer export path')
    runs=_runs(structure)
    seq=[];prev=None;rank=0
    for item in structure['blocks']:
        x,y,z,state=item
        if prev is None or not (prev[1]==y and prev[2]==z and prev[3]==state and prev[0]+1==x):
            rank+=1
        seq.append([x,y,z,state,rank]);prev=item
    payload={'voxels':seq,'runs':runs,'size':structure['size'],'digest':structure['id'],
             'filename':structure['name'],'format':structure['format'],'materials':materials(structure)}
    encoded=json.dumps(payload,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    page=PAGE.replace('__PAYLOAD__',encoded)
    fd,tmp=tempfile.mkstemp(dir=root,prefix='.viewer-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as file:
            file.write(page);file.flush();os.fsync(file.fileno())
        os.replace(tmp,dst)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {'file':str(dst),'size_bytes':dst.stat().st_size,'layers':structure['size'][1],
            'steps':len(runs),'features':['offline isometric model','orbit 90 degrees','pan/zoom','step navigation','layers','materials checklist','progress memory','wireframe and canvas colors','point-to-point measurements'],
            'warning':'Offline instructional renderer is not texture-accurate, nor a pixel-for-pixel clone of another service.'}
