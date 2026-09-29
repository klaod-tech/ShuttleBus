'use strict';

// ---------------------------------------------------------------- state
const $ = (id) => document.getElementById(id);
const STATUS = {
  blocked: '결정·확인 필요',
  planned: '할 일',
  in_progress: '진행 중',
  review: '검수 대기',
  completed: '완료',
};
const PAGES = {
  overview: ['한눈에 보기', '지금 무엇이 진행 중이고, 다음에 무엇을 할 수 있는지.'],
  documents: ['프로젝트 여정', '어디까지 왔는지, 무엇이 남았는지. 단계별 작업과 근거 문서를 함께 봅니다.'],
  board: ['진행 보드', '해야 할 일부터 완료된 기록까지, 근거와 함께.'],
};

let config = {
  projectName: '프로젝트',
  tagline: '',
  taskPrefix: 'T',
  categories: [],
  quickDocs: [],
  rulesFile: 'AGENTS.md',
  boardDir: 'tools/board',
};
let stages = [];
let docs = [];
let workspace = { cards: [], nextNumber: 1 };
let version = '';
let current = 'overview';
let selectedDoc = '';
let selectedStage = '';
let stageScope = true;
let rawMode = false;
let loading = false;
let editing = null;
let pendingTask = '';
let searchHits = null; // {query, paths:Set}
let searchTimer = 0;
const docCache = new Map(); // path -> {modified, body}

// ---------------------------------------------------------------- helpers
const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const docURL = (path) => '#doc=' + encodeURIComponent(path);
const badge = (status) => `<span class="badge ${esc(status)}">${esc(STATUS[status] || status)}</span>`;
const stars = (n) => '★'.repeat(n || 0) || '☆';
const dateText = (seconds) => new Date(seconds * 1000).toLocaleDateString('ko-KR');

function notice(message) {
  $('notice').textContent = message;
  $('notice').hidden = !message;
}

async function api(path, options) {
  const response = await fetch(path, options);
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) throw new Error(body.error || '요청에 실패했습니다.');
  return body;
}

// ---------------------------------------------------------------- derived data
const cards = () => workspace.cards;
const findCard = (number) => cards().find((c) => c.number === number);
const isOngoing = (stageId) => Boolean(stages.find((s) => s.id === stageId)?.ongoing);

function waitingFor(card) {
  return (card.dependsOn || []).filter((n) => findCard(n)?.status !== 'completed');
}

function stageCards(id) {
  return cards().filter((c) => c.stage === id);
}

function stageStats(id) {
  const tasks = stageCards(id);
  return {
    tasks,
    done: tasks.filter((c) => c.status === 'completed').length,
    active: tasks.filter((c) => ['in_progress', 'review'].includes(c.status)).length,
  };
}

function productCards() {
  return cards().filter((c) => c.stage && !isOngoing(c.stage));
}

function currentStage() {
  const product = stages.filter((s) => !s.ongoing);
  const unfinished = product.find((s) => {
    const { tasks, done } = stageStats(s.id);
    return done < tasks.length;
  });
  if (unfinished) return unfinished;
  if (!productCards().length) return product[0] || stages[0];
  return null; // every registered product card is done
}

function orderedTasks(tasks) {
  const result = [];
  const seen = new Set();
  const byNumber = new Map(tasks.filter((t) => t.number).map((t) => [t.number, t]));
  const visit = (task) => {
    if (seen.has(task.id)) return;
    seen.add(task.id);
    for (const n of task.dependsOn || []) if (byNumber.has(n)) visit(byNumber.get(n));
    result.push(task);
  };
  tasks
    .slice()
    .sort((a, b) => (a.order ?? 99999) - (b.order ?? 99999) || (b.priority || 0) - (a.priority || 0))
    .forEach(visit);
  return result;
}

function readyCards() {
  const rows = cards().filter((c) => ['planned', 'in_progress', 'review'].includes(c.status) && !waitingFor(c).length);
  return orderedTasks(rows).sort((a, b) => (a.status === 'planned') - (b.status === 'planned'));
}

function pendingPlans() {
  const sources = new Set(cards().map((c) => c.source));
  const numbers = new Set(cards().map((c) => c.number));
  return docs.filter((d) => d.status && !sources.has(d.path) && !(d.task && numbers.has(d.task)));
}

function boardItems() {
  const plans = pendingPlans().map((d) => ({
    kind: 'pending-plan',
    id: d.path,
    number: '',
    title: d.title,
    status: d.status,
    source: d.path,
    category: d.declared?.[0] || '',
    stage: '',
    body: '계획 문서에 상태가 적혀 있지만 아직 작업 카드로 등록되지 않았습니다. 눌러서 등록하세요.',
    priority: 0,
    size: 1,
    order: 99999,
    dependsOn: [],
  }));
  return [...cards().map((c) => ({ ...c, kind: 'card' })), ...plans];
}

function stageDocuments(id) {
  const phase = stages.find((s) => s.id === id);
  const tasks = stageCards(id);
  return docs.filter((d) => phase?.docs.includes(d.path) || tasks.some((c) => c.source === d.path || (d.task && c.number === d.task)));
}

