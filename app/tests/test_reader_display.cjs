const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
function setup() {
  const elements = new Map();
  const calls = { focus: [], back: null, mode: [] };
  const shell = { classList: { add: (v) => calls.mode.push(['add',v]), remove: (v) => calls.mode.push(['remove',v]) } };
  const row = { dataset: { id: 'long' }, classList: { toggle(){} }, focus: (options) => calls.focus.push(options) };
  const list = { querySelectorAll: () => [row] };
  const reader = { innerHTML: '', focus: (options) => calls.focus.push(options) };
  const ids = ['reader','list','reader-back'];
  for (const id of ids) elements.set(id, id === 'reader' ? reader : id === 'list' ? list : { addEventListener: (type, fn) => { calls.back = fn } });
  const article = { title:'本文', topic_id:'T', topic:'主题', status:'pending_review', review_status:'ORIGINAL_BODY_TECHNICALLY_ACCEPTED_QUALITY_NEEDS_EVIDENCE', reference_status:'NEEDS_EVIDENCE', claim_verification:'SOURCE_REPORTED', reference_Q:0, reference_reason:'待核', reference_reason_codes:[], reference_evidence_refs:[], counts_toward_target:false, account:'账号', published_at:'2026-11-01' };
  const body = '首段\n' + '正文内容。'.repeat(3000) + '\n尾部练习与关注我';
  const context = vm.createContext({
    document: { getElementById(id) { if (!elements.has(id)) elements.set(id, { innerHTML:'', textContent:'', querySelectorAll: () => [], classList:{toggle(){}}, addEventListener(){} }); return elements.get(id); }, querySelector: () => shell },
    fetch: async () => ({ ok:true, json: async () => ({ article, body, body_source:'本地研究库', media:{status:'NOT_COLLECTED',limitation:'未采集原图',images:[]} }) })
  });
  vm.runInContext(source.slice(0, source.indexOf("$('search').addEventListener")), context);
  return { context, elements, calls, body };
}

test('opening an article focuses a native reader, puts full escaped body before collapsed audit details, and returns focus to selection', async () => {
  const { context, elements, calls, body } = setup();
  await vm.runInContext("state.dataset='digital-life'; openArticle('long')", context);
  const markup = elements.get('reader').innerHTML;
  assert.ok(markup.indexOf('class="reader-body"') < markup.indexOf('<details'));
  assert.match(markup, /<details class="reader-disclosure"><summary>审核\/资格详情/);
  assert.match(markup, /图片详情 · 原图未采集/);
  assert.match(markup, /参考资格：待补证 · 作者自述/);
  assert.ok(markup.includes('尾部练习与关注我'));
  assert.equal((markup.match(/正文内容/g) || []).length, 3000);
  assert.equal(calls.focus[0].preventScroll, true);
  assert.deepEqual(calls.mode[0], ['add','reading-mode']);
  calls.back();
  assert.deepEqual(calls.mode[1], ['remove','reading-mode']);
  assert.equal(calls.focus[1].preventScroll, true);
});
