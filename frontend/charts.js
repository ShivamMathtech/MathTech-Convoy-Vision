/** Offline Canvas charts. Data comes exclusively from persisted/inferred outputs. */
export const colors={truck:'#f44b5b',car:'#4291ff',bus:'#24d3a2',motorcycle:'#f6b13c',bicycle:'#ad75ff'};
export function chart(canvas,series,{max=1,format=y=>y.toFixed(1),xLabel='Frame',empty='No analyzed samples yet'}={}){
  const box=canvas.getBoundingClientRect();if(!box.width||!box.height)return;
  const ratio=window.devicePixelRatio||1,w=box.width,h=box.height;
  canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
  const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,w,h);
  const pad={left:31,right:10,top:10,bottom:27},pw=w-pad.left-pad.right,ph=h-pad.top-pad.bottom;
  ctx.font='9px Segoe UI, sans-serif';ctx.lineWidth=1;ctx.textAlign='right';ctx.fillStyle='#86a5c5';
  for(let i=0;i<=4;i++){
    const y=pad.top+ph*i/4;ctx.strokeStyle='#173149';ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();
    ctx.fillText(format(max*(1-i/4)),pad.left-5,y+3);
  }
  const values=series.flatMap(s=>s.data),xs=values.map(p=>p[0]);
  const xmin=xs.length?Math.min(...xs):0,xmax=xs.length?Math.max(...xs):1,span=Math.max(1,xmax-xmin);
  ctx.textAlign='center';for(let i=0;i<4;i++){const x=pad.left+pw*i/3;ctx.fillText(String(Math.round(xmin+span*i/3)),x,h-14)}
  ctx.fillStyle='#577a9b';ctx.fillText(xLabel,pad.left+pw/2,h-2);
  if(!values.length){ctx.fillStyle='#728dab';ctx.fillText(empty,pad.left+pw/2,pad.top+ph/2);return}
  for(const s of series){
    if(!s.data.length)continue;ctx.strokeStyle=s.color;ctx.lineWidth=1.6;ctx.beginPath();
    s.data.forEach(([x,y],i)=>{const px=pad.left+(x-xmin)/span*pw,py=pad.top+(1-Math.min(max,Math.max(0,y))/max)*ph;i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();
    const [x,y]=s.data.at(-1);ctx.beginPath();ctx.arc(pad.left+(x-xmin)/span*pw,pad.top+(1-y/max)*ph,2.3,0,Math.PI*2);ctx.fillStyle=s.color;ctx.fill();
  }
}

