/* Report views render server-owned claims as text. No model/source HTML is executed. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = String(text);
    if (cls) result.className = cls;
    return result;
  };
  const setText = (id, text) => { $(id).textContent = text; };
  const list = value => Array.isArray(value) ? value : [];
  const amount = value => value && typeof value === 'object' ? value.amount : value;
  const textValue = value => {
    const raw = amount(value);
    if (raw === null || raw === undefined || raw === '') return '未知';
    const numeric = Number(raw);
    return Number.isFinite(numeric) ? new Intl.NumberFormat('zh-TW', {maximumFractionDigits: 4}).format(numeric) : String(raw);
  };
  const monthNumber = value => {
    const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value || '');
    return match ? Number(match[1]) * 12 + Number(match[2]) - 1 : null;
  };
  const timestamp = value => {
    if (!value) return '未記錄';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : `${new Intl.DateTimeFormat('zh-TW', {timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(date)}（臺北時間）`;
  };
  const units = {person: '人', people: '人', posting: '筆', company: '家公司', company_name: '個公司名稱', factory: '家工廠', TWD: '元', percent: '%', ratio: ''};
  function showError(id, message) { setText(id, message); $(id).hidden = false; }
  function readableError(data, status) {
    const detail = data?.detail ?? data;
    if (detail?.error_code === 'RENDER_CONTRACT_INCOMPATIBLE') return '報告顯示規則已更新。原報告仍可閱讀與匯出，請建立新版報告後追問。';
    if (status === 409) return '資料期別確認已過期或條件已變更。請重新確認期別後建立報告。';
    if (status === 410) return '這份報告已過保存期限，請建立新報告查看目前可用資料。';
    if (status === 404) return '找不到這份報告，請檢查網址或建立新報告。';
    if (Array.isArray(detail)) return '輸入條件有誤，請確認地區、月份順序與招募人數後重試。';
    if (typeof detail === 'string' && detail.length < 500) return detail;
    if (typeof detail?.reason === 'string') return detail.reason;
    if (status === 503) return '服務暫時無法讀取或保存資料，請稍後重試。這次沒有以預設數字補位。';
    return `服務未完成這次操作（HTTP ${status}），請稍後重試。`;
  }
  async function request(path, options = {}, timeoutMs = 20000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {...options, signal: controller.signal, cache: 'no-store'});
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const error = new Error(readableError(data, response.status));
        error.status = response.status;
        throw error;
      }
      if (!data || typeof data !== 'object') throw new Error('服務沒有回傳可讀取的資料，請重試。');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('讀取逾時，請稍後重試；目前畫面不會以未核對的結果補位。');
      if (error instanceof TypeError) throw new Error('無法連線至服務，請確認本機伺服器或網路連線後重試。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  const jsonPost = body => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const uniqueKey = () => globalThis.crypto?.randomUUID?.() || `report-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  function addPeriod(dl, label, value) {
    dl.append(node('dt', label), node('dd', value === null || value === undefined || value === '' ? '目前無可用期別' : value));
  }
  function periodText(period) {
    if (!period) return null;
    if (typeof period === 'string') return period;
    if (period.start && period.end) return period.start === period.end ? period.start : `${period.start} ～ ${period.end}`;
    return period.snapshot_date || period.period || period.month || null;
  }
  function renderPeriods(box, periods) {
    box.replaceChildren();
    addPeriod(box, '公開職缺快照', periodText(periods?.jobs));
    addPeriod(box, '區域公司事件', periodText(periods?.gcis_local || periods?.local_observation_window));
    const city = periods?.gcis_city || periods?.city_background_comparison_windows;
    addPeriod(box, '全市公司新設背景', periodText(city));
    if (city?.baseline_start) addPeriod(box, '全市背景對照期', `${city.baseline_start} ～ ${city.baseline_end}`);
    if (periods?.factory) addPeriod(box, '工廠快照', periodText(periods.factory));
    if (periods?.wage) addPeriod(box, '平均投保薪資', periodText(periods.wage));
  }
  function describeScenario(scenario, divisionName = '') {
    const places = list(scenario?.districts).join('、');
    const code = scenario?.manufacturing?.division_code;
    const occupation = scenario?.occupation?.keyword || '';
    const plan = scenario?.hiring_plan;
    return `${places} · ${divisionName || `製造業中類 ${code || '未指定'}`} · 職務「${occupation}」${plan ? ` · 規劃 ${plan.net_hires} 人，${plan.start_month} ～ ${plan.end_month}` : ''}`;
  }

  async function setupComparison() {
    let catalog;
    let resolution = null;
    let buildKey = null;
    let generation = 0;
    const form = $('comparison-form');
    const fields = $('scenario-fields');
    function invalidate() {
      generation += 1;
      resolution = null;
      buildKey = null;
      $('resolution').hidden = true;
      $('compare-error').hidden = true;
      setText('compare-status', '條件變更後，請重新確認資料期別。');
    }
    function observationMode() {
      const fixed = $('observation-mode').value === 'FIXED_MONTH';
      $('observation-month-field').hidden = !fixed;
      $('observation-month').required = fixed;
    }
    function scenarioFromForm() {
      const districts = [1,2,3].map(i => $(`district-${i}`).value).filter(Boolean);
      if (districts.length < 2 || new Set(districts).size !== districts.length) throw new Error('請選擇2～3個不同的行政區。');
      const keyword = $('occupation').value.trim();
      if (!keyword) throw new Error('請填入要比較的職稱或職類關鍵字。');
      const start = monthNumber($('hiring-start').value);
      const end = monthNumber($('hiring-end').value);
      if (start === null || end === null || end < start || end - start >= 12) throw new Error('招募完成月份不能早於開始月份，含起迄最多12個月。');
      const count = Number($('net-hires').value);
      if (!Number.isInteger(count) || count < 1 || count > 100000) throw new Error('預計淨新增到職人數請填1～100,000的整數。');
      return {
        schema_version: '1.0', districts,
        manufacturing: {division_code: $('division').value, classification_version: catalog.classification_version},
        occupation: {type: 'KEYWORD', keyword, retrieval_profile_version: catalog.retrieval_profile_version},
        observation: {mode: $('observation-mode').value, month: $('observation-mode').value === 'FIXED_MONTH' ? $('observation-month').value : null, window_months: Number($('window-months').value), knowledge_cutoff: null},
        hiring_plan: {net_hires: count, start_month: $('hiring-start').value, end_month: $('hiring-end').value},
      };
    }
    function restoreScenario(scenario) {
      if (!scenario) return;
      [1,2,3].forEach(i => { $(`district-${i}`).value = scenario.districts?.[i - 1] || ''; });
      $('division').value = scenario.manufacturing?.division_code || '29';
      $('occupation').value = scenario.occupation?.keyword || '';
      $('observation-mode').value = scenario.observation?.mode || 'LATEST_AVAILABLE';
      $('observation-month').value = scenario.observation?.month || '';
      $('window-months').value = String(scenario.observation?.window_months || 3);
      $('net-hires').value = scenario.hiring_plan?.net_hires ?? 31;
      $('hiring-start').value = scenario.hiring_plan?.start_month || '';
      $('hiring-end').value = scenario.hiring_plan?.end_month || '';
      observationMode();
    }
    async function loadOptions() {
      fields.disabled = true;
      $('retry-options').hidden = true;
      $('compare-error').hidden = true;
      setText('options-status', '正在載入可比較的地區與資料期別…');
      try {
        catalog = await request('/api/comparison-options');
        if (!list(catalog.districts).length || !list(catalog.manufacturing_divisions).length || !catalog.classification_version || !catalog.retrieval_profile_version) throw new Error('可用比較選項不完整，請稍後重新載入。');
        const defaults = catalog.defaults || {};
        [1,2,3].forEach(i => {
          const select = $(`district-${i}`); select.replaceChildren();
          if (i === 3) select.append(new Option('不加入第三區', ''));
          catalog.districts.forEach(d => select.append(new Option(d, d)));
          select.value = defaults.districts?.[i - 1] || (i === 3 ? '' : catalog.districts[i - 1]);
        });
        $('division').replaceChildren();
        catalog.manufacturing_divisions.forEach(d => $('division').append(new Option(`${d.code} ${d.name}`, d.code)));
        $('division').value = defaults.division_code || '29';
        $('occupation').value = defaults.occupation_keyword || 'CNC';
        $('window-months').replaceChildren();
        list(catalog.window_months).forEach(m => $('window-months').append(new Option(`${m}個月`, String(m))));
        $('window-months').value = '3';
        $('hiring-start').value = defaults.hiring_start_month || '';
        $('hiring-end').value = defaults.hiring_end_month || '';
        const months = list(catalog.observation_months).filter(m => monthNumber(m) !== null).sort();
        if (months.length) $('observation-month').value = months[months.length - 1];
        const from = new URLSearchParams(window.location.search).get('from');
        if (from) {
          try { const old = await request(`/api/reports/${encodeURIComponent(from)}`); restoreScenario(old.scenario); }
          catch (error) { showError('compare-error', `原報告條件無法載入：${error.message} 你仍可重新設定條件。`); }
        }
        observationMode();
        fields.disabled = false;
        setText('options-status', '選擇條件後，先確認各來源會使用的期別。');
      } catch (error) {
        showError('compare-error', error.message);
        $('retry-options').hidden = false;
        setText('options-status', '尚未取得可用選項，請重新載入。');
      }
    }
    form.addEventListener('input', invalidate);
    form.addEventListener('change', () => { invalidate(); observationMode(); });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      $('compare-error').hidden = true;
      let scenario;
      try { scenario = scenarioFromForm(); }
      catch (error) { showError('compare-error', error.message); return; }
      const current = ++generation;
      resolution = null;
      $('resolution').hidden = true;
      fields.disabled = true;
      setText('resolve-submit', '正在確認期別…');
      setText('compare-status', '正在固定資料版本，尚未建立報告…');
      try {
        const data = await request('/api/reports/expansion-comparison/resolve', jsonPost(scenario));
        if (current !== generation) return;
        if (!data.resolution_token || !data.scenario) throw new Error('資料期別確認不完整，請重新確認。');
        resolution = data; buildKey = uniqueKey();
        const division = catalog.manufacturing_divisions.find(d => d.code === data.scenario.manufacturing?.division_code);
        setText('resolution-scenario', describeScenario(data.scenario, division?.name));
        renderPeriods($('resolved-periods'), data.resolved_periods);
        setText('resolution-expiry', data.expires_at ? `這次期別確認有效至 ${timestamp(data.expires_at)}；逾期可重新確認。` : '建立報告時會使用這次已固定的資料版本。');
        $('resolution').hidden = false;
        $('resolution').focus();
        setText('compare-status', '請確認期別；缺少的資料會在報告中如實標示。');
      } catch (error) { if (current === generation) { showError('compare-error', error.message); setText('compare-status', '期別尚未確認，請重試。'); } }
      finally { if (current === generation) { fields.disabled = false; setText('resolve-submit', '確認資料期別'); } }
    });
    $('build-report').addEventListener('click', async () => {
      if (!resolution) { showError('compare-error', '請先重新確認資料期別。'); return; }
      const current = generation;
      $('build-report').disabled = true; $('edit-scenario').disabled = true; fields.disabled = true;
      $('compare-error').hidden = true;
      setText('build-report', '正在保存報告…');
      setText('compare-status', '正在建立並保存比較報告；資料未知時仍會保留原因。');
      try {
        const options = jsonPost({scenario: resolution.scenario, resolution_token: resolution.resolution_token});
        options.headers['Idempotency-Key'] = buildKey;
        const report = await request('/api/reports/expansion-comparison', options, 30000);
        if (!report.report_id) throw new Error('服務沒有回傳已保存的報告編號，請重試。');
        window.location.assign(`/reports/${encodeURIComponent(report.report_id)}`);
      } catch (error) {
        showError('compare-error', error.message);
        setText('compare-status', '尚未開啟新報告；重試會沿用同一次建立識別碼。');
        if (error.status === 409) { resolution = null; $('resolution').hidden = true; }
      } finally {
        if (current === generation) { $('build-report').disabled = false; $('edit-scenario').disabled = false; fields.disabled = false; setText('build-report', '使用這些期別建立報告'); }
      }
    });
    $('edit-scenario').addEventListener('click', () => { invalidate(); $('district-1').focus(); });
    $('retry-options').addEventListener('click', loadOptions);
    await loadOptions();
  }

  async function setupReport() {
    const parts = window.location.pathname.split('/').filter(Boolean);
    let reportId;
    try { reportId = parts[0] === 'reports' ? decodeURIComponent(parts[1] || '') : new URLSearchParams(window.location.search).get('id'); }
    catch { reportId = null; }
    let report;
    let evidenceMap = new Map();
    const rootPath = `/api/reports/${encodeURIComponent(reportId || '')}`;
    function evidenceLink(id, label = '查證紀錄') {
      const target = evidenceMap.get(id);
      if (!target) return node('span', label, 'help');
      const link = node('a', label); link.href = `#${target}`;
      link.addEventListener('click', () => { const detail = $(target); if (detail) detail.open = true; });
      return link;
    }
    function renderBlocks(box, blocks, emptyText) {
      box.replaceChildren();
      list(blocks).forEach(block => {
        const text = typeof block === 'string' ? block : block?.text;
        if (!text) return;
        const item = node('div', null, 'block');
        item.append(node('p', text, block?.type === 'disclosure' ? 'block-note' : undefined));
        if (list(block.evidence_ids).length) {
          const refs = node('div', null, 'evidence-links');
          block.evidence_ids.forEach((id, i) => refs.append(evidenceLink(id, `查證 ${i + 1}`)));
          item.append(refs);
        }
        box.append(item);
      });
      if (!box.childElementCount && emptyText) box.append(node('p', emptyText, 'block-note'));
    }
    function safeSourceLink(value) {
      try {
        const url = new URL(value);
        if (url.protocol !== 'https:' || !(url.hostname === 'gov.tw' || url.hostname.endsWith('.gov.tw'))) return node('span', value);
        const a = node('a', value); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
      } catch { return node('span', String(value)); }
    }
    function renderEvidence(content) {
      const box = $('report-evidence'); box.replaceChildren(); evidenceMap = new Map();
      list(content.evidence).forEach((ev, i) => {
        const id = `evidence-${i + 1}`;
        if (ev.evidence_id) evidenceMap.set(ev.evidence_id, id);
        const detail = node('details', null, 'evidence-detail'); detail.id = id;
        const fact = list(content.facts).find(f => list(f.evidence_ids).includes(ev.evidence_id));
        const place = fact?.subject?.district;
        const period = periodText(fact?.period);
        const title = [ev.source_name || ev.indicator || ev.dataset_id || `來源紀錄 ${i + 1}`, place, period].filter(Boolean).join(' · ');
        detail.append(node('summary', title));
        const body = node('div', null, 'evidence-body');
        if (ev.fetched_at) body.append(node('p', `資料取得時間：${timestamp(ev.fetched_at)}`));
        if (fact?.selection) body.append(node('p', `分類／篩選版本：${fact.selection.classification_version || '未記錄'}`));
        const sources = [...list(ev.source_urls), ...(ev.source_url ? [ev.source_url] : [])];
        sources.forEach(url => { const p = node('p'); p.append(safeSourceLink(url)); body.append(p); });
        const limitations = list(ev.limitations);
        if (limitations.length) { const ul = node('ul'); limitations.forEach(item => ul.append(node('li', item))); body.append(ul); }
        const raw = node('details'); raw.append(node('summary', '欄位、計算與版本紀錄'));
        raw.append(node('pre', JSON.stringify(ev, null, 2))); body.append(raw);
        detail.append(body); box.append(detail);
      });
      if (!box.childElementCount) box.append(node('p', '這份報告目前沒有可用查證紀錄；不可將缺資料視為已核驗。', 'block-note'));
    }
    function renderGroups(content) {
      const box = $('metric-groups'); box.replaceChildren();
      list(content.metric_groups).forEach(group => {
        const rows = list(group.rows);
        if (!rows.some(row => row.district) || /plan|hiring/i.test(group.metric_id || '')) return;
        const section = node('div', null, 'metric-section');
        section.append(node('h3', group.label || '資料指標'));
        const wrap = node('div', null, 'table-wrap'); wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', `${group.label || '指標'}比較表，可水平捲動`);
        const table = node('table', null, 'comparison-table');
        const descriptive = group.comparison_status !== 'COMPARABLE_SAMPLE';
        table.append(node('caption', descriptive ? '僅描述各區已觀測資料；本列不作地點排名或推定招募難易。' : '相同資料期別與篩選下的公開樣本，不代表全部市場。'));
        const head = node('thead'); const hr = node('tr');
        const first = node('th', '比較項目'); first.scope = 'col'; hr.append(first);
        list(report.scenario?.districts).forEach(d => { const th = node('th', d); th.scope = 'col'; hr.append(th); }); head.append(hr); table.append(head);
        const body = node('tbody'); const tr = node('tr'); const label = node('th', group.label || '觀測值'); label.scope = 'row'; tr.append(label);
        report.scenario.districts.forEach(district => {
          const row = rows.find(r => r.district === district);
          const td = node('td');
          const unknown = !row || row.value_status === 'UNKNOWN' || amount(row.value) == null;
          const lower = row?.value_status === 'LOWER_BOUND';
          const value = unknown ? '未知' : `${lower ? '至少 ' : ''}${textValue(row.value)}${units[group.unit] ? ` ${units[group.unit]}` : ''}`;
          td.append(node('span', value, `metric-value${unknown ? ' unknown' : ''}`));
          if (lower) td.append(node('small', '來源涵蓋有限，不作排名', 'value-help'));
          if (row?.value_status === 'SAMPLE_MATCH_ZERO') td.append(node('small', '本樣本無匹配；不代表沒有需求或同業', 'value-help'));
          if (unknown) td.append(node('small', '目前缺少足以呈現的資料', 'value-help'));
          const fact = list(content.facts).find(f => f.fact_id === row?.fact_id);
          const factEvidence = list(fact?.evidence_ids);
          const evidenceIds = factEvidence.length ? factEvidence : list(row?.evidence_ids);
          evidenceIds.forEach(id => td.append(evidenceLink(id)));
          tr.append(td);
        });
        body.append(tr); table.append(body); wrap.append(table); section.append(wrap); box.append(section);
      });
      if (!box.childElementCount) box.append(node('p', '目前沒有可用的跨區觀測列。請查看下方資料缺口，或修改條件建立新報告。', 'notice'));
    }
    function renderCity(content) {
      const box = $('city-context');
      const blocks = list(content.summary_blocks).filter(b => b.district === null && b.heading_id !== 'NEXT_STEPS' && (/^gcis\.city/.test(b.metric_id || '') || b.heading_id === 'COMMON_BACKGROUND'));
      if (blocks.length) { renderBlocks(box, blocks); return; }
      box.replaceChildren();
      box.append(node('p', '目前沒有核准的共同背景資料；未通過事實與期別檢查的原始值不會補入報告。', 'block-note'));
    }
    function summaryHighlights(content) {
      const blocks = list(content.summary_blocks).filter(b => b.type === 'claim' && ['PUBLIC_JOB_OBSERVATIONS', 'GCIS_CONTEXT'].includes(b.heading_id));
      const selected = [];
      const add = block => { if (block && !selected.includes(block)) selected.push(block); };
      add(blocks.find(b => /^GS0[12]/.test(b.rule_id || '')));
      const comparisonIds = new Set(list(content.claims).filter(c => c.type === 'COMPARISON' || c.type === 'DIFFERENCE').map(c => c.claim_id));
      add(blocks.find(b => comparisonIds.has(b.claim_id)) || blocks.find(b => b.heading_id === 'PUBLIC_JOB_OBSERVATIONS'));
      add(blocks.find(b => /^gcis\.local/.test(b.metric_id || '')));
      blocks.forEach(b => { if (selected.length < 3) add(b); });
      return selected.slice(0, 3);
    }
    function renderPlanning() {
      const plan = report.scenario?.hiring_plan;
      setText('plan-summary', plan ? `你規劃在 ${plan.start_month} ～ ${plan.end_month} 淨新增到職 ${textValue(plan.net_hires)} 人。` : '這份報告沒有可用的企業招募計畫。');
      const box = $('planning-months'); box.replaceChildren();
      list(report.planning?.monthly_targets).forEach(target => { const dl = node('dl', null, 'plan-month'); dl.append(node('dt', target.month), node('dd', `${textValue(target.people)} 人`)); box.append(dl); });
      if (!box.childElementCount) box.append(node('p', '目前沒有可用的每月目標分配。', 'help'));
    }
    function present(data) {
      report = data;
      const content = report.content || {};
      renderEvidence(content);
      setText('report-scenario', describeScenario(report.scenario));
      const statusNames = {USABLE: '可用資料報告', LIMITED: '部分資料可用', UNAVAILABLE: '官方資料目前不足'};
      const badge = node('span', statusNames[report.data_status] || '請查看各資料組限制', `badge${report.data_status === 'USABLE' ? '' : ' warn'}`);
      $('report-badges').replaceChildren(badge, node('span', '固定快照 · 不隨後續更新改寫', 'badge'));
      setText('report-meta', `建立時間 ${timestamp(report.created_at)} · 報告編號 ${report.report_id}`);
      const periods = report.manifest?.resolved_periods || report.resolved_periods || report.manifest?.periods || {};
      renderPeriods($('report-periods'), periods);
      if (report.scenario?.observation?.mode === 'FIXED_MONTH') {
        $('historical-notice').hidden = false;
        setText('historical-notice', `回看 ${report.scenario.observation.month} 的觀測期，使用目前留存版本；不是重現當時已知資訊。分類標籤與取得時間請查看查證紀錄。`);
      } else $('historical-notice').hidden = true;
      renderBlocks($('summary-blocks'), summaryHighlights(content), '這份報告尚無足夠資料產生比較摘要；請查看已保存的觀測值與資料缺口。');
      renderGroups(content); renderCity(content); renderPlanning();
      renderBlocks($('next-actions'), list(content.summary_blocks).filter(b => b.heading_id === 'NEXT_STEPS'), '這份報告目前沒有可用的下一步查證主張。');
      renderBlocks($('report-disclosures'), content.disclosures, '公開職缺不等於實際缺工；公司事件不代表招聘計畫。無法由這些資料推算單一企業招募成功率。');
      $('edit-report').href = `/compare?from=${encodeURIComponent(report.report_id)}`;
      $('print-report').href = `${rootPath}/export?format=html`;
      $('download-report').href = `${rootPath}/export?format=json`;
      $('report').hidden = false; $('report-status').hidden = true; $('report-recovery').hidden = true;
      document.title = `${list(report.scenario?.districts).join('、')}招募環境報告｜產業人才雷達`;
    }
    async function loadReport() {
      $('report-error').hidden = true; $('report-status').hidden = false; $('report-recovery').hidden = true;
      setText('report-status', '正在讀取已保存的報告…');
      try {
        if (!reportId) throw new Error('網址缺少報告編號，請建立新報告。');
        present(await request(rootPath));
      } catch (error) {
        $('report').hidden = true; $('report-recovery').hidden = false;
        showError('report-error', error.message); setText('report-status', '報告尚未載入。');
        $('retry-report').hidden = error.status === 410 || error.status === 404 || !reportId;
      }
    }
    async function ask(question) {
      const value = question.trim();
      if (!value || !report) return;
      $('question-error').hidden = true; $('question-answer').hidden = true;
      $('question-submit').disabled = true;
      document.querySelectorAll('.suggestion').forEach(button => { button.disabled = true; });
      setText('question-status', '正在依這份報告整理解說…');
      try {
        const result = await request(`${rootPath}/questions`, jsonPost({question: value}), 25000);
        if (!Array.isArray(result.blocks)) throw new Error('這次沒有可顯示的受控解說，請稍後重試。');
        setText('asked-question', `你的問題：${value}`);
        const labels = {VERIFIED: '依核准主張整理', FALLBACK: '使用標準解說', BLOCKED: '本次未作答'};
        $('answer-badges').replaceChildren(node('span', labels[result.ai_status] || '請依報告資料解讀', `badge${result.ai_status === 'VERIFIED' ? '' : ' warn'}`));
        renderBlocks($('answer-blocks'), result.blocks, '這份報告目前沒有足以回答該問題的核准資料。');
        setText('answer-meta', result.request_id ? `解說查證編號：${result.request_id}` : '解說與本報告使用相同資料版本。');
        $('question-answer').hidden = false;
        setText('question-status', result.ai_status === 'FALLBACK' ? '模型暫不可用或未通過驗證，已提供標準解說；報告與匯出仍可使用。' : '解說已完成。');
      } catch (error) { showError('question-error', error.message); setText('question-status', '解說未完成；上方報告與匯出仍可使用。'); }
      finally { $('question-submit').disabled = false; document.querySelectorAll('.suggestion').forEach(button => { button.disabled = false; }); }
    }
    $('retry-report').addEventListener('click', loadReport);
    $('question-form').addEventListener('submit', event => { event.preventDefault(); if (event.target.reportValidity()) ask($('question').value); });
    document.querySelectorAll('.suggestion').forEach(button => button.addEventListener('click', () => { $('question').value = button.textContent; ask(button.textContent); }));
    await loadReport();
  }
  if (document.body.dataset.page === 'compare') setupComparison();
  if (document.body.dataset.page === 'report') setupReport();
})();
