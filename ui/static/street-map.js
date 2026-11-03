/* Real OpenStreetMap vector geometry rendered by MapLibre. */
(() => {
  let map, marker, revision = 0, currentLocation, mapReady = false;
  let animationFrame = 0;
  let companyPopup = null, pinHeld = false, tickFrame = 0;
  const $ = id => document.getElementById(id);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function message(text, error = false) {
    $('map-status').textContent = text;
    $('map-status').classList.toggle('map-error', error);
  }
  function init() {
    if (map) return map;
    if (!window.maplibregl) throw Error('此瀏覽器無法啟用 3D 地圖，請使用支援 WebGL 的瀏覽器。');
    map = new maplibregl.Map({
      container: 'city-map', style: '/static/street-map-style.json?v=20261103-minimal',
      center: [120.64735,24.22105], zoom: 14.8, pitch: 58, bearing: -25,
      maxPitch: 75, attributionControl: false,
      localIdeographFontFamily: 'sans-serif',
    });
    map.addControl(new maplibregl.AttributionControl({compact:false}), 'bottom-right');
    map.addControl(new maplibregl.NavigationControl({visualizePitch:true}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({unit:'metric'}), 'bottom-left');
    map.on('error',()=>message('部分地圖資料載入失敗；請確認網路後重試。',true));
    map.on('pitch',tiltPin);
    // MapLibre only tracks window resizes; the sidebar changes the map's width on its own.
    new ResizeObserver(()=>map.resize()).observe($('city-map'));
    map.on('load',()=>{
      mapReady=true;
      map.setLight({anchor:'viewport',color:'#ffffff',intensity:0.42,position:[1.5,160,45]});
      document.dispatchEvent(new CustomEvent('streetmap:ready'));
      if (currentLocation) go(currentLocation);
    });
    $('map-rotate').addEventListener('click',()=>map.easeTo({bearing:map.getBearing()+45,duration:reduced?0:700}));
    $('map-home').addEventListener('click',()=>{if(currentLocation)go(currentLocation);});
    $('map-flat').addEventListener('click',()=>{
      const flat=map.getPitch()>10;map.easeTo({pitch:flat?0:58,duration:reduced?0:700});
      $('map-flat').textContent=flat?'立體 3D':'平面 2D';
    });
    $('map-retry').addEventListener('click',()=>{
      if(window.streetMap.selected) window.streetMap.locate(...window.streetMap.selected);
    });
    return map;
  }
  function closeCompany(restoreFocus=false) {
    companyPopup?.remove();
    if(restoreFocus)marker?.getElement().focus({preventScroll:true});
  }
  function openCompany(data) {
    if(companyPopup)return;
    document.dispatchEvent(new CustomEvent('streetmap:company-open'));
    const card=$('company-card-popup');
    card.hidden=false;$('city-stage').classList.add('company-popup-open');
    const anchor=popupAnchor(card,map.project(data.coordinates));
    companyPopup=new maplibregl.Popup({closeButton:false,closeOnClick:false,anchor,offset:25,maxWidth:'310px',focusAfterOpen:false})
      .setLngLat(data.coordinates).setDOMContent(card).addTo(map);
    marker.getElement().setAttribute('aria-expanded','true');
    companyPopup.on('close',()=>{
      card.hidden=true;card.style.maxHeight='';$('city-stage').classList.remove('company-popup-open');$('city-stage').append(card);companyPopup=null;
      marker?.getElement().setAttribute('aria-expanded','false');
    });
    $('close-company-window').focus({preventScroll:true});
  }
  // Picks the first side with room so the map never has to move to make space for the card.
  function popupAnchor(card,{x,y}) {
    const {clientWidth:width,clientHeight:height}=map.getContainer();
    const toolbar=document.querySelector('.map-toolbar');
    // bottom keeps the scale and the required map attribution uncovered.
    const edge=12, bottom=52, top=toolbar.offsetTop+toolbar.offsetHeight+edge, gap=25, diagonal=18;
    // Same cap as the popup's CSS max-height.
    const w=Math.min(card.offsetWidth,310), h=Math.min(card.scrollHeight,480,innerHeight-230);
    const spots={
      bottom:[x-w/2,y-gap-h], left:[x+gap,y-h/2], right:[x-gap-w,y-h/2], top:[x-w/2,y+gap],
      'bottom-left':[x+diagonal,y-diagonal-h], 'bottom-right':[x-diagonal-w,y-diagonal-h],
      'top-left':[x+diagonal,y+diagonal], 'top-right':[x-diagonal-w,y+diagonal],
    };
    const fits=([left,up])=>left>=edge&&up>=top&&left+w<=width-edge&&up+h<=height-bottom;
    const anchor=Object.keys(spots).find(name=>fits(spots[name]));
    if(anchor)return anchor;
    // Nothing fits (common on phones): take the taller side and let the card scroll inside it.
    const above=y-gap-top, below=height-bottom-y-gap;
    card.style.maxHeight=Math.max(above,below)+'px';
    return above>=below?'bottom':'top';
  }
  function growBuildings() {
    cancelAnimationFrame(animationFrame);
    if (reduced || !map.getLayer('radar-buildings-3d')) return;
    const started=performance.now();
    const tick=now=>{
      const fraction=Math.min(1,(now-started)/1300);
      map.setPaintProperty('radar-buildings-3d','fill-extrusion-height', ['*',1-Math.pow(1-fraction,3),['coalesce',['get','render_height'],8]]);
      if(fraction<1)animationFrame=requestAnimationFrame(tick);
    };
    animationFrame=requestAnimationFrame(tick);
  }
  function dropPin(pin) {
    if(!pin||pin!==marker)return;
    const element=pin.getElement();
    element.classList.remove('pin-waiting');element.classList.add('pin-drop');
    showReadouts();
  }
  function coordinateText(lat,lng) { return `${lat.toFixed(5)}° N, ${lng.toFixed(5)}° E`; }
  // Both readouts count up once and always finish on the real value.
  function showReadouts() {
    if(!currentLocation)return;
    const [lng,lat]=currentLocation.coordinates, chip=$('map-hud-coords');
    chip.hidden=false;
    cancelAnimationFrame(tickFrame);
    if(reduced){chip.textContent=coordinateText(lat,lng);return;}
    const scale=map.getContainer().querySelector('.maplibregl-ctrl-scale');
    const reading=scale?.textContent.match(/^([\d.]+)\s*(\S+)/);
    // Moving the map rewrites the scale, so hand it straight back to MapLibre.
    let scaleLive=Boolean(reading);
    map.once('movestart',()=>{scaleLive=false;});
    const started=performance.now();
    const step=now=>{
      const fraction=Math.min(1,(now-started)/900), eased=1-Math.pow(1-fraction,3);
      chip.textContent=coordinateText(lat*eased,lng*eased);
      if(scaleLive)scale.textContent=fraction<1?`${Math.round(reading[1]*eased)} ${reading[2]}`:reading[0];
      if(fraction<1)tickFrame=requestAnimationFrame(step);
    };
    tickFrame=requestAnimationFrame(step);
  }
  // Ground effects tilt with the camera; the beam shortens to nothing when viewed from directly above.
  function tiltPin() {
    if(!marker)return;
    const pitch=map.getPitch(), {style}=marker.getElement();
    style.setProperty('--pitch',pitch+'deg');
    style.setProperty('--beam',Math.sin(pitch*Math.PI/180).toFixed(3));
  }
  function go(data) {
    if (!mapReady) return;
    closeCompany();
    marker?.remove();
    const dot=document.createElement('button');dot.className='real-map-pin';dot.type='button';dot.setAttribute('aria-label',data.label+'，開啟企業情境');dot.setAttribute('aria-expanded','false');dot.setAttribute('aria-controls','company-card-popup');
    dot.innerHTML='<span class="real-map-pin-grid"></span><span class="real-map-pin-ground"><span class="real-map-pin-wave"></span><span class="real-map-pin-wave"></span><span class="real-map-pin-wave"></span></span><span class="real-map-pin-beam"></span><svg class="real-map-pin-core" viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="10.5"/><path d="M18 2v9M18 25v9M2 18h9M25 18h9"/><circle class="real-map-pin-dot" cx="18" cy="18" r="2.6"/></svg>';
    dot.addEventListener('click',()=>openCompany(data));
    const pin=marker=new maplibregl.Marker({element:dot,anchor:'center'}).setLngLat(data.coordinates).addTo(map);
    tiltPin();
    if(reduced)showReadouts();
    else {
      dot.classList.add('pin-waiting');
      if(!pinHeld)map.once('moveend',()=>dropPin(pin));
    }
    map.flyTo({center:data.coordinates,zoom:16.7,pitch:58,bearing:-25,duration:reduced?0:1800,essential:false});
    growBuildings();
    message('已定位道路 · 拖曳移動，右鍵拖曳旋轉');
    $('map-coordinates').textContent=`${data.coordinates[1].toFixed(5)}° N, ${data.coordinates[0].toFixed(5)}° E`;
    $('map-source').href=data.source_url;$('map-source').hidden=false;
    $('pin-precision').textContent=data.limitation;
    document.dispatchEvent(new CustomEvent('streetmap:location',{detail:data}));
  }
  window.streetMap={
    selected:null,
    closeCompany(restoreFocus=true){closeCompany(restoreFocus);},
    getMap(){return mapReady?map:null;},
    getLocation(){return currentLocation?{...currentLocation}:null;},
    popupAnchor(card,coordinates){return popupAnchor(card,map.project(coordinates));},
    // Keeps the map and pin hidden behind the radar until the entrance has faded away.
    hold(){
      if(reduced)return;
      pinHeld=true;$('city-stage').classList.add('map-pending');
    },
    reveal(){
      if(!pinHeld)return;
      const stage=$('city-stage');
      stage.classList.remove('map-pending');stage.classList.add('map-reveal');
      setTimeout(()=>{stage.classList.remove('map-reveal');pinHeld=false;dropPin(marker);},1000);
    },
    async locate(district,road) {
      this.selected=[district,road];
      const request=++revision;
      document.dispatchEvent(new CustomEvent('streetmap:location-changing'));
      currentLocation=null;closeCompany();marker?.remove();$('map-source').hidden=true;
      cancelAnimationFrame(tickFrame);$('map-hud-coords').hidden=true;
      $('map-coordinates').textContent='定位中';
      $('pin-precision').textContent='正在查詢相符的行政區與道路座標…';
      message('正在定位道路…');
      try {
        init();
        const response=await fetch('/api/map/location?'+new URLSearchParams({district,road}));
        const data=await response.json();
        if(request!==revision)return;
        if(!response.ok)throw Error(data.detail||'道路定位暫時不可用');
        if(!data.coordinates)throw Error(data.reason||'找不到此道路的座標');
        currentLocation=data;
        go(data);
      } catch(error) {
        if(request!==revision)return;
        document.dispatchEvent(new CustomEvent('streetmap:location-error',{detail:error.message}));
        message(error.message,true);$('map-coordinates').textContent='未定位';
        $('pin-precision').textContent='目前未能定位選定道路，地圖保留原視角，沒有放置紅點。';
      }
    }
  };
})();
