"""Vector Store 영역 — 컬렉션 생성 · 조회 · 색인 (F2002 · F2005).

UI 와 무관한 순수 모듈입니다. Streamlit 캐시는 UI 쪽에서 감쌉니다.

    law_meta  항목 메타데이터. 항목당 1청크, id = item_id
    law_docs  외부 문서 청크. id = "item_id:doc_id:순번"

같은 id 로 다시 넣으면 덮어쓰기(upsert)만 일어나 개수가 늘지 않습니다.
"""

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from config import DOCS_COLLECTION, GMS_BASE_URL, META_COLLECTION, VECTOR_DIR, env, load_settings


class MissingKeyError(RuntimeError):
    """GMS_KEY 가 없을 때. 화면에서 안내 문구로 바꿔 보여 준다 (F2012)."""


def get_embeddings() -> Embeddings:
    key = env("GMS_KEY")
    if not key:
        raise MissingKeyError("GMS_KEY가 없습니다. .env 를 확인하세요.")
    return OpenAIEmbeddings(
        model=load_settings()["embedding_model"], api_key=key, base_url=GMS_BASE_URL
    )


def get_collection(name: str, embeddings: Embeddings | None = None, persist_dir=VECTOR_DIR) -> Chroma:
    """컬렉션을 열고, 없으면 만든다. 거리는 코사인."""
    return Chroma(
        collection_name=name,
        embedding_function=embeddings or get_embeddings(),
        persist_directory=str(persist_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )


def get_meta(embeddings: Embeddings | None = None, **kwargs) -> Chroma:
    return get_collection(META_COLLECTION, embeddings, **kwargs)


def get_docs(embeddings: Embeddings | None = None, **kwargs) -> Chroma:
    return get_collection(DOCS_COLLECTION, embeddings, **kwargs)


def upsert(store: Chroma, docs: list[Document], ids: list[str], batch_size: int = 100) -> None:
    """같은 id 는 덮어쓴다. 임베딩 요청이 너무 커지지 않게 나눠 넣는다."""
    for start in range(0, len(docs), batch_size):
        store.add_documents(docs[start:start + batch_size], ids=ids[start:start + batch_size])


def count(store: Chroma, where: dict | None = None) -> int:
    """컬렉션 전체 또는 조건에 맞는 청크 수 (화면 · 검증용)."""
    if where is None:
        return store._collection.count()
    return len(store.get(where=where, include=[])["ids"])


def get_by_id(store: Chroma, chunk_id: str) -> Document | None:
    """검색 없이 id 로 한 청크를 꺼낸다. 선택한 항목의 메타 청크를 항상 근거에 넣을 때 (F2006)."""
    result = store.get(ids=[chunk_id], include=["documents", "metadatas"])
    if not result["ids"]:
        return None
    return Document(page_content=result["documents"][0], metadata=result["metadatas"][0], id=chunk_id)
