"""쟁점 나누기 모드 — 여러 법이 얽힌 복합 질문을 쟁점별로 나눠 근거를 찾고 답한다.

    "미성년자 A가 … 명의를 도용해 … 이중계약 … 천재지변으로 붕괴 … D 에게 피해" 같은 질문은
    법률 하나 · 근거 8개로는 덮이지 않는다 (지금 구조는 고른 법률 하나 안에서만 찾는다).

    1. 쟁점 분해 (LLM 1회) — 쟁점마다 법률 1~2개 · 검색어, 결론이 갈리는 사실은 '가정'
    2. 쟁점별 근거 — 그 법률의 조문을 색인(처음 한 번), 조문 목록에서 정답 조문 지목(검색 개선 1) + 검색
       쟁점끼리는 동시에 처리한다 (색인은 저장소에 쓰므로 먼저 차례로)
    3. 쟁점별 답변 (LLM 1회) — 쟁점 → 적용 규정 → 상황 적용(가정은 경우를 나눠) → 정리, 끝에 전문가 상담 안내

    단일 쟁점이면 None — 화면은 지금처럼 법률 카드를 보여 준다.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from prep.collect import BASE_VERSION, article_doc_ids, base_documents, load_cache, pick_articles, save_cache
from prep.disclaimer import LEGAL
from rag.citations import cited_numbers, cited_sources, citation_warnings
from rag.llm import parse_json
from rag.prompts import CITE_RETRY, COMPLEX_PROMPT, DECOMPOSE_PROMPT, NOT_FOUND
from rag.retriever import format_sources, retrieve_sources
from service.chat import Result, index_documents
from service.runtime import Runtime

MIN_CHARS = 40            # 이보다 짧은 상황은 쟁점이 여럿일 가능성이 낮다 → 분해 호출을 아낀다
MAX_ISSUES = 5
PER_ISSUE_K = 4           # 쟁점 · 법률 하나에서 검색으로 더하는 청크 수 (지목한 조문은 따로)
MAX_SOURCES = 22


def decompose(rt: Runtime, question: str, items: list[dict]) -> dict | None:
    """{"issues": [{title, laws, queries}], "assumptions": [...]} — 쟁점이 2개 미만이면 None."""
    if len(question) < MIN_CHARS:
        return None
    by_label = {i["label"]: i for i in items}
    catalog = " · ".join(i["label"] for i in items)          # 이름만 — 짧을수록 빠르다
    parsed = parse_json(rt.llm.invoke(DECOMPOSE_PROMPT.format(laws=catalog, question=question)).content, default={})
    issues = []
    for entry in (parsed.get("issues", []) if isinstance(parsed, dict) else [])[:MAX_ISSUES]:
        if not isinstance(entry, dict):
            continue
        names = entry.get("laws") or [entry.get("law", "")]
        laws = [by_label[n.strip()] for n in names if isinstance(n, str) and n.strip() in by_label][:2]
        if not laws:
            continue                                      # 목록에 없는 법 이름 — 지어낸 이름은 버린다
        queries = [q.strip() for q in entry.get("queries", []) if isinstance(q, str) and q.strip()][:3]
        issues.append({"title": str(entry.get("title", "")).strip() or laws[0]["label"], "laws": laws,
                       "queries": queries})
    if len(issues) < 2:
        return None
    assumptions = [a.strip() for a in parsed.get("assumptions", []) if isinstance(a, str) and a.strip()][:4]
    return {"issues": issues, "assumptions": assumptions}


def ensure_base(rt: Runtime, item: dict) -> None:
    """그 법률의 조문 전체가 색인돼 있게 — 질의응답의 '항목 자체 문서'와 같은 기록을 쓴다 (처음 한 번만)."""
    cache = load_cache()
    entry = cache.setdefault(item["item_id"], {"base": [], "queries": {}})
    if entry.get("base") and entry.get("base_version") == BASE_VERSION:
        return
    base = base_documents(item)
    index_documents(rt, base)
    entry["base"], entry["base_version"] = [d["doc_id"] for d in base], BASE_VERSION
    save_cache(cache)


def issue_sources(rt: Runtime, issue: dict, question: str) -> tuple[list[dict], list[dict]]:
    """쟁점 하나 — 관련 법률(1~2개)마다 조문 지목 + 검색. (지목한 조문, 검색으로 찾은 나머지)."""
    ask = f"{issue['title']} — {question}"
    settings = {**rt.settings, "top_k": PER_ISSUE_K}
    pinned, rest = [], []
    for item in issue["laws"]:
        doc_ids = article_doc_ids(item, pick_articles(item, ask, rt.llm))   # 조문 목록에서 이 쟁점에 답할 조문 지목
        sources = retrieve_sources(rt.meta, rt.docs, item, [issue["title"]] + issue["queries"], settings,
                                   pinned_docs=doc_ids)
        for s in sources:
            if s["type"] == "meta":
                continue                                  # 법률 개요는 빼고 실제 근거만
            is_pinned = any(f":{d}:" in s.get("chunk_id", "") for d in doc_ids)
            (pinned if is_pinned else rest).append(s)
    return pinned, rest


def answer_complex(rt: Runtime, question: str, plan: dict, on_step=lambda m: None) -> Result:
    started = time.perf_counter()
    issues = plan["issues"]
    for item in {law["item_id"]: law for issue in issues for law in issue["laws"]}.values():   # 색인은 차례로
        on_step(f"{item['label']} 조문을 준비하는 중")
        ensure_base(rt, item)
    on_step(f"쟁점 {len(issues)}개의 근거를 동시에 찾는 중")
    with ThreadPoolExecutor(max_workers=len(issues)) as pool:
        per_issue = list(pool.map(lambda issue: issue_sources(rt, issue, question), issues))

    # 1) 쟁점마다 지목한 조문을 먼저 모두 담고  2) 남는 자리를 검색 결과로 — 쟁점끼리 번갈아
    #    (평가: 법률 2개짜리 쟁점에서 둘째 법률의 지목 조문이 상한에 밀려 잘렸다 — 전세 경매 · 도난품)
    sources, seen = [], set()

    def add(source: dict) -> None:
        if source["chunk_id"] not in seen and len(sources) < MAX_SOURCES:
            seen.add(source["chunk_id"])
            sources.append(source)

    for group in (0, 1):
        lists = [found[group] for found in per_issue]
        for rank in range(max(map(len, lists), default=0)):
            for found in lists:
                if rank < len(found):
                    add(found[rank])
    sources = [{**s, "n": n} for n, s in enumerate(sources, start=1)]
    if not sources:
        return Result(answer=NOT_FOUND, sources=[], cited=[], notices=[LEGAL],
                      elapsed=time.perf_counter() - started)

    on_step("쟁점별로 정리해 답변을 쓰는 중")
    issue_lines = [f"{n}. {i['title']} (관련 법률: {', '.join(l['label'] for l in i['laws'])})"
                   for n, i in enumerate(issues, start=1)]
    system = COMPLEX_PROMPT.format(issues="\n".join(issue_lines),
                                   assumptions="\n".join(f"- {a}" for a in plan["assumptions"]) or "(없음)",
                                   sources=format_sources(sources))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    answer = rt.llm.invoke(messages).content
    if not cited_numbers(answer):                         # 근거 번호를 빼먹었으면 한 번 다시 쓰게
        answer = rt.llm.invoke(messages + [{"role": "assistant", "content": answer},
                                           {"role": "user", "content": CITE_RETRY.format(not_found=NOT_FOUND)}]).content
    return Result(answer=answer, sources=sources, cited=cited_sources(answer, sources),
                  warnings=citation_warnings(answer, sources), notices=[LEGAL],
                  elapsed=time.perf_counter() - started)
