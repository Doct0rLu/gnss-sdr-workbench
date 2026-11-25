let eventWindow=null;
let showReferenceSky=false;
let workspace='overview',debugGeneration=0,debugData=null,acqFile='',lastDebugRun='';
const workspaceNames={overview:'运行总览',channel:'单通道 / 环路',acquisition:'捕获搜索',baseband:'输入信号',sky:'卫星星座',events:'事件 / 切片',files:'数据文件',ports:'调试接口'};
$('workspaces').innerHTML=Object.entries(workspaceNames).map(([k,v])=>`<button data-workspace="${k}" class="${k==='overview'?'active':''}">${v}</button>`).join('');
$('workspaces').querySelectorAll('button').forEach(b=>b.onclick=()=>setWorkspace(b.dataset.workspace));
document.querySelectorAll('[data-browse]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const v=await api('/api/browse',{kind:b.dataset.browse});if(v.path){if(b.dataset.browse==='config'){presetDirty=false;$('config').value=v.config;loadCommonFields();}else {$(b.dataset.browse).value=v.path;if(b.dataset.browse==='iq')await readRecording();}}}catch(e){$('validation').textContent=e.message;}finally{b.disabled=false;}});
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
 const rf=state.meta.channel_map?.find(r=>r.channel===selected)?.rf_channel||0;const d=await get('iq&rf='+rf+'&t='+(typeof clock!=='undefined'?clock.time:start));if(generation!==debugGeneration)return;debugData=d;
 const real=d.real===true,series=real?[['i','实数']]:[['i','I'],['q','Q']],label=d.label||'IQ · int8';
 const amplitude=Math.max(1e-12,...d.i.map(Math.abs),...d.q.map(Math.abs));
 const scatter=real?'':card('I/Q 散点','<svg class="constellation" viewBox="0 0 300 200"><path d="M150 5V195M10 100H290" stroke="#dbe5e8"/>'+d.i.map((v,n)=>`<circle cx="${150+v/amplitude*135}" cy="${100-d.q[n]/amplitude*90}" r="1.7" fill="#0c9583" opacity=".35"/>`).join('')+'</svg>','源：原始文件 · '+esc(label));
 $('debugContent').innerHTML=`<div class="debug-heading"><h2>输入信号 · RF ${d.rf_channel||0} · ${esc(label)} · ${fmt(d.t,6)} s</h2><a class="button" download="input-slice.bin" href="/api/raw-input?run=${m.id}&rf=${d.rf_channel||0}&t=${d.t}&count=8192">下载原始信号切片</a><p>${d.fs/1e6} MS/s · ${d.samples} 个${real?'实':'复'}样本 · RMS ${fmt(d.rms,2)} · DC ${real?fmt(d.dc_i,2):'('+fmt(d.dc_i,2)+', '+fmt(d.dc_q,2)+')'}${d.clipped===null?'':' · 满幅样本 '+fmt(d.clipped,2)+'%'}${d.invalid?' · 非有限值 '+d.invalid:''}</p></div><div class="instrument-grid">${card('时域波形',plot(d.i.map((v,n)=>({t:n,i:v,q:d.q[n]})),series,'幅值 / sample'))}${card('输入频谱',plot(d.spectrum.map((v,n)=>({t:d.mhz[n],power:v})),[['power','Hann · FFT']],'dB re 1 / MHz'),real?'双边频谱 · 实数输入呈镜像对称':'')}${scatter}</div>`;
 }else if(workspace==='sky'){
 const t=clock.time, d=await get('sky&t='+t+'&reference='+(showReferenceSky?1:0));if(generation!==debugGeneration)return;debugData=d;
 const id=s=>esc(s.system)+String(s.prn).padStart(2,'0');
 const drawable=d.filter(s=>Number.isFinite(s.azimuth)&&Number.isFinite(s.elevation)&&s.elevation>=0&&s.status!=='已失锁');
 const receiverCount=new Set(drawable.filter(s=>s.geometry!=='M1 参考').map(id)).size;
 const referenceCount=new Set(drawable.filter(s=>s.geometry==='M1 参考').map(id)).size;
 let svg='<svg class="skyplot" viewBox="0 0 420 420" aria-label="所选时刻卫星方位和仰角">';
 for(const radius of [55,110,165])svg+='<circle cx="210" cy="210" r="'+radius+'" fill="none" stroke="#d9e5e8"/>';
 svg+='<path d="M210 25V395M25 210H395" stroke="#d9e5e8"/><text x="206" y="22">N</text><text x="400" y="214">E</text><text x="206" y="412">S</text><text x="9" y="214">W</text>';
 for(const sat of drawable){
   const r=(90-sat.elevation)/90*165,a=sat.azimuth*Math.PI/180,x=210+Math.sin(a)*r,y=210-Math.cos(a)*r;
   svg+=`<g><title>${id(sat)} · ${esc(sat.geometry)} · CH ${sat.channel??'—'}</title><circle cx="${x}" cy="${y}" r="13" fill="${sat.system==='C'?'#4974af':'#087f73'}"/><text x="${x}" y="${y+4}" fill="white" text-anchor="middle">${id(sat)}</text></g>`;
 }
 const table='<div class="table-wrap"><table><tr><th>卫星</th><th>通道</th><th>状态</th><th>方位 °</th><th>仰角 °</th><th>角度来源</th></tr>'+d.map(s=>`<tr><td>${id(s)}</td><td>${s.channel??'—'}</td><td>${esc(s.status)}</td><td>${fmt(s.azimuth)}</td><td>${fmt(s.elevation)}</td><td>${esc(s.geometry||'待取得')}</td></tr>`).join('')+'</table></div>';
 const chart=drawable.length?svg+'</svg>':'<div class="empty">该时刻尚无可显示的角度。可在右侧查看已捕获和跟踪的卫星。</div>';
 $('debugContent').innerHTML=`<div class="debug-heading"><h2>卫星天空图 · ${fmt(t,2)} s</h2>
   <p>接收解算角度 ${receiverCount} 颗 · M1 参考角度 ${referenceCount} 颗</p>
   <label class="inline-choice"><input id="referenceSky" type="checkbox" ${showReferenceSky?'checked':''}> 显示 M1 参考角度</label>
   <p>接收机在有位置和可用星历后才提供角度。M1 参考来自仿真轨迹和导航文件。</p></div>
   <div class="instrument-grid">${card('方位角 / 仰角',chart)}${card('该时刻的卫星',table)}</div>`;
 $('referenceSky').onchange=e=>{showReferenceSky=e.target.checked;bump();loadDebug();};
 }else if(workspace==='files'){
 const d=await get('files');if(generation!==debugGeneration)return;debugData=d;$('debugContent').innerHTML=`<div class="debug-heading"><h2>原始输出与中间数据</h2><p>${esc(m.output)}</p></div><table><tr><th>文件</th><th>大小</th><th>访问</th></tr>${d.map(f=>`<tr><td class="num">${esc(f.name)}</td><td>${fmt(f.bytes/1024,1)} KB</td><td><a href="/api/file?run=${m.id}&name=${encodeURIComponent(f.name)}">下载</a></td></tr>`).join('')}</table>`;
 }else if(workspace==='ports'){
 debugData=m;const running=['running','stopping'].includes(m.status);$('debugContent').innerHTML=`<div class="debug-heading"><h2>进程与调试接口</h2><p>${running?'运行中':'已归档'} · PID ${m.pid??'—'} · ${esc(m.exe)}</p></div><div class="instrument-grid">${card('监测端口',`<dl><dt>TrackingMonitor / UDP Protobuf</dt><dd>${m.tracking_port?'127.0.0.1:'+m.tracking_port:'未监听 · 见 receiver.conf'}</dd><dt>AcquisitionMonitor / UDP Protobuf</dt><dd>${m.acquisition_port?'127.0.0.1:'+m.acquisition_port:'未监听 · 见 receiver.conf'}</dd><dt>生命周期控制</dt><dd>独立进程 stdin · q 正常退出</dd></dl>`)}${card('数据访问 API',`<pre>GET /api/state?run=${m.id}\nGET /api/inspect?run=${m.id}&kind=tracking&channel=0&start=0&end=10\nGET /api/inspect?run=${m.id}&kind=acquisition\nGET /api/inspect?run=${m.id}&kind=files</pre>`)}${card('接收机标识',`<dl><dt>GNSS-SDR 提交</dt><dd>${esc(m.upstream_commit??'自选接收机')}</dd><dt>可执行文件 · SHA-256</dt><dd>${esc(m.exe_sha256)}</dd><dt>实际配置 · SHA-256</dt><dd>${esc(m.config_sha256)}</dd></dl>`)}${card('原生调试器',`<pre>gdb "${esc(m.exe)}"\n(gdb) attach ${m.pid??'PID'}</pre><p>符号：使用带调试信息的接收机构建。端口状态：${running?'监测监听中':'接收机已结束，UDP 已关闭'}。</p>`)}</div>`;
 }
 if(generation===debugGeneration)$('debugSource').textContent={channel:'Tracking dump',acquisition:'Acquisition MAT73',baseband:'原始信号文件',sky:'捕获事件 · GSV / 参考星历',events:'监测 / 接收机日志',files:'实验目录',ports:'运行元数据'}[workspace]||'';
 }catch(e){if(generation===debugGeneration){$('debugSource').textContent='读取失败';$('debugContent').innerHTML='<div class="empty">'+esc(e.message)+'</div>';}}}
