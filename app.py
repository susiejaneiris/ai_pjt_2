"""내일의 법 — 청년을 위한 생활법령 RAG 서비스 — 생활 다방면 법률 276건 (Streamlit 화면 · F2009 ~ F2012).

실행:
    python -m scripts.build_index      # 처음 한 번 (법률 메타데이터 색인)
    streamlit run app.py

step7_skeleton.py 를 이어 쓴 프로젝트 본 파일입니다. 화면은 service/ 만 호출합니다 (NF2005).
첫 화면은 가운데 검색창 + 작은 버튼(법률 고르기 · 자주 찾는 법 · 상황으로 법 찾기)이고, 버튼을 눌러야
패널이 열린다. 로우를 누르면 인사 말풍선, 경고 바닥글은 아래 고정. 사이드바는 법률을 고른 뒤에만.
웹 화면(web/)과 같은 "로우의 작은 법정" 컨셉 — 남색 법정 판넬 · 사건 기록부 · 증거 서류(근거) · 판결 도장.

마스코트 로우 배치
    wave       처음 화면 인사            magnifier  내게 맞는 법 찾기
    walking    법률을 고른 뒤 빈 대화     reading    자료 수집 중 (진행 표시)
    avatar     답변 말풍선               thinking   근거 없음 · 결과 없음 · 오류
    gavel      팩트체크 판정             desk       조문 쉽게 읽기
    scale      로고 · 면책 안내
"""

import base64
import html
import logging
import re
from functools import lru_cache

import streamlit as st
from openai import APIConnectionError, AuthenticationError

from config import ROOT
from prep.casebook import KOGL_NOTICE
from prep.disclaimer import LEGAL, notices_for
from prep.easy_explain import load_easy
from prep.item_text import load_items
from rag.prompts import NOT_FOUND

from service.features import article_choices, explain, factcheck
from service.complex import answer_complex, decompose
from service.find_laws import find_laws
from service.offline import QUOTA_MESSAGE, ask_or_offline, is_quota_error
from service.runtime import build_runtime
from store.vectorstore import MissingKeyError

SERVICE_NAME = "내일의 법"
SLOGAN = "내 일에 필요한 법, 내일을 위한 지식."
MASCOT_DIR = ROOT / "assets" / "mascot"
TYPE_ICONS = {"meta": "🗂️", "article": "📜", "prec": "⚖️", "expc": "📘", "qa": "💬", "wiki": "📖"}
CITE = re.compile(r"\[근거\s*([\d,\s]+)\]")
STAMP_CLASS = {"사실": "true", "사실 아님": "false", "확인 불가": "unknown"}

SAMPLE_SITUATIONS = [
    "전세 보증금을 돌려받지 못하고 있어요",
    "알바하다가 다쳤어요",
    "온라인으로 산 물건을 환불받고 싶어요",
    "보이스피싱으로 돈을 보냈어요",
]
POPULAR_LAWS = ["주택임대차보호법", "근로기준법", "전자상거래 등에서의 소비자보호에 관한 법률",
                "도로교통법", "형법", "민법(상속)"]      # 표시 이름(label)
SAMPLE_QUESTIONS = {
    "주택임대차보호법": ["전입신고한 날 집주인이 대출을 받으면 내 보증금이 먼저인가요?",
                    "계약갱신요구권은 몇 번, 몇 년 쓸 수 있나요?",
                    "계약이 끝났는데 보증금을 안 돌려줘요"],
    "근로기준법": ["5명 미만 가게 알바도 연차휴가를 받나요?",
               "주휴수당은 언제 받을 수 있나요?",
               "해고 예고 없이 잘렸어요"],
    "전자상거래 등에서의 소비자보호에 관한 법률": ["포장을 뜯으면 환불이 안 되나요?",
                                 "청약철회는 며칠 안에 해야 하나요?"],
}
GENERIC_QUESTIONS = ["이 법은 누구에게 적용되나요?", "이 법으로 내가 신청할 수 있는 게 있나요?",
                     "이 법을 어기면 어떻게 되나요?"]

log = logging.getLogger("naeil_law")
esc = html.escape


def mascot(pose: str) -> str:
    return str(MASCOT_DIR / f"{pose}.png")