// ---------------------------------------------------------------- loading
async function loadConfig() {
  config = await api('/api/config');
  document.title = config.projectName + ' · 관리판';
  $('brand-name').textContent = config.projectName;
  $('brand-icon').firstChild.textContent = Array.from(config.projectName.trim())[0]?.toUpperCase() || 'P';
  $('hero-title').textContent = config.projectName;
  $('item-dependencies').placeholder = `${config.taskPrefix}-0001, ${config.taskPrefix}-0002`;
  const categoryOptions = config.categories.map((c) => `<option>${esc(c)}</option>`).join('');
  $('item-category').innerHTML = categoryOptions;
  $('board-category').insertAdjacentHTML('beforeend', categoryOptions);
  $('doc-group').insertAdjacentHTML('beforeend', categoryOptions + '<option>미분류</option>');
  $('item-status').innerHTML = Object.entries(STATUS)
    .map(([v, t]) => `<option value="${v}">${t}</option>`)
    .join('');
}

async function refresh(silent = false) {
  if (loading || $('editor').open) return;
  loading = true;
  try {
    const [documentList, data, journey] = await Promise.all([api('/api/documents'), api('/api/workspace'), api('/api/stages')]);
    docs = documentList.documents;
    workspace = data.data;
    version = data.version;
    if (!stages.length) {
      const options = journey.stages.map((s) => `<option value="${esc(s.id)}">${esc(s.title)}</option>`).join('');
      $('item-stage').innerHTML = '<option value="">단계를 선택하세요</option>' + options;
      $('board-stage').insertAdjacentHTML('beforeend', options);
    }
    stages = journey.stages;
    for (const doc of docs) {
      const cached = docCache.get(doc.path);
      if (cached && cached.modified !== doc.modified) docCache.delete(doc.path);
    }
    $('doc-count').textContent = docs.length;
    $('card-count').textContent = cards().length;
    $('sync-time').textContent = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) + ' 갱신';
    render();
    if (!silent) notice('');
  } catch (error) {
    notice(error.message + ' · 관리판이 꺼졌다면 start-board를 다시 실행하세요.');
  } finally {
    loading = false;
  }
}

// ---------------------------------------------------------------- routing
function route() {
  const hash = location.hash.slice(1);
  if (hash.startsWith('doc=')) {
    try {
      selectedDoc = decodeURIComponent(hash.slice(4));
    } catch {
      selectedDoc = '';
    }
    current = 'documents';
    rawMode = false;
    if (!stageDocuments(selectedStage).some((d) => d.path === selectedDoc)) stageScope = false;
  } else if (hash.startsWith('task=')) {
    pendingTask = decodeURIComponent(hash.slice(5));
    current = 'board';
  } else {
    current = PAGES[hash] ? hash : 'overview';
  }
  render();
}

function render() {
  for (const el of document.querySelectorAll('.view')) el.hidden = el.id !== current;
  for (const el of document.querySelectorAll('[data-nav]')) el.classList.toggle('active', el.dataset.nav === current);
  $('page-title').textContent = PAGES[current][0];
  $('page-description').textContent = PAGES[current][1];
  $('eyebrow').textContent = config.projectName.toUpperCase() + ' / PROJECT JOURNAL';
  if (current === 'overview') renderOverview();
  if (current === 'documents') {
    renderJourney();
    renderDocList();
    renderDocument();
  }
  if (current === 'board') renderBoard();
  syncSelects();
  if (pendingTask && version) {
    const task = findCard(pendingTask);
    pendingTask = '';
    if (task) openEditor('card', task.id);
    else notice('작업 번호를 찾을 수 없습니다. 새로고침 후 다시 확인하세요.');
  }
}

// ---------------------------------------------------------------- overview
function cardRow(card, extra = '') {
  return `<a class="plan-card" href="#task=${esc(card.number)}"><div class="card-top">${badge(card.status)}<span class="task-stars">${stars(card.priority)}</span></div><h3>${esc(card.number + ' ' + card.title)}</h3><div class="card-meta"><span>${esc(card.category || '')}${card.ref ? ' · ' + esc(card.ref) : ''}</span><span>${extra || '작업·근거 확인 ↗'}</span></div></a>`;
}