async function restartReceiver(next){
 $('restart').disabled=true;$('saveRestart').disabled=true;notify('正在保存当前结果并重启接收机…');
 try{const m=await api('/api/restart',next);config=next;eventWindow=null;selectedRun='';lastSeq=0;logRows=[];state=null;selected=null;freeze=false;cursor=null;acqFile='';await poll();notify('接收机已重启 · '+m.id);}
 catch(e){notify(e.message);}finally{$('restart').disabled=false;$('saveRestart').disabled=false;}
}
$('restart').onclick=()=>restartReceiver(config);
$('saveRestart').onclick=async()=>{
 const button=$('saveRestart');button.disabled=true;
 try{
   if($('configMode').value!=='original'&&presetDirty)await generateConfig();
   const next=formData();
   await api('/api/settings',next);
   $('configDialog').close();
   await restartReceiver(next);
 }catch(e){$('validation').textContent=e.message;}
 finally{button.disabled=false;}
};

const commonFields=[['GNSS-SDR.internal_fs_sps','内部采样率 / MS/s',1e6],['SignalSource.sampling_frequency','输入采样率 / MS/s',1e6],['InputFilter.IF','中频 / kHz',1e3],['Channels_1C.count','通道数',1],['Channels.in_acquisition','并行捕获通道',1],['Tracking_1C.pll_bw_hz','PLL 带宽 / Hz',1],['Tracking_1C.dll_bw_hz','DLL 带宽 / Hz',1],['Acquisition_1C.doppler_max','多普勒范围 / Hz',1],['Acquisition_1C.doppler_step','搜索步长 / Hz',1]];
function configValue(key){const line=$('config').value.split('\n').find(l=>l.trim().split('=')[0].trim()===key);return line?Number(line.split('=')[1]):null;}
function updateParameter(key,value){const lines=$('config').value.split('\n');const index=lines.findIndex(l=>l.trim().split('=')[0].trim()===key);if(index>=0)lines[index]=key+'='+value;else lines.push(key+'='+value);$('config').value=lines.join('\n');}
function activeCommonFields(){const signal=$('parameterSignal').value||'1C',suffix=rfCount()>1?$('parameterRF').value||'0':'';return commonFields.map(([key,label,scale])=>[key.replace('_1C.','_'+signal+'.').replace(/^SignalSource\./,sourceRole(suffix)+'.').replace(/^InputFilter\./,'InputFilter'+suffix+'.'),label,scale]);}
function loadCommonFields(){
 loadSignalSelectors();const suffix=rfCount()>1?$('parameterRF').value:'';const type=textConfigValue(sourceRole(suffix)+'.item_type')||'ibyte';$('inputFormat').value=type;
 $('commonParameters').innerHTML=activeCommonFields().map(([key,label,scale],n)=>`<label>${label}<input type="number" step="any" data-common="${n}" data-original="${configValue(key)===null?'':configValue(key)/scale}" value="${configValue(key)===null?'':configValue(key)/scale}"></label>`).join('');
 const shared = isSharedConfig();
 $('inputFormat').disabled = shared;
 for(const input of $('commonParameters').querySelectorAll('input')){
   input.disabled = shared && Number(input.dataset.common) < 3;
 }
 $('commonParameters').querySelectorAll('input').forEach(input=>input.oninput=()=>{const [key,label,scale]=activeCommonFields()[Number(input.dataset.common)],value=Number(input.value)*scale;updateParameter(key,value);if(/SignalSource\d*\.sampling_frequency/.test(key)){const suffix=rfCount()>1?$('parameterRF').value:'';if(multichannelFile() && rfCount()>1){for(let n=0;n<rfCount();n++)updateParameter('InputFilter'+n+'.sampling_frequency',value);}else updateParameter('InputFilter'+suffix+'.sampling_frequency',value);const decimation=configValue('InputFilter'+suffix+'.decimation_factor')||1;if(rfCount()===1)updateParameter('GNSS-SDR.internal_fs_sps',Math.round(value/decimation));}if(/InputFilter\d*\.IF/.test(key)&&value!==0){const suffix=rfCount()>1?$('parameterRF').value:'';updateParameter('InputFilter'+suffix+'.implementation','Freq_Xlating_Fir_Filter');updateParameter('InputFilter'+suffix+'.filter_type','lowpass');updateParameter('InputFilter'+suffix+'.sampling_frequency',configValue(sourceRole(suffix)+'.sampling_frequency'));updateParameter('InputFilter'+suffix+'.output_item_type','gr_complex');updateParameter('InputFilter'+suffix+'.taps_item_type','float');}});
}
$('config').oninput=()=>{presetDirty=false;loadCommonFields();};
function applyCommonFields(){if(presetDirty)throw Error("录制或信号选择已修改，请先生成配置");for(const input of $('commonParameters').querySelectorAll('input')){if(input.value!==input.dataset.original){if(input.oninput)input.oninput();}}}

