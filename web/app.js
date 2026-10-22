// 내일의 법 — 웹 화면 (F2013). 첫 화면은 가운데 검색창 + 작은 버튼. 서버 API 는 server.py 상단 주석 참고.
"use strict";

const NOT_FOUND = "제공된 자료에서 확인되지 않습니다.";
const MASCOT = (pose) => `/mascot/${pose}.png`;
const TYPE_ICONS = { meta: "🗂️", article: "📜", prec: "⚖️", expc: "📘", qa: "💬", wiki: "📖" };
const STAMP = { "사실": "true", "사실 아님": "false", "확인 불가": "unknown" };
const SITUATIONS = [
  "전세 보증금을 돌려받지 못하고 있어요",
  "알바하다가 다쳤어요",
  "온라인으로 산 물건을 환불받고 싶어요",
  "보이스피싱으로 돈을 보냈어요",
];
const SAMPLE_QUESTIONS = {
  "주택임대차보호법": ["전입신고한 날 집주인이 대출을 받으면 내 보증금이 먼저인가요?",
    "계약갱신요구권은 몇 번, 몇 년 쓸 수 있나요?", "계약이 끝났는데 보증금을 안 돌려줘요"],
  "근로기준법": ["5명 미만 가게 알바도 연차휴가를 받나요?", "주휴수당은 언제 받을 수 있나요?", "해고 예고 없이 잘렸어요"],
  "전자상거래 등에서의 소비자보호에 관한 법률": ["포장을 뜯으면 환불이 안 되나요?", "청약철회는 며칠 안에 해야 하나요?"],
};
const POPULAR = ["주택임대차보호법", "근로기준법", "전자상거래 등에서의 소비자보호에 관한 법률", "도로교통법", "형법", "민법(상속)"];   // 표시 이름(label)
const GENERIC_QUESTIONS = ["이 법은 누구에게 적용되나요?", "이 법으로 내가 신청할 수 있는 게 있나요?", "이 법을 어기면 어떻게 되나요?"];

const state = {
  items: [], byId: {}, category: null, search: "", selected: null, tab: "chat",
  status: { ok: true, message: "" }, found: null, busy: false,
  articles: {}, fact: {}, explain: {},
};

// ── 도구 ───────────────────────────────────────────────────────────────────────

const $ = (selector, root = document) => root.querySelector(selector);
const esc = (text) => String(text ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function inline(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[근거\s*([\d,\s]+)\]/g, (_, n) => `<span class="cite">근거 ${n.replace(/\s/g, "")}</span>`);
}

/** 답변용 작은 Markdown — 먼저 이스케이프하고 굵게 · 목록 · 제목 · 근거 표시만 바꾼다. */
function md(text) {
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of esc(text).split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)/);
    const numbered = line.match(/^\d+[.)]\s+(.*)/);
    const heading = line.match(/^#{1,4}\s+(.*)/);
    if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (list !== tag) { close(); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
    } else {
      close();
      if (heading) out.push(`<p><b>${inline(heading[1])}</b></p>`);
      else if (line) out.push(`<p>${inline(line)}</p>`);
    }
  }
  close();
  return out.join("");
}

// 브라우저 저장소는 막혀 있을 수 있다 — 실패해도 앱은 그대로 동작
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장 못 해도 괜찮다 */ } },
};
const historyKey = (id) => `naeil:history:${id}`;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = "요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
    try { message = (await response.json()).detail || message; } catch { /* 기본 문구 */ }
    throw new Error(message);
  }
  return response.json();
}

/** NDJSON 스트림 — 진행 단계는 onStep 으로, 마지막 결과를 돌려준다 (F2012). */
async function streamPost(path, body, onStep) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = "요청을 처리하지 못했어요.";
    try { message = (await response.json()).detail || message; } catch { /* 기본 문구 */ }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, cut).trim();
      buffer = buffer.slice(cut + 1);
      if (!line) continue;
      const event = JSON.parse(line);
      if (event.type === "step") onStep(event.message);
      else if (event.type === "error") throw new Error(event.message);
      else if (event.type === "result") return event;
    }
  }
  throw new Error("응답이 중간에 끊겼어요. 다시 시도해 주세요.");
}