function renderOverview() {
  const stage = currentStage();
  $('hero-tagline').textContent = config.tagline || '문서와 작업 카드를 한곳에서. 다음 단계는 더 분명하게.';
  $('hero-stage').textContent = stage ? stage.title : '등록된 제품 작업 완료';
  $('hero-goal').textContent = stage ? stage.goal : '새 단계나 작업을 추가하세요.';

  const all = cards();
  const active = all.filter((c) => ['in_progress', 'review'].includes(c.status));
  const blocked = all.filter((c) => c.status === 'blocked');
  const done = all.filter((c) => c.status === 'completed').length;
  const metrics = [
    ['프로젝트 문서', docs.length, '개'],
    ['진행·검수 작업', active.length, '개'],
    ['결정·확인 필요', blocked.length, '개'],
    ['완료한 작업', done, `/ ${all.length}`],
  ];
  $('metrics').innerHTML = metrics
    .map(([label, n, unit]) => `<div class="metric"><p>${label}</p><strong>${n}</strong><small>${unit}</small></div>`)
    .join('');

  $('active-cards').innerHTML =
    [...orderedTasks(active), ...orderedTasks(blocked)].map((c) => cardRow(c)).join('') ||
    `<div class="empty">진행 중인 작업이 없습니다.<br>${all.length ? '아래 "바로 할 수 있는 작업"에서 시작하세요.' : '상단의 <b>＋ 작업 추가</b> 또는 AI에게 <code>work.py add</code>로 첫 작업을 등록하세요.'}</div>`;

  const ready = readyCards()
    .filter((c) => c.status === 'planned')
    .slice(0, 5);
  $('ready-cards').innerHTML =
    ready.map((c) => cardRow(c, '착수 가능 →')).join('') ||
    `<div class="empty">${all.length ? '선행 작업이 끝나기를 기다리는 작업만 남았습니다.' : '등록된 작업이 없습니다.'}</div>`;

  const configured = (config.quickDocs || []).filter((q) => docs.some((d) => d.path === q.path));
  const quick = configured.length
    ? configured.map((q) => ({ path: q.path, title: q.title || docs.find((d) => d.path === q.path).title, note: q.note || q.path }))
    : docs
        .slice()
        .sort((a, b) => b.modified - a.modified)
        .slice(0, 5)
        .map((d) => ({ path: d.path, title: d.title, note: d.path + ' · ' + dateText(d.modified) }));
  $('quick-title').textContent = configured.length ? '자주 찾는 문서' : '최근 수정한 문서';
  $('quick-note').textContent = configured.length ? 'START HERE' : 'config.json quickDocs로 고정 가능';
  $('quick-docs').innerHTML =
    quick
      .map(
        (q, i) =>
          `<a href="${docURL(q.path)}"><span class="number">0${i + 1}</span><span><strong>${esc(q.title)}</strong><small>${esc(q.note)}</small></span><span class="arrow">↗</span></a>`,
      )
      .join('') || '<div class="empty">아직 Markdown 문서가 없습니다.</div>';

  const groups = [...config.categories, '미분류'];
  $('shelves').innerHTML = groups
    .map(
      (g) =>
        `<button class="shelf" type="button" data-group="${esc(g)}"><strong>${esc(g)}</strong><span>${docs.filter((d) => d.groups.includes(g)).length}개 ↗</span></button>`,
    )
    .join('');
  $('shelves')
    .querySelectorAll('button')
    .forEach((b) => {
      b.onclick = () => {
        stageScope = false;
        $('doc-group').value = b.dataset.group;
        $('doc-search').value = '';
        searchHits = null;
        location.hash = 'documents';
      };
    });
}

// ---------------------------------------------------------------- journey
function renderJourney() {
  if (!stages.length) return;
  if (!selectedStage) selectedStage = (currentStage() || stages[0]).id;
  const product = productCards();
  const productDone = product.filter((c) => c.status === 'completed').length;
  const focus = currentStage();
  $('journey-summary').innerHTML =
    `<div><p class="eyebrow">OUR PROJECT, STEP BY STEP</p><h2>${focus ? '지금 단계, ' + esc(focus.title) : '등록된 제품 작업을 마쳤습니다'}</h2><p>단계는 병행할 수 있고, 완료 여부는 연결된 카드의 근거를 따릅니다.<br>문서 수·체크박스·커밋 수로 완료를 추정하지 않습니다.</p></div><div class="journey-count"><strong>${productDone}<span> / ${product.length}</span></strong><span>제품 작업 완료 · 상시 운영 제외</span><progress max="${product.length || 1}" value="${productDone}" aria-label="제품 작업 ${productDone}/${product.length} 완료"></progress></div>`;

  let productIndex = 0;
  $('stage-steps').innerHTML = stages
    .map((s) => {
      const { tasks, done, active } = stageStats(s.id);
      const complete = tasks.length > 0 && done === tasks.length;
      const label = s.ongoing ? '↻' : String(++productIndex).padStart(2, '0');
      const state = complete ? '등록 작업 완료' : active ? '진행 중' : done ? '일부 완료' : tasks.length ? '준비 중' : '작업 없음';
      return `<button type="button" class="stage-step ${s.id === selectedStage ? 'selected' : ''} ${complete ? 'complete' : ''}" data-stage="${esc(s.id)}" aria-pressed="${s.id === selectedStage}"><span class="step-number">${label}</span><strong>${esc(s.title)}</strong><small>${state} · ${done}/${tasks.length}</small><progress max="${tasks.length || 1}" value="${done}" aria-label="${esc(s.title)} ${done}/${tasks.length} 완료"></progress></button>`;
    })
    .join('');
  $('stage-steps')
    .querySelectorAll('button')
    .forEach((b) => {
      b.onclick = () => {
        selectedStage = b.dataset.stage;
        stageScope = true;
        selectedDoc = '';
        $('doc-search').value = '';
        $('doc-group').value = '';
        searchHits = null;
        renderJourney();
        renderDocList();
        renderDocument();
        syncSelects();
      };
    });

  const phase = stages.find((s) => s.id === selectedStage) || stages[0];
  const { tasks, done, active } = stageStats(phase.id);
  const waiting = tasks.filter((c) => c.status !== 'completed' && waitingFor(c).length);
  const ready = orderedTasks(tasks.filter((c) => ['planned', 'in_progress', 'review'].includes(c.status) && !waitingFor(c).length));
  const position = stages.filter((s) => !s.ongoing).indexOf(phase) + 1;
  const next = ready.length
    ? `다음 실행 후보 <a href="#task=${esc(ready[0].number)}">${esc(ready[0].number + ' ' + ready[0].title)} →</a>`
    : waiting.length
      ? '선행 대기 카드의 선행 작업을 먼저 확인하세요.'
      : tasks.length
        ? '등록 작업이 완료되었습니다. 아래 근거 문서를 확인하세요.'
        : '이 단계에 등록된 작업이 없습니다. 작업을 추가할 때 이 단계를 고르세요.';
  const rows =
    orderedTasks(tasks)
      .map((t) => {
        const w = waitingFor(t);
        const sub =
          t.status === 'completed'
            ? '수행: ' + (t.performedBy || '근거 참조')
            : w.length
              ? '선행 대기 ' + w.join(' · ')
              : t.ref || '착수 가능';
        return `<a class="journey-task" href="#task=${esc(t.number)}"><span class="journey-task-main"><small>${esc(t.number)} · ${esc(t.category)} <span class="task-stars">${'★'.repeat(t.priority || 0)}</span></small><strong>${esc(t.title)}</strong><small>${esc(sub)}</small></span>${badge(t.status)}</a>`;
      })
      .join('') || '<p class="empty">아직 등록된 작업이 없습니다.</p>';
  $('stage-detail').innerHTML =
    `<div class="stage-intro"><span class="eyebrow">${phase.ongoing ? 'ALWAYS ON' : 'STEP ' + String(position).padStart(2, '0')}</span><h2>${esc(phase.title)}</h2><p>${esc(phase.goal)}</p><div class="stage-gate"><strong>단계 완료 기준</strong><p>${esc(phase.exit || '아직 정하지 않았습니다 (stages.json exit).')}</p></div><div class="stage-totals"><span><b>${done}</b> 완료</span><span><b>${active}</b> 진행·검수</span><span><b>${waiting.length}</b> 선행 대기</span></div><p class="next-step">${next}</p></div><div class="stage-work"><div class="section-heading"><h3>이 단계의 작업</h3><span>${tasks.length}개</span></div>${rows}</div>`;
  $('library-scope').textContent = stageScope ? phase.title + ' · 연결된 근거 문서' : '전체 프로젝트 문서';
  $('all-documents').textContent = stageScope ? '전체 문서 탐색' : '단계 문서로 돌아가기';
}

