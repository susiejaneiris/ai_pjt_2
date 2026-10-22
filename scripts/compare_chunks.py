"""청크 크기 · 중복 길이 · 임베딩 모델 비교 (명세 2.5 · 4.2 · 6장 "값을 바꿨을 때의 차이").

실행 (프로젝트 폴더에서, 평가를 한 번 돌린 뒤 — 질문별 검색어 캐시를 쓴다):
    python -m scripts.compare_chunks
    python -m scripts.compare_chunks --large      # text-embedding-3-large 도 비교 (임베딩을 새로 만든다)

방법
    1. 지금 law_docs 의 청크를 문서 단위로 다시 이어 붙여 원문을 복원한다 (외부 호출 없이 같은 문서로 비교)
    2. 설정마다 실험용 컬렉션을 따로 만든다 (vectorstore/experiments — 실제 색인은 건드리지 않음)
    3. 평가 질문(정상 21개)을 저장된 검색어 그대로 retrieve 만 돌려 정답 조문이 근거에 들어오는지 본다
       → LLM 을 부르지 않아 빠르고, 실행마다 결과가 같다
결과는 docs/compare_chunks.md 에 저장한다.
"""

import argparse
import json
from datetime import date, datetime

from langchain_openai import OpenAIEmbeddings

from config import COLLECTED_JSON, DATA_DIR, GMS_BASE_URL, ROOT, VECTOR_DIR, env, load_settings
from prep.collect import question_key
from prep.item_text import load_items
from rag.retriever import join_chunks, retrieve_sources
from service.runtime import build_runtime
from store.chunking import chunk_documents
from store.vectorstore import get_collection, upsert

EXP_DIR = VECTOR_DIR / "experiments"
OUT = ROOT / "docs" / "compare_chunks.md"
CONFIGS = [(500, 100), (1000, 200), (1500, 300)]


def restore_raw_docs(docs_store) -> list[dict]:
    """색인된 청크 → 문서 단위 원문 (헤더 · 메타데이터 포함). 겹친 부분은 한 번만."""
    data = docs_store.get(include=["documents", "metadatas"])
    groups: dict[tuple, list] = {}
    for text, meta in zip(data["documents"], data["metadatas"]):
        groups.setdefault((meta["item_id"], meta["doc_id"]), []).append((meta.get("chunk_seq", 0), text, meta))
    raws = []
    for parts in groups.values():
        parts.sort(key=lambda p: p[0])
        header = parts[0][1].split("\n", 1)[0].strip("[]")
        bodies = [p[1].split("\n", 1)[-1] for p in parts]
        meta = parts[0][2]
        raws.append({**{k: meta.get(k, "") for k in ("item_id", "item_name", "doc_id", "source_type", "title",
                                                     "url", "citation", "date", "query")},
                     "header": header, "text": join_chunks(bodies)})
    return raws


def build_experiment(name: str, raws: list[dict], size: int, overlap: int, embeddings) -> tuple:
    store = get_collection(f"exp_{name}", embeddings, persist_dir=EXP_DIR)
    if store._collection.count() == 0:
        docs, ids = chunk_documents(raws, {"chunk_size": size, "chunk_overlap": overlap}, date.today().isoformat())
        upsert(store, docs, ids)
    return store, store._collection.count()


def run(rt, store, questions, items, cache, settings) -> dict:
    hits, chars, misses = 0, [], []
    for q in questions:
        item = items[q["law"]]
        entry = cache[item["item_id"]]["questions"][question_key(q["question"])]
        sources = retrieve_sources(rt.meta, store, item, [q["question"]] + entry["queries"], settings)
        ok = any(f"{q['law']} {lab}(" in s["title"] for s in sources for lab in q["expect"])
        hits += ok
        if not ok:
            misses.append(q["id"])
        chars.append(sum(len(s["text"]) for s in sources))
    return {"hit": round(100 * hits / len(questions), 1), "misses": misses,
            "chars": round(sum(chars) / len(chars))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--large", action="store_true", help="text-embedding-3-large 도 비교")
    args = parser.parse_args()

    rt = build_runtime()
    settings = load_settings()
    # 이름 → 법률 전체 항목, 표시 이름 → 부분 항목까지 (민법(총칙) · 민법(친족) … 은 이름이 모두 "민법")
    items = {i["name"]: i for i in load_items() if not i.get("article_range")} | {i["label"]: i for i in load_items()}
    cache = json.loads(COLLECTED_JSON.read_text(encoding="utf-8"))
    questions = [q for q in json.loads((DATA_DIR / "eval_questions.json").read_text(encoding="utf-8"))
                 if not q["trap"]]
    raws = restore_raw_docs(rt.docs)
    print(f"복원한 문서 {len(raws)}개")

    small = rt.meta._embedding_function
    runs = [(f"{s}_{o}_small", s, o, small, settings["embedding_model"]) for s, o in CONFIGS]
    if args.large:
        large = OpenAIEmbeddings(model="text-embedding-3-large", api_key=env("GMS_KEY"), base_url=GMS_BASE_URL)
        runs.append(("1000_200_large", 1000, 200, large, "text-embedding-3-large"))

    rows = []
    for name, size, overlap, emb, model in runs:
        store, n_chunks = build_experiment(name, raws, size, overlap, emb)
        result = run(rt, store, questions, items, cache, settings)
        rows.append((size, overlap, model, n_chunks, result))
        print(f"{size}/{overlap} {model}: 청크 {n_chunks} · 적중 {result['hit']}% · 근거 평균 {result['chars']}자 · 놓침 {result['misses']}")

    lines = ["# 청크 크기 · 중복 길이 · 임베딩 모델 비교", "",
             f"- 실행: {datetime.now():%Y-%m-%d %H:%M}",
             f"- 같은 문서 {len(raws)}개를 설정마다 다시 청킹 · 임베딩해 실험용 컬렉션에 색인",
             f"- 평가 질문 정상 {len(questions)}개, 저장된 검색어로 retrieve 만 실행 (top_k={settings['top_k']}, "
             f"RRF · 조문 전체 확장 포함) — LLM 을 부르지 않아 결과가 실행마다 같다", "",
             "| 청크 크기 | 중복 길이 | 임베딩 모델 | 청크 수 | 검색 적중률 | 근거 평균 길이(자) | 놓친 질문 |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {s} | {o} | {m} | {n} | {r['hit']}% | {r['chars']:,} | {', '.join(r['misses']) or '-'} |"
              for s, o, m, n, r in rows]
    lines += ["", "## 관찰", "", "- (실행 결과를 보고 작성)", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ docs/{OUT.name}")


if __name__ == "__main__":
    main()