// ── 공통 조각 ─────────────────────────────────────────────────────────────────

const note = (pose, html, cls = "") =>
  `<div class="note ${cls}"><img class="law-mascot" src="${MASCOT(pose)}" alt=""><p>${html}</p></div>`;

function workingCard(title) {
  const el = document.createElement("div");
  el.className = "card working";
  el.innerHTML = `<img class="law-mascot bob" src="${MASCOT("reading")}" alt="">
    <div><b>${esc(title)}</b><ul class="timeline"></ul></div>`;
  const timeline = $(".timeline", el);
  el.step = (message) => {
    timeline.querySelectorAll("li.now").forEach((li) => { li.className = "done"; });
    timeline.insertAdjacentHTML("beforeend", `<li class="now">${esc(message)}</li>`);
  };
  return el;
}

function errorCard(message) {
  return `<div class="card alert"><img class="law-mascot" src="${MASCOT("thinking")}" alt="">
    <div><b>잠깐만요!</b><br>${esc(message)}</div></div>`;
}

function evidenceHtml(data, open = false) {
  const cited = data.cited || [];
  if (!cited.length) return `<div class="no-cite">ⓘ 답변에 인용된 근거가 없어요. 원문으로 한 번 더 확인해 주세요.</div>`;
  const rows = cited.map((s) => {
    const source = s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">원문 ↗</a>` : esc(s.citation);
    return `<div class="exhibit"><span class="exhibit-tag">근거 ${s.n}</span>
      <span class="exhibit-type">${TYPE_ICONS[s.type] || ""} ${esc(s.type_label)}</span>
      <b>${esc(s.title)}</b> · ${source}<p>${esc(s.excerpt)}${s.excerpt.length >= 400 ? "…" : ""}</p></div>`;
  }).join("");
  return `<details class="evidence" ${open ? "open" : ""}><summary>답변에 사용한 근거 ${cited.length}건</summary>${rows}
    ${data.kogl ? `<div class="notice">🅚 ${esc(data.kogl)}</div>` : ""}</details>`;
}

function reportHtml(report, elapsed) {
  if (!report) return elapsed ? `<div class="report">${elapsed}초</div>` : "";
  let text;
  if (report.fallback) text = `외부 연결이 안 돼 저장된 문서 묶음으로 답했어요`;
  else if (report.new_queries.length) text = `새 문서 ${report.selected.length}건을 모아 답했어요`;
  else text = `이미 모아 둔 문서 ${report.reused}건으로 답했어요`;
  return `<div class="report">🔎 ${esc(text)} · 검색어: ${esc(report.queries.join(", "))} · ${elapsed}초</div>`;
}

function answerHtml(data, latest = false) {
  const notFound = (data.answer || "").startsWith(NOT_FOUND);
  const body = notFound
    ? note("thinking", `<b>${NOT_FOUND}</b><br><span class="muted">질문을 조금 바꾸거나, ‘법 찾기’에서 다른 법을 골라 보세요.</span>`)
      + md(data.answer.slice(NOT_FOUND.length))
    : md(data.answer);
  return `<div class="md">${body}</div>
    ${(data.warnings || []).map((w) => `<div class="warn">⚠️ ${esc(w)}</div>`).join("")}
    ${evidenceHtml(data, latest)}
    ${(data.notices || []).map((n) => `<div class="notice">${esc(n)}</div>`).join("")}
    ${reportHtml(data.report, data.elapsed)}`;
}

// 가장 최근 답변은 근거를 펼쳐 둔다
const replyHtml = (data, latest = false) =>
  `<div class="reply"><img src="${MASCOT("avatar")}" alt="로우"><div class="paper">${answerHtml(data, latest)}</div></div>`;

// ── 사건 목록 (법률 고르기) ────────────────────────────────────────────────────

