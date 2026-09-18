// Small, dependency-free UI primitives. All model and user text is escaped.
const paths = {
  bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7z"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 10 10 0 0 1-4-.8L3 21l1.7-5A9 9 0 1 1 21 11.5Z"/><path d="M8 9h8M8 13h5"/>',
  book: '<path d="M12 5C9 3 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-2-1-6-1-9 1Zm0 0v15"/>',
  agent: '<rect x="4" y="6" width="16" height="14" rx="4"/><path d="M12 2v4M1 11v5M23 11v5M8 15h8"/><circle cx="8" cy="11" r=".5"/><circle cx="16" cy="11" r=".5"/>',
  chart: '<path d="M4 3v17h17M8 15l4-5 4 2 5-8"/>',
  arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  search: '<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
  refresh: '<path d="M20 7a9 9 0 1 0 1 9M20 3v5h-5"/>',
  network: '<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M8 16a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r=".5"/>',
  identity_access: '<rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
  software: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 8h18m-12 4-3 3 3 3m6-6 3 3-3 3"/>',
  device: '<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M12 16v5m-5 0h10"/>',
  security: '<path d="m12 2 8 3v6c0 5-5 9-8 11-3-2-8-6-8-11V5Zm-4 9 3 3 5-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 2H5v20h14V7Zm0 0v5h5M8 12h8M8 16h6"/>',
  terminal: '<rect x="2" y="3" width="20" height="18" rx="3"/><path d="m6 8 4 4-4 4m7 0h5"/>',
  external: '<path d="M14 3h7v7m0-7-11 11M10 3H4v17h17v-7"/>',
  copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5"/>',
  filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7Zm-10 10 10 5 10-5M2 17l10 5 10-5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  send: '<path d="m3 3 18 9-18 9 4-9Zm4 9h14"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
};

export const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.agent}</svg>`;
export const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
export const pct = value => Number.isFinite(value) ? `${(value * 100).toFixed(1).replace(/\.0$/, '')}%` : '—';
export const seconds = value => Number.isFinite(value) ? `${(value / 1000).toFixed(2)} s` : '—';
export const date = value => value && !Number.isNaN(new Date(value).valueOf()) ? new Date(value).toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}) : '—';
export const agents = {
  network: {name: '网络诊断', english: 'Network Agent', desc: 'VPN、DNS、连接与网络质量', color: 'mint'},
  identity_access: {name: '账号权限', english: 'Identity Agent', desc: 'SSO、认证与资源访问权限', color: 'blue'},
  software: {name: '软件应用', english: 'Software Agent', desc: '安装、升级与运行时故障', color: 'purple'},
  device: {name: '终端设备', english: 'Device Agent', desc: '电脑、打印机与办公外设', color: 'orange'},
  security: {name: '安全响应', english: 'Security Agent', desc: '钓鱼、入侵与数据泄露', color: 'rose'},
  triage: {name: '故障分诊', english: 'Triage Agent', desc: '补充信息与故障分流', color: 'mint'},
};
export const agentName = value => agents[value]?.name || value || '待识别';
export const badge = (text, tone = '') => `<span class="badge ${tone}">${esc(text)}</span>`;

export async function api(path, options = {}, timeout = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {cache: 'no-store', ...options, signal: controller.signal,
      headers: {...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请稍后重试。后台任务可能仍在运行。');
    if (error instanceof TypeError) throw new Error('无法连接服务，请检查 Docker 服务是否已启动。');
    throw error;
  } finally { clearTimeout(timer); }
}

export function markdown(text) {
  let inCode = false, inList = false;
  const output = [];
  const inline = line => esc(line).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  for (const line of String(text || '').split('\n')) {
    if (line.trim().startsWith('```')) {
      if (inList) { output.push('</ul>'); inList = false; }
      output.push(inCode ? '</code></pre>' : '<pre><code>'); inCode = !inCode; continue;
    }
    if (inCode) { output.push(`${esc(line)}\n`); continue; }
    const list = line.match(/^\s*(?:[-*]|\d+[.)、])\s+(.*)/);
    if (list) { if (!inList) output.push('<ul>'); inList = true; output.push(`<li>${inline(list[1])}</li>`); continue; }
    if (inList) { output.push('</ul>'); inList = false; }
    if (!line.trim()) continue;
    const heading = line.match(/^#{1,6}\s+(.*)/);
    if (heading) output.push(`<h3>${inline(heading[1])}</h3>`);
    else if (line.startsWith('> ')) output.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
    else if (/^[-*_]{3,}$/.test(line.trim())) output.push('<hr>');
    else output.push(`<p>${inline(line)}</p>`);
  }
  if (inCode) output.push('</code></pre>');
  if (inList) output.push('</ul>');
  return output.join('');
}

export function toast(message, error = false) {
  const el = document.createElement('div');
  el.className = `toast ${error ? 'error' : ''}`;
  el.innerHTML = `${icon(error ? 'info' : 'check')}<span>${esc(message)}</span>`;
  document.querySelector('#toasts').append(el);
  setTimeout(() => el.remove(), 5000);
}

export function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
