/* Campus-owned camera snapshots; no changes to the shared street-map controls. */
(() => {
  'use strict';
  window.createCampusCamera = (map, reduced, onState = () => {}) => {
    let overview = null, revision = 0, listener = null, timer = null, state = 'overview';
    const emit = next => {state = next; onState(next);};
    function cancel() {
      ++revision; clearTimeout(timer);
      if (listener) map.off('moveend', listener);
      listener = null; map.stop();
    }
    return {
      focus(coordinates) {
        cancel();
        if (!overview) {const c = map.getCenter(); overview = {center: [c.lng, c.lat], zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing(), padding: {...map.getPadding()}};}
        const request = revision; emit('flying');
        const arrive = () => {if (request !== revision) return; clearTimeout(timer); if (listener) map.off('moveend', listener); listener = null; emit('detail');};
        listener = arrive; timer = setTimeout(arrive, 2400); map.once('moveend', arrive);
        map.flyTo({center: coordinates, zoom: 16.5, pitch: 56, bearing: -20, padding: {top: 90, bottom: 70, left: 35, right: 35}, duration: reduced ? 0 : 1350, essential: false});
      },
      restore(instant=false) {cancel(); const previous = overview; overview = null; if (previous) map.easeTo({...previous, duration: reduced||instant ? 0 : 650}); emit('overview');},
      discard() {cancel(); overview = null; emit('overview');},
      getState() {return state;},
    };
  };
})();
