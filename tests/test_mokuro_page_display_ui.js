// Run with: node tests/test_mokuro_page_display_ui.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
for (const file of ['queue_ui.py', 'logs_ui.py']) {
  const source = fs.readFileSync(path.join(__dirname, '../app/web', file), 'utf8');
  const start = source.indexOf('function mokuroPagesHtml(e){');
  const end = source.indexOf('\n}', start) + 2;
  const render = new Function('escapeHtml', `${source.slice(start, end)}; return mokuroPagesHtml;`)(String);
  const entry = {source: 'mokuro', amount: 164, mokuro_logged_pages: 32,
    notes: 'pages 32→196 (+164); total=196; completed', tadoku_status: 'pending'};
  const complete = render(entry);
  assert.match(complete, /mokuro-logged[^>]*>32</);
  assert.match(complete, /mokuro-current[^>]*>164</);
  assert.match(complete, /mokuro-total done[^>]*>196/);
  assert.match(complete, /✓/);
  assert.match(complete, /Pages to submit with this log/);
  assert.match(render({...entry, tadoku_status: 'pushed'}), /Pages submitted by this log/);
  const incomplete = render({...entry, amount: 40, notes: 'pages 32→72 (+40); total=196'});
  assert.doesNotMatch(incomplete, /✓|mokuro-total done/);
  // Baseline/end position is not an already-submitted page count.
  const baseline = render({...entry, amount: 20, mokuro_logged_pages: 0,
    notes: 'pages 80→100 (+20); total=196'});
  assert.match(baseline, /mokuro-logged[^>]*>0</);
  assert.doesNotMatch(baseline, /✓/);
  assert.match(render({...entry, notes: '', mokuro_logged_pages: 0}), />\?</);
  assert.match(render({...entry, notes: 'pages 32→196 (+164); completed'}), /mokuro-total done[^>]*>196/);
  assert.doesNotMatch(render({...entry, source: 'manual'}), /mokuro-pages/);
}
console.log('Mokuro page display checks passed for queue and log history');
