/* One shared GSAP clock drives the sweep and every target response. */
(() => {
  'use strict';
  window.createRadarEntrance = function createRadarEntrance(intro) {
    const dialog = intro.querySelector('dialog');
    const scene = intro.querySelector('.radar-object');
    const start = intro.querySelector('#radar-start');
    const motion = intro.querySelector('#radar-motion');
    const sweep = intro.querySelector('.radar-sweep');
    const ripples = [...intro.querySelectorAll('.radar-pulses i')];
    const shock = intro.querySelector('.radar-shock');
    const soundToggle = intro.querySelector('#radar-sound');
    const submit = intro.querySelector('#intro-submit');
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
    let scan, reveal, departure, nextRipple, spin, launching=false;
    let audio, master, echo, hum, soundOn=true;
    try { soundOn=localStorage.getItem('radar-sound')!=='off'; } catch {}
    // Browsers only allow audio after a gesture, so the graph is built on first interaction.
    function unlockAudio() {
      if(!soundOn||!window.AudioContext)return;
      if(!audio) {
        audio=new AudioContext();
        master=audio.createGain();master.connect(audio.destination);
        echo=audio.createDelay(1);echo.delayTime.value=.34;
        const damp=audio.createBiquadFilter(), feedback=audio.createGain();
        damp.type='lowpass';damp.frequency.value=1600;feedback.gain.value=.42;
        echo.connect(damp);damp.connect(feedback);feedback.connect(echo);damp.connect(master);
      }
      if(audio.state==='suspended')audio.resume();
    }
    function tone(start,{type='sine',from,to=from,attack=.005,length,peak,wet=0}) {
      const osc=audio.createOscillator(), gain=audio.createGain(), send=audio.createGain();
      const end=start+attack+length;
      osc.type=type;osc.frequency.setValueAtTime(from,start);
      if(to!==from)osc.frequency.exponentialRampToValueAtTime(to,start+attack+length*.6);
      gain.gain.setValueAtTime(.001,start);
      gain.gain.exponentialRampToValueAtTime(peak,start+attack);
      gain.gain.exponentialRampToValueAtTime(.001,end);
      send.gain.value=wet;
      osc.connect(gain);gain.connect(master);gain.connect(send);send.connect(echo);
      osc.onended=()=>{gain.disconnect();send.disconnect();};
      osc.start(start);osc.stop(end+.01);
    }
    function burst(start,{length,peak,from,to=from,q=1,attack=0,wet=0}) {
      const noise=audio.createBufferSource(), band=audio.createBiquadFilter(), gain=audio.createGain(), send=audio.createGain();
      noise.buffer=audio.createBuffer(1,Math.ceil(audio.sampleRate*length),audio.sampleRate);
      noise.buffer.getChannelData(0).forEach((_,index,data)=>{data[index]=Math.random()*2-1;});
      band.type='bandpass';band.Q.value=q;band.frequency.setValueAtTime(from,start);
      if(to!==from)band.frequency.exponentialRampToValueAtTime(to,start+length);
      if(attack){gain.gain.setValueAtTime(.001,start);gain.gain.exponentialRampToValueAtTime(peak,start+attack);}
      else gain.gain.setValueAtTime(peak,start);
      gain.gain.exponentialRampToValueAtTime(.001,start+length);
      send.gain.value=wet;
      noise.connect(band);band.connect(gain);gain.connect(master);gain.connect(send);send.connect(echo);
      noise.onended=()=>{noise.disconnect();band.disconnect();gain.disconnect();send.disconnect();};
      noise.start(start);
    }
    function playSonar() {
      if(!soundOn||audio?.state!=='running')return;
      const now=audio.currentTime;
      tone(now,{from:1180,to:1120,attack:.012,length:1.5,peak:.0574,wet:.55});
      tone(now,{from:1770,attack:.012,length:.7,peak:.0115,wet:.55});
    }
    function playBoot() {
      if(!soundOn||!audio)return;
      const now=audio.currentTime;
      burst(now,{length:.04,peak:.22,from:2800,q:3});
      tone(now+.02,{type:'triangle',from:180,to:1400,attack:.02,length:.36,peak:.11,wet:.2});
      tone(now+.26,{from:1320,length:.2,peak:.07,wet:.35});
      tone(now+.36,{from:1760,length:.32,peak:.06,wet:.45});
    }
    function playOpen() {
      if(!soundOn||audio?.state!=='running')return;
      const now=audio.currentTime;
      burst(now,{length:.5,peak:.1,from:380,to:2600,q:1.2,attack:.2,wet:.25});
      tone(now+.14,{from:880,to:1320,attack:.03,length:.26,peak:.022,wet:.5});
      tone(now+.24,{from:1760,attack:.02,length:.3,peak:.014,wet:.6});
    }
    function playTick() {
      if(!soundOn||audio?.state!=='running')return;
      burst(audio.currentTime,{length:.016,peak:.09,from:5200,q:6});
    }
    function startHum() {
      if(!soundOn||audio?.state!=='running'||hum||submit.disabled)return;
      const now=audio.currentTime;
      const osc=audio.createOscillator(), low=audio.createBiquadFilter(), gain=audio.createGain();
      osc.type='sawtooth';osc.frequency.setValueAtTime(70,now);osc.frequency.exponentialRampToValueAtTime(210,now+.73);
      low.type='lowpass';low.frequency.setValueAtTime(240,now);low.frequency.exponentialRampToValueAtTime(900,now+.73);
      gain.gain.setValueAtTime(.001,now);gain.gain.exponentialRampToValueAtTime(.05,now+.6);gain.gain.exponentialRampToValueAtTime(.001,now+1.15);
      osc.connect(low);low.connect(gain);gain.connect(master);
      osc.onended=()=>{low.disconnect();gain.disconnect();hum=null;};
      osc.start(now);osc.stop(now+1.16);
      hum={osc,gain};
    }
    function stopHum() {
      if(!hum)return;
      const now=audio.currentTime;
      hum.gain.gain.cancelScheduledValues(now);hum.gain.gain.setTargetAtTime(.0001,now,.03);
      hum.osc.stop(now+.15);
    }
    function playInitialize() {
      stopHum();
      if(!soundOn||audio?.state!=='running')return;
      const now=audio.currentTime, end=now+2.33;
      const body=audio.createOscillator(), sub=audio.createOscillator(), rotor=audio.createOscillator();
      const low=audio.createBiquadFilter(), throb=audio.createGain(), depth=audio.createGain(), gain=audio.createGain();
      body.type='sawtooth';sub.type='sine';
      body.frequency.setValueAtTime(104,now);body.frequency.exponentialRampToValueAtTime(148,now+1.73);
      sub.frequency.setValueAtTime(82,now);sub.frequency.exponentialRampToValueAtTime(116,now+1.73);
      // The rotor LFO pulses the volume in step with the sweep speeding up.
      rotor.frequency.setValueAtTime(4.5,now);rotor.frequency.exponentialRampToValueAtTime(9.75,now+1.73);
      low.type='lowpass';low.frequency.value=520;
      throb.gain.value=.6;depth.gain.value=.4;
      gain.gain.setValueAtTime(.001,now);gain.gain.exponentialRampToValueAtTime(.225,now+.4);
      gain.gain.setValueAtTime(.225,now+1.6);gain.gain.exponentialRampToValueAtTime(.001,end);
      body.connect(low);sub.connect(low);low.connect(throb);throb.connect(gain);gain.connect(master);
      rotor.connect(depth);depth.connect(throb.gain);
      body.onended=()=>{low.disconnect();throb.disconnect();depth.disconnect();gain.disconnect();};
      for(const osc of [body,sub,rotor]){osc.start(now);osc.stop(end+.01);}
    }
    function syncSound() {
      soundToggle.textContent=soundOn?'音效：開':'音效：關';
      soundToggle.setAttribute('aria-pressed',String(soundOn));
    }
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
      if(delta>0&&active) targets.forEach(target=>{
        const distance=(target.bearing-previous+360)%360;
        if(distance>0&&distance<=delta) pulse(target);
      });
      previous=angle;
    }
    function emitRipple() {
      playSonar();
      ripples.forEach((ring,index)=>{
        const delay=index*.42, peak=.34-index*.08;
        gs.fromTo(ring,{scale:.08},{scale:1,duration:2.6,delay,ease:'sine.out'});
        gs.fromTo(ring,{opacity:0},{keyframes:[{opacity:peak,duration:.5,ease:'sine.out'},{opacity:0,duration:2.1,ease:'sine.in'}],delay});
      });
      scheduleRipple();
    }
    function scheduleRipple() { nextRipple=gs.delayedCall(gs.utils.random(3,5),emitRipple); }
    function syncRipples() {
      intro.classList.toggle('motion-paused',paused);
      if(!gs)return;
      nextRipple?.kill();
      if(active&&!paused) return scheduleRipple();
      gs.killTweensOf(ripples);gs.set(ripples,{opacity:0});
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
      playOpen();
      dialog.showModal();
      intro.querySelector('#explore-dialog-title').focus({preventScroll:true});
    }
    function closeDialog() { if(dialog.open)dialog.close(); }
    function setSpin(timeScale,duration) {
      spin?.kill();
      spin=gs.to(scan,{timeScale,duration,ease:'power2.inOut'});
    }
    // Keyboard and assistive activations have no pointer position, so they burst from the radar centre.
    function launch(x,y) {
      if(!active||dialog.open||launching)return;
      unlockAudio();playBoot();
      if(!gs||paused)return openDialog();
      launching=true;
      const box=intro.getBoundingClientRect(), radar=scene.getBoundingClientRect();
      const left=(x??radar.left+radar.width/2)-box.left, top=(y??radar.top+radar.height/2)-box.top;
      const size=2*Math.hypot(Math.max(left,box.width-left),Math.max(top,box.height-top));
      gs.set(shock,{left,top,width:size,height:size,xPercent:-50,yPercent:-50});
      gs.fromTo(shock,{scale:.02},{scale:1,duration:.85,ease:'expo.out'});
      gs.fromTo(shock,{opacity:1},{opacity:0,duration:.85,ease:'power2.in'});
      setSpin(6,.45);
      gs.delayedCall(.6,()=>{launching=false;openDialog();setSpin(1,1.4);});
    }
    intro.addEventListener('pointerdown',unlockAudio);
    soundToggle.addEventListener('click',()=>{
      soundOn=!soundOn;syncSound();
      try { localStorage.setItem('radar-sound',soundOn?'on':'off'); } catch {}
      unlockAudio();
      if(audio)master.gain.setTargetAtTime(soundOn?1:0,audio.currentTime,.02);
      if(soundOn)playSonar();
    });
    intro.addEventListener('click',event=>{
      if(event.target.closest('dialog, .radar-motion'))return;
      if(event.detail)launch(event.clientX,event.clientY);else launch();
    });
    // Tab retains normal focus navigation; modified shortcuts never activate the page.
    document.addEventListener('keydown',event=>{
      if(!active||intro.hidden||dialog.open||event.repeat||event.isComposing||event.ctrlKey||event.metaKey||event.altKey)return;
      if(event.key.length!==1&&event.key!=='Enter')return;
      if(event.target===motion||event.target===soundToggle)return;
      event.preventDefault();event.stopImmediatePropagation();launch();
    },true);
    intro.querySelector('#explore-close').addEventListener('click',closeDialog);
    // Picker options sit inside the select; their pick is covered by the change event.
    dialog.addEventListener('pointerdown',({target})=>{
      if(target.closest('select:not(:disabled)')&&!target.closest('option'))playTick();
    });
    submit.addEventListener('pointerenter',event=>{if(event.pointerType==='mouse')startHum();});
    submit.addEventListener('pointerleave',stopHum);
    dialog.addEventListener('change',({target})=>{
      playTick();
      target.classList.remove('confirmed');
      void target.offsetWidth; // Restart the flash when the same field changes again.
      target.classList.add('confirmed');
    });
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
      syncRipples();
    });
    preference.addEventListener('change',()=>{
      paused=preference.matches;scan?.paused(paused);
      motion.textContent=paused?'播放動態':'暫停動態';motion.setAttribute('aria-pressed',String(paused));
      if(paused){reveal?.progress(1);gs?.killTweensOf(targetParts);gs?.set(targetParts,{opacity:0});}
      syncRipples();
    });
    startScan();syncRipples();syncSound();revealScene();
    return {
      leave(done) {
        active=false;reveal?.kill();playInitialize();
        const complete=()=>{intro.hidden=true;scan?.pause();syncRipples();gs?.killTweensOf(targetParts);gs?.set(targetParts,{opacity:0});done();};
        if(!gs||preference.matches){dialog.close();return complete();}
        // inert blocks a second submit while the window is shrinking.
        dialog.inert=true;dialog.classList.add('closing');
        gs.delayedCall(.49,()=>{dialog.close();dialog.classList.remove('closing');dialog.inert=false;});
        if(!paused){
          setSpin(7.9,.89);
          gs.killTweensOf(targetParts);gs.set(targetParts,{opacity:0});
          gs.fromTo(targets.flatMap(target=>[target.light,target.lock]),{opacity:0,scale:1},{opacity:1,duration:.124,repeat:9,yoyo:true,ease:'none',stagger:.053});
        }
        departure=gs.to(intro,{opacity:0,delay:paused?.36:.89,duration:1.07,ease:'power2.inOut',onComplete:complete});
      },
      show() {
        departure?.kill();active=true;intro.hidden=false;intro.inert=false;
        if(gs)gs.set(intro,{opacity:1});else intro.style.opacity='1';
        intro.classList.remove('leaving','choosing');
        spin?.kill();scan?.timeScale(1).paused(paused);syncRipples();revealScene();start.focus({preventScroll:true});
      },
    };
  };
})();
