"""AI(GMS) 사용 한도가 끝났을 때 — 한도 초과 판별과 '원문 보여 주기' (F2012).

GMS 키 하나로 답변 모델과 임베딩을 같이 쓰므로, 한도가 끝나면 벡터 검색도 멈춘다.
그래서 API 없이 할 수 있는 것만 한다.
    - 이미 색인해 둔 이 법률의 문서(조문 · 판례 · 생활법령 Q&A …)를 저장소에서 꺼내
      질문과 글자 2개씩 겹치는 정도(bigram)로 순서를 매긴다 — 임베딩 호출 없음
    - 색인한 문서가 없으면 법령 API 로 조문을 받아 같은 방식으로 (법령 API 는 GMS 키와 무관)
    - 요약 · 풀이는 하지 않는다. 원문과 출처만 보여 줘서 지어낸 말이 섞일 여지를 없앤다
"""

import logging
import math
import re
import time
from collections import Counter

from openai import APIStatusError, RateLimitError

from prep.collect import article_doc, get_law_articles
from prep.disclaimer import notices_for
from rag.retriever import SOURCE_LABELS
from service.chat import Result, ask
from service.runtime import Runtime

log = logging.getLogger(__name__)

QUOTA_MESSAGE = ("오늘 쓸 수 있는 AI 사용량(GMS 토큰)이 모두 끝났어요. "
                 "한도가 다시 채워지면 평소처럼 답해 드릴게요.")
OFFLINE_ANSWER = ("🔋 **지금은 AI 사용 한도가 끝나 답변을 만들 수 없어요.**\n\n"
                  "대신 질문과 관련 있어 보이는 **원문을 그대로** 보여 드려요. "
                  "로우가 풀어 쓴 것이 아니라 글자가 겹치는 순서로 고른 것이라, "
                  "내 상황에 맞는 내용인지는 원문을 직접 읽고 확인해 주세요.")
OFFLINE_EMPTY = ("🔋 **지금은 AI 사용 한도가 끝나 답변을 만들 수 없어요.**\n\n"
                 "이 법률에서 질문과 겹치는 원문도 찾지 못했어요. 한도가 다시 채워진 뒤 물어봐 주세요.")
QUOTA_STATUS = {402, 403, 429}
# 답변 프롬프트의 신뢰 순서와 같게 — 조문 > 생활법령 Q&A · 법령해석례 > 판례 > 위키 (위키는 길어서 글자 겹침만으로는 늘 위로 온다)
TYPE_WEIGHT = {"article": 1.0, "qa": 0.9, "expc": 0.8, "prec": 0.7, "wiki": 0.35, "meta": 0.3}
QUOTA_WORDS = ("quota", "rate limit", "insufficient", "exceeded", "billing", "credit", "한도", "초과", "소진")


def is_quota_error(error: BaseException | None) -> bool:
    """한도 초과(토큰 소진 · 요청 제한)인지. LangChain 이 감싼 예외도 원인까지 따라가 본다."""
    seen = 0
    while error is not None and seen < 5:
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIStatusError) and (
                error.status_code in QUOTA_STATUS or any(w in str(error).lower() for w in QUOTA_WORDS)):
            return True
        error, seen = error.__cause__ or error.__context__, seen + 1
    return False


def stored_documents(rt: Runtime, item: dict) -> list[dict]:
    """이 법률에 이미 색인한 청크 — 저장소에서 꺼내기만 한다 (임베딩 호출 없음)."""
    got = rt.docs.get(where={"item_id": item["item_id"]}, include=["documents", "metadatas"])
    return [{"text": text, **meta, "chunk_id": chunk_id}
            for text, meta, chunk_id in zip(got["documents"], got["metadatas"], got["ids"])]


def law_api_documents(item: dict) -> list[dict]:
    """색인한 문서가 없을 때 — 법령 API 로 받은 이 법률의 조문 (GMS 키를 쓰지 않는다)."""
    try:
        return [{**article_doc(item, a, "원문 보기"), "chunk_id": ""}
                for a in get_law_articles(item) if a["source"] == item["name"]]
    except Exception:                    # 법령 API 까지 막힌 환경 — 보여 줄 원문이 없다
        log.exception("law_api_documents")
        return []


def word_grams(text: str) -> set[str]:
    """낱말 안에서만 두 글자씩 — 띄어쓰기를 지우고 자르면 "는데 · 받아 · 아요" 같은 조각이 아무 문서에나 걸린다."""
    grams = set()
    for word in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        grams |= {word[i:i + 2] for i in range(len(word) - 1)}
    return grams


def offline_sources(rt: Runtime, item: dict, question: str, limit: int = 5) -> list[dict]:
    """질문과 겹치는 글자 조각이 많은 원문 순으로 — 여러 문서에 흔한 조각일수록 낮게 친다(IDF).
    같은 문서의 청크는 하나만. 일상어와 법률 용어가 다르면("월급" ↔ "임금") 못 찾는 한계가 있다."""
    docs = stored_documents(rt, item) or law_api_documents(item)
    query = word_grams(question)
    doc_grams = [word_grams(d.get("title", "") + " " + d["text"]) for d in docs]
    df = Counter(g for grams in doc_grams for g in grams & query)
    idf = {g: math.log((len(docs) + 1) / (n + 0.5)) for g, n in df.items()}

    title_grams = [word_grams(d.get("title", "")) for d in docs]

    def score(n: int) -> float:
        body = sum(idf[g] for g in doc_grams[n] & query) / math.log(len(doc_grams[n]) + 10)
        title = sum(idf[g] for g in title_grams[n] & query)              # 조문 제목에 맞으면 더 친다
        return (body + 0.3 * title) * TYPE_WEIGHT.get(docs[n].get("source_type", ""), 0.5)

    picked, seen = [], set()
    for n in sorted(range(len(docs)), key=score, reverse=True):
        doc = docs[n]
        key = doc.get("doc_id") or doc["chunk_id"]
        if key in seen or score(n) <= 0:
            continue
        seen.add(key)
        picked.append(doc)
        if len(picked) == limit:
            break
    return [{
        "n": n, "type": d.get("source_type", ""), "type_label": SOURCE_LABELS.get(d.get("source_type", ""), ""),
        "title": d.get("title", ""), "url": d.get("url", ""), "citation": d.get("citation") or d.get("url", ""),
        "date": d.get("date", ""), "text": d["text"], "chunk_id": d["chunk_id"],
    } for n, d in enumerate(picked, start=1)]


def answer_offline(rt: Runtime, item: dict, question: str) -> Result:
    started = time.perf_counter()
    sources = offline_sources(rt, item, question)
    return Result(answer=OFFLINE_ANSWER if sources else OFFLINE_EMPTY, sources=sources, cited=sources,
                  notices=notices_for(item), offline=True, elapsed=time.perf_counter() - started)


def ask_or_offline(rt: Runtime, item: dict, question: str, history: list[dict],
                   on_step=lambda m: None) -> Result:
    """평소에는 ask(). AI 사용 한도가 끝났으면 원문 보여 주기로 바꾼다 (다른 오류는 그대로 올린다)."""
    try:
        return ask(rt, item, question, history, on_step=on_step)
    except Exception as error:
        if not is_quota_error(error):
            raise
        log.warning("AI 사용 한도 초과 — 원문 보여 주기로 전환")
        on_step("AI 사용 한도가 끝나 관련 원문을 찾는 중")
        return answer_offline(rt, item, question)
