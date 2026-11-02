'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const first = $('needs-form'), review = $('review-form');
  let busy = false;
  function setBusy(value) {
    busy = value;
    for (const id of ['prepare', 'sample', 'approve']) $(id).disabled = value;
  }
  async function request(path, body) {
    let response;
    try { response = await fetch('/api/mock104/' + path, {method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(body), credentials:'same-origin', cache:'no-store'}); }
    catch { throw new Error('無法連線至本機服務，請確認服務已啟動。'); }
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '請檢查必填欄位與薪資範圍。');
    return result;
  }
  async function prepare(mode) {
    if (busy) return;
    if (mode === 'SAMPLE') {
      $('company-name').value = '雷達示範精密工業';
      $('company-intro').value = '虛構精密加工企業，示範 CNC 製造現場的招募流程。';
      $('role').value = 'CNC 操作員';
      $('needs').value = '招募3人，月薪35000至45000元。固定日班08:00–17:00，至少1年CNC經驗。負責機台操作、品質檢查與設備保養，機械製圖可培訓。這是固定範例展示。';
    }
    if (!first.reportValidity()) return;
    setBusy(true); $('error').hidden = true;
    $('status').textContent = mode === 'MODEL' ? 'AI 正在整理公司提供的招募需求，結果仍需 HR 核對…' : '正在載入固定範例，不呼叫 AI…';
    try {
      await request('start', {});
      const result = await request('agent/prepare', {company_name:$('company-name').value, company_intro:$('company-intro').value,
        district:$('district').value, role:$('role').value, needs:$('needs').value, mode});
      for (const [name,value] of Object.entries(result.job)) {
        const input = review.elements.namedItem(name);
        if (input) input.value = Array.isArray(value) ? value.join('、') : value ?? '';
      }
      $('source').textContent = result.source === 'MODEL' ? 'AI 整理，待 HR 檢查' : '固定範例，非 AI 推論';
      $('source').className = 'source' + (result.source === 'MODEL' ? '' : ' sample');
      const names={title:'職缺名稱',district:'工作地區',shift:'班別',headcount:'招募人數',min_experience_months:'最低經驗',salary_min:'月薪下限',salary_max:'月薪上限',description:'工作內容',work_hours:'上班時間',schedule_system:'班制',employment_type:'工作性質'};
      $('review-note').textContent = result.missing_fields.length ? '尚缺欄位：' + result.missing_fields.map(key=>names[key]||key).join('、') + '。請補齊並確認其他內容。' : '請核對公司資訊、薪資、班制、上班時段與工作內容。確認後才會交給 Agent 操作模擬網站。';
      review.hidden = false; $('status').textContent = '整理完成。請在下方編修及確認。';
      review.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    } catch (error) { $('error').textContent=error.message; $('error').hidden=false; $('status').textContent='尚未建立填表工作。'; }
    finally { setBusy(false); }
  }
  first.addEventListener('submit', event => { event.preventDefault(); prepare('MODEL'); });
  $('sample').addEventListener('click', () => prepare('SAMPLE'));
  review.addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    $('r-max').setCustomValidity(Number($('r-max').value)<Number($('r-min').value)?'薪資上限不能低於下限。':'');
    if (!review.reportValidity()) return;
    const job = Object.fromEntries(new FormData(review));
    for (const key of ['salary_min','salary_max','headcount','min_experience_months']) job[key]=Number(job[key]);
    for (const key of ['required_skills','trainable_skills']) job[key]=job[key].split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean);
    const target = $('new-window').checked ? window.open('about:blank','recruitment-agent-demo') : null;
    if ($('new-window').checked && !target) { $('error').textContent='瀏覽器阻擋新視窗，請取消另開視窗後再試。'; $('error').hidden=false; return; }
    setBusy(true); $('error').hidden=true;
    try {
      await request('agent/approve',{job,hr_confirmed:true,confirm_before_publish:$('second-confirm').checked,
        scenario:$('scenario').value,typing_speed:$('speed').value});
      if (target) { target.location.href='/mock104#agent'; target.focus(); $('status').textContent='已交給 Agent，請看另一個視窗的實際填表過程。'; }
      else location.assign('/mock104#agent');
    } catch (error) { if (target) target.close(); $('error').textContent=error.message; $('error').hidden=false; }
    finally { setBusy(false); }
  });
  for (const id of ['r-min','r-max']) $(id).addEventListener('input',()=> $('r-max').setCustomValidity(''));
})();
