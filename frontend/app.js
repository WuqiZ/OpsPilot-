import {icon, esc, pct, seconds, date, agents, agentName, badge, api, markdown, toast, download} from './ui.js';

const storageKey = 'opspilot.sessions.v1';
const prompts = [
  {icon: 'network', title: 'VPN 连接异常', text: '公司 VPN 从今天早上开始连接超时，三个人受影响，本地网络正常。'},
  {icon: 'identity_access', title: '账号权限问题', text: '我的账号访问项目返回 403，同组同事可以正常访问。'},
  {icon: 'software', title: '应用启动崩溃', text: 'Office 升级后打开文档立即崩溃，昨天还可以正常使用。'},
  {icon: 'security', title: '可疑邮件处置', text: '我刚点击了疑似钓鱼邮件中的链接，应该怎么处理？'},
];
const pages = {overview: '工作台', history: '诊断记录', knowledge: '知识库', agents: 'Agent & Skills', evaluation: '评测中心', diagnosis: '智能诊断'};
function readSessions() {
  try { return JSON.parse(localStorage.getItem(storageKey) || '[]').filter(x => x.id && Array.isArray(x.turns)).slice(0, 30); }
  catch { return []; }
}
const state = {
  page: location.hash.slice(1) || 'overview', health: null, healthError: '', skills: null,
  report: null, reportError: '', documents: [], knowledgeLoaded: false, knowledgeError: '',
  source: 'all', query: '', search: null, searching: false,
  sessions: readSessions(), current: null, draft: '', busy: false, chatError: '',
  evaluating: false, evalFilter: 'failed', historyQuery: '', skillReloading: false,
};
const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
const currentSession = () => state.sessions.find(item => item.id === state.current);
const latestTurn = () => currentSession()?.turns.at(-1);
const button = (text, action, symbol = '', cls = 'button') => `<button class="${cls}" data-action="${action}">${symbol ? icon(symbol) : ''}${text}</button>`;
const empty = (symbol, title, desc) => `<div class="empty-state">${icon(symbol)}<h3>${esc(title)}</h3><p>${esc(desc)}</p></div>`;