function renderDocket() {
  const categories = [...new Set(state.items.map((i) => i.category))];
  $("#categories").innerHTML = [null, ...categories].map((c) =>
    `<button class="chip ${state.category === c ? "on" : ""}" data-category="${esc(c ?? "")}">${esc(c ?? "전체")}</button>`).join("");
  const words = state.search.trim();
  const list = state.items.filter((i) =>
    (!state.category || i.category === state.category) && (!words || i.label.includes(words)));
  $("#lawList").innerHTML = list.map((i) => `<li><button class="${state.selected === i.item_id ? "on" : ""}"
      data-item="${i.item_id}">${esc(i.label)}<span class="law-cat">${esc(i.category)}</span></button></li>`).join("")
    || `<li class="muted" style="padding:8px">찾는 법률이 없어요.</li>`;
}

async function renderDocketFoot() {
  const foot = $("#docketFoot");
  if (!state.selected) { foot.textContent = `법률 메타데이터 색인 ${state.status.meta_count ?? 0}건`; return; }
  try {
    const detail = await api(`/api/items/${state.selected}`);
    foot.innerHTML = `법률 메타데이터 색인 ${state.status.meta_count ?? 0}건<br>
      이 법률에 모은 문서 ${detail.collected_titles.length}건 (청크 ${detail.docs_count}개)`;
  } catch { foot.textContent = ""; }
}

/** ask — 상황 검색에 적은 문장. 대화가 열리면 그 문장을 첫 질문으로 바로 물어본다 (다시 적지 않게). */
function select(itemId, ask = "") {
  state.selected = itemId;
  state.tab = "chat";
  const item = state.byId[itemId];
  if (item && state.category && item.category !== state.category) state.category = item.category;
  $("#docket").classList.add("collapsed");
  $("#menu").setAttribute("aria-expanded", "false");
  renderDocket();
  renderDocketFoot();
  renderMain();
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (ask && state.status.ok) sendQuestion(ask);
}

// ── 화면 ───────────────────────────────────────────────────────────────────────

function renderMain() {
  const main = $("#main");
  window.history.replaceState(null, "", state.selected ? `#${state.selected}/${state.tab}` : location.pathname);
  const alert = state.status.ok ? "" : errorCard(state.status.message);
  // 첫 화면 — 가운데 검색창 + 작은 버튼. 사이드바 · 머리글은 숨기고, 바닥글은 맨 아래에 고정
  document.body.classList.toggle("landing", !state.selected);
  if (state.selected) positionLanding();
  if (!state.selected) {
    main.innerHTML = `${alert}
      <section class="landing-hero">
        <details class='law-talk'><summary title='로우를 눌러 보세요'><img class="law-mascot bob" src="${MASCOT("wave")}" alt="손 흔드는 로우 — 눌러서 인사 보기"><span class='tap-hint'>👆 로우를 눌러 보세요</span></summary><div class='law-bubble' role='note'><b class='title'>안녕하세요, 저는 <em>로우</em>예요!</b><p>법을 잘 몰라도 괜찮아요 😊<br><span class="kw kw-home">집</span> · <span class="kw kw-job">알바</span> · <span class="kw kw-shop">쇼핑</span> · <span class="kw kw-money">돈</span> 문제처럼 <b>생활 속 궁금한 점</b>을 물어보면, 실제 <b>법 조문과 판례를 찾아 근거와 함께</b> 알려 드려요.</p></div></details>
        <h1>내일의 법</h1>
        <p class="landing-slogan">내 일에 필요한 법, 내일을 위한 지식.</p>
        <p class="landing-hint">있었던 일을 그대로 들려주세요. 어려운 법 이야기는 로우가 대신 읽고 알려 드릴게요.</p>
        <form id="mainSearch" class="main-search" role="search">
          <input name="q" type="search" autocomplete="off" maxlength="500" aria-label="궁금한 상황이나 법률 이름"
                 placeholder="궁금한 상황이나 법률 이름  예) 알바하다가 다쳤어요" value="${esc(state.search_q || "")}">
          ${state.searching ? `<span class="search-spinner" role="status" aria-label="검색 중"></span>` : ""}
          <button class="btn gold" ${state.searching ? "disabled" : ""}>검색</button>
        </form>
        <div class="small-buttons">
          ${[["laws", "📚 법률 고르기"], ["popular", "⭐ 자주 찾는 법"], ["situation", "🔎 상황으로 법 찾기"]]
            .map(([id, label]) => `<button class="small-btn ${state.panel === id ? "on" : ""}" data-panel="${id}"
               aria-expanded="${state.panel === id}">${label}</button>`).join("")}
        </div>
      </section>
      <section id="landingPanel"></section>`;
    renderLandingPanel();
    watchLanding();
    requestAnimationFrame(positionLanding);
    return;
  }

  const item = state.byId[state.selected];
  const date = item.effective_date;
  main.innerHTML = `${alert}
    <section class="card case-head">
      <div class="case-label">사건 기록부 · ${esc(item.category)}</div>
      <h1>${esc(item.label)}</h1>
      <span class="badge">소관 ${esc(item.ministry)}</span>
      <span class="badge">${date.slice(0, 4)}.${date.slice(4, 6)}.${date.slice(6)} 시행</span>
      <a href="${esc(item.url)}" target="_blank" rel="noopener">법령 원문 ↗</a>
      <div id="riskNotices"></div>
    </section>
    <nav class="tabs" role="tablist">
      ${[["chat", "💬 물어보기"], ["fact", "⚖️ 사실일까?"], ["explain", "📜 조문 쉽게 읽기"], ["find", "🔎 법 찾기"]]
        .map(([id, label]) => `<button class="tab" role="tab" data-tab="${id}" aria-selected="${state.tab === id}">${label}</button>`).join("")}
    </nav>
    <section id="panel"></section>`;
  api(`/api/items/${item.item_id}`).then((d) => {
    $("#riskNotices").innerHTML = d.notices.slice(1).map((n) => `<div class="risk">${esc(n)}</div>`).join("");
  }).catch(() => {});
  renderPanel();
}