$('inputFormat').onchange=()=>{
 const rf=rfCount()>1?$('parameterRF').value:'',type=$('inputFormat').value,real=['byte','short','float'].includes(type);
 const adapter={ibyte:'Ibyte_To_Complex',ishort:'Ishort_To_Complex',gr_complex:'Pass_Through',byte:'Pass_Through',short:'Pass_Through',float:'Pass_Through'}[type];
 updateParameter(sourceRole(rf)+'.item_type',type);
 const branches=multichannelFile() && rfCount()>1?Array.from({length:rfCount()},(_,n)=>String(n)):[rf];
 for(const suffix of branches){
   const set=(key,value)=>updateParameter(key.replace('.',suffix+'.'),value);
   set('DataTypeAdapter.implementation',adapter);set('DataTypeAdapter.item_type',real?type:'gr_complex');
   set('InputFilter.input_item_type',real?type:'gr_complex');set('InputFilter.output_item_type','gr_complex');set('InputFilter.taps_item_type','float');
   if(real){set('SignalConditioner.implementation','Signal_Conditioner');set('InputFilter.implementation','Freq_Xlating_Fir_Filter');set('InputFilter.filter_type','lowpass');set('InputFilter.sampling_frequency',configValue(sourceRole(suffix)+'.sampling_frequency'));}
 }
 loadCommonFields();
};

