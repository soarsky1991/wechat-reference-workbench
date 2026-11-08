const state = { dataset: 'digital-life', topic: '', q: '', account: '', month: '', body: '', window: '', status: '', reference: '', claim: '', selected: '', articles: [] }
const statusLabel = (s) => ({accepted:'技术通过', pending:'待采集', pending_review:'待复核', failed:'失败待处理', unknown:'中断待确认', running:'采集中', input_invalid:'链接待核验', finished:'执行结束', completed:'已结束', stopped:'已暂停'}[s] || s || '待采集')
const $ = (id) => document.getElementById(id)
const esc = (value = '') => String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
const reviewLabel = (s = '') => s === 'READY_FOR_HUMAN_REVIEW' ? '审核通过 · 待人工确认'
  : s === 'ORIGINAL_BODY_TECHNICALLY_ACCEPTED_FINAL_GATE_BLOCKED_FEE_ATTRIBUTION_UNKNOWN' ? '最终审核受阻：费用待归因'
  : s.includes('NEEDS_EVIDENCE') ? '内容待证'
  : s.includes('QUALITY_EXCLUDE') ? '内容排除'
  : s.includes('QUALITY_PASS') ? '内容通过 · 待最终门审'
  : '内容待审'
const researchNotice = (a) => a.research_note ? `<aside class="error-box" role="note"><b>研究勘误与使用边界</b><p>${esc(a.research_note)}</p></aside>` : ''
const mediaStatusLabel = (s) => ({VERIFIED:'原图已登记并校验', PARTIAL:'媒体仅部分登记', BLOCKED:'媒体校验受阻', NOT_COLLECTED:'原图未采集'}[s] || '媒体状态未知')
function mediaNotice(media) {
  const m = media && typeof media === 'object' ? media : { status: 'NOT_COLLECTED', limitation: '原图未采集；此状态不表示原文没有图片。', images: [] }
  const images = Array.isArray(m.images) ? m.images : []
  const items = images.map((image) => {
    const src = typeof image.url === 'string' && image.url.startsWith('/media/') ? image.url : ''
    const source = typeof image.source_url === 'string' && /^https:\/\//i.test(image.source_url)
      ? `<a href="${esc(image.source_url)}" target="_blank" rel="noopener noreferrer">查看图片来源 ↗</a>` : '<span>来源链接不可用</span>'
    const preview = src ? `<a class="media-preview-link" href="${esc(src)}" target="_blank" rel="noopener noreferrer"><img src="${esc(src)}" alt="${esc(image.caption || '文章原图')}" loading="lazy"></a>` : '<div class="media-unavailable">本地预览链接不可用</div>'
    return `<figure class="media-item">${preview}<figcaption><b>${esc(image.caption || '原图')}</b><span>${esc(image.position || '')} · ${esc(image.width)}×${esc(image.height)} · ${esc(image.captured_at || '采集时间未记录')}</span>${source}</figcaption></figure>`
  }).join('')
  return `<section class="media-panel" aria-label="文章原图"><div class="media-heading"><b>${esc(mediaStatusLabel(m.status))}</b>${images.length ? `<span>${images.length} 张本地登记图片</span>` : ''}</div><p>${esc(m.limitation || '媒体范围说明未记录。')}</p>${images.length ? `<div class="media-grid">${items}</div>` : `<p class="media-empty">${m.status === 'NOT_COLLECTED' ? '原图未采集；不能据此判断原文图片数量。' : '当前没有可安全展示的本地图片。'}</p>`}</section>`
}