// ── 첫 화면 위치 — 처음엔 세로 가운데, 패널 · 결과가 열리면 위로 올라간다 ─────────

function landingActive() {
  return Boolean(state.panel || state.searchResult || state.searching);
}

function positionLanding() {
  const layout = document.querySelector(".layout");
  const hero = document.querySelector(".landing-hero");
  if (!layout) return;
  if (!hero || !document.body.classList.contains("landing")) { layout.style.removeProperty("--hero-top"); return; }
  const footer = document.querySelector("footer");
  const free = window.innerHeight - (footer ? footer.offsetHeight : 0) - hero.offsetHeight;
  const top = landingActive() ? 24 : Math.max(24, Math.round(free / 2));
  layout.style.setProperty("--hero-top", `${top}px`);
}
window.addEventListener("resize", positionLanding);
// 좁은 화면에서는 말풍선이 로우 아래로 열려 덩어리 높이가 바뀐다 → 다시 가운데로
document.addEventListener("toggle", positionLanding, true);
// 글꼴 · 이미지가 늦게 불러와지면 덩어리 · 바닥글 높이가 바뀐다 (실측 431px → 407px).
// 처음 잰 값에 머물면 새로고침 직후 위로 치우치므로, 높이가 바뀔 때마다 다시 계산한다.
const landingObserver = new ResizeObserver(() => positionLanding());
function watchLanding() {
  landingObserver.disconnect();
  [".landing-hero", "footer"].forEach((sel) => { const el = document.querySelector(sel); if (el) landingObserver.observe(el); });
}
document.fonts?.ready.then(positionLanding);
window.addEventListener("load", () => {
  positionLanding();
  // 첫 자리는 애니메이션 없이 — 이후 버튼으로 오르내릴 때만 움직임을 보인다
  requestAnimationFrame(() => document.body.classList.remove("no-anim"));
});

// ── 첫 화면 패널 ─────────────────────────────────────────────────

