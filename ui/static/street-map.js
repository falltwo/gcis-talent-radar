/* Real OpenStreetMap vector geometry rendered by MapLibre. */
(() => {
  let map, marker, revision = 0, currentLocation, mapReady = false;
  let animationFrame = 0;
  let companyPopup = null;
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
      container: 'city-map', style: '/static/street-map-style.json?v=20261102-3',
      center: [120.64735,24.22105], zoom: 14.8, pitch: 58, bearing: -25,
      maxPitch: 75, attributionControl: false,
      localIdeographFontFamily: 'sans-serif',
    });
    map.addControl(new maplibregl.AttributionControl({compact:false}), 'bottom-right');
    map.addControl(new maplibregl.NavigationControl({visualizePitch:true}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({unit:'metric'}), 'bottom-left');
    map.on('error',()=>message('部分地圖資料載入失敗；請確認網路後重試。',true));
    map.on('load',()=>{
      mapReady=true;
      map.setLight({anchor:'viewport',color:'#ffffff',intensity:0.42,position:[1.5,160,45]});
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
    companyPopup=new maplibregl.Popup({closeButton:false,closeOnClick:false,anchor:'bottom',offset:25,maxWidth:'310px',focusAfterOpen:false})
      .setLngLat(data.coordinates).setDOMContent(card).addTo(map);
    marker.getElement().setAttribute('aria-expanded','true');
    companyPopup.on('close',()=>{
      card.hidden=true;$('city-stage').classList.remove('company-popup-open');$('city-stage').append(card);companyPopup=null;
      marker?.getElement().setAttribute('aria-expanded','false');
    });
    // Place the selected point lower in the viewport so the window fits above it.
    map.easeTo({center:data.coordinates,offset:[0,Math.max(0,map.getContainer().clientHeight/2-70)],duration:reduced?0:450});
    $('close-company-window').focus({preventScroll:true});
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
  function go(data) {
    if (!mapReady) return;
    closeCompany();
    marker?.remove();
    const dot=document.createElement('button');dot.className='real-map-pin';dot.type='button';dot.setAttribute('aria-label',data.label+'，開啟企業情境');dot.setAttribute('aria-expanded','false');dot.setAttribute('aria-controls','company-card-popup');
    dot.innerHTML='<span class="real-map-pin-wave"></span><span class="real-map-pin-core"></span>';
    dot.addEventListener('click',()=>openCompany(data));
    marker=new maplibregl.Marker({element:dot,anchor:'center'}).setLngLat(data.coordinates).addTo(map);
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
    async locate(district,road) {
      this.selected=[district,road];
      const request=++revision;
      document.dispatchEvent(new CustomEvent('streetmap:location-changing'));
      currentLocation=null;closeCompany();marker?.remove();$('map-source').hidden=true;
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
