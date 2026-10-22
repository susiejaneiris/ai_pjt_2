"""RAG 2 — 외부 문서 수집 (F2003 · F2004 · NF2002). 도메인에 묶인 규칙이라 데이터 준비 영역에 둡니다.

    질문 ─► 프롬프트 1 검색어 추출 ─► 새 검색어만 ─► 후보 모으기 ─────────────► 프롬프트 2 선별 ─► 본문 수집
                                    (collected.json)   조문 목록 · 판례 · 법령해석례   (제목 · 요약만)
                                                       (PDF 변환본) · 위키

선택한 법률 자체를 다룬 문서(목적 · 정의 조문, 같은 제목의 위키 문서)는
선별과 무관하게 항목별로 한 번 항상 수집합니다. (F2004)

수집한 문서(raw doc)는 store.chunking 으로 넘겨 청킹 · 색인합니다.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import requests

from config import COLLECTED_JSON, FALLBACK_DIR
from prep import casebook, easylaw_qa, kids_guide, law_api, wiki_api
from rag.llm import parse_json
from rag.prompts import QUERY_PROMPT, SELECT_PROMPT

BASE_ARTICLES = ("제1조", "제2조")       # 목적 · 정의 — 부분 항목(민법)에서도 항상 넣는 조문
# 항목 자체 문서의 구성이 바뀌면 올린다 → 이미 수집한 항목도 새 구성으로 다시 수집
#   1: 제1조 · 제2조 + 같은 제목 위키
#   2: 법률 조문 전부 + 같은 제목 위키 (평가에서 조문 제목만 보고 고르면 정답 조문을 놓쳐 검색 적중률 81%)
BASE_VERSION = 2


# ── 문서 단위 만들기 (출처별) ──────────────────────────────────────────────────────

def article_doc(item: dict, art: dict, query: str) -> dict:
    title = f"{art['source']} {art['article']}({art['title']})" if art["title"] else f"{art['source']} {art['article']}"
    return {
        "item_id": item["item_id"], "item_name": item["label"],
        "doc_id": f"article-{art['mst']}-{art['article']}", "source_type": "article",
        "title": title, "header": title, "url": art["url"], "date": art["effective_date"],
        "query": query, "text": art["text"],
    }


def prec_docs(item: dict, prec: dict, query: str) -> list[dict]:
    """판시사항 · 판결요지를 따로 문서로 만든다."""
    name = f"{prec['court']} {prec['case_no']}".strip()
    docs = []
    for part, label in (("holding", "판시사항"), ("summary", "판결요지")):
        text = prec[part]
        if part == "holding" and prec["ref_articles"]:
            text += f"\n\n참조조문: {prec['ref_articles']}"
        if not text.strip():
            continue
        docs.append({
            "item_id": item["item_id"], "item_name": item["label"],
            "doc_id": f"prec-{prec['prec_id']}-{part}", "source_type": "prec",
            "title": f"{name} {label}", "header": f"{name} ({prec['date']}) {label}",
            "url": prec["url"], "date": prec["date"].replace(".", ""), "query": query, "text": text,
        })
    return docs


def qa_doc(item: dict, qa: dict, query: str) -> dict:
    """생활법령 Q&A — 일상어 질문과 조문을 잇는 다리 역할.
    백문백답(질문 · 답 · 관련 법령)과 어린이 생활법령 PDF(상황 · 설명, URL 대신 책 · 쪽)를 한 문서로."""
    if qa.get("kind") == "kids":
        story = f"상황: {qa['story']}\n\n" if qa["story"] else ""
        text = f"주제: {qa['subject']}\n\n{story}설명: {qa['answer']}"
        return {
            "item_id": item["item_id"], "item_name": item["label"],
            "doc_id": qa["qa_id"], "source_type": "qa",
            "title": f"어린이 생활법령: {qa['subject']}", "header": f"어린이 생활법령 — {qa['subject']} ({qa['citation']})",
            "url": "", "citation": qa["citation"], "date": "201212", "query": query, "text": text,
        }
    laws = "\n".join(qa.get("laws", []))
    text = f"질문: {qa['question']}\n\n답: {qa['answer']}"
    if laws:
        text += f"\n\n관련 법령: {laws}"
    return {
        "item_id": item["item_id"], "item_name": item["label"],
        "doc_id": qa["qa_id"], "source_type": "qa",
        "title": f"백문백답: {qa['subject']}", "header": f"생활법령 백문백답 — {qa['subject']}",
        "url": qa["url"], "citation": f"법제처 찾기쉬운 생활법령정보 백문백답 ({qa['service_date']} 작성)",
        "date": qa["service_date"].replace("-", ""), "query": query, "text": text,
    }


def expc_docs(item: dict, case: dict, query: str) -> list[dict]:
    """법령해석례(PDF) — '질의요지 + 회답'(핵심)과 '이유'(해설)를 따로 문서로 만든다.
    원문 출처는 URL 대신 파일명과 쪽 (명세 F2004)."""
    name = f"법령해석례 {case['case_no']}"
    common = {
        "item_id": item["item_id"], "item_name": item["label"], "source_type": "expc",
        "url": "", "citation": case["source"], "date": "", "query": query,
    }
    return [
        {**common, "doc_id": f"{case['doc_id']}-qa", "title": f"{name} 질의·회답",
         "header": f"{name} ({case['source']}) 질의요지·회답",
         "text": f"질의 제목: {case['title']}\n\n질의요지\n{case['question']}\n\n회답\n{case['answer']}"},
        {**common, "doc_id": f"{case['doc_id']}-reason", "title": f"{name} 이유",
         "header": f"{name} ({case['source']}) 이유", "text": case["reason"]},
    ]


def wiki_doc(item: dict, page: dict, query: str) -> dict:
    return {
        "item_id": item["item_id"], "item_name": item["label"],
        "doc_id": f"wiki-{page['page_id']}", "source_type": "wiki",
        "title": page["title"], "header": f"위키백과: {page['title']}",
        "url": page["url"], "date": page["touched"], "query": query, "text": page["text"],
    }


# ── 법률 본문 (항목에 연결된 문서) ──────────────────────────────────────────────────

@lru_cache(maxsize=64)
def law_articles(item_json: str) -> tuple[dict, ...]:
    """항목 법률의 조문 + 시행령 조문. 부분 항목(민법)은 범위 안 조문만. 같은 법은 한 번만 받는다."""
    item = json.loads(item_json)
    articles = law_api.fetch_articles(item["mst"])
    if item.get("article_range"):
        start, end = map(int, item["article_range"].split("-"))
        base = [a for a in articles if a["article"] in BASE_ARTICLES]
        return tuple(base + [a for a in articles if start <= a["number"] <= end])

    decree_name = f"{item['name']} 시행령"
    decree = next((l for l in law_api.search_laws(decree_name) if l["name"] == decree_name), None)
    if decree:
        articles += law_api.fetch_articles(decree["mst"])
    return tuple(articles)


def get_law_articles(item: dict) -> list[dict]:
    return list(law_articles(json.dumps(item, ensure_ascii=False, sort_keys=True)))


def base_documents(item: dict) -> list[dict]:
    """선택한 법률 자체를 다룬 문서 — 선별 · 길이 규칙보다 우선해 항상 색인 (F2004).

    법률 조문은 그 항목 자체이므로 선별하지 않고 전부 넣는다. 조문 제목만 보고 고르게 하면
    "이사를 가야 해요" → 임차권등기명령 처럼 말이 다른 정답 조문을 놓친다 (평가 v0: 검색 적중률 81%).
    시행령은 양이 많아 프롬프트 2 의 선별 대상으로 남긴다. 부분 항목(민법)은 범위 안 조문만.
    """
    docs = [article_doc(item, a, "법률 자체")
            for a in get_law_articles(item) if a["source"] == item["name"]]
    if not item.get("article_range"):
        page = wiki_api.fetch_page(item["name"])
        if page:
            docs.append(wiki_doc(item, page, "법률 자체"))
    return docs


# ── 프롬프트 1 · 2 ────────────────────────────────────────────────────────────────

def extract_queries(item: dict, question: str, llm) -> tuple[list[str], bool]:
    """프롬프트 1 — (검색어, 범위 안인지). 파싱에 실패하면 질문 자체로 검색하고 범위 안으로 본다."""
    prompt = QUERY_PROMPT.format(item_name=item["label"], item_purpose=item.get("purpose", ""), question=question)
    parsed = parse_json(llm.invoke(prompt).content, default={})
    if isinstance(parsed, list):                      # 예전 형식(배열만)으로 답해도 받아 준다
        parsed = {"queries": parsed}
    queries = [q.strip() for q in parsed.get("queries", []) if isinstance(q, str) and q.strip()]
    in_scope = parsed.get("in_scope", True) is not False
    return queries[:4] or [question], in_scope


def gather_candidates(item: dict, queries: list[str], settings: dict, skip_doc_ids: set[str]) -> dict:
    """검색어로 후보를 모은다. 이미 색인한 문서는 후보에서 뺀다 (외부 호출 절약)."""
    limits = settings["candidate_limit"]
    # 법률 조문은 항목 자체 문서로 이미 색인 → 후보는 아직 색인하지 않은 조문(시행령)
    articles = [a for a in get_law_articles(item)
                if f"article-{a['mst']}-{a['article']}" not in skip_doc_ids][:300]

    precs, wikis = {}, {}
    for query in queries:
        for prec in law_api.search_precs(query, limit=limits["prec"]):
            if f"prec-{prec['prec_id']}-holding" not in skip_doc_ids:
                precs.setdefault(prec["prec_id"], {**prec, "query": query})
        for hit in wiki_api.search(query, limit=limits["wiki"]):
            if f"wiki-{hit['page_id']}" not in skip_doc_ids:
                wikis.setdefault(hit["page_id"], {**hit, "query": query})
    # 대법원 판례를 앞에, 같은 법원 안에서는 최신 선고일을 앞에 둔다
    prec_list = sorted(precs.values(),
                       key=lambda p: (p["court"] != "대법원", -int(p["date"].replace(".", "") or 0)))
    # 법령해석례는 로컬 PDF 변환본에서 찾는다 (외부 호출 없음)
    expcs = [{**c, "query": queries[0]} for c in casebook.search_cases(item, queries, limits["expc"])
             if f"{c['doc_id']}-qa" not in skip_doc_ids]
    # 생활법령 Q&A 도 로컬 변환본에서 — 백문백답(data/qa.json) + 어린이 생활법령(data/kids_guide.json)
    qa_rows = easylaw_qa.load_qa() + kids_guide.load_guide()
    qas = [{**q, "query": queries[0]} for q in easylaw_qa.search_qa(item, queries, limits.get("qa", 8), qa_rows)
           if q["qa_id"] not in skip_doc_ids]
    return {"article": articles, "prec": prec_list, "expc": expcs, "qa": qas, "wiki": list(wikis.values())}


def format_candidates(candidates: dict) -> dict:
    def numbered(lines):
        return "\n".join(f"{n}. {line}" for n, line in enumerate(lines, start=1)) or "(없음)"
    return {
        "article_list": numbered(f"{a['source']} {a['article']}({a['title']})" for a in candidates["article"]),
        "prec_list": numbered(f"{p['court']} {p['case_no']} ({p['date']}) {p['case_name'][:120]}" for p in candidates["prec"]),
        "expc_list": numbered(f"{c['case_no']} {c['title'][:150]}" for c in candidates["expc"]),
        "qa_list": numbered(f"[{q['subject']}] {easylaw_qa.row_question(q)[:120]}" for q in candidates["qa"]),
        "wiki_list": numbered(f"{w['title']} — {w['snippet'][:100]}" for w in candidates["wiki"]),
    }


def select_candidates(item: dict, question: str, candidates: dict, settings: dict, llm) -> dict:
    """프롬프트 2 — 번호로 고르게 하고, 범위를 벗어난 번호는 버린다."""
    limits = settings["select_limit"]
    prompt = SELECT_PROMPT.format(
        item_name=item["label"], question=question,
        max_article=limits["article"], max_prec=limits["prec"], max_expc=limits["expc"],
        max_qa=limits.get("qa", 2), max_wiki=limits["wiki"],
        **format_candidates(candidates),
    )
    picked = parse_json(llm.invoke(prompt).content, default={})
    selected = {}
    for kind in ("article", "prec", "expc", "qa", "wiki"):
        numbers = [n for n in picked.get(kind, []) if isinstance(n, int) and 1 <= n <= len(candidates[kind])]
        selected[kind] = [candidates[kind][n - 1] for n in dict.fromkeys(numbers)][:limits[kind]]
    return selected


# ── 수집 캐시 (NF2002) ─────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if COLLECTED_JSON.exists():
        with open(COLLECTED_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    with open(COLLECTED_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def collected_doc_ids(entry: dict) -> set[str]:
    ids = set(entry.get("base", []))
    for doc_ids in entry.get("queries", {}).values():
        ids.update(doc_ids)
    return ids


# ── 전체 흐름 ─────────────────────────────────────────────────────────────────────

@dataclass
class CollectReport:
    """수집 결과. 화면 진행 표시와 검증(명세 4.2) 캡처에 쓴다."""
    queries: list[str] = field(default_factory=list)
    new_queries: list[str] = field(default_factory=list)
    candidate_counts: dict = field(default_factory=dict)
    selected: list[str] = field(default_factory=list)     # 색인한 문서 제목
    dropped: list[str] = field(default_factory=list)      # 후보였지만 버린 문서 제목
    raw_docs: list[dict] = field(default_factory=list)
    reused_docs: int = 0                                  # 이미 색인돼 있어 다시 수집하지 않은 문서 수
    fallback: bool = False                                # 외부 호출이 막혀 저장된 문서 묶음을 썼는지
    in_scope: bool = True                                 # 프롬프트 1 이 본 질문 범위 — False 면 수집 · 생성을 건너뛴다


EXTERNAL_ERRORS = (requests.RequestException, RuntimeError)     # 네트워크 · 한도 초과 · 인증 실패


def collect_external(item: dict, question: str, report: CollectReport, settings: dict, llm,
                     skip_doc_ids: set[str], on_step) -> list[dict]:
    """외부 출처에서 후보를 모으고 선별해 본문을 받는다."""
    on_step(f"외부 문서 검색 중: {', '.join(report.new_queries)}")
    candidates = gather_candidates(item, report.new_queries, settings, skip_doc_ids)
    report.candidate_counts = {k: len(v) for k, v in candidates.items()}

    on_step(f"후보 조문 {len(candidates['article'])} · 판례 {len(candidates['prec'])} · "
            f"법령해석례 {len(candidates['expc'])} · 생활법령 Q&A {len(candidates['qa'])} · "
            f"위키 {len(candidates['wiki'])}건 중 선별하는 중")
    selected = select_candidates(item, question, candidates, settings, llm) if any(candidates.values()) \
        else {"article": [], "prec": [], "expc": [], "qa": [], "wiki": []}

    on_step("선별한 문서의 본문을 받는 중")
    docs = [article_doc(item, a, report.new_queries[0]) for a in selected["article"]]
    for prec in selected["prec"]:
        body = law_api.fetch_prec(prec["prec_id"])
        if body:
            docs += prec_docs(item, body, prec["query"])
    docs += [qa_doc(item, q, q["query"]) for q in selected["qa"]]
    for case in selected["expc"]:
        docs += expc_docs(item, case, case["query"])
    for hit in selected["wiki"]:
        page = wiki_api.fetch_page(hit["title"])
        if page:
            docs.append(wiki_doc(item, page, hit["query"]))

    report.dropped = (
        [f"{p['court']} {p['case_no']}" for p in candidates["prec"] if p not in selected["prec"]]
        + [f"법령해석례 {c['case_no']}" for c in candidates["expc"] if c not in selected["expc"]]
        + [f"생활법령 Q&A {q['subject']}" for q in candidates["qa"] if q not in selected["qa"]]
        + [w["title"] for w in candidates["wiki"] if w not in selected["wiki"]]
    )
    return docs


def question_key(question: str) -> str:
    return " ".join(question.split())


def collect(item: dict, question: str, settings: dict, llm, on_step=lambda message: None) -> CollectReport:
    report = CollectReport()
    cache = load_cache()
    entry = cache.setdefault(item["item_id"], {"base": [], "queries": {}})
    asked = entry.setdefault("questions", {})            # 질문 → 그때 뽑은 검색어

    # 프롬프트 1 은 같은 질문에도 검색어를 조금씩 다르게 뽑는다 (실측).
    # 검색어만 기억하면 같은 질문이 또 수집을 일으키므로, 질문도 기억해 검색어를 그대로 다시 쓴다 (NF2002).
    cached = asked.get(question_key(question))
    if isinstance(cached, dict):                      # 범위 판단까지 저장된 질문 — 같은 질문은 늘 같은 결과
        on_step("전에 받은 질문이라 모아 둔 문서를 다시 써요")
        report.queries, report.in_scope = cached["queries"], cached["in_scope"]
    else:                                             # 처음 받은 질문 (또는 범위 판단 없이 저장된 예전 기록)
        on_step("질문을 살펴보고 검색어를 정리하는 중")
        report.queries, report.in_scope = extract_queries(item, question, llm)
    if not report.in_scope:
        # 고른 법률이 다루지 않는 질문 — 외부 문서를 모으지 않는다 (엉뚱한 문서가 이 법률 칸에 쌓이는 것도 막는다)
        on_step("이 법률이 다루는 질문이 아니라 문서를 모으지 않아요")
        asked[question_key(question)] = {"queries": report.queries, "in_scope": False}
        save_cache(cache)
        return report
    report.new_queries = [q for q in report.queries if q not in entry["queries"]]
    report.reused_docs = len(collected_doc_ids(entry))

    try:
        if not entry["base"] or entry.get("base_version") != BASE_VERSION:
            on_step("법률 조문 전체와 같은 제목의 위키 문서를 수집하는 중")
            base = base_documents(item)
            report.raw_docs += base
            entry["base"] = [d["doc_id"] for d in base]
            entry["base_version"] = BASE_VERSION
        if report.new_queries:
            docs = collect_external(item, question, report, settings, llm, collected_doc_ids(entry), on_step)
            report.raw_docs += docs
            # 이번 검색어들로 수집을 마쳤다고 기록한다. 다음에 같은 검색어가 나오면 건너뛴다 (NF2002).
            for q in report.new_queries:
                entry["queries"][q] = [d["doc_id"] for d in docs]
        asked[question_key(question)] = {"queries": report.queries, "in_scope": True}
    except EXTERNAL_ERRORS:
        # 외부 호출이 막힌 환경 — 미리 받아 둔 문서 묶음으로 수집을 대신한다 (명세 F2004).
        # 검색어는 '수집함'으로 기록하지 않는다 → 연결이 돌아오면 다시 수집한다.
        on_step("외부 문서를 받지 못해 저장된 문서 묶음을 사용하는 중")
        done = collected_doc_ids(entry) | {d["doc_id"] for d in report.raw_docs}
        bundle = [d for d in load_fallback(item) if d["doc_id"] not in done]
        report.raw_docs += bundle
        report.fallback = True

    report.selected = list(dict.fromkeys(d["title"] for d in report.raw_docs))
    save_cache(cache)
    return report


def load_fallback(item: dict) -> list[dict]:
    """외부 호출이 막힌 환경에서 data/fallback/{item_id}.json 의 문서 묶음을 읽는다 (명세 F2004 허용)."""
    path = FALLBACK_DIR / f"{item['item_id']}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def today() -> str:
    return date.today().isoformat()