function renderLandingPanel() {
  const box = $("#landingPanel");
  if (!box) return;
  box.className = "";
  if (state.panel === "laws") {
    box.className = "card landing-panel";
    box.innerHTML = `<h2>📚 법률 고르기</h2>
      <input class="search" id="panelLawSearch" type="search" placeholder="법률 이름으로 찾기" value="${esc(state.search)}" aria-label="법률 이름으로 찾기">
      <div class="chips" id="panelCategories"></div>
      <ul class="law-list panel-list" id="panelLawList"></ul>`;
    renderPanelLaws();
  } else if (state.panel === "popular") {
    box.className = "card landing-panel";
    box.innerHTML = `<h2>⭐ 자주 찾는 법</h2><div class="popular-grid">${POPULAR.map((name) =>
      state.items.find((i) => i.label === name)).filter(Boolean).map((i) =>
      `<button class="popular-card" data-item="${i.item_id}"><span class="badge">${esc(i.category)}</span>${esc(i.label)}</button>`).join("")}</div>`;
  } else if (state.panel === "situation") {
    renderFind(box);
    box.classList.add("landing-panel");
  } else if (state.searchResult) {
    const { q, results, kind } = state.searchResult;
    box.className = "landing-panel";
    box.innerHTML = `<p class="muted" style="margin:0 0 8px">‘${esc(q)}’ — ${kind === "name" ? "이름이 맞는 법률" : "상황에 맞는 법"}</p>
      ${results.length ? `<div class="results">${results.map((r) => `
        <div class="result"><span class="badge" style="align-self:flex-start">${esc(r.category)}</span>
          <h3>${esc(r.label)}</h3>${r.reason ? `<p>${esc(r.reason)}</p>` : ""}
          <button class="btn ghost" data-item="${r.item_id}" ${kind === "situation" ? `data-ask="${esc(q)}"` : ""}>이 법으로 물어보기 →</button></div>`).join("")}</div>`
        : note("thinking", "꼭 맞는 법을 찾지 못했어요. 상황을 조금 더 구체적으로 적어 주세요.")}`;
  } else {
    box.innerHTML = "";
  }
}

function renderPanelLaws() {
  const categories = [...new Set(state.items.map((i) => i.category))];
  $("#panelCategories").innerHTML = [null, ...categories].map((c) =>
    `<button class="chip ${state.category === c ? "on" : ""}" data-category="${esc(c ?? "")}">${esc(c ?? "전체")}</button>`).join("");
  const words = state.search.trim();
  const list = state.items.filter((i) => (!state.category || i.category === state.category) && (!words || i.label.includes(words)));
  $("#panelLawList").innerHTML = list.map((i) => `<li><button data-item="${i.item_id}">${esc(i.label)}
    <span class="law-cat">${esc(i.category)}</span></button></li>`).join("") || `<li class="muted" style="padding:8px">찾는 법률이 없어요.</li>`;
}

/** 가운데 검색 — 법률 이름이면 그 법률을, 아니면 상황으로 보고 맞는 법을 찾는다 */
async function runMainSearch(q) {
  q = q.trim();
  if (!q || state.busy) return;
  state.search_q = q;
  state.panel = null;
  const key = q.replace(/\s/g, "");
  const named = state.items.filter((i) => i.label.replace(/\s/g, "").includes(key));
  if (named.length) {
    state.searchResult = { q, kind: "name", results: named.slice(0, 6) };
    renderMain();
    return;
  }
  state.searching = true;
  renderMain();
  $("#landingPanel").innerHTML = note("magnifier", "로우가 상황에 맞는 법을 찾는 중…", "bob");
  state.busy = true;
  try {
    const { results } = await api("/api/find-laws", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ condition: q }),
    });
    state.searchResult = { q, kind: "situation", results };
  } catch (error) {
    state.searchResult = null;
    $("#landingPanel").innerHTML = errorCard(error.message);
    return;
  } finally {
    state.busy = false;
    state.searching = false;
    // 결과 영역만 다시 그리므로 검색창의 로딩 아이콘은 직접 걷는다
    $("#mainSearch .search-spinner")?.remove();
    const button = $("#mainSearch .btn");
    if (button) button.disabled = false;
  }
  renderLandingPanel();
  positionLanding();
}

function renderPanel() {
  const panel = $("#panel");
  if (!panel) return;
  ({ chat: renderChat, fact: renderFact, explain: renderExplain, find: renderFind })[state.tab](panel);
}

