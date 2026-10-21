"""RAG 1 — 항목 메타데이터 색인 (F2001 · F2002). 앱 실행 전에 한 번 실행합니다.

실행 (프로젝트 폴더에서):
    python -m scripts.build_index

data/items.json → 항목 1건 = 텍스트 1개 → 임베딩 → law_meta 컬렉션 (id = item_id)
두 번 실행해도 청크 수가 늘지 않습니다. (명세 4.1)
"""

from langchain_core.documents import Document

from prep.item_text import build_item_text, item_metadata, load_items
from store.vectorstore import count, get_meta, upsert


def main() -> None:
    items = load_items()
    print(f"항목 로드: {len(items)}건")

    docs = [Document(page_content=build_item_text(i), metadata=item_metadata(i)) for i in items]
    ids = [i["item_id"] for i in items]

    store = get_meta()
    before = count(store)
    upsert(store, docs, ids)
    after = count(store)

    print(f"law_meta 청크 수: {before} → {after}")
    print("항목 수와 청크 수가 같습니다." if after == len(items) else "⚠ 항목 수와 청크 수가 다릅니다.")
    print(f"\n[예시] {ids[0]}\n{docs[0].page_content}")


if __name__ == "__main__":
    main()
