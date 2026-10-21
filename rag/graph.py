"""LangGraph RAG 파이프라인 — retrieve → generate 두 노드 (F2007).

    START → retrieve → generate → END

mode 로 같은 그래프를 질의응답 · 팩트체크 · 조문 풀이에 함께 씁니다 (F2010).
그래프 구조 확인 (명세 4.3):
    python -m rag.graph
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from config import load_settings
from prep.disclaimer import notices_for, prompt_rules
from rag.citations import citation_warnings, cited_numbers
from rag.prompts import (ANSWER_PROMPT, CITE_RETRY, EXPLAIN_PROMPT, FACTCHECK_PROMPT, NO_EVIDENCE_GUIDE, NOT_FOUND,
                         OUT_OF_SCOPE_GUIDE)
from rag.retriever import format_sources, retrieve_sources

MODE_PROMPTS = {"qa": ANSWER_PROMPT, "factcheck": FACTCHECK_PROMPT, "explain": EXPLAIN_PROMPT}


class RagState(TypedDict, total=False):
    item: dict
    question: str
    history: list[dict]          # [{"role": "user"|"assistant", "content": ...}]
    mode: str                    # "qa" | "factcheck" | "explain"
    settings: dict
    pinned_ids: list[str]        # 검색과 무관하게 꼭 넣을 청크 (조문 풀이)
    queries: list[str]           # 프롬프트 1 이 만든 법률 용어 검색어 — 검색 질의를 보강
    in_scope: bool               # 프롬프트 1 의 범위 판단 — False 면 generate 가 LLM 없이 안내만
    sources: list[dict]
    answer: str
    warnings: list[str]
    notices: list[str]           # 면책 안내 — 답변과 함께 항상 표시 (F2012)


def build_graph(meta_store, docs_store, llm):
    """저장소와 모델을 받아 그래프를 만든다. UI 는 이 그래프를 invoke 만 한다."""

    def retrieve(state: RagState) -> dict:
        settings = state.get("settings") or load_settings()
        # 후속 질문("그건 몇 번까지?")은 직전 질문을 붙여 검색해야 맥락이 산다.
        # 일상어 질문만으로는 조문과 의미가 멀어 핵심 조문을 놓친다 → 법률 용어 검색어도 각각 검색해 합친다.
        last_user = [m["content"] for m in state.get("history", []) if m["role"] == "user"][-1:]
        queries = [" ".join(last_user + [state["question"]])] + state.get("queries", [])
        return {"sources": retrieve_sources(meta_store, docs_store, state["item"], queries, settings,
                                            state.get("pinned_ids"))}

    def generate(state: RagState) -> dict:
        item, sources = state["item"], state["sources"]
        notices = notices_for(item)
        mode = state.get("mode", "qa")
        if not state.get("in_scope", True) and mode != "explain":
            # 고른 법률이 다루지 않는 질문 — 같은 법의 관계없는 조문을 끌어와 답하지 않게 LLM 을 부르지 않는다
            guide = OUT_OF_SCOPE_GUIDE.format(item_name=item["label"])
            return {"answer": f"{NOT_FOUND}\n\n{guide}", "warnings": [], "notices": notices}
        external = [s for s in sources if s["type"] != "meta"]
        if not external and mode != "explain":
            # 외부 근거가 하나도 없으면 LLM 을 부르지 않는다 — 추측 차단
            return {"answer": NOT_FOUND, "warnings": [], "notices": notices}

        settings = state.get("settings") or load_settings()
        system = MODE_PROMPTS[state.get("mode", "qa")].format(
            sources=format_sources(sources), not_found=NOT_FOUND, risk_rules=prompt_rules(item),
            item_name=item["label"],
        )
        turns = state.get("history", [])[-settings["history_turns"] * 2:]
        messages = [{"role": "system", "content": system}] + turns + [{"role": "user", "content": state["question"]}]
        answer = llm.invoke(messages).content
        if mode in ("qa", "factcheck") and not cited_numbers(answer) and not answer.startswith(NOT_FOUND):
            # 근거 번호를 빼먹은 답 — 바로 버리지 않고 한 번 다시 쓰게 한다 (평가: 맞는 답인데 인용만 빠진 경우가 있었다)
            retry = messages + [{"role": "assistant", "content": answer},
                                {"role": "user", "content": CITE_RETRY.format(not_found=NOT_FOUND)}]
            answer = llm.invoke(retry).content
        # 모델은 "정해진 문장으로 시작하라"는 지시를 표현만 바꿔 어기곤 한다 (실측).
        # 인용이 하나도 없는 답은 근거 없는 답이므로 코드에서 확정적으로 표시한다 (F2007).
        # 본문은 버린다 — 인용 없이 쓴 내용은 모델의 기억 · 추측이라 보여 주면 안 된다 (평가 v2: 음주 킥보드 질문).
        if state.get("mode", "qa") == "qa" and not cited_numbers(answer):
            answer = f"{NOT_FOUND}\n\n{NO_EVIDENCE_GUIDE}"
        return {"answer": answer, "warnings": citation_warnings(answer, sources), "notices": notices}

    graph = StateGraph(RagState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


if __name__ == "__main__":
    # 저장소 없이 구조만 출력한다
    print(build_graph(None, None, None).get_graph().draw_mermaid())
