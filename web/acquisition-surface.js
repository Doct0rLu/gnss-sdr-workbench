const defaultAcquisitionView = {yaw:-0.57,elevation:0.50};
let acquisitionView = {...defaultAcquisitionView};

function drawAcquisitionSurface(canvas, frame) {
 const surface = frame.surface;
 const values = surface.values;
 const rows = values.length, cols = values[0].length;
 const peak = Math.max(frame.peak, 1e-30);
 const ctx = canvas.getContext('2d');
 const w = 960, h = 520;
 const ratio = Math.min(window.devicePixelRatio || 1, 2);
 canvas.width = w * ratio; canvas.height = h * ratio;
 ctx.scale(ratio, ratio);
 ctx.fillStyle = '#f7fbfc'; ctx.fillRect(0,0,w,h);

 const {yaw,elevation} = acquisitionView;
 const sin = Math.sin(yaw), cos = Math.cos(yaw);
 const depthScale=Math.min(Math.sin(elevation),114/(305*Math.abs(sin)+220*Math.abs(cos)));
 const project = (x,y,z) => {
   const xWorld=(x-.5)*610, yWorld=(y-.5)*440;
   const depth=xWorld*sin+yWorld*cos;
   return [w/2+(xWorld*cos-yWorld*sin), 335-depth*depthScale-z*228*Math.cos(elevation),depth];
 };
 function line(a,b,color,width=1) {
   ctx.strokeStyle=color;ctx.lineWidth=width;
   ctx.beginPath();ctx.moveTo(...a.slice(0,2));ctx.lineTo(...b.slice(0,2));ctx.stroke();
 }
 function label(point,text,align='left',dx=0,dy=0,color='#466371') {
   ctx.fillStyle=color;ctx.textAlign=align;
   ctx.fillText(text,point[0]+dx,point[1]+dy);
 }
 const floorColor='#d3e2e8', axisColor='#456675';
 for(let k=0;k<=4;k++){
   const v=k/4;
   line(project(v,0,0),project(v,1,0),floorColor);
   line(project(0,v,0),project(1,v,0),floorColor);
   if(k)line(project(0,1,v),project(1,1,v),floorColor);
 }
 const nodes=values.map((row,y)=>row.map((z,x)=>project(cols===1?.5:(x+.5)/cols,rows===1?.5:(y+.5)/rows,z/peak)));
 const faces=[];
 for(let y=0;y<rows-1;y++){
   for(let x=0;x<cols-1;x++){
     const points=[nodes[y][x],nodes[y][x+1],nodes[y+1][x+1],nodes[y+1][x]];
     const tallest=Math.max(values[y][x],values[y][x+1],values[y+1][x],values[y+1][x+1])/peak;
     faces.push({points,depth:points[0][2]+points[2][2],tallest});
   }
 }
 faces.sort((a,b)=>b.depth-a.depth);
 for(const {points,tallest} of faces){
   ctx.beginPath();
   points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
   ctx.closePath();
   const intensity=Math.sqrt(tallest);
   ctx.fillStyle=`hsl(${182-153*intensity} 59% ${79-30*intensity}%)`;
   ctx.fill();
   ctx.strokeStyle='#22566c30';ctx.lineWidth=.45;ctx.stroke();
 }
 if(!faces.length){
   const strip=rows===1?nodes[0]:nodes.map(row=>row[0]);
   for(let i=1;i<strip.length;i++)line(strip[i-1],strip[i],'#087f75',2);
 }
 const origin=project(0,0,0);
 line(origin,project(1,0,0),axisColor,1.6);
 line(origin,project(0,1,0),axisColor,1.6);
 line(origin,project(0,0,1),axisColor,1.6);
 ctx.font="14px Consolas, monospace";
 for(let k=0;k<=4;k++){
   const v=k/4, hz=frame.dopplers[0]+v*(frame.dopplers.at(-1)-frame.dopplers[0]);
   label(project(v,0,0),String(Number((v*surface.period_ms).toFixed(3))),'center',0,20);
   label(project(0,v,0),String(Math.round(hz)),'right',-10,4);
   if(k)label(project(0,0,v),(frame.peak*v).toExponential(1),'right',-10,3);
 }
 ctx.font="bold 15px 'Segoe UI','Microsoft YaHei',sans-serif";
 label(project(.61,0,0),'码相位（ms）','center',5,42);
 label(project(0,1,0),'多普勒（Hz）','right',-14,-23);
 label(project(0,0,1),'相关功率（Metric）','center',0,-13);
 const marker=nodes[surface.peak_row][surface.peak_col];
 ctx.beginPath();ctx.arc(marker[0],marker[1],5,0,Math.PI*2);
 ctx.fillStyle='#fff';ctx.fill();ctx.strokeStyle='#a14a14';ctx.lineWidth=2;ctx.stroke();
 label(marker,'峰值','left',10,-5,'#813d19');
}

function bindAcquisitionSurface(canvas, frame, reset) {
 const draw = ()=>drawAcquisitionSurface(canvas, frame);
 function rotate(dx,dy){
   acquisitionView.yaw=Math.max(-1.04,Math.min(-.15,acquisitionView.yaw+dx));
   acquisitionView.elevation=Math.max(.34,Math.min(.83,acquisitionView.elevation+dy));
   draw();
 }
 let drag=null;
 canvas.onpointerdown=e=>{
   if(e.button!==0)return;
   drag=[e.clientX,e.clientY];
   canvas.setPointerCapture(e.pointerId);
 };
 canvas.onpointermove=e=>{
   if(!drag)return;
   rotate((e.clientX-drag[0])/180,(e.clientY-drag[1])/220);
   drag=[e.clientX,e.clientY];
 };
 canvas.onlostpointercapture=()=>{drag=null;};
 canvas.onkeydown=e=>{
   const change={ArrowLeft:[-.06,0],ArrowRight:[.06,0],ArrowUp:[0,.06],ArrowDown:[0,-.06]}[e.key];
   if(change){e.preventDefault();rotate(...change);}
 };
 reset.onclick=()=>{acquisitionView={...defaultAcquisitionView};draw();};
 draw();
}