let signalCatalog=[],inputPaths=[],captureSelection=new Set([0]);
function renderCaptureSelection(){
 const groups=signalCatalog.filter(s=>Number(textConfigValue('Channels_'+s.id+'.count'))>0);
 const labels=groups.flatMap(s=>Array.from({length:Math.min(128,Number(textConfigValue('Channels_'+s.id+'.count')))},()=>s.label)).slice(0,128);
 if(!labels.length)return;
 captureSelection=new Set([...captureSelection].filter(ch=>ch<labels.length));
 $('captureSummary').textContent='保存快照通道 · 已选 '+captureSelection.size+' / '+labels.length;
 $('captureChannels').innerHTML=labels.map((label,ch)=>`<label class="inline-choice"><input type="checkbox" value="${ch}" ${captureSelection.has(ch)?'checked':''}> CH ${String(ch).padStart(2,'0')} · ${esc(label)}</label>`).join('');
 $('captureChannels').onchange=()=>{
   captureSelection=new Set([...$('captureChannels').querySelectorAll('input:checked')].map(input=>Number(input.value)));
   $('captureSummary').textContent='保存快照通道 · 已选 '+captureSelection.size+' / '+labels.length;
 };
 $('captureAll').onclick=()=>{captureSelection=new Set(labels.map((_,ch)=>ch));renderCaptureSelection();};
 $('captureNone').onclick=()=>{captureSelection.clear();renderCaptureSelection();};
}

