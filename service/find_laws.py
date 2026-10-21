"""조건 기반 항목 탐색 (F2011) — "알바하다 다쳤을 때 볼 법" → 조건에 맞는 법률만.

    1. 상황을 법률 용어로 바꾼다 (일상어로는 법률 설명과 의미가 멀어 정답이 후보에 안 들어온다)
       실측: "알바하다가 다쳤어요" 후보 15건에 산업재해보상보험법 없음 → "업무상 재해 산업재해 보상" 은 1위
    2. 원래 문장 + 바꾼 검색어로 law_meta 를 검색해 후보를 합친다
    3. LLM 이 후보 설명만 보고 조건에 맞는 것만 고른다 → 맞지 않는 항목이 섞이지 않게
"""

from rag.llm import parse_json
from rag.prompts import FIND_LAWS_PROMPT, FIND_QUERY_PROMPT
from service.runtime import Runtime

MAX_CANDIDATES = 20


def legal_queries(rt: Runtime, condition: str) -> list[str]:
    queries = parse_json(rt.llm.invoke(FIND_QUERY_PROMPT.format(condition=condition)).content, default=[])
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()][:3]


def gather(rt: Runtime, queries: list[str]) -> list:
    """검색어별 결과를 번갈아 합친다 — 한 검색어의 후보가 목록을 다 차지하지 않게."""
    k = rt.settings["find_laws_candidates"]
    results = [rt.meta.similarity_search(q, k=k) for q in queries]
    merged, seen = [], set()
    for rank in range(k):
        for docs in results:
            if rank < len(docs) and docs[rank].metadata["item_id"] not in seen:
                seen.add(docs[rank].metadata["item_id"])
                merged.append(docs[rank])
    return merged[:MAX_CANDIDATES]


def find_laws(rt: Runtime, condition: str, items_by_id: dict[str, dict]) -> list[dict]:
    """[{item, reason}] — 조건에 맞는 법률이 없으면 빈 목록."""
    candidates = gather(rt, legal_queries(rt, condition) + [condition])
    if not candidates:
        return []

    lines = []
    for number, doc in enumerate(candidates, start=1):
        summary = doc.page_content.replace("\n", " / ")[:300]     # 법률명 · 분야 · 목적 · 조문 제목 앞부분
        lines.append(f"{number}. {summary}")
    prompt = FIND_LAWS_PROMPT.format(condition=condition, candidates="\n".join(lines))
    picked = parse_json(rt.llm.invoke(prompt).content, default=[])

    results = []
    for entry in picked if isinstance(picked, list) else []:
        number = entry.get("no") if isinstance(entry, dict) else None
        if isinstance(number, int) and 1 <= number <= len(candidates):
            item = items_by_id.get(candidates[number - 1].metadata["item_id"])
            if item and all(r["item"]["item_id"] != item["item_id"] for r in results):
                results.append({"item": item, "reason": str(entry.get("reason", "")).strip()})
    return results