// ---------------------------------------------------------------- documents
function scheduleSearch() {
  const q = $('doc-search').value.trim();
  clearTimeout(searchTimer);
  if (q.length < 2) {
    searchHits = null;
    renderDocList();
    return;
  }
  searchTimer = setTimeout(async () => {
    try {
      const result = await api('/api/search?q=' + encodeURIComponent(q));
      if ($('doc-search').value.trim() === q) {
        searchHits = { query: q, paths: new Set(result.paths) };
        renderDocList();
      }
    } catch (error) {
      notice(error.message);
    }
  }, 250);
}

function renderDocList() {
  const q = $('doc-search').value.trim().toLowerCase();
  const group = $('doc-group').value;
  const source = stageScope ? stageDocuments(selectedStage) : docs;
  const bodyHits = searchHits && searchHits.query.toLowerCase() === q ? searchHits.paths : null;
  const filtered = source.filter(
    (d) => (!group || d.groups.includes(group)) && (!q || `${d.title} ${d.path}`.toLowerCase().includes(q) || bodyHits?.has(d.path)),
  );
  $('search-count').textContent =
    `${filtered.length}개 문서${q.length >= 2 && !bodyHits ? ' · 본문 검색 중…' : q ? ' · 제목·경로·본문' : ''}`;
  $('doc-list').innerHTML =
    filtered
      .map(
        (d) =>
          `<button type="button" class="doc-link ${d.path === selectedDoc ? 'selected' : ''}" data-path="${esc(d.path)}"><strong>${esc(d.title)}</strong><small>${esc(d.path)}${d.task ? ' · ' + esc(d.task) : ''}</small></button>`,
      )
      .join('') ||
    `<p class="empty">${stageScope && !q && !group ? '이 단계에 연결된 문서가 없습니다.<br>전체 문서 탐색을 눌러 보세요.' : '일치하는 문서가 없습니다.'}</p>`;
  $('doc-list')
    .querySelectorAll('button')
    .forEach((b) => {
      b.onclick = () => {
        location.hash = docURL(b.dataset.path);
      };
    });
}

function linkTo(href, path) {
  if (href.startsWith('#')) return href;
  try {
    const base = new URL(path, 'http://documents.local/');
    const url = new URL(href, base);
    if (['http:', 'https:'].includes(url.protocol) && url.hostname !== 'documents.local') return url.href;
    if (url.origin === base.origin) {
      const target = decodeURIComponent(url.pathname.slice(1));
      if (docs.some((d) => d.path === target)) return docURL(target);
      if (docs.some((d) => d.path.startsWith(target.replace(/\/$/, '') + '/'))) return '#folder=' + encodeURIComponent(target);
    }
  } catch {
    /* not a usable link */
  }
  return '';
}

