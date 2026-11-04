/* District-level map shading. Values describe a whole district, never a building. */
(() => {
  const BLUES = ['#d7e6f8','#a6c9ef','#6da4e0','#3a7bc8','#1b5299'];
  const ORANGES = ['#fde6d3','#f9c49a','#f29a5c','#e26d2c','#b84a14'];
  const UNKNOWN = '#c4c9d1';
  const ALL_FACTORIES = '全部製造業';
  const JOB_OPTIONS = [
    ['all_postings','全部職類・刊登筆數','筆'],
    ['all_openings','全部職類・需求人數','人'],
    ['manufacturing_postings','製造相關職類・刊登筆數','筆'],
    ['manufacturing_openings','製造相關職類・需求人數','人'],
  ];
  const $ = id => document.getElementById(id);
  let stats, map, values = {}, layerOn = false, unit = '家';

  function factoryValue(district, industry) {
    const row = stats.factories.districts[district];
    if (industry !== ALL_FACTORIES) return row[industry] ?? null;
    const known = Object.values(row).filter(count => count !== null);
    return known.length ? known.reduce((sum, count) => sum + count, 0) : null;
  }
  // A district that hit the query cap only has a lower bound, so it cannot be ranked.
  function jobValue(district, metric) {
    if (stats.jobs.capped.includes(district)) return null;
    return stats.jobs.metrics[metric][district] ?? null;
  }
  // Quantile breaks keep the few largest districts from washing out the rest.
  function breaksFor(counts) {
    const sorted = [...counts].sort((a, b) => a - b);
    return [.2, .4, .6, .8].map(share => sorted[Math.floor(share * (sorted.length - 1))]);
  }
  function colorFor(value, breaks, ramp) {
    if (value === null) return UNKNOWN;
    const step = breaks.findIndex(limit => value <= limit);
    return ramp[step < 0 ? ramp.length - 1 : step];
  }
  function showReadout(district) {
    const value = values[district];
    $('district-readout').textContent = !district ? '滑過或點選行政區查看數值'
      : `${district}｜${value === null || value === undefined ? '無資料' : value.toLocaleString() + ' ' + unit}`;
  }
  function render() {
    for (const id of ['district-fill','district-edge','district-glow']) map.setLayoutProperty(id, 'visibility', layerOn ? 'visible' : 'none');
    // Slightly see-through buildings let the ground colour read through them.
    map.setPaintProperty('radar-buildings-3d', 'fill-extrusion-opacity', layerOn ? .72 : .94);
    $('district-panel').hidden = !layerOn;
    $('map-districts').setAttribute('aria-pressed', String(layerOn));
    if (!layerOn) return;
    const [kind, choice] = $('district-industry').value.split(':');
    const jobs = kind === 'jobs';
    const names = Object.keys(stats.factories.districts);
    values = Object.fromEntries(names.map(name => [name, jobs ? jobValue(name, choice) : factoryValue(name, choice)]));
    unit = jobs ? JOB_OPTIONS.find(([key]) => key === choice)[2] : '家';
    const ramp = jobs ? ORANGES : BLUES;
    const counts = Object.values(values).filter(value => value !== null);
    const breaks = breaksFor(counts);
    map.setPaintProperty('district-fill', 'fill-color', ['match', ['get','TOWNNAME'], ...names.flatMap(name => [name, colorFor(values[name], breaks, ramp)]), UNKNOWN]);
    $('district-scale').replaceChildren(...ramp.map(color => {
      const item = document.createElement('span');
      item.style.background = color;
      return item;
    }));
    $('district-low').textContent = (counts.length ? Math.min(...counts) : 0).toLocaleString();
    $('district-high').textContent = Math.max(...counts, 0).toLocaleString() + ' ' + unit;
    $('district-year').textContent = jobs
      ? `${stats.jobs.snapshot_date} 公開刊登快照・行政區層級；刊登不等於缺工`
      : `${stats.factories.year} 年工廠家數・行政區層級，非單棟建物`;
    const source = jobs ? stats.jobs : stats.factories;
    $('district-source').href = source.source_url;
    $('district-source').textContent = source.source;
    showReadout('');
  }
  function fillOptions() {
    const totals = {};
    for (const row of Object.values(stats.factories.districts)) for (const [name, count] of Object.entries(row)) totals[name] = (totals[name] || 0) + (count || 0);
    const factories = document.createElement('optgroup');
    factories.label = `工廠家數（${stats.factories.year} 年）`;
    factories.append(...[ALL_FACTORIES, ...Object.keys(totals).sort((a, b) => totals[b] - totals[a])].map(name => new Option(name, 'factories:' + name)));
    const jobs = document.createElement('optgroup');
    jobs.label = `公開職缺（${stats.jobs.snapshot_date}）`;
    jobs.append(...JOB_OPTIONS.map(([key, label]) => new Option(label, 'jobs:' + key)));
    $('district-industry').append(factories, jobs);
  }
  function districtAt(point) {
    return map.queryRenderedFeatures(point, {layers:['district-fill']})[0]?.properties.TOWNNAME || '';
  }
  async function setup() {
    map = window.streetMap.getMap();
    const [boundaries, loaded] = await Promise.all(['/static/taichung-districts.geojson','/static/district-stats.json'].map(async url => {
      const response = await fetch(url);
      if (!response.ok) throw Error(url);
      return response.json();
    }));
    stats = loaded;
    fillOptions();
    map.addSource('districts', {type:'geojson', data:boundaries});
    map.addLayer({id:'district-fill', type:'fill', source:'districts', paint:{'fill-color':UNKNOWN,'fill-opacity':.42}}, 'building');
    map.addLayer({id:'district-glow', type:'line', source:'districts', paint:{'line-color':'#2f6fbd','line-width':5,'line-blur':4,'line-opacity':.28}}, 'waterway_line_label');
    map.addLayer({id:'district-edge', type:'line', source:'districts', paint:{'line-color':'#3a6ea8','line-width':1,'line-opacity':.65}}, 'waterway_line_label');
    $('district-industry').addEventListener('change', render);
    map.on('mousemove', 'district-fill', event => showReadout(event.features[0]?.properties.TOWNNAME || ''));
    map.on('mouseleave', 'district-fill', () => showReadout(''));
    map.on('click', event => { if (layerOn) showReadout(districtAt(event.point)); });
    $('map-districts').addEventListener('click', () => { layerOn = !layerOn; render(); });
    render();
    $('map-districts').hidden = false;
  }
  // If the data fails to load the button simply never appears; the map keeps working.
  document.addEventListener('streetmap:ready', () => setup().catch(() => {}));
})();