// 💬 물어보기 — 법률별 대화 (F2009)
function renderChat(panel) {
  const item = state.byId[state.selected];
  const history = store.get(historyKey(item.item_id), []);
  const samples = SAMPLE_QUESTIONS[item.name] || GENERIC_QUESTIONS;
  panel.innerHTML = `
    <div class="thread" id="thread">
      ${history.length ? history.map((m, n) => m.role === "user"
        ? `<div class="bubble-user">${esc(m.content)}</div>` : replyHtml(m.data, n === history.length - 1)).join("")
      : `<div class="card">${note("walking", `<b>${esc(item.label)}</b>에 대해 무엇이든 물어보세요.<br>
          <span class="muted">이렇게 물어봐도 좋아요</span>`)}
          <div class="samples">${samples.map((q) => `<button class="sample" data-question="${esc(q)}">💬 ${esc(q)}</button>`).join("")}</div></div>`}
    </div>
    <form class="composer" id="chatForm">
      <input class="field" name="q" placeholder="${esc(item.label)}에 대해 물어보세요" autocomplete="off" maxlength="1000" ${state.status.ok ? "" : "disabled"}>
      <button class="btn gold" ${state.status.ok ? "" : "disabled"}>보내기</button>
    </form>
    ${history.length ? `<div style="text-align:right;margin-top:8px"><button class="btn ghost" id="clearChat">이 법의 대화 지우기</button></div>` : ""}`;
}

async function sendQuestion(question) {
  if (state.busy || !question.trim()) return;
  const item = state.byId[state.selected];
  const key = historyKey(item.item_id);
  const history = store.get(key, []);
  const thread = $("#thread");
  if (!history.length) thread.innerHTML = "";
  thread.insertAdjacentHTML("beforeend", `<div class="bubble-user">${esc(question)}</div>`);
  const working = workingCard("로우가 법전을 넘기고 있어요");
  thread.appendChild(working);
  working.scrollIntoView({ behavior: "smooth", block: "center" });
  state.busy = true;
  try {
    const data = await streamPost("/api/chat", {
      item_id: item.item_id, question,
      history: history.map((m) => ({ role: m.role, content: m.role === "user" ? m.content : m.data.answer })),
    }, working.step);
    history.push({ role: "user", content: question }, { role: "assistant", data });
    store.set(key, history);
    working.outerHTML = replyHtml(data, true);
  } catch (error) {
    working.outerHTML = errorCard(error.message);
  } finally {
    state.busy = false;
  }
}

// ⚖️ 사실일까? — 팩트체크 판정 (F2010 ①)
function renderFact(panel) {
  const saved = state.fact[state.selected];
  panel.innerHTML = `
    <div class="card">
      ${note("gavel", "<b>들은 이야기가 법적으로 맞는지</b> 로우가 근거를 찾아 판정해 드려요.")}
      <form id="factForm">
        <textarea class="field" name="claim" rows="3" maxlength="1000" placeholder="예) 전입신고를 한 당일부터 대항력이 생긴다">${esc(saved?.claim || "")}</textarea>
        <div style="margin-top:10px"><button class="btn" ${state.status.ok ? "" : "disabled"}>⚖️ 판정하기</button></div>
      </form>
    </div>
    <div id="factResult" style="margin-top:14px">${saved ? verdictHtml(saved) : ""}</div>`;
}

const verdictHtml = (saved) => `
  <div class="card">
    <div class="verdict">
      <img class="law-mascot" src="${MASCOT(saved.data.verdict === "확인 불가" ? "thinking" : "gavel")}" alt="">
      <div><div class="claim">“${esc(saved.claim)}”</div>
        <span class="stamp ${STAMP[saved.data.verdict]}">${esc(saved.data.verdict)}</span></div>
    </div>
    <div class="paper" style="margin-top:14px">${answerHtml(saved.data, true)}</div>
  </div>`;