function inline(text, path) {
  const tokens = [];
  const token = (html) => {
    tokens.push(html);
    return '\u0000' + (tokens.length - 1) + '\u0000';
  };
  let value = String(text).replace(/\u0000/g, '');
  value = value.replace(/`([^`]+)`/g, (_, v) => token('<code>' + esc(v) + '</code>'));
  value = value.replace(/!?\[([^\]]+)\]\(([^\s)]+)(?:\s+"[^"]*")?\)/g, (_, label, href) => {
    const url = linkTo(href, path);
    return token(
      url
        ? `<a href="${esc(url)}"${url.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : ''}>${esc(label)}</a>`
        : `<span title="${esc(href)}">${esc(label)} <small>(파일: ${esc(href)})</small></span>`,
    );
  });
  value = esc(value)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>');
  return value.replace(/\u0000(\d+)\u0000/g, (_, i) => tokens[Number(i)]);
}

function markdown(body, path) {
  const lines = body.replace(/\r/g, '').split('\n');
  const out = [];
  const headings = [];
  const cells = (line) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim());
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = line.match(/^\s*(`{3,}|~{3,})\s*([\w-]*)/);
    if (fence) {
      const block = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) block.push(lines[i++]);
      i++;
      const label = fence[2] ? `<span class="code-label">${esc(fence[2])}${fence[2] === 'mermaid' ? ' · 도표 원문' : ''}</span>` : '';
      out.push('<pre>' + label + '<code>' + esc(block.join('\n')) + '</code></pre>');
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const id = 'section-' + headings.length;
      headings.push({ id, title: heading[2], level });
      out.push(`<h${level} id="${id}">${inline(heading[2], path)}</h${level}>`);
      i++;
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
      const header = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|')) rows.push(cells(lines[i++]));
      out.push(
        '<div class="table-wrap"><table><thead><tr>' +
          header.map((c) => '<th>' + inline(c, path) + '</th>').join('') +
          '</tr></thead><tbody>' +
          rows.map((r) => '<tr>' + r.map((c) => '<td>' + inline(c, path) + '</td>').join('') + '</tr>').join('') +
          '</tbody></table></div>',
      );
      continue;
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      out.push('<hr>');
      i++;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(inline(lines[i++].replace(/^\s*>\s?/, ''), path));
      out.push('<blockquote>' + quote.join('<br>') + '</blockquote>');
      continue;
    }
    if (/^\s*(?:[-*+] |\d+\. )/.test(line)) {
      const ordered = /^\s*\d+\. /.test(line);
      const tag = ordered ? 'ol' : 'ul';
      const items = [];
      const pattern = ordered ? /^\s*\d+\. / : /^\s*[-*+] /;
      while (i < lines.length && pattern.test(lines[i])) {
        const content = lines[i++].replace(/^\s*(?:[-*+] |\d+\. )/, '');
        const check = content.match(/^\[([ xX])\]\s*/);
        items.push(
          '<li>' +
            (check ? `<input type="checkbox" disabled ${check[1].toLowerCase() === 'x' ? 'checked' : ''}>` : '') +
            inline(check ? content.slice(check[0].length) : content, path) +
            '</li>',
        );
      }
      out.push(`<${tag}>${items.join('')}</${tag}>`);
      continue;
    }
    const para = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*(?:#|```|~~~|>|[-*+] |\d+\. )/.test(lines[i]) &&
      !(lines[i].includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || ''))
    )
      para.push(lines[i++]);
    out.push('<p>' + para.map((l) => inline(l, path)).join('<br>') + '</p>');
  }
  const toc = headings.filter((h) => h.level === 2);
  return (
    (toc.length
      ? '<details class="toc"><summary>이 문서의 목차</summary>' +
        toc.map((h) => `<a href="#${h.id}" data-anchor="${h.id}">${inline(h.title, path)}</a>`).join('') +
        '</details>'
      : '') +
    '<article class="markdown">' +
    out.join('\n') +
    '</article>'
  );
}

async function renderDocument() {
  const doc = docs.find((d) => d.path === selectedDoc);
  if (!doc) {
    $('reader-meta').innerHTML = '';
    $('reader-content').innerHTML =
      `<div class="empty">${selectedDoc ? '문서를 찾을 수 없습니다. 경로를 확인하거나 왼쪽 목록에서 선택하세요.' : '왼쪽에서 문서를 선택하세요.'}</div>`;
    return;
  }
  let cached = docCache.get(doc.path);
  if (!cached) {
    $('reader-content').innerHTML = '<div class="empty">문서를 읽는 중…</div>';
    try {
      const full = await api('/api/document?path=' + encodeURIComponent(doc.path));
      cached = { modified: full.modified, body: full.body };
      docCache.set(doc.path, cached);
    } catch (error) {
      $('reader-content').innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      return;
    }
    if (selectedDoc !== doc.path) return; // user moved on while loading
  }
  const linked = cards().filter((c) => c.source === doc.path || (doc.task && c.number === doc.task));
  $('reader-meta').innerHTML =
    `<div class="reader-actions"><div>${doc.groups.map((g) => `<span class="badge">${esc(g)}</span>`).join(' ')}${linked
      .map((c) => ` <a class="badge link-badge" href="#task=${esc(c.number)}">${esc(c.number)} · ${esc(STATUS[c.status])}</a>`)
      .join(
        '',
      )}<p class="reader-path">${esc(doc.path)} · ${dateText(doc.modified)}</p></div><button type="button" id="toggle-raw">${rawMode ? '읽기 화면' : 'MD 원문'}</button></div>`;
  $('reader-content').innerHTML = rawMode ? '<pre class="raw">' + esc(cached.body) + '</pre>' : markdown(cached.body, doc.path);
  $('toggle-raw').onclick = () => {
    rawMode = !rawMode;
    renderDocument();
  };
  $('reader-content')
    .querySelectorAll('a')
    .forEach((a) => {
      a.onclick = (event) => {
        const href = a.getAttribute('href');
        if (href.startsWith('#folder=')) {
          event.preventDefault();
          stageScope = false;
          $('doc-search').value = decodeURIComponent(href.slice(8));
          $('doc-group').value = '';
          searchHits = null;
          renderJourney();
          renderDocList();
        } else if (href.startsWith('#') && !href.startsWith('#doc=') && !href.startsWith('#task=')) {
          event.preventDefault();
          const anchor = a.dataset.anchor || href.slice(1);
          let target = document.getElementById(anchor);
          if (!target) {
            const slug = (s) =>
              s
                .toLowerCase()
                .replace(/[^\p{L}\p{N}\s-]/gu, '')
                .replace(/\s/g, '-');
            let wanted = anchor;
            try {
              wanted = decodeURIComponent(anchor);
            } catch {
              /* keep raw */
            }
            target = Array.from($('reader-content').querySelectorAll('h1,h2,h3,h4')).find((h) => slug(h.textContent) === wanted);
          }
          target?.scrollIntoView({ behavior: 'smooth' });
        }
      };
    });
}

