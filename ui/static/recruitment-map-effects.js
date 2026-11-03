/* Task illustration over real coordinates; no network/data-flow claims. */
(()=>{
  'use strict';const ns='http://www.w3.org/2000/svg';
  window.createRecruitmentMapEffects=(stage,panel)=>{
    const svg=document.createElementNS(ns,'svg');svg.classList.add('posting-signal');svg.setAttribute('aria-hidden','true');svg.hidden=true;svg.dataset.phase='off';
    svg.innerHTML='<path class="posting-signal-halo"/><path class="posting-signal-line"/><circle class="posting-signal-wave" r="18"/><circle class="posting-signal-origin" r="6"/><circle class="posting-signal-packet" r="4"/><text class="posting-signal-label">任務示意</text>';
    panel.prepend(svg);
    const path=svg.querySelector('.posting-signal-line'),halo=svg.querySelector('.posting-signal-halo'),originDot=svg.querySelector('.posting-signal-origin'),wave=svg.querySelector('.posting-signal-wave'),packet=svg.querySelector('.posting-signal-packet'),label=svg.querySelector('text');
    const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    let map=null,point=null,live=null,camera=null,phase='off',frame=0,paused=false,returnStart=0,length=0,lastD='',paint=[],focusCamera=null;
    function xy(el,x,y){el.setAttribute('cx',x);el.setAttribute('cy',y);}
    function draw(){
      if(!map||!point||phase==='off')return;
      const box=stage.getBoundingClientRect(),windowBox=live.getBoundingClientRect(),p=map.project(point);
      svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);
      const endX=windowBox.left-box.left+2,endY=Math.min(Math.max(p.y,windowBox.top-box.top+45),windowBox.bottom-box.top-45);
      const dx=endX-p.x,d=`M ${p.x} ${p.y} C ${p.x+dx*.42} ${p.y-18}, ${endX-dx*.3} ${endY}, ${endX} ${endY}`;
      if(lastD!==d){lastD=d;path.setAttribute('d',d);halo.setAttribute('d',d);length=path.getTotalLength();}
      xy(originDot,p.x,p.y);xy(wave,p.x,p.y);label.setAttribute('x',p.x+10);label.setAttribute('y',p.y+23);
      if(phase==='review'||phase==='complete'||paused||reduced){packet.style.display='none';return;}
      packet.style.display='';const elapsed=performance.now();let progress=(elapsed%1700)/1700;
      if(phase==='returning')progress=1-Math.min(1,(elapsed-returnStart)/950);
      const pos=path.getPointAtLength(length*progress);xy(packet,pos.x,pos.y);
      if(phase==='returning'&&progress===0){phase='complete';packet.style.display='none';svg.dataset.phase='complete';wave.classList.add('is-returned');}
    }
    function tick(){frame=0;draw();if(!paused&&!reduced&&['working','returning'].includes(phase))frame=requestAnimationFrame(tick);}
    function schedule(){if(!frame)frame=requestAnimationFrame(tick);}
    function soften(){
      for(const layer of map.getStyle()?.layers||[]){
        const keys=layer.type==='symbol'?['text-opacity','icon-opacity']:layer.type==='fill-extrusion'?['fill-extrusion-opacity']:[];
        for(const key of keys){try{const before=map.getPaintProperty(layer.id,key);paint.push([layer.id,key,before]);map.setPaintProperty(layer.id,key,key==='fill-extrusion-opacity'?.38:.35);}catch{}}
      }
    }
    function stop(restore=true){
      cancelAnimationFrame(frame);frame=0;phase='off';svg.hidden=true;svg.dataset.phase='off';wave.classList.remove('is-returned');lastD='';
      if(map){map.off('move',draw);map.off('resize',draw);for(const [id,key,value]of paint)if(map.getLayer(id))try{map.setPaintProperty(id,key,value??null);}catch{};if(restore&&camera)map.easeTo({...camera,duration:reduced?0:600});}
      paint=[];map=null;camera=null;point=null;focusCamera=null;
    }
    function start(coordinates,windowEl){
      stop();const nextMap=window.streetMap.getMap();if(!nextMap||!coordinates)return;
      map=nextMap;point=[...coordinates];live=windowEl;camera={center:map.getCenter().toArray(),zoom:map.getZoom(),bearing:map.getBearing(),pitch:map.getPitch()};phase='working';paused=false;svg.hidden=false;svg.dataset.phase='working';soften();map.on('move',draw);map.on('resize',draw);
      const width=stage.clientWidth,panelWidth=parseFloat(getComputedStyle(live).width)||live.getBoundingClientRect().width,targetX=Math.max(30,(width-panelWidth)/4);
      focusCamera={center:point,offset:[targetX-width/2,0]};map.easeTo({...focusCamera,duration:reduced?0:950});draw();schedule();
    }
    const resize=new ResizeObserver(()=>{if(phase!=='off')schedule();});resize.observe(stage);
    return {start,stop,review(){if(phase==='off')return;phase='review';paused=false;svg.dataset.phase='review';if(map.isMoving()&&focusCamera)map.easeTo({...focusCamera,duration:0});cancelAnimationFrame(frame);frame=0;draw();},finish(){if(phase==='off')return;phase=reduced?'complete':'returning';paused=false;returnStart=performance.now();svg.dataset.phase=phase;draw();schedule();},pause(value){paused=value;cancelAnimationFrame(frame);frame=0;draw();if(!value)schedule();}};
  };
})();