const referenceLabel = (s) => ({PASS:'参考合格', NEEDS_EVIDENCE:'待补证', EXCLUDE:'排除', UNAPPROVED:'未独立批准'}[s] || '未独立批准')
const claimLabel = (s) => ({SOURCE_REPORTED:'作者自述', INDEPENDENTLY_TESTED:'独立实测', NOT_APPLICABLE:'不适用'}[s] || '核验未批准')
const referenceNotice = (a) => `<aside class="reference-review" role="note"><b>${esc(referenceLabel(a.reference_status))} · ${esc(claimLabel(a.claim_verification))}</b><p>参考原Q：${esc(a.reference_Q ?? '—')} / 5 · 时效加权：${esc(a.reference_weighted_score ?? '—')} · 计入目标：${a.counts_toward_target === true ? '是（正文去重）' : '否'}</p><p>${esc(a.reference_reason || '未独立批准')}${(a.reference_reason_codes || []).length ? `（${esc(a.reference_reason_codes.join(' / '))}）` : ''}</p>${(a.reference_evidence_refs || []).length ? `<p>证据引用：${a.reference_evidence_refs.map(esc).join('；')}</p>` : ''}</aside>`
function renderReferenceCounts(counts) {
  $('reference-summary').textContent = state.dataset === 'digital-life'
    ? `当前筛选：参考合格 ${counts?.PASS || 0} · 待补证 ${counts?.NEEDS_EVIDENCE || 0} · 排除 ${counts?.EXCLUDE || 0} · 未独立批准 ${counts?.UNAPPROVED || 0} · 计入目标（正文去重）${counts?.counts_toward_target || 0}。仅 approved.json 为批准依据；作者自述不等于独立实测。`
    : ''
}

async function request(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
  if (!response.ok) throw new Error(`读取失败（${response.status}）`)
  return response.json()
}

function queryString() {
  const params = new URLSearchParams()
  if (state.topic) params.set('topic', state.topic)
  if (state.q) params.set('q', state.q)
  if (state.account) params.set('account', state.account)
  if (state.month) params.set('month', state.month)
  if (state.body) params.set('body', state.body)
  if (state.window) params.set('window', state.window)
  if (state.status) params.set('status', state.status)
  if (state.reference) params.set('reference', state.reference)
  if (state.claim) params.set('claim', state.claim)
  return params.toString()
}

function endpoint() { return state.dataset === 'digital-life' ? '/api/digital-life-articles' : '/api/articles' }

function renderTopics(all) {
  const counts = new Map()
  all.forEach((a) => counts.set(a.topic_id, { name: a.topic, count: (counts.get(a.topic_id)?.count || 0) + 1 }))
  $('topics').innerHTML = `<button class="topic-link ${state.topic ? '' : 'active'}" data-topic=""><span>全部主题</span><b>${all.length}</b></button>` +
    [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([id, x]) => `<button class="topic-link ${state.topic === id ? 'active' : ''}" data-topic="${esc(id)}"><span><i>${esc(id)}</i>${esc(x.name)}</span><b>${x.count}</b></button>`).join('')
  $('topics').querySelectorAll('[data-topic]').forEach((button) => button.addEventListener('click', () => { state.topic = button.dataset.topic; refresh() }))
}

function renderList(articles, count) {
  $('result-count').textContent = `${count} ${state.dataset === 'digital-life' ? '条元数据' : '篇文章'}`
  $('list').innerHTML = articles.length ? articles.map((a) => `<button class="article-row ${state.selected === a.id ? 'selected' : ''}" data-id="${esc(a.id)}">
    <span class="row-kicker"><span class="topic-chip">${esc(a.topic_id)}</span><span>${state.dataset === 'digital-life' ? `${a.body_available ? '正文可读' : esc(statusLabel(a.status))} · ${esc(a.time_window || '日期缺失')} · 权重×${esc(a.recency_multiplier || '—')}` : (a.body_available ? '正文可读' : '仅元数据')}</span></span>
    <strong>${esc(a.title || '（无标题）')}</strong>${state.dataset === 'digital-life' ? `<span class="row-meta">${esc(a.reference_reason || '未独立批准')}</span>` : ''}<span class="row-meta">${esc(a.account || '公众号未记录')} · ${esc(a.published_at ? a.published_at.slice(0, 10) : '日期未记录')}${state.dataset === 'digital-life' ? ` · 旧审：${esc(reviewLabel(a.review_status))} · ${esc(referenceLabel(a.reference_status))} · ${esc(claimLabel(a.claim_verification))} · 原Q ${esc(a.reference_Q ?? '—')} · 加权 ${esc(a.reference_weighted_score ?? '—')}` : ''}</span>
  </button>`).join('') : '<div class="empty-list">没有匹配文章。可以清除筛选或更换关键词。</div>'
  $('list').querySelectorAll('[data-id]').forEach((button) => button.addEventListener('click', () => openArticle(button.dataset.id)))
}

