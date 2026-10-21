"""검색 설정 비교 (F2014 · 명세 4.3 · 4.5) — 같은 질문에 설정만 바꿔 근거 목록이 어떻게 달라지는지.

실행 (프로젝트 폴더에서):
    python -m scripts.compare_search
    python -m scripts.compare_search "근로기준법" "주휴수당은 언제 받을 수 있나요?"

비교 항목
    1. 유사도 검색 vs MMR  (F2014)
    2. Top-k 3 / 6 / 10    (F2006 · 명세 4.3)
결과는 docs/compare_search.md 에 표로 저장합니다.
"""

import sys
from datetime import datetime

from config import ROOT, load_settings
from prep.item_text import load_items
from rag.retriever import retrieve_sources
from service.chat import prepare_documents
from service.runtime import Runtime, build_runtime

OUT = ROOT / "docs" / "compare_search.md"
DEFAULT = ("주택임대차보호법", "계약이 끝났는데 집주인이 보증금을 안 돌려줘요")


def run_config(rt: Runtime, item: dict, question: str, **overrides) -> list[dict]:
    return retrieve_sources(rt.meta, rt.docs, item, question, load_settings(**overrides))


def table(sources: list[dict]) -> list[str]:
    rows = ["| 번호 | 유형 | 제목 |", "|---|---|---|"]
    rows += [f"| {s['n']} | {s['type_label']} | {s['title']} |" for s in sources]
    return rows


def compare(rt: Runtime, item: dict, question: str) -> str:
    prepare_documents(rt, item, question, on_step=lambda m: print(f"  · {m}"))
    lines = [f"# 검색 설정 비교", "", f"- 실행: {datetime.now():%Y-%m-%d %H:%M}",
             f"- 항목: {item['label']}", f"- 질문: {question}",
             f"- 이 항목에 색인된 청크: {rt.docs_count(item['item_id'])}개", ""]

    similar = run_config(rt, item, question, search_type="similarity")
    mmr = run_config(rt, item, question, search_type="mmr")
    lines += ["## 1. 유사도 검색 vs MMR (F2014)", "",
              f"MMR 설정: fetch_k={load_settings()['mmr_fetch_k']}, lambda={load_settings()['mmr_lambda']}", "",
              "### 유사도 검색", *table(similar), "", "### MMR", *table(mmr), ""]
    only_similar = {s["title"] for s in similar} - {s["title"] for s in mmr}
    only_mmr = {s["title"] for s in mmr} - {s["title"] for s in similar}
    types = lambda ss: sorted({s["type_label"] for s in ss})
    lines += [f"- 유사도에만 있는 근거: {', '.join(sorted(only_similar)) or '없음'}",
              f"- MMR 에만 있는 근거: {', '.join(sorted(only_mmr)) or '없음'}",
              f"- 출처 유형 수: 유사도 {len(types(similar))}종 {types(similar)} / MMR {len(types(mmr))}종 {types(mmr)}", ""]

    lines += ["## 2. Top-k 비교 (F2006)", ""]
    for k in (3, 6, 10):
        sources = run_config(rt, item, question, top_k=k)
        lines += [f"### top_k = {k} → 근거 {len(sources)}개 (메타 1 + 외부 문서)", *table(sources), ""]
    lines += ["## 관찰 (직접 작성)", "", "- ", ""]
    return "\n".join(lines)


def main(rt: Runtime | None = None) -> None:
    name, question = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else DEFAULT
    item = next(i for i in load_items() if name in (i["name"], i["label"], i["item_id"]))
    rt = rt or build_runtime()
    report = compare(rt, item, question)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(f"→ docs/{OUT.name}")


if __name__ == "__main__":
    main()
