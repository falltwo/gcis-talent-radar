/* Official snapshot comparison. Values are rendered as text, never interpreted as HTML. */
(() => {
    'use strict';
    const districts = ['中區','東區','南區','西區','北區','西屯區','南屯區','北屯區','豐原區','東勢區','大甲區','清水區','沙鹿區','梧棲區','后里區','神岡區','潭子區','大雅區','新社區','石岡區','外埔區','大安區','烏日區','大肚區','龍井區','霧峰區','太平區','大里區','和平區'];
    const industries = [['','全部工作領域'],['IND_MFG','智慧製造與精密機械'],['IND_ICT','資訊軟體與數位科技'],['IND_SEM','半導體與綠能科技'],['IND_BIOMED','生技醫療與精準健康'],['IND_PRO_FIN','專業商管與金融服務'],['IND_TRADE_LOG','國際貿易與現代物流'],['IND_TOUR_CULT','數位文創與觀光休閒']];
    const el = id => document.getElementById(id);
    const number = value => Number(value).toLocaleString('zh-TW');
    let initialized = false;
    let activated = false;
    let controller;
    let requestId = 0;

    function node(tag, text, className) {
        const result = document.createElement(tag);
        if (text !== undefined) result.textContent = text;
        if (className) result.className = className;
        return result;
    }

    function safeLink(label, value) {
        try {
            const url = new URL(value);
            if (url.protocol !== 'https:' || !['job.taiwanjobs.gov.tw','data.gov.tw'].includes(url.hostname)) return node('span', label);
            const link = node('a', label);
            link.href = url.href;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            return link;
        } catch { return node('span', label); }
    }

    function setLoading(loading) {
        el('comparison-submit').disabled = loading;
        el('comparison-submit').textContent = loading ? '比較中…' : '開始比較';
        el('comparison-loading').hidden = !loading;
        el('comparison-results').setAttribute('aria-busy', String(loading));
    }

    function invalidate() {
        requestId += 1;
        controller?.abort();
        setLoading(false);
        el('comparison-results').hidden = true;
        el('comparison-error').hidden = true;
        el('comparison-status').textContent = '條件已變更，按「開始比較」更新結果。';
    }

    function renderTable(data) {
        const table = node('table', undefined, 'comparison-table');
        table.append(node('caption', '相同工作條件、相同快照日期；以下數值只涵蓋公開刊登樣本。'));
        const head = node('thead');
        const row = node('tr');
        const metricHead = node('th', '比較項目');
        metricHead.scope = 'col';
        row.append(metricHead);
        for (const district of data.comparisons) {
            const th = node('th', district.district);
            th.scope = 'col';
            row.append(th);
        }
        head.append(row);
        table.append(head);
        const body = node('tbody');
        const metrics = [
            ['刊登職缺','vacancy_postings','筆','每一則刊登算一筆'],
            ['刊登需求人數','requested_workers','人','刊登職缺所列的需求加總'],
            ['徵才公司','distinct_companies','家','以公司名稱去重計算'],
        ];
        for (const [label, key, unit, help] of metrics) {
            const tr = node('tr');
            const th = node('th', label);
            th.scope = 'row';
            th.append(node('small', help));
            tr.append(th);
            for (const district of data.comparisons) {
                const td = node('td');
                td.append(node('span', number(district[key]), 'comparison-number'), node('span', unit, 'comparison-unit'));
                tr.append(td);
            }
            body.append(tr);
        }
        const coverage = node('tr');
        const coverageLabel = node('th', '資料涵蓋');
        coverageLabel.scope = 'row';
        coverage.append(coverageLabel);
        for (const district of data.comparisons) {
            const capped = district.coverage_status === 'QUERY_LIMIT_REACHED';
            coverage.append(node('td', capped ? '查詢達上限，僅供下限參考' : '該區已擷取，未達查詢上限', `comparison-coverage${capped ? ' is-capped' : ''}`));
        }
        body.append(coverage);
        table.append(body);
        el('comparison-table-wrap').replaceChildren(table);
    }

    function renderDistrictDetails(data) {
        const fragment = document.createDocumentFragment();
        for (const district of data.comparisons) {
            const detail = node('details', undefined, 'comparison-district-detail');
            detail.append(node('summary', `${district.district}：主要職類與實際職缺（${number(district.vacancy_postings)} 筆刊登）`));
            if (!district.vacancy_postings) {
                detail.append(node('p', '這份快照中沒有符合條件的刊登。可移除關鍵字或改選工作領域後重新比較；零筆不代表當地沒有徵才需求。', 'comparison-empty'));
                fragment.append(detail);
                continue;
            }
            const columns = node('div', undefined, 'comparison-detail-columns');
            const occupations = node('div');
            occupations.append(node('h4', '主要職類（依刊登筆數，最多 5 類）'));
            const occupationList = node('ul', undefined, 'comparison-occupations');
            for (const item of district.top_occupations) {
                const li = node('li');
                li.append(node('span', item.name), node('span', `${number(item.vacancy_postings)} 筆 · ${number(item.requested_workers)} 人`));
                occupationList.append(li);
            }
            occupations.append(occupationList);
            const vacancies = node('div');
            vacancies.append(node('h4', '實際職缺（依需求人數，最多 10 筆）'));
            const vacancyList = node('ul', undefined, 'comparison-vacancies');
            for (const item of district.top_vacancies) {
                const li = node('li');
                li.append(safeLink(item.occupation_title, item.source_url));
                li.append(node('p', `${item.company_name || '公司名稱未提供'} · 刊登需求 ${number(item.openings)} 人`));
                li.append(node('p', `${item.work_location || district.district} · 刊登更新：${item.updated_date || '未提供'}`));
                vacancyList.append(li);
            }
            vacancies.append(vacancyList);
            columns.append(occupations, vacancies);
            detail.append(columns);
            fragment.append(detail);
        }
        el('comparison-details').replaceChildren(fragment);
    }

    function renderEvidence(data) {
        const evidence = data.evidence || {};
        const content = document.createDocumentFragment();
        content.append(node('p', `資料快照：${data.snapshot_date}。數值是該快照保留的刊登紀錄，並非即時全市場總數；職缺是否仍開放，請以來源頁為準。`));
        content.append(node('p', `資料擷取時間：${evidence.last_updated || '未記錄'}`));
        const source = node('p', '官方來源：');
        source.append(safeLink('勞動部台灣就業通職缺清單（資料集 44062）', 'https://data.gov.tw/dataset/44062'));
        content.append(source);
        for (const [title, items] of [['計算方式', evidence.calculation], ['閱讀提醒', evidence.limitations]]) {
            if (!items?.length) continue;
            content.append(node('h4', title));
            const list = node('ul');
            for (const text of items) list.append(node('li', text));
            content.append(list);
        }
        el('comparison-evidence-content').replaceChildren(content);
    }

    function errorText(body) {
        const detail = body?.detail || body;
        if (detail?.error_code === 'MISSING_DISTRICT_AUDIT' || detail?.error_code === 'INCOMPLETE_DISTRICT_AUDIT') return '部分行政區的快照擷取紀錄不完整，暫時無法公平比較。請更新官方職缺資料後重試，或改選其他行政區。';
        if (typeof detail === 'string') return detail;
        return detail?.reason || '無法取得官方比較資料。請確認本機服務與官方職缺快照可用，再按「開始比較」重試。';
    }

    async function compare(event) {
        event?.preventDefault();
        const selected = [1,2,3].map(i => el(`comparison-district-${i}`).value).filter(Boolean);
        el('comparison-error').hidden = true;
        el('comparison-results').hidden = true;
        if (selected.length < 2 || selected.length > 3 || new Set(selected).size !== selected.length) {
            el('comparison-error').textContent = '請選擇 2～3 個不同的行政區，再開始比較。';
            el('comparison-error').hidden = false;
            el('comparison-status').textContent = '行政區重複或數量不足，請調整選擇。';
            return;
        }
        controller?.abort();
        const activeController = new AbortController();
        controller = activeController;
        const current = ++requestId;
        const timeout = setTimeout(() => activeController.abort(), 20000);
        const params = new URLSearchParams();
        selected.forEach(district => params.append('districts', district));
        const industry = el('comparison-industry').value;
        const keyword = el('comparison-keyword').value.trim();
        if (industry) params.set('industry_id', industry);
        if (keyword) params.set('occupation_keyword', keyword);
        setLoading(true);
        el('comparison-status').textContent = `正在比較${selected.join('、')}的官方職缺資料…`;
        try {
            const response = await fetch(`/api/official/district-comparison?${params}`, {signal: activeController.signal});
            const contentType = response.headers.get('content-type') || '';
            const data = contentType.includes('application/json') ? await response.json() : null;
            if (!response.ok || !data?.available) throw new Error(errorText(data));
            if (current !== requestId) return;
            renderTable(data);
            renderDistrictDetails(data);
            renderEvidence(data);
            el('comparison-period').textContent = `資料快照：${data.snapshot_date}`;
            el('comparison-applied').textContent = `${data.industry_name || '全部工作領域'}${data.occupation_keyword ? ` · 關鍵字：${data.occupation_keyword}` : ' · 未限定職稱關鍵字'}`;
            const empty = data.comparisons.every(item => item.vacancy_postings === 0);
            el('comparison-status').textContent = empty ? '查詢完成，目前沒有符合條件的刊登。可移除關鍵字或改選工作領域再比較。' : `已完成 ${data.comparisons.length} 區比較。展開行政區可查看職類和來源職缺。`;
            el('comparison-results').hidden = false;
        } catch (error) {
            if (current !== requestId) return;
            el('comparison-error').textContent = error.name === 'AbortError'
                ? '讀取逾時，請按「開始比較」重試。'
                : error instanceof TypeError
                    ? '無法連線至比較服務，請確認本機伺服器已啟動，再按「開始比較」重試。'
                    : error.message;
            el('comparison-error').hidden = false;
            el('comparison-status').textContent = '本次未取得比較結果。';
        } finally {
            clearTimeout(timeout);
            if (current === requestId) setLoading(false);
        }
    }

    function initialize() {
        if (initialized) return;
        initialized = true;
        const defaults = ['大雅區','潭子區','神岡區'];
        [1,2,3].forEach(i => {
            const select = el(`comparison-district-${i}`);
            if (i === 3) select.append(new Option('不加入第三區', ''));
            districts.forEach(district => select.append(new Option(district, district)));
            select.value = defaults[i-1];
        });
        industries.forEach(([id,label]) => el('comparison-industry').append(new Option(label,id)));
        el('comparison-industry').value = 'IND_MFG';
        el('comparison-form').addEventListener('submit', compare);
        el('comparison-form').addEventListener('input', invalidate);
        el('comparison-form').addEventListener('change', invalidate);
        window.addEventListener('hashchange', () => {
            const tab = window.location.hash.slice(1) || 'overview';
            if (!['overview','dynamics','map','compare','supply','mismatch','agent'].includes(tab)) return;
            const target = el(`page-${tab}`);
            if (target?.classList.contains('hidden') && typeof window.switchTab === 'function') window.switchTab(tab);
            if (tab === 'compare') activate();
        });
    }

    function activate() {
        initialize();
        if (activated) return;
        activated = true;
        compare();
    }

    window.districtComparison = {activate};
    initialize();
    if (window.location.hash === '#compare') activate();
})();
