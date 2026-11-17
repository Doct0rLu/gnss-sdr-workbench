/* Playback clock is independent of receiver execution. */
(function(root){
class ReplayClock{
 constructor(){this.run='';this.available=0;this.time=0;this.mode='paused';this.speed=1;this.span=6;this.event=null;}
 reset(run,available,active){this.run=run;this.available=Math.max(0,available);this.time=this.available;this.mode=active?'live':'paused';this.event=null;}
 update(available){this.available=Math.max(this.available,available);if(this.mode==='live')this.time=this.available;}
 seek(t){this.mode='paused';this.event=null;this.time=Math.max(0,Math.min(this.available,t));}
 follow(){this.mode='live';this.event=null;this.time=this.available;}
 toggle(){if(this.mode==='playing'){this.mode='paused';return;}if(this.event){const [start,end]=this.range();if(!this.eventPlaybackStarted||this.time>=end)this.time=start;this.eventPlaybackStarted=true;}else if(this.time>=this.available)this.time=0;this.mode='playing';}
 tick(seconds){if(this.mode!=='playing')return false;const limit=this.event?this.range()[1]:this.available;this.time=Math.min(limit,this.time+Math.max(0,seconds)*this.speed);if(this.time>=limit)this.mode='paused';return true;}
 focus(event){this.seek(event.t);this.event=event;this.eventPlaybackStarted=false;this.eventRange=null;}
 range(){if(this.event){if(!this.eventRange){const center=Math.min(this.available,this.event.t);this.eventRange=[Math.max(0,center-this.span/2),Math.min(this.available,center+this.span/2)];}return [...this.eventRange];}return [Math.max(0,this.time-this.span),Math.max(.001,this.time)];}
}
root.ReplayClock=ReplayClock;if(typeof module!=='undefined')module.exports={ReplayClock};
})(typeof globalThis!=='undefined'?globalThis:window);
