"""법령용어 → 관련 조문 (검색 개선 5). 국가법령정보센터 Open API — 법령 API 키(LAW_OC) 그대로, 새 승인 불필요.

    프롬프트 1 검색어("대항력 보호", "해약금")
        └ 낱말마다 법령용어 사전(target=lstrmAI)에서 이름이 정확히 같은 용어를 찾는다
            └ 그 용어의 조문 관계(target=lstrmRltJo) — 법제처가 정리한 "이 용어가 핵심인 조문"
                └ 고른 법률의 조문만 → 근거에 고정 (프롬프트 1 의 조문 지목과 합친다)

왜 — 남은 실패는 일상어 질문과 조문의 의미 거리가 먼 경우였다. 프롬프트 1 은 일상어를 법률 용어로는 잘 바꾸지만
("전입신고 당일" → "대항력"), 그 용어가 어느 조문에 있는지는 벡터 검색이 놓칠 때가 있다.
용어 ↔ 조문 관계는 LLM 판단이 아니라 법제처 자료라, 조문 지목(LLM)이 틀릴 때 보완이 된다.

호출 결과는 용어별로 data/term_links.json 에 저장해 같은 용어는 다시 부르지 않는다 (NF2002).
"""

import json
import re

from config import DATA_DIR
from prep.law_api import SEARCH_URL, SERVICE_URL, as_list, request_law

TERM_LINKS_JSON = DATA_DIR / "term_links.json"
MAX_TERMS = 8                 # 질문 하나에 찾아볼 용어 수 (호출 수 · 시간)
MST = re.compile(r"MST=(\d+)")


def load_links() -> dict:
    if TERM_LINKS_JSON.exists():
        return json.loads(TERM_LINKS_JSON.read_text(encoding="utf-8"))
    return {}


def save_links(links: dict) -> None:
    TERM_LINKS_JSON.write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")


def article_label(number: str, branch: str) -> str:
    """조번호 "0003" + 조가지번호 "02" → "제3조의2"."""
    label = f"제{int(number)}조"
    return label + (f"의{int(branch)}" if branch and int(branch) else "")


def unwrap(data) -> dict:
    """응답이 {"lstrmAISearch": {...}} 처럼 한 겹 감싸져 온다 → 안쪽 dict."""
    if isinstance(data, dict) and len(data) == 1:
        inner = next(iter(data.values()))
        if isinstance(inner, dict):
            return inner
    return data if isinstance(data, dict) else {}


def fetch_term(term: str) -> list[list[str]]:
    """용어 하나 → [[법령명, 조문], ...]. 사전에 이름이 정확히 같은 용어가 없으면 빈 목록."""
    data = unwrap(request_law(SEARCH_URL, {"target": "lstrmAI", "query": term, "display": 10}))
    entries = as_list(data.get("법령용어"))
    links = []
    for entry in entries:
        if entry.get("법령용어명", "").replace(" ", "") != term.replace(" ", ""):
            continue
        found = MST.search(entry.get("조문간관계링크", ""))
        if not found:
            continue
        body = unwrap(request_law(SERVICE_URL, {"target": "lstrmRltJo", "MST": found.group(1)}))
        term_entry = body.get("법령용어", {})
        for law in as_list(term_entry.get("연계법령") if isinstance(term_entry, dict) else None):
            if law.get("법령명") and law.get("조번호", "").isdigit():
                links.append([law["법령명"], article_label(law["조번호"], law.get("조가지번호", "0"))])
    return links


def candidate_terms(queries: list[str]) -> list[str]:
    """검색어 통째로 + 검색어 속 낱말(2글자 이상) — 앞에 나온 것부터 MAX_TERMS 개."""
    terms = []
    for query in queries:
        for term in [query.replace(" ", "")] + re.findall(r"[가-힣]{2,}", query):
            if term not in terms:
                terms.append(term)
    return terms[:MAX_TERMS]


def linked_articles(item: dict, queries: list[str], limit: int = 3) -> list[str]:
    """검색어의 법령용어와 연결된, 고른 법률의 조문 번호. 법령 API 가 막히면 그때까지 찾은 것만."""
    links = load_links()
    changed, picked = False, []
    start, end = map(int, item["article_range"].split("-")) if item.get("article_range") else (0, 10 ** 6)
    try:
        for term in candidate_terms(queries):
            if term not in links:
                links[term] = fetch_term(term)
                changed = True
            for law_name, label in links[term]:
                number = int(re.match(r"제(\d+)", label).group(1))
                if law_name.replace(" ", "") == item["name"].replace(" ", "") and start <= number <= end \
                        and label not in picked:
                    picked.append(label)
    except Exception:            # 법령 API 오류 — 용어 연결 없이 진행 (검색 · 조문 지목은 그대로)
        pass
    if changed:
        save_links(links)
    return picked[:limit]
