"""질의응답 (F2009) — 문서 준비(RAG 2) → LangGraph(retrieve → generate) → 인용된 근거만 추리기.

화면은 ask() 하나만 부릅니다. on_step 으로 진행 상황을 받아 진행 표시에 씁니다 (F2012).
"""

import time
from dataclasses import dataclass, field

from prep.collect import CollectReport, collect, load_cache, restore_entry, today
from rag.citations import cited_sources
from service.runtime import Runtime
from store.chunking import chunk_documents
from store.vectorstore import upsert


@dataclass
class Result:
    answer: str
    sources: list[dict]                      # 검색된 근거 전체 (번호 포함)
    cited: list[dict]                        # 답변이 실제로 인용한 근거만 (F2008)
    warnings: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    report: CollectReport | None = None
    elapsed: float = 0.0


def index_documents(rt: Runtime, raw_docs: list[dict]) -> int:
    """수집한 문서를 청킹해 law_docs 에 넣는다 (F2005). 넣은 청크 수."""
    if not raw_docs:
        return 0
    docs, ids = chunk_documents(raw_docs, rt.settings, today())
    upsert(rt.docs, docs, ids)
    return len(ids)


def prepare_documents(rt: Runtime, item: dict, question: str, on_step=lambda m: None) -> CollectReport:
    before = load_cache().get(item["item_id"])
    report = collect(item, question, rt.settings, rt.llm, on_step)
    if report.raw_docs:
        on_step(f"문서 {len(report.raw_docs)}개를 잘게 나눠 색인하는 중")
        try:
            index_documents(rt, report.raw_docs)
        except Exception:
            restore_entry(item["item_id"], before)     # 다음 질문 때 다시 수집 · 색인하도록
            raise
    return report


def run_graph(rt: Runtime, item: dict, question: str, history: list[dict], mode: str = "qa",
              pinned_ids: list[str] | None = None, queries: list[str] | None = None, in_scope: bool = True) -> Result:
    state = rt.graph.invoke({
        "item": item, "question": question, "mode": mode, "settings": rt.settings,
        "history": [{"role": m["role"], "content": m["content"]} for m in history],
        "pinned_ids": pinned_ids or [], "queries": queries or [], "in_scope": in_scope,
    })
    answer = state["answer"]
    return Result(
        answer=answer, sources=state["sources"], cited=cited_sources(answer, state["sources"]),
        warnings=state.get("warnings", []), notices=state.get("notices", []),
    )


def ask(rt: Runtime, item: dict, question: str, history: list[dict], mode: str = "qa",
        on_step=lambda m: None) -> Result:
    started = time.perf_counter()
    report = prepare_documents(rt, item, question, on_step)
    on_step("근거를 찾아 답변을 쓰는 중")
    result = run_graph(rt, item, question, history, mode, queries=report.queries, in_scope=report.in_scope)
    result.report = report
    result.elapsed = time.perf_counter() - started
    return result