async function openArticle(id) {
  state.selected = id
  $('list').querySelectorAll('[data-id]').forEach((button) => button.classList.toggle('selected', button.dataset.id === id))
  document.querySelector('.app-shell').classList.add('reading-mode')
  $('reader').innerHTML = '<div class="loading">正在读取本地文章…</div>'
  try {
    const data = await request(`${endpoint()}/${encodeURIComponent(id)}`)
    const a = data.article
    const link = a.url ? `<a class="source-link" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">在微信中打开原文 ↗</a>` : '<span class="no-link">没有可验证的安全原文链接</span>'
    const isDigital = state.dataset === 'digital-life'
    const referenceSummaryText = isDigital ? `参考资格：${referenceLabel(a.reference_status)} · ${claimLabel(a.claim_verification)}` : ''
    const mediaSummaryText = isDigital ? `${mediaStatusLabel(data.media?.status)}${Array.isArray(data.media?.images) && data.media.images.length ? ` · ${data.media.images.length} 张` : ''}` : ''
    const qualifications = isDigital ? `<span>${esc(referenceSummaryText)}</span>` : ''
    const disclosures = `${isDigital ? `<details class="reader-disclosure"><summary>审核/资格详情 · ${esc(referenceSummaryText)}</summary>${referenceNotice(a)}</details><details class="reader-disclosure"><summary>图片详情 · ${esc(mediaSummaryText)}</summary>${mediaNotice(data.media)}</details>` : ''}${researchNotice(a)}${a.error_category || a.error_message ? `<details class="reader-disclosure"><summary>采集问题详情</summary><p class="error-box">${esc(a.error_category || '')} ${esc(a.error_message || '')}</p></details>` : ''}`
    $('reader').innerHTML = `<header class="reader-header"><div class="reader-toolbar"><button id="reader-back" type="button" class="reader-back">返回列表</button><div class="reader-chips"><span>${esc(a.topic_id)} · ${esc(a.topic)}</span><span>${isDigital ? esc(statusLabel(a.status)) : (a.status === 'ACCEPTED_RECONSTRUCTED' ? '重建验收' : '已验收')}</span>${isDigital ? `<span>旧内容审核：${esc(reviewLabel(a.review_status))}</span>${qualifications}` : ''}</div></div>
      <h2>${esc(a.title || '（无标题）')}</h2><div class="reader-byline"><strong>${esc(a.account || '公众号未记录')}</strong><span>${esc(a.published_at ? a.published_at.slice(0, 10) : '日期未记录')}</span>${a.quality ? `<span>质量 ${esc(a.quality)} / 5</span>` : ''}${isDigital ? `<span>${esc(a.time_window || '日期缺失')} · 权重×${esc(a.recency_multiplier || '—')}</span>${a.recency_weighted_score ? `<span>时效加权 ${esc(a.recency_weighted_score)}</span>` : ''}` : ''}</div>
      <div class="source-row">${link}<span>${data.body ? `正文来源：${esc(data.body_source || '本地研究库')}` : (isDigital ? `正文状态：${esc(statusLabel(a.status))}` : '正文：本地未找到')}</span><span>记录状态：${esc(statusLabel(a.status))}</span></div></header>
      <div class="reader-body">${data.body ? esc(data.body) : `<div class="body-missing"><b>${isDigital ? '这是标题级名录记录' : '本地暂无匹配正文'}</b><p>${isDigital ? '本地缓存复用，链接未逐条在线验证；当前页面不会启动文章采集。' : '当前仅展示台账元数据。页面不会自动访问原文来补正文。'}</p></div>`}</div>${disclosures}`
    $('reader').focus({ preventScroll: true })
    $('reader-back').addEventListener('click', returnToList)
  } catch (error) {
    $('reader').innerHTML = `<div class="error-box">${esc(error.message || '读取失败')}</div>`
  }
}

function returnToList() {
  document.querySelector('.app-shell').classList.remove('reading-mode')
  const row = [...$('list').querySelectorAll('[data-id]')].find((button) => button.dataset.id === state.selected)
  row?.focus({ preventScroll: true })
}