@lru_cache(maxsize=16)
def mascot_src(pose: str) -> str:
    """HTML 로 직접 그릴 때 쓰는 data URI — 애니메이션 · 배치를 CSS 로 다루기 위해."""
    data = base64.b64encode((MASCOT_DIR / f"{pose}.png").read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def mascot_img(pose: str, width: int, cls: str = "") -> str:
    return f"<img class='law-mascot {cls}' src='{mascot_src(pose)}' width='{width}' alt=''>"


st.set_page_config(page_title=SERVICE_NAME, page_icon=mascot("avatar"), layout="centered")
st.markdown("""
<style>
:root { --navy:#1f2a44; --navy-2:#2b3a5c; --gold:#c9a44c; --gold-soft:#f3e3b5; --gold-ink:#8c6a1f;
        --paper:#fffdf8; --paper-2:#f6f0e4; --line:#e6dccb; --muted:#7a7468; --red:#b3412e; --green:#2f6b4f; }
/* 위 여백은 Streamlit 상단 막대(실행 표시 · Stop · 배포 사이트의 Fork · GitHub, 높이 3.75rem)보다 크게 — 작으면 판넬 윗부분이 막대 밑에 깔린다 */
.block-container { padding-top: 4.5rem; }

/* 법정 판넬 */
.bench { display:flex; align-items:center; gap:12px; padding:12px 18px; margin-bottom:18px; border-radius:16px;
  color:#fff; border-bottom:3px solid var(--gold);
  background: repeating-linear-gradient(90deg, rgba(255,255,255,.03) 0 2px, transparent 2px 80px),
              linear-gradient(180deg, var(--navy-2), var(--navy)); }
.bench .name { font-size:1.5rem; font-weight:800; letter-spacing:-.02em; line-height:1.1; }
.bench .slogan { font-size:.78rem; color:var(--gold-soft); }
.bench .pill { margin-left:auto; font-size:.75rem; padding:3px 12px; border-radius:999px;
  background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.2); white-space:nowrap; }

.law-mascot { filter: drop-shadow(0 6px 10px rgba(31,42,68,.15)); }
.bob { animation: bob 2.6s ease-in-out infinite; }
@keyframes bob { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-6px); } }
@media (prefers-reduced-motion: reduce) { .bob { animation:none; } }

.paper-card { background:var(--paper); border:1px solid var(--line); border-radius:16px; padding:18px 20px;
  box-shadow:0 1px 2px rgba(31,42,68,.06), 0 6px 20px rgba(31,42,68,.07); margin-bottom:14px; }
.hero { display:grid; grid-template-columns:200px 1fr; gap:16px; align-items:center;
  background: radial-gradient(circle at 12% 30%, rgba(201,164,76,.18), transparent 45%), var(--paper); }
.hero h2 { color:var(--navy); font-weight:800; letter-spacing:-.02em; margin:0 0 6px; font-size:1.7rem; }
.hero em { font-style:normal; color:var(--gold-ink); }
.steps { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:12px; }
.step { background:#fff; border:1px solid var(--line); border-radius:12px; padding:8px 10px; font-size:.82rem; }
.step-num { display:inline-grid; place-items:center; width:1.45rem; height:1.45rem; border-radius:50%;
  background:var(--navy); color:var(--gold-soft); font-size:.78rem; margin-right:4px; }
.note { display:grid; grid-template-columns:auto 1fr; gap:14px; align-items:center; margin:4px 0 12px; }
.note b { color:var(--navy); }

.case-head { border-top:6px solid var(--navy); position:relative; overflow:hidden; }
.case-head::after { content:"法"; position:absolute; right:16px; top:-12px; 
  font-size:5.5rem; color:rgba(201,164,76,.13); }
.case-label { font-size:.74rem; letter-spacing:.12em; color:var(--gold-ink); font-weight:700; }
.case-head h1 { font-size:1.55rem; font-weight:800; letter-spacing:-.02em; color:var(--navy); margin:2px 0 8px; padding:0; }
/* 카드의 법률 이름 — 마우스를 올리거나(키보드 Tab 으로 가도) 쉬운 설명 말풍선 */
.law-name { font-weight:700; color:#1f2a44; position:relative; }
.law-name[data-tip] { cursor:help; text-decoration: underline dotted var(--gold); text-underline-offset: 4px; }
.law-name[data-tip]:hover::after, .law-name[data-tip]:focus::after { content: attr(data-tip); position:absolute; left:0; top: calc(100% + 8px);
  z-index: 1000; width: max-content; max-width: 300px; padding: 10px 12px; border-radius: 12px; background: var(--navy); color: #fff;
  font-size: .82rem; font-weight: 500; line-height: 1.55; white-space: normal; word-break: keep-all; box-shadow: 0 8px 22px rgba(31,42,68,.22); }
.law-name[data-tip]:hover::before, .law-name[data-tip]:focus::before { content:""; position:absolute; left:14px; top: calc(100% + 2px);
  border: 6px solid transparent; border-bottom-color: var(--navy); border-top: 0; z-index: 1001; }
/* 말풍선이 카드 · 고정 바닥글(z-index 50) 위로 나오게 — 마우스를 올린 카드를 앞으로 */
[data-testid="stVerticalBlockBorderWrapper"]:has(.law-name:hover), [data-testid="stElementContainer"]:has(.law-name:hover) { z-index: 1000; position: relative; }
.badge { display:inline-block; font-size:.74rem; padding:2px 10px; border-radius:999px; margin:0 4px 4px 0;
  background:var(--paper-2); border:1px solid var(--line); color:var(--gold-ink); }

/* 증거 서류 (근거) */
.exhibit { margin:8px 0; padding:9px 12px 9px 14px; background:#fff; border:1px solid var(--line);
  border-left:4px solid var(--gold); border-radius:8px; font-size:.86rem; }
.exhibit-tag { display:inline-block; background:var(--navy); color:var(--gold-soft); font-size:.72rem; font-weight:700;
  padding:1px 8px; border-radius:4px; margin-right:6px; }
.exhibit .type { font-size:.74rem; color:var(--muted); margin-right:4px; }
.exhibit p { margin:6px 0 0; color:#4a4a4a; font-size:.82rem; white-space:pre-wrap; }
.small-note { font-size:.78rem; color:var(--muted); margin-top:4px; }

/* 판결 도장 */
.verdict { display:grid; grid-template-columns:auto 1fr; gap:16px; align-items:center; }
.claim { font-size:1.05rem; font-weight:600; color:var(--navy); }
.stamp { display:inline-block; margin-top:8px; padding:3px 16px; border:3px solid currentColor; border-radius:8px;
  font-weight:800; font-size:1.45rem; letter-spacing:.12em;
  transform:rotate(-6deg); opacity:.9; animation: stamp .35s cubic-bezier(.2,1.6,.4,1) both; }
.stamp.true { color:var(--green); } .stamp.false { color:var(--red); } .stamp.unknown { color:var(--muted); }
@keyframes stamp { from { transform:rotate(-6deg) scale(1.6); opacity:0; } to { transform:rotate(-6deg) scale(1); opacity:.9; } }
.parchment { background:linear-gradient(180deg,#fffaf0,#f8f0dd); border:1px solid #e8d9b5; border-radius:12px;
  padding:14px 16px; white-space:pre-wrap; font-size:.9rem; line-height:1.8; }

/* 탭 · 버튼 · 말풍선 */
.stTabs [role="tablist"] { gap:6px; flex-wrap:wrap; border-bottom:0; }
.stTabs [data-testid="stTab"] { border:1px solid var(--line); border-radius:999px; padding:6px 16px; background:#fff; }
.stTabs [data-testid="stTab"] p { font-weight:600; }
.stTabs [data-testid="stTab"][aria-selected="true"] { background:var(--navy); border-color:var(--navy); }
/* Streamlit 기본 탭 강조선(선택 탭 밑 2px) · 탭 줄 아래 구분선 — 남색 알약 밑으로 비쳐 보여서 없앤다 */
.stTabs [role="tablist"] .react-aria-SelectionIndicator { display:none; }
.stTabs [role="tablist"]::after { display:none; }
.st-key-scroll_top { display:none; }
.stTabs [data-testid="stTab"][aria-selected="true"] p { color:#fff; }
[data-testid="stChatMessage"] { background:transparent; }
[data-testid="stImage"] img { pointer-events:none; }
.stButton > button { border-radius:999px; }
/* 입력칸 안내 한글화 — Streamlit 기본 "Press Enter to submit form" 은 바꾸는 설정이 없어 숨기고 같은 자리에 넣는다 */
[data-testid="InputInstructions"] { font-size: 0 !important; }
[data-testid="InputInstructions"] > * { display: none !important; }
/* 키보드 키처럼 생긴 작은 배지 — 회색 작은 글씨는 입력칸 테두리에 묻혀 잘 보이지 않았다 */
[data-testid="InputInstructions"]::after { content: "↵ Enter로 검색"; font-size: .78rem; font-weight: 700; color: var(--navy);
  background: var(--gold-soft); border: 1px solid var(--gold); border-bottom-width: 2px; border-radius: 7px;
  padding: 2px 9px; white-space: nowrap; }
[data-testid="stTextArea"] [data-testid="InputInstructions"]::after { content: "Ctrl + ↵ Enter로 판정"; }
/* 한 줄 입력칸 — 배지를 오른쪽 세로 가운데에, 글자가 배지 밑으로 들어가지 않게 오른쪽 여백.
   안내의 기준 상자는 입력칸 맨 아래에 붙은 높이 0 상자 → 아래에서 (입력칸 높이 − 배지 20px) / 2 만큼 올린다 */
[data-testid="stTextInput"] [data-testid="InputInstructions"] { position: absolute; right: 10px; top: auto; bottom: 10px;
  pointer-events: none; }
[data-testid="stTextInput"] input { padding-right: 128px; }
.st-key-main_search [data-testid="InputInstructions"] { right: 16px; bottom: 16px; }      /* 큰 검색창 52px */
.st-key-main_search input { padding-right: 150px !important; }
/* 좁은 사이드바는 짧게 */
[data-testid="stSidebar"] [data-testid="InputInstructions"]::after { content: "↵ Enter"; }
[data-testid="stSidebar"] [data-testid="stTextInput"] input { padding-right: 78px; }

/* 사이드바 — 한국어는 글자 단위로 끊기면 읽기 어렵다 → 단어 단위 줄바꿈 */
[data-testid="stSidebar"] { word-break: keep-all; overflow-wrap: anywhere; }
.brand-row { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
.brand-row b { font-size:1.3rem; font-weight:800; color:var(--navy); line-height:1.2; }
.brand-row .slogan { font-size:.76rem; color:var(--gold-ink); line-height:1.4; }
.doc-row { font-size:.8rem; line-height:1.45; padding:5px 2px; border-bottom:1px dashed var(--line); color:#4a4a4a; }
.doc-row:last-child { border-bottom:0; }
/* 사이드바 법률 목록 — 한 줄에 하나씩, 고른 법률은 남색 */
[data-testid="stSidebar"] [data-testid="stRadio"] label { padding:4px 6px; border-radius:8px; width:100%; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:var(--paper-2); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background:var(--navy); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p { color:#fff; font-weight:600; }
[data-testid="stSidebar"] [data-testid="stRadio"] p { font-size:.88rem; }
.side-footer { display:flex; flex-direction:column; align-items:center; gap:6px; text-align:center;
  font-size:.76rem; line-height:1.55; color:var(--muted); }
.side-footer .sources { font-size:.7rem; opacity:.85; }
@media (max-width: 640px) { .hero { grid-template-columns:1fr; text-align:center; } .steps { grid-template-columns:1fr; text-align:left; } }
</style>
""", unsafe_allow_html=True)


# ── 데이터 · 실행 객체 ─────────────────────────────────────────────────────────────

@st.cache_data
def get_items() -> list[dict]:
    easy = load_easy()          # 법을 몰라도 알 수 있는 한두 문장 (prep/easy_explain.py)
    return [{**i, "easy": easy.get(i["item_id"], "")} for i in load_items()]


@st.cache_resource(show_spinner="로우가 법률 목록을 정리하는 중이에요… (처음 한 번만)")
def get_runtime():
    return build_runtime()


def friendly_error(error: Exception) -> str:
    """화면에는 쉬운 안내만 — 키 · 프롬프트 · 오류 추적 정보는 보여 주지 않는다 (NF2004)."""
    if isinstance(error, MissingKeyError):
        return "GMS_KEY가 설정되지 않았어요. `.env` 파일에 키를 넣고 다시 실행해 주세요."
    if is_quota_error(error):
        return QUOTA_MESSAGE
    if isinstance(error, AuthenticationError):
        return "GMS 키가 만료되었거나 올바르지 않아요. 키를 다시 발급받아 `.env`에 넣어 주세요."
    if isinstance(error, APIConnectionError):
        return "AI 서버에 연결하지 못했어요. 네트워크를 확인하고 잠시 뒤 다시 시도해 주세요."
    return "처리하는 중에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."


items = get_items()
items_by_id = {i["item_id"]: i for i in items}
items_by_label = {i["label"]: i for i in items}
categories = list(dict.fromkeys(i["category"] for i in items))

try:
    rt, runtime_error = get_runtime(), None
except Exception as error:      # 키 누락 등 — 화면은 띄우고 안내한다
    rt, runtime_error = None, error
    log.exception("runtime")

for key, default in {"histories": {}, "factchecks": {}, "explains": {}, "found": None}.items():
    st.session_state.setdefault(key, default)


# ── 공통 그리기 ───────────────────────────────────────────────────────────────────

def input_loading(key: str):
    """검색하는 동안 입력칸의 '↵ Enter로 검색' 배지를 숨기고 같은 자리에서 로딩 아이콘을 돌린다.
    돌려준 자리(st.empty)를 .empty() 하면 원래대로. key — 그 입력칸의 위젯 key (.st-key-<key>)."""
    spot = st.empty()
    spot.markdown(f"""<style>
.st-key-{key} [data-testid="InputInstructions"] {{ display: none !important; }}
.st-key-{key} [data-testid="stTextInputRootElement"] {{ position: relative; }}
.st-key-{key} [data-testid="stTextInputRootElement"]::after {{ content: ""; position: absolute; right: 18px; top: 50%;
  width: 18px; height: 18px; margin-top: -9px; border-radius: 50%; border: 3px solid var(--gold-soft);
  border-top-color: var(--navy); animation: input-spin .8s linear infinite; }}
@keyframes input-spin {{ to {{ transform: rotate(360deg); }} }}
</style>""", unsafe_allow_html=True)
    return spot


def law_title_html(law: dict) -> str:
    """카드의 법률 이름 — 마우스를 올리면 쉬운 설명 말풍선 (설명이 없으면 이름만)."""
    tip = f" data-tip='{esc(law['easy'])}' tabindex='0'" if law.get("easy") else ""
    return f"<b class='law-name'{tip}>{esc(law['label'])}</b>"


def note(pose: str, text_html: str, width: int = 84, cls: str = "") -> None:
    st.markdown(f"<div class='note'>{mascot_img(pose, width, cls)}<div>{text_html}</div></div>",
                unsafe_allow_html=True)


def select_item(item_id: str, question: str | None = None) -> None:
    """카드 · 바로가기 → 그 법률의 대화로 (위젯 key 를 콜백에서 바꿔야 선택이 한 번에 반영된다).
    question — 상황 검색에 적은 문장. 대화가 열리면 그 문장을 첫 질문으로 바로 물어본다 (다시 적지 않게)."""
    st.session_state.auto_question = (item_id, question) if question else None
    st.session_state.category = items_by_id[item_id]["category"]
    st.session_state.law_search = ""
    st.session_state.panel = None
    st.session_state.item_id = item_id


def render_sources(cited: list[dict], expanded: bool = False) -> None:
    """답변이 실제로 인용한 근거만 — 증거 서류 꼬리표 · 원문 출처 · 발췌 (F2008 · F2016)."""
    if not cited:
        st.caption("ⓘ 답변에 인용된 근거가 없어요. 내용을 그대로 믿기 전에 원문을 확인해 주세요.")
        return
    with st.expander(f"📎 답변에 사용한 근거 {len(cited)}건", expanded=expanded):
        rows = []
        for s in cited:
            source = (f"<a href='{esc(s['url'])}' target='_blank'>원문 ↗</a>" if s["url"] else esc(s["citation"]))
            excerpt = s["text"].split("\n", 1)[-1]
            excerpt = excerpt[:280] + ("…" if len(excerpt) > 280 else "")
            rows.append(f"<div class='exhibit'><span class='exhibit-tag'>근거 {s['n']}</span>"
                        f"<span class='type'>{TYPE_ICONS.get(s['type'], '')} {esc(s['type_label'])}</span>"
                        f"<b>{esc(s['title'])}</b> · {source}<p>{esc(excerpt)}</p></div>")
        if any(s["type"] == "expc" for s in cited):
            rows.append(f"<div class='small-note'>🅚 {esc(KOGL_NOTICE)}</div>")   # 공공누리 제4유형 출처 표시
        st.markdown("".join(rows), unsafe_allow_html=True)


def cite_badges(text: str) -> str:
    """답변 속 [근거 N] 을 금색 꼬리표 배지로 — 근거 목록의 '근거 N' 과 눈으로 바로 이어지게."""
    return CITE.sub(lambda m: f":orange-badge[근거 {m.group(1).replace(' ', '')}]", text)


BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def answer_markdown(text: str) -> str:
    """답변의 **굵게** 를 <b> 로 직접 바꾼다 — 화면에 ** 가 그대로 보이지 않게.

    마크다운은 "**고등학생(미성년자 여부)**에 따라" 처럼 닫는 ** 앞이 문장부호이고 뒤에 한글이 붙으면
    굵게로 인정하지 않아 ** 를 글자로 남긴다 (한국어에서 자주 생긴다). 먼저 HTML 을 이스케이프해
    답변에 섞인 태그는 글자로만 보이게 하고, 짝이 맞지 않아 남은 ** 는 지운다.
    """
    text = html.escape(text, quote=False)
    return BOLD.sub(r"<b>\1</b>", text).replace("**", "")


def render_answer(message: dict, latest: bool = False, show_summary: bool = True) -> None:
    if message["content"].startswith(NOT_FOUND):
        note("thinking", f"<b>{NOT_FOUND}</b><br><span class='small-note'>질문을 조금 바꾸거나, "
                         "‘법 찾기’에서 다른 법을 골라 보세요.</span>", 72)
        rest = message["content"][len(NOT_FOUND):].strip()
        if rest:
            st.markdown(answer_markdown(rest), unsafe_allow_html=True)
    else:
        st.markdown(cite_badges(answer_markdown(message["content"])), unsafe_allow_html=True)
    for warning in message.get("warnings", []):
        st.caption(f"⚠️ {warning}")
    render_sources(message.get("cited", []), expanded=latest)
    for notice in message.get("notices", []):
        st.caption(notice)
    if show_summary and message.get("summary"):
        st.caption(f"🔎 {message['summary']}")


def run_with_status(label: str, task):
    """진행 표시 (F2012) — 로우가 법전을 읽는 동안 단계를 보여 주고, 끝나면 접는다."""
    with st.status(f"📚 {label}", expanded=True) as status:
        picture = st.empty()
        picture.markdown(mascot_img("reading", 104, "bob"), unsafe_allow_html=True)

        def on_step(message: str) -> None:
            status.update(label=f"📚 {message}…")
            st.write(f"· {message}")

        try:
            result = task(on_step)
        except Exception as error:
            log.exception("task")
            picture.markdown(mascot_img("thinking", 84), unsafe_allow_html=True)
            status.update(label=friendly_error(error), state="error", expanded=True)
            return None, ""
        picture.empty()

        outcome = result[1] if isinstance(result, tuple) else result
        report, elapsed = outcome.report, outcome.elapsed
        if getattr(outcome, "offline", False):
            summary = f"AI 사용 한도가 끝나 관련 원문만 찾아 보여 드려요 · {elapsed:.0f}초"
        elif report and report.fallback:
            summary = f"외부 연결이 안 돼 저장된 문서 묶음으로 답했어요 · {elapsed:.0f}초"
        elif report and report.new_queries:
            summary = f"새 문서 {len(report.raw_docs)}건을 모아 답했어요 · {elapsed:.0f}초"
        elif report:
            summary = f"이미 모아 둔 문서 {report.reused_docs}건으로 답했어요 · {elapsed:.0f}초"
        else:
            summary = f"완료 · {elapsed:.0f}초"
        if report:
            st.write("**검색어** " + " · ".join(report.queries))
            st.write("**색인한 문서** " + (" · ".join(report.selected) or "없음 (모두 이미 수집함)"))
            if report.dropped:
                st.write("**버린 후보** " + " · ".join(report.dropped[:10]))
        status.update(label=summary, state="complete", expanded=False)
    return result, summary


# ── 사이드바: 법률 고르기 · 색인 상태 ───────────────────────────────────────────────

def go_home() -> None:
    """처음 접속한 화면으로 — 검색어 · 검색 결과 · 상황 찾기 결과까지 비운다 (법률별 대화 기록은 남긴다, F2009)."""
    st.session_state.item_id = None
    st.session_state.shown_item = None          # 같은 법률에 다시 들어와도 맨 위부터
    st.session_state.panel = None
    st.session_state.search_result = None
    st.session_state.complex = None
    st.session_state.found = None
    st.session_state.auto_question = None
    for key in ("main_query", "find_condition", "landing_law_search"):
        st.session_state[key] = ""
    st.session_state.landing_category = None


item = items_by_id.get(st.session_state.get("item_id"))
if item:     # 첫 화면에서는 사이드바를 그리지 않는다 — 검색창과 작은 버튼만
    with st.sidebar:
        slogan = SLOGAN.replace(", ", ",<br>")          # "내 일에 필요한 법, / 내일을 위한 지식." 두 줄로
        st.markdown(f"<div class='brand-row'>{mascot_img('scale', 56)}<div><b>{SERVICE_NAME}</b><br>"
                    f"<span class='slogan'>{slogan}</span></div></div>", unsafe_allow_html=True)
        st.button("🏠 처음으로", on_click=go_home, width="stretch")
        st.markdown("**법률 고르기**")
        # 펼침 목록(selectbox)은 사이드바 밖 페이지 위에 떠서 108건이 영역을 넘어 펼쳐진다
        # → 분야는 칩, 법률은 사이드바 안의 높이를 정한 상자에서 스크롤하는 목록으로 둔다
        category = st.pills("분야", categories, key="category", label_visibility="collapsed")
        words = st.text_input("법률 이름으로 찾기", key="law_search", placeholder="🔍 법률 이름으로 찾기",
                              label_visibility="collapsed").strip()
        options = [i["item_id"] for i in items
                   if category in (None, i["category"]) and (not words or words in i["label"])]
        selected = st.session_state.get("item_id")
        if selected and selected not in options:
            options.insert(0, selected)      # 고른 법률은 필터에 걸러져도 목록에 남긴다 (선택이 풀리지 않게)
        with st.container(height=300, border=True):
            if options:
                item_id = st.radio("법률", options, key="item_id", index=None, label_visibility="collapsed",
                                   format_func=lambda i: items_by_id[i]["label"])
            else:
                item_id = None
                st.caption("찾는 법률이 없어요.")
        item = items_by_id.get(item_id)

        if rt:
            st.caption(f"법률 메타데이터 색인 **{rt.meta_count()}**건")
            if item:
                docs = rt.collected_docs(item["item_id"])
                with st.expander(f"이 법률에 모은 문서 {len(docs)}건"):
                    if not docs:
                        st.caption("아직 없어요. 질문하면 로우가 모아 와요.")
                    else:
                        counts = {}
                        for d in docs:
                            counts[d["type"]] = counts.get(d["type"], 0) + 1
                        st.caption(" · ".join(f"{TYPE_ICONS.get(t, '')} {n}" for t, n in counts.items()))
                        # 문서가 많아도 사이드바가 끝없이 길어지지 않게 — 정한 높이 안에서만 스크롤
                        with st.container(height=min(240, 34 * len(docs) + 16), border=False):
                            st.markdown("".join(
                                f"<div class='doc-row'>{TYPE_ICONS.get(d['type'], '')} {esc(d['title'])}</div>"
                                for d in docs), unsafe_allow_html=True)
                if st.button("이 법의 대화 지우기", width="stretch"):
                    st.session_state.histories[item["item_id"]] = []
                    st.rerun()
        st.divider()
        # 웹 화면 바닥글과 같은 모양 — 로우를 위에, 안내 · 출처를 아래에 가운데 정렬
        st.markdown(f"<div class='side-footer'>{mascot_img('scale', 48)}<div>{esc(LEGAL)}</div>"
                    f"<div class='sources'>출처: 국가법령정보센터 Open API · 한국어 위키백과(CC BY-SA 4.0) · "
                    f"법제처 「2024 법령해석 사례집」(공공누리 제4유형)</div></div>", unsafe_allow_html=True)


# ── 법정 판넬 (머리글) ─────────────────────────────────────────────────────────────

pill = f"법률 {rt.meta_count()}건 색인" if rt and not runtime_error else "답변 준비 안 됨"
if item:
    st.markdown(f"<div class='bench'>{mascot_img('scale', 46)}<div><div class='name'>{SERVICE_NAME}</div>"
                f"<div class='slogan'>{SLOGAN}</div></div><span class='pill'>{pill}</span></div>",
                unsafe_allow_html=True)

# 실행 상태 안내 (F2012)
if runtime_error:
    note("thinking", f"<b>지금은 답변을 만들 수 없어요.</b><br>{esc(friendly_error(runtime_error))}")
    st.stop()
if rt.meta_count() == 0:
    note("thinking", "<b>아직 법률 색인이 없어요.</b><br>터미널에서 아래 명령을 한 번 실행한 뒤 새로고침해 주세요.")
    st.code("python -m scripts.build_index", language="bash")
    st.stop()


# ── 내게 맞는 법 찾기 (F2011) ─────────────────────────────────────────────────────

def render_find_laws() -> None:
    note("magnifier", "<b>어떤 법을 봐야 할지 모르겠다면</b> 지금 상황을 편하게 적어 주세요. "
                      "로우가 관련 있는 법만 골라 드려요.")
    pending = None
    chips = st.columns(2)
    for n, situation in enumerate(SAMPLE_SITUATIONS):
        if chips[n % 2].button(situation, key=f"chip_{n}", width="stretch"):
            pending = situation
    with st.form("find_form", border=False):
        condition = st.text_input("내 상황", placeholder="예) 월세 계약을 했는데 집주인이 수리를 안 해 줘요",
                                  key="find_condition")
        submitted = st.form_submit_button("🔎 찾아보기", type="primary")
    query = pending or (condition.strip() if submitted else "")

    if query:
        loading = input_loading("find_condition")
        with st.spinner("로우가 법률 목록을 살펴보는 중…"):
            try:
                st.session_state.found = (query, find_laws(rt, query, items_by_id))
            except Exception as error:
                log.exception("find_laws")
                st.error(friendly_error(error))
        loading.empty()

    if st.session_state.found:
        query, results = st.session_state.found
        st.caption(f"‘{query}’에 맞는 법")
        if not results:
            note("thinking", "조건에 꼭 맞는 법을 찾지 못했어요. 상황을 조금 더 구체적으로 적어 주세요.", 72)
        cols = st.columns(2)
        for n, r in enumerate(results):
            law = r["item"]
            with cols[n % 2].container(border=True):
                st.markdown(f"<span class='badge'>{esc(law['category'])}</span><br>"
                            + law_title_html(law),
                            unsafe_allow_html=True)
                st.caption(r["reason"])
                st.button("이 법으로 물어보기 →", key=f"pick_{law['item_id']}",
                          on_click=select_item, args=(law["item_id"], query),
                          help="적은 상황을 이 법률에 바로 물어봐요")


# ── 처음 화면 — 가운데 검색창 + 작은 버튼 (법률을 고르기 전) ─────────────────────────

def toggle_panel(name: str) -> None:
    """작은 버튼 → 해당 패널을 열고, 같은 버튼을 다시 누르면 닫는다."""
    st.session_state.panel = None if st.session_state.get("panel") == name else name


def render_complex(saved: dict) -> None:
    """쟁점 나누기 결과 — 쟁점 목록(법률로 더 물어보기) · 가정 · 쟁점별 답변."""
    issues = saved["issues"]
    st.caption(f"‘{saved['q']}’ — 여러 법이 얽혀 있어 쟁점 {len(issues)}개로 나눠 살펴봤어요")
    with st.container(border=True):
        note("magnifier", "<b>쟁점별로 정리했어요.</b> 한 가지를 더 자세히 알고 싶으면 그 법을 눌러 이어서 물어보세요.", 64)
        for n, issue in enumerate(issues, start=1):
            st.markdown(f"**{n}. {esc(issue['title'])}**")
            with st.container(horizontal=True):
                for item_id in issue["laws"]:
                    law = items_by_id[item_id]
                    st.button(f"📜 {law['label']}", key=f"issue_{n}_{item_id}", width="content",
                              on_click=select_item, args=(item_id,), help=law.get("easy") or None)
        if saved["assumptions"]:
            st.caption("이렇게 가정하고 살펴봤어요 — " + " · ".join(saved["assumptions"]))
    render_answer(saved["message"], latest=True)


def render_law_cards(results: list[dict], question: str | None = None) -> None:
    """question 이 있으면(상황 검색 결과) 카드를 눌렀을 때 그 문장을 바로 물어본다."""
    cols = st.columns(2)
    for n, r in enumerate(results):
        law = r["item"]
        with cols[n % 2].container(border=True):
            st.markdown(f"<span class='badge'>{esc(law['category'])}</span><br>"
                        + law_title_html(law),
                        unsafe_allow_html=True)
            if r.get("reason"):
                st.caption(r["reason"])
            st.button("이 법으로 물어보기 →", key=f"card_{law['item_id']}",
                      on_click=select_item, args=(law["item_id"], question),
                      help="적은 상황을 이 법률에 바로 물어봐요" if question else None)


def greeting_mascot() -> str:
    """맨 위 로우 — 누르면 인사 말풍선이 열리고 다시 누르면 닫힌다 (details/summary, 스크립트 없음)."""
    return (f"<details class='law-talk'><summary title='로우를 눌러 보세요'>{mascot_img('wave', 130, 'bob')}"
            f"<span class='tap-hint'>👆 로우를 눌러 보세요</span></summary>"
            f"<div class='law-bubble' role='note'><b class='title'>안녕하세요, 저는 <em>로우</em>예요!</b>"
            f"<p>법을 잘 몰라도 괜찮아요 😊<br><span class='kw kw-home'>집</span> · <span class='kw kw-job'>알바</span> · <span class='kw kw-shop'>쇼핑</span> · <span class='kw kw-money'>돈</span> 문제처럼 <b>생활 속 궁금한 점</b>을 물어보면, "
            f"실제 <b>법 조문과 판례를 찾아 근거와 함께</b> 알려 드려요.</p></div></details>")


if not item:
    # 첫 화면 전체를 컨테이너 하나로 — 법률 화면으로 넘어가면 이 자리를 바로 덮어써서
    # 답변을 기다리는 동안 검색 결과 카드가 흐리게 남지 않는다 (Streamlit 은 다시 그리지 않은 요소를 실행이 끝날 때까지 남긴다)
    with st.container(key="landing"):
        st.session_state.setdefault("panel", None)
        st.markdown("""
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
.block-container { max-width: 760px; padding-bottom: 170px; }
.landing-brand { text-align:center; margin-bottom: 18px; }
.landing-brand .name { font-size: 2.4rem; font-weight: 800; color: var(--navy); letter-spacing: -.03em; margin-top: 4px; }
.landing-brand .slogan { font-size: .95rem; font-weight: 500; color: var(--gold-ink); }
.landing-brand .hint { font-size: .85rem; color: var(--muted); margin-top: 6px; }
/* 가운데 검색창 — 크고 둥글게 */
.st-key-main_search [data-testid="stTextInputRootElement"] { height: 52px; border-radius: 999px; border: 2px solid var(--line);
  background: #fff; box-shadow: 0 6px 20px rgba(31,42,68,.07); overflow: hidden; }
.st-key-main_search [data-testid="stTextInputRootElement"]:focus-within { border-color: var(--gold); }
.st-key-main_search [data-testid="stTextInputRootElement"] > div { height: 100%; border: 0; background: #fff; }
.st-key-main_search input { font-size: 1.02rem; padding-left: 20px; background: #fff; }
.st-key-main_search button { height: 52px; border-radius: 999px; font-weight: 700; }
/* 작은 버튼 */
.st-key-small_buttons button { border-radius: 999px; font-size: .86rem; font-weight: 600; min-height: 36px; padding: 4px 12px; }
/* 맨 아래 고정 경고 바닥글 */
.landing-footer { position: fixed; left: 0; right: 0; bottom: 0; z-index: 50; padding: 10px 16px 14px;
  display:flex; flex-direction:column; align-items:center; gap:4px; text-align:center; word-break: keep-all;
  background: rgba(251,248,243,.96); border-top: 1px solid var(--line); font-size: .76rem; color: var(--muted); }
.landing-footer .sources { font-size: .7rem; opacity: .85; }
/* 바닥글 로고 — 저울 든 로우 + 서비스명 */
.footer-brand { display: flex; align-items: center; justify-content: center; gap: 8px; }
.footer-logo { font-size: 1.05rem; font-weight: 800; letter-spacing: -.02em; color: var(--navy); }
/* 로우 말풍선 — 로우를 누르면 열리고 다시 누르면 닫힌다 (details/summary, 스크립트 없음) */
.law-talk { position: relative; display: inline-block; }
.law-talk summary { list-style: none; cursor: pointer; display: inline-block; outline: none; }
.law-talk summary::-webkit-details-marker { display: none; }
.law-talk summary:focus-visible img { outline: 3px solid var(--gold); outline-offset: 4px; border-radius: 50%; }
.law-talk .tap-hint { display: block; font-size: .74rem; font-weight: 600; color: var(--muted); margin-top: 2px; }
.law-talk[open] .tap-hint { visibility: hidden; }
.law-bubble {
  position: absolute; left: calc(100% + 14px); top: 8px; width: 300px; z-index: 60;
  background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px;
  box-shadow: 0 10px 28px rgba(31,42,68,.14); text-align: left; word-break: keep-all;
  animation: pop .22s cubic-bezier(.2,1.4,.4,1) both;
}
.law-bubble::before {   /* 로우 쪽을 가리키는 꼬리 */
  content: ""; position: absolute; left: -8px; top: 34px; width: 14px; height: 14px; background: #fff;
  border-left: 1px solid var(--line); border-bottom: 1px solid var(--line); transform: rotate(45deg);
}
.law-bubble b.title { display: block; font-size: 1.05rem; font-weight: 800; color: var(--navy); margin-bottom: 6px; }
.law-bubble b.title em { font-style: normal; color: var(--gold-ink); }
.law-bubble p { margin: 0; font-size: .88rem; line-height: 1.6; color: #3a3a3a; }
/* Streamlit 본문의 줄바꿈 설정(overflow-wrap: anywhere)이 덮어써 단어 중간에서 끊기는 것을 막는다 */
.law-bubble, .law-bubble p, .landing-brand .hint { word-break: keep-all !important; overflow-wrap: normal !important; }
/* 말풍선 키워드 — 생활 영역마다 다른 색 */
.law-bubble .kw { font-weight: 600; }
.law-bubble .kw-home { color: #2C5DA8; } .law-bubble .kw-job { color: #2F7A55; }
.law-bubble .kw-shop { color: #C2571A; } .law-bubble .kw-money { color: #9A7212; }
@keyframes pop { from { opacity: 0; transform: scale(.85) translateY(4px); } to { opacity: 1; transform: none; } }
@media (max-width: 760px) {
  .law-bubble { position: relative; left: auto; top: auto; width: auto; max-width: 320px; margin: 10px auto 0; }
  .law-bubble::before { left: calc(50% - 7px); top: -8px; transform: rotate(135deg); }
}
</style>""", unsafe_allow_html=True)

        st.markdown(f"<div class='landing-brand'>{greeting_mascot()}"
                    f"<div class='name'>{SERVICE_NAME}</div><div class='slogan'>{SLOGAN}</div>"
                    f"<div class='hint'>있었던 일을 그대로 들려주세요. 어려운 법 이야기는 로우가 대신 읽고 알려 드릴게요.</div></div>", unsafe_allow_html=True)

        # 가운데 검색창 — 법률 이름이면 그 법률을, 아니면 상황으로 보고 맞는 법을 찾는다
        with st.container(key="main_search"):
            with st.form("main_search_form", border=False):
                box, go = st.columns([5, 1], vertical_alignment="bottom")
                query = box.text_input("검색", placeholder="궁금한 상황이나 법률 이름  예) 알바하다가 다쳤어요", key="main_query",
                                       label_visibility="collapsed")
                searched = go.form_submit_button("검색", type="primary", width="stretch")

        # 작은 버튼 3개 — 눌러야 해당 패널이 열린다
        # 글자 크기만큼만 차지하는 작은 버튼을 가운데로 모은다
        with st.container(key="small_buttons", horizontal=True, horizontal_alignment="center"):
            panel = st.session_state.panel
            for name, label in (("laws", "📚 법률 고르기"), ("popular", "⭐ 자주 찾는 법"), ("situation", "🔎 상황으로 법 찾기")):
                st.button(label, key=f"panel_{name}", width="content", on_click=toggle_panel, args=(name,),
                          type="primary" if panel == name else "secondary")

        if searched and query.strip():
            q = query.strip()
            named = [i for i in items if q.replace(" ", "") in i["label"].replace(" ", "")
                     or (i.get("abbr") and q.replace(" ", "") in i["abbr"])]
            st.session_state.panel = None
            st.session_state.complex = None
            if named:
                st.session_state.search_result = (q, [{"item": i, "reason": ""} for i in named[:6]], "name")
            else:
                st.session_state.search_result = None
                loading = input_loading("main_query")
                try:
                    # 여러 법이 얽힌 긴 상황이면 쟁점별로 나눠 바로 답한다 (service/complex.py) — 아니면 법률 카드
                    with st.spinner("로우가 상황을 살펴보는 중…"):
                        plan = decompose(rt, q, items)
                    if plan:
                        result, summary = run_with_status(
                            f"쟁점 {len(plan['issues'])}개를 하나씩 살펴보고 있어요",
                            lambda step: answer_complex(rt, q, plan, on_step=step))
                        if result:
                            st.session_state.complex = {
                                "q": q, "assumptions": plan["assumptions"],
                                "issues": [{"title": i["title"], "laws": [l["item_id"] for l in i["laws"]]}
                                           for i in plan["issues"]],
                                "message": {"role": "assistant", "content": result.answer, "cited": result.cited,
                                            "warnings": result.warnings, "notices": result.notices,
                                            "summary": summary}}
                    else:
                        with st.spinner("로우가 상황에 맞는 법을 찾는 중…"):
                            st.session_state.search_result = (q, find_laws(rt, q, items_by_id), "situation")
                except Exception as error:
                    log.exception("search")
                    st.error(friendly_error(error))
                loading.empty()

        panel = st.session_state.panel
        if panel == "laws":
            with st.container(border=True):
                st.markdown("**📚 법률 고르기**")
                cat = st.pills("분야", categories, key="landing_category", label_visibility="collapsed")
                words = st.text_input("법률 이름", key="landing_law_search", placeholder="🔍 법률 이름으로 찾기",
                                      label_visibility="collapsed").strip()
                options = [i["item_id"] for i in items
                           if cat in (None, i["category"]) and (not words or words in i["label"])]
                with st.container(height=300, border=False):
                    if options:
                        st.radio("법률", options, key="item_id", index=None, label_visibility="collapsed",
                                 format_func=lambda i: items_by_id[i]["label"])
                    else:
                        st.caption("찾는 법률이 없어요.")
        elif panel == "popular":
            with st.container(border=True):
                st.markdown("**⭐ 자주 찾는 법**")
                render_law_cards([{"item": items_by_label[n], "reason": items_by_label[n]["easy"]   # 쉬운 설명
                                   or items_by_label[n]["purpose"].split(")", 1)[-1].strip()[:60] + "…"}
                                  for n in POPULAR_LAWS])
        elif panel == "situation":
            with st.container(border=True):
                render_find_laws()
        elif st.session_state.get("complex"):
            render_complex(st.session_state.complex)
        elif st.session_state.get("search_result"):
            q, results, kind = st.session_state.search_result
            st.caption(f"‘{q}’ " + ("— 이름이 맞는 법률" if kind == "name" else "— 상황에 맞는 법"))
            if results:
                render_law_cards(results, question=q if kind == "situation" else None)
            else:
                note("thinking", "꼭 맞는 법을 찾지 못했어요. 상황을 조금 더 구체적으로 적어 주세요.", 72)

        # 처음엔 로우 ~ 작은 버튼 덩어리(약 470px)를 세로 가운데에, 패널 · 결과가 열리면 위로 올린다
        active = bool(st.session_state.panel or st.session_state.get("search_result")
                      or st.session_state.get("complex"))
        top = "4.5rem" if active else "max(4.5rem, calc((100vh - 150px - 470px) / 2))"      # 4.5rem — 상단 막대 아래부터
        # 첫 화면을 처음 그릴 때는 애니메이션 없이 바로 가운데에 — 이후 버튼으로 오르내릴 때만 부드럽게 움직인다
        motion = "transition: padding-top .45s cubic-bezier(.2, .8, .2, 1);" if st.session_state.get("landing_drawn") else ""
        st.session_state.landing_drawn = True
        st.markdown(f"<style>.block-container {{ padding-top: {top}; {motion} }}</style>", unsafe_allow_html=True)

        st.markdown(f"<div class='landing-footer'><div class='footer-brand'>{mascot_img('scale', 40)}<span class='footer-logo'>{SERVICE_NAME}</span></div><div>{esc(LEGAL)}</div>"
                    f"<div class='sources'>출처: 국가법령정보센터 Open API · 한국어 위키백과(CC BY-SA 4.0) · "
                    f"법제처 「2024 법령해석 사례집」(공공누리 제4유형)</div></div>", unsafe_allow_html=True)
    st.stop()

# ── 법률을 고른 뒤: 사건 기록부 + 탭 ───────────────────────────────────────────────

# 법률 화면에 처음 들어오면 맨 위로 — 첫 화면에서 검색 결과를 보려고 내린 스크롤이 그대로 남아 윗부분이 잘려 보인다
if st.session_state.get("shown_item") != item["item_id"]:
    st.session_state.shown_item = item["item_id"]
    with st.container(key="scroll_top"):
        st.iframe("<script>const m = window.parent.document.querySelector('[data-testid=\"stMain\"]');"
                  "if (m) m.scrollTo({top: 0});</script>", height=1)      # 고정 문자열만 — 사용자 입력은 넣지 않는다

date = item["effective_date"]
st.markdown(f"""
<div class='paper-card case-head'>
  <div class='case-label'>사건 기록부 · {esc(item['category'])}</div>
  <h1>{esc(item['label'])}</h1>
  <span class='badge'>소관 {esc(item['ministry'])}</span>
  <span class='badge'>{date[:4]}.{date[4:6]}.{date[6:]} 시행</span>
  <a href='{esc(item['url'])}' target='_blank'>법령 원문 ↗</a>
</div>""", unsafe_allow_html=True)
for notice in notices_for(item)[1:]:          # 금융 · 건강 항목은 맨 위에 한 번 더 (F2012)
    st.info(notice)

tab_chat, tab_fact, tab_explain, tab_find = st.tabs(["💬 물어보기", "⚖️ 사실일까?", "📜 조문 쉽게 읽기", "🔎 법 찾기"])

# 💬 물어보기 — 법률별로 대화를 따로 둔다 (F2009)
with tab_chat:
    history = st.session_state.histories.setdefault(item["item_id"], [])
    pending_question = None
    # 상황 검색 → "이 법으로 물어보기" 로 들어왔으면 그때 적은 문장을 바로 물어본다 (한 번만)
    auto = st.session_state.get("auto_question")
    if auto and auto[0] == item["item_id"]:
        st.session_state.auto_question = None
        pending_question = auto[1]
    if not history and not pending_question:      # 바로 물어볼 질문이 있으면 예시 질문 상자는 건너뛴다
        with st.container(border=True):
            note("walking", f"<b>{esc(item['label'])}</b>에 대해 무엇이든 물어보세요.<br>"
                            "<span class='small-note'>이렇게 물어봐도 좋아요</span>", cls="bob")
            for n, sample in enumerate(SAMPLE_QUESTIONS.get(item["name"], GENERIC_QUESTIONS)):
                if st.button(f"💬 {sample}", key=f"sample_{n}"):
                    pending_question = sample

    thread = st.container()          # 대화 자리 — 입력창보다 위
    last_assistant = max((n for n, m in enumerate(history) if m["role"] == "assistant"), default=-1)
    for n, message in enumerate(history):
        with thread.chat_message(message["role"], avatar=mascot("avatar") if message["role"] == "assistant" else "🙋"):
            if message["role"] == "assistant":
                render_answer(message, latest=n == last_assistant)
            else:
                st.markdown(message["content"])

    question = st.chat_input(f"{item['label']}에 대해 물어보세요", key="chat_input") or pending_question
    if question:
        history.append({"role": "user", "content": question})
        with thread.chat_message("user", avatar="🙋"):
            st.markdown(question)
        with thread.chat_message("assistant", avatar=mascot("avatar")):
            result, summary = run_with_status("로우가 법전을 넘기고 있어요",
                                              lambda step: ask_or_offline(rt, item, question, history[:-1], on_step=step))
            if result:
                message = {"role": "assistant", "content": result.answer, "cited": result.cited,
                           "warnings": result.warnings, "notices": result.notices, "summary": summary}
                render_answer(message, latest=True, show_summary=False)
                history.append(message)
            else:
                history.pop()           # 실패한 질문은 기록에서 뺀다

# ⚖️ 사실일까? — 법률 상식 팩트체크 (F2010 ①)
with tab_fact:
    note("gavel", "<b>들은 이야기가 법적으로 맞는지</b> 로우가 근거를 찾아 판정해 드려요.")
    with st.form("factcheck_form", border=False):
        claim = st.text_area("확인할 문장", height=80, placeholder="예) 전입신고를 한 당일부터 대항력이 생긴다")
        go = st.form_submit_button("⚖️ 판정하기", type="primary")
    if go and claim.strip():
        outcome, summary = run_with_status("로우가 근거를 살펴보고 있어요",
                                           lambda step: factcheck(rt, item, claim.strip(), on_step=step))
        if outcome:
            st.session_state.factchecks[item["item_id"]] = {"claim": claim.strip(), "verdict": outcome[0],
                                                            "result": outcome[1], "summary": summary}
    saved = st.session_state.factchecks.get(item["item_id"])
    if saved:
        verdict, result = saved["verdict"], saved["result"]
        pose = "thinking" if verdict == "확인 불가" else "gavel"
        st.markdown(f"<div class='paper-card verdict'>{mascot_img(pose, 100)}<div>"
                    f"<div class='claim'>“{esc(saved['claim'])}”</div>"
                    f"<span class='stamp {STAMP_CLASS[verdict]}'>{verdict}</span></div></div>",
                    unsafe_allow_html=True)
        body = result.answer.split("\n", 1)[-1] if result.answer.startswith("판정") else result.answer
        render_answer({"content": body.strip(), "cited": result.cited, "warnings": result.warnings,
                       "notices": result.notices, "summary": saved["summary"]}, latest=True,
                      show_summary=not go)

# 📜 조문 쉽게 읽기 — 조문 쉬운 말 풀이 (F2010 ②)
with tab_explain:
    note("desk", "<b>어려운 조문을 하나 골라 주세요.</b> 쉬운 말로 풀고, 원문과 나란히 보여 드려요.")
    try:
        articles = article_choices(item)
    except Exception as error:
        log.exception("articles")
        articles = []
        st.error(friendly_error(error))
    if articles:
        picked = st.selectbox("조문", range(len(articles)), index=None, key=f"article_{item['item_id']}",
                              placeholder="조문 제목으로 찾기",
                              format_func=lambda n: f"{articles[n]['source']} {articles[n]['article']}"
                                                    f"({articles[n]['title']})")
        if st.button("📜 쉽게 풀어 줘", type="primary", disabled=picked is None):
            article = articles[picked]
            result, summary = run_with_status("로우가 조문을 읽고 있어요",
                                              lambda step: explain(rt, item, article, on_step=step))
            if result:
                st.session_state.explains[item["item_id"]] = {"article": article, "result": result}
    saved = st.session_state.explains.get(item["item_id"])
    if saved:
        article, result = saved["article"], saved["result"]
        easy, original = st.columns(2)
        with easy:
            st.markdown("#### 🟡 쉽게 말하면")
            render_answer({"content": result.answer, "cited": result.cited,
                           "warnings": result.warnings, "notices": result.notices})
        with original:
            st.markdown(f"#### 📜 원문")
            st.markdown(f"<b>{esc(article['source'])} {esc(article['article'])}({esc(article['title'])})</b>"
                        f"<div class='parchment'>{esc(article['text'])}</div>"
                        f"<p><a href='{esc(article['url'])}' target='_blank'>법령 원문 보기 ↗</a></p>",
                        unsafe_allow_html=True)

# 🔎 법 찾기 (F2011)
with tab_find:
    render_find_laws()