async function runFact(claim) {
  if (state.busy || !claim.trim()) return;
  const box = $("#factResult");
  const working = workingCard("로우가 근거를 살펴보고 있어요");
  box.replaceChildren(working);
  state.busy = true;
  const itemId = state.selected;
  try {
    const data = await streamPost("/api/factcheck", { item_id: itemId, claim }, working.step);
    state.fact[itemId] = { claim, data };
    box.innerHTML = verdictHtml(state.fact[itemId]);
  } catch (error) {
    box.innerHTML = errorCard(error.message);
  } finally {
    state.busy = false;
  }
}

// 📜 조문 쉽게 읽기 (F2010 ②)
async function renderExplain(panel) {
  const itemId = state.selected;
  const saved = state.explain[itemId];
  panel.innerHTML = `
    <div class="card">
      ${note("desk", "<b>어려운 조문을 하나 골라 주세요.</b> 쉬운 말로 풀고, 원문과 나란히 보여 드려요.")}
      <form id="explainForm" style="display:flex;gap:8px;flex-wrap:wrap">
        <select class="field" name="article" style="flex:1;min-width:220px" aria-label="조문"><option value="">조문을 불러오는 중…</option></select>
        <button class="btn" ${state.status.ok ? "" : "disabled"}>📜 쉽게 풀어 줘</button>
      </form>
    </div>
    <div id="explainResult">${saved ? explainHtml(saved) : ""}</div>`;
  try {
    state.articles[itemId] ??= await api(`/api/items/${itemId}/articles`);
    if (state.selected !== itemId || state.tab !== "explain") return;
    $("#explainForm select").innerHTML = `<option value="">조문을 고르세요</option>` +
      state.articles[itemId].map((a) => `<option value="${a.index}">${esc(a.label)}</option>`).join("");
  } catch (error) {
    $("#explainResult").innerHTML = errorCard(error.message);
  }
}

const explainHtml = (data) => `
  <div class="side-by-side">
    <div class="paper"><h3>🟡 쉽게 말하면</h3>${answerHtml(data, true)}</div>
    <div><h3>📜 원문 — ${esc(data.original.title)}</h3>
      <div class="parchment">${esc(data.original.text)}</div>
      <p><a href="${esc(data.original.url)}" target="_blank" rel="noopener">법령 원문 보기 ↗</a></p></div>
  </div>`;

async function runExplain(index) {
  if (state.busy || index === "") return;
  const box = $("#explainResult");
  const working = workingCard("로우가 조문을 읽고 있어요");
  working.style.marginTop = "14px";
  box.replaceChildren(working);
  state.busy = true;
  const itemId = state.selected;
  try {
    state.explain[itemId] = await streamPost("/api/explain", { item_id: itemId, article_index: Number(index) }, working.step);
    box.innerHTML = explainHtml(state.explain[itemId]);
  } catch (error) {
    box.innerHTML = errorCard(error.message);
  } finally {
    state.busy = false;
  }
}

// 🔎 법 찾기 — 조건 기반 항목 탐색 (F2011)
function renderFind(panel) {
  panel.classList.add("card");
  panel.innerHTML = `
    ${note("magnifier", "<b>어떤 법을 봐야 할지 모르겠다면</b> 지금 상황을 편하게 적어 주세요. 로우가 관련 있는 법만 골라 드려요.")}
    <div class="chips">${SITUATIONS.map((s) => `<button class="chip" data-situation="${esc(s)}">${esc(s)}</button>`).join("")}</div>
    <form id="findForm" style="display:flex;gap:8px">
      <input class="field" name="condition" maxlength="500" placeholder="예) 월세 계약을 했는데 집주인이 수리를 안 해 줘요" value="${esc(state.found?.condition || "")}">
      <button class="btn" ${state.status.ok ? "" : "disabled"}>찾아보기</button>
    </form>
    <div id="findResult">${findResultHtml()}</div>`;
}

