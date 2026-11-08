const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
function setup() {
  const elements = new Map();
  const context = vm.createContext({ document: { getElementById(id) {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', querySelectorAll: () => [] });
    return elements.get(id);
  } } });
  // Only function definitions, before event wiring or any initial HTTP requests.
  vm.runInContext(source.slice(0, source.indexOf("$('search').addEventListener")), context);
  return { context, elements };
}
test('review status remains distinct from technical status in the list', () => {
  const { context, elements } = setup();
  vm.runInContext(`state.dataset = 'digital-life'; renderList([
    {id:'ready', status:'accepted', review_status:'READY_FOR_HUMAN_REVIEW'},
    {id:'needs', status:'accepted', review_status:'ORIGINAL_BODY_TECHNICALLY_ACCEPTED_QUALITY_NEEDS_EVIDENCE'},
    {id:'fee-blocked', status:'accepted', review_status:'ORIGINAL_BODY_TECHNICALLY_ACCEPTED_FINAL_GATE_BLOCKED_FEE_ATTRIBUTION_UNKNOWN'}
  ], 3)`, context);
  const markup = elements.get('list').innerHTML;
  assert.match(markup, /审核通过 · 待人工确认/);
  assert.match(markup, /内容待证/);
  assert.match(markup, /最终审核受阻：费用待归因/);
  assert.equal(vm.runInContext("statusLabel('accepted')", context), '技术通过');
});
test('untrusted research notes, titles and IDs are escaped instead of active HTML', () => {
  const { context, elements } = setup();
  const notice = vm.runInContext(`researchNotice({research_note:'<img src=x onerror="alert(1)"><script>run()</script>'})`, context);
  assert.ok(notice.includes('&lt;img'));
  assert.ok(notice.includes('&lt;script&gt;'));
  assert.ok(!notice.includes('<img'));
  assert.ok(!notice.includes('<script>'));
  vm.runInContext(`state.dataset='digital-life'; renderList([{id:'" onmouseover="run()', title:'<script>run()</script>', review_status:'<script>run()</script>'}],1)`, context);
  assert.ok(!elements.get('list').innerHTML.includes('<script>'));
  assert.ok(elements.get('list').innerHTML.includes('data-id="&quot; onmouseover=&quot;'));
});
test('reference decisions show separately, retain zero Q and escape reasons', () => {
  const { context, elements } = setup();
  const markup = vm.runInContext(`referenceNotice({reference_status:'PASS',claim_verification:'SOURCE_REPORTED',reference_Q:0,reference_weighted_score:0,reference_reason:'<script>bad()</script>',reference_reason_codes:['<img>'],reference_evidence_refs:['<svg>'],counts_toward_target:false})`, context);
  assert.match(markup, /参考合格 · 作者自述/);
  assert.match(markup, /原Q：0/);
  assert.match(markup, /时效加权：0/);
  assert.ok(!markup.includes('<script>'));
  assert.ok(!markup.includes('<img>'));
  assert.ok(!markup.includes('<svg>'));
  assert.match(vm.runInContext(`referenceNotice({review_status:'READY_FOR_HUMAN_REVIEW'})`, context), /未独立批准/);
  vm.runInContext(`state.dataset='digital-life'; renderReferenceCounts({PASS:2,NEEDS_EVIDENCE:1,EXCLUDE:3,UNAPPROVED:4,counts_toward_target:1})`, context);
  assert.match(elements.get('reference-summary').textContent, /参考合格 2/);
  assert.match(elements.get('reference-summary').textContent, /正文去重）1/);
});

test('media notice distinguishes uncollected originals and escapes captions and source URLs', () => {
  const { context } = setup();
  const missing = vm.runInContext(`mediaNotice({status:'NOT_COLLECTED',limitation:'原图未采集；不是原文无图',images:[]})`, context);
  assert.match(missing, /原图未采集/);
  assert.match(missing, /不能据此判断原文图片数量/);
  assert.doesNotMatch(missing, /0 张/);
  const markup = vm.runInContext(`mediaNotice({status:'VERIFIED',limitation:'仅供研究',images:[{url:'/media/id/a.png',source_url:'https://example.test/\"><svg onload=1>',caption:'<img src=x onerror=1>',position:'source img[1]',width:2,height:3,captured_at:'2026-11-06T10:00:00Z'}]})`, context);
  assert.match(markup, /<img src="\/media\/id\/a.png"/);
  assert.ok(markup.includes('&lt;img'));
  assert.ok(markup.includes('&lt;svg'));
  assert.ok(!markup.includes('<svg'));
  assert.ok(!markup.includes('onerror=1>'));
  assert.match(markup, /2026-11-06T10:00:00Z/);
});
