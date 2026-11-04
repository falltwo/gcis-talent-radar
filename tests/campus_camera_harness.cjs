const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let center=[120.65,24.2],zoom=12,pitch=35,bearing=18,padding={top:8,bottom:9,left:10,right:11};
let handler=null,fly=null,ease=null;const states=[];
const map={getCenter:()=>({lng:center[0],lat:center[1]}),getZoom:()=>zoom,getPitch:()=>pitch,getBearing:()=>bearing,getPadding:()=>padding,
 getContainer:()=>({clientWidth:930}),stop(){},off(){handler=null;},once(_,fn){handler=fn;},
 flyTo(options){fly=options;center=options.center;zoom=options.zoom;pitch=options.pitch;bearing=options.bearing;},easeTo(options){ease=options;}};
const c={window:{innerWidth:1280},setTimeout,clearTimeout};vm.createContext(c);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../ui/static/campus-camera.js'),'utf8'),c);
const camera=c.window.createCampusCamera(map,false,state=>states.push(state));
camera.focus([120.7,24.1]);assert.equal(camera.getState(),'flying');const old=handler;
camera.focus([120.8,24.3]);old();assert.equal(camera.getState(),'flying','Old moveend must not complete a newer flight');
handler();assert.equal(camera.getState(),'detail');assert.equal(fly.zoom,16.5);assert.equal(fly.pitch,56);
camera.restore();assert.deepEqual(Array.from(ease.center),[120.65,24.2]);assert.equal(ease.zoom,12);assert.equal(ease.pitch,35);assert.equal(ease.bearing,18);assert.equal(ease.padding.left,10);
camera.focus([120.9,24.3]);const late=handler;camera.discard();late();assert.equal(camera.getState(),'overview');ease=null;camera.restore();assert.equal(ease,null,'A discarded location cannot be restored');
const reduced=c.window.createCampusCamera(map,true);reduced.focus([120.6,24.2]);assert.equal(fly.duration,0);reduced.restore();assert.equal(ease.duration,0);
console.log('PASS campus camera: chained focus, exact restoration, cancellation, reduced motion');