function findResultHtml() {
  if (!state.found) return "";
  if (!state.found.results.length)
    return `<div style="margin-top:14px">${note("thinking", "조건에 꼭 맞는 법을 찾지 못했어요. 상황을 조금 더 구체적으로 적어 주세요.")}</div>`;
  return `<p class="muted" style="margin:14px 0 0">‘${esc(state.found.condition)}’에 맞는 법</p>
    <div class="results">${state.found.results.map((r) => `
      <div class="result"><span class="badge" style="align-self:flex-start">${esc(r.category)}</span>
        <h3>${esc(r.label)}</h3><p>${esc(r.reason)}</p>
        <button class="btn ghost" data-item="${r.item_id}" data-ask="${esc(state.found.condition)}">이 법으로 물어보기 →</button></div>`).join("")}</div>`;
}

async function runFind(condition) {
  if (state.busy || !condition.trim()) return;
  const box = $("#findResult");
  box.innerHTML = `<div style="margin-top:14px">${note("magnifier", "로우가 법률 목록을 살펴보는 중…", "bob")}</div>`;
  state.busy = true;
  try {
    const { results } = await api("/api/find-laws", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ condition }),
    });
    state.found = { condition, results };
    box.innerHTML = findResultHtml();
  } catch (error) {
    box.innerHTML = errorCard(error.message);
  } finally {
    state.busy = false;
  }
}

// ── 이벤트 ─────────────────────────────────────────────────────────────────────

document.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) return;
  if (target.id === "home") { event.preventDefault(); state.selected = null; state.panel = null; state.searchResult = null; state.found = null; renderDocket(); renderDocketFoot(); renderMain(); return; }
  if (target.id === "menu") {
    const docket = $("#docket");
    docket.classList.toggle("collapsed");
    target.setAttribute("aria-expanded", String(!docket.classList.contains("collapsed")));
    return;
  }
  if (target.dataset.panel) { state.panel = state.panel === target.dataset.panel ? null : target.dataset.panel; renderMain(); return; }
  if (target.dataset.category !== undefined) {
    state.category = target.dataset.category || null; renderDocket(); if ($("#panelLawList")) renderPanelLaws(); return;
  }
  if (target.dataset.item) { select(target.dataset.item, target.dataset.ask || ""); return; }
  if (target.dataset.tab) { state.tab = target.dataset.tab; renderMain(); return; }
  if (target.dataset.question) { sendQuestion(target.dataset.question); return; }
  if (target.dataset.situation) {
    const input = $("#findForm input");
    if (input) input.value = target.dataset.situation;
    runFind(target.dataset.situation);
    return;
  }
  if (target.id === "clearChat") { store.set(historyKey(state.selected), []); renderPanel(); }
});

document.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === "chatForm") { const q = form.q.value; form.q.value = ""; sendQuestion(q); }
  if (form.id === "factForm") runFact(form.claim.value);
  if (form.id === "explainForm") runExplain(form.article.value);
  if (form.id === "findForm") runFind(form.condition.value);
  if (form.id === "mainSearch") runMainSearch(form.q.value);
});

$("#lawSearch").addEventListener("input", (event) => { state.search = event.target.value; renderDocket(); });
document.addEventListener("input", (event) => {
  if (event.target.id === "panelLawSearch") { state.search = event.target.value; renderPanelLaws(); }
});

// ── 시작 ───────────────────────────────────────────────────────────────────────

(async function start() {
  try {
    state.items = await api("/api/items");
    state.byId = Object.fromEntries(state.items.map((i) => [i.item_id, i]));
  } catch (error) {
    $("#main").innerHTML = errorCard(error.message);
    return;
  }
  try { state.status = await api("/api/status"); } catch (error) { state.status = { ok: false, message: error.message }; }
  const badge = $("#status");
  badge.textContent = state.status.ok ? `법률 ${state.status.meta_count}건 색인` : "답변 준비 안 됨";
  badge.classList.toggle("bad", !state.status.ok);
  // 바로가기 주소 — #law_001 또는 #law_001/fact 로 그 법률 · 탭을 바로 연다
  const [hashItem, hashTab] = decodeURIComponent(location.hash.slice(1)).split("/");
  if (state.byId[hashItem]) {
    state.selected = hashItem;
    if (["chat", "fact", "explain", "find"].includes(hashTab)) state.tab = hashTab;
  }
  renderDocket();
  renderDocketFoot();
  renderMain();
})();
