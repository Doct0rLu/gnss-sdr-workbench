const assert=require('node:assert/strict');
const {ReplayClock}=require('../web/replay-model.js');
const c=new ReplayClock();c.reset('real',10,true);c.update(12);assert.equal(c.time,12);
c.seek(3);c.update(20);assert.equal(c.time,3);assert.equal(c.mode,'paused');
c.toggle();c.speed=2;c.tick(.5);assert.equal(c.time,4);assert.equal(c.mode,'playing');
c.focus({t:8,channel:4,text:'Loss of lock'});c.span=4;assert.deepEqual(c.range(),[6,10]);assert.equal(c.mode,'paused');
c.update(30);assert.equal(c.time,8);assert.deepEqual(c.range(),[6,10]);
c.follow();assert.equal(c.time,30);c.toggle();assert.equal(c.time,0);c.tick(30);assert.equal(c.time,30);assert.equal(c.mode,'paused');
c.reset('second',4,false);assert.equal(c.event,null);assert.equal(c.time,4);assert.equal(c.mode,'paused');
console.log('Playback clock: live / pause / speed / event pin / run switch passed');

c.focus({t:2,channel:0});c.span=2;c.speed=1;c.toggle();assert.equal(c.time,1);c.tick(9);assert.equal(c.time,3);assert.equal(c.mode,'paused');assert.deepEqual(c.range(),[1,3]);console.log('Event clip playback starts before event and stops after event');

c.reset("growing",4,true);c.span=4;c.focus({t:3});assert.deepEqual(c.range(),[1,4]);c.update(20);assert.deepEqual(c.range(),[1,4]);assert.equal(c.time,3);console.log("Pinned event window does not expand during recording");