async function refresh() {
  $('list').innerHTML = '<div class="loading">正在读取本地台账…</div>'
  try {
    const all = await request(endpoint())
    renderTopics(all.articles)
    const result = await request(`${endpoint()}?${queryString()}`)
    state.articles = result.articles
    renderList(result.articles, result.count)
    renderReferenceCounts(result.reference_counts)
    if (state.selected && !result.articles.some((a) => a.id === state.selected)) {
      state.selected = ''
      $('reader').innerHTML = '<div class="empty-reader"><div class="empty-icon">演</div><h2>选择一条演示记录</h2><p>正文是合成测试内容，不对应真实文章、账号或来源。</p></div>'
    }
  } catch (error) {
    $('reference-summary').textContent = ''
    $('result-count').textContent = '读取失败'
    $('list').innerHTML = `<div class="error-box">${esc(error.message || '读取失败')}</div>`
  }
}

$('search').addEventListener('input', (event) => { state.q = event.target.value.trim(); refresh() })
$('account').addEventListener('input', (event) => { state.account = event.target.value.trim(); refresh() })
$('month').addEventListener('change', (event) => { state.month = event.target.value; refresh() })
$('body-filter').addEventListener('change', (event) => { state.body = event.target.value; refresh() })
$('time-window').addEventListener('change', (event) => { state.window = event.target.value; refresh() })
$('dataset-switch').addEventListener('click', (event) => {
  const button = event.target.closest('[data-dataset]')
  if (!button || button.dataset.dataset === state.dataset) return
  state.dataset = button.dataset.dataset
  state.topic = state.month = state.body = state.window = state.status = state.reference = state.claim = state.selected = ''
  $('month').value = $('body-filter').value = $('time-window').value = ''
  $('collection-status').value = $('reference-filter').value = $('claim-filter').value = ''
  $('reference-filter').parentElement.hidden = $('claim-filter').parentElement.hidden = state.dataset !== 'digital-life'
  renderReferenceCounts()
  $('window-filter').hidden = state.dataset !== 'digital-life'
  $('month').parentElement.hidden = state.dataset === 'digital-life'
  $('body-filter').parentElement.hidden = false
  $('collection-status').parentElement.hidden = state.dataset !== 'digital-life'
  document.querySelectorAll('[data-dataset]').forEach((item) => {
    const active = item === button
    item.classList.toggle('active', active)
    item.setAttribute('aria-pressed', String(active))
  })
  $('reader').innerHTML = '<div class="empty-reader"><div class="empty-icon">演</div><h2>选择一条记录</h2><p>测试正文为合成数据；页面不触发采集。</p></div>'
  refresh()
})
$('clear').addEventListener('click', () => {
  state.topic = state.q = state.account = state.month = state.body = state.window = state.status = state.reference = state.claim = ''
  $('search').value = $('account').value = $('month').value = ''
  $('body-filter').value = $('time-window').value = $('collection-status').value = $('reference-filter').value = $('claim-filter').value = ''
  refresh()
})
request('/api/runtime-info').then((info) => {
  $('runtime-status').textContent = info.data_mode === 'bundled-synthetic-demo' ? '包内合成演示数据' : '显式外部本地工作区'
}).catch(() => { $('runtime-status').textContent = '工作区状态未知' })
refresh()

$('reference-filter').addEventListener('change', (event) => { state.reference = event.target.value; refresh() })
$('claim-filter').addEventListener('change', (event) => { state.claim = event.target.value; refresh() })
$('collection-status').addEventListener('change', (event) => { state.status = event.target.value; refresh() })
request('/api/collection-batches').then(({batches}) => {
  $('batch-summary').textContent = batches.length ? batches.slice(0, 3).map(b => `${b.batch_id} · ${statusLabel(b.status)} · ${Object.entries({...b.summary.counts, new_bodies:b.summary.new_bodies}).filter(([,v]) => typeof v === 'number').map(([k,v]) => `${({new_bodies:'新增技术正文', planned:'计划', accepted:'技术通过', new:'新增', is_new:'新增', new_count:'新增', failed:'失败', pending:'待采', pending_review:'待复核', duplicates:'重复', unknown:'中断未知'}[k] || statusLabel(k))} ${v}`).join(' / ')}`).join(' ｜ ') : '尚无采集批次；页面只读，不自动发起请求。'
}).catch(e => { $('batch-summary').textContent = e.message })
