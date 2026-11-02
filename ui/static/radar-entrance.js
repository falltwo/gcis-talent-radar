/* One shared GSAP clock drives the sweep and every target response. */
(() => {
  'use strict';
  window.createRadarEntrance = function createRadarEntrance(intro) {
    const dialog = intro.querySelector('dialog');
    const scene = intro.querySelector('.radar-object');
    const start = intro.querySelector('#radar-start');
    const motion = intro.querySelector('#radar-motion');
    const sweep = intro.querySelector('.radar-sweep');
    const copy = intro.querySelector('.radar-invitation');
    const title = intro.querySelector('.radar-copy');
    const preference = matchMedia('(prefers-reduced-motion: reduce)');
    const gs = window.gsap;
    const rotateSweep = gs?.quickSetter(sweep,'rotation','deg');
    const targets = [
      {x:31,y:29}, {x:72,y:36}, {x:64,y:73},
      {x:22,y:62}, {x:49,y:16}, {x:81,y:58},
    ].map(({x,y}) => {
      const node = document.createElement('span');
      node.className = 'radar-target'; node.style.left = x+'%'; node.style.top = y+'%';
      node.innerHTML = '<i class="target-halo"></i><i class="target-light"></i><span class="target-lock"><b></b><b></b><b></b><b></b></span>';
      intro.querySelector('.radar-targets').append(node);
      return {node,light:node.querySelector('.target-light'),halo:node.firstElementChild,lock:node.lastElementChild,
        bearing:(Math.atan2(x-50,50-y)*180/Math.PI+360)%360};
    });
    const ns='http://www.w3.org/2000/svg';
    const scale = intro.querySelector('.radar-ticks');
    for(let index=0;index<72;index++) {
      const angle=index*5*Math.PI/180, major=index%6===0;
      const line=document.createElementNS(ns,'line');
      const r=major?225:231;
      for(const [name,value] of Object.entries({x1:250+Math.sin(angle)*r,y1:250-Math.cos(angle)*r,x2:250+Math.sin(angle)*238,y2:250-Math.cos(angle)*238})) line.setAttribute(name,value);
      line.setAttribute('class',major?'major':'minor');scale.append(line);
    }
    let active = true, paused = preference.matches, clock = {angle:0}, previous=0;
    let scan, reveal, departure;
    const targetParts = targets.flatMap(target=>[target.light,target.halo,target.lock]);
    function pulse(target) {
      gs.killTweensOf([target.light,target.halo,target.lock]);
      gs.fromTo(target.light,{opacity:1,scale:1.2},{opacity:0,scale:.75,duration:2.05,ease:'power2.out'});
      gs.fromTo(target.halo,{opacity:.65,scale:.3},{opacity:0,scale:2.2,duration:1.75,ease:'power2.out'});
      gs.fromTo(target.lock,{opacity:1,scale:1.35},{opacity:0,scale:1,duration:2.05,ease:'power2.out'});
    }
    function updateSweep() {
      const angle=clock.angle%360;
      const delta=(angle-previous+360)%360;
      rotateSweep(angle);
      if(delta>0) targets.forEach(target=>{
        const distance=(target.bearing-previous+360)%360;
        if(distance>0&&distance<=delta) pulse(target);
      });
      previous=angle;
    }
    function startScan() {
      scan?.kill();
      if(!gs) return;
      scan=gs.to(clock,{angle:360,duration:5.8,ease:'none',repeat:-1,onUpdate:updateSweep,paused});
      motion.textContent=paused?'播放動態':'暫停動態';
      motion.setAttribute('aria-pressed',String(paused));
    }
    function revealScene() {
      reveal?.kill();
      if(!gs) {scene.style.opacity='1';copy.style.opacity='1';title.style.opacity='1';return;}
      gs.set(scene,{opacity:0});gs.set([copy,title],{opacity:0});
      reveal=gs.timeline().to(scene,{opacity:1,duration:preference.matches?0:3.2,ease:'power1.inOut'})
        .to(title,{opacity:1,duration:preference.matches?0:1.8,ease:'power1.out'},preference.matches?0:1)
        .to(copy,{opacity:1,duration:preference.matches?0:1.1,ease:'power1.out'},preference.matches?0:2.3);
    }
    function openDialog() {
      if(!active||dialog.open)return;
      intro.classList.add('choosing');
      dialog.showModal();
      intro.querySelector('#explore-dialog-title').focus({preventScroll:true});
    }
    function closeDialog() { if(dialog.open)dialog.close(); }
    intro.addEventListener('click',event=>{
      if(event.target.closest('dialog, #radar-motion'))return;
      openDialog();
    });
    // Tab retains normal focus navigation; modified shortcuts never activate the page.
    document.addEventListener('keydown',event=>{
      if(!active||intro.hidden||dialog.open||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.altKey)return;
      if(event.key.length!==1&&event.key!=='Enter')return;
      if(event.target===motion)return;
      event.preventDefault();event.stopImmediatePropagation();openDialog();
    },true);
    intro.querySelector('#explore-close').addEventListener('click',closeDialog);
    dialog.addEventListener('close',()=>{
      intro.classList.remove('choosing');
      if(active)start.focus({preventScroll:true});
    });
    dialog.addEventListener('click',event=>{
      if(event.target!==dialog)return;
      const box=dialog.getBoundingClientRect();
      if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)closeDialog();
    });
    motion.addEventListener('click',()=>{
      paused=!paused;scan?.paused(paused);
      motion.textContent=paused?'播放動態':'暫停動態';motion.setAttribute('aria-pressed',String(paused));
      if(paused){gs?.killTweensOf(targetParts);gs?.set(targetParts,{opacity:0});}
    });
    preference.addEventListener('change',()=>{
      paused=preference.matches;scan?.paused(paused);
      motion.textContent=paused?'播放動態':'暫停動態';motion.setAttribute('aria-pressed',String(paused));
      if(paused){reveal?.progress(1);gs?.killTweensOf(targetParts);gs?.set(targetParts,{opacity:0});}
    });
    startScan();revealScene();
    return {
      leave(done) {
        active=false;dialog.close();reveal?.kill();
        const complete=()=>{intro.hidden=true;scan?.pause();gs?.killTweensOf(targetParts);gs?.set(targetParts,{opacity:0});done();};
        if(gs&&!preference.matches)departure=gs.to(intro,{opacity:0,duration:.75,ease:'power2.inOut',onComplete:complete});
        else complete();
      },
      show() {
        departure?.kill();active=true;intro.hidden=false;intro.inert=false;
        if(gs)gs.set(intro,{opacity:1});else intro.style.opacity='1';
        intro.classList.remove('leaving','choosing');
        scan?.paused(paused);revealScene();start.focus({preventScroll:true});
      },
    };
  };
})();