// ---------------------------------------------------------------- board
function renderBoard() {
  const q = $('board-search').value.toLowerCase();
  const kind = $('board-kind').value;
  const category = $('board-category').value;
  const stage = $('board-stage').value;
  const priority = $('board-priority').value;
  const items = orderedTasks(boardItems()).filter(
    (t) =>
      (!kind || t.kind === kind) &&
      (!category || t.category === category) &&
      (!stage || t.stage === stage) &&
      (priority === '' || String(t.priority || 0) === priority) &&
      `${t.number} ${t.title} ${t.body} ${t.ref || ''} ${t.performedBy || ''}`.toLowerCase().includes(q),
  );
  $('kanban').innerHTML = Object.entries(STATUS)
    .map(([state, label]) => {
      const column = items.filter((t) => t.status === state);
      const html = column
        .map((t) => {
          const waiting = t.kind === 'card' ? waitingFor(t) : [];
          const last = t.log?.at(-1);
          const who = t.status === 'completed' && t.performedBy ? '수행: ' + t.performedBy : '';
          return `<button type="button" class="task-card priority-${t.priority || 0} ${t.kind === 'pending-plan' ? 'pending-plan' : ''}" data-kind="${t.kind}" data-id="${esc(t.id)}"><div class="card-top"><span class="task-number">${esc(t.number || '등록 필요')}</span><span class="task-stars" title="${esc(t.priorityNote || '중요도 미분류')}">${stars(t.priority)}</span></div><small>${esc(t.category || '계획 문서')} · 규모 ${'●'.repeat(t.size || 1)}${t.kind === 'card' ? ' · 배치 ' + (t.order ?? '—') : ''}</small><h3>${esc(t.title)}</h3>${t.ref ? `<p class="ref">${esc(t.ref)}</p>` : ''}${who ? `<p>${esc(who)}</p>` : ''}${waiting.length ? `<p class="dependency">선행 대기 ${esc(waiting.join(', '))}</p>` : ''}<p>${esc(t.body.slice(0, 100))}</p>${last ? `<small>${esc(last.by)} · ${esc(last.text.slice(0, 80))}</small>` : ''}</button>`;
        })
        .join('');
      return `<section class="column"><h2>${label}<span>${column.length}</span></h2>${html || '<p class="empty">작업 없음</p>'}</section>`;
    })
    .join('');
  $('kanban')
    .querySelectorAll('button')
    .forEach((b) => {
      b.onclick = () => openEditor(b.dataset.kind, b.dataset.id);
    });
}

// ---------------------------------------------------------------- editor
function setField(id, value) {
  $(id).value = value ?? '';
}

function openEditor(kind, id = '') {
  if (!version) {
    notice('자료를 불러온 뒤 다시 시도하세요.');
    return;
  }
  let item = null;
  if (kind === 'card' && id) item = cards().find((c) => c.id === id);
  if (kind === 'pending-plan') {
    const doc = docs.find((d) => d.path === id);
    item = {
      title: doc.title,
      source: doc.path,
      status: doc.status,
      category: config.categories.includes(doc.declared?.[0]) ? doc.declared[0] : '',
      plan: true,
    };
  }
  editing = { id: kind === 'card' ? id : '', item: kind === 'card' ? item : null, prefill: kind === 'pending-plan' ? item : null, version };
  const existing = editing.item;
  $('editor-heading').textContent = existing?.number
    ? existing.number + ' · 작업 카드'
    : kind === 'pending-plan'
      ? '계획 문서를 작업 카드로 등록'
      : '새 작업 · 저장하면 번호 발급';
  setField('item-title', item?.title);
  setField('item-stage', item?.stage || '');
  setField('item-category', item?.category || config.categories[0]);
  setField('item-status', item?.status || 'planned');
  setField('item-ref', item?.ref);
  setField('item-priority', String(item?.priority || 0));
  setField('item-size', String(item?.size || 1));
  setField('item-priority-note', item?.priorityNote);
  setField('item-order', existing ? String(existing.order ?? 0) : '');
  setField('item-dependencies', (item?.dependsOn || []).join(', '));
  setField('item-body', item?.body);
  setField('item-performer', item?.performedBy);
  setField('item-evidence', item?.evidence);
  setField('item-feedback', '');
  $('item-source').innerHTML =
    '<option value="">연결하지 않음</option>' +
    docs.map((d) => `<option value="${esc(d.path)}">${esc(d.title)} · ${esc(d.path)}</option>`).join('');
  setField('item-source', item?.source || '');
  $('source-link').hidden = !item?.source;
  $('source-link').href = docURL(item?.source || '');
  $('source-link').onclick = () => $('editor').close();
  $('card-tools').hidden = !existing?.number;
  $('feedback-label').hidden = !existing;
  $('delete-item').hidden = !existing;
  $('ai-result').hidden = !existing?.result;
  $('ai-result').textContent = existing?.result ? `${existing.agent || 'AI'} 최근 처리 기록\n${existing.result}` : '';
  $('card-history').innerHTML = (existing?.log || [])
    .slice()
    .reverse()
    .map(
      (e) =>
        `<div class="history-entry"><strong>${esc(e.by)} <small>${e.kind === 'ai' ? 'AI' : '사용자'} · ${esc(new Date(e.at).toLocaleString('ko-KR'))}</small></strong><p>${esc(e.text)}</p></div>`,
    )
    .join('');
  $('editor-error').textContent = '';
  $('save-item').disabled = false;
  syncSelects();
  $('editor').showModal();
}

