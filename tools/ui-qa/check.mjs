import {chromium} from 'playwright';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/i, '$1'));
const artifacts = path.join(root, 'artifacts');
await mkdir(artifacts, {recursive: true});
const live = process.argv.includes('--live');
const base = process.env.OPSPILOT_URL || 'http://localhost';
const browser = await chromium.launch({channel: 'msedge', headless: true});
const context = await browser.newContext({viewport: {width: 1440, height: 1050}, locale: 'zh-CN'});
const page = await context.newPage();
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
const check = (name, detail = '') => { checks.push({name, detail, passed: true}); console.log('PASS', name, detail); };
const shot = name => page.screenshot({path: path.join(artifacts, name + '.png'), fullPage: true, animations: 'disabled'});

try {
  await page.goto(base, {waitUntil: 'domcontentloaded'});
  await page.getByText('服务已连接', {exact: true}).waitFor();
  assert.equal(await page.locator('.metric-value').first().textContent(), '5');
  assert.equal(await page.locator('.metric-value').nth(1).textContent(), '7');
  assert.equal(await page.locator('.metric-value').nth(2).textContent(), '5');
  const theme = await page.evaluate(() => ({
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    glass: getComputedStyle(document.querySelector('.sidebar')).backdropFilter,
    titleSize: parseFloat(getComputedStyle(document.querySelector('h1')).fontSize),
    bodySize: parseFloat(getComputedStyle(document.querySelector('.hero p')).fontSize),
  }));
  assert.equal(theme.accent, '#4f7cff');
  assert.ok(theme.glass.includes('blur'));
  assert.ok(theme.titleSize >= 28 && theme.bodySize >= 14);
  assert.equal(await page.getByRole('button', {name: '打开导航'}).isVisible(), false);
  check('Liquid Glass tokens, frosted navigation and readable desktop typography');
  await shot('01-workspace-desktop');
  check('Dashboard shows live platform counts');

  await page.getByRole('link', {name: '知识库', exact: true}).click();
  await page.locator('.document-card').first().waitFor();
  assert.equal(await page.locator('.document-card').count(), 7);
  await page.getByRole('button', {name: '历史案例', exact: true}).click();
  assert.equal(await page.locator('.document-card').count(), 3);
  await page.getByRole('button', {name: '阅读内容', exact: false}).first().click();
  await page.locator('dialog[open] .markdown').waitFor();
  assert.ok((await page.locator('dialog .markdown').textContent()).length > 20);
  await page.keyboard.press('Escape');
  await page.getByRole('button', {name: '全部内容', exact: true}).click();
  await shot('02-knowledge-desktop');
  await page.getByRole('button', {name: '添加知识', exact: true}).click();
  assert.equal(await page.locator('#add-document-form').count(), 1);
  await page.keyboard.press('Escape');
  check('Knowledge list, source filter, detail and add form');

  if (live) {
    await page.locator('#knowledge-query').fill('多人 VPN 认证失败但普通网络正常');
    await page.getByRole('button', {name: '语义检索', exact: true}).click();
    await page.locator('.search-meta').waitFor({timeout: 90000});
    assert.ok(await page.locator('.document-card').count() > 0);
    assert.ok(await page.locator('.query-chip').count() > 1);
    await page.getByRole('button', {name: '返回知识库', exact: false}).click();
    check('Live semantic search returns evidence and rewritten queries');
  }

  await page.getByRole('link', {name: 'Agent & Skills', exact: true}).click();
  await page.locator('.agent-card').first().waitFor();
  assert.equal(await page.locator('.agent-card').count(), 6);
  await page.locator('[data-skill]').first().click();
  await page.locator('dialog[open] .markdown').waitFor();
  assert.ok((await page.locator('dialog .markdown').textContent()).length > 50);
  await page.keyboard.press('Escape');
  await shot('03-agents-desktop');
  check('Six Agent roles and registered Skill content');

  await page.getByRole('link', {name: '评测中心', exact: false}).click();
  await page.getByText('opspilot_eval_200', {exact: true}).waitFor();
  assert.equal(await page.locator('.eval-case').count(), 4);
  await page.locator('.eval-case summary').first().click();
  assert.ok((await page.locator('.eval-case[open] pre').textContent()).includes('expected_primary'));
  await shot('04-evaluation-desktop');
  await page.getByRole('button', {name: '全部 200', exact: true}).click();
  assert.equal(await page.locator('.eval-case').count(), 200);
  await page.getByRole('button', {name: '运行评测', exact: true}).click();
  assert.equal(await page.locator('#eval-form input[value=smoke]').isChecked(), true);
  await page.keyboard.press('Escape');
  check('Saved evaluation: 200 cases, 4 failures, expandable evidence; no new evaluation run');

  await page.getByRole('link', {name: '工作台', exact: true}).click();
  await page.getByRole('button', {name: 'VPN 连接异常', exact: false}).click();
  assert.ok((await page.locator('#incident-input').inputValue()).includes('VPN'));
  if (live) {
    await page.getByRole('button', {name: '开始诊断', exact: false}).click();
    await page.locator('.answer-panel').first().waitFor({timeout: 120000});
    assert.ok((await page.locator('.answer-body').first().textContent()).length > 50);
    assert.equal(await page.locator('.trace-dot.failed').count(), 0);
    assert.ok(await page.locator('.trace-step').count() >= 3);
    await shot('05-live-diagnosis-desktop');
    check('Live VPN diagnosis through the UI', 'Real LLM + RAG + Agent trace');
    const pending = page.waitForRequest(request => request.url().endsWith('/chat') && request.method() === 'POST');
    await page.locator('#incident-input').fill('VPN 客户端提示连接超时，我们三人都从今天早上开始无法访问内网，还需要补充什么信息？');
    await page.getByRole('button', {name: '继续诊断', exact: false}).click();
    const request = await pending;
    assert.equal(request.postDataJSON().history.length, 2);
    await page.locator('.answer-panel').nth(1).waitFor({timeout: 120000});
    check('Follow-up sends previous user and assistant turns');
    await page.getByRole('link', {name: '诊断记录', exact: true}).click();
    await page.locator('#history-search').waitFor();
    assert.equal(await page.locator('.table-title').count(), 1);
    await page.locator('#history-search').fill('不存在的故障');
    assert.equal(await page.locator('.table-title').count(), 0);
    await page.locator('#history-search').fill('VPN');
    assert.equal(await page.locator('.table-title').count(), 1);
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.locator('.table-title').first().waitFor();
    check('History search and persistence after reload');
  }

  // A separate explicit API fixture checks HTML escaping, not model quality.
  const fixtureContext = await browser.newContext({viewport: {width: 1440, height: 1050}});
  const fixturePage = await fixtureContext.newPage();
  await fixturePage.route('**/chat', route => route.fulfill({json: {
    request_id: 'ui-fixture', response: '<img src=x onerror="window.__unsafe=1"> **safe text**',
    intent: 'other', confidence: .2, urgency: 'low', entities: {}, primary_agent: 'triage',
    secondary_agents: [], clarification_required: true, routing_reason: 'UI fixture',
    agent_trace: [{stage: 'intent_recognition', status: 'clarify'}], knowledge_used: false,
    rewritten_queries: [], escalated: false, latency_ms: 2,
  }}));
  await fixturePage.goto(base + '/#diagnosis', {waitUntil: 'domcontentloaded'});
  await fixturePage.getByText('服务已连接', {exact: true}).waitFor();
  await fixturePage.getByRole('button', {name: '新建诊断', exact: true}).click();
  await fixturePage.locator('#incident-input').fill('HTML escaping verification');
  await fixturePage.getByRole('button', {name: '开始诊断', exact: false}).click();
  await fixturePage.locator('.answer-panel').waitFor();
  assert.equal(await fixturePage.locator('.answer-body img').count(), 0);
  assert.ok((await fixturePage.locator('.answer-body').textContent()).includes('<img'));
  assert.equal(await fixturePage.evaluate(() => window.__unsafe), undefined);
  await fixtureContext.close();
  check('Clarification state and escaped model HTML (explicit fixture)');

  await page.setViewportSize({width: 390, height: 844});
  for (const route of ['overview', 'knowledge', 'agents', 'evaluation', 'diagnosis', 'history']) {
    await page.goto(base + '/#' + route, {waitUntil: 'domcontentloaded'});
    await page.getByText('服务已连接', {exact: true}).waitFor();
    await page.waitForFunction(title => document.title.startsWith(title), ({overview:'工作台',knowledge:'知识库',agents:'Agent & Skills',evaluation:'评测中心',diagnosis:'智能诊断',history:'诊断记录'})[route]);
    const dimensions = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
    assert.ok(dimensions.scroll <= dimensions.width + 1, `${route} mobile overflow: ${JSON.stringify(dimensions)}`);
    if (['overview','diagnosis','evaluation'].includes(route)) await shot('mobile-' + route);
    check('Mobile width: ' + route, '390 px; no page-level horizontal overflow');
  }
  await page.getByRole('button', {name: '打开导航'}).click();
  await page.getByRole('link', {name: '知识库', exact: true}).click();
  assert.equal(await page.locator('body.menu-open').count(), 0);
  check('Mobile drawer navigation');
  await page.getByRole('link', {name: '跳至主内容'}).focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#main').evaluate(el => el === document.activeElement), true);
  assert.ok(page.url().endsWith('#knowledge'));
  check('Keyboard skip link focuses main content without changing the route');

  for (const width of [320, 768, 1024]) {
    await page.setViewportSize({width, height: 1000});
    for (const route of ['overview', 'knowledge', 'agents', 'evaluation', 'diagnosis', 'history']) {
      await page.goto(base + '/#' + route, {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(title => document.title.startsWith(title), ({overview:'工作台',knowledge:'知识库',agents:'Agent & Skills',evaluation:'评测中心',diagnosis:'智能诊断',history:'诊断记录'})[route]);
      const dimensions = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
      assert.ok(dimensions.scroll <= dimensions.width + 1, `${route} ${width}px overflow: ${JSON.stringify(dimensions)}`);
    }
    check('Responsive layout across six pages', `${width} px; no horizontal overflow`);
  }

  const offline = await context.newPage();
  await offline.route('**/health', route => route.abort('connectionrefused'));
  await offline.goto(base, {waitUntil: 'domcontentloaded'});
  await offline.getByText('服务未连接', {exact: true}).waitFor();
  assert.equal(await offline.locator('.metric-value').first().textContent(), '—');
  await offline.close();
  check('Service error state does not fabricate live counts');
  assert.deepEqual(errors, [], 'browser runtime errors');
  await writeFile(path.join(artifacts, live ? 'qa-report-live.json' : 'qa-report.json'), JSON.stringify({timestamp: new Date().toISOString(), base, live, checks, errors}, null, 2));
  console.log(`PASS ${checks.length} browser checks; artifacts: ${artifacts}`);
} catch(error) {
  await shot('failure');
  await writeFile(path.join(artifacts, 'qa-failure.json'), JSON.stringify({error: error.stack, checks, errors}, null, 2));
  throw error;
} finally { await browser.close(); }
