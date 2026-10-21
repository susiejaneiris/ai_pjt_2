"""근거 검색 및 병합 (F2006 · F2014).

    1. 선택한 항목의 메타 청크 — 검색 없이 id 로 꺼내 항상 [근거 1]
    2. law_docs 에서 item_id 로 범위를 좁혀 의미 유사도 검색 (similarity 또는 MMR, settings.json)
    3. 병합 · 중복 제거 → 정렬(메타 → 조문 → 판례 → 법령해석례 → 위키) → 근거 번호 부여
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document

from store.vectorstore import get_by_id

SOURCE_LABELS = {"meta": "항목 메타데이터", "article": "조문", "prec": "판례",
                 "expc": "법령해석례(PDF)", "qa": "생활법령 백문백답", "wiki": "위키백과"}
SOURCE_ORDER = {"meta": 0, "article": 1, "prec": 2, "expc": 3, "qa": 4, "wiki": 5}


def search_one(docs_store: Chroma, query: str, item_id: str, settings: dict, k: int) -> list[Document]:
    """질의 하나로 외부 문서 청크 검색. search_type 만 바꾸면 MMR 로 바뀐다 (F2014).

    유사도 컷오프(score_cutoff) 아래인 청크는 버린다 — 아주 관련 없는 문서만 거르는 안전망.
    기준값은 평가 세트로 정했다: 정답 조문 점수 최저 0.415, 정답 아닌 상위 문서와 분포가 거의 겹쳐
    0.45 만 돼도 정답 3개를 잃는다 → 정답을 하나도 잃지 않는 0.38 (text-embedding-3-large 기준).
    범위 밖 질문을 막는 주된 장치는 컷오프가 아니라 프롬프트 1 의 범위 판단이다.
    """
    where = {"item_id": item_id}
    cutoff = settings.get("score_cutoff", 0)
    scored = docs_store.similarity_search_with_relevance_scores(
        query, k=max(k, settings["mmr_fetch_k"]) if settings["search_type"] == "mmr" else k, filter=where)
    passed = {doc.id for doc, score in scored if score >= cutoff}
    if settings["search_type"] == "mmr":
        docs = docs_store.max_marginal_relevance_search(
            query, k=k, fetch_k=settings["mmr_fetch_k"], lambda_mult=settings["mmr_lambda"], filter=where
        )
        return [d for d in docs if d.id in passed]
    return [doc for doc, score in scored if doc.id in passed]


RRF_K = 60      # 순위 융합 상수 — 한 질의의 1등만으로 전체 1등이 되지 않게 완만하게


def search_docs(docs_store: Chroma, queries: str | list[str], item_id: str, settings: dict) -> list[Document]:
    """외부 문서 청크 검색 (F2006).

    multi_query 가 켜져 있으면 질문 · 법률 용어 검색어를 **따로** 검색해 순위를 합친다 (Reciprocal Rank Fusion).
    한 문장으로 이어 붙여 검색하면 의미가 섞여 흐려진다 — 평가 v1 에서 "이사를 가야 해요"(질문)와
    "임차권등기명령"(검색어)을 이어 붙이자 정답 조문이 18위로 밀렸다.
    """
    if isinstance(queries, str):
        queries = [queries]
    queries = [q for q in queries if q and q.strip()]
    k = settings["top_k"]
    if not settings.get("multi_query", True) or len(queries) == 1:
        return search_one(docs_store, " ".join(queries), item_id, settings, k)

    # 질의마다 top_k 보다 깊게(rrf_depth) 본다 — 상위 6개만 합산하면 여러 질의에서 꾸준히 10~20위인 정답이
    # 표를 못 받는다 (평가 v5: 한 검색어로 1위인 정답 조문이 다른 질의의 표에 밀려 탈락)
    depth = max(k, settings.get("rrf_depth", 30))
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}
    for query in queries:
        for rank, doc in enumerate(search_one(docs_store, query, item_id, settings, depth), start=1):
            scores[doc.id] = scores.get(doc.id, 0.0) + 1.0 / (RRF_K + rank)
            docs.setdefault(doc.id, doc)
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [docs[i] for i in ranked[:k]]


def expand_articles(docs_store: Chroma, found: list[Document]) -> list[Document]:
    """조문 청크가 하나라도 잡히면 그 조문의 나머지 청크도 함께 넣는다 (부모 문서 확장).

    근거 단위는 조문 하나다. 긴 조문(도로교통법 제50조 등)은 여러 청크로 잘리는데, 질문과 맞는 항이 든 청크가
    아니라 같은 조문의 다른 청크만 잡히면 답을 못 한다 — 평가 v2 의 "킥보드 헬멧" 질문이 그랬다.
    """
    expanded, seen = [], set()
    for doc in found:
        expanded.append(doc)
        meta = doc.metadata
        key = (meta.get("item_id"), meta.get("doc_id"))
        if meta.get("source_type") != "article" or key in seen:
            continue
        seen.add(key)
        rest = docs_store.get(where={"$and": [{"item_id": key[0]}, {"doc_id": key[1]}]},
                              include=["documents", "metadatas"])
        for chunk_id, text, chunk_meta in zip(rest["ids"], rest["documents"], rest["metadatas"]):
            if chunk_id != doc.id:
                expanded.append(Document(page_content=text, metadata=chunk_meta, id=chunk_id))
    return expanded


def join_chunks(bodies: list[str], max_overlap: int = 400) -> str:
    """이웃 청크는 앞 청크의 끝과 뒤 청크의 시작이 겹친다(chunk_overlap) → 겹친 부분을 한 번만 남긴다."""
    text = bodies[0]
    for body in bodies[1:]:
        overlap = next((n for n in range(min(max_overlap, len(text), len(body)), 20, -1)
                        if text.endswith(body[:n])), 0)
        text += ("" if overlap else "\n") + body[overlap:]
    return text


def merge(meta: Document | None, found: list[Document]) -> list[Document]:
    """중복 제거 3단계 → 메타 → 조문 → 판례 → 법령해석례 → 위키 순으로 세운다.

    1. 같은 청크 id
    2. 본문이 거의 같은 청크 (헤더를 뺀 앞 200자가 같음 — 법률 · 시행령에 같은 문장이 있을 때)
    3. 같은 문서의 여러 청크 → 순번대로 이어 근거 하나로 (한 문서가 근거 목록을 도배하지 않게)
    """
    unique, seen_ids, seen_text = [], set(), set()
    for doc in ([meta] if meta else []) + found:
        key_text = doc.page_content.split("\n", 1)[-1][:200]
        if doc.id in seen_ids or key_text in seen_text:
            continue
        seen_ids.add(doc.id)
        seen_text.add(key_text)
        unique.append(doc)

    by_doc: dict[str, list[Document]] = {}
    for doc in unique:
        by_doc.setdefault(doc.metadata.get("doc_id") or doc.id, []).append(doc)
    merged = []
    for parts in by_doc.values():                  # dict 는 처음 나온 순서(=검색 순위)를 지킨다
        if len(parts) == 1:
            merged.append(parts[0])
            continue
        parts.sort(key=lambda d: d.metadata.get("chunk_seq", 0))
        header, first_body = parts[0].page_content.split("\n", 1) if "\n" in parts[0].page_content \
            else ("", parts[0].page_content)
        bodies = [first_body] + [p.page_content.split("\n", 1)[-1] for p in parts[1:]]
        seqs = [p.metadata.get("chunk_seq", 0) for p in parts]
        contiguous = seqs == list(range(seqs[0], seqs[0] + len(seqs)))
        body = join_chunks(bodies) if contiguous else "\n…\n".join(bodies)    # 끊긴 곳은 … 로 표시
        merged.append(Document(page_content=header + "\n" + body, metadata=parts[0].metadata, id=parts[0].id))
    # 같은 유형 안에서는 검색 순위를 유지한다 (sorted 는 안정 정렬)
    return sorted(merged, key=lambda d: SOURCE_ORDER.get(d.metadata.get("source_type"), 9))


def to_sources(docs: list[Document]) -> list[dict]:
    """화면 · 프롬프트에 쓰는 근거 목록. 번호는 1부터."""
    sources = []
    for number, doc in enumerate(docs, start=1):
        meta = doc.metadata
        source_type = meta.get("source_type", "")
        sources.append({
            "n": number,
            "type": source_type,
            "type_label": SOURCE_LABELS.get(source_type, source_type),
            "title": meta.get("title") or meta.get("label", ""),
            "url": meta.get("url", ""),
            "citation": meta.get("citation") or meta.get("url", ""),   # PDF 는 "파일명 · 쪽"
            "date": meta.get("date") or meta.get("effective_date", ""),
            "text": doc.page_content,
            "chunk_id": doc.id,
        })
    return sources


def retrieve_sources(meta_store: Chroma, docs_store: Chroma, item: dict, query: str | list[str], settings: dict,
                     pinned_ids: list[str] | None = None) -> list[dict]:
    """pinned_ids — 검색과 무관하게 꼭 넣을 청크 (조문 풀이에서 고른 조문)."""
    meta = get_by_id(meta_store, item["item_id"])
    if meta:
        meta.metadata["title"] = f"{item['label']} — 법률 개요"
    pinned = [d for d in (get_by_id(docs_store, i) for i in pinned_ids or []) if d]
    found = search_docs(docs_store, query, item["item_id"], settings)
    if settings.get("expand_articles", True):
        found = expand_articles(docs_store, found)
    return to_sources(merge(meta, pinned + found))


def format_sources(sources: list[dict]) -> str:
    """프롬프트 3 에 넣을 근거 텍스트. 출처 유형을 함께 적는다 (F2007)."""
    return "\n\n".join(f"[근거 {s['n']}] ({s['type_label']}) {s['title']}\n{s['text']}" for s in sources)