function textConfigValue(key){const line=$('config').value.split('\n').find(l=>l.trim().split('=')[0].trim()===key);return line?line.slice(line.indexOf('=')+1).split(/[;#]/)[0].trim():'';}
function multichannelFile(){return textConfigValue('SignalSource.implementation')==='Multichannel_File_Signal_Source';}
function sourceRole(suffix){return 'SignalSource'+(multichannelFile()?'':suffix);}
function rfCount(){if(multichannelFile())return Number(textConfigValue('SignalSource.RF_channels')||1);return Number(textConfigValue('GNSS-SDR.num_sources')||textConfigValue('Receiver.sources_count')||1);}
function rfFilename(n){return textConfigValue(multichannelFile()?'SignalSource.filename'+n:'SignalSource'+n+'.filename');}
function collectInputs(){if(isSharedConfig())return [{path:$('iq').value}];const inputs=[{path:$('iq').value}];for(let n=1;n<rfCount();n++)inputs.push({path:document.querySelector('[data-rf-path="'+n+'"]')?.value||inputPaths[n]||rfFilename(n)});return inputs;}
function loadSignalSelectors(){
 const enabled=signalCatalog.filter(s=>Number(textConfigValue('Channels_'+s.id+'.count'))>0),previous=$('parameterSignal').value,rf=$('parameterRF').value;
 $('parameterSignal').innerHTML=(enabled.length?enabled:signalCatalog).map(s=>`<option value="${s.id}">${esc(s.label)}</option>`).join('');if(enabled.some(s=>s.id===previous))$('parameterSignal').value=previous;
 $('parameterRF').innerHTML=Array.from({length:rfCount()},(_,n)=>`<option value="${n}">RF ${n}</option>`).join('');if(Number(rf)<rfCount())$('parameterRF').value=rf||'0';
 const current=[...document.querySelectorAll('[data-rf-path]')];for(const f of current)inputPaths[Number(f.dataset.rfPath)]=f.value;
 $('rfFiles').innerHTML=(presetDirty||isSharedConfig())?'':Array.from({length:Math.max(0,rfCount()-1)},(_,i)=>{const n=i+1,path=inputPaths[n]||rfFilename(n);return `<label>RF ${n} · ${esc(branchSignals(enabled,n)||'信号')} 文件</label><div class="file-field"><input data-rf-path="${n}" aria-label="RF ${n} 文件路径" value="${esc(path)}"><button data-rf-browse="${n}">浏览…</button></div>`;}).join('');
 for(const b of $('rfFiles').querySelectorAll('[data-rf-browse]'))b.onclick=async()=>{b.disabled=true;try{const v=await api('/api/browse',{kind:'iq'});if(v.path){inputPaths[Number(b.dataset.rfBrowse)]=v.path;document.querySelector('[data-rf-path="'+b.dataset.rfBrowse+'"]').value=v.path;}}catch(e){$('validation').textContent=e.message;}finally{b.disabled=false;}};
 if(!presetDirty)restorePreset(enabled);
 renderCaptureSelection();
}
$('parameterSignal').onchange=loadCommonFields;$('parameterRF').onchange=loadCommonFields;
let presetDirty=false;
function isSharedConfig(){return textConfigValue('Workbench.capture_center_hz')!=='';}
function branchSignals(enabled, n){
 return enabled.filter(s=>Number(textConfigValue('Channels_'+s.id+'.RF_channel_ID'))===n).map(s=>s.label).join(' / ');
}
async function readRecording(fillDuration=true){
 const path=$('iq').value.trim();if(!path)return;
 const note=await api('/api/recording',{path});
 if(path!==$('iq').value.trim())return;
 if(!note.rate_hz){
   $('recordingInfo').textContent='请按录制记录填写采样率、格式和处理时长。';
   return;
 }
 const center=Number(note.center_hz);
 $('recordingInfo').textContent='已读到录制记录 · '+note.rate_hz/1e6+' MS/s · '+(note.duration_s||'—')+' 秒'+(center>0?' · 中心 '+center/1e6+' MHz':'');
 if(fillDuration&&note.duration_s>0)$('duration').value=Math.min(3600,Math.floor(note.duration_s*10)/10||note.duration_s);
 if($('receptionProfile').value)return;
 $('captureRate').value=note.rate_hz/1e6;$('captureFormat').value=note.format;
 if(center>0)$('captureCenter').value=center/1e6;
 const role=sourceRole(rfCount()>1?'0':'');
 if(configValue(role+'.sampling_frequency')!==note.rate_hz||textConfigValue(role+'.item_type')!==note.format||(center>0&&$('rfMode').value==='shared'&&configValue('Workbench.capture_center_hz')!==center)){
   editPreset();$('branchPlan').textContent='录制记录为 '+note.rate_hz/1e6+' MS/s · '+note.format+'，请生成配置。';
 }
}
$('iq').onchange=()=>readRecording().catch(e=>$('validation').textContent=e.message);
function showPresetFields(){
 const m1=Boolean($('receptionProfile').value);
 $('standardPresetFields').hidden=m1;
 $('m1PrnFields').hidden=!m1;
 const cross=$('receptionProfile').value==='cross';
 $('mixedPrnFields').hidden=!cross;$('singlePrnLabel').hidden=cross;
 $('m1InputHint').textContent=(cross?'采集中心 1568.259 MHz':'采集中心对准信号载频')+' · 24 MS/s int8 IQ。填写 PRN 后，每颗卫星分配一个通道。';
 $('presetCount').disabled=m1 && (cross?['1C','1D','B1'].every(s=>$('prns'+s).value.trim()):Boolean($('assignedPrns').value.trim()));
 const shared=$('rfMode').value==='shared';
 $('sharedRecording').hidden=m1;$('centerField').hidden=!shared;
 $('rfModeHint').textContent=shared
   ?'一份文件可含同频或跨频信号。工作台按载频分支，下变频、滤波和降采样，最后联合定位。'
   :'每个载频选择一份起点同步的文件。同频信号共用一路。生成配置后会列出所需文件。';
 $('b1cChoice').hidden=m1||!$('signalCatalog').querySelector('input[value="1D"]:checked');
 $('prelockChoice').hidden=m1?!['1D','cross'].includes($('receptionProfile').value):$('b1cChoice').hidden;
 $('iqLabel').textContent=m1||shared?'信号文件':'RF 0 · '+(presetDirty?'首路信号':branchSignals(signalCatalog.filter(s=>s.id&&Number(textConfigValue('Channels_'+s.id+'.count'))>0),0)||'首路信号')+' 文件';
}
function restorePreset(enabled){
 const m1=textConfigValue('Workbench.replay_profile')==='m1';
 const cross=m1 && enabled.length===3 && enabled.every(s=>['1C','1D','B1'].includes(s.id));
 if(m1)$('presetDetails').open=true;
 $('receptionProfile').value=cross?'cross':m1 && enabled.length===1?enabled[0].id:'';
 let offset=0;
 $('assignedPrns').value='';
 for(const id of ['1C','1D','B1'])$('prns'+id).value='';
 for(const item of enabled){
   const count=configValue('Channels_'+item.id+'.count');
   const prns=Array.from({length:count},(_,i)=>textConfigValue('Channel'+(offset+i)+'.satellite')).filter(Boolean);
   if(cross)$('prns'+item.id).value=prns.join(' ');
   else if(m1)$('assignedPrns').value=prns.join(' ');
   offset+=count;
 }
 for(const c of $('signalCatalog').querySelectorAll('input'))c.checked=enabled.some(s=>s.id===c.value);
 const shared=isSharedConfig(),suffix=rfCount()>1?'0':'';
 $('rfMode').value=shared?'shared':!$('iq').value&&rfCount()===1?'shared':'separate';
 $('b1cProfile').value=textConfigValue('Acquisition_1D.qmboc')==='true'?'wide':'narrow';
 if(enabled.length)$('presetCount').value=configValue('Channels_'+enabled[0].id+'.count');
 {
   if(shared)$('captureCenter').value=configValue('Workbench.capture_center_hz')/1e6;
   $('captureRate').value=configValue(sourceRole(suffix)+'.sampling_frequency')/1e6;
   $('captureFormat').value=textConfigValue(sourceRole(suffix)+'.item_type');
 }
 showPresetFields();
 const internal=configValue('GNSS-SDR.internal_fs_sps')/1e6;
 $('branchPlan').innerHTML=enabled.length?'<strong>已生成的接收支路</strong>'+Array.from({length:rfCount()},(_,n)=>{
   const suffix=rfCount()>1?String(n):'',prefix='InputFilter'+suffix+'.',offset=configValue(prefix+'IF')/1e6;
   const input=configValue(sourceRole(suffix)+'.sampling_frequency')/1e6;
   const factor=configValue(prefix+'decimation_factor')||1;
   return `<div><b>RF ${n}</b> ${esc(branchSignals(enabled,n))}<span>${input} → ${internal} MS/s · IF ${offset>0?'+':''}${offset} MHz · 抽取 ×${factor}</span></div>`;
 }).join(''):'选择信号后生成配置。';
}
function editPreset(){presetDirty=true;showPresetFields();$('branchPlan').textContent='配置有改动。点「生成配置」查看分频、频偏和降采样的结果。';}
$('receptionProfile').oninput=()=>{if($('receptionProfile').value)$('presetCount').value=$('receptionProfile').value==='2S'?12:9;for(const k of ['assignedPrns','prns1C','prns1D','prnsB1'])$(k).value='';editPreset();};
for(const id of ['prns1C','prns1D','prnsB1','assignedPrns','signalCatalog','rfMode','b1cProfile','captureCenter','captureRate','captureFormat','presetCount'])$(id).oninput=editPreset;
async function generateConfig(){
   const ids=[...$('signalCatalog').querySelectorAll('input:checked')].map(c=>c.value);
   const request={signals:ids,count:Number($('presetCount').value),b1c_profile:$('b1cProfile').value};
   const m1=$('receptionProfile').value;
   if(m1==='cross')Object.assign(request,{signals:['1C','1D','B1'],profile:'m1',b1c_profile:'narrow',prns:Object.fromEntries(['1C','1D','B1'].map(s=>[s,$('prns'+s).value]))});
   else if(m1)Object.assign(request,{signals:[m1],profile:'m1',b1c_profile:'narrow',prns:$('assignedPrns').value});
   else if($('rfMode').value==='shared')request.shared={center_mhz:Number($('captureCenter').value),rate_hz:Math.round(Number($('captureRate').value)*1e6),format:$('captureFormat').value};
   else {
     const path=$('iq').value.trim(), note=path?await api('/api/recording',{path}):{};
     request.separate={rate_hz:note.rate_hz||Math.round(Number($('captureRate').value)*1e6),format:note.format||$('captureFormat').value};
   }
   if(request.shared&&$('iq').value.trim()){
     const note=await api('/api/recording',{path:$('iq').value.trim()});
     const center=Number(note.center_hz);
     if(note.rate_hz&&note.rate_hz!==request.shared.rate_hz)throw Error('录制记录显示 '+note.rate_hz/1e6+' MS/s，请更新录制采样率。');
     if(center>0&&Math.round(request.shared.center_mhz*1e6)!==center)throw Error('录制记录显示中心 '+center/1e6+' MHz，请更新录制中心。');
   }
   const v=await api('/api/template',request);
   presetDirty=false;$('config').value=v.config;loadCommonFields();
   $('validation').textContent=rfCount()>1&&!isSharedConfig()?'配置已生成。请在第 2 步选齐各路文件。':'配置已生成。核对支路后，点「检查并启动」。';
}
$('generateSignals').onclick=async()=>{
 try{await generateConfig();}catch(e){$('validation').textContent=e.message;}
};
api('/api/signals').then(rows=>{signalCatalog=rows;$('signalCatalog').innerHTML=rows.map(s=>`<label><input type="checkbox" value="${s.id}"> ${esc(s.label)} · ${s.mhz} MHz</label>`).join('');if($('configDialog').open)loadCommonFields();}).catch(e=>notify(e.message));
