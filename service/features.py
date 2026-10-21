"""도메인 특화 기능 (F2010) — 둘 다 색인된 문서만 근거로 쓰고 근거를 함께 돌려줍니다.

    ① 법률 상식 팩트체크  "전입신고 당일부터 대항력이 생긴다" → 사실 / 사실 아님 / 확인 불가
    ② 조문 쉬운 말 풀이   조문 하나를 골라 쉬운 말 + 용어 풀이 + 원문
"""

import re
import time

from prep.collect import article_doc, get_law_articles, today
from service.chat import Result, ask, index_documents, run_graph
from service.runtime import Runtime
from store.chunking import chunk_documents


def parse_verdict(answer: str) -> str:
    """첫 줄의 '판정: 사실 / 사실 아님 / 확인 불가'. 정규식은 '사실 아님'을 '사실'보다 먼저 본다."""
    match = re.search(r"판정\s*[:：]\s*(사실 아님|사실|확인 불가)", answer)
    return match.group(1) if match else "확인 불가"


def factcheck(rt: Runtime, item: dict, claim: str, on_step=lambda m: None) -> tuple[str, Result]:
    result = ask(rt, item, claim, history=[], mode="factcheck", on_step=on_step)
    verdict = parse_verdict(result.answer) if result.cited else "확인 불가"
    return verdict, result


def article_choices(item: dict) -> list[dict]:
    """조문 풀이에서 고를 수 있는 조문 (법률 + 시행령)."""
    return [a for a in get_law_articles(item) if a["title"]]


def explain(rt: Runtime, item: dict, article: dict, on_step=lambda m: None) -> Result:
    """고른 조문을 색인하고(이미 있으면 덮어쓰기), 그 조문을 반드시 근거에 넣어 풀이한다."""
    started = time.perf_counter()
    on_step(f"{article['source']} {article['article']} 원문을 가져오는 중")
    raw = article_doc(item, article, "조문 풀이")
    index_documents(rt, [raw])
    _, ids = chunk_documents([raw], rt.settings, today())

    on_step("쉬운 말로 풀어 쓰는 중")
    question = f"{raw['title']}을(를) 쉬운 말로 풀어 주세요."
    result = run_graph(rt, item, question, history=[], mode="explain", pinned_ids=ids)
    result.elapsed = time.perf_counter() - started
    return result