function shell() {
  if (!pages[state.page]) state.page = 'overview';
  app.innerHTML = `
    <aside class="sidebar" id="sidebar">
      <a class="brand" href="#overview" aria-label="OpsPilot 工作台"><span class="brand-mark">${icon('bolt')}</span><span>OpsPilot<span class="brand-dot">.</span></span></a>
      <div class="workspace"><span class="workspace-logo">O</span><span><strong>企业 IT 服务空间</strong><small>Development workspace</small></span><span class="workspace-tag">DEV</span></div>
      <span class="nav-label">工作空间</span>
      <nav aria-label="主导航">${nav('overview', 'grid')}${nav('history', 'chat')}${nav('knowledge', 'book')}</nav>
      <span class="nav-label second">平台管理</span>
      <nav aria-label="平台管理">${nav('agents', 'agent')}${nav('evaluation', 'chart')}</nav>
      <div class="sidebar-bottom"><div class="sidebar-note"><span class="tiny-spark">${icon('spark')}</span><strong>让知识参与每次诊断</strong><p>专业 Agent 与运维经验协同，<br>把复杂故障变成清晰的下一步。</p><a href="#agents">了解 Agent 协作 ${icon('arrow')}</a></div>
      <a class="docs-link" href="/docs" target="_blank" rel="noopener">${icon('terminal')} API 开发文档 ${icon('external')}</a>
      <div class="profile"><span class="avatar">OP</span><span><strong>本地工作区</strong><small>OpsPilot Console · v1.0</small></span><span class="online-dot"></span></div></div>
    </aside>
    <div class="sidebar-backdrop" data-action="close-menu"></div>
    <div class="workspace-main"><header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-menu" data-action="menu" aria-label="打开导航">${icon('menu')}</button><span>工作空间</span>${icon('chevron')}<strong>${pages[state.page]}</strong></div><div class="topbar-right"><span id="service-status" class="service-status">${healthStatus()}</span><span class="header-divider"></span><a class="top-docs" href="/docs" target="_blank" rel="noopener">开发文档 ${icon('external')}</a><span class="avatar small">OP</span></div></header>
      <main id="main" tabindex="-1"></main><footer class="page-footer"><span><span class="footer-dot"></span> OpsPilot · 让 IT 支持更有把握</span><span>Multi-Agent powered · Built for clarity</span></footer></div>`;
  renderPage();
}
function nav(page, symbol) {
  const active = state.page === page || (page === 'overview' && state.page === 'diagnosis');
  return `<a class="nav-item ${active ? 'active' : ''}" href="#${page}" ${active ? 'aria-current="page"' : ''}>${icon(symbol)}<span>${pages[page]}</span>${page === 'evaluation' ? '<span class="nav-pill">EVAL</span>' : ''}${active ? '<span class="nav-active-dot"></span>' : ''}</a>`;
}
function healthStatus() {
  return state.health ? '<span class="online-dot"></span>服务已连接' : `<span class="online-dot ${state.healthError ? 'offline' : 'waiting'}"></span>${state.healthError ? '服务未连接' : '连接中'}`;
}
function renderPage() {
  const renderers = {overview, history: historyPage, diagnosis, knowledge, agents: agentPage, evaluation};
  document.querySelector('#main').innerHTML = renderers[state.page]();
  document.title = `${pages[state.page]} · OpsPilot`;
}
function heading(eyebrow, title, subtitle, action = '') {
  return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${subtitle}</p></div>${action}</div>`;
}
function metric(symbol, label, value, note, color = 'mint') {
  return `<div class="metric-card"><div class="metric-top"><span>${label}</span><span class="metric-icon ${color}">${icon(symbol)}</span></div><div class="metric-value">${esc(value)}</div><div class="metric-note">${note}</div></div>`;
}
function serviceBanner() {
  return state.healthError ? `<div class="notice error">${icon('info')}<span>暂时无法连接诊断服务。${esc(state.healthError)}</span>${button('重新连接', 'refresh', 'refresh', 'text-button')}</div>` : '';
}
function overview() {
  const agentCount = state.health ? Object.keys(state.health.agents).filter(x => x !== 'triage').length : '—';
  const totalKnowledge = state.health ? Object.values(state.health.knowledge).reduce((a, b) => a + b, 0) : '—';
  return `${heading('OPERATIONS, IN FOCUS', '每一次故障，都有清晰的下一步。', '连接专业 Agent 与企业知识，让诊断有依据，让过程可追溯。', `<div class="date-stamp">${icon('clock')}${new Date().toLocaleDateString('zh-CN', {year: 'numeric', month: 'long', day: 'numeric'})}</div>`)}
    ${serviceBanner()}
    <section class="hero"><div class="hero-content"><div class="hero-kicker"><span class="online-dot"></span> YOUR AI OPERATIONS COPILOT</div><h2>复杂问题，<br>交给协作的力量<span>。</span></h2><p>从一句故障描述开始，自动识别意图、检索知识，<br class="desktop-break">由专业 Agent 共同找到解决路径。</p><a class="button dark" href="#diagnosis">${icon('plus')}发起智能诊断 ${icon('arrow')}</a><span class="hero-footnote">5 类专业 Agent · 知识增强 · 全链路可观测</span></div><div class="hero-art" aria-hidden="true"><div class="orbit orbit-outer"></div><div class="orbit orbit-inner"></div><span class="orbit-dot dot-a"></span><span class="orbit-dot dot-b"></span><div class="orbit-center">${icon('bolt')}<span>OpsPilot</span></div><span class="orbit-node node-top">${icon('network')}<span>Network</span></span><span class="orbit-node node-right">${icon('security')}<span>Security</span></span><span class="orbit-node node-bottom">${icon('book')}<span>Knowledge</span></span><span class="orbit-node node-left">${icon('agent')}<span>Multi-Agent</span></span><span class="art-caption">CONNECTED INTELLIGENCE</span></div></section>
    <section class="metrics" aria-label="平台概况">${metric('agent', '专业 Agent', agentCount, '覆盖 5 类 IT 故障领域')}${metric('book', '知识片段', totalKnowledge, '运维知识 + 历史故障案例', 'blue')}${metric('layers', '诊断 Skills', state.skills?.count ?? '—', '按需注入专业处置 SOP', 'purple')}${metric('chart', '最近评测通过率', pct(state.report?.pass_rate), state.report ? `${state.report.passed} / ${state.report.total} 条 · 离线合成评测` : '尚未读取评测报告', 'orange')}</section>
    <div class="dashboard-grid"><section class="panel quick-panel"><div class="panel-heading"><div><h2>${icon('spark')}开始一次诊断</h2><p>告诉 OpsPilot 发生了什么，剩下的我们一起梳理。</p></div>${badge('AI ASSISTED', 'neutral')}</div>${composer(false)}<div class="quick-prompts"><span class="small-label">也可以从常见问题开始</span><div class="prompt-grid">${prompts.map((p, i) => `<button class="prompt-card" data-prompt="${i}"><span class="prompt-symbol ${agents[p.icon].color}">${icon(p.icon)}</span><span>${p.title}</span>${icon('arrow')}</button>`).join('')}</div></div></section>
    <section class="panel agent-roster"><div class="panel-heading"><h2>专业 Agent 团队</h2><a class="text-link" href="#agents">查看全部 ${icon('arrow')}</a></div>${Object.entries(agents).filter(([id]) => id !== 'triage').map(([id, a]) => `<div class="roster-row"><span class="agent-symbol ${a.color}">${icon(id)}</span><div><strong>${a.name}</strong><small>${a.desc}</small></div><span class="roster-state">${state.health ? '<span class="online-dot"></span>已加载' : '未连接'}</span></div>`).join('')}<div class="roster-footer">${icon('layers')} 意图驱动路由，主辅 Agent 协同诊断</div></section></div>
    <section class="panel recent-panel"><div class="panel-heading"><div><h2>最近诊断</h2><p>当前浏览器中的诊断记录</p></div><a href="#history" class="text-link">全部记录 ${icon('arrow')}</a></div>${sessionTable(state.sessions.slice(0, 4))}</section>`;
}
function composer(followup) {
  return `<form id="diagnosis-form" class="composer ${followup ? 'followup' : ''}"><label class="sr-only" for="incident-input">${followup ? '补充故障信息' : '描述故障'}</label><textarea id="incident-input" name="message" maxlength="8000" placeholder="${followup ? '补充排查结果或错误信息，继续诊断…' : '例如：公司 VPN 从今天早上开始连接超时，三个人受影响…'}" required ${state.busy ? 'disabled' : ''}>${esc(state.draft)}</textarea><div class="composer-toolbar"><span>${icon('security')}请勿输入密码、密钥等敏感信息</span><button class="button dark" type="submit" ${state.busy ? 'disabled' : ''}>${icon(state.busy ? 'refresh' : 'spark', state.busy ? 'spin' : '')}${state.busy ? '正在诊断' : followup ? '继续诊断' : '开始诊断'}${state.busy ? '' : icon('arrow')}</button></div></form>`;
}
function sessionTable(items) {
  if (!items.length) return empty('chat', '下一次解决，从这里开始', '发起一次诊断后，问题、处理建议与执行链路会显示在这里。');
  return `<div class="table-scroll"><table><thead><tr><th>故障描述</th><th>负责 Agent</th><th>诊断状态</th><th>时间</th><th></th></tr></thead><tbody>${items.map(s => {
    const r = s.turns.at(-1)?.result;
    return `<tr><td><button class="table-title" data-session="${esc(s.id)}">${esc(s.title)}</button><span class="table-subtitle">${esc(r?.request_id || '')}</span></td><td><span class="agent-inline">${icon(r?.primary_agent || 'agent')}${esc(agentName(r?.primary_agent))}</span></td><td>${resultBadge(r)}</td><td class="muted nowrap">${date(s.updated)}</td><td><button class="icon-button" data-session="${esc(s.id)}" aria-label="查看诊断 ${esc(s.title)}">${icon('arrow')}</button></td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function resultBadge(r) {
  if (!r) return badge('等待诊断', 'neutral');
  if (r.clarification_required) return badge('待补充信息', 'amber');
  if (r.agent_trace?.some(x => x.status === 'failed')) return badge('执行异常', 'rose');
  return badge(r.escalated ? '建议人工介入' : '诊断完成', r.escalated ? 'amber' : 'green');
}
function historyPage() {
  const filtered = state.sessions.filter(x => x.title.toLowerCase().includes(state.historyQuery.toLowerCase()));
  return `${heading('DIAGNOSIS HISTORY', '每一次排查，都值得留存。', '回看故障描述、诊断建议与 Agent 执行依据。', '<a class="button dark" href="#diagnosis" data-action="new">'+icon('plus')+'新建诊断</a>')}<section class="panel"><div class="panel-heading"><h2>诊断记录 <span class="count">${state.sessions.length}</span></h2><label class="search-field">${icon('search')}<input id="history-search" placeholder="搜索故障描述" value="${esc(state.historyQuery)}" aria-label="搜索诊断记录"></label></div><div id="history-table">${sessionTable(filtered)}</div><div class="panel-footnote">${icon('info')}记录仅保存在当前浏览器，最多保留最近 30 次诊断。可在详情中导出。</div></section>`;
}
function diagnosis() {
  const session = currentSession();
  const turn = latestTurn();
  return `${heading('INTELLIGENT DIAGNOSIS', session ? '沿着线索，找到解决路径。' : '描述问题，开启一次智能诊断。', session ? `诊断编号 ${esc(turn?.result?.request_id || '—')} · ${date(session.updated)}` : '补充故障现象、发生时间和影响范围，会让诊断更准确。', button('新建诊断', 'new', 'plus'))}${serviceBanner()}
    <div class="diagnosis-layout"><div class="diagnosis-main">${session ? session.turns.map((t, i) => `<div class="question-bubble"><span class="avatar small">我</span><div><span class="small-label">故障描述 · ${i + 1}</span><p>${esc(t.message)}</p></div></div><section class="panel answer-panel"><div class="panel-heading"><h2><span class="answer-logo">${icon('bolt')}</span>OpsPilot 诊断建议</h2>${resultBadge(t.result)}</div><div class="markdown answer-body">${markdown(t.result.response)}</div><div class="answer-footer"><span>${icon(t.result.primary_agent)}${esc(agentName(t.result.primary_agent))}${t.result.secondary_agents?.length ? ' + ' + t.result.secondary_agents.map(x => esc(agentName(x))).join('、') : ''}</span><button class="text-button" data-copy="${i}">${icon('copy')}复制</button></div></section>`).join('') : `<section class="panel diagnosis-welcome"><span class="large-spark">${icon('spark')}</span><h2>你的 IT 诊断搭档，已就位。</h2><p>连接网络、账号、软件、设备和安全领域的专业能力。</p><div class="prompt-grid">${prompts.map((p, i) => `<button class="prompt-card" data-prompt="${i}">${icon(p.icon)}<span>${p.title}</span>${icon('arrow')}</button>`).join('')}</div></section>`}
    ${state.busy ? `<div class="pending-card" role="status">${icon('refresh', 'spin')}<div><strong>正在分析故障并生成诊断建议…</strong><p>意图识别、知识检索与 Agent 协作完成后，将展示实际执行链路。</p></div></div>` : ''}
    ${state.chatError ? `<div class="notice error" role="alert">${icon('info')}<span>${esc(state.chatError)}</span></div>` : ''}${composer(!!session)}<p class="under-composer">诊断建议供排查参考，涉及权限变更或生产操作时请由授权人员执行。</p></div><aside class="diagnosis-inspector">${turn ? inspector(turn) : `<section class="panel"><div class="panel-heading"><h2>${icon('layers')}诊断如何发生</h2></div><div class="intro-steps">${[['01','理解问题','识别故障意图、实体与紧急程度'],['02','连接知识','多角度检索 SOP 与历史案例'],['03','Agent 协作','匹配主辅专家，注入诊断规范'],['04','给出路径','输出排查建议与可追溯依据']].map(([n,t,d]) => `<div class="intro-step"><span>${n}</span><div><strong>${t}</strong><p>${d}</p></div></div>`).join('')}</div></section>`}</aside></div>`;
}
function inspector(turn) {
  const r = turn.result;
  const urgency = {low: '低', medium: '中', high: '高', critical: '严重'};
  const traceNames = {intent_recognition: '意图识别', rag_retrieval: '知识检索', routing: 'Agent 路由', agent_execution: 'Agent 执行', fallback: '降级处理'};
  return `<section class="panel"><div class="panel-heading"><h2>诊断概况</h2>${badge('LIVE RESULT', 'neutral')}</div><div class="inspector-body"><div class="kv"><span>故障类别</span><strong>${esc(agentName(r.intent))}</strong></div><div class="kv"><span>识别置信度</span><strong>${pct(r.confidence)}</strong></div><div class="progress-track"><span style="width:${Math.min(100, Math.max(0, Number(r.confidence) * 100))}%"></span></div><div class="kv"><span>紧急程度</span>${badge(urgency[r.urgency] || r.urgency, ['high','critical'].includes(r.urgency) ? 'rose' : 'neutral')}</div><div class="kv"><span>知识引用</span><strong>${r.knowledge_used ? '已使用检索证据' : '未使用'}</strong></div><div class="kv"><span>请求总耗时</span><strong>${seconds(turn.elapsed)}</strong></div></div></section>
    <section class="panel"><div class="panel-heading"><h2>执行链路</h2><span class="count">${r.agent_trace?.length || 0}</span></div><div class="trace-list">${(r.agent_trace || []).map(step => `<details class="trace-step" ${step.status === 'failed' ? 'open' : ''}><summary><span class="trace-dot ${step.status === 'failed' ? 'failed' : ''}">${icon(step.status === 'failed' ? 'close' : 'check')}</span><div><strong>${traceNames[step.stage] || esc(step.stage)}</strong><small>${step.agent ? esc(agentName(step.agent)) : step.stage === 'rag_retrieval' ? `${step.evidence_count ?? 0} 条证据 · ${step.reranked ? '已重排' : '未重排'}` : esc(step.status)}</small></div>${icon('down')}</summary><pre>${esc(JSON.stringify(step, null, 2))}</pre></details>`).join('')}</div></section>
    <section class="panel"><div class="panel-heading"><h2>路由依据</h2></div><div class="inspector-body"><p class="routing-reason">${esc(r.routing_reason)}</p>${Object.keys(r.entities || {}).length ? '<span class="small-label">识别到的实体</span><div class="entity-tags">'+Object.values(r.entities).flat().map(x => badge(x, 'neutral')).join('')+'</div>' : ''}${r.rewritten_queries?.length ? '<details class="query-details"><summary>检索改写 · '+r.rewritten_queries.length+' 个查询 '+icon('down')+'</summary><ul>'+r.rewritten_queries.map(q => '<li>'+esc(q)+'</li>').join('')+'</ul></details>' : ''}</div></section>${button('导出本次诊断', 'export-session', 'download', 'button full-width')}`;
}
function knowledge() {
  const items = (state.search?.items || state.documents).filter(x => state.source === 'all' || x.source === state.source);
  return `${heading('KNOWLEDGE, CONNECTED', '让经验成为可检索的答案。', '统一管理运维 SOP 与历史故障案例，为 Agent 提供可靠的诊断依据。', button('添加知识', 'add-document', 'plus', 'button dark'))}${serviceBanner()}
    <div class="knowledge-stats"><div>${icon('book')}<span>运维知识</span><strong>${state.health?.knowledge?.knowledge ?? '—'}</strong><small>个片段</small></div><div>${icon('clock')}<span>历史案例</span><strong>${state.health?.knowledge?.incident ?? '—'}</strong><small>个片段</small></div><div>${icon('layers')}<span>双源召回</span><strong class="text-value">Query Rewrite + Rerank</strong></div></div>
    <section class="panel search-panel"><form id="knowledge-search"><label class="search-field large">${icon('search')}<input id="knowledge-query" name="query" placeholder="描述你想解决的问题，跨知识库检索相关证据…" value="${esc(state.query)}" required maxlength="2000" aria-label="知识检索问题"></label><button class="button dark" ${state.searching ? 'disabled' : ''}>${icon(state.searching ? 'refresh' : 'spark', state.searching ? 'spin' : '')}${state.searching ? '检索中' : '语义检索'}</button></form><div class="search-hint">${icon('info')}将自动改写查询、并行召回，再对结果进行相关性重排。</div></section>
    <div class="section-toolbar"><div class="tabs" aria-label="知识来源">${[['all','全部内容'],['knowledge','运维知识'],['incident','历史案例']].map(([v,t]) => `<button class="tab ${state.source === v ? 'active' : ''}" data-source="${v}" aria-pressed="${state.source === v}">${t}</button>`).join('')}</div><span class="muted">${state.search ? button('返回知识库', 'clear-search', 'close', 'text-button') : `当前显示 ${items.length} 个片段`}</span></div>
    ${state.search ? `<div class="search-meta">${badge(state.search.reranked ? 'LLM 已重排' : '未重排', 'green')}<span>${(state.search.rewritten_queries || []).map(q => `<span class="query-chip">${esc(q)}</span>`).join('')}</span></div>` : ''}
    ${state.knowledgeError ? `<div class="notice error">${icon('info')}${esc(state.knowledgeError)}${button('重试', 'load-knowledge', 'refresh', 'text-button')}</div>` : ''}
    <div class="document-grid">${items.map((doc,i) => `<article class="panel document-card"><div class="document-top"><span class="document-icon ${doc.source === 'incident' ? 'orange' : 'mint'}">${icon(doc.source === 'incident' ? 'clock' : 'book')}</span>${badge(doc.source === 'incident' ? '历史案例' : '运维 SOP', 'neutral')}</div><h2>${esc(doc.title || '未命名片段')}</h2><p>${esc(doc.content)}</p><div class="document-footer"><span>${doc.content?.length || 0} 字 · 知识片段</span><button class="text-button" data-document="${i}">阅读内容 ${icon('arrow')}</button></div></article>`).join('')}</div>${!items.length ? empty('book', state.searching ? '正在检索相关知识…' : state.knowledgeLoaded ? '没有匹配的知识片段' : '正在连接知识库…', '可添加运维 SOP，或尝试其他检索描述。') : ''}`;
}
function agentPage() {
  return `${heading('SPECIALISTS, WORKING TOGETHER', '各有所长，协同解决。', '根据故障意图动态选择主辅 Agent，为每位专家注入匹配的诊断 Skills。', `<button class="button" data-action="reload-skills" ${state.skillReloading ? 'disabled' : ''}>${icon('refresh', state.skillReloading ? 'spin' : '')}${state.skillReloading ? '加载中' : '重新加载 Skills'}</button>`)}${serviceBanner()}
    <section class="collaboration-strip"><div>${icon('chat')}<span>用户故障</span></div>${icon('arrow')}<div>${icon('filter')}<span>意图与实体</span></div>${icon('arrow')}<div class="accent">${icon('agent')}<span>主辅 Agent</span></div>${icon('plus')}<div>${icon('book')}<span>诊断 Skills</span></div>${icon('arrow')}<div>${icon('check')}<span>可追溯建议</span></div></section>
    <div class="agent-cards">${Object.entries(agents).map(([id, a]) => {
      const skills = state.skills?.skills?.filter(x => x.agents.includes(id)) || [];
      const stats = state.health?.agents?.[id];
      return `<article class="panel agent-card"><div class="agent-card-top"><span class="agent-symbol large ${a.color}">${icon(id === 'triage' ? 'filter' : id)}</span>${badge(stats ? '已加载' : '未连接', stats ? 'green' : 'neutral')}</div><span class="eyebrow">${a.english.toUpperCase()}</span><h2>${a.name}</h2><p>${a.desc}</p><div class="agent-stats"><div><strong>${stats?.total ?? '—'}</strong><span>本次启动调用数</span></div><div><strong>${pct(stats?.success_rate)}</strong><span>调用成功率</span></div></div><div class="skill-links"><span class="small-label">注入的 SKILLS</span>${skills.length ? skills.map(s => `<button data-skill="${esc(s.name)}">${icon('file')}<span>${esc(s.name)}</span>${icon('chevron')}</button>`).join('') : '<span class="muted">'+(id === 'triage' ? '通用分诊指令 · 补充信息与故障分流' : '暂未读取到匹配的 Skill')+'</span>'}</div></article>`;
    }).join('')}</div>${state.skills?.errors?.length ? `<div class="notice error">${esc(state.skills.errors.join('；'))}</div>` : ''}`;
}
function evaluation() {
  const r = state.report;
  const scores = r?.avg_scores || {};
  const filtered = r?.results.filter(x => state.evalFilter === 'all' || !x.passed) || [];
  return `${heading('MEASURE. LEARN. IMPROVE.', '用评测，把每一步做扎实。', '覆盖意图、路由、检索与端到端回复，用可审计的数据持续回归。', `<div class="heading-actions">${r ? button('导出报告', 'export-report', 'download') : ''}<button class="button dark" data-action="eval-dialog" ${state.evaluating ? 'disabled' : ''}>${icon(state.evaluating ? 'refresh' : 'chart', state.evaluating ? 'spin' : '')}${state.evaluating ? '评测运行中' : '运行评测'}</button></div>`)}
    ${state.evaluating ? `<div class="notice">${icon('refresh','spin')}评测任务正在后台运行，完成后自动更新结果。请保持当前页面打开。</div>` : ''}
    ${state.reportError ? `<div class="notice error">${icon('info')}${esc(state.reportError)}${button('重新读取', 'load-report', 'refresh', 'text-button')}</div>` : ''}
    ${!r ? `<section class="panel">${empty('chart','暂无可用的评测报告','运行评测后，这里将展示真实指标、失败样本及模型判分。')}</section>` : `
    <div class="report-banner"><div>${badge('已完成', 'green')}<strong>${esc(r.dataset_name)}</strong><span>v${esc(r.dataset_version)}</span></div><span>${icon('clock')}最近运行 ${date(r.timestamp)}</span></div>
    <section class="metrics">${metric('check','样本通过率',pct(r.pass_rate),`${r.passed} / ${r.total} 条样本通过`)}${metric('filter','主辅路由精确匹配',pct(scores.routing_exact_match),`${r.breakdown.routing} 条路由用例`,'blue')}${metric('spark','Judge 质量均分',pct(scores.end_to_end_quality),`${r.breakdown.dialog} 条端到端用例`,'purple')}${metric('clock','评测耗时 P95',seconds(scores.latency_p95_ms),'端到端计时包含 LLM Judge','orange')}</section>
    <div class="evaluation-grid"><section class="panel"><div class="panel-heading"><h2>能力评测</h2>${badge('OFFLINE BENCHMARK','neutral')}</div><div class="score-bars">${[['Intent Macro-F1',scores.intent_macro_f1,'意图识别'],['Clarification F1',scores.clarification_f1,'澄清判断'],['Secondary Agent F1',scores.secondary_agent_f1,'辅助路由'],['Recall@4',scores.rag_recall_at_4,'知识检索'],['E2E primary accuracy',scores.dialog_primary_accuracy,'主 Agent 命中']].map(([n,v,t]) => `<div class="score-row"><div><span>${t} <small>${n}</small></span><strong>${pct(v)}</strong></div><div class="progress-track"><span style="width:${Math.min(100,Math.max(0,(v || 0)*100))}%"></span></div></div>`).join('')}</div></section><section class="panel dataset-panel"><div class="panel-heading"><h2>评测集构成</h2><span class="count">${r.total}</span></div><div class="dataset-chart" role="img" aria-label="${esc(Object.entries(r.breakdown).map(([k,v])=>k+' '+v+'条').join('，'))}">${Object.entries(r.breakdown).map(([key,val],i)=>`<span class="segment segment-${i}" style="flex:${val}">${val}</span>`).join('')}</div><div class="dataset-legend">${Object.entries(r.breakdown).map(([key,val],i)=>`<div><span><i class="legend-dot segment-${i}"></i>${({intent:'意图与澄清',routing:'Agent 路由',retrieval:'RAG 检索',dialog:'端到端诊断'})[key] || esc(key)}</span><strong>${val} 条</strong></div>`).join('')}</div><div class="dataset-note">${icon('info')}<p>自建合成离线评测集。历史评测的检索语料为 7 篇内置知识；Judge 分数为模型评估结果。</p></div></section></div>
    <section class="panel failures-panel"><div class="panel-heading"><div><h2>用例明细</h2><p>保留失败样本，让下一次优化有据可依。</p></div><div class="tabs"><button class="tab ${state.evalFilter==='failed'?'active':''}" data-eval-filter="failed">未通过 ${r.total-r.passed}</button><button class="tab ${state.evalFilter==='all'?'active':''}" data-eval-filter="all">全部 ${r.total}</button></div></div><div class="eval-cases">${filtered.length ? filtered.map(x => `<details class="eval-case"><summary>${badge(x.passed?'通过':'未通过',x.passed?'green':'rose')}<strong>${esc(x.test_id)}</strong><span>${esc(x.detail)}</span>${icon('down')}</summary><div class="eval-case-body"><div class="entity-tags">${Object.entries(x.scores).map(([k,v])=>badge(k+' '+pct(v),'neutral')).join('')}</div><pre>${esc(JSON.stringify(x.metadata,null,2))}</pre></div></details>`).join('') : empty('check','当前筛选下没有失败样本','查看全部用例了解本次评测详情。')}</div></section>`}`;
}

function navigate(page) { if (location.hash === '#'+page) { state.page = page; shell(); } else location.hash = page; }
async function loadHealth() {
  try { state.health = await api('/health'); state.healthError = ''; }
  catch (e) { state.health = null; state.healthError = e.message; }
}
async function loadSkills() { try { state.skills = await api('/skills'); } catch { state.skills = null; } }
async function loadReport() {
  try { state.report = await api('/eval/latest'); state.reportError = ''; }
  catch (e) { state.reportError = e.status === 404 ? '当前没有已保存的评测报告。' : e.message; }
}
async function loadDocuments() {
  try { const data = await api('/knowledge/documents'); state.documents = data.items; state.knowledgeLoaded = true; state.knowledgeError = ''; }
  catch(e) { state.knowledgeError = e.message; }
  if (state.page === 'knowledge') renderPage();
}
async function refresh() {
  await Promise.allSettled([loadHealth(),loadSkills(),loadReport()]);
  shell();
}
function saveSessions() {
  state.sessions = state.sessions.slice(0,30);
  try { localStorage.setItem(storageKey,JSON.stringify(state.sessions)); }
  catch { toast('浏览器存储不可用，本次记录暂未持久保存。',true); }
}
async function submitDiagnosis(form) {
  if (state.busy) return;
  const message = new FormData(form).get('message').trim();
  if (!message) return;
  const session = state.page === 'diagnosis' ? currentSession() : null;
  if (!session) state.current = null;
  const history = (session?.turns || []).flatMap(t=>[{role:'user',content:t.message},{role:'assistant',content:t.result.response}]).slice(-10);
  state.busy = true; state.chatError = ''; state.draft = message;
  navigate('diagnosis');
  const start = performance.now();
  try {
    const result = await api('/chat',{method:'POST',body:JSON.stringify({message,user_id:'console-user',history})},120000);
    const turn = {message,result,elapsed:performance.now()-start};
    if (session) { session.turns.push(turn); session.updated = new Date().toISOString(); state.current=session.id; }
    else {
      const created = {id:crypto.randomUUID(),title:message,updated:new Date().toISOString(),turns:[turn]};
      state.sessions.unshift(created); state.current=created.id;
    }
    state.sessions.sort((a,b)=>b.updated.localeCompare(a.updated));
    state.draft=''; saveSessions();
    await loadHealth();
  } catch(e) { state.chatError=e.message; toast(e.message,true); }
  finally { state.busy=false; if (state.page==='diagnosis' || state.page==='overview' || state.page==='history') renderPage(); }
}
function openModal(title, content) {
  modal.innerHTML=`<div class="modal-heading"><h2 id="modal-title">${esc(title)}</h2><button class="icon-button" data-action="close-modal" aria-label="关闭弹窗">${icon('close')}</button></div><div class="modal-body">${content}</div>`;
  if (!modal.open) modal.showModal();
}
function documentModal() {
  openModal('添加知识',`<form id="add-document-form"><label class="field">知识类型<select name="source"><option value="knowledge">运维知识 / SOP</option><option value="incident">历史故障案例</option></select></label><label class="field">标题<input name="title" required maxlength="200" placeholder="例如：VPN 连接故障排查 SOP"></label><label class="field">正文<textarea name="content" rows="9" required maxlength="100000" placeholder="描述故障现象、诊断步骤、处理建议与验证方法…"></textarea></label><p class="muted">保存后会切分为知识片段，写入 ChromaDB 并参与检索。</p><button class="button dark full-width" type="submit">${icon('plus')}保存到知识库</button><div class="form-error" role="alert"></div></form>`);
}
async function addDocument(form) {
  const values = new FormData(form), title=values.get('title').trim(), content=values.get('content').trim();
  if (!title || !content) { form.querySelector('.form-error').textContent='标题和正文不能为空。'; return; }
  const submit=form.querySelector('[type=submit]'); submit.disabled=true;
  try {
    const result=await api('/knowledge/add',{method:'POST',body:JSON.stringify({source:values.get('source'),documents:[{title,content}]})},120000);
    modal.close(); toast(`已添加 ${result.added_chunks} 个知识片段`); state.search=null;
    await loadHealth(); await loadDocuments();
  } catch(e) { form.querySelector('.form-error').textContent=e.message; }
  finally { submit.disabled=false; }
}
async function searchKnowledge(form) {
  if(state.searching) return;
  state.query=new FormData(form).get('query').trim(); if(!state.query) return;
  state.searching=true; state.knowledgeError=''; renderPage();
  try { state.search=await api(`/search?query=${encodeURIComponent(state.query)}&top_k=4`,{},90000); }
  catch(e) { state.knowledgeError=e.message; }
  finally { state.searching=false; if(state.page==='knowledge') renderPage(); }
}
function evalDialog() {
  openModal('运行回归评测',`<form id="eval-form"><p class="modal-intro">使用当前模型执行评测，并更新最近一次报告。评测会产生模型 API 调用。</p><label class="radio-card"><input type="radio" name="suite" value="smoke" checked><span><strong>快速回归</strong><small>16 条内置用例 · 检查核心链路</small></span></label><label class="radio-card"><input type="radio" name="suite" value="full"><span><strong>完整评测集</strong><small>200 条用例 · 覆盖四类评测任务</small></span></label><div class="notice">${icon('info')}运行前可先导出已有报告。全量评测可能需要数分钟。</div><button class="button dark full-width" type="submit">${icon('chart')}开始运行</button></form>`);
}
async function runEvaluation(form) {
  if(state.evaluating) return;
  const full_dataset=new FormData(form).get('suite')==='full';
  state.evaluating=true; state.reportError=''; modal.close(); renderPage();
  try { state.report=await api('/eval/run',{method:'POST',body:JSON.stringify({full_dataset})},900000); toast(`评测完成：${state.report.passed} / ${state.report.total} 条通过`); }
  catch(e) { state.reportError=e.message; toast(e.message,true); }
  finally { state.evaluating=false; if(state.page==='evaluation') renderPage(); }
}

document.addEventListener('submit', event => {
  const form=event.target;
  const handlers={'diagnosis-form':submitDiagnosis,'knowledge-search':searchKnowledge,'add-document-form':addDocument,'eval-form':runEvaluation};
  if(handlers[form.id]) { event.preventDefault(); handlers[form.id](form); }
});
document.addEventListener('input',event=>{
  if(event.target.id==='incident-input') state.draft=event.target.value;
  if(event.target.id==='knowledge-query') state.query=event.target.value;
  if(event.target.id==='history-search') {
    state.historyQuery=event.target.value;
    document.querySelector('#history-table').innerHTML=sessionTable(state.sessions.filter(x=>x.title.toLowerCase().includes(state.historyQuery.toLowerCase())));
  }
});
document.addEventListener('keydown',event=>{
  if(event.target.id==='incident-input' && event.key==='Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); event.target.form.requestSubmit(); }
});
document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-action],[data-prompt],[data-session],[data-source],[data-document],[data-skill],[data-copy],[data-eval-filter]');
  if(!el) return;
  try {
    if(el.dataset.prompt!==undefined) {
      if(state.busy) { toast('当前诊断仍在进行，请稍候。'); return; }
      state.draft=prompts[Number(el.dataset.prompt)].text;
      const input=document.querySelector('#incident-input'); input.value=state.draft; input.focus(); input.scrollIntoView({behavior:'smooth',block:'center'}); return;
    }
    if(el.dataset.session) {
      if(state.busy) { toast('当前诊断仍在进行，请稍候。'); return; }
      state.current=el.dataset.session; state.draft=''; state.chatError=''; navigate('diagnosis'); return;
    }
    if(el.dataset.source) { state.source=el.dataset.source; renderPage(); return; }
    if(el.dataset.document!==undefined) {
      const doc=(state.search?.items || state.documents).filter(x=>state.source==='all'||x.source===state.source)[Number(el.dataset.document)];
      openModal(doc.title,`<div class="document-meta">${badge(doc.source==='incident'?'历史案例':'运维 SOP','green')}</div><div class="markdown">${markdown(doc.content)}</div>`); return;
    }
    if(el.dataset.skill) {
      openModal(el.dataset.skill,'<p class="muted">正在读取诊断规范…</p>');
      const s=await api('/skills/'+encodeURIComponent(el.dataset.skill));
      openModal(s.name,`<p class="muted">${esc(s.description)}</p><div class="entity-tags">${s.agents.map(a=>badge(agentName(a),'green')).join('')}${badge(s.enabled?'已启用':'未启用','neutral')}</div><div class="markdown">${markdown(s.content)}</div>`); return;
    }
    if(el.dataset.copy!==undefined) { await navigator.clipboard.writeText(currentSession().turns[Number(el.dataset.copy)].result.response); toast('诊断建议已复制'); return; }
    if(el.dataset.evalFilter) { state.evalFilter=el.dataset.evalFilter; renderPage(); return; }
    switch(el.dataset.action) {
      case 'skip': event.preventDefault(); document.querySelector('#main').focus(); document.querySelector('#main').scrollIntoView({block:'start'}); break;
      case 'menu': document.body.classList.add('menu-open'); break;
      case 'close-menu': document.body.classList.remove('menu-open'); break;
      case 'close-modal': modal.close(); break;
      case 'new':
        event.preventDefault(); if(state.busy) { toast('当前诊断仍在进行，请稍候。'); break; }
        state.current=null; state.draft=''; state.chatError=''; navigate('diagnosis'); break;
      case 'refresh': await refresh(); break;
      case 'load-knowledge': await loadDocuments(); break;
      case 'clear-search': state.search=null; state.query=''; state.knowledgeError=''; renderPage(); break;
      case 'add-document': documentModal(); break;
      case 'export-session': if(currentSession()) download('opspilot-diagnosis-'+currentSession().id+'.json',currentSession()); break;
      case 'export-report': if(state.report) download(state.report.dataset_name+'-report.json',state.report); break;
      case 'load-report': await loadReport(); renderPage(); break;
      case 'eval-dialog': evalDialog(); break;
      case 'reload-skills':
        state.skillReloading=true; renderPage();
        try { state.skills=await api('/skills/reload',{method:'POST'}); toast(`已加载 ${state.skills.count} 个 Skills`); }
        finally { state.skillReloading=false; if(state.page==='agents') renderPage(); } break;
    }
  } catch(e) { toast(e.message,true); }
});
window.addEventListener('hashchange',()=>{
  state.page=location.hash.slice(1)||'overview'; document.body.classList.remove('menu-open'); shell(); window.scrollTo(0,0);
  if(state.page==='knowledge'&&!state.knowledgeLoaded) loadDocuments();
});
shell();
await refresh();
if(state.page==='knowledge') loadDocuments();
