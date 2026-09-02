(function(){
'use strict';
const $=id=>document.getElementById(id);
const PRESETS=MC.PRESETS, META=MC.META;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const hex=a=>Array.from(a).map(b=>b.toString(16).padStart(2,'0')).join('');

/* checksum FNV-1a em fluxo (nao carrega o arquivo inteiro) */
async function streamChecksum(file){
  let h=2166136261>>>0;const CH=1<<20;let off=0;
  while(off<file.size){
    const buf=new Uint8Array(await file.slice(off,Math.min(file.size,off+CH)).arrayBuffer());
    for(let i=0;i<buf.length;i++){h^=buf[i];h=Math.imul(h,16777619)>>>0;}
    off+=CH;
  }
  return h>>>0;
}

/* ---------- abas ---------- */
function tab(w){
  $('t-tx').classList.toggle('on',w==='tx');$('t-rx').classList.toggle('on',w==='rx');
  $('tx').classList.toggle('hide',w!=='tx');$('rx').classList.toggle('hide',w!=='rx');
  if(w==='tx')stopCam();
}
$('t-tx').onclick=()=>tab('tx');$('t-rx').onclick=()=>tab('rx');

/* ---------- presets ---------- */
PRESETS.forEach((p,i)=>{const o=document.createElement('option');o.value=i;
  o.textContent=`${p.name} — N${p.n}, ${p.cm===0?'P&B':p.cm+'-cor'} · ~${p.bytes} B/quadro`;
  $('preset').appendChild(o);});
$('preset').value=1;

/* ---------- TX ---------- */
let txRun=false;
function fmtMB(b){return b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(2)+' MB';}
function updateTxInfo(){
  const files=collectFiles();
  if(!files.length){$('txinfo').textContent='Escolha um arquivo ou pasta.';return;}
  const p=PRESETS[+$('preset').value];
  let total=0,size=0;
  for(const f of files){size+=f.file.size;total+=MC.framesFor(f.file.size,p.n,p.cm,p.nsym);}
  $('txinfo').innerHTML=`<span class="big">${files.length} arquivo(s)</span> · ${fmtMB(size)}<br>${total} quadro(s) no total · ~${p.bytes} B/quadro`;
}
let dropped=[];
function collectFiles(){
  const out=[];
  for(const f of dropped)out.push({name:f.name,path:f.webkitRelativePath||f.name,file:f});
  const ff=$('file').files; for(const f of ff)out.push({name:f.name,path:f.name,file:f});
  const df=$('folder').files;
  if(df&&df.length)for(const f of df)out.push({name:f.name,path:f.webkitRelativePath||f.name,file:f});
  return out;
}
$('file').onchange=()=>{$('folder').value='';updateTxInfo();capInfo();};
$('folder').onchange=()=>{$('file').value='';updateTxInfo();};
$('preset').onchange=updateTxInfo;

function drawFrame(R){
  const cv=$('cv'),s=R.side;cv.width=s;cv.height=s;
  const ctx=cv.getContext('2d'),id=ctx.createImageData(s,s);
  for(let i=0;i<s*s;i++){id.data[i*4]=R.img[i*3];id.data[i*4+1]=R.img[i*3+1];id.data[i*4+2]=R.img[i*3+2];id.data[i*4+3]=255;}
  ctx.putImageData(id,0,0);
}
$('start').onclick=async()=>{
  const files=collectFiles();
  if(!files.length){alert('Escolha um arquivo ou pasta primeiro.');return;}
  const p=PRESETS[+$('preset').value];
  $('txinfo').textContent='Preparando (checksum)…';
  // metadados + fileId por arquivo (checksum em fluxo)
  const items=[];
  for(const f of files){
    const sha=await streamChecksum(f.file);
    items.push({...f,sha,fileId:MC.fileId(f.path,f.file.size),total:MC.framesFor(f.file.size,p.n,p.cm,p.nsym)});
  }
  // lista de tarefas (leve): meta + quadros de cada arquivo
  const tasks=[];
  items.forEach((it,fi)=>{
    const meta=JSON.stringify({v:1,name:it.name,path:it.path,size:it.file.size,sha:it.sha,fi,tf:items.length});
    tasks.push({kind:'meta',it,meta});
    for(let i=0;i<it.total;i++)tasks.push({kind:'data',it,idx:i});
  });
  $('txview').classList.remove('hide');$('start').classList.add('hide');$('stop').classList.remove('hide');
  txRun=true;let k=0;
  const enc=new TextEncoder();
  while(txRun){
    const t=tasks[k%tasks.length];
    let R;
    if(t.kind==='meta'){
      R=MC.render(p,t.it.fileId,META,t.it.total,enc.encode(t.meta),6,4,t.it.name);
      $('txstat').innerHTML=`<b>${t.it.path}</b> · metadados`;
    }else{
      const off=t.idx*p.bytes,end=Math.min(t.it.file.size,off+p.bytes);
      const chunk=new Uint8Array(await t.it.file.slice(off,end).arrayBuffer());
      R=MC.render(p,t.it.fileId,t.idx,t.it.total,chunk,6,4,t.it.name);
      $('txstat').innerHTML=`<b>${t.it.path}</b> · quadro ${t.idx+1}/${t.it.total}`;
    }
    if(R)drawFrame(R);
    k++;await sleep(90);
  }
};
$('stop').onclick=()=>{txRun=false;$('start').classList.remove('hide');$('stop').classList.add('hide');};

/* ---------- Gerar PNG (P&B, varios blocos; resolucao configuravel) ---------- */
const sleep0=ms=>new Promise(r=>setTimeout(r,ms));
function fmtKB(b){return b<1048576?(b/1024).toFixed(1)+' KB':(b/1048576).toFixed(2)+' MB';}
function sheetLayout(px,W,H){const n=96,quiet=4,bp=(n+2*quiet)*px;
  return {n,cm:0,nsym:32,quiet,bp,W,H,cols:Math.max(1,Math.floor(W/bp)),rows:Math.max(1,Math.floor(H/bp)),
    get bpi(){return this.cols*this.rows;},cap:MC.dataMax(n,0,32)};}
function drawBlockTo(ctx,R,ox,oy){const s=R.side,tmp=document.createElement('canvas');tmp.width=s;tmp.height=s;
  const t=tmp.getContext('2d'),id=t.createImageData(s,s);
  for(let i=0;i<s*s;i++){id.data[i*4]=R.img[i*3];id.data[i*4+1]=R.img[i*3+1];id.data[i*4+2]=R.img[i*3+2];id.data[i*4+3]=255;}
  t.putImageData(id,0,0);ctx.drawImage(tmp,ox,oy);}
function exportSheet(cv,name){const url=cv.toDataURL('image/png');
  if(window.MegaCodeNative&&window.MegaCodeNative.saveFile){window.MegaCodeNative.saveFile(name,url);return 'salvo';}
  const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();return 'baixado';}
function readGenOpts(){const v=($('res')&&$('res').value)||'1920x1080';const p=v.split('x');
  return {px:+((($('dens')&&$('dens').value)||4)),W:+p[0],H:+p[1],
    single:!(!$('single')&&$('single').checked), grid:!(!$('grid')&&$('grid').checked)};}
async function gerarBig(f,W,H,single){
  const n=224,nsym=32,quiet=4,px=Math.max(1,Math.floor(Math.min(W,H)/(n+2*quiet)));
  const side=(n+2*quiet)*px,cap=MC.dataMax(n,0,nsym);
  const dataFrames=Math.max(1,Math.ceil(f.size/cap)),images=dataFrames;
  if(single&&dataFrames>1)return {tooBig:true,maxBytes:cap,images};
  const fid=MC.fileId(f.name,f.size),enc=new TextEncoder();
  const _ext=(n=>{const i=n.lastIndexOf('.');return i>0?n.slice(i+1):'';})(f.name);const meta=JSON.stringify({v:1,name:f.name,path:f.name,size:f.size,ext:_ext,fi:0,tf:1});
  const base=(f.name.replace(/\.[^.]+$/,'')||'arquivo');
  let first=null,modo='';
  const ox=Math.max(0,Math.floor((W-side)/2)),oy=Math.max(0,Math.floor((H-side)/2));
  for(let img=0;img<images;img++){
    const cv=document.createElement('canvas');cv.width=W;cv.height=H;
    const ctx=cv.getContext('2d');if(!ctx)throw new Error('resolução grande demais para o canvas');
    ctx.fillStyle='#fff';ctx.fillRect(0,0,W,H);let R;
    {const di=img,off=di*cap,end=Math.min(f.size,off+cap);
      const chunk=new Uint8Array(await f.slice(off,end).arrayBuffer());
      R=MC.render({n,cm:0,nsym},fid,di,dataFrames,chunk,px,quiet,f.name);}
    if(R)drawBlockTo(ctx,R,ox,oy);
    modo=exportSheet(cv,base+'_megacode_'+String(img).padStart(4,'0')+'.png');
    if(img===0)first=cv;
    $('txinfo').textContent='Gerando… '+(img+1)+'/'+images;
    await sleep0(30);
  }
  return {first,images,dataFrames,bpi:1,modo,W,H};
}
function capInfo(){if(!$('res'))return;const o=readGenOpts(),L=sheetLayout(o.px,o.W,o.H);
  const perImg=(L.bpi-1)*L.cap,f=$('file').files[0];let need='';
  if(f){const imgs=Math.ceil((1+Math.max(1,Math.ceil(f.size/L.cap)))/L.bpi);
    need=` · seu arquivo: <b>${imgs}</b> imagem(ns)`;}
  $('txinfo').innerHTML=`${o.W}×${o.H} · ${L.cols}×${L.rows} = <b>${L.bpi}</b> blocos/imagem · ~<b>${fmtKB(perImg)}</b> úteis por imagem${need}`;}
async function gerarPNG(f,px,W,H,single){
  const L=sheetLayout(px,W,H),fid=MC.fileId(f.name,f.size);
  const dataFrames=Math.max(1,Math.ceil(f.size/L.cap)),totalBlocks=1+dataFrames;
  const images=Math.ceil(totalBlocks/L.bpi);
  if(single&&images>1)return {tooBig:true,maxBytes:(L.bpi-1)*L.cap,images};
  const enc=new TextEncoder();
  const _ext=(n=>{const i=n.lastIndexOf('.');return i>0?n.slice(i+1):'';})(f.name);const meta=JSON.stringify({v:1,name:f.name,path:f.name,size:f.size,ext:_ext,fi:0,tf:1});
  const base=(f.name.replace(/\.[^.]+$/,'')||'arquivo');
  let first=null,modo='';
  for(let img=0;img<images;img++){
    const cv=document.createElement('canvas');cv.width=W;cv.height=H;
    const ctx=cv.getContext('2d');
    if(!ctx)throw new Error('resolução grande demais para o canvas deste dispositivo');
    ctx.fillStyle='#fff';ctx.fillRect(0,0,W,H);
    for(let b=0;b<L.bpi;b++){
      const gi=img*L.bpi+b;if(gi>=totalBlocks)break;
      const r=Math.floor(b/L.cols),c=b%L.cols,ox=c*L.bp,oy=r*L.bp;let R;
      if(gi===0)R=MC.render({n:L.n,cm:0,nsym:L.nsym},fid,MC.META,dataFrames,enc.encode(meta),px,L.quiet,f.name);
      else{const di=gi-1,off=di*L.cap,end=Math.min(f.size,off+L.cap);
        const chunk=new Uint8Array(await f.slice(off,end).arrayBuffer());
        R=MC.render({n:L.n,cm:0,nsym:L.nsym},fid,di,dataFrames,chunk,px,L.quiet,f.name);}
      if(R)drawBlockTo(ctx,R,ox,oy);
    }
    modo=exportSheet(cv,base+'_megacode_'+String(img).padStart(4,'0')+'.png');
    if(img===0)first=cv;
    $('txinfo').textContent='Gerando… '+(img+1)+'/'+images;
    await sleep0(30);
  }
  return {first,images,dataFrames,bpi:L.bpi,modo,W,H};
}
let lastGen=null;
$('genpng').onclick=async()=>{
  const items=collectFiles();
  if(!items.length){alert('Escolha um arquivo ou uma pasta.');return;}
  const o=readGenOpts();lastGen={items,o};
  let totImg=0,firstCv=null,tooBig=null,err=null;
  for(let idx=0;idx<items.length;idx++){
    const f=items[idx].file;
    $('txinfo').textContent='Gerando '+(idx+1)+'/'+items.length+': '+items[idx].name+' ('+o.W+'\u00d7'+o.H+(o.grid?' grade':' 1 c\u00f3digo')+')\u2026';
    try{
      const r=o.grid?await gerarPNG(f,o.px,o.W,o.H,o.single):await gerarBig(f,o.W,o.H,o.single);
      if(r.tooBig){tooBig=r;continue;}
      totImg+=r.images; if(!firstCv&&r.first)firstCv=r.first;
    }catch(e){err=e;}
  }
  if(err){$('txinfo').textContent='Erro: '+err.message;return;}
  if(!totImg&&tooBig){$('txinfo').innerHTML=`<b>N\u00e3o cabe em 1 imagem</b>: cabem ~${fmtKB(tooBig.maxBytes)}, mas precisa de ${tooBig.images} imagens.<br>Desmarque \u201cimagem \u00fanica\u201d, ou aumente a resolu\u00e7\u00e3o/densidade.`;return;}
  if(firstCv){const pv=$('cv');const sc=Math.min(1,1280/o.W);pv.width=Math.max(1,Math.round(o.W*sc));pv.height=Math.max(1,Math.round(o.H*sc));pv.getContext('2d').drawImage(firstCv,0,0,pv.width,pv.height);$('txview').classList.remove('hide');}
  $('dlpng').classList.remove('hide');
  $('txinfo').innerHTML=`<b>${items.length}</b> arquivo(s) \u00b7 <b>${totImg}</b> imagem(ns) P&B geradas (${o.grid?'grade':'1 c\u00f3digo grande'}).<br>Para ler: aba Receber > Ler PNG/imagem (ou c\u00e2mera).`;
};
$('dlpng').onclick=()=>{if(lastGen){const{items,o}=lastGen;for(const it of items){o.grid?gerarPNG(it.file,o.px,o.W,o.H,o.single):gerarBig(it.file,o.W,o.H,o.single);}}};
if($('res'))$('res').onchange=capInfo;
if($('dens'))$('dens').onchange=capInfo;
if($('single'))$('single').onchange=capInfo;

/* ---------- Drag & drop (varios arquivos) ---------- */
function wireDrop(){
  const el=$('drop'); if(!el)return;
  const act=e=>{e.preventDefault();e.stopPropagation();};
  ['dragover','dragenter'].forEach(ev=>el.addEventListener(ev,e=>{act(e);el.style.background='#24405f';el.style.color='#fff';}));
  ['dragleave','dragend'].forEach(ev=>el.addEventListener(ev,e=>{act(e);el.style.background='';el.style.color='';}));
  el.addEventListener('drop',e=>{act(e);el.style.background='';el.style.color='';
    dropped=Array.from(e.dataTransfer.files);
    if(dropped.length){if($('file'))$('file').value='';if($('folder'))$('folder').value='';updateTxInfo();if(typeof capInfo==='function')capInfo();}});
}
/* ---------- RX ---------- */
let stream=null,rxLoop=null;
const rx=new Map(); // fileIdHex -> {meta,parts,total,got,done,out}
function rxProgress(){
  let got=0,total=0;
  for(const e of rx.values()){got+=e.got;total+=e.total;}
  const pct=total?Math.round(got/total*100):0;
  $('rxbar').style.width=pct+'%';
  return {got,total,pct};
}
function onFrame(D){
  const inf=D.info,key=hex(inf.fileId);
  let e=rx.get(key);
  if(inf.frameIndex===META){
    let meta=null;try{meta=JSON.parse(new TextDecoder().decode(D.data));}catch(_){}
    if(!meta)return;
    if(!e){e={meta,parts:[],total:Math.max(1,Math.ceil(meta.size/1)),got:0,done:false};rx.set(key,e);}
    e.meta=meta; if(inf.name)e.hname=inf.name;
    const p=PRESETS.find(x=>x.n===inf.n&&x.cm===inf.cm&&x.nsym===inf.nsym)||PRESETS[1];
    e.total=Math.max(1,Math.ceil(meta.size/p.bytes));
    if(e.parts.length<e.total){const np=new Array(e.total).fill(null);for(let i=0;i<e.parts.length;i++)np[i]=e.parts[i];e.parts=np;}
    e.got=e.parts.filter(x=>x!==null).length;
    refresh();return;
  }
  if(!e){e={meta:null,parts:[],total:inf.totalFrames,got:0,done:false};rx.set(key,e);}
  if(inf.name&&!e.hname)e.hname=inf.name;
  if(inf.totalFrames>e.total)e.total=inf.totalFrames;
  if(e.parts.length<e.total){const np=new Array(e.total).fill(null);for(let i=0;i<e.parts.length;i++)np[i]=e.parts[i];e.parts=np;}
  if(e.parts[inf.frameIndex]===null){e.parts[inf.frameIndex]=D.data;e.got++;}
  if(e.total>0&&e.got>=e.total&&!e.done){e.done=true;assemble(e);}
  refresh();
}
function refresh(){
  const {got,total,pct}=rxProgress();
  let doneN=0;for(const e of rx.values())if(e.done)doneN++;
  $('rxstat').innerHTML=`Recebido: ${got}/${total} quadros (${pct}%) · ${doneN} arquivo(s) completo(s)`;
  if(doneN>0)$('save').classList.remove('hide');
}
function assemble(e){
  let size=0;for(let i=0;i<e.total;i++)if(e.parts[i])size+=e.parts[i].length;
  const out=new Uint8Array(size);let w=0;
  for(let i=0;i<e.total;i++){if(e.parts[i]){out.set(e.parts[i],w);w+=e.parts[i].length;}}
  e.out=out;
}
$('cam').onclick=async()=>{
  try{
    stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
    const v=$('vid');v.srcObject=stream;await v.play();v.classList.remove('hide');
    const rc=$('rcv'),ctx=rc.getContext('2d',{willReadFrequently:true});
    const tick=()=>{
      if(v.readyState>=2&&v.videoWidth){
        const w=v.videoWidth,h=v.videoWidth? v.videoHeight:1;
        const sc=Math.min(1,720/Math.max(w,h)),cw=Math.round(w*sc),ch=Math.round(h*sc);
        rc.width=cw;rc.height=ch;ctx.drawImage(v,0,0,cw,ch);
        const R=MC.decodeMulti(ctx.getImageData(0,0,cw,ch).data,cw,ch);
        if(R&&R.ok)for(const D of R.frames)onFrame(D);
      }
      rxLoop=requestAnimationFrame(tick);
    };
    tick();
  }catch(err){$('rxstat').textContent='Erro na câmera: '+err.message;}
};
function stopCam(){if(rxLoop){cancelAnimationFrame(rxLoop);rxLoop=null;}
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}$('vid').classList.add('hide');}
$('imp').onclick=()=>$('impfile').click();
$('impfile').onchange=ev=>{
  const files=Array.from(ev.target.files); if(!files.length)return;
  let done=0,totBlocks=0;
  const finish=()=>{done++;
    if(done===files.length){
      const {pct}=rxProgress();
      $('rxstat').innerHTML=`${files.length} imagem(ns) lida(s): ${totBlocks} bloco(s) novos · progresso total ${pct}%.`+
        (pct<100?' Importe as próximas imagens (ou use a câmera).':'');
    }};
  for(const f of files){
    const fr=new FileReader();
    fr.onload=()=>{
      const img=new Image();
      img.onload=()=>{
        const cv=$('rcv');cv.width=img.width;cv.height=img.height;
        const ctx=cv.getContext('2d',{willReadFrequently:true});
        ctx.drawImage(img,0,0);
        let R=null;try{R=MC.decodeMulti(ctx.getImageData(0,0,img.width,img.height).data,img.width,img.height);}catch(e){}
        if(R&&R.ok){for(const D of R.frames)onFrame(D);totBlocks+=R.frames.length;}
        finish();
      };
      img.onerror=finish;
      img.src=fr.result; // data: URL nao contamina o canvas (funciona em file://)
    };
    fr.readAsDataURL(f);
  }
  ev.target.value='';
};
$('save').onclick=()=>{
  let n=0;
  for(const e of rx.values()){
    if(!e.done||!e.out)continue;
    const name=(e.meta&&(e.meta.name||e.meta.path))||e.hname||('megacode'+n+'.bin');
    if(window.MegaCodeNative&&window.MegaCodeNative.saveFile){
      let bin='';const CH=0x8000;
      for(let i=0;i<e.out.length;i+=CH)bin+=String.fromCharCode.apply(null,e.out.subarray(i,i+CH));
      window.MegaCodeNative.saveFile(name,btoa(bin));
    }else{
      const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([e.out],{type:'application/octet-stream'}));
      a.download=name;document.body.appendChild(a);a.click();a.remove();
    }
    n++;
  }
  $('rxstat').innerHTML=n?`Salvo ${n} arquivo(s).`:'Nada completo para salvar.';
};
wireDrop();
})();


