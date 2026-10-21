"""청킹 (F2005 · F2016). 청크 크기와 중복 길이는 settings.json 에서 읽습니다.

수집 단계가 출처별로 '문서 단위'를 먼저 정해 넘겨 줍니다.
    조문   조 1개 = 문서 1개     → 근거 1개 = 조문 1개로 인용할 수 있게
    판례   판시사항 · 판결요지 각각  → 성격이 다른 두 부분이 한 청크에 섞이지 않게
    위키   문서 전체               → 서술형이라 글자 수 기준 분할이 맞다
여기서는 그 문서를 같은 splitter 로 자르고, 청크마다 출처 헤더를 붙입니다.
헤더가 없으면 "제3조" 본문만으로는 어느 법인지 몰라 검색이 흔들립니다.
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 수집 단계가 넘겨 주는 문서(raw doc)의 필드
#   item_id, item_name, doc_id, source_type(article|prec|expc|wiki), title, header, url, date, query, text
#   citation — 원문 출처를 사람이 읽는 형태로. URL 이 없는 PDF 는 "파일명과 쪽" (명세 F2004)


def make_splitter(settings: dict) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings["chunk_size"],
        chunk_overlap=settings["chunk_overlap"],
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def chunk_documents(raw_docs: list[dict], settings: dict, collected_at: str) -> tuple[list[Document], list[str]]:
    """문서 목록 → (청크, 청크 id). id 는 '항목 ID:문서 ID:순번' — 여러 항목이 같은 문서를 모아도 덮어쓰지 않는다."""
    splitter = make_splitter(settings)
    docs, ids = [], []
    for raw in raw_docs:
        for seq, piece in enumerate(splitter.split_text(raw["text"])):
            docs.append(Document(
                page_content=f"[{raw['header']}]\n{piece}",
                metadata={
                    "item_id": raw["item_id"],
                    "item_name": raw["item_name"],
                    "doc_id": raw["doc_id"],
                    "source_type": raw["source_type"],
                    "title": raw["title"],
                    "url": raw["url"],
                    "citation": raw.get("citation") or raw["url"],
                    "date": raw.get("date", ""),
                    "query": raw.get("query", ""),
                    "chunk_seq": seq,
                    "collected_at": collected_at,
                },
            ))
            ids.append(f"{raw['item_id']}:{raw['doc_id']}:{seq}")
    return docs, ids