async function persist(next, expectedVersion, message = '') {
  const result = await api('/api/workspace', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: next, version: expectedVersion, message }),
  });
  workspace = result.data;
  version = result.version;
  $('card-count').textContent = cards().length;
  render();
}

function editorError(message) {
  $('editor-error').textContent = message;
  $('save-item').disabled = false;
}

$('editor-form').onsubmit = async (event) => {
  event.preventDefault();
  if (!editing) return;
  $('save-item').disabled = true;
  const previous = editing.item;
  const orderText = $('item-order').value.trim();
  const item = {
    ...(previous || {}),
    ...(editing.prefill ? { plan: true } : {}),
    id: editing.id || crypto.randomUUID(),
    title: $('item-title').value.trim(),
    stage: $('item-stage').value,
    category: $('item-category').value,
    status: $('item-status').value,
    ref: $('item-ref').value.trim(),
    priority: Number($('item-priority').value),
    size: Number($('item-size').value),
    priorityNote: $('item-priority-note').value,
    dependsOn: $('item-dependencies')
      .value.split(/[,\s]+/)
      .filter(Boolean)
      .map((n) => n.toUpperCase()),
    body: $('item-body').value,
    source: $('item-source').value,
    performedBy: $('item-performer').value.trim(),
    evidence: $('item-evidence').value,
    result: previous?.result || '',
    agent: previous?.agent || '',
    updated: new Date().toISOString(),
    log: previous?.log || [],
  };
  if (orderText !== '') item.order = Math.max(0, Math.floor(Number(orderText) || 0));
  else if (previous) item.order = previous.order;
  else delete item.order; // the server gives new cards number×10
  if (!item.title) return editorError('제목을 입력하세요.');
  if (!item.stage) return editorError('프로젝트 단계를 선택하세요.');
  if (item.status === 'completed' && previous?.status !== 'completed' && !item.evidence.trim())
    return editorError('완료로 옮기려면 완료 근거(무엇을 했고 어떻게 확인했는지)를 적으세요.');
  const next = structuredClone(workspace);
  const index = next.cards.findIndex((c) => c.id === item.id);
  if (index < 0) next.cards.push(item);
  else next.cards[index] = item;
  try {
    await persist(next, editing.version, previous ? $('item-feedback').value.trim() : '');
    $('editor').close();
    notice('저장했습니다.');
  } catch (error) {
    editorError(error.message);
  }
};

$('delete-item').onclick = async () => {
  if (!editing?.item || !confirm(`${editing.item.number} 카드를 삭제할까요? 번호는 다시 쓰지 않습니다. Git 기록으로만 되돌릴 수 있습니다.`))
    return;
  const next = structuredClone(workspace);
  next.cards = next.cards.filter((c) => c.id !== editing.id);
  try {
    await persist(next, editing.version);
    $('editor').close();
    notice('삭제했습니다.');
  } catch (error) {
    editorError(error.message);
  }
};

function closeEditor() {
  if (confirm('편집 창을 닫을까요? 저장하지 않은 입력은 사라집니다.')) $('editor').close();
}

$('close-editor').onclick = closeEditor;
$('editor').addEventListener('cancel', (event) => {
  event.preventDefault();
  closeEditor();
});

$('copy-task').onclick = async () => {
  const n = editing?.item?.number;
  if (!n) return;
  const text = `${n} 작업을 진행해줘. 먼저 ${config.rulesFile}를 읽고 python ${config.boardDir}/work.py show ${n}으로 요구사항·선행 작업·근거 문서를 확인해줘. 착수·진행·완료는 work.py move/log로 같은 카드에 기록하고, 완료는 실제로 한 일과 검증 결과를 근거로 남겨줘. 끝내지 못한 범위는 새 카드로 분리해줘.`;
  try {
    await navigator.clipboard.writeText(text);
    $('editor-error').textContent = 'AI에게 보낼 지시문을 복사했습니다.';
  } catch {
    $('editor-error').textContent = text;
  }
};

$('copy-task-link').onclick = async () => {
  const link = location.origin + '/#task=' + (editing?.item?.number || '');
  try {
    await navigator.clipboard.writeText(link);
    $('editor-error').textContent = '작업 링크를 복사했습니다.';
  } catch {
    $('editor-error').textContent = link;
  }
};

// ---------------------------------------------------------------- page controls
$('add-item').onclick = () => openEditor('card');
$('refresh').onclick = () => refresh();
$('all-documents').onclick = () => {
  stageScope = !stageScope;
  $('doc-search').value = '';
  $('doc-group').value = '';
  searchHits = null;
  renderJourney();
  renderDocList();
  syncSelects();
};
$('doc-search').addEventListener('input', () => {
  renderDocList();
  scheduleSearch();
});
$('doc-group').addEventListener('input', renderDocList);
for (const id of ['board-search', 'board-kind', 'board-category', 'board-stage', 'board-priority'])
  $(id).addEventListener('input', renderBoard);
