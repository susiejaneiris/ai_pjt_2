"""서비스 실행에 필요한 객체(저장소 · 모델 · 그래프)를 한 번에 만듭니다.

Streamlit 과 FastAPI(F2013)가 둘 다 이 모듈만 거쳐 RAG 를 씁니다 (NF2005).
UI 쪽에서 캐시로 감싸 한 번만 만듭니다.
"""

from dataclasses import dataclass, field

from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI

from config import load_settings
from rag.graph import build_graph
from rag.llm import get_chat_model
from store.vectorstore import count, get_docs, get_embeddings, get_meta


@dataclass
class Runtime:
    meta: Chroma
    docs: Chroma
    llm: ChatOpenAI
    graph: object
    overrides: dict = field(default_factory=dict)   # 평가 · 비교 실험에서 settings.json 값을 잠시 바꿀 때

    @property
    def settings(self) -> dict:
        # 매번 다시 읽는다 — settings.json 을 바꾸면 앱을 껐다 켜지 않아도 반영 (검증 실험용)
        return load_settings(**self.overrides)

    def meta_count(self) -> int:
        return count(self.meta)

    def docs_count(self, item_id: str | None = None) -> int:
        return count(self.docs, {"item_id": item_id} if item_id else None)

    def collected_titles(self, item_id: str) -> list[str]:
        """이 항목에 수집된 외부 문서 제목 (화면 왼쪽 표시용)."""
        return [d["title"] for d in self.collected_docs(item_id)]

    def collected_docs(self, item_id: str) -> list[dict]:
        """이 항목에 수집된 외부 문서 — 제목과 출처 종류 (문서 단위로 한 번씩)."""
        result = self.docs.get(where={"item_id": item_id}, include=["metadatas"])
        docs = {}
        for meta in result["metadatas"]:
            docs.setdefault(meta["doc_id"], {"title": meta["title"], "type": meta["source_type"]})
        return list(docs.values())


def ensure_meta_index(meta: Chroma) -> int:
    """law_meta 가 비었거나 items.json 보다 적으면 바로 색인한다 (scripts/build_index.py 와 같은 내용).

    배포 서버(Streamlit Community Cloud 등)에는 vectorstore/ 가 없다 — 저장소에 올리지 않으므로.
    처음 켜질 때 한 번 법률 276건을 임베딩한다 (수 초). 법률 목록을 늘린 뒤에도 같은 길로 채워진다.
    외부 문서(law_docs)는 질문할 때 모은다.
    """
    from prep.item_text import build_item_text, item_metadata, load_items
    items = load_items()
    if count(meta) < len(items):
        from langchain_core.documents import Document
        from store.vectorstore import upsert
        upsert(meta, [Document(page_content=build_item_text(i), metadata=item_metadata(i)) for i in items],
               [i["item_id"] for i in items])
    return count(meta)


def build_runtime(auto_index: bool = True) -> Runtime:
    """GMS_KEY 가 없으면 MissingKeyError — 화면에서 안내로 바꾼다. 색인이 비어 있으면 먼저 만든다."""
    embeddings = get_embeddings()
    meta, docs = get_meta(embeddings), get_docs(embeddings)
    if auto_index:
        ensure_meta_index(meta)
    llm = get_chat_model()
    return Runtime(meta=meta, docs=docs, llm=llm, graph=build_graph(meta, docs, llm))
