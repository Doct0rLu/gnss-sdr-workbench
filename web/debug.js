let eventWindow=null;
let workspace='overview',debugGeneration=0,debugData=null,acqFile='',lastDebugRun='';
const workspaceNames={overview:'运行总览',channel:'单通道 / 环路',acquisition:'捕获搜索',baseband:'输入信号',sky:'卫星星座',events:'事件 / 切片',files:'数据文件',ports:'调试接口'};
$('workspaces').innerHTML=Object.entries(workspaceNames).map(([k,v])=>`<button data-workspace="${k}" class="${k==='overview'?'active':''}">${v}</button>`).join('');
$('workspaces').querySelectorAll('button').forEach(b=>b.onclick=()=>setWorkspace(b.dataset.workspace));
document.querySelectorAll('[data-browse]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const v=await api('/api/browse',{kind:b.dataset.browse});if(v.path){if(b.dataset.browse==='config'){$('config').value=v.config;loadCommonFields();}else $(b.dataset.browse).value=v.path;}}catch(e){$('validation').textContent=e.message;}finally{b.disabled=false;}});
function plot(rows,series,unit,xkey='t',bounds=null){
 if(!rows.length)return '<div class="empty">等待数据</div>';
 const values=rows.flatMap(r=>series.map(s=>r[s[0]])).filter(Number.isFinite);if(!values.length)return '<div class="empty">此窗口无有效值</div>';
 let low=Math.min(...values),high=Math.max(...values);const pad=(high-low)*.08||1;low-=pad;high+=pad;const first=bounds?bounds[0]:rows[0][xkey],last=bounds?bounds[1]:rows.at(-1)[xkey];const x=t=>45+(t-first)/(last-first||1)*640,y=v=>145-(v-low)/(high-low)*125;
 let svg='<svg viewBox="0 0 700 175" role="img" aria-label="'+esc(unit)+'"><text x="5" y="12">'+esc(unit)+'</text>';
 for(let n=0;n<4;n++){const v=low+(high-low)*n/3;svg+=`<path d="M45 ${y(v)}H685" class="grid"/><text x="0" y="${y(v)+3}">${fmt(v,2)}</text>`;}
 for(let n=0;n<series.length;n++){let prev=false,prior=null;const d=rows.map(r=>{if(!Number.isFinite(r[series[n][0]])){prev=false;prior=null;return '';}if(bounds&&prior&&(r.t-prior.t>.1||r.prn!==prior.prn))prev=false;const p=(prev?'L':'M')+x(r[xkey]).toFixed(2)+' '+y(r[series[n][0]]).toFixed(2);prev=true;prior=r;return p;}).join('');svg+=`<path d="${d}" fill="none" stroke="${colors[n]}" stroke-width="1.5"/>`;}
 svg+=`<text x="45" y="170">${fmt(first,3)}</text><text x="650" y="170">${fmt(last,3)}</text></svg>`;
 return `<div class="instrument-plot">${svg}<div class="plot-legend">${series.map((s,n)=>`<span style="color:${colors[n]}">● ${esc(s[1])}</span>`).join('')}</div></div>`;
}
function card(title,body,note=''){return `<section class="instrument"><h3>${title}</h3>${body}${note?'<p>'+note+'</p>':''}</section>`;}
async function loadLegacyDebug(){if(!state){$('debugContent').innerHTML='<div class="empty">请选择或启动实验</div>';return;}const generation=++debugGeneration;const m=state.meta,ch=Number($('debugChannel').value),start=Number($('sliceStart').value),end=Number($('sliceEnd').value);const query='/api/inspect?run='+m.id+'&kind=';const get=kind=>api(query+kind);$('debugSource').textContent='读取中…';try{
 if(workspace==='baseband'){
 const d=await get('iq&t='+(typeof clock!=='undefined'?clock.time:start));if(generation!==debugGeneration)return;debugData=d;
 const real=d.real===true,series=real?[['i','实数']]:[['i','I'],['q','Q']],label=d.label||'IQ · int8';
 const amplitude=Math.max(1e-12,...d.i.map(Math.abs),...d.q.map(Math.abs));
 const scatter=real?'':card('I/Q 散点','<svg class="constellation" viewBox="0 0 300 200"><path d="M150 5V195M10 100H290" stroke="#dbe5e8"/>'+d.i.map((v,n)=>`<circle cx="${150+v/amplitude*135}" cy="${100-d.q[n]/amplitude*90}" r="1.7" fill="#0c9583" opacity=".35"/>`).join('')+'</svg>','源：原始文件 · '+esc(label));
 $('debugContent').innerHTML=`<div class="debug-heading"><h2>输入信号 · ${esc(label)} · ${fmt(d.t,6)} s</h2><a class="button" download="input-slice.bin" href="/api/raw-input?run=${m.id}&t=${d.t}&count=8192">下载原始信号切片</a><p>${d.fs/1e6} MS/s · ${d.samples} 个${real?'实':'复'}样本 · RMS ${fmt(d.rms,2)} · DC ${real?fmt(d.dc_i,2):'('+fmt(d.dc_i,2)+', '+fmt(d.dc_q,2)+')'}${d.clipped===null?'':' · 满幅样本 '+fmt(d.clipped,2)+'%'}${d.invalid?' · 非有限值 '+d.invalid:''}</p></div><div class="instrument-grid">${card('时域波形',plot(d.i.map((v,n)=>({t:n,i:v,q:d.q[n]})),series,'幅值 / sample'))}${card('输入频谱',plot(d.spectrum.map((v,n)=>({t:d.mhz[n],power:v})),[['power','Hann · FFT']],'dB re 1 / MHz'),real?'双边频谱 · 实数输入呈镜像对称':'')}${scatter}</div>`;
 }else if(workspace==='sky'){
 const d=await get('sky');if(generation!==debugGeneration)return;debugData=d;let svg='<svg class="skyplot" viewBox="0 0 420 420">';for(const r of [55,110,165])svg+=`<circle cx="210" cy="210" r="${r}" fill="none" stroke="#d9e5e8"/>`;svg+='<path d="M210 25V395M25 210H395" stroke="#d9e5e8"/><text x="206" y="22">N</text><text x="400" y="214">E</text><text x="206" y="412">S</text><text x="9" y="214">W</text>';for(const sat of d){const r=(90-sat.elevation)/90*165,a=sat.azimuth*Math.PI/180,x=210+Math.sin(a)*r,y=210-Math.cos(a)*r;svg+=`<circle cx="${x}" cy="${y}" r="15" fill="#0c8979"/><text x="${x}" y="${y+4}" fill="white" text-anchor="middle">${sat.prn}</text>`;}svg+='</svg>';$('debugContent').innerHTML=`<div class="debug-heading"><h2>卫星天空图</h2><p>最近 NMEA GSV · ${d.length} 颗卫星</p></div><div class="instrument-grid">${card('方位角 / 仰角',d.length?svg:'<div class="empty">等待 GSV 星历几何输出</div>')}${card('卫星观测',`<table><tr><th>PRN</th><th>仰角 °</th><th>方位角 °</th><th>C/N₀</th></tr>${d.map(s=>`<tr><td>${esc(s.system||'?')}${s.prn}</td><td>${s.elevation}</td><td>${s.azimuth}</td><td>${fmt(s.cn0,0)}</td></tr>`).join('')}</table>`)}</div>`;
 }else if(workspace==='files'){
 const d=await get('files');if(generation!==debugGeneration)return;debugData=d;$('debugContent').innerHTML=`<div class="debug-heading"><h2>原始输出与中间数据</h2><p>${esc(m.output)}</p></div><table><tr><th>文件</th><th>大小</th><th>访问</th></tr>${d.map(f=>`<tr><td class="num">${esc(f.name)}</td><td>${fmt(f.bytes/1024,1)} KB</td><td><a href="/api/file?run=${m.id}&name=${encodeURIComponent(f.name)}">下载</a></td></tr>`).join('')}</table>`;
 }else if(workspace==='ports'){
 debugData=m;const running=['running','stopping'].includes(m.status);$('debugContent').innerHTML=`<div class="debug-heading"><h2>进程与调试接口</h2><p>${running?'运行中':'已归档'} · PID ${m.pid??'—'} · ${esc(m.exe)}</p></div><div class="instrument-grid">${card('监测端口',`<dl><dt>TrackingMonitor / UDP Protobuf</dt><dd>127.0.0.1:${m.tracking_port??'见 receiver.conf'}</dd><dt>AcquisitionMonitor / UDP Protobuf</dt><dd>127.0.0.1:${m.acquisition_port??'见 receiver.conf'}</dd><dt>生命周期控制</dt><dd>独立进程 stdin · q 正常退出</dd></dl>`)}${card('数据访问 API',`<pre>GET /api/state?run=${m.id}\nGET /api/inspect?run=${m.id}&kind=tracking&channel=0&start=0&end=10\nGET /api/inspect?run=${m.id}&kind=acquisition\nGET /api/inspect?run=${m.id}&kind=files</pre>`)}${card('原生调试器',`<pre>gdb "${esc(m.exe)}"\n(gdb) attach ${m.pid??'PID'}</pre><p>符号：使用带调试信息的接收机构建。端口状态：${running?'监测监听中':'接收机已结束，UDP 已关闭'}。</p>`)}</div>`;
 }
 if(generation===debugGeneration)$('debugSource').textContent={channel:'Tracking dump',acquisition:'Acquisition MAT73',baseband:'原始信号文件',sky:'NMEA GSV',events:'监测 / 接收机日志',files:'实验目录',ports:'运行元数据'}[workspace]||'';
 }catch(e){if(generation===debugGeneration){$('debugSource').textContent='读取失败';$('debugContent').innerHTML='<div class="empty">'+esc(e.message)+'</div>';}}}
async function restartReceiver(next){
 $('restart').disabled=true;$('saveRestart').disabled=true;notify('正在保存当前结果并重启接收机…');
 try{const m=await api('/api/restart',next);config=next;eventWindow=null;selectedRun='';lastSeq=0;logRows=[];state=null;selected=null;freeze=false;cursor=null;acqFile='';await poll();notify('接收机已重启 · '+m.id);}
 catch(e){notify(e.message);}finally{$('restart').disabled=false;$('saveRestart').disabled=false;}
}
$('restart').onclick=()=>restartReceiver(config);
$('saveRestart').onclick=async()=>{const next=formData();try{await api('/api/settings',next);$('configDialog').close();await restartReceiver(next);}catch(e){$('validation').textContent=e.message;}};

const commonFields=[['SignalSource.sampling_frequency','输入采样率 / MS/s',1e6],['InputFilter.IF','中频 / kHz',1e3],['Channels_1C.count','通道数',1],['Channels.in_acquisition','并行捕获通道',1],['Tracking_1C.pll_bw_hz','PLL 带宽 / Hz',1],['Tracking_1C.dll_bw_hz','DLL 带宽 / Hz',1],['Acquisition_1C.doppler_max','多普勒范围 / Hz',1],['Acquisition_1C.doppler_step','搜索步长 / Hz',1]];
function configValue(key){const line=$('config').value.split('\n').find(l=>l.trim().split('=')[0].trim()===key);return line?Number(line.split('=')[1]):null;}
function updateParameter(key,value){const lines=$('config').value.split('\n');const index=lines.findIndex(l=>l.trim().split('=')[0].trim()===key);if(index>=0)lines[index]=key+'='+value;else lines.push(key+'='+value);$('config').value=lines.join('\n');}
function activeCommonFields(){const match=$('config').value.match(/^\s*Channel.signal\s*=\s*(\w+)/m),signal=match?match[1]:'1C';return commonFields.map(([key,label,scale])=>[key.replace('_1C.','_'+signal+'.'),label,scale]);}
function loadCommonFields(){
 const type=$('config').value.match(/^\s*SignalSource.item_type\s*=\s*(\w+)/m)?.[1]||'ibyte';$('inputFormat').value=type;
 $('commonParameters').innerHTML=activeCommonFields().map(([key,label,scale],n)=>`<label>${label}<input type="number" step="any" data-common="${n}" data-original="${configValue(key)===null?'':configValue(key)/scale}" value="${configValue(key)===null?'':configValue(key)/scale}"></label>`).join('');
 $('commonParameters').querySelectorAll('input').forEach(input=>input.oninput=()=>{const [key,label,scale]=activeCommonFields()[Number(input.dataset.common)],value=Number(input.value)*scale;updateParameter(key,value);if(key==='SignalSource.sampling_frequency'){updateParameter('InputFilter.sampling_frequency',value);const decimation=configValue('InputFilter.decimation_factor')||1;updateParameter('GNSS-SDR.internal_fs_sps',Math.round(value/decimation));}});
}
$('config').oninput=loadCommonFields;
function applyCommonFields(){for(const input of $('commonParameters').querySelectorAll('input')){if(input.value!==input.dataset.original){if(input.oninput)input.oninput();}}}

$('inputFormat').onchange=()=>{
 const type=$('inputFormat').value,real=['byte','short','float'].includes(type);
 const adapter={ibyte:'Ibyte_To_Complex',ishort:'Ishort_To_Complex',gr_complex:'Pass_Through',byte:'Pass_Through',short:'Pass_Through',float:'Pass_Through'}[type];
 updateParameter('SignalSource.item_type',type);updateParameter('DataTypeAdapter.implementation',adapter);
 updateParameter('DataTypeAdapter.item_type',real?type:'gr_complex');
 updateParameter('InputFilter.input_item_type',real?type:'gr_complex');updateParameter('InputFilter.output_item_type','gr_complex');updateParameter('InputFilter.taps_item_type','float');
 if(real){updateParameter('SignalConditioner.implementation','Signal_Conditioner');updateParameter('InputFilter.implementation','Freq_Xlating_Fir_Filter');updateParameter('InputFilter.filter_type','lowpass');updateParameter('InputFilter.sampling_frequency',configValue('SignalSource.sampling_frequency'));}
 loadCommonFields();
};