$('stop-server').onclick = async () => {
  if (!confirm('관리판 서버를 종료할까요? 다시 열려면 start-board를 실행하세요.')) return;
  try {
    await api('/api/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    notice('관리판을 종료했습니다. 이 탭을 닫아도 됩니다.');
    $('sync-time').textContent = '종료됨';
  } catch (error) {
    notice(error.message);
  }
};

// ---------------------------------------------------------------- accessible select menus
// Native <select> elements stay the single source of form state; these are only the visible menus.
const customSelects = new Map();
let activeSelect = null;

function closeSelect(restoreFocus = false) {
  if (!activeSelect) return;
  const { button, menu } = activeSelect;
  menu.hidePopover();
  button.setAttribute('aria-expanded', 'false');
  activeSelect = null;
  if (restoreFocus) button.focus();
}

function syncSelects() {
  document.querySelectorAll('select').forEach((select) => {
    let control = customSelects.get(select);
    if (!control) {
      const wrapper = document.createElement('div');
      wrapper.className = 'custom-select';
      const label = select.closest('label');
      const labelText = label
        ? Array.from(label.childNodes)
            .filter((n) => n.nodeType === 3)
            .map((n) => n.textContent.trim())
            .join(' ')
        : document.querySelector(`label[for="${select.id}"]`)?.textContent || '선택';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'select-trigger';
      button.setAttribute('role', 'combobox');
      button.setAttribute('aria-label', labelText);
      button.setAttribute('aria-haspopup', 'listbox');
      button.setAttribute('aria-expanded', 'false');
      const menu = document.createElement('div');
      menu.className = 'select-menu';
      menu.id = select.id + '-options';
      menu.setAttribute('role', 'listbox');
      menu.setAttribute('aria-label', labelText);
      menu.setAttribute('popover', 'manual');
      button.setAttribute('aria-controls', menu.id);
      select.after(wrapper);
      wrapper.append(button, menu);
      select.hidden = true;
      control = { select, button, menu, wrapper };
      customSelects.set(select, control);

      const open = () => {
        if (select.disabled) return;
        if (activeSelect === control) {
          closeSelect(true);
          return;
        }
        closeSelect();
        menu.innerHTML = Array.from(select.options)
          .map(
            (o, i) =>
              `<button type="button" role="option" tabindex="-1" aria-selected="${o.selected}" data-index="${i}" ${o.disabled ? 'disabled' : ''}><span>${esc(o.textContent)}</span><span class="select-tick" aria-hidden="true">${o.selected ? '✓' : ''}</span></button>`,
          )
          .join('');
        menu.querySelectorAll('button').forEach((option) => {
          option.onclick = (event) => {
            event.preventDefault();
            select.selectedIndex = Number(option.dataset.index);
            select.dispatchEvent(new Event('input', { bubbles: true }));
            select.dispatchEvent(new Event('change', { bubbles: true }));
            closeSelect(true);
            syncSelects();
          };
        });
        activeSelect = control;
        button.setAttribute('aria-expanded', 'true');
        menu.showPopover();
        const rect = button.getBoundingClientRect();
        const roomBelow = innerHeight - rect.bottom - 16;
        const roomAbove = rect.top - 16;
        const height = Math.min(300, Math.max(roomBelow, roomAbove));
        menu.style.width = Math.min(Math.max(rect.width, 180), innerWidth - 24) + 'px';
        menu.style.maxHeight = height + 'px';
        menu.style.left = Math.max(12, Math.min(rect.left, innerWidth - Math.max(rect.width, 180) - 12)) + 'px';
        menu.style.top =
          (roomBelow >= Math.min(260, menu.scrollHeight)
            ? rect.bottom + 7
            : Math.max(12, rect.top - Math.min(height, menu.scrollHeight) - 7)) + 'px';
        const selectedOption = menu.querySelector('[aria-selected="true"]') || menu.querySelector('button');
        selectedOption?.focus({ preventScroll: true });
        selectedOption?.scrollIntoView({ block: 'nearest' });
      };
      button.onclick = (event) => {
        event.preventDefault();
        open();
      };
      button.onkeydown = (event) => {
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
          event.preventDefault();
          open();
        }
      };
      menu.onkeydown = (event) => {
        const options = Array.from(menu.querySelectorAll('button:not(:disabled)'));
        const index = options.indexOf(document.activeElement);
        let next = index;
        if (event.key === 'ArrowDown') next = (index + 1) % options.length;
        else if (event.key === 'ArrowUp') next = (index - 1 + options.length) % options.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = options.length - 1;
        else if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          closeSelect(true);
          return;
        } else if (event.key === 'Tab') {
          closeSelect(true);
          return;
        } else return;
        event.preventDefault();
        options[next]?.focus();
      };
      select.addEventListener('change', () => syncSelects());
    }
    control.button.innerHTML = `<span>${esc(select.selectedOptions[0]?.textContent || '선택')}</span><svg aria-hidden="true" width="14" height="14" viewBox="0 0 20 20"><path d="m5 7 5 5 5-5"/></svg>`;
    control.button.disabled = select.disabled;
  });
}

document.addEventListener('pointerdown', (event) => {
  if (activeSelect && !activeSelect.wrapper.contains(event.target)) closeSelect();
});
window.addEventListener('resize', () => closeSelect());
$('editor').addEventListener('close', () => closeSelect());

// ---------------------------------------------------------------- start
window.addEventListener('hashchange', route);
(async () => {
  try {
    await loadConfig();
  } catch (error) {
    notice(error.message);
  }
  route();
  await refresh();
  setInterval(() => {
    if (!document.hidden && current !== 'documents') refresh(true);
  }, 15000);
})();
