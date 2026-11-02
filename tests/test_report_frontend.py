"""Report UI boundaries; no server, network or production data writes."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
SCRIPT = UI / "static" / "report-comparison.js"


class SurfaceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.labels, self.urls, self.events = [], [], [], []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if "id" in attr:
            self.ids.append(attr["id"])
        if tag == "label":
            self.labels.append(attr.get("for"))
        for key in ("src", "href"):
            if key in attr:
                self.urls.append(attr[key])
        self.events.extend(key for key in attr if key.startswith("on"))


class ReportFrontendTests(unittest.TestCase):
    def test_surfaces_have_unique_ids_resolved_labels_and_local_assets(self):
        for filename in ("compare.html", "report.html"):
            with self.subTest(surface=filename):
                parser = SurfaceParser()
                parser.feed((UI / filename).read_text(encoding="utf-8"))
                self.assertEqual(len(parser.ids), len(set(parser.ids)))
                self.assertTrue(all(label in parser.ids for label in parser.labels))
                self.assertFalse(parser.events, "No inline event execution")
                self.assertFalse(any(url.startswith(("http:", "https:", "//")) for url in parser.urls))
                self.assertFalse(any("/legacy" in url for url in parser.urls))

    def test_source_and_model_text_cannot_enter_html_execution_sinks(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\.(?:innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write\s*\(|\beval\s*\(")
        self.assertIn("result.textContent = String(text)", source)
        self.assertIn("url.protocol !== 'https:'", source)
        self.assertIn("url.hostname.endsWith('.gov.tw')", source)
        self.assertIn("a.rel = 'noopener noreferrer'", source)

    def test_build_uses_resolved_scenario_token_and_idempotency(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/api/reports/expansion-comparison/resolve", source)
        self.assertIn("scenario: resolution.scenario, resolution_token: resolution.resolution_token", source)
        self.assertIn("options.headers['Idempotency-Key'] = buildKey", source)
        self.assertIn("function invalidate()", source)
        self.assertIn("resolution = null", source)
        self.assertIn("controller.abort()", source)
        self.assertNotIn("accuracy_pct", source)
        self.assertNotIn("golden-responses", source)

    def test_report_uses_controlled_blocks_and_preserves_partial_values(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("result.blocks", source)
        self.assertNotRegex(source, r"result\.answer\b|data\.answer\b|innerHTML")
        self.assertIn("report.planning?.monthly_targets", source)
        self.assertIn("content.summary_blocks", source)
        self.assertIn("row?.value_status === 'LOWER_BOUND'", source)
        self.assertIn("factEvidence.length ? factEvidence : list(row?.evidence_ids)", source)
        self.assertIn("b.heading_id !== 'NEXT_STEPS'", source)
        self.assertIn("jsonPost({question: value}), 25000", source)
        self.assertNotRegex(source, r"(?:new_company_count|requested_workers|vacancy_postings)\s*\|\|\s*0")

    def test_print_keeps_evidence_and_unknown_states(self):
        css = (UI / "static" / "report-comparison.css").read_text(encoding="utf-8")
        self.assertIn("@media print", css)
        self.assertIn(".evidence-detail>*{display:block!important}", css)
        self.assertIn("@media(prefers-reduced-motion:no-preference)", css)
        self.assertIn("focus-visible", css)
        self.assertIn("overflow-x:auto", css)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_javascript_parses(self):
        subprocess.run([shutil.which("node"), "--check", str(SCRIPT)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_null_never_formats_as_zero_and_zero_is_preserved(self):
        harness = r"""
const fs = require('fs');
const vm = require('vm');
let source = fs.readFileSync(process.argv[1], 'utf8');
source = source.replace(/\}\)\(\);\s*$/, 'globalThis.helpers = {textValue, monthNumber};})();');
const context = {document: {body: {dataset: {}}}, Intl, URLSearchParams};
vm.createContext(context); vm.runInContext(source, context);
const h = context.helpers;
if (h.textValue(null) !== '未知' || h.textValue({amount:null}) !== '未知') throw Error('null became zero');
if (h.textValue(0) !== '0' || h.textValue({amount:'0'}) !== '0') throw Error('real zero dropped');
if (h.monthNumber('2026-13') !== null) throw Error('invalid month accepted');
"""
        subprocess.run([shutil.which("node"), "-e", harness, str(SCRIPT)], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_city_view_never_restores_rejected_raw_values(self):
        # Run the actual rendering function against a minimal DOM, including a
        # source claiming "available" whose values never entered the catalog.
        harness = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('    function renderCity(content) {');
const end = source.indexOf('    function summaryHighlights(content)', start);
if (start < 0 || end < 0) throw Error('renderCity function not found');
const box = {children: [], replaceChildren() {this.children = [];}, append(n) {this.children.push(n);}};
const context = {
  report: {gcis: {city: {available: true, start: '2026-99', end: '2026-99', current_sum: 987654321, baseline_sum: 876543210, baseline_start: '2025-99', baseline_end: '2025-99'}}},
  $: () => box,
  list: value => Array.isArray(value) ? value : [],
  node: (tag, text, cls) => ({tag, textContent: String(text), cls}),
  textValue: value => String(value),
  renderBlocks: (target, blocks) => {target.replaceChildren(); blocks.forEach(b => target.append({textContent: b.text}));},
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
vm.runInContext('renderCity({summary_blocks: []})', context);
let output = box.children.map(n => n.textContent).join(' ');
if (output.includes('987654321') || output.includes('876543210') || output.includes('2026-99')) throw Error('Rejected raw city values were restored');
if (!output.includes('沒有核准')) throw Error('Missing-data notice was not rendered');
context.content = {summary_blocks: [
  {district: null, metric_id: 'gcis.city_new_companies', heading_id: 'GCIS_CONTEXT', text: '核准背景：100家'},
  {district: null, metric_id: 'gcis.city_new_companies', heading_id: 'NEXT_STEPS', text: '這是下一步，不是共同背景'},
  {district: '大雅區', metric_id: 'gcis.local_new_companies', heading_id: 'GCIS_CONTEXT', text: '區域值不可變成全市背景'},
]};
vm.runInContext('renderCity(content)', context);
output = box.children.map(n => n.textContent).join(' ');
if (output !== '核准背景：100家') throw Error('City view lost approved blocks or admitted wrong-scope actions');
"""
        subprocess.run([shutil.which("node"), "-e", harness, str(SCRIPT)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
