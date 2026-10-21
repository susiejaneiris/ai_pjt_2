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


def build_runtime() -> Runtime:
    """GMS_KEY 가 없으면 MissingKeyError — 화면에서 안내로 바꾼다."""
    embeddings = get_embeddings()
    meta, docs = get_meta(embeddings), get_docs(embeddings)
    llm = get_chat_model()
    return Runtime(meta=meta, docs=docs, llm=llm, graph=build_graph(meta, docs, llm))
