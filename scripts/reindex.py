"""임베딩 모델이나 청크 설정을 바꾼 뒤 색인을 다시 만든다 (외부 문서를 다시 내려받지 않는다).

실행 (프로젝트 폴더에서, settings.json 을 먼저 바꾼 뒤):
    python -m scripts.reindex

    1. 지금 law_docs 의 청크를 문서 단위 원문으로 복원
    2. law_meta · law_docs 를 지우고 settings.json 의 임베딩 모델 · 청크 설정으로 다시 색인
모델을 바꾸면 벡터 차원이 달라져(small 1536 → large 3072) 기존 컬렉션에 섞어 넣을 수 없으므로 통째로 다시 만든다.
"""

from datetime import date

import chromadb
from langchain_core.documents import Document

from config import DOCS_COLLECTION, META_COLLECTION, VECTOR_DIR, load_settings
from prep.item_text import build_item_text, item_metadata, load_items
from scripts.compare_chunks import restore_raw_docs
from store.chunking import chunk_documents
from store.vectorstore import count, get_docs, get_embeddings, get_meta, upsert


def main() -> None:
    settings = load_settings()
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    names = {c.name for c in client.list_collections()}

    raws = []
    if DOCS_COLLECTION in names:
        old = client.get_collection(DOCS_COLLECTION)
        data = old.get(include=["documents", "metadatas"])

        class _Store:                                   # restore_raw_docs 가 쓰는 get() 만 흉내
            def get(self, include=None):
                return data
        raws = restore_raw_docs(_Store())
    print(f"복원한 외부 문서 {len(raws)}개 · 새 임베딩 모델 {settings['embedding_model']}")

    for name in (META_COLLECTION, DOCS_COLLECTION):
        if name in names:
            client.delete_collection(name)

    embeddings = get_embeddings()
    items = load_items()
    meta = get_meta(embeddings)
    upsert(meta, [Document(page_content=build_item_text(i), metadata=item_metadata(i)) for i in items],
           [i["item_id"] for i in items])
    docs_store = get_docs(embeddings)
    if raws:
        chunks, ids = chunk_documents(raws, settings, date.today().isoformat())
        upsert(docs_store, chunks, ids)
    print(f"law_meta {count(meta)}건 · law_docs {count(docs_store)}청크로 다시 색인했습니다.")


if __name__ == "__main__":
    main()
