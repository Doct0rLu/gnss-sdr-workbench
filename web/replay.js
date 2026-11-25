const clock=new ReplayClock();
$('followLive').after($('freeze'));
let captureFilter=null,offlineRows=[],offlineReady=false,offlineAvailable=false,showOffline=false;
let terminalTimeline=false,sessionTrack=[],sessionInfo=null,sessionEvents=[],playbackEpoch=0,loadingFrame=false,pendingFrame=false,lastFrameKey='',lastTimelinePoll=0,lastTick=performance.now(),dragTimer=null,refreshingTimeline=false;
const linkedViews=['channel','acquisition','events'];
function activeRun(){return state&&['starting','running','stopping'].includes(state.meta.status)&&!selectedRun;}
function inspect(kind,extra=''){return api('/api/inspect?run='+encodeURIComponent(state.meta.id)+'&kind='+kind+extra);}
function bump(){playbackEpoch++;debugGeneration++;lastFrameKey='';$('exportLinked').disabled=true;}
function syncDebug(){syncPlayback();}
function syncPlayback(){
 if(!state)return;
 const changed=clock.run!==state.meta.id;if(changed){acqFile='';captureFilter=null;offlineRows=[];offlineReady=false;offlineAvailable=false;showOffline=false;acquisitionView={...defaultAcquisitionView};bump();clock.reset(state.meta.id,state.signal_time,activeRun());sessionInfo=null;sessionEvents=[];sessionTrack=[];terminalTimeline=false;lastTimelinePoll=0;eventWindow=null;debugData=null;$('debugContent').innerHTML='<div class="empty">读取实验数据…</div>';}
 clock.update(state.signal_time||0);if(!activeRun()&&clock.mode==='live')clock.mode='paused';
 const count=state.meta.configured_channels||12,signature=state.meta.id+':'+count;
 if($('playChannel').dataset.signature!==signature){$('playChannel').innerHTML=Array.from({length:count},(_,n)=>`<option value="${n}">CH ${String(n).padStart(2,'0')}</option>`).join('');$('debugChannel').innerHTML=$('playChannel').innerHTML;$('playChannel').dataset.signature=signature;}
 if(selected===null)selected=state.meta.capture_channel??state.channels[0]?.channel??0;
 $('playChannel').value=selected;$('debugChannel').value=selected;
 transportUI();if(changed&&workspace!=='overview')loadDebug();
 if(!terminalTimeline&&Date.now()-lastTimelinePoll>900)refreshTimeline();
}
async function refreshTimeline(){
 if(!state||refreshingTimeline)return;refreshingTimeline=true;lastTimelinePoll=Date.now();const run=state.meta.id,finished=['completed','stopped','failed'].includes(state.meta.status);
 try{const [info,events,track]=await Promise.all([inspect('timeline'),inspect('events','&start=0&end=3600'),inspect('solution')]);if(state?.meta.id!==run)return;sessionInfo=info;sessionTrack=track;terminalTimeline=finished;
 if(finished){
   const status=await inspect('offline-status');
   if(state?.meta.id!==run)return;
   offlineReady=status.ready;offlineAvailable=status.available;
 }clock.update(info.available);sessionEvents=events.length?events:state.events;transportUI();renderSolution();}
 catch(e){$('rangeLabel').textContent=e.message;}
 finally{refreshingTimeline=false;}
}
function transportUI(){
 const labels={live:'实时跟随',paused:'已暂停',playing:'回放中'};
 $('inputSourceLabel').hidden=!/派生|测试|演示/.test(state?.meta.source||'');$('inputSourceLabel').textContent=state?.meta.source||'';$('playMode').textContent=labels[clock.mode];$('playMode').className='play-mode '+clock.mode;
 $('playTime').textContent=fmt(clock.time,3)+' s';$('playhead').max=clock.available;$('playhead').value=clock.time;
 $('availableTime').textContent=fmt(clock.available,2)+' s';$('playReplay').textContent=clock.mode==='playing'?'Ⅱ 暂停回放':'▶ 播放回放';
 $('followLive').textContent=activeRun()?'● 实时跟随':'↦ 回到末尾';$('followLive').classList.toggle('selected',clock.mode==='live');$('freeze').hidden=!activeRun();$('freeze').disabled=clock.mode!=='live';$('freeze').textContent='Ⅱ 暂停查看';
 $('playSpan').value=String(clock.span);$('clearEvent').hidden=!clock.event;
 const [start,end]=clock.range();$('sliceStart').value=fmt(start,3);$('sliceEnd').value=fmt(end,3);
 $('rangeLabel').textContent=clock.event?'事件切片 · '+fmt(start,3)+'–'+fmt(end,3)+' s':'窗口 '+fmt(start,3)+'–'+fmt(end,3)+' s';
 cursor=clock.mode==='live'?null:clock.time;
 const events=eventsForChannel().filter(isIncident).slice(-10);
 const signature=events.map(eventKey).join('|')+':'+selected;
 if($('eventMarkers').dataset.signature!==signature){$('eventMarkers').dataset.signature=signature;$('eventMarkers').innerHTML=events.map((e,n)=>`<button class="event-marker" data-mark="${n}" title="${esc(e.text)}">${fmt(e.t,2)} s · ${esc(eventType(e))}</button>`).join('');$('eventMarkers').querySelectorAll('button').forEach(b=>b.onclick=()=>focusEvent(events[Number(b.dataset.mark)]));}
}
function setWorkspace(key){
 workspace=key;bump();document.querySelector('main').classList.toggle('debug-mode',key!=='overview');
 $('debugArea').hidden=key==='overview';document.querySelector('.workspace').hidden=key!=='overview';document.querySelector('.solution-panel').hidden=!['overview','sky'].includes(key);document.querySelector('.logs-panel').hidden=!['overview','channel','events','ports'].includes(key);
 $('workspaces').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.workspace===key));
 $('debugChannel').disabled=false;$('sliceStart').disabled=false;$('sliceEnd').disabled=false;
 syncPlayback();if(key!=='overview')loadDebug();
}
function selectPlaybackChannel(ch){selected=Number(ch);acqFile='';bump();syncPlayback();if(workspace==='overview')setWorkspace('channel');else loadDebug();}
$('playChannel').onchange=()=>selectPlaybackChannel($('playChannel').value);
$('debugChannel').onchange=()=>selectPlaybackChannel($('debugChannel').value);
function seekPlayback(t){acqFile='';clock.seek(Number(t));eventWindow=null;freeze=false;bump();transportUI();if(workspace==='overview')setWorkspace('channel');clearTimeout(dragTimer);dragTimer=setTimeout(()=>loadDebug(),100);}
$('playhead').oninput=()=>seekPlayback($('playhead').value);
$('playhead').onchange=()=>{clearTimeout(dragTimer);loadDebug();};
$('playReplay').onclick=()=>{acqFile='';clock.toggle();eventWindow=null;freeze=false;bump();if(workspace==='overview')setWorkspace('channel');transportUI();loadDebug();};
$('followLive').onclick=()=>{acqFile='';clock.follow();eventWindow=null;freeze=false;bump();transportUI();loadDebug();};
$('freeze').onclick=()=>{if(clock.mode==='live')clock.seek(clock.time);else clock.follow();freeze=false;bump();transportUI();loadDebug();};
$('playRate').onchange=()=>{clock.speed=Number($('playRate').value);};
$('playSpan').onchange=()=>{clock.span=Number($('playSpan').value);clock.eventRange=null;clock.eventPlaybackStarted=false;if(clock.event){clock.mode='paused';clock.time=Math.min(clock.available,clock.event.t);}bump();transportUI();loadDebug();};
$('clearEvent').onclick=()=>{clock.seek(clock.time);eventWindow=null;bump();transportUI();loadDebug();};
$('refreshDebug').onclick=()=>{const a=Number($('sliceStart').value),b=Number($('sliceEnd').value);if(!(b>a&&a>=0&&b<=clock.available+.01)){notify('请输入已记录范围内的起止时间');return;}clock.seek(b);clock.span=b-a;bump();transportUI();loadDebug();};
$('cursor').oninput=()=>seekPlayback($('cursor').value);$('latest').onclick=()=>$('followLive').click();
function eventKey(e){return [e.t,e.channel,e.text].join(':');}
function routineBoundary(e){return /Stopping GNSS-SDR|Warning: file .* has .* samples, but SignalSource.samples/i.test(e.text);}
function isIncident(e){if(routineBoundary(e))return false;return e.level==='WARN'||e.level==='ERROR'||/失锁|无效|中断|周跳|loss of lock|stopp|quit/i.test(e.text);}
function eventType(e){if(/Stopping GNSS-SDR/i.test(e.text))return state?.meta.status==='completed'?'结束':'停止';if(/Warning: file .* has .* samples, but SignalSource.samples/i.test(e.text))return '文件边界';return /周跳/.test(e.text)?'周跳':/loss of lock|失锁/i.test(e.text)?'失锁':/无效|中断|stopp|quit/i.test(e.text)?'中断':e.level==='ERROR'?'错误':e.level==='WARN'?'异常':e.module==='acquisition'?'捕获':'跟踪';}
function eventsForChannel(all=false){
 return (sessionEvents.length?sessionEvents:state?.events||[]).filter(e=>e.module!=='pvt'&&(all||e.channel==null||e.channel===selected)).map(e=>{
  if(/Tracking of .*started/.test(e.text)){const prn=Number(e.text.match(/PRN (\d+)/)?.[1]);const prior=(state.acquisitions||[]).find(a=>a.channel===e.channel&&a.prn===prn);if(prior)return {...e,t:prior.t};}return e;
 }).sort((a,b)=>a.t-b.t);
}
function focusEvent(e){
 if(e.channel!==null&&e.channel!==undefined)selected=e.channel;
 clock.focus(e);freeze=false;eventWindow=clock.range();bump();
 setWorkspace('channel');transportUI();loadDebug();requestAnimationFrame(()=>$('debugArea').scrollIntoView({block:'start',behavior:'auto'}));
}
function eventRail(){const events=eventsForChannel(workspace==='events').slice(-100);return `<aside class="event-rail"><h3>${workspace==='events'?'实验事件':'通道事件'}</h3><div class="linked-events">${events.map((e,n)=>`<button data-linked-event="${encodeURIComponent(eventKey(e))}" class="linked-event ${isIncident(e)?'incident':''} ${clock.event&&eventKey(e)===eventKey(clock.event)?'chosen':''}"><time>${fmt(e.t,3)} s · ${e.channel==null?'系统':'CH '+e.channel}</time><span>${esc(eventType(e))}</span><p>${esc(e.text)}</p></button>`).join('')||'<p class="muted">暂无事件</p>'}</div></aside>`;}
function bindLinkedEvents(){const events=new Map(eventsForChannel(true).map(e=>[eventKey(e),e]));$('debugContent').querySelectorAll('[data-linked-event]').forEach(b=>b.onclick=()=>{const e=events.get(decodeURIComponent(b.dataset.linkedEvent));if(e)focusEvent(e);});const rail=$('debugContent').querySelector('.linked-events'),chosen=rail?.querySelector('.chosen');if(chosen){rail.scrollLeft=Math.max(0,chosen.offsetLeft-(rail.clientWidth-chosen.clientWidth)/2);rail.scrollTop=Math.max(0,chosen.offsetTop-(rail.clientHeight-chosen.clientHeight)/2);}}
function timePlot(rows,series,unit,range){
 const html=rows.length?plot(rows,series,unit,'t',range):'<div class="empty">此窗口无跟踪记录</div>';
 return '<div class="linked-time-plot" data-start="'+range[0]+'" data-end="'+range[1]+'">'+html+'</div>';
}
function satelliteSystem(ch=selected){return state?.meta.channel_map?.find(r=>r.channel===ch)?.system||state?.channels.find(r=>r.channel===ch)?.system||({'B3':'C','1C':'G'}[state?.meta.signal])||'?';}
function captureCard(d,compact=false){const f=d.frame;if(!f)return card('捕获快照','<div class="empty">当前时间窗口暂无捕获快照</div>');return card(`捕获帧 · ${satelliteSystem(f.channel)}${String(f.prn).padStart(2,'0')} · ${fmt(f.t,3)} s`,plot(f.delay.map((t,n)=>({t,value:f.profile[n]})),[['value','码延迟峰形']],'归一化功率 / sample'),`${f.positive?'成功':'未过门限'} · 统计量 ${fmt(f.statistic,2)} / ${fmt(f.threshold,2)} · ${fmt(f.doppler_hz,0)} Hz`);}
function renderLinkedFrame(d,capture,range,at){
 const expanded=$('loopAdvanced')?.open||false,rows=d.rows,last=rows.at(-1),ch=selected;
 const event=clock.event?`<div class="event-focus"><b>${esc(eventType(clock.event))} · ${fmt(clock.event.t,3)} s</b><span>${esc(clock.event.text)}</span></div>`:'';
 const graphs=card('PLL 鉴别器',timePlot(rows,[['pll','相位误差']],'cycle',range))+card('DLL 鉴别器',timePlot(rows,[['dll','码误差']],'chip',range))+card('C/N₀',timePlot(rows.map(r=>({...r,cn0:r.cn0>0?r.cn0:null})),[['cn0','C/N₀']],'dB-Hz',range))+card('E / P / L 相关器',timePlot(rows,[['early','Early'],['prompt','Prompt'],['late','Late']],'幅值',range));
 $('debugContent').innerHTML=`<div class="debug-heading"><h2>CH ${String(ch).padStart(2,'0')}${last?' / '+satelliteSystem()+String(last.prn).padStart(2,'0'):''} · ${fmt(range[0],3)}–${fmt(range[1],3)} s</h2><p>${rows.length} 个显示点 · 游标 ${fmt(at,3)} s</p></div>${event}<div class="linked-layout"><div class="linked-main"><div class="instrument-grid">${graphs}${captureCard(capture)}${card('载波锁定指标',timePlot(rows,[['lock','锁定指标']],'ratio',range))}</div><details id="loopAdvanced" ${expanded?'open':''}><summary>更多环路结果 · NCO / 多普勒 / Prompt I/Q</summary><div class="instrument-grid">${card('载波 NCO',timePlot(rows,[['pll_nco','载波 NCO']],'Hz',range))}${card('码 NCO',timePlot(rows,[['dll_nco','码 NCO']],'chip/s',range))}${card('多普勒',timePlot(rows,[['doppler','多普勒']],'Hz',range))}${card('Prompt I/Q',timePlot(rows,[['i','I'],['q','Q']],'幅值',range))}</div></details></div>${eventRail()}</div>`;
 bindLinkedEvents();bindCrosshair(at);
}
function renderAcquisition(d){
 const f=d.frame, frames=d.files;
 const index=frames.findIndex(row=>row.name===f?.name);
 const surface=f?.surface;
 const saved=[...new Set([...(state.meta.capture_channels||[]),...(sessionInfo?.captures||[]).map(r=>r.channel),...frames.map(r=>r.channel)])].sort((a,b)=>a-b);
 const labelFor=ch=>'CH '+String(ch).padStart(2,'0');
 const filters=saved.length?`<details class="capture-filter" ${captureFilter===null?'':'open'}>
  <summary>查看快照通道 · ${captureFilter?.size??saved.length} / ${saved.length}</summary>
  <div class="capture-choice-actions"><button id="showAllCapture" type="button">查看全部</button></div>
  <div id="snapshotFilter" class="capture-choices">${saved.map(ch=>`<label class="inline-choice"><input type="checkbox" value="${ch}" ${captureFilter===null||captureFilter.has(ch)?'checked':''}> ${labelFor(ch)} · ${esc(state.meta.channel_map?.find(r=>r.channel===ch)?.label||'')}</label>`).join('')}</div></details>`:'';
 const summary=surface
   ? `峰值码相位 ${fmt(surface.phase_ms,4)} ms · 多普勒 ${fmt(surface.peak_hz,0)} Hz · 峰值 ${f.peak.toExponential(3)}`
   : '';
 const view=surface?`<section class="instrument acq-surface">
   <div class="surface-heading"><div><h3>三维捕获搜索网格</h3><p>${summary}</p></div><button id="resetAcqView" type="button">重置视角</button></div>
   <canvas id="acqSurface" tabindex="0" aria-label="三维捕获网格，方向键旋转"></canvas>
   <p>拖动旋转。码相位覆盖一个主码周期，每个网格块取最大相关功率。判决统计量和门限见下方。</p>
   </section>`:'';
 const waiting=frames.length?'选择快照，或将时间轴移到捕获发生之后。':'在「配置实验 → 生成配置并运行」勾选「保存捕获搜索网格」，再运行。这里显示所选快照通道的数据。';
 $('debugContent').innerHTML=`<div class="debug-heading"><h2>捕获搜索${f?' · '+labelFor(f.channel):''}</h2>
   ${filters}
   <p>游标 ${fmt(clock.time,3)} s${f?' · 帧时间 '+fmt(f.t,3)+' s':''}</p>
   <div class="snapshot-control"><button id="previousFrame" ${index<=0?'disabled':''}>← 上一帧</button>
   <select id="acqFrames" aria-label="捕获快照"><option value="">${frames.length?'选择捕获快照':'暂无捕获快照'}</option>
   ${frames.map(r=>`<option value="${esc(r.name)}" ${f?.name===r.name?'selected':''}>${fmt(r.t,3)} s · ${labelFor(r.channel)} · ${satelliteSystem(r.channel)}${r.prn} · ${r.positive?'成功':'未过门限'}</option>`).join('')}</select>
   <button id="nextFrame" ${index>=frames.length-1?'disabled':''}>下一帧 →</button></div></div>
   <div class="linked-layout"><div class="instrument-grid">${view}${f?captureCard(d)+card('多普勒剖面',plot(f.dopplers.map((t,n)=>({t,value:f.doppler_profile[n]})),[['value','峰值码延迟列']],'归一化功率 / Hz')):card('捕获快照','<div class="empty">'+waiting+'</div>')}</div>${eventRail()}</div>`;
 const chooseFrame=row=>{
   if(!row)return;
   selected=row.channel;clock.update(row.t);clock.seek(row.t);acqFile=row.name;
   bump();transportUI();loadDebug();
 };
 $('previousFrame').onclick=()=>chooseFrame(frames[index-1]);
 $('nextFrame').onclick=()=>chooseFrame(frames[index+1]);
 $('acqFrames').onchange=()=>chooseFrame(frames.find(row=>row.name===$('acqFrames').value));
 if(filters){
   const refresh=()=>{acqFile='';bump();loadDebug();};
   $('snapshotFilter').onchange=()=>{captureFilter=new Set([...$('snapshotFilter').querySelectorAll('input:checked')].map(input=>Number(input.value)));refresh();};
   $('showAllCapture').onclick=()=>{captureFilter=null;refresh();};
 }
 if(surface)bindAcquisitionSurface($('acqSurface'),f,$('resetAcqView'));
 bindLinkedEvents();
}
function bindCrosshair(at){
 const plots=[...$('debugContent').querySelectorAll('.linked-time-plot')];
 function line(t){for(const p of plots){const svg=p.querySelector('svg');if(!svg)continue;let marker=svg.querySelector('.shared-crosshair');if(!marker){marker=document.createElementNS('http://www.w3.org/2000/svg','path');marker.setAttribute('class','shared-crosshair');svg.append(marker);}const x=45+(t-Number(p.dataset.start))/(Number(p.dataset.end)-Number(p.dataset.start)||1)*640;marker.setAttribute('d',`M${x} 15V145`);}}
 line(at);
 for(const p of plots){const svg=p.querySelector('svg');if(!svg)continue;const t=e=>{const rect=svg.getBoundingClientRect(),f=Math.max(0,Math.min(1,((e.clientX-rect.left)/rect.width*700-45)/640));return Number(p.dataset.start)+f*(Number(p.dataset.end)-Number(p.dataset.start));};svg.onpointermove=e=>line(t(e));svg.onpointerleave=()=>line(at);svg.onclick=e=>seekPlayback(t(e));}
}
async function loadDebug(){
 if(!state||workspace==='overview')return;
 if(loadingFrame){pendingFrame=true;$('frameStatus').textContent='定位中…';return;}loadingFrame=true;pendingFrame=false;
 const epoch=playbackEpoch,run=state.meta.id,key=workspace,ch=selected??0,at=clock.time,range=clock.range();
  $('frameStatus').textContent='读取…';$('debugSource').textContent='读取中…';
 try{
  if(linkedViews.includes(key)){
   let captureQuery=`&channel=${ch}&t=${at}`;
   if(key==='acquisition'){
     captureQuery=`&surface=1&t=${at}`+(acqFile?'&file='+encodeURIComponent(acqFile):'');
     if(captureFilter?.size)captureQuery+='&channels='+[...captureFilter].join(',');
   }
   const capture=key==='acquisition'&&captureFilter?.size===0?Promise.resolve({files:[],frame:null}):inspect('acquisition',captureQuery);
   const jobs=[capture];if(key!=='acquisition')jobs.push(inspect('tracking',`&channel=${ch}&start=${range[0]}&end=${Math.max(range[0]+.001,range[1])}`));
   const [captured,tracking]=await Promise.all(jobs);if(epoch!==playbackEpoch||run!==state?.meta.id)return;
   debugData={run,channel:ch,time:at,range,event:clock.event?{...clock.event}:null,tracking,capture:captured};
   if(key==='acquisition')renderAcquisition(captured);else renderLinkedFrame(tracking,captured,range,at);
   $('debugSource').textContent='Tracking dump · Acquisition MAT73';
   if(key!=='acquisition'&&clock.mode!=='live'){
    const logs=await inspect('logs',`&start=${range[0]}&end=${range[1]}&channel=${ch}`);if(epoch!==playbackEpoch)return;renderSliceLogs(logs,ch,range);
   }
  }else await loadLegacyDebug();
 }catch(e){if(epoch===playbackEpoch){debugData=null;$('debugSource').textContent='读取失败';$('debugContent').innerHTML='<div class="empty">'+esc(e.message)+'</div>';}}
 finally{loadingFrame=false;if(epoch===playbackEpoch&&!pendingFrame){$('frameStatus').textContent='';$('exportLinked').disabled=!debugData;}if(pendingFrame){pendingFrame=false;loadDebug();}}
}
function renderSliceLogs(rows,ch,range){sliceLogRows=rows;sliceLogChannel=ch;sliceLogRange=range;const search=$('search').value.toLowerCase(),level=$('level').value,module=$('module').value;const filtered=rows.filter(r=>(r.channel==null||r.channel===ch)&&(!search||r.text.toLowerCase().includes(search))&&(!level||r.level===level)&&(!module||r.module===module));const scroll=$('logs').scrollTop;$('logCount').textContent=filtered.length+' 行 · 切片';$('logs').innerHTML=filtered.map(r=>`<div class="log-row ${esc(r.level)}"><time>${fmt(r.t,3)} s</time><span class="level">${esc(r.level)}</span><span class="module">${esc(r.module)}</span><span class="message">${esc(r.text)}</span></div>`).join('')||'<div class="empty">此切片没有对应日志</div>';$('logs').scrollTop=$('autoScroll').checked?$('logs').scrollHeight:scroll;$('logSummary').textContent=fmt(range[0],3)+'–'+fmt(range[1],3)+' s · CH '+ch;}
// A single request flight plus a replaceable pending frame bounds work under dragging.
setInterval(()=>{
 const now=performance.now(),delta=Math.min(1,(now-lastTick)/1000);lastTick=now;if(!state)return;
 const moved=clock.tick(delta);if(document.hidden)return;if(moved)transportUI();
 if([...linkedViews,'baseband','sky'].includes(workspace)&&(moved||clock.mode==='live')){const range=clock.range(),key=[state.meta.id,workspace,selected,Math.floor(range[0]*4),Math.floor(range[1]*4),Math.floor(clock.time*4)].join('|');if(key!==lastFrameKey){lastFrameKey=key;if(workspace==='sky')renderSolution();loadDebug();}}
},200);
// Preserve the existing overview but route its channel and event actions into the session.
const originalChoose=choose;choose=ch=>selectPlaybackChannel(ch);
const originalRenderEvents=renderEvents;renderEvents=()=>{originalRenderEvents();const nodes=$('events').querySelectorAll('.event');nodes.forEach(node=>{node.tabIndex=0;node.setAttribute('role','button');node.onclick=()=>{const text=node.querySelector('p')?.textContent;const e=[...state.events].reverse().find(e=>e.text.slice(0,230)===text);if(e)focusEvent(e);};node.onkeydown=e=>{if(e.key==='Enter')node.click();};});};

let sliceLogRows=[],sliceLogChannel=0,sliceLogRange=[0,0];
const baseRenderLogs=renderLogs;
renderLogs=()=>{if(clock.mode!=='live'&&['channel','events'].includes(workspace))renderSliceLogs(sliceLogRows,sliceLogChannel,sliceLogRange);else baseRenderLogs();};

function exportCurrentSlice(){if(!debugData)return;const url=URL.createObjectURL(new Blob([JSON.stringify(debugData,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=state.meta.id+'-'+workspace+'-slice.json';a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);}
$('exportLinked').onclick=exportCurrentSlice;$('exportSlice').onclick=exportCurrentSlice;
